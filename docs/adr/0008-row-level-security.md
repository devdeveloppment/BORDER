# ADR 0008 — Row-Level Security PostgreSQL (P2.6)

- **Statut** : proposée (en attente de validation de P2.6)
- **Date** : 08/10/2026
- **Source** : spécification interne non publiée v1.0, §12.3 (niveau 3 : RLS PostgreSQL et variable de session `app.current_org`),
  §19.1, §20.2 ; ADR 0003 (rôles), 0005 (multi-tenant), 0006 (RBAC), 0007 (authentification)

## Contexte

Jusqu'à P2.5, l'isolation entre organismes reposait sur le code Python. Un filtre oublié, du SQL brut, l'accès par
`_base_manager` ou une tâche sans contexte pouvaient lire les données de tous les organismes, car le rôle `rbi_app`
voyait toutes les lignes. P2.6 place la frontière dans PostgreSQL.

## Décisions

### 1. Contexte transmis à PostgreSQL : quatre variables à portée transactionnelle

| Variable | Posée par | Sens |
|---|---|---|
| `app.current_org` | `tenant_context` (requête d'un utilisateur d'organisme, tâche `@tenant_task`) | organisme validé côté serveur |
| `app.current_user` | middleware (compte authentifié), `identity_scope` (compte précis en vérification) | compte du périmètre |
| `app.auth_email` | connexion, demande de réinitialisation | recherche d'UN compte par e-mail |
| `app.platform` | `@platform_operation` (`PlatformScope` délivré, audité) | permission plateforme en cours |

- Posées **uniquement** par `set_config(nom, valeur, true)`, équivalent paramétré de `SET LOCAL`, dans
  `transaction.atomic()` (`apps/core/db_scope.py`). Jamais de `SET` de session : un test statique l'interdit dans le code.
- Un périmètre imbriqué hérite des valeurs non précisées et restaure exactement les précédentes en sortie. En cas
  d'exception, l'annulation du point de sauvegarde restaure les valeurs côté PostgreSQL.
- Les identifiants sont validés comme UUID avant SQL. Une valeur mal formée qui parviendrait à la base provoque une
  erreur de conversion : refus, jamais d'accès.
- **Aucune valeur par défaut** : sans périmètre, aucune politique ne laisse passer une ligne.
- Une requête authentifiée s'exécute dans une transaction (middleware). Le contexte est donc posé avant toute requête
  métier et disparaît au commit ou au rollback.
- **Connexions et pool** : connexions persistantes de Django (`CONN_MAX_AGE` 60 s hors développement), aucun pool
  externe. La portée transactionnelle est compatible avec un futur PgBouncer en mode transaction. Testé sur une
  connexion réutilisée de A vers B : aucune ligne de A n'est visible pour B.

### 2. Politiques par table (migration `core.0001_row_level_security`)

Inventaire complet et vérifié : `apps/core/rls_inventory.py` (17 tables + table de test).

| Catégorie | Table | RLS | Isolation |
|---|---|---|---|
| Organisme | `integrations_datasource` | oui | `organization_id = app.current_org` en lecture et écriture (USING + WITH CHECK) |
| Plateforme | `organizations_organization` | oui | lecture : son organisme, celui des comptes visibles, ou plateforme ; création et mise à jour : `platform.organizations` ; suppression impossible |
| Plateforme | `organizations_organizationauthorization` | oui | lecture : son organisme ou plateforme ; création : plateforme ; immuable |
| Plateforme | `organizations_accessrequest` | oui | création publique d'une demande neuve uniquement ; lecture et traitement : plateforme |
| Identité | `users_user` | oui | lecture : soi, son organisme, ou l'e-mail recherché ; écriture : soi (sans changer d'organisme) ou son organisme ; jamais de suppression |
| Identité | `users_user_role` | oui | lecture : ses affectations ou celles de son organisme ; écriture : rôles d'organisme de son organisme ; désignation du 1er administrateur sous `platform.institutional_admins` |
| MFA | `otp_totp_totpdevice`, `authentication_mfa_backup_code` | oui | `user_id = app.current_user` uniquement |
| Catalogue | `users_role` | oui | lecture seule : rôles par défaut ou de son organisme (V1) |
| Catalogue | `users_permission`, `users_role_permission` | non | lecture seule (privilèges) : catalogue global non sensible |
| Cadriciel | `auth_*`, `django_content_type`, `django_migrations` | non | lecture seule |
| Extension | `spatial_ref_sys` | non | référentiel PostGIS public |

- **Aucune politique « tout autoriser »** (vérifié). Toutes les politiques sont permissives et ne s'additionnent que
  vers des périmètres explicites. Une commande sans politique est refusée.
- **Moindre privilège** : `rbi_app` n'a plus que SELECT sur les catalogues et tables du cadriciel. Il ne peut supprimer
  ni un compte, ni un organisme, ni une demande ; les autorisations sont immuables. Pas de TRUNCATE, REFERENCES ni
  TRIGGER.

### 3. `FORCE ROW LEVEL SECURITY` : non appliqué, délibérément

