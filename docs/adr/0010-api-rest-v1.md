# ADR 0010 — API REST v1, contrats et consultation du journal d'audit (P2.8)

- **Statut** : proposée (en attente de validation de P2.8)
- **Date** : 09/10/2026
- **Source** : spécification interne non publiée v1.0, §9.11, §9.12, §9.16, §13 (DRF, drf-spectacular), §15.1-15.2, §19.1, écrans
  5, 22, 23, 31 ; critères CA-07/08 (isolation, 404), CA-11 (cycle de vie audité), « actions sensibles
  enregistrées » ; contrat du frontend P1 (`frontend/src/lib/api/endpoints.ts`, `types.ts`) ; ADR 0005 à 0009

## Décisions

### 1. Politique d'accès déclarée, refus par défaut

Toute vue de l'API hérite de `RBIAPIView` (`apps/core/api/views.py`) et déclare **exactement une** politique,
vérifiée dès la définition de la classe (sinon `ImproperlyConfigured`, l'application ne démarre pas) :

| Politique | Sens |
|---|---|
| `public = True` | route publique : 10 routes, liste fermée et testée (sondes, CSRF, connexion, MFA en cours de connexion, déconnexion, réinitialisation, demande d'accès) |
| `authenticated = True` | tout compte en session complète (MFA comprise), pour SES données : `/me`, mot de passe, facteurs, schéma OpenAPI |
| `permission = "code"` ou `by_method(GET=…, POST=…)` | permission RBAC du catalogue P2.4, par méthode ; la table doit couvrir exactement les méthodes implémentées |

- La permission est évaluée par `require_permission` (refus audité) dans le **contexte d'organisme du serveur**
  (P2.3) ; les permissions plateforme exigent en plus un `PlatformScope` délivré pour la permission exacte de
  l'opération (P2.3, audité). Un utilisateur authentifié n'est jamais autorisé par défaut.
- Permission DRF par défaut = `RBIPolicy` : une vue DRF qui n'hériterait pas de la base est refusée (testé).
- Aucune permission Django, aucun `is_staff` ni `is_superuser`.
- `test_api_routes.py` compare TOUTES les routes et méthodes à une table de référence : nouvelle route sans
  politique, permission modifiée ou route rendue publique → échec.

### 2. Sécurité des requêtes (inchangée depuis P2.5, étendue à l'API)

- Authentification par **session uniquement** (cookie HttpOnly, SameSite=Strict) ; MFA selon le rôle.
- **CSRF** : DRF exempte ses vues et ne revérifie le jeton que pour une session authentifiée ; cette exemption
  est **retirée** (`csrf_exempt = False`) : le middleware CSRF de Django s'applique à toute requête non sûre,
  publique comprise.
- **JSON uniquement** (parseur et rendu) ; corps limité à **64 Kio** (refus 413 avant lecture si
  `Content-Length` le dépasse, et borne à la lecture sinon) ; méthode OPTIONS retirée (405 : elle décrirait les
  sérialiseurs).
- **Limitation de débit** (Redis) : 600/min par compte, 120/min par adresse anonyme, 5/heure pour le formulaire
  public de demande d'accès ; en plus des verrouillages de connexion et de MFA de P2.5.
- Toutes les réponses : `Cache-Control: no-store` ; `X-Request-ID` (P2.7).

### 3. Erreurs (RFC 9457) et exceptions

Format `{"type": "about:blank", "title", "status", "detail"?, "errors"?}` (contrat P1 `ProblemDetails`) :
400 « Requête invalide » (+ erreurs par champ, sous-champs « parent.enfant »), 401, 403 générique (ne nomme ni
la permission ni la ressource), 404, 405, 409 « Opération impossible » (transition métier, message métier), 413,
415, 429 (+ `Retry-After`). **Toute autre exception : 500 « Erreur interne »**, sans trace ni message ; la trace
reste dans les journaux du serveur, retrouvable par `X-Request-ID`. Sous `/api/`, un 404 est toujours du JSON,
y compris en développement (`DEBUG`), où Django servirait sinon une page HTML listant toutes les routes.

### 4. Identifiants, dates, pagination, filtres, tri

- Identifiants UUID (chaînes) ; entrées du journal : entier séquentiel. Dates ISO 8601 UTC suffixées `Z`.
- **Pagination par page** (contrat P1 `Paginated<T>` : `count`, `page`, `page_size`, `results`) : `page_size`
  1 à 100 (défaut 50), profondeur bornée à 10 000 résultats (au-delà : filtrer par période). Une page au-delà de
  la dernière est vide.
- **Filtres validés par sérialiseur** ; sur le journal, un paramètre inconnu est **refusé** (400), en
  particulier un `organization_id` : jamais ignoré en silence, jamais utilisé.
- **Tri déterministe** par identifiant (`-id` par défaut, ou `id`).
- Écart au §15.1 : django-filter n'est pas utilisé (filtres explicites et typés, sans dépendance
  supplémentaire) ; pas de pagination par curseur (le §15.1 admet la pagination par page).

### 5. Isolation et contrôles objet par objet

- L'organisme vient **toujours** du contexte serveur ; aucun identifiant d'organisme n'est lu dans l'URL, les
  paramètres ni le corps (un `organization_id` dans le corps d'une création est ignoré : le compte est créé dans
  l'organisme du contexte ; sur le journal, il est refusé).
- Objet d'un autre organisme = objet inexistant : **404 identique** (§15.1).
- **Défense en profondeur testée** : les filtres applicatifs isolent à eux seuls (tests exécutés en rôle
  propriétaire, RLS contourné) ET le RLS isole à lui seul (tests SQL P2.6/P2.7).
- Deux fonctions `SECURITY DEFINER` bornées (`core.0002_api_read_functions`), revérifiant la permission en SQL :
  `rbi_org_mfa_enabled_users()` (booléen MFA des comptes de son organisme, `users.view`, sans accès aux appareils
  ni aux secrets) et `rbi_platform_org_user_counts()` (décompte de comptes par organisme, `platform.organizations`,
  aucun compte lisible).

### 6. Routes livrées (38 opérations, `openapi/rbi-api-v1.yaml`)

| Domaine | Routes | Politique |
|---|---|---|
| Authentification (P2.5, convertie en DRF, comportement identique) | `/auth/csrf`, `/auth/login`, `/auth/mfa/{enroll,verify}`, `/auth/logout`, `/auth/password-reset{,/confirm}` · `/auth/password/change`, `/auth/sessions/revoke-others`, `/auth/mfa/{totp/renew,totp/renew/confirm,backup-codes,disable}`, `/me` | public · authentifié |
| Public | `POST /public/access-requests` | public, 5/heure |
| Son organisme | `GET /organization` | `organization.view` |
| Comptes et rôles | `GET /users`, `GET /users/{id}`, `GET /roles` · `POST /users`, `PATCH /users/{id}` (activation), `POST /users/{id}/roles`, `DELETE /users/{id}/roles/{role}`, `POST /users/{id}/mfa-reset` | `users.view` · `users.manage` |
| Journal (organisme) | `GET /audit-logs`, `/audit-logs/export`, `/audit-logs/integrity` | `audit.view` |
| Plateforme | `GET/POST /platform/organizations`, `GET/PATCH /platform/organizations/{id}`, `POST …/{id}/status`, `POST …/{id}/authorizations`, `POST /platform/access-requests/{id}/reject` · `POST …/{id}/institutional-admins` | `platform.organizations` · `platform.institutional_admins` |
| Journal (plateforme) | `GET /platform/audit-logs`, `/export`, `/integrity` | `platform.audit` |

Toutes les écritures passent par les services existants (P2.3 à P2.5), qui portent les règles métier et l'audit.
Aucune route ne crée de compte plateforme ni n'attribue de rôle plateforme (le Super Administrateur reste créé par
commande serveur).

### 7. API du journal d'audit

- **Consultation** : pagination bornée, filtres (période, catégorie ou action, résultat, acteur, type et
  identifiant d'objet), tri. Organisme : ses entrées (y compris les opérations plateforme qui le concernent) ;
  plateforme : entrées de portée plateforme seulement.
- **Export CSV** : mêmes filtres, **10 000 lignes au plus** ; au-delà, refus (400) et refus journalisé — jamais
  de troncature silencieuse. Lecture par lots selon l'identifiant (pas d'OFFSET croissant). Cellules neutralisées
  contre l'injection de formules (`=`, `+`, `-`, `@`, tabulation, retour). Le fichier est construit en mémoire
  (≤ 10 000 lignes) : la lecture doit avoir lieu dans le périmètre transactionnel (RLS).
- **Intégrité** : `…/integrity` vérifie la chaîne (P2.7) et renvoie la tête à ancrer ; la liste porte
  `chain_integrity: "non_verifiee"` (une vérification complète à chaque page serait coûteuse).
- **Traçabilité** : chaque consultation (`audit.read`), export (`audit.export`) et vérification
  (`audit.verify`) est journalisée avec ses filtres. Ces écritures ne déclenchent aucune lecture : pas de boucle
  (testé : une consultation = une entrée).
- **Lecture seule** : aucune méthode d'écriture (405), aucune route par identifiant d'entrée.
- **Acteur** présenté par son adresse lorsqu'elle est lisible dans le périmètre (RLS : comptes de son
  organisme), sinon par un libellé neutre (« Compte 1a2b3c4d », « Système », « Anonyme ») : l'adresse d'un compte
  plateforme n'est jamais révélée à un organisme.

