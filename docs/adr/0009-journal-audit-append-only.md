# ADR 0009 — Journal d'audit append-only et chaîné (P2.7)

- **Statut** : proposée (en attente de validation de P2.7)
- **Date** : 09/10/2026
- **Source** : spécification interne non publiée v1.0, §9.11 (module Journal d'audit), §14 (modèle `AuditLog`), §7.2 B et F,
  §7.3, §19.1 (journal append-only chaîné, MVP), §20.2 (traçabilité, conservation limitée), écran 22, critères
  d'acceptation (actions sensibles enregistrées ; aucun utilisateur standard ne peut modifier ni supprimer une entrée d'audit, vérifié par tests BDD et API) ; ADR 0005 §8, 0006, 0007, 0008

## Contexte

Jusqu'à P2.6, `apps.audit.services.record_event` n'émettait qu'une ligne JSON sur le journal technique
`rbi.audit` : rien n'était conservé en base, et rien n'empêchait de modifier ou de perdre un événement. La spécification interne non publiée exige une table en insertion seule, protégée par les droits PostgreSQL et un chaînage d'empreintes.

## Exigé par la spécification interne non publiée ou proposé

| Élément | Exigé | Proposé (amélioration) |
|---|---|---|
| Table append-only, aucune modification ni suppression par les utilisateurs | §9.11 | — |
| Droits PostgreSQL : INSERT et SELECT seulement pour le rôle applicatif | §14 | INSERT limité aux colonnes descriptives ; SELECT filtré par le RLS |
| Chaînage SHA-256 `prev_hash` / `hash` | §9.11, §14, §19.1 | une chaîne par organisme + une chaîne plateforme ; tête de chaîne |
| Champs : utilisateur, organisme, date et heure UTC, action, objet, ancienne et nouvelle valeur, IP si approprié, identifiant de requête | §9.11, §14 | `scope`, `actor_type`, `outcome`, `metadata` |
| Événements : connexion, déconnexion, échec de connexion, création, modification, changement de permission, changement de statut d'un organisme | §9.11 | refus RBAC et de contexte, MFA, maintenance, consultation du journal |
| Lecture : Auditeur et Administrateur institutionnel (organisme), Super Administrateur (plateforme) | §7.2, écran 22 | permission revérifiée en SQL |
| Indicateur d'intégrité de la chaîne | écran 22 | vérificateur indépendant en Python, commande `audit_verify` |
| Conservation selon la politique de rétention de l'organisme, purge journalisée | §9.11, §20.2 | **non implémentée** (décision 9) |
| Consultation sensible, export, traitement d'alerte, rapport, accès sous mandat | §9.11 | **non déclarés** : fonctionnalités inexistantes à ce stade |

## Décisions

### 1. Modèle d'événement (`audit_auditlog`, migration `audit.0001_initial`)

