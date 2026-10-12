/**
 * Contrat de données de l'API RBI v1, aligné sur le dictionnaire des entités (spécification interne non publiée §14).
 * Routes livrées : alignés sur le schéma OpenAPI versionné (backend/openapi/rbi-api-v1.yaml, P2.8) ; modules
 * métier reportés : contrat P1 servi par MSW (P2.10).
 */

export type UUID = string;
export type ISODateTime = string;

export type Level = "NORMAL" | "ATTENTION" | "ELEVE" | "CRITIQUE";

export type RoleCode = "SUPER_ADMIN" | "ORG_ADMIN" | "SUPERVISOR" | "AGENT" | "ANALYST" | "AUDITOR";

export type OrganizationStatus = "EN_ATTENTE" | "AUTORISEE" | "ACTIVE" | "SUSPENDUE" | "ARCHIVEE";
export type OrganizationType = "douane" | "recettes" | "police" | "portuaire" | "transport" | "autre";

export interface OrganizationSummary {
  id: UUID;
  name: string;
  short_name: string;
  type: OrganizationType;
  status: OrganizationStatus;
  country_code: string;
  timezone: string;
  deployment_mode: "mutualise" | "dedie";
  is_demo: boolean;
}

export interface PlatformOrganization extends OrganizationSummary {
  users_count: number;
  authorization_reference: string | null;
  valid_from: string | null;
  valid_until: string | null;
  created_at: ISODateTime;
}

export interface OrganizationAuthorization {
  id: UUID;
  reference: string;
  scope: string;
  valid_from: string;
  valid_until: string | null;
  created_at: ISODateTime;
}

export interface PlatformOrganizationDetail extends PlatformOrganization {
  retention_days: number;
  authorizations: OrganizationAuthorization[];
}

export interface OrganizationCreate {
  name: string;
  short_name: string;
  type: OrganizationType;
  country_code: string;
  timezone: string;
  retention_days: number;
  deployment_mode: "mutualise" | "dedie";
  is_demo: boolean;
  access_request_id?: UUID | null;
}

export type OrganizationStatusAction = "activate" | "suspend" | "reactivate" | "archive";

export interface RoleDefinition {
  code: RoleCode;
  name: string;
  mfa_required: boolean;
  permissions: string[];
}

export interface AccessRequest {
  id: UUID;
  organization_name: string;
  requester_name: string;
  requester_role: string;
  email: string;
  request_type: "demonstration" | "acces";
  created_at: ISODateTime;
}

export interface CurrentUser {
  id: UUID;
  email: string;
  first_name: string;
  last_name: string;
  roles: RoleCode[];
  permissions: string[];
  organization: OrganizationSummary | null;
  mfa_enabled: boolean;
  mfa_required: boolean;
  assigned_post_ids: UUID[];
  last_login: ISODateTime | null;
}

export type AuthStep = "AUTHENTICATED" | "MFA_REQUIRED" | "MFA_ENROLLMENT_REQUIRED";

export interface LoginResponse {
  step: AuthStep;
}

/** Réponse de vérification MFA ; `backup_codes` uniquement après un premier enrôlement (affichés une fois). */
export interface MfaVerifyResponse extends LoginResponse {
  backup_codes?: string[];
}

/** Enrôlement TOTP : URI du QR code et clé de saisie manuelle — renvoyés une seule fois, jamais conservés. */
export interface TotpEnrollment {
  otpauth_uri: string;
  secret: string;
}

export interface BackupCodes {
  backup_codes: string[];
}

export type PostType = "terrestre" | "portuaire" | "aeroportuaire" | "autre";
export type PostStatus = "actif" | "inactif" | "ferme_temporairement";

export interface BorderPost {
  id: UUID;
  code: string;
  name: string;
  post_type: PostType;
  status: PostStatus;
  capacity_per_hour: number | null;
  location: { lat: number; lng: number; region: string; locality: string };
  today_volume: number;
  variation_pct: number;
  open_alerts: number;
  risk_score: number;
  level: Level;
}

