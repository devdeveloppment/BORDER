/**
 * Base de données SIMULÉE — Phase 1 uniquement.
 *
 * Toutes les données sont FICTIVES (spécification interne non publiée §26) : organismes « Démo A / Démo B »,
 * « Poste Démo 01…10 », coordonnées génériques, références de véhicules générées.
 * Ces mocks seront remplacés par l'API Django (P2+) ; ils ne doivent jamais être livrés en production.
 */
import type {
  AccessRequest,
  Activity,
  ActivityType,
  Alert,
  AlertAction,
  AlertStatus,
  AlertType,
  AuditEntry,
  BorderPost,
  Level,
  Notification,
  OrganizationSettings,
  OrganizationSummary,
  OrgUser,
  PlatformOrganization,
  Report,
  ReportType,
  RiskFactor,
  RoleCode,
} from "@/lib/api/types";
import { ALERT_TYPE_LABEL, levelFromScore } from "@/lib/labels";
import { mockUuid, mulberry32, noise, pick } from "./rng";

export const MOCK_PASSWORD = "Demo-RBI-2026!";
export const MOCK_TOTP = "123456";

const HOUR = 3_600_000;
const DAY = 24 * HOUR;

/** Instant de référence : heure courante tronquée (les séries suivent l'horloge réelle). */
export function nowRef(): Date {
  const d = new Date();
  d.setMinutes(0, 0, 0);
  return d;
}

function startOfToday(): Date {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d;
}

// ---------------------------------------------------------------------------
// Organismes
// ---------------------------------------------------------------------------

export const ORGS: OrganizationSummary[] = [
  {
    id: mockUuid(1, 1),
    name: "Organisme Démo A",
    short_name: "DEMO-A",
    type: "douane",
    status: "ACTIVE",
    country_code: "XX",
    timezone: "Africa/Lome",
    deployment_mode: "mutualise",
    is_demo: true,
  },
  {
    id: mockUuid(1, 2),
    name: "Organisme Démo B",
    short_name: "DEMO-B",
    type: "portuaire",
    status: "ACTIVE",
    country_code: "XX",
    timezone: "Africa/Lome",
    deployment_mode: "mutualise",
    is_demo: true,
  },
];

export function orgIndex(orgId: string): number {
  return ORGS.findIndex((o) => o.id === orgId);
}

// ---------------------------------------------------------------------------
// Postes (coordonnées génériques fictives — la zone de démonstration sera fixée en P4)
// ---------------------------------------------------------------------------

const POST_TYPES = ["terrestre", "terrestre", "terrestre", "portuaire", "terrestre", "aeroportuaire", "terrestre", "terrestre", "portuaire", "terrestre"] as const;

interface PostSeed {
  id: string;
  orgId: string;
  idx: number;
  code: string;
  name: string;
  post_type: BorderPost["post_type"];
  status: BorderPost["status"];
  capacity: number;
  base: number;
  lat: number;
  lng: number;
}

export const POSTS: PostSeed[] = ORGS.flatMap((org, o) =>
  Array.from({ length: 10 }, (_, i) => {
    const r = mulberry32(100 + o * 50 + i);
    const base = Math.round(18 + r() * 40 + (o === 1 ? 10 : 0));
    return {
      id: mockUuid(2 + o, i + 1),
      orgId: org.id,
      idx: i,
      code: `PD-${String(i + 1).padStart(2, "0")}`,
      name: `Poste Démo ${String(i + 1).padStart(2, "0")}`,
      post_type: POST_TYPES[i] ?? "terrestre",
      status: i === 9 && o === 0 ? "ferme_temporairement" : "actif",
      capacity: Math.round(base * 1.6),
      base,
      lat: 10 + (i % 5) * 0.42 + r() * 0.2 + o * 0.05,
      lng: 1 + Math.floor(i / 5) * 0.9 + r() * 0.3 + o * 0.05,
    } satisfies PostSeed;
  }),
);

export function postsOf(orgId: string): PostSeed[] {
  return POSTS.filter((p) => p.orgId === orgId);
}

