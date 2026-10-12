# Backend RBI

Monolithe Django modulaire. État d'avancement des sous-phases : [suivi de la phase 2](../docs/phases/phase-2/README.md).
Décisions : [ADR](../docs/adr/).

## Structure

```
backend/
├─ config/            settings (base, development, test), urls, celery, env (lecture typée de l'environnement)
├─ apps/              16 applications du §12.2 (core, health, users… ; la plupart encore vides)
│  └─ <app>/          models.py · services.py · selectors.py · api/ · tasks.py · tests/  (dès qu'elle a du code)
├─ tests/
│  ├─ infra/          P2.1 : services Docker réels (rôles PostgreSQL, RLS, Redis, S3, Mailpit)
│  ├─ foundation/     P2.2 : réglages, base, PostGIS, migrations, Redis/Celery, conteneurs en marche
│  └─ gisprobe/       application de test (modèle géographique), installée uniquement par settings.test
├─ manage.py
├─ pyproject.toml / uv.lock
└─ Dockerfile
```

## Commandes (depuis la racine du dépôt)

```bash
docker compose up -d --wait                                       # infra + migrate + api + worker + frontend + proxy
curl http://127.0.0.1:8080/api/v1/health/ready                    # par Nginx (point d'entrée unique, P2.10)
docker compose --profile tools run --rm backend pytest            # toute la suite
docker compose --profile tools run --rm backend pytest -m infra   # tests P2.1 seuls
docker compose --profile tools run --rm backend ruff check .
docker compose --profile tools run --rm backend ruff format --check .
docker compose --profile tools run --rm backend mypy .
docker compose run --rm migrate                                   # réappliquer les migrations
docker compose --profile tools run --rm backend python manage.py makemigrations <app>
docker compose --profile tools build backend                      # après modification de uv.lock
```

Le code est monté dans les conteneurs (`./backend:/app`) : l'API se recharge seule. Après l'ajout d'une migration,
relancer `docker compose run --rm migrate`.

## Multi-tenant : règles pour tout nouveau code

- Toute donnée d'un organisme hérite de `apps.organizations.models.TenantScopedModel` ; `organization` en tête des index.
- Lire et écrire **uniquement** dans un `tenant_context(...)` obtenu par `context_for_user` (requêtes) ou `@tenant_task`
  (tâches, avec `organization_id=` explicite). Sans contexte, `Model.objects` lève `TenantContextMissing`.
- Ne jamais lire un `organization_id` envoyé par le client ; ne jamais utiliser `_base_manager` dans le code applicatif.
- Opérations globales : uniquement via `platform_scope(...)` ; les services globaux commencent par `require_scope(scope)`.
- Événements sensibles : `apps.audit.services.record_event(...)` (journal append-only, voir plus bas).

## RBAC : règles pour tout nouveau code

- Chaque action protégée commence par `require_permission(user, "<module.action>", context)` (`apps.users.rbac`) ;
  le `context` est celui déterminé côté serveur. Refus par défaut : code inconnu, sans contexte, autre organisme.
- Nouvelle permission ou évolution d'un rôle par défaut : modifier `apps/users/catalog.py` (source de vérité),
  puis `docker compose run --rm migrate` (synchronisation automatique) ; la matrice attendue des tests est à mettre à jour.
- Rôles : uniquement via `apps.users.services` (jamais `UserRole.objects.create` dans le code applicatif).
- Premier Super Administrateur : `docker compose run --rm migrate python manage.py create_super_admin --email …`.

## Authentification (P2.5)

- Routes : `GET /api/v1/auth/csrf` (cookie `csrftoken`), `POST /api/v1/auth/login` → `{step}`
  (`AUTHENTICATED`, `MFA_REQUIRED`, `MFA_ENROLLMENT_REQUIRED`), `/auth/mfa/enroll`, `/auth/mfa/verify`, `/auth/logout`,
  `/auth/password-reset` (+ `/confirm`), `GET /api/v1/me` ; voir ADR 0007 pour la liste complète.
- Toute vue exige une session complète (MFA comprise) sauf si elle est décorée `@public_endpoint`
  (`apps.core.http`) : ne l'ajouter qu'avec une justification, la liste des routes publiques est figée par un test.
- E-mails (réinitialisation) visibles dans Mailpit : http://127.0.0.1:8025.
- Récupération MFA d'un compte plateforme :
  `docker compose run --rm migrate python manage.py reset_user_mfa --email …`.

## Row-Level Security (P2.6) : règles pour tout nouveau code

- PostgreSQL filtre lui-même les lignes selon le périmètre transactionnel (`apps/core/db_scope.py`) :
  `tenant_context` (organisme), `identity_scope` (un compte), `@platform_operation` (opération globale).
  Hors périmètre, une table protégée renvoie 0 ligne et refuse toute écriture.
- **Nouvelle table** : l'ajouter à `apps/core/rls_inventory.py` et, si elle appartient à un organisme, hériter de
  `TenantScopedModel` et lui écrire sa politique dans une migration (`organization_id = rbi_current_org()`, USING et
  WITH CHECK). Sinon `test_rls_inventory` échoue.
