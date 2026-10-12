# ADR 0004 — Socle Django (P2.2)

- **Statut** : acceptée (validation du propriétaire du projet, 08/10/2026)
- **Date** : 08/10/2026
- **Source** : spécification interne non publiée v1.0, §12.2 (applications), §12.3 (isolation), §14.2 (conventions), §19.1, §23 ; ADR 0003

## Décisions

### 1. Projet et structure

- Projet `config/` : `settings/{base,development,test}.py`, `urls.py`, `wsgi.py`, `asgi.py`, `celery.py`, `env.py`.
- Les 16 applications du §12.2 existent sous `apps/<nom>` (label court identique) et sont enregistrées.
  En P2.2, seules `core` (modèles abstraits, commande `check_db_role`), `health` (sondes) et `users`
  (modèle technique) ont du contenu ; les autres ne contiennent que leur `AppConfig`.
- Convention de chaque application, appliquée dès qu'elle reçoit du code : `models.py`, `services.py`
  (écritures et règles), `selectors.py` (lectures), `api/` (sérialiseurs et vues DRF, sans logique métier), `tasks.py`, `tests/`.
- La configuration de production (`settings/production.py`, serveur WSGI) est ajoutée avec le déploiement. En attendant,
  `base.py` est sûr par défaut : `DEBUG=False`, `ALLOWED_HOSTS=[]`, cookies `Secure`, `HttpOnly`, `SameSite=Strict`.

### 2. Configuration par l'environnement

- `config/env.py` (sans dépendance) : `env_str`, `env_bool`, `env_int`, `env_list`. **Aucun secret n'a de valeur par défaut** :
  une variable obligatoire absente lève `ImproperlyConfigured` avec son nom, sans jamais afficher de valeur.
- Le rôle PostgreSQL est choisi **par service** dans `docker-compose.yml` (`RBI_DB_USER` / `RBI_DB_PASSWORD`) :

| Service | Réglages Django | Rôle PostgreSQL |
|---|---|---|
| `migrate` (ponctuel) | development | `rbi_owner` |
| `api`, `worker` | development | `rbi_app` |
| `backend` (pytest, profil `tools`) | test | `rbi_owner` (crée `test_rbi`) |

### 3. Modèle utilisateur technique dès la première migration

`AUTH_USER_MODEL = "users.User"` : clé UUID v4, identifiant e-mail normalisé, `PermissionsMixin`. `AUTH_USER_MODEL`
ne peut pas changer une fois les migrations appliquées. Le modèle ne porte aucune notion métier : organisme (P2.3),
rôles RBI (P2.4), MFA (P2.5) seront ajoutés par migrations. `TimestampedModel` (UUID + `created_at` / `updated_at`)
applique les conventions du §14.2.

### 4. Garde-fou de rôle au démarrage (`check_db_role`)

L'API et le worker exécutent `manage.py check_db_role` avant de démarrer. La commande refuse un rôle superutilisateur,
`BYPASSRLS`, propriétaire de tables ou membre d'un autre rôle. Une erreur de configuration qui ferait tourner
l'application avec le propriétaire, et donc hors RLS, empêche le démarrage au lieu de passer inaperçue.

### 5. Connexions PostgreSQL

- Pilote **psycopg 3** (vérifié par test), moteur `django.contrib.gis.db.backends.postgis`, `CONN_HEALTH_CHECKS`.
- `CONN_MAX_AGE` vaut 60 s par défaut, mais **0 en développement** : le serveur de développement crée un thread par
  requête et chaque thread gardait sa connexion (34 connexions inactives constatées en quelques minutes).
- Le contexte d'organisme sera posé **par transaction** (`SET LOCAL`, P2.6). Ce choix reste compatible avec les
  connexions persistantes et un éventuel PgBouncer en mode transaction.

### 6. Redis et Celery

- Bases Redis : 0 broker Celery, 1 résultats Celery, 2 cache Django (`KEY_PREFIX = "rbi"`).
- Celery : sérialisation **JSON uniquement** (jamais pickle), `acks_late`, `reject_on_worker_lost`, prefetch 1,
  limites de durée, UTC. Seule tâche : `health.ping`, qui vérifie la chaîne broker → worker → résultat.
- Règle pour P2.3/P2.6 : une tâche portant sur des données d'un organisme reçoit son `organization_id` explicitement
  et pose le contexte dans sa propre transaction ; le worker n'hérite d'aucun contexte.
- Celery Beat sera ajouté avec la première tâche planifiée (`django-celery-beat`, déjà verrouillé).

### 7. Sondes de santé (§23)

`GET /api/v1/health/live` (processus) et `GET /api/v1/health/ready` (base + Redis ; 503 en cas d'échec).
La réponse ne contient que `ok` / `error` par composant ; le détail est journalisé côté serveur, jamais renvoyé.
Ce sont des vues Django simples ; l'API DRF et OpenAPI relèvent de P2.8.

### 8. Tests GeoDjango

L'application `tests.gisprobe` (modèle `ProbeSite`, point `geography` WGS 84 + polygone) n'est installée que par les
réglages de test : aucune table de test dans la base de développement (vérifié). À retenir pour les modèles
géographiques : `ST_Transform` n'accepte pas le type `geography`, une conversion explicite en `geometry` est nécessaire.

### 9. Outillage

`django-stubs` 5.2.x (ligne alignée sur Django 5.2), qui limite mypy à 1.19.x ; `celery-types`.
Ruff exclut les migrations générées par Django.