// Profil horaire habituel (activité diurne)
const HOURLY_PROFILE = [0.15, 0.1, 0.08, 0.08, 0.12, 0.3, 0.6, 0.9, 1.1, 1.2, 1.25, 1.2, 1.05, 1.1, 1.2, 1.25, 1.2, 1.1, 0.95, 0.75, 0.55, 0.4, 0.3, 0.2];
const WEEKDAY_FACTOR = [0.7, 1.05, 1.0, 1.0, 1.02, 1.12, 0.85]; // dim → sam

/** Le Poste Démo 07 de l'Organisme Démo A porte l'anomalie scénarisée (§26.1). */
function isScenarioPost(post: PostSeed): boolean {
  return post.orgId === ORGS[0]?.id && post.idx === 6;
}

/** Volume horaire simulé — `dayStart` = minuit local du jour concerné. */
export function hourlyVolume(post: PostSeed, dayStart: Date, hour: number): number {
  if (post.status === "ferme_temporairement" && Date.now() - dayStart.getTime() < 2 * DAY) return 0;
  const dayKey = Math.floor(dayStart.getTime() / DAY);
  const weekday = dayStart.getDay();
  const n = 0.85 + noise(post.idx, dayKey, hour, post.orgId.charCodeAt(0)) * 0.3;
  // Variation journalière commune à l'organisme (météo, calendrier…) : sans elle, le bruit horaire
  // se moyenne à l'agrégation et deux périodes deviennent artificiellement identiques.
  const dayFactor = 0.82 + noise(dayKey, post.orgId.charCodeAt(post.orgId.length - 1)) * 0.36;
  let v = post.base * (HOURLY_PROFILE[hour] ?? 0.5) * (WEEKDAY_FACTOR[weekday] ?? 1) * dayFactor * n;
  const daysAgo = Math.round((startOfToday().getTime() - dayStart.getTime()) / DAY);
  if (isScenarioPost(post) && daysAgo <= 2 && (hour === 2 || hour === 3)) {
    // +38 % du volume journalier concentré entre 02 h et 04 h
    v += (post.base * 17.8 * (WEEKDAY_FACTOR[weekday] ?? 1) * 0.38) / 2;
  }
  return Math.round(v);
}

export function dayVolume(post: PostSeed, dayStart: Date, untilHour = 23): number {
  let total = 0;
  for (let h = 0; h <= untilHour; h++) total += hourlyVolume(post, dayStart, h);
  return total;
}

export function dayStartOffset(daysAgo: number): Date {
  const d = startOfToday();
  d.setDate(d.getDate() - daysAgo);
  return d;
}

// ---------------------------------------------------------------------------
// Utilisateurs
// ---------------------------------------------------------------------------

export interface MockAccount extends OrgUser {
  orgId: string | null;
}

const ROLE_ACCOUNTS: { role: RoleCode; local: string; first: string; last: string }[] = [
  { role: "ORG_ADMIN", local: "admin", first: "Démo", last: "Administrateur" },
  { role: "SUPERVISOR", local: "superviseur", first: "Démo", last: "Superviseur" },
  { role: "AGENT", local: "agent", first: "Démo", last: "Agent" },
  { role: "ANALYST", local: "analyste", first: "Démo", last: "Analyste" },
  { role: "AUDITOR", local: "auditeur", first: "Démo", last: "Auditeur" },
];

export const ACCOUNTS: MockAccount[] = [
  {
    id: mockUuid(9, 0),
    orgId: null,
    email: "superadmin@plateforme.rbi.test",
    first_name: "Plateforme",
    last_name: "Super Admin",
    roles: ["SUPER_ADMIN"],
    is_active: true,
    mfa_enabled: true,
    last_login: new Date(Date.now() - 5 * HOUR).toISOString(),
    assigned_posts: [],
  },
  ...ORGS.flatMap((org, o) => [
    ...ROLE_ACCOUNTS.map((a, i) => ({
      id: mockUuid(10 + o, i + 1),
      orgId: org.id,
      email: `${a.local}@demo-${o === 0 ? "a" : "b"}.rbi.test`,
      first_name: a.first,
      last_name: `${a.last} ${o === 0 ? "A" : "B"}`,
      roles: [a.role],
      is_active: true,
      mfa_enabled: a.role !== "AGENT" && a.role !== "ANALYST",
      last_login: new Date(Date.now() - (i + 1) * 3 * HOUR).toISOString(),
      assigned_posts: a.role === "AGENT" ? ["PD-03", "PD-07"] : [],
    })),
    ...Array.from({ length: 4 }, (_, k) => ({
      id: mockUuid(10 + o, 20 + k),
      orgId: org.id,
      email: `agent${k + 2}@demo-${o === 0 ? "a" : "b"}.rbi.test`,
      first_name: "Démo",
      last_name: `Agent ${o === 0 ? "A" : "B"}${k + 2}`,
      roles: ["AGENT" as RoleCode],
      is_active: k !== 3,
      mfa_enabled: false,
      last_login: k === 3 ? null : new Date(Date.now() - (k + 2) * DAY).toISOString(),
      assigned_posts: [`PD-0${k + 1}`],
    })),
  ]),
];

