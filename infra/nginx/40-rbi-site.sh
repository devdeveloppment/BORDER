#!/bin/sh
# Génère la configuration Nginx de RBI selon l'environnement (P2.10, ADR 0012). Échec sûr : toute valeur
# inattendue ou tout certificat manquant arrête le conteneur au lieu de servir une configuration dégradée.
#
#   RBI_FRONTEND_UPSTREAM  vite (développement, rechargement à chaud) | static (frontend construit, /srv/frontend)
#   RBI_TLS                off (HTTP local) | on (HTTPS ; /etc/nginx/tls/{cert,key}.pem requis)
#   RBI_SERVER_NAMES       noms acceptés (autre Host : connexion fermée, protection contre le DNS rebinding)
#   RBI_HTTPS_PUBLIC_PORT  port HTTPS vu du navigateur (redirection HTTP → HTTPS)
set -eu

fail() { echo "rbi-nginx: $*" >&2; exit 1; }

UPSTREAM="${RBI_FRONTEND_UPSTREAM:-vite}"
TLS="${RBI_TLS:-off}"
NAMES="${RBI_SERVER_NAMES:-localhost 127.0.0.1}"
HTTPS_PORT="${RBI_HTTPS_PUBLIC_PORT:-443}"

case "$UPSTREAM" in vite|static) ;; *) fail "RBI_FRONTEND_UPSTREAM invalide : $UPSTREAM" ;; esac
case "$TLS" in on|off) ;; *) fail "RBI_TLS invalide : $TLS" ;; esac
case "$HTTPS_PORT" in ''|*[!0-9]*) fail "RBI_HTTPS_PUBLIC_PORT invalide : $HTTPS_PORT" ;; esac
echo "$NAMES" | grep -Eq '^[A-Za-z0-9. -]+$' || fail "RBI_SERVER_NAMES invalide"
[ "$UPSTREAM" = static ] && [ ! -f /srv/frontend/index.html ] && fail "frontend construit absent (/srv/frontend/index.html)"

RUN=/etc/nginx/rbi-run
mkdir -p "$RUN"
cp "/etc/nginx/rbi/csp-$UPSTREAM.conf" "$RUN/csp.conf"
cp "/etc/nginx/rbi/frontend-$UPSTREAM.conf" "$RUN/frontend.conf"

if [ "$UPSTREAM" = vite ]; then
    FRONTEND_UPSTREAM="upstream frontend_upstream { server frontend:5173; }"
else
    FRONTEND_UPSTREAM=""
fi

SITE="
    server_name $NAMES;
    include /etc/nginx/rbi/proxy-api.conf;
    include $RUN/frontend.conf;"

{
    cat <<CONF
# Généré par 40-rbi-site.sh — ne pas modifier (frontend : $UPSTREAM, TLS : $TLS).
server_tokens off;
client_max_body_size 64k;
map \$http_upgrade \$connection_upgrade { default upgrade; '' close; }
upstream api_upstream { server api:8000; keepalive 8; }
$FRONTEND_UPSTREAM

# Sonde de santé du conteneur : interface locale du conteneur uniquement (port non publié).
server {
    listen 127.0.0.1:81;
    access_log off;
    location = /health { default_type text/plain; return 200 "ok"; }
    location / { return 404; }
}

# Hôte inconnu : connexion fermée sans réponse.
server {
    listen 80 default_server;
    return 444;
}
CONF
    if [ "$TLS" = off ]; then
        cp /etc/nginx/rbi/transport-http.conf "$RUN/transport.conf"
        cat <<CONF
server {
    listen 80;$SITE
}
CONF
    else
        [ -f /etc/nginx/tls/cert.pem ] && [ -f /etc/nginx/tls/key.pem ] || fail "RBI_TLS=on sans /etc/nginx/tls/cert.pem et key.pem"
        cp /etc/nginx/rbi/transport-tls.conf "$RUN/transport.conf"
        cat <<CONF
# HTTP : redirection permanente vers HTTPS, aucun contenu, aucun HSTS.
server {
    listen 80;
    server_name $NAMES;
    location / { return 301 https://\$host:$HTTPS_PORT\$request_uri; }
}
server {
    listen 443 ssl default_server;
    ssl_certificate /etc/nginx/tls/cert.pem;
    ssl_certificate_key /etc/nginx/tls/key.pem;
    return 444;
}
server {
    listen 443 ssl;
    http2 on;
    ssl_certificate /etc/nginx/tls/cert.pem;
    ssl_certificate_key /etc/nginx/tls/key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_tickets off;$SITE
}
CONF
    fi
} > /etc/nginx/conf.d/default.conf

nginx -t
