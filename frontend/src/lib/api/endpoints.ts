import { api, apiDownload } from "./client";
import type {
  AccessRequest,
  Activity,
  ActivityDetail,
  Alert,
  AlertDetail,
  AlertStatus,
  AnalysisData,
  AuditIntegrity,
  AuditPage,
  AuditQuery,
  BackupCodes,
  BorderPost,
  BorderPostDetail,
  CurrentUser,
  DashboardData,
  LoginResponse,
  MfaVerifyResponse,
  Notification,
  OrganizationCreate,
  OrganizationStatusAction,
  OrganizationSettings,
  OrgUser,
  Paginated,
  PeriodKey,
  PlatformOrganization,
  PlatformOrganizationDetail,
  Report,
  ReportType,
  RoleCode,
  RoleDefinition,
  TotpEnrollment,
  UUID,
} from "./types";

export interface AlertListResponse extends Paginated<Alert> {
  status_counts: Record<AlertStatus, number>;
  total: number;
}

export type ListQuery = Record<string, string | number | undefined>;

const id = (value: string) => encodeURIComponent(value);

type AuditScope = "organization" | "platform";
const auditBase = (scope: AuditScope) => (scope === "platform" ? "/platform/audit-logs" : "/audit-logs");

/**
 * Routes de l'API v1. Livrées par le backend (schéma OpenAPI, P2.8) : authentification, profil, comptes et
 * rôles, organisme, journal d'audit, plateforme, demande d'accès. Les autres (tableau de bord, postes,
 * activités, alertes, analyses, rapports, notifications, paramètres) sont reportées : simulées par MSW en
 * mode intégré (src/mocks/handlers.ts, `DEFERRED_PATH_PREFIXES`).
 */