export function accountName(a: Pick<OrgUser, "first_name" | "last_name">): string {
  return `${a.first_name} ${a.last_name}`;
}

/** Rôles soumis à MFA obligatoire (§9.12). */
export const MFA_REQUIRED_ROLES: RoleCode[] = ["SUPER_ADMIN", "ORG_ADMIN", "SUPERVISOR", "AUDITOR"];

// ---------------------------------------------------------------------------
// Activités
// ---------------------------------------------------------------------------

const CATEGORIES = ["Marchandises", "Passagers", "Transit", "Fret léger", "Hydrocarbures", "Agricole"];
const ACTIVITY_TYPES: ActivityType[] = ["passage", "passage", "passage", "controle", "operation", "autre"];

export interface ActivityRow extends Activity {
  orgId: string;
}

export const SOURCES = ORGS.map((org, o) => [
  { id: mockUuid(30 + o, 1), name: "Saisie manuelle", source_type: "manuelle" as const, orgId: org.id },
  { id: mockUuid(30 + o, 2), name: "Import mensuel CSV", source_type: "fichier" as const, orgId: org.id },
]);

function buildActivities(): ActivityRow[] {
  const rows: ActivityRow[] = [];
  ORGS.forEach((org, o) => {
    const posts = postsOf(org.id);
    const rand = mulberry32(500 + o);
    for (let i = 0; i < 1200; i++) {
      const post = pick(posts, rand());
      const ageHours = Math.floor(rand() * 30 * 24);
      const at = new Date(nowRef().getTime() - ageHours * HOUR - Math.floor(rand() * 59) * 60000);
      const score = Math.round(rand() < 0.88 ? rand() * 38 : 40 + rand() * 55);
      const src = SOURCES[o]?.[rand() < 0.7 ? 1 : 0];
      const type = pick(ACTIVITY_TYPES, rand());
      rows.push({
        orgId: org.id,
        id: mockUuid(40 + o, i),
        reference: `ACT-${org.short_name.slice(-1)}-${String(100000 + i)}`,
        occurred_at: at.toISOString(),
        border_post: { id: post.id, code: post.code, name: post.name },
        activity_type: type,
        category: pick(CATEGORIES, rand()),
        vehicle_ref: type === "autre" ? null : `VH-${Math.floor(rand() * 0xffffff).toString(16).toUpperCase().padStart(6, "0")}`,
        operational_ref: rand() < 0.6 ? `OPR-${Math.floor(rand() * 900000 + 100000)}` : null,
        status: rand() < 0.94 ? "validee" : rand() < 0.5 ? "enregistree" : "rejetee",
        level: levelFromScore(score),
        processing_minutes: Math.round((4 + rand() * 30) * 10) / 10,
        source: src ? { id: src.id, name: src.name, source_type: src.source_type } : { id: "", name: "—", source_type: "manuelle" },
        is_demo: true,
        created_at: at.toISOString(),
        updated_at: at.toISOString(),
      });
    }
  });
  return rows.sort((a, b) => b.occurred_at.localeCompare(a.occurred_at));
}

export const ACTIVITIES: ActivityRow[] = buildActivities();

// ---------------------------------------------------------------------------
// Alertes (vocabulaire neutre — §17.3)
// ---------------------------------------------------------------------------

export interface AlertRow extends Alert {
  orgId: string;
  description: string;
  explanation: string;
  factors: RiskFactor[];
  actions: AlertAction[];
}

