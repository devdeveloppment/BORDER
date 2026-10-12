/**
 * Codes de permission du catalogue du backend (apps/users/catalog.py, §7.3).
 *
 * IMPORTANT : côté frontend, ces permissions servent UNIQUEMENT à adapter l'interface (§11.5). La liste
 * effective d'un utilisateur vient de `GET /api/v1/me` ; l'autorisation décisive est toujours vérifiée par
 * l'API. Aucun tableau local « rôle → permissions » ne sert d'autorité (P2.10).
 */
export const PERMISSIONS = {
  dashboardView: "dashboard.view",
  mapView: "map.view",
  postsView: "border_posts.view",
  postsManage: "border_posts.manage",
  activitiesView: "activities.view",
  activitiesCreate: "activities.create",
  activitiesExport: "activities.export",
  alertsView: "alerts.view",
  alertsTake: "alerts.take",
  alertsAssign: "alerts.assign",
  alertsComment: "alerts.comment",
  alertsDecide: "alerts.decide",
  analyticsView: "analytics.view",
  whatIfRun: "analytics.what_if",
  reportsView: "reports.view",
  reportsGenerate: "reports.generate",
  importsRun: "imports.run",
  sourcesManage: "sources.manage",
  usersView: "users.view",
  usersManage: "users.manage",
  settingsManage: "settings.manage",
  settingsView: "settings.view",
  auditView: "audit.view",
  organizationView: "organization.view",
  platformOrganizations: "platform.organizations",
  platformInstitutionalAdmins: "platform.institutional_admins",
  platformHealth: "platform.health",
  platformAudit: "platform.audit",
} as const;

export type Permission = (typeof PERMISSIONS)[keyof typeof PERMISSIONS];