### 8. OpenAPI

- drf-spectacular (§13), schéma OpenAPI 3 **versionné** : `backend/openapi/rbi-api-v1.yaml`. Les tests le
  régénèrent (`--validate --fail-on-warn`) et échouent s'il diffère du fichier : toute évolution de contrat est
  volontaire et visible dans le diff.
- Chaque opération porte `x-rbi-policy` ; un test vérifie qu'elle correspond à la politique réelle de la vue.
  Routes publiques : `security: []` ; autres : cookie de session (+ en-tête CSRF décrit).
- Hors schéma : sondes de santé, schéma lui-même, commandes de maintenance (non exposées en HTTP).
- `GET /api/v1/schema` : réservé aux comptes authentifiés (§15.1). **Swagger UI et ReDoc ne sont pas servis** :
  ils chargeraient du JavaScript depuis un CDN externe (décision à prendre : `drf-spectacular-sidecar`).
- Typage : `djangorestframework-stubs` 3.16.9 (développement) pour mypy strict.

### 9. Contrat P1 : correspondance

| P1 (`endpoints.ts`) | P2.8 | Écart |
|---|---|---|
| `login`, `verifyMfa`, `logout`, `requestPasswordReset`, `confirmPasswordReset`, `me` | livrées (P2.5) | `GET /auth/csrf` à appeler avant la connexion (P2.10) ; `assigned_post_ids` toujours vide (pas de module des postes) |
| `submitAccessRequest` | livrée | erreurs sous les noms de champs du formulaire P1 ; 429 au-delà de 5/heure |
| `users` | livrée (+ détail, création, rôles, activation, MFA) | lecture `users.view` (le mock P1 exigeait `users.manage`) : l'Auditeur lit les comptes (§7.3) ; `assigned_posts` toujours vide |
| `organization` | livrée | — |
| `platformOrganizations` | livrée (+ gestion du cycle de vie) | `access_requests` : demandes EN_ATTENTE uniquement |
| `audit` | livrée (+ export, intégrité, journal plateforme) | `result` : refus et échecs → `echec` (champ `outcome` exact ajouté) ; `chain_integrity` : `non_verifiee` sur la liste (voir `/integrity`) ; filtre `action` par catégorie entière (« auth », « auth.mfa ») ou action exacte, pas par préfixe de caractères ; champs ajoutés (`outcome`, `actor_type`, `actor_id`, `scope`, `organization_id`, `object_id`, `request_id`, `details`, `prev_hash`) |
| `dashboard`, `posts`, `post`, `activities`, `activity`, `alerts`, `alert`, `alertAction`, `analysis`, `reports`, `generateReport`, `notifications`, `markNotificationRead`, `markAllNotificationsRead`, `settings`, `updateSettings` | **reportées** | aucun modèle métier : non exposées (404 RFC 9457), aucune donnée simulée servie comme réelle ; le frontend P1 continue de les obtenir de MSW |