const ALERT_TYPES = Object.keys(ALERT_TYPE_LABEL) as AlertType[];
const STATUSES: AlertStatus[] = ["NOUVELLE", "NOUVELLE", "EN_COURS", "EN_COURS", "EXAMINEE", "CONFIRMEE", "ECARTEE", "CLOTUREE", "CLOTUREE"];

const FACTOR_CATALOG: { code: string; label: string; max: number }[] = [
  { code: "VOLUME_VAR", label: "Variation de volume", max: 25 },
  { code: "HOUR_SHIFT", label: "Écart horaire", max: 15 },
  { code: "HIST_ANOMALY", label: "Anomalie historique", max: 20 },
  { code: "REPETITION", label: "Répétition d'événements", max: 20 },
  { code: "PROCESSING_TIME", label: "Temps de passage", max: 15 },
  { code: "DATA_INCONSISTENCY", label: "Incohérence de données", max: 10 },
  { code: "THRESHOLD", label: "Seuil configuré", max: 25 },
];

function scenarioFactors(): RiskFactor[] {
  return [
    { code: "VOLUME_VAR", label: "Variation de volume", observed: "+38 %", reference: "moy. 4 mêmes jours de semaine", points: 20, max_points: 25 },
    { code: "HOUR_SHIFT", label: "Écart horaire", observed: "31 % de l'activité entre 02 h et 04 h", reference: "profil habituel : 4 %", points: 15, max_points: 15 },
    { code: "HIST_ANOMALY", label: "Anomalie historique", observed: "+41 % vs N-1", reference: "tendance 28 j", points: 17, max_points: 20 },
    { code: "REPETITION", label: "Répétition d'événements", observed: "6 événements identiques en 72 h", reference: "habituel : 1", points: 20, max_points: 20 },
  ];
}

function buildAlerts(): AlertRow[] {
  const rows: AlertRow[] = [];
  ORGS.forEach((org, o) => {
    const posts = postsOf(org.id);
    const orgUsers = ACCOUNTS.filter((a) => a.orgId === org.id && (a.roles.includes("SUPERVISOR") || a.roles.includes("AGENT")));
    const rand = mulberry32(900 + o);
    for (let i = 0; i < 36; i++) {
      const post = pick(posts, rand());
      const type = pick(ALERT_TYPES, rand());
      const status = pick(STATUSES, rand());
      const score = Math.round(40 + rand() * 58);
      const detected = new Date(nowRef().getTime() - Math.floor(rand() * 29 * 24 + 4) * HOUR);
      const nFactors = 2 + Math.floor(rand() * 3);
      const factors: RiskFactor[] = [];
      let remaining = score;
      for (let k = 0; k < nFactors; k++) {
        const f = FACTOR_CATALOG[(i + k) % FACTOR_CATALOG.length]!;
        const points = k === nFactors - 1 ? Math.min(f.max, remaining) : Math.min(f.max, Math.round(remaining / (nFactors - k)));
        remaining -= points;
        factors.push({ code: f.code, label: f.label, observed: `+${Math.round(10 + rand() * 40)} %`, reference: "moy. 4 mêmes jours", points, max_points: f.max });
      }
      const finalScore = factors.reduce((s, f) => s + f.points, 0);
      const assignee = status === "NOUVELLE" ? null : pick(orgUsers, rand());
      rows.push(
        makeAlert(org.id, o, i, {
          type,
          post,
          status,
          score: finalScore,
          detected,
          factors,
          assignee: assignee ? { id: assignee.id, name: accountName(assignee) } : null,
        }),
      );
    }
  });

  // Alerte scénarisée (§26.1, §30) — Poste Démo 07, Organisme Démo A, score 72
  const orgA = ORGS[0]!;
  const p07 = postsOf(orgA.id)[6]!;
  rows.push(
    makeAlert(orgA.id, 0, 123, {
      type: "VOLUME_INHABITUEL",
      post: p07,
      status: "NOUVELLE",
      score: 72,
      detected: new Date(nowRef().getTime() - 2 * HOUR),
      factors: scenarioFactors(),
      assignee: null,
      reference: "ALR-2026-000123",
      explanation:
        "Niveau ÉLEVÉ (72/100) principalement dû à une variation de +38 % du volume par rapport à la moyenne des 4 mêmes jours de semaine précédents, associée à une concentration inhabituelle d'activité entre 02 h et 04 h.",
    }),
  );
  return rows.sort((a, b) => b.detected_at.localeCompare(a.detected_at));
}