export const endpoints = {
  // --- Authentification (P2.5) -------------------------------------------------------------------
  login: (email: string, password: string) => api.post<LoginResponse>("/auth/login", { email, password }),
  verifyMfa: (code: string) => api.post<MfaVerifyResponse>("/auth/mfa/verify", { code }),
  startMfaEnrollment: () => api.post<TotpEnrollment>("/auth/mfa/enroll"),
  logout: () => api.post<void>("/auth/logout"),
  requestPasswordReset: (email: string) => api.post<{ detail: string }>("/auth/password-reset", { email }),
  confirmPasswordReset: (token: string, password: string) => api.post<void>("/auth/password-reset/confirm", { token, password }),
  me: () => api.get<CurrentUser>("/me"),
  changePassword: (current_password: string, new_password: string) =>
    api.post<void>("/auth/password/change", { current_password, new_password }),
  revokeOtherSessions: (password: string) => api.post<void>("/auth/sessions/revoke-others", { password }),
  renewTotp: (password: string) => api.post<TotpEnrollment>("/auth/mfa/totp/renew", { password }),
  confirmTotpRenewal: (code: string) => api.post<BackupCodes>("/auth/mfa/totp/renew/confirm", { code }),
  regenerateBackupCodes: (password: string) => api.post<BackupCodes>("/auth/mfa/backup-codes", { password }),
  disableMfa: (password: string) => api.post<void>("/auth/mfa/disable", { password }),

  submitAccessRequest: (payload: Record<string, string>) => api.post<{ detail: string }>("/public/access-requests", payload),

  dashboard: (period: PeriodKey) => api.get<DashboardData>("/dashboard", { period }),

  posts: () => api.get<BorderPost[]>("/border-posts"),
  post: (id: string) => api.get<BorderPostDetail>(`/border-posts/${encodeURIComponent(id)}`),

  activities: (query: ListQuery) => api.get<Paginated<Activity>>("/activities", query),
  activity: (id: string) => api.get<ActivityDetail>(`/activities/${encodeURIComponent(id)}`),

  alerts: (query: ListQuery) => api.get<AlertListResponse>("/alerts", query),
  alert: (id: string) => api.get<AlertDetail>(`/alerts/${encodeURIComponent(id)}`),
  alertAction: (id: string, payload: { action: "OBSERVATION" | "CHANGEMENT_STATUT"; to_status?: AlertStatus; comment?: string }) =>
    api.post<AlertDetail>(`/alerts/${encodeURIComponent(id)}/actions`, payload),

  analysis: (days: number) => api.get<AnalysisData>("/analytics/compare", { days }),

  reports: () => api.get<Report[]>("/reports"),
  generateReport: (payload: { report_type: ReportType; period_start: string; period_end: string; format: Report["format"] }) =>
    api.post<Report>("/reports", payload),

  notifications: () => api.get<Notification[]>("/notifications"),
  markNotificationRead: (id: string) => api.post<void>(`/notifications/${encodeURIComponent(id)}/read`),
  markAllNotificationsRead: () => api.post<void>("/notifications/read-all"),

  // --- Journal d'audit (P2.8) : organisme ou plateforme ------------------------------------------
  audit: (query: AuditQuery, scope: AuditScope = "organization") => api.get<AuditPage>(auditBase(scope), { ...query }),
  auditIntegrity: (scope: AuditScope = "organization") => api.get<AuditIntegrity>(`${auditBase(scope)}/integrity`),
  auditExport: (query: Omit<AuditQuery, "page" | "page_size">, scope: AuditScope = "organization") =>
    apiDownload(`${auditBase(scope)}/export`, { ...query }),

  // --- Comptes et rôles de son organisme (P2.8) ---------------------------------------------------
  users: () => api.get<OrgUser[]>("/users"),
  user: (userId: UUID) => api.get<OrgUser>(`/users/${id(userId)}`),
  createUser: (payload: { email: string; first_name: string; last_name: string; roles: RoleCode[] }) =>
    api.post<OrgUser>("/users", payload),
  setUserActive: (userId: UUID, is_active: boolean) => api.patch<OrgUser>(`/users/${id(userId)}`, { is_active }),
  assignRole: (userId: UUID, role: RoleCode) => api.post<OrgUser>(`/users/${id(userId)}/roles`, { role }),
  revokeRole: (userId: UUID, role: RoleCode) => api.delete<void>(`/users/${id(userId)}/roles/${id(role)}`),
  resetUserMfa: (userId: UUID) => api.post<void>(`/users/${id(userId)}/mfa-reset`),
  roles: () => api.get<RoleDefinition[]>("/roles"),

  organization: () => api.get<PlatformOrganization>("/organization"),
  settings: () => api.get<OrganizationSettings>("/settings"),
  updateSettings: (payload: { thresholds: { code: string; value: number }[]; retention_days: number; comment: string }) =>
    api.patch<OrganizationSettings>("/settings", payload),

  // --- Plateforme (P2.8) --------------------------------------------------------------------------
  platformOrganizations: () =>
    api.get<{ organizations: PlatformOrganization[]; access_requests: AccessRequest[] }>("/platform/organizations"),
  platformOrganization: (organizationId: UUID) => api.get<PlatformOrganizationDetail>(`/platform/organizations/${id(organizationId)}`),
  createOrganization: (payload: OrganizationCreate) => api.post<PlatformOrganizationDetail>("/platform/organizations", payload),
  updateOrganization: (organizationId: UUID, payload: Partial<Omit<OrganizationCreate, "deployment_mode" | "access_request_id">>) =>
    api.patch<PlatformOrganizationDetail>(`/platform/organizations/${id(organizationId)}`, payload),
  changeOrganizationStatus: (organizationId: UUID, action: OrganizationStatusAction, reason?: string) =>
    api.post<PlatformOrganizationDetail>(`/platform/organizations/${id(organizationId)}/status`, reason ? { action, reason } : { action }),
  addAuthorization: (organizationId: UUID, payload: { reference: string; scope: string; valid_from: string; valid_until: string | null }) =>
    api.post<PlatformOrganizationDetail>(`/platform/organizations/${id(organizationId)}/authorizations`, payload),
  designateInstitutionalAdmin: (organizationId: UUID, payload: { email: string; first_name: string; last_name: string }) =>
    api.post<{ id: UUID; email: string }>(`/platform/organizations/${id(organizationId)}/institutional-admins`, payload),
  rejectAccessRequest: (requestId: UUID, reason: string) =>
    api.post<AccessRequest>(`/platform/access-requests/${id(requestId)}/reject`, { reason }),
};
