# ADR 0003 — Infrastructure et environnement backend (P2.1)

- **Statut** : acceptée (validation du propriétaire du projet, 08/10/2026), mise à jour en P2.2 (PostgreSQL 16.15)
- **Date** : 08/10/2026
- **Source** : spécification interne non publiée v1.0, §12 (architecture), §13 (technologies), §19 (sécurité), §23, §25

## Contexte

P2.1 met en place l'environnement Docker Compose du backend avant toute ligne de code Django.
La spécification interne non publiée fixe PostgreSQL 16 + PostGIS, Redis 7, Celery 5 + Beat, un stockage objet compatible S3
(« MinIO en souverain »), Docker Compose en développement et une isolation par RLS (`app.current_org`).

## Décisions

### 1. Services démarrés en P2.1

| Service | Image | Rôle |
|---|---|---|
| `db` | `rbi-postgres:16-postgis3.6` (construite sur PostgreSQL 16.15, voir §2) | Données transactionnelles, géospatial, RLS |
| `redis` | `redis:7.4.11-alpine` | Broker Celery, cache, sessions, limitation de débit (à venir) |
| `storage` | `chrislusf/seaweedfs:4.47` (mode `mini`) | Stockage objet S3 : rapports, imports, logos |
| `mailpit` | `axllent/mailpit:v1.31.1` | Capture de tous les e-mails (ADR 0001 · P12) |
| `backend` (profil `tools`) | `rbi-backend:dev` (construite) | Outillage : tests d'infrastructure, ruff, mypy |

**Non démarrés en P2.1, faute de code à exécuter** : API Django et Celery worker (P2.2) ; Celery Beat (P2.2/P2.3,
avec `django-celery-beat`) ; Nginx et conteneur frontend (P2.10, intégration ; en développement, Vite sert le frontend).

### 2. PostgreSQL : image construite plutôt que `postgis/postgis`

L'image `postgis/postgis:16-3.5` embarque toujours **PostgreSQL 16.9 sur Debian 11** (mai 2025), sans les correctifs
mineurs publiés depuis. L'image RBI part de l'officielle `postgres:16.14-trixie` et installe PostGIS **3.6** depuis le
dépôt PGDG déjà configuré, comme le fait le Dockerfile de `postgis/postgis`.

**Mise à jour P2.2 — PostgreSQL 16.15** : à la demande du propriétaire du projet, l'image suit la dernière version
mineure supportée de la branche 16 (16.15, publiée le 13/08/2026 ; branche 16 supportée jusqu'au 09/11/2028 selon
postgresql.org). Une mise à jour mineure ne change pas le format des données : le volume `rbi_pgdata` existant a été
conservé (image reconstruite, `docker compose up -d`), sans dump ni recréation. Procédure pour toute mineure future :
modifier la ligne `FROM`, `docker compose build db`, `docker compose up -d --wait db`, relancer les tests.
Un changement de version **majeure** exigerait au contraire `pg_dump`/`pg_restore` ou `pg_upgrade`. La compatibilité de Django 5.2 avec PostGIS 3.6
sera confirmée en P2.2 par les migrations GeoDjango ; le repli sur PostGIS 3.5 se fait en changeant la contrainte du Dockerfile.

### 3. Rôles PostgreSQL (prérequis du RLS)

| Rôle | Attributs | Usage |
|---|---|---|
| `POSTGRES_SUPERUSER` | superutilisateur | Amorçage du cluster uniquement ; **jamais** transmis au backend |
| `rbi_owner` | NOSUPERUSER, NOBYPASSRLS, CREATEDB | Propriétaire de la base et des tables : migrations, création des bases de test |
| `rbi_app` | NOSUPERUSER, NOBYPASSRLS, NOCREATEDB, NOINHERIT, aucune appartenance | API et Celery : lecture/écriture de lignes uniquement |

- PostGIS et les privilèges par défaut sont posés sur `template1` : la base `rbi` **et** les bases de test en héritent.
- Les tables créées par `rbi_owner` donnent à `rbi_app` `SELECT, INSERT, UPDATE, DELETE` seulement
  (ni `TRUNCATE`, ni `ALTER`, ni `DROP`, ni `REFERENCES`, ni `TRIGGER`).
- `rbi_app` ne peut pas se connecter à la base de maintenance `postgres`.
- Le test `test_default_privileges_and_real_rls` démontre dès P2.1, sur une table temporaire, que `rbi_app` est **réellement**
  soumis à une politique RLS fondée sur `app.current_org`, que `set_config(..., true)` (équivalent de `SET LOCAL`)
  disparaît en fin de transaction, et que `rbi_app` ne peut ni désactiver le RLS ni supprimer la table.
  Les politiques métier sont l'objet de P2.6.