/** Chemin de statuts parcouru pour atteindre un statut final (cycle de vie §17.2). */
const STATUS_PATH: Record<AlertStatus, AlertStatus[]> = {
  NOUVELLE: [],
  EN_COURS: ["EN_COURS"],
  EXAMINEE: ["EN_COURS", "EXAMINEE"],
  CONFIRMEE: ["EN_COURS", "EXAMINEE", "CONFIRMEE"],
  ECARTEE: ["EN_COURS", "EXAMINEE", "ECARTEE"],
  CLOTUREE: ["EN_COURS", "EXAMINEE", "CONFIRMEE", "CLOTUREE"],
};

function makeAlert(
  orgId: string,
  o: number,
  i: number,
  p: {
    type: AlertType;
    post: PostSeed;
    status: AlertStatus;
    score: number;
    detected: Date;
    factors: RiskFactor[];
    assignee: { id: string; name: string } | null;
    reference?: string;
    explanation?: string;
  },
): AlertRow {
  const level: Level = levelFromScore(p.score);
  const top = [...p.factors].sort((a, b) => b.points - a.points)[0];
  const actions: AlertAction[] = [
    { id: mockUuid(70 + o, i * 10), at: p.detected.toISOString(), actor: "Système RBI", action: "CREATION", from_status: null, to_status: "NOUVELLE", comment: "Alerte générée automatiquement par le moteur d'indicateurs." },
  ];
  const path = STATUS_PATH[p.status];
  for (let k = 0; k < path.length; k++) {
    const to = path[k]!;
    actions.push({
      id: mockUuid(70 + o, i * 10 + k + 1),
      at: new Date(p.detected.getTime() + (k + 1) * 2 * HOUR).toISOString(),
      actor: p.assignee?.name ?? "Superviseur",
      action: "CHANGEMENT_STATUT",
      from_status: k === 0 ? "NOUVELLE" : path[k - 1]!,
      to_status: to,
      comment: to === "EXAMINEE" ? "Vérification des enregistrements de la période effectuée." : to === "ECARTEE" ? "Écart expliqué par un événement planifié (maintenance)." : to === "CONFIRMEE" ? "Écart vérifié par un humain." : to === "CLOTUREE" ? "Clôture motivée après traitement." : null,
    });
  }
  return {
    orgId,
    id: mockUuid(60 + o, i),
    reference: p.reference ?? `ALR-2026-${String(1000 + i + o * 500).padStart(6, "0")}`,
    alert_type: p.type,
    title: `${ALERT_TYPE_LABEL[p.type]} — ${p.post.name}`,
    border_post: { id: p.post.id, code: p.post.code, name: p.post.name },
    level,
    score: p.score,
    status: p.status,
    assignee: p.assignee,
    detected_at: p.detected.toISOString(),
    description: `Comportement inhabituel observé au ${p.post.name} : indicateur nécessitant une vérification.`,
    explanation:
      p.explanation ??
      `Niveau ${level === "ELEVE" ? "ÉLEVÉ" : level} (${p.score}/100) principalement dû au facteur « ${top?.label ?? "—"} » (${top?.observed ?? "—"} par rapport à la référence).`,
    factors: p.factors,
    actions,
  };
}

export const ALERTS: AlertRow[] = buildAlerts();

/** Transitions autorisées (§17.2). Les règles par rôle sont appliquées dans les handlers. */
export const TRANSITIONS: Record<AlertStatus, AlertStatus[]> = {
  NOUVELLE: ["EN_COURS"],
  EN_COURS: ["EXAMINEE"],
  EXAMINEE: ["CONFIRMEE", "ECARTEE"],
  CONFIRMEE: ["CLOTUREE"],
  ECARTEE: ["CLOTUREE"],
  CLOTUREE: [],
};

// ---------------------------------------------------------------------------
// Événements, notifications, rapports, audit, paramètres
// ---------------------------------------------------------------------------

