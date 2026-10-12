# Phase 2 — Backend : suivi des sous-phases

Chaque sous-phase est validée explicitement par le propriétaire du projet avant la suivante, et produit un commit dédié.

| Sous-phase | Contenu | État |
|---|---|---|
| P2.1 | Infrastructure et environnement backend | ✅ validée — [rapport](P2.1-RAPPORT.md) · [ADR 0003](../../adr/0003-infrastructure-backend.md) |
| P2.2 | Django + PostgreSQL/PostGIS | ✅ validée — [rapport](P2.2-RAPPORT.md) · [ADR 0004](../../adr/0004-socle-django.md) |
| P2.3 | Core + Organizations + architecture multi-tenant | ✅ validée — [rapport](P2.3-RAPPORT.md) · [ADR 0005](../../adr/0005-organismes-multi-tenant.md) |
| P2.4 | Users + Roles + Permissions + RBAC | ✅ validée — [rapport](P2.4-RAPPORT.md) · [ADR 0006](../../adr/0006-rbac.md) |
| P2.5 | Authentication + Sessions + MFA | ✅ validée — [rapport](P2.5-RAPPORT.md) · [ADR 0007](../../adr/0007-authentification-sessions-mfa.md) |
| P2.6 | PostgreSQL RLS + isolation réelle | terminée, passage à P2.7 autorisé — [rapport](P2.6-RAPPORT.md) · [ADR 0008](../../adr/0008-row-level-security.md) |
| P2.7 | Audit append-only + intégrité | terminée, passage à P2.8 autorisé — [rapport](P2.7-RAPPORT.md) · [ADR 0009](../../adr/0009-journal-audit-append-only.md) |
| P2.8 | API v1 + OpenAPI | terminée — [rapport](P2.8-RAPPORT.md) · [ADR 0010](../../adr/0010-api-rest-v1.md) |
| — | Données de démonstration + seed_demo | replanifiées : première tâche de P2.11 (décision D6, P2.10) |
| P2.10 | Intégration frontend ↔ backend, Nginx, proxy de confiance, E2E réels | clôturée et validée (contre-épreuves CP-01 à CP-04 concluantes ; ne vaut pas autorisation de production) — [rapport](P2.10-RAPPORT.md) · [ADR 0012](../../adr/0012-integration-frontend-backend.md) |
| P2.11 | seed_demo (socle : deux organismes, cinq comptes par organisme) | validée avec réserves (défaut `search_path` corrigé en développement, à confirmer par le test d'intrusion ; écarts §26 ; ADR 0013 proposée ; ne vaut pas autorisation de pilote) — [rapport](P2.11-RAPPORT.md) · [ADR 0013](../../adr/0013-donnees-demonstration.md) |
| P2.12 | Validation finale P2 | à venir |