- Pas de PgBouncer en P2.1. S'il est ajouté, le mode *transaction* reste compatible car le contexte est posé
  par transaction (`SET LOCAL`) ; jamais par session.

### 4. Stockage objet : SeaweedFS au lieu de MinIO (écart au §12.1 / §13)

Le dépôt open source de MinIO est **archivé** et ses images ne sont plus distribuées (`minio/minio` absent de
Docker Hub, `quay.io/minio/minio` soumis à authentification ; vérifié le 08/10/2026). Un composant non maintenu est
incompatible avec les exigences de sécurité (§19.1, analyse des dépendances).

| Option | Licence | Constat |
|---|---|---|
| **SeaweedFS 4.47** (retenu) | Apache-2.0 | Projet mature (≈ 10 ans), publications régulières, mode `mini` mono-conteneur |
| RustFS 1.0 | Apache-2.0 | Remplaçant direct de MinIO, mais version 1.0 très récente |
| Garage | AGPL-3.0 | Licence plus contraignante pour une diffusion institutionnelle |

L'exigence réelle de la spécification interne non publiée, un **stockage S3 auto-hébergeable (souverain)**, est conservée.
Le backend n'utilisera que l'API S3 (boto3 / django-storages) : changer de fournisseur reste une modification de configuration.
Sécurité : accès anonyme refusé (403, testé) ; seul le port S3 authentifié est publié ; le master, le filer
(sans authentification) et le volume ne sont joignables que depuis le réseau Docker interne ; WebDAV, Iceberg, Lance et
l'interface d'administration sont désactivés ; création implicite de bucket désactivée.

### 5. Redis

Mot de passe obligatoire (`--requirepass`, testé), persistance AOF, `maxmemory-policy noeviction` pour ne jamais perdre
un message Celery. Si le cache doit plus tard évincer des clés, il disposera d'une instance distincte.

### 6. Image backend

- **Python 3.13** (la spécification interne non publiée exige 3.12+ ; 3.13 est la version la plus récente supportée par l'ensemble de la stack
  en octobre 2026). `requires-python = ">=3.12,<3.14"`.
- Dépendances gérées par **uv** et verrouillées dans `backend/uv.lock` (installation `--frozen`).
  `exclude-newer` interdit toute version publiée depuis moins de deux semaines ; on avance la date volontairement à chaque mise à jour.
- **djangorestframework ≥ 3.17.2** : pip-audit a signalé CVE-2026-73228 et CVE-2026-73229 dans 3.16.1.
- Bibliothèques GDAL 3.10 / GEOS / PROJ de Debian trixie, sans chaîne de compilation ; utilisateur non root (uid 10001).
- Seules les dépendances de la stack imposée sont installées en P2.1. MFA (`django-otp`), Argon2, `django-storages` et
  le serveur WSGI seront ajoutés dans leurs sous-phases respectives.

### 7. Secrets et exposition

- Aucun secret dans Git : `docker-compose.yml` exige chaque secret (`${VAR:?}`) ; `.env` (ignoré) est généré par
  `scripts/init_env.py` avec des valeurs aléatoires ; `.env.example` ne contient que des marqueurs `__GENERATE__`.
- Tous les ports sont liés à `127.0.0.1`. PostgreSQL est publié sur **5433** (5432 est souvent occupé par un PostgreSQL local).
- Le socket local de PostgreSQL reste en `trust` (comportement de l'image officielle, requis par l'amorçage) : il n'est
  accessible qu'à l'intérieur du conteneur. Les connexions TCP exigent `scram-sha-256`.
- Mailpit (interface sans authentification) n'est joignable que depuis le poste local.

## Contraintes Windows prises en compte

- `.gitattributes` (`eol=lf`) garantit des scripts shell en LF dans les conteneurs ; `COPY --chmod=0755` pallie l'absence
  de bit exécutable sous Windows.
- Les scripts initdb ne s'exécutent que sur un volume **vide** : après un échec d'initialisation, `docker compose down -v`.
- Le dépôt doit être placé hors d'un dossier synchronisé (OneDrive) et dans un chemin ASCII (ADR 0001 · P1) ; montage `./backend:/app` géré par Docker Desktop (WSL 2).

## Conséquences

- L'écart MinIO → SeaweedFS est validé. Le backend reste découplé du fournisseur : API S3 standard uniquement,
  aucune fonctionnalité propre à SeaweedFS.
- La production (§25.3) n'utilisera pas le mode `mini` de SeaweedFS : stockage managé ou déploiement multi-composants
  avec TLS et identités IAM dédiées.