export function eventsCount(orgId: string, fromMs: number): number {
  const days = Math.max(1, Math.round((Date.now() - fromMs) / DAY));
  return Math.round(days * (orgIndex(orgId) === 0 ? 0.9 : 0.7));
}

export interface NotificationRow extends Notification {
  orgId: string | null;
  recipientId: string;
}

function buildNotifications(): NotificationRow[] {
  const rows: NotificationRow[] = [];
  for (const account of ACCOUNTS) {
    const orgAlerts = ALERTS.filter((a) => a.orgId === account.orgId).slice(0, 6);
    const rand = mulberry32(account.id.charCodeAt(0) * 31 + account.id.charCodeAt(3));
    orgAlerts.forEach((a, k) => {
      rows.push({
        id: mockUuid(80, rows.length),
        orgId: account.orgId,
        recipientId: account.id,
        title: a.level === "CRITIQUE" || a.level === "ELEVE" ? "Indicateur nécessitant une vérification" : "Nouvelle alerte",
        body: `${a.title} (niveau ${a.score}/100).`,
        priority: a.level === "CRITIQUE" ? "urgent" : a.level === "ELEVE" ? "attention" : "info",
        created_at: a.detected_at,
        read_at: k > 2 || rand() < 0.2 ? a.detected_at : null,
        target: { type: "alert", id: a.id },
      });
    });
    if (account.orgId) {
      rows.push({
        id: mockUuid(80, rows.length),
        orgId: account.orgId,
        recipientId: account.id,
        title: "Rapport disponible",
        body: "Le rapport journalier d'hier a été généré.",
        priority: "info",
        created_at: new Date(Date.now() - 20 * HOUR).toISOString(),
        read_at: new Date(Date.now() - 19 * HOUR).toISOString(),
        target: null,
      });
    }
  }
  return rows;
}

export const NOTIFICATIONS: NotificationRow[] = buildNotifications();

export interface ReportRow extends Report {
  orgId: string;
}

function buildReports(): ReportRow[] {
  const types: ReportType[] = ["journalier", "journalier", "hebdomadaire", "alertes", "poste", "mensuel", "activite", "statistique"];
  return ORGS.flatMap((org, o) =>
    types.map((t, i) => {
      const end = dayStartOffset(i * 3 + 1);
      const start = new Date(end.getTime() - (t === "mensuel" ? 30 : t === "hebdomadaire" ? 7 : 1) * DAY);
      return {
        orgId: org.id,
        id: mockUuid(90 + o, i),
        title: `Rapport ${t} — ${org.name}`,
        report_type: t,
        period_start: start.toISOString().slice(0, 10),
        period_end: end.toISOString().slice(0, 10),
        format: (["PDF", "XLSX", "CSV"] as const)[i % 3]!,
        generated_by: i % 2 ? `Démo Analyste ${o === 0 ? "A" : "B"}` : `Démo Superviseur ${o === 0 ? "A" : "B"}`,
        created_at: new Date(end.getTime() + 7 * HOUR).toISOString(),
        status: i === 7 ? "echec" : "termine",
      } satisfies ReportRow;
    }),
  );
}

export const REPORTS: ReportRow[] = buildReports();

export interface AuditRow extends AuditEntry {
  orgId: string | null;
}

const AUDIT_ACTIONS: { action: string; object_type: string }[] = [
  { action: "auth.login", object_type: "Session" },
  { action: "auth.login_failed", object_type: "Session" },
  { action: "alert.status_changed", object_type: "Alerte" },
  { action: "alert.assigned", object_type: "Alerte" },
  { action: "activity.export", object_type: "Export" },
  { action: "report.generated", object_type: "Rapport" },
  { action: "user.role_changed", object_type: "Utilisateur" },
  { action: "settings.updated", object_type: "Paramètres" },
];

