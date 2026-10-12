import type { RoleCode } from "@/lib/api/types";
import { PERMISSIONS, type Permission } from "@/lib/permissions";

/**
 * Matrice rôles → permissions des MOCKS UNIQUEMENT (mode « tout simulé », maquette Phase 1).
 *
 * Elle reproduit le catalogue du backend (apps/users/catalog.py, P2.4) pour que la maquette se comporte comme
 * l'API. Elle n'est JAMAIS une source d'autorisation : l'application lit les permissions effectives de
 * `GET /api/v1/me` (P2.10) ; un test vérifie qu'aucun module hors `src/mocks` n'importe ce fichier.
 */
const P = PERMISSIONS;

const VIEW: Permission[] = [P.dashboardView, P.mapView, P.postsView, P.activitiesView, P.alertsView, P.analyticsView, P.reportsView, P.settingsView];

export const MOCK_ROLE_PERMISSIONS: Record<RoleCode, Permission[]> = {
  // Le Super Admin n'accède à aucune donnée opérationnelle hors mandat (§7.1).
  SUPER_ADMIN: [P.platformOrganizations, P.platformInstitutionalAdmins, P.platformHealth, P.platformAudit],
  ORG_ADMIN: [
    ...VIEW, P.auditView, P.organizationView, P.usersView, P.activitiesCreate, P.activitiesExport, P.alertsTake,
    P.alertsComment, P.alertsAssign, P.alertsDecide, P.reportsGenerate, P.importsRun, P.postsManage, P.sourcesManage,
    P.settingsManage, P.usersManage,
  ],
  SUPERVISOR: [...VIEW, P.activitiesExport, P.alertsTake, P.alertsComment, P.alertsAssign, P.alertsDecide, P.whatIfRun, P.reportsGenerate],
  // Import interdit par défaut (décision P10) : `imports.run` s'accorde explicitement.
  AGENT: [P.dashboardView, P.mapView, P.postsView, P.activitiesView, P.alertsView, P.activitiesCreate, P.alertsTake, P.alertsComment],
  ANALYST: [...VIEW, P.activitiesExport, P.whatIfRun, P.reportsGenerate],
  AUDITOR: [...VIEW, P.auditView, P.organizationView, P.usersView],
};

export function mockPermissionsForRoles(roles: RoleCode[]): Permission[] {
  return [...new Set(roles.flatMap((role) => MOCK_ROLE_PERMISSIONS[role]))];
}
