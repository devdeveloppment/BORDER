# ADR 0012 — Intégration frontend ↔ backend, reverse proxy et proxy de confiance (P2.10)

- **Statut** : acceptée (validation humaine de la clôture de P2.10 accordée ; contre-épreuves CP-01 à CP-04
  concluantes, voir [rapport P2.10 §5 bis](../phases/phase-2/P2.10-RAPPORT.md)). Cette acceptation ne vaut pas
  autorisation de déploiement en production et ne clôt aucun risque résiduel de la revue de sécurité interne.
- **Date** : 12/10/2026
- **Source** : feuille de route P2 (P2.10 « Intégration frontend ↔ backend ») ; ADR 0003 §1 (« Nginx et conteneur
  frontend : P2.10, intégration ») ; décisions D1 à D8 approuvées par le propriétaire (12/10/2026) ; spécification interne non publiée §11.5, §12, §19.1 (HTTPS, HSTS, CSP stricte, cookies), §25 ; ADR 0007, 0010

## Contexte

Le frontend P1 fonctionnait entièrement sur MSW ; l'API v1 (P2.8) est livrée pour l'authentification, les comptes,
l'organisme, le journal d'audit, la plateforme et la demande d'accès. La session HttpOnly SameSite=Strict et le
contrôle CSRF par origine exigent que le navigateur atteigne le frontend et l'API par la **même origine**.
L'adresse cliente (limitation de débit, audit) devait être lue derrière un proxy sans faire confiance à un en-tête
fourni par le client.

## Décisions

### 1. Topologie : Nginx, point d'entrée unique (D1, D8)

`Navigateur → Nginx (127.0.0.1:8080) → frontend (/) | API Django (/api/)`.

- Image `rbi-proxy` (nginx 1.30.4-alpine) ; configuration générée au démarrage par `40-rbi-site.sh` selon
  `RBI_FRONTEND_UPSTREAM` (`vite` | `static`) et `RBI_TLS` (`off` | `on`). Échec sûr : valeur inconnue, frontend
  construit absent ou certificat manquant → le conteneur ne démarre pas.
- Seuls Nginx (8080) et l'interface Mailpit (8025, liens de réinitialisation en local) sont publiés. Les ports
  directs (API 8000, PostgreSQL 5433, Redis 6379, S3 8333, SMTP 1025) passent dans `infra/compose.host-ports.yml`,
  à activer explicitement pour le débogage. Les tests n'en dépendent pas (noms de service internes).
- `Host` inconnu : connexion fermée sans réponse (`444`), y compris en TLS (protection contre le DNS rebinding,
  qui vise notamment un serveur de développement).
- `/api/` : `Host` transmis (contrôle ALLOWED_HOSTS et d'origine CSRF), délais bornés (5 s connexion, 60 s
  lecture), corps ≤ 64 Kio comme l'API, erreurs 413 et 502/503/504 de Nginx au format RFC 9457.

### 2. Proxy de confiance et adresse cliente (D1)

Politique unique (`apps.core.client_ip`), utilisée par l'authentification (verrouillages), DRF (classes de
limitation `apps.core.api.throttling`, `NUM_PROXIES = 0` conservé) et le journal d'audit :

1. sans proxy déclaré (`RBI_TRUSTED_PROXIES` vide), adresse = pair TCP ;
2. `X-Forwarded-For` lu **seulement** si le pair TCP est un proxy déclaré ; entrée la plus à droite non déclarée ;
3. derrière un proxy déclaré, en-tête absent ou illisible → adresse du proxy et avertissement (jamais une valeur
   invérifiable) ;
4. configuration vérifiée au démarrage : entrée illisible ou réseau plus large que /16 (IPv4) ou /48 (IPv6),
   dont `0.0.0.0/0`, → `ImproperlyConfigured`.