`rbi_owner`, propriétaire des tables, est le **rôle de maintenance** : migrations, commandes serveur
(`create_super_admin`, `reset_user_mfa`), préparation des tests. Il n'est pas soumis au RLS. Ce contournement n'est
pas involontaire :
- l'API et le worker refusent de démarrer s'ils sont connectés en propriétaire (`check_db_role`, P2.2) ;
- les identifiants du propriétaire ne sont fournis qu'au service `migrate` et à l'outillage de test ;
- les commandes de maintenance refusent de s'exécuter sous `rbi_app` (`require_maintenance_role`, testé).

`FORCE` imposerait au propriétaire un contexte pour toute migration de données, sans protéger davantage le rôle
applicatif. À réévaluer si un rôle de maintenance distinct du propriétaire est introduit.

### 4. Fonctions `SECURITY DEFINER` (propriétaire, `search_path` figé, exécution réservée à `rbi_app`)

| Fonction | Rôle | Garde |
|---|---|---|
| `rbi_current_user_org()` | organisme du compte du périmètre, utilisé par la politique UPDATE de `users_user`, car une politique ne peut pas interroger sa propre table sans récursion | ne renvoie que l'organisme de `app.current_user` |
| `rbi_org_has_active_admin(org)` | précondition d'activation d'un organisme | exige `app.platform = platform.organizations` ; ne renvoie qu'un booléen |
| `rbi_admin_reset_mfa(user)` | réinitialisation MFA par un Administrateur institutionnel | revérifie organisme, compte, acteur actif et permission `users.manage` ; refuse sur soi-même |

La plateforme n'a jamais besoin de lire les comptes ni les secrets des organismes : ces fonctions renvoient le strict
nécessaire.

### 5. Identité, sessions et MFA

- **Avant authentification** : la recherche par e-mail ne rend visibles que ce compte et son organisme (`app.auth_email`) ;
  aucun secret MFA n'est lisible. La restauration de session (`get_user`), l'étape MFA en attente et la vérification d'un
  lien de réinitialisation se limitent au seul compte concerné (`identity_scope`).
- **Lectures liées à une identité** : `permission_codes`, `role_codes`, `requires_mfa` et toutes les fonctions MFA
  s'exécutent dans le périmètre du compte évalué. Sans cela, des lignes masquées feraient conclure « pas de MFA »,
  un **échec permissif** que la contre-épreuve a confirmé.
- **Secrets TOTP** : lisibles uniquement par leur titulaire (`app.current_user`). Un administrateur du même organisme
  ne les lit pas (testé). Ils restent stockés **en clair** : le chiffrement au repos (V1) n'est pas traité en P2.6.
- **Sessions** : dans Redis, hors PostgreSQL. Le RLS ne s'y applique pas ; elles restent protégées par l'empreinte de
  sécurité (ADR 0007).

### 6. Opérations globales et tâches Celery

- `@platform_operation(permission)` exige un `PlatformScope` délivré pour cette permission précise, et ne pose
  `app.platform` que le temps de l'appel. Les résultats sont évalués dans le périmètre (listes, jamais de QuerySet paresseux).
- `@tenant_task` exige un `organization_id` explicite, vérifie l'organisme (ACTIVE) et pose le contexte dans sa
  propre transaction. Testé : tâche sans contexte refusée ; tâches A puis B isolées ; échec en cours de tâche annulé
  sans contamination de la suivante.

### 7. Tests sous le vrai rôle applicatif

Le corps de chaque test `django_db` s'exécute en `SET ROLE rbi_app` : la suite entière, parcours HTTP compris,
s'exécute sous RLS. Les données sont préparées en propriétaire via un utilisateur `owner()` explicite. Pour cela,
le propriétaire est membre de `rbi_app` **sans héritage** (`WITH INHERIT FALSE, SET TRUE`) : il peut l'endosser, et
`rbi_app` ne gagne aucun droit. Les changements de rôle sont testés sur de vraies connexions ouvertes en `rbi_app`.
Clusters antérieurs à P2.6 : `infra/postgres/maintenance/p2.6-owner-can-set-app-role.sql` (exécuté une fois sur le
cluster de développement).

## Limites (risques non résolus)

1. **Les variables de session ne protègent pas contre l'exécution de SQL arbitraire.** Un attaquant capable
   d'exécuter du SQL sous `rbi_app` (injection) peut appeler `set_config` lui-même. Le RLS par variable protège contre
   les oublis de filtre et les chemins sans contexte, pas contre une injection, qui reste prévenue par l'ORM et les
   requêtes paramétrées (§19.1). Une isolation par rôle PostgreSQL ou par base dédiée (§12.3 « dédié ») est hors périmètre.
2. **Unicité globale** : une contrainte d'unicité (ex. e-mail) peut révéler l'existence d'une valeur dans un autre
   organisme par une erreur d'intégrité (comportement documenté de PostgreSQL).
3. **Membres d'un même organisme** : tout utilisateur d'un organisme voit au niveau SQL les comptes et affectations de
   rôles de son organisme ; le RBAC applicatif restreint ce qui est exposé.
4. **Propriétaire non soumis au RLS** (décision 3).
5. Secrets TOTP en clair ; sessions hors PostgreSQL ; journal d'audit non encore append-only (P2.7).
   **P2.7** : tables `audit_auditlog` et `audit_chain` ajoutées à l'inventaire (catégorie `audit`), politiques et
   fonctions décrites dans l'ADR 0009.