| Champ | Type | Origine |
|---|---|---|
| `id` | bigint, séquentiel | déclencheur de scellement (jamais l'appelant) |
| `created_at` | timestamptz | `clock_timestamp()` du serveur PostgreSQL, UTC |
| `scope` | `platform` / `organization` | appelant (défaut : `organization` si un organisme est concerné) |
| `organization_id` | uuid, nullable | contexte serveur ; nul seulement en portée plateforme |
| `actor_type`, `actor_id` | `user` / `anonymous` / `system`, uuid | `actor_id` présent si et seulement si `user` (contrainte) |
| `action`, `outcome` | catalogue fermé ; `success` / `denied` / `failure` | appelant, validé |
| `object_type`, `object_id` | catégorie et identifiant de ressource | appelant, validés (formats contraints) |
| `old_value`, `new_value`, `metadata` | jsonb, objets plats bornés | appelant, validés (décision 3) |
| `ip_address` | inet, nullable | pair TCP, si `RBI_AUDIT_RECORD_IP` |
| `request_id` | uuid | généré par le serveur à chaque requête (`X-Request-ID` client ignoré, renvoyé en réponse) |
| `prev_hash`, `hash` | char(64) | déclencheur de scellement |

- **Pas de clé étrangère** vers les comptes ni les organismes : une entrée doit survivre à l'évolution de ces
  lignes, et l'écriture autonome (décision 6) ne doit ni voir ni attendre les lignes et verrous non validés de la
  transaction métier (une clé étrangère prendrait un verrou sur la ligne d'organisme déjà verrouillée par la
  transaction métier : interblocage). La relation « N-1 User, Organization » du §14 est conservée comme valeur.
- Modèle Django `AuditLog` en **lecture seule** (`managed = False`) : `save`, `delete`, `update`, `create` et
  `bulk_*` lèvent `AppendOnlyError`.

### 2. Catalogue fermé (`apps/audit/catalog.py`, 39 actions)

Une action inconnue est refusée. Un test statique vérifie que chaque action du code figure au catalogue et que le
catalogue ne déclare **aucune action que le code ne produit pas**.

| Famille | Événements |
|---|---|
| Authentification | `auth.login` (échec : `failure`, sans identifiant soumis ; refus : verrouillage, organisme non actif), `auth.session.open/close/terminate`, `auth.reauthenticate`, mot de passe (changement, demande et confirmation de réinitialisation), `auth.sessions.revoke_others` |
| MFA | enrôlement, vérification (méthode : `totp` / `backup_code`), renouvellement, régénération des codes, désactivation, réinitialisation par l'administrateur ou par commande serveur |
| Contrôle d'accès | `rbac.check` (refus), `platform.scope` (délivrance et refus), `tenant.access` (contexte refusé) |
| Organismes | demande d'accès (dépôt, rejet), enregistrement, modification (anciennes et nouvelles valeurs), changement de statut (ancien et nouveau statut), autorisation formelle, refus d'activation ou de réactivation |
| Comptes et rôles | création, désignation du premier administrateur, attribution et retrait de rôle, activation et désactivation, refus (auto-administration, dernier administrateur) |
| Maintenance | `user.bootstrap_super_admin`, `auth.mfa.server_reset`, `audit.verify` : acteur `system`, `metadata.channel = maintenance` |
| Journal | `audit.read` (consultation), `audit.verify` (vérification d'intégrité) |

### 3. Aucune donnée secrète (deux couches)

1. **Application** (`prepare_event`) : clés `[a-z][a-z0-9_]{0,39}` uniquement ; toute clé contenant `password`,
   `passwd`, `secret`, `token`, `otp`, `cookie`, `session`, `csrf`, `backup_code`, `api_key`, `apikey`,
   `private_key` ou `credential` est refusée ; valeurs scalaires (≤ 500 caractères, longueur maximale d'un motif) ou listes de scalaires (≤ 50) ;
   objets plats ; 4 000 octets au plus. Aucun corps de requête ni de réponse n'est journalisé.
2. **PostgreSQL** : contrainte `rbi_audit_json_safe` (mêmes clés, à toute profondeur, via JSONPath), objets JSON
   obligatoires, tailles bornées (4 Ko pour `metadata`, 8 Ko pour les valeurs).

Limite : une **valeur** secrète placée sous une clé neutre ne peut pas être détectée de façon générique ; la
défense repose sur le catalogue fermé, la revue de code et les tests de non-fuite (mot de passe, secret TOTP,
codes, cookie de session absents du journal après un parcours MFA complet).

### 4. Append-only appliqué par PostgreSQL

| Protection | Garantit | Ne garantit pas |
|---|---|---|
| **Privilèges** : `rbi_app` a SELECT et INSERT sur 13 colonnes descriptives ; ni UPDATE, ni DELETE, ni TRUNCATE, ni accès à la séquence, ni écriture des têtes de chaîne | l'API et le worker ne peuvent modifier, supprimer, vider le journal, ni fixer identifiant, horodatage ou empreinte | rien contre le propriétaire ou un superutilisateur |
| **RLS** : attribution (insertion) et lecture limitées (décision 7) | aucune entrée attribuée à un autre organisme ou acteur que le contexte serveur ; aucune lecture sans permission | rien contre l'exécution de SQL arbitraire sous `rbi_app` (ADR 0008, limite 1) |
| **Scellement** (`rbi_audit_seal`, SECURITY DEFINER, non appelable) | identifiant, horodatage et chaînage posés par la base | — |
| **Déclencheurs d'immuabilité** sur UPDATE, DELETE, TRUNCATE (journal et têtes de chaîne) | même le propriétaire ne modifie pas le journal par erreur (migration, maintenance) ; un UPDATE accordé par erreur resterait bloqué | **pas** une barrière contre un propriétaire ou un superutilisateur : il peut désactiver les déclencheurs (`ALTER TABLE … DISABLE TRIGGER`) |
| **Chaînage** (décision 5) | détection d'une modification, insertion ou suppression ponctuelle | pas d'immutabilité : une réécriture complète avec recalcul des empreintes et de la tête n'est détectable que par un ancrage externe |

Le retour arrière de la migration (qui détruirait le journal) est refusé tant qu'il existe des entrées, sauf
décision explicite du propriétaire dans sa session (`SET rbi.audit_allow_drop = 'on'`). Ne jamais le faire en
production.

### 5. Chaînage SHA-256

- **Une chaîne par organisme** (entrées de portée `organization`) **et une chaîne plateforme** : l'auditeur d'un
  organisme peut vérifier sa chaîne sans voir celle des autres ; la contention se limite à une chaîne.
- **Message canonique v1** : `netstring("rbi-audit-v1") + netstring(prev_hash) + netstring(champ)…`, où
  `netstring(v) = "longueur:v;"` (longueur en caractères) et `"~;"` pour NULL ; champs dans l'ordre id,
  horodatage UTC (`YYYY-MM-DDTHH:MI:SS.ffffffZ`), portée, organisme, type d'acteur, acteur, action, résultat,
  type et identifiant d'objet, ancienne valeur, nouvelle valeur, métadonnées (forme texte jsonb), IP, requête.
  Encodage sans ambiguïté, indépendant du fuseau horaire de la session (testé).
- **Concurrence** : le déclencheur verrouille la tête de chaîne (`SELECT … FOR UPDATE`), PUIS attribue
  l'identifiant : dans une chaîne, l'ordre des identifiants est l'ordre du chaînage ; une écriture annulée
  n'avance pas la tête. Testé avec 8 threads concurrents sur trois chaînes.
- **Tête de chaîne** (`audit_chain` : dernière entrée, dernière empreinte, longueur) : détecte la suppression de
  la dernière entrée.
- **Vérification** (`apps/audit/integrity.py`) : empreintes recalculées en Python, indépendamment de la fonction
  SQL ; disponible pour l'organisme (`verify_organization_chain`, `audit.view`), la plateforme
  (`verify_platform_chain`, `platform.audit`) et la maintenance (`audit_verify`, toutes les chaînes, têtes
  affichées pour ancrage externe, code de sortie non nul en cas d'altération).

### 6. Transactions : que devient l'événement si l'opération échoue ?

| Événement | Écriture | Conséquence |
|---|---|---|
| **Refus et échecs** | immédiate, sur une **connexion PostgreSQL dédiée** (une transaction courte par événement) | conservés même si la transaction métier est ensuite annulée (testé) |
| **Succès** | après le COMMIT de la transaction métier (`on_commit`), sur la même connexion dédiée | jamais de « succès » pour une opération annulée (testé) |
| Hors transaction | immédiate | — |

- La connexion dédiée est propre au processus et au thread (nouvelle connexion après un `fork`), fermée en fin de
  requête. Elle s'exécute **toujours en `rbi_app`** (`SET ROLE`), même déclenchée par une commande de
  maintenance connectée en propriétaire. Le verrou de tête de chaîne n'est tenu que le temps d'une insertion, et
  jamais par la transaction métier : pas d'interblocage (testé avec une ligne d'organisme verrouillée).
- **Échec d'écriture avant la fin de l'opération** : `AuditWriteError`, l'opération échoue (pas d'action non
  tracée). **Après un COMMIT** : l'opération ne peut plus être annulée ; la perte est consignée en CRITIQUE sur le
  journal technique avec le contenu de l'événement (testé).
- **Fenêtre résiduelle** : un arrêt brutal du processus entre le COMMIT métier et l'écriture du succès perd ce
  succès (quelques millisecondes). Une boîte d'envoi transactionnelle (outbox) supprimerait cette fenêtre : non
  retenue en P2.7.
- **Tests** : `RBI_AUDIT_WRITE_MODE = "inline"` (écriture dans la transaction du test, seule visible des données de
  test non validées) ; le mode autonome est éprouvé par des tests transactionnels dédiés. Le contrôle système
  `rbi.E001` interdit `inline` hors environnement de test.

### 7. RLS et contextes

- **Insertion** (`rbi_audit_insert`) : `actor_id` nul ou égal à `app.current_user` ; `organization_id` nul (portée
  plateforme uniquement, contrainte), ou égal à `app.current_org`, ou à l'organisme du compte du périmètre
  (`rbi_current_user_org()`, ADR 0008), ou à n'importe quel organisme **uniquement** pendant une opération
  plateforme `platform.organizations` / `platform.institutional_admins` et en portée `platform`. Le périmètre
  appliqué est celui du serveur au moment de l'événement (capturé, puis réappliqué par l'écrivain) ; aucune
  valeur du client.
- **Refus RBAC** : rattaché à l'organisme de l'**acteur**, jamais à celui du contexte présenté (`context_mismatch`
  indiqué) : un refus n'écrit rien dans le journal d'un autre organisme.
- **Lecture** (`rbi_audit_select`) : entrées de son organisme (y compris les opérations plateforme qui le
  concernent) si `rbi_audit_org_reader()` ; entrées de portée plateforme si `rbi_audit_platform_reader()`. Ces
  fonctions SECURITY DEFINER **revérifient la permission** (`audit.view` dans son organisme, compte actif ;
  `platform.audit` pour un compte plateforme avec `app.platform = 'platform.audit'`). Sans contexte, avec un
  contexte mal formé (erreur) ou falsifié (couple compte / organisme incohérent) : aucune ligne.
- **Chemins de consultation** (`apps/audit/selectors.py`) : RBAC puis RLS ; chaque consultation (`audit.read`) et
  vérification (`audit.verify`) est elle-même journalisée. L'API (filtres, pagination, export) relève de P2.8 (**fait** : ADR 0010, décision 7).
- **Lecture transversale** (tous les organismes) : uniquement par la commande de maintenance `audit_verify`, en
  rôle propriétaire, refusée sous `rbi_app`, et tracée.

### 8. Séparation des privilèges

| Usage | Rôle | Accès au journal |
|---|---|---|
| Exécution (API, worker) | `rbi_app` | insertion contrôlée, lecture selon permission |
| Migration | `rbi_owner` (service `migrate`) | DDL ; modification des données bloquée par les déclencheurs |
| Maintenance | `rbi_owner` (commandes serveur) | `audit_verify` (lecture transversale tracée) ; écritures via l'écrivain en `rbi_app` |
| Consultation | `rbi_app` + permission RBAC revérifiée en SQL | Auditeur, Administrateur institutionnel, Super Administrateur, Auditeur plateforme |

Un rôle de lecture distinct pour un export externe (SIEM) est une amélioration possible, non créée.

### 9. Conservation (rétention) : non implémentée

Aucune purge n'existe : toute suppression est refusée. Le §9.11 prévoit une conservation « selon la politique de
rétention de l'organisme » et le §20.2 une purge planifiée et journalisée. Décision à prendre avant de
l'implémenter : la durée de conservation du journal suit-elle `retention_days` (conçu pour les données
opérationnelles) ou une durée propre, souvent plus longue pour une trace de sécurité ? Conception prévue : une
fonction SECURITY DEFINER dédiée, exécutée par une tâche planifiée, qui supprime les entrées les plus anciennes
d'une chaîne, enregistre un point de reprise (dernière empreinte purgée) et journalise la purge ; le vérificateur
repartira de ce point.