`TrustedProxyMiddleware` (premier middleware) **supprime** `X-Forwarded-For`, `X-Forwarded-Proto`,
`X-Forwarded-Host` et `Forwarded` reçus d'un autre pair : Django ne peut pas croire à tort qu'une requête est en
HTTPS (`SECURE_PROXY_SSL_HEADER`, défini seulement si un proxy est déclaré). Nginx **remplace** ces en-têtes
(`X-Forwarded-For $remote_addr`) et vide `X-Real-IP`, `Forwarded`, `X-Forwarded-Host` et `X-Request-ID`.

Nginx a une adresse **fixe** sur le réseau `edge` (`172.29.89.2`, hors de la plage d'attribution automatique
`.8–.15`) ; c'est la seule déclarée (`/32`). Le frontend de développement n'est que sur `edge` : il n'atteint ni la
base ni Redis. Le contexte d'organisme ne dépend toujours d'aucun en-tête (P2.3, P2.6).

### 3. HTTP local, TLS activable (D2)

- Développement : HTTP sur 127.0.0.1:8080, sans HSTS ; cookies non `Secure` (`RBI_HTTPS=false`).
- `RBI_TLS=on` : TLS 1.2 et 1.3 uniquement, redirection 301 HTTP → HTTPS (port public `RBI_HTTPS_PUBLIC_PORT`),
  HSTS (1 an, sous-domaines) sur les seules réponses HTTPS, tickets de session désactivés, `server_tokens off`.
  `RBI_HTTPS=true` côté API : cookies de session et CSRF `Secure`.
- Certificat : monté depuis `/etc/nginx/tls` ; aucun certificat ni clé n'est versionné. La configuration TLS est
  vérifiée dans l'environnement E2E avec un certificat autosigné généré pour l'exécution. **Non validée en
  production** (certificat réel, chaîne, OCSP, préchargement HSTS : déploiement).

### 4. CSP stricte, nonce par requête