- Une fonction dont un résultat « vide » serait permissif (ex. « pas de MFA ») doit s'exécuter dans le périmètre
  du compte évalué (`identity_scope`).
- Jamais de `SET` de session ni de `set_config(…, false)` (test statique) ; jamais de valeur interpolée en SQL.
- Tests : le corps de chaque test s'exécute en `rbi_app` (sous RLS) ; préparer ou simuler un état avec `owner()`
  (`conftest.py`) ; `@pytest.mark.db_owner` pour les seuls tests de schéma.
- Cluster initialisé avant P2.6 : exécuter une fois `infra/postgres/maintenance/p2.6-owner-can-set-app-role.sql`.

## Journal d'audit (P2.7) : règles pour tout nouveau code

- Seule voie d'écriture : `apps.audit.services.record_event(action, outcome=…, actor_id=…, …)` (ADR 0009). Le
  journal PostgreSQL `audit_auditlog` est en insertion seule (privilèges, déclencheurs) et chaîné (SHA-256).
- **Nouvelle action** : la déclarer dans `apps/audit/catalog.py` avec la fonctionnalité qui la produit (un test
  refuse une action inconnue comme une action déclarée mais jamais produite).
- Jamais de secret ni de corps de requête dans `details`, `old_value`, `new_value` : clés et valeurs sont validées,
  puis contrôlées par PostgreSQL.
- Organisme et acteur viennent du contexte serveur ; une opération plateforme visant un organisme passe
  `scope="platform"` ; une action sans utilisateur passe `system=True`.
- Les succès sont écrits après le COMMIT, les refus et échecs immédiatement (conservés si la transaction est
  annulée). En tests, mode `inline` : lire le journal avec `owner()`.
- Vérifier toutes les chaînes et relever leurs têtes : `docker compose run --rm migrate python manage.py audit_verify`.

## API REST v1 (P2.8) : règles pour tout nouveau code

- Toute vue hérite de `apps.core.api.views.RBIAPIView` et déclare UNE politique : `public = True`,
  `authenticated = True` ou `permission = "code"` / `by_method(GET="…", POST="…")` (ADR 0010). Ajouter la route à
  la table `EXPECTED` de `apps/core/tests/test_api_routes.py` : sinon la suite échoue.
- L'organisme vient du contexte serveur (`get_current_tenant()`), jamais de l'URL, des paramètres ni du corps ; un
  objet d'un autre organisme répond 404. Les écritures passent par les services (règles métier, audit).
- Erreurs : lever les exceptions métier ou DRF ; le gestionnaire produit du RFC 9457 sans détail interne.
- Contrat OpenAPI versionné : après une évolution VOLONTAIRE de l'API, régénérer puis relire le diff :
  `docker compose run --rm --no-deps backend python manage.py spectacular --validate --fail-on-warn --file openapi/rbi-api-v1.yaml`.

## Proxy de confiance et adresse cliente (P2.10) : règles pour tout nouveau code

- L'adresse cliente vient TOUJOURS de `apps.core.client_ip.client_ip(request)` (authentification, limitation,
  audit) ; jamais de `REMOTE_ADDR` ni de `X-Forwarded-For` lus directement (ADR 0012).
- Toute limitation DRF utilise les classes de `apps.core.api.throttling` (vérifié par `test_client_ip.py`).
- `RBI_TRUSTED_PROXIES` ne contient que l'adresse fixe de Nginx (`/32`) ; un réseau plus large que /16 (/48 en
  IPv6) empêche le démarrage. Derrière un nouveau proxy (répartiteur de charge), déclarer chaque niveau.
- Tests de la pile réelle derrière Nginx : `tests/foundation/test_nginx_proxy.py` ; E2E jetables :
  `py scripts/e2e.py` (projet Docker `rbi-e2e`, HTTP puis TLS).

## Rôles PostgreSQL

`migrate` et les tests utilisent `rbi_owner` (propriétaire des tables) ; `api` et `worker` utilisent `rbi_app`
(non propriétaire, soumis au RLS). L'API et le worker refusent de démarrer avec un rôle privilégié (`check_db_role`).

## Dépendances

Gérées par [uv](https://docs.astral.sh/uv/) ; `uv.lock` est versionné et l'image s'installe avec `--frozen`.
Pour ajouter ou mettre à jour une dépendance sans installer uv sur le poste :

```bash
docker run --rm -v "$PWD/backend:/src" -w /src python:3.13.16-slim-trixie \
  sh -c "pip install -q uv==0.12.14 && uv lock"
```

`exclude-newer` (pyproject.toml) refuse les versions publiées depuis moins de deux semaines : avancer la date
volontairement lors d'une mise à jour, puis relancer pip-audit :

```bash
docker run --rm -v "$PWD/backend:/src:ro" python:3.13.16-slim-trixie sh -c \
  "pip install -q uv==0.12.14 pip-audit && cd /src && uv export --frozen --all-groups --no-hashes \
   --format requirements-txt -o /tmp/r.txt -q && pip-audit -r /tmp/r.txt --no-deps --disable-pip"
```
