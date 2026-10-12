# ADR 0005 — Organismes et fondations du multi-tenant (P2.3)

- **Statut** : acceptée (validation du propriétaire du projet, 08/10/2026) ; §7 complété par l'ADR 0006 (permission RBAC `platform.organizations`)
- **Date** : 08/10/2026
- **Source** : spécification interne non publiée v1.0, §2.3, §7.1–7.3, §8.3, §9.16, §12.3, §14.2–14.3, §20 ; écrans 5 et 31 ; ADR 0001 à 0004

## Contexte

L'isolation des organismes est l'exigence d'architecture la plus structurante (§12.3). P2.3 pose les niveaux 1 à 3
de la défense en profondeur (identité, contexte applicatif, gestionnaires filtrants) ; le niveau base de données
(RLS) est l'objet de P2.6.

## Décisions

### 1. Entités (application `organizations`)

| Entité | Contenu | Écarts au §14.3 |
|---|---|---|
| `Organization` | nom et sigle (uniques, insensibles à la casse), type, statut, pays ISO 3166-1, fuseau IANA, rétention (> 0 j), mode d'hébergement, `is_demo` | `logo` reporté (stockage applicatif non configuré) ; `is_demo` ajouté (données fictives marquées, §25.1) |
| `OrganizationAuthorization` | référence (unique par organisme), périmètre, période (`valid_until ≥ valid_from`), `granted_by` | `document` reporté (même raison) |
| `AccessRequest` | demande publique de démonstration ou d'accès (écran 5), consentement obligatoire, file EN_ATTENTE / TRAITÉE / REJETÉE | **entité ajoutée** : séparée de `Organization` pour qu'un formulaire public ne crée jamais d'organisme ni n'occupe un nom |

Énumérations stockées en texte contrôlé par contraintes `CHECK` (§14.2), clés UUID v4, horodatages UTC.
Aucune suppression : `on_delete=PROTECT` partout ; la fin de vie est le statut ARCHIVÉE.

### 2. Cycle de vie (§9.16)

```
EN_ATTENTE ─authorize─► AUTORISÉE ─activate─► ACTIVE ⇄ SUSPENDUE ;  tout statut non final ─archive─► ARCHIVÉE
```

- Le statut ne change que par les services (`apps/organizations/services.py`), sous verrou de ligne (`select_for_update`).
- `authorize` enregistre l'autorisation formelle ; `activate` et `reactivate` exigent une autorisation **en vigueur**
  à la date du jour (expirée ou future : refus).
- Suspension, réactivation et archivage exigent un motif. Un organisme archivé n'est plus modifiable.
- Préconditions d'activation ajoutées plus tard : premier Administrateur institutionnel (P2.4), sources déclarées.

### 3. Utilisateur, organisme, source de données : trois entités distinctes

- `User.organization` : FK nullable, `PROTECT`. **NULL uniquement pour les comptes plateforme** (§14.3). Aucun changement
  d'`AUTH_USER_MODEL` (migration `users.0002`).
- `DataSource` (application `integrations`) : première donnée organisationnelle, canal d'entrée des données (§8.3).
  Nom unique par organisme ; référence d'autorisation obligatoire pour `api` et `connecteur` (CHECK).
  Identifiants machine et `SystemIntegration` viendront avec l'ingestion ; aucun système réel n'est raccordé.
- Les rôles RBI ne sont pas modélisés en P2.3 (P2.4).

### 4. Contexte d'organisme, fermé par défaut (`apps/organizations/tenancy.py`)

- `TenantContext(organization_id, source)` immuable, porté par une `ContextVar` : propre au thread ou à la tâche
  asyncio, restauré à la sortie de `tenant_context(...)` même en cas d'exception.
- **Aucune valeur par défaut** : sans contexte, `get_current_tenant()` lève `TenantContextMissing`.
- Sources autorisées : `context_for_user(user)` (utilisateur authentifié, actif, organisme ACTIVE) et
  `context_for_task(organization_id)` (tâche asynchrone). Un compte plateforme n'obtient **jamais** de contexte :
  le Super Administrateur n'accède pas aux données opérationnelles (§7.1).

### 5. Modèles organisationnels (`TenantScopedModel`, `TenantManager`)

- `organization` NOT NULL, indexé, non éditable, sans relation inverse (`related_name="+"`).
- `objects` filtre automatiquement sur l'organisme du contexte et **échoue sans contexte**.
- `save()` attribue l'organisme du contexte, refuse une écriture pour un autre organisme, y compris sur un objet
  obtenu hors filtre ; `delete()` de même ; `bulk_create`, `update` et `bulk_update` ne peuvent ni viser un autre
  organisme ni modifier le rattachement.
- Un identifiant d'un autre organisme et un identifiant inexistant produisent la **même** exception `DoesNotExist`
  (404 indiscernable côté API).
- `_base_manager` (non filtré) reste réservé aux mécanismes internes de Django. Les traitements multi-organismes
  futurs (purge de rétention…) parcourront les organismes en posant un contexte pour chacun.

### 6. Requêtes et tâches

- `TenantContextMiddleware` : contexte déduit **uniquement** de `request.user`. Paramètres d'URL, en-têtes et corps
  sont ignorés (testé avec `?organization_id=` et `X-Organization-Id`). Organisme non ACTIVE : 403 générique.
  Il sera actif dès que `AuthenticationMiddleware` sera placé avant lui (P2.5) ; d'ici là, aucun contexte n'est posé.
- `@tenant_task` : une tâche reçoit `organization_id` en argument nommé explicite, vérifié (UUID valide, organisme
  existant et ACTIVE) ; sinon elle échoue. Le worker n'hérite d'aucun contexte.

### 7. Opérations globales : périmètre plateforme audité

- Seule porte d'entrée : `platform_scope(actor, purpose=...)`, qui exige un compte plateforme actif disposant de la
  permission `organizations.manage_organizations`. Un utilisateur organisationnel est refusé **même s'il possède la
  permission**. Chaque délivrance et chaque refus sont audités.
- Chaque service et sélecteur global commence par `require_scope(scope)` : un autre objet est refusé avant toute écriture.
- La permission utilise le mécanisme Django existant ; en P2.4, elle sera portée par le rôle SUPER_ADMIN
  (le §14.3 définit un rôle comme un ensemble nommé de permissions).

### 8. Audit

`apps.audit.services.record_event` est le point d'entrée unique. En P2.3, il émet du JSON structuré sur le journal
`rbi.audit`. En P2.7, il écrira dans le journal append-only chaîné sans changer les appelants.
**P2.7** : c'est fait (ADR 0009) ; les appelants précisent en outre l'objet concerné et la portée.

## Limites assumées (traitées par P2.6)

Le cloisonnement applicatif repose sur la discipline du code Python : `_base_manager`, du SQL brut ou un
`PlatformScope` construit à la main le contourneraient. C'est précisément le rôle du RLS PostgreSQL de P2.6 :
`tenant_context` posera `SET LOCAL app.current_org` dans la transaction, et les politiques des tables
organisationnelles s'appliqueront au rôle `rbi_app`, quel que soit le code. Les requêtes sur `User` ne sont pas encore
cloisonnées par organisme : la gestion des utilisateurs relève de P2.4.