`default-src 'self'; script-src 'self' 'nonce-…'; style-src 'self' 'nonce-…'; img-src 'self'; font-src 'self';
connect-src 'self'; worker-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors
'none'`, plus `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, COOP, CORP et
`Permissions-Policy`. Le nonce est `$request_id` de Nginx (128 bits, renouvelé à chaque réponse), substitué au
marqueur `RBI_CSP_NONCE` que Vite place sur ses balises (`html.cspNonce`). Aucune directive `unsafe-inline` ou
`unsafe-eval` : ni ECharts, ni Radix (à condition que le nonce lui soit transmis, voir ci-dessous), ni le rechargement à
chaud de Vite n'en ont eu besoin. Même politique en développement (Vite) et pour le frontend construit ; la configuration de développement n'est pas une configuration de production.

Une violation réelle a été trouvée par le parcours E2E et corrigée : les feuilles de style créées à
l'exécution par la bibliothèque de verrouillage du défilement des fenêtres modales (Radix) n'avaient pas le
nonce de la page et étaient bloquées (`style-src`). Le nonce, lu sur le script de l'application, est transmis à
la bibliothèque (`__webpack_nonce__`, `src/main.tsx`) ; la politique reste inchangée. Les styles appliqués par
React à ses éléments passent par l'API CSSOM et ne sont pas concernés. Les attributs `style` écrits en HTML
restent interdits par la politique.

### 5. Frontend de développement en conteneur (D3)

Image `rbi-frontend-dev` (node 24.19.0-alpine, utilisateur `node`) : `npm ci` puis Vite ; sources montées,
`node_modules` dans un volume du conteneur (dépendances Linux) ; surveillance par interrogation (sources
Windows) ; WebSocket du rechargement à chaud sur la même origine (port du proxy). Développement uniquement.

### 6. Trois modes de l'API côté frontend (D5)

| Mode | `VITE_API_MOCKS` | Comportement |
|---|---|---|
| tout simulé | `true` (défaut hors production) | maquette P1 : MSW sert toutes les routes ; les actions réelles non simulées répondent « Action non simulée » (501) |
| intégré | `deferred` | API réelle ; MSW pour les seuls modules métier reportés (`DEFERRED_PATH_PREFIXES`) ; mention « Données simulées — module non encore implémenté » sur leurs écrans ; leurs données sont générées avec l'identité et les permissions réelles (`/me`) |
| production | (ignoré) | `VITE_APP_ENV=production` : mode `live` imposé à la construction ; code des mocks, comptes fictifs et `mockServiceWorker.js` absents du bundle (contrôle positif et négatif dans `src/test/modes.test.ts`) |

En mode intégré, un mock sans contexte répond 403 (jamais 401, qui fermerait la session réelle). Un test vérifie
que chaque appel du frontend vise une opération du schéma OpenAPI versionné ou un module reporté, et qu'aucun
module reporté n'existe dans l'API réelle (MSW ne masque jamais une route réelle).

### 7. Permissions et session

- Le frontend lit les permissions **effectives** de `GET /me` ; une liste absente ou mal formée ne donne aucune
  permission. La matrice rôles → permissions ne subsiste que dans les mocks (`src/mocks/roles.ts`), alignée sur le
  catalogue du backend, importée par aucun module applicatif (testé). Le backend reste seul juge.
- Toute réponse 401 ramène la session à « anonyme » (déconnexion côté serveur, suspension de l'organisme,
  inactivité) ; un backend injoignable affiche un état d'erreur, sans redirection trompeuse vers la connexion.
- CSRF : jeton obtenu par `GET /auth/csrf` avant la première écriture, renvoyé en `X-CSRFToken`.

### 8. Secrets d'authentification dans l'interface (D4)

QR code dessiné localement en SVG par `qrcode.react` 4.2.0 (licence ISC, aucune dépendance, aucun appel réseau,
compatible CSP). Secret TOTP, URI et codes de secours : état de l'écran uniquement (jamais l'URL, le stockage du
navigateur, les journaux ni le cache des mutations, `gcTime: 0`), clé de saisie manuelle masquée par défaut,
codes de secours affichés une fois avec confirmation de conservation. Jeton de réinitialisation retiré de l'URL
dès sa lecture. Point d'attention : `qrcode.react` n'a pas publié de version depuis 12/2024 (fonction stable,
à surveiller).

### 9. Envoi des e-mails et environnement E2E (D6)

`RBI_FRONTEND_URL` (liens des e-mails) vaut l'origine de Nginx. Tests E2E : `scripts/e2e.py` crée le projet Docker
jetable `rbi-e2e` (ports 18080/18443/18025, sous-réseau distinct, secrets générés hors du dépôt), construit le
frontend en mode intégré, crée le Super Administrateur par la commande serveur, exécute Playwright
(`playwright.integrated.config.ts`), bascule en TLS et vérifie redirection, HSTS, versions TLS et cookies `Secure`,
puis détruit l'environnement **après** avoir prouvé que chaque volume visé appartient au projet E2E ; les volumes
de développement sont comparés avant et après. `seed_demo` reste à faire (début de P2.11).

## Conséquences

- Accès local : `http://127.0.0.1:8080` (frontend et API). L'API n'est plus publiée directement.
- Aucune migration, aucun privilège ajouté à `rbi_app`, aucun changement du contrat de l'API.
- Le frontend P1 est modifié dans les limites approuvées (D7) ; les tests P1 en mode simulé restent valides.

## Limites

1. TLS testé localement avec un certificat autosigné ; aucune validation en production.
2. Une seule instance de proxy déclarée ; plusieurs niveaux de proxys (répartiteur de charge en amont) exigeront
   de déclarer chaque niveau et de revoir la configuration de Nginx (`real_ip`).
3. Les risques résiduels de la revue de sécurité interne restent ouverts ; ce proxy local ne remplace ni un test d'intrusion
   indépendant ni la validation d'un déploiement réel ; aucun test de charge.