function buildAudit(): AuditRow[] {
  const rows: AuditRow[] = [];
  [...ORGS.map((o) => o.id), null].forEach((orgId, o) => {
    const rand = mulberry32(1200 + o);
    const actors = ACCOUNTS.filter((a) => a.orgId === orgId);
    for (let i = 0; i < 120; i++) {
      const a = pick(AUDIT_ACTIONS, rand());
      const actor = pick(actors, rand());
      const failed = a.action === "auth.login_failed";
      rows.push({
        orgId,
        id: o * 10000 + 120 - i,
        created_at: new Date(Date.now() - i * 2.7 * HOUR - Math.floor(rand() * 50) * 60000).toISOString(),
        actor: actor ? accountName(actor) : "Système RBI",
        action: a.action,
        object_type: a.object_type,
        object_repr: a.object_type === "Alerte" ? `ALR-2026-${String(1000 + Math.floor(rand() * 36)).padStart(6, "0")}` : `${a.object_type} #${Math.floor(rand() * 900 + 100)}`,
        ip_address: `10.0.${o}.${Math.floor(rand() * 200 + 10)}`,
        result: failed ? "echec" : "succes",
        old_value: a.action === "alert.status_changed" ? { status: "EN_COURS" } : null,
        new_value: a.action === "alert.status_changed" ? { status: "EXAMINEE" } : null,
        hash: Array.from({ length: 64 }, () => Math.floor(rand() * 16).toString(16)).join(""),
      });
    }
  });
  return rows;
}

export const AUDIT: AuditRow[] = buildAudit();

export const SETTINGS: Record<string, OrganizationSettings> = Object.fromEntries(
  ORGS.map((org) => [
    org.id,
    {
      version: 3,
      updated_at: new Date(Date.now() - 6 * DAY).toISOString(),
      updated_by: `Démo Administrateur ${org.short_name.slice(-1)}`,
      identity: { name: org.name, short_name: org.short_name },
      timezone: org.timezone,
      retention_days: 730,
      thresholds: [
        { code: "z_score", label: "Seuil d'écart statistique |z|", value: 3, unit: "σ robuste" },
        { code: "history_pct", label: "Variation vs historique", value: 30, unit: "%" },
        { code: "repetition", label: "Répétitions d'un même événement (72 h)", value: 4, unit: "occurrences" },
        { code: "cooldown", label: "Période de silence entre alertes identiques", value: 6, unit: "heures" },
      ],
      risk_weights: FACTOR_CATALOG.map((f) => ({ code: f.code, label: f.label, max_points: f.max })),
      notifications: { email_on_high: true, email_on_critical: true, daily_brief_email: false },
      history: [
        { version: 3, at: new Date(Date.now() - 6 * DAY).toISOString(), by: "Administrateur institutionnel", comment: "Ajustement du seuil de répétition" },
        { version: 2, at: new Date(Date.now() - 40 * DAY).toISOString(), by: "Administrateur institutionnel", comment: "Pondérations initiales validées" },
        { version: 1, at: new Date(Date.now() - 90 * DAY).toISOString(), by: "Système RBI", comment: "Valeurs par défaut" },
      ],
    } satisfies OrganizationSettings,
  ]),
);

export const PLATFORM_ORGS: PlatformOrganization[] = [
  ...ORGS.map((org, o) => ({
    ...org,
    users_count: ACCOUNTS.filter((a) => a.orgId === org.id).length,
    authorization_reference: `CONV-DEMO-2026-00${o + 1}`,
    valid_from: "2026-09-01",
    valid_until: "2027-08-31",
    created_at: new Date(Date.now() - 60 * DAY).toISOString(),
  })),
  {
    id: mockUuid(1, 3),
    name: "Organisme Démo C",
    short_name: "DEMO-C",
    type: "transport",
    status: "SUSPENDUE",
    country_code: "XX",
    timezone: "Africa/Lome",
    deployment_mode: "mutualise",
    is_demo: true,
    users_count: 3,
    authorization_reference: "CONV-DEMO-2026-003",
    valid_from: "2026-05-01",
    valid_until: "2026-09-30",
    created_at: new Date(Date.now() - 150 * DAY).toISOString(),
  },
];

export const ACCESS_REQUESTS: AccessRequest[] = [
  {
    id: mockUuid(95, 1),
    organization_name: "Organisme Démo D",
    requester_name: "Responsable Démo",
    requester_role: "Directeur des systèmes d'information",
    email: "dsi@demo-d.rbi.test",
    request_type: "demonstration",
    created_at: new Date(Date.now() - 2 * DAY).toISOString(),
  },
];