export interface BorderPostDetail extends BorderPost {
  opening_hours: string;
  assigned_agents: { id: UUID; name: string }[];
  utilization_pct: number;
  avg_processing_minutes: number;
  controls_today: number;
  hourly: { hour: number; volume: number; reference: number }[];
}

export type ActivityType = "passage" | "controle" | "operation" | "autre";

export interface Activity {
  id: UUID;
  reference: string;
  occurred_at: ISODateTime;
  border_post: { id: UUID; code: string; name: string };
  activity_type: ActivityType;
  category: string;
  vehicle_ref: string | null;
  operational_ref: string | null;
  status: "enregistree" | "validee" | "rejetee";
  level: Level;
  processing_minutes: number | null;
  source: { id: UUID; name: string; source_type: DataSourceType };
  is_demo: boolean;
  created_at: ISODateTime;
  updated_at: ISODateTime;
}

export interface ActivityDetail extends Activity {
  import_job: { id: UUID; file_name: string } | null;
  linked_alerts: { id: UUID; reference: string; title: string; level: Level }[];
  history: { at: ISODateTime; actor: string; field: string; old_value: string; new_value: string }[];
}

export type AlertStatus = "NOUVELLE" | "EN_COURS" | "EXAMINEE" | "CONFIRMEE" | "ECARTEE" | "CLOTUREE";

export type AlertType =
  | "VOLUME_INHABITUEL"
  | "FREQUENCE_INHABITUELLE"
  | "TEMPS_PASSAGE"
  | "VARIATION_HISTORIQUE"
  | "CONCENTRATION_TEMPORELLE"
  | "INCOHERENCE_DONNEES"
  | "CHANGEMENT_COMPORTEMENT"
  | "REPETITION_ANORMALE"
  | "ANOMALIE_GEOGRAPHIQUE"
  | "SEUIL_CONFIGURE";

export interface Alert {
  id: UUID;
  reference: string;
  alert_type: AlertType;
  title: string;
  border_post: { id: UUID; code: string; name: string };
  level: Level;
  score: number;
  status: AlertStatus;
  assignee: { id: UUID; name: string } | null;
  detected_at: ISODateTime;
}

export interface RiskFactor {
  code: string;
  label: string;
  observed: string;
  reference: string;
  points: number;
  max_points: number;
}

export interface AlertAction {
  id: UUID;
  at: ISODateTime;
  actor: string;
  action: "CREATION" | "PRISE_EN_CHARGE" | "ASSIGNATION" | "OBSERVATION" | "CHANGEMENT_STATUT";
  from_status: AlertStatus | null;
  to_status: AlertStatus | null;
  comment: string | null;
}

export interface AlertDetail extends Alert {
  description: string;
  explanation: string;
  factors: RiskFactor[];
  model_version: string;
  reference_period: string;
  comparison: { label: string; observed: number; reference: number }[];
  linked_activities: { id: UUID; reference: string; occurred_at: ISODateTime; activity_type: ActivityType }[];
  actions: AlertAction[];
  allowed_transitions: AlertStatus[];
  disclaimer: string;
}

export interface Kpis {
  activities: number;
  controls: number;
  vehicles: number;
  events: number;
  alerts: number;
  critical_alerts: number;
  open_alerts: number;
  processed_alerts: number;
  active_posts: number;
  total_posts: number;
  previous: { activities: number; controls: number; vehicles: number; events: number; alerts: number };
}

export interface TimePoint {
  bucket: string;
  value: number;
  previous: number;
}

export interface DailyBrief {
  generated_at: ISODateTime;
  items: { heading: string; text: string }[];
  disclaimer: string;
}

export interface DashboardData {
  period: PeriodKey;
  kpis: Kpis;
  series: TimePoint[];
  posts: Pick<BorderPost, "id" | "code" | "name" | "location" | "level" | "risk_score" | "open_alerts">[];
  recent_alerts: Alert[];
  brief: DailyBrief;
}