`settings` / `updateSettings` : seuls quelques champs existent (fuseau, rétention) ; seuils, pondérations,
notifications et historique versionné n'existent pas. Une réponse partielle serait trompeuse : reportée.

## Limites

1. Les fonctionnalités métier (postes, activités, alertes, analyses, rapports, notifications, paramètres) ne
   sont pas exposées : le frontend reste partiellement sur MSW jusqu'aux phases concernées.
2. Unicité globale de l'adresse électronique : une création refusée révèle qu'une adresse est déjà utilisée
   quelque part (ADR 0008, limite 2) ; le message reste générique.
3. Export CSV construit en mémoire (≤ 10 000 lignes) ; pas d'export asynchrone par lots pour de gros volumes.
4. Limitation de débit par adresse : derrière un proxy, l'adresse cliente devra être lue d'un en-tête de confiance
   (P2.10) ; tous les clients derrière un même NAT partagent la limite anonyme. Historique : DRF lisait `X-Forwarded-For`
   fourni par le client (contournement) ; corrigé par `NUM_PROXIES = 0`.
5. Les tests de matrices de permissions ouvrent la session dans l'état « MFA vérifiée » sans rejouer le TOTP ;
   les parcours réels sont testés à part (P2.5, et de bout en bout pour le journal).
6. Pas d'Idempotency-Key ni d'authentification machine (OAuth2 / clés API par source) : avec l'ingestion
   (§15.1, phases suivantes).