## Limites (risques non résolus)

1. **Administrateurs de la base** : propriétaire et superutilisateur peuvent désactiver les déclencheurs, modifier
   ou supprimer des entrées et recalculer les empreintes. Seul un **ancrage externe** régulier des têtes de chaîne
   (hors de portée des administrateurs) le révèle ; `audit_verify` affiche les têtes, l'ancrage n'est pas mis en
   place. Leurs accès directs (psql) ne sont pas tracés par RBI (pgaudit ou journalisation des requêtes du
   serveur : hors périmètre).
2. **Injection SQL sous `rbi_app`** : elle pourrait insérer des entrées attribuées à un contexte falsifié (ADR
   0008, limite 1) ; elle ne pourrait ni modifier ni supprimer les entrées existantes (privilèges).
3. **Fenêtre de perte** d'un événement de succès entre COMMIT et écriture (décision 6).
4. **Valeurs secrètes** sous une clé neutre : non détectables automatiquement (décision 3).
5. **Contention** : une chaîne par organisme sérialise ses écritures d'audit (une insertion à la fois).
6. **Une connexion supplémentaire** par thread qui écrit un événement (fermée en fin de requête).
7. **Rétention et purge** non implémentées (décision 9) ; **adresse IP** enregistrée par défaut sur données
   fictives, à valider juridiquement par organisme avant tout traitement réel.
8. **Journal technique `rbi.audit`** : toujours émis pour la supervision, il n'est ni append-only ni cloisonné ;
   seul le journal PostgreSQL fait foi.