export type PeriodKey = "today" | "7d" | "30d" | "90d" | "365d";

export interface AnalysisData {
  period_a: string;
  period_b: string;
  series: { bucket: string; a: number; b: number }[];
  heatmap: { day: number; hour: number; value: number }[];
  by_post: { code: string; name: string; a: number; b: number; variation_pct: number }[];
  by_category: { category: string; a: number; b: number }[];
}

export type ReportType =
  | "journalier"
  | "hebdomadaire"
  | "mensuel"
  | "activite"
  | "alertes"
  | "poste"
  | "statistique"
  | "personnalise";

export interface Report {
  id: UUID;
  title: string;
  report_type: ReportType;
  period_start: string;
  period_end: string;
  format: "PDF" | "XLSX" | "CSV";
  generated_by: string;
  created_at: ISODateTime;
  status: "en_attente" | "en_cours" | "termine" | "echec";
}

export interface Notification {
  id: UUID;
  title: string;
  body: string;
  priority: "info" | "attention" | "urgent";
  created_at: ISODateTime;
  read_at: ISODateTime | null;
  target: { type: "alert" | "report" | "import"; id: UUID } | null;
}

export type AuditOutcome = "success" | "denied" | "failure";

/** Entrée du journal d'audit (schéma OpenAPI `AuditEntry`, P2.8) ; les champs P2 sont facultatifs en maquette. */
export interface AuditEntry {
  id: number;
  created_at: ISODateTime;
  scope?: "platform" | "organization";
  organization_id?: UUID | null;
  actor: string;
  actor_type?: "user" | "anonymous" | "system";
  actor_id?: UUID | null;
  action: string;
  outcome?: AuditOutcome;
  object_type: string;
  object_id?: string | null;
  object_repr: string;
  ip_address: string | null;
  request_id?: UUID | null;
  result: "succes" | "echec";
  old_value: Record<string, unknown> | null;
  new_value: Record<string, unknown> | null;
  details?: Record<string, unknown>;
  prev_hash?: string;
  hash: string;
}

export interface AuditPage extends Paginated<AuditEntry> {
  chain_integrity: "valide" | "rompue" | "non_verifiee";
}

export interface AuditIntegrity {
  chain: string;
  chain_integrity: "valide" | "rompue";
  checked: number;
  head_hash: string;
  errors: string[];
  verified_at: ISODateTime;
}

export interface AuditQuery {
  date_from?: string;
  date_to?: string;
  action?: string;
  outcome?: AuditOutcome | "";
  object_type?: string;
  ordering?: "-id" | "id";
  page?: number;
  page_size?: number;
}

export interface OrgUser {
  id: UUID;
  email: string;
  first_name: string;
  last_name: string;
  roles: RoleCode[];
  is_active: boolean;
  mfa_enabled: boolean;
  last_login: ISODateTime | null;
  assigned_posts: string[];
}

export type DataSourceType = "manuelle" | "fichier" | "api" | "connecteur";

export interface OrganizationSettings {
  version: number;
  updated_at: ISODateTime;
  updated_by: string;
  identity: { name: string; short_name: string };
  timezone: string;
  retention_days: number;
  thresholds: { code: string; label: string; value: number; unit: string }[];
  risk_weights: { code: string; label: string; max_points: number }[];
  notifications: { email_on_high: boolean; email_on_critical: boolean; daily_brief_email: boolean };
  history: { version: number; at: ISODateTime; by: string; comment: string }[];
}

export interface Paginated<T> {
  count: number;
  page: number;
  page_size: number;
  results: T[];
}

/** RFC 9457 — Problem Details for HTTP APIs */
export interface ProblemDetails {
  type: string;
  title: string;
  status: number;
  detail?: string;
  errors?: Record<string, string[]>;
}
