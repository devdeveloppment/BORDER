# syntax=docker/dockerfile:1
# Reverse proxy RBI (P2.10, ADR 0012) : point d'entrée unique, frontend et API sur la même origine.
# La configuration est générée au démarrage par 40-rbi-site.sh selon RBI_FRONTEND_UPSTREAM et RBI_TLS.
FROM nginx:1.30.4-alpine
RUN rm -f /etc/nginx/conf.d/default.conf
COPY rbi/ /etc/nginx/rbi/
COPY --chmod=0755 40-rbi-site.sh /docker-entrypoint.d/40-rbi-site.sh
