/**
 * Handlers MSW — simulation de l'API /api/v1 (maquette Phase 1, puis modules reportés en mode intégré, P2.10).
 *
 * - `handlers` : toutes les routes (mode « tout simulé »).
 * - `deferredHandlers` : uniquement les modules métier non encore implémentés par le backend (mode intégré) ;
 *   les routes livrées (authentification, comptes, organisme, audit, plateforme, demande d'accès) partent alors
 *   vers l'API réelle. En mode intégré, l'identité simulée est l'identité réelle (`/me`).
 *
 * Ils reproduisent le CONTRAT attendu du backend (codes HTTP, RFC 9457, cloisonnement par organisme,
 * 404 hors organisme, 403 sans permission) afin que les écrans soient construits contre un
 * comportement réaliste. L'implémentation de référence de ces règles sera le backend Django (P2).
 * Chaque réponse porte l'en-tête `X-RBI-Mock: true`.
 */
import { delay, http, HttpResponse, type JsonBodyType } from "msw";
import type {
  ActivityDetail,
  AlertDetail,
  AlertStatus,
  AnalysisData,
  BorderPost,
  BorderPostDetail,
  CurrentUser,
  DailyBrief,
  DashboardData,
  Level,
  Paginated,
  PeriodKey,
  ReportType,
  TimePoint,
} from "@/lib/api/types";
import { levelFromScore } from "@/lib/labels";
import { integratedIdentity } from "@/lib/integratedIdentity";
import { PERMISSIONS, type Permission } from "@/lib/permissions";
import {
  ACCESS_REQUESTS,
  ACCOUNTS,
  ACTIVITIES,
  ALERTS,
  AUDIT,
  MFA_REQUIRED_ROLES,
  MOCK_PASSWORD,
  MOCK_TOTP,
  NOTIFICATIONS,
  ORGS,
  PLATFORM_ORGS,
  REPORTS,
  SETTINGS,
  TRANSITIONS,
  accountName,
  dayStartOffset,
  dayVolume,
  eventsCount,
  hourlyVolume,
  nowRef,
  postsOf,
  type MockAccount,
} from "./db";
import { mockUuid } from "./rng";
import { mockPermissionsForRoles as permissionsForRoles } from "./roles";

const BASE = "/api/v1";
let integrated = false;
const DAY = 86_400_000;
const MOCK_HEADERS = { "X-RBI-Mock": "true" };
const SESSION_KEY = "rbi.mock.session";

// ---------------------------------------------------------------------------
// Session simulée (le vrai backend utilisera un cookie de session HttpOnly)
// ---------------------------------------------------------------------------

interface MockSession {
  accountId: string;
  mfaPassed: boolean;
}

let memorySession: MockSession | null = null;

function readSession(): MockSession | null {
  try {
    const raw = globalThis.sessionStorage?.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as MockSession) : memorySession;
  } catch {
    return memorySession;
  }
}

function writeSession(session: MockSession | null): void {
  memorySession = session;
  try {
    if (session) globalThis.sessionStorage?.setItem(SESSION_KEY, JSON.stringify(session));
    else globalThis.sessionStorage?.removeItem(SESSION_KEY);
  } catch {
    /* stockage indisponible : la session reste en mémoire */
  }
}

export function resetMockSession(): void {
  writeSession(null);
}

function json(body: JsonBodyType, status = 200) {
  return HttpResponse.json(body, { status, headers: MOCK_HEADERS });
}

function problem(status: number, title: string, detail?: string, errors?: Record<string, string[]>) {
  return HttpResponse.json(
    { type: "about:blank", title, status, detail, errors },
    { status, headers: { ...MOCK_HEADERS, "Content-Type": "application/problem+json" } },
  );
}

const notFound = () => problem(404, "Ressource introuvable");
// Mode intégré : l'absence de contexte simulé (compte plateforme, identité pas encore publiée) n'est PAS une
// session expirée — 403, pour ne jamais déclencher la déconnexion d'une session réelle.
const unauthenticated = () => (integrated ? problem(403, "Vous n'avez pas accès à cette ressource") : problem(401, "Authentification requise"));
const forbidden = () => problem(403, "Vous n'avez pas accès à cette ressource");

interface Ctx {
  account: MockAccount;
  orgId: string | null;
  perms: Set<Permission>;
  postIds: Set<string> | null; // restriction aux postes affectés (Agent)
}

/** Mode intégré : le contexte des modules reportés vient de l'identité réelle publiée par la session. */
export function setIntegratedMode(enabled: boolean): void {
  integrated = enabled;
}

/** Jeu de données simulé d'un utilisateur réel : celui du premier organisme fictif, avec SES permissions. */
function integratedContext(): Ctx | null {
  const user = integratedIdentity();
  if (!user?.organization) return null;
  const orgId = ORGS[0]!.id;
  const account = ACCOUNTS.find((a) => a.orgId === orgId && a.roles.some((r) => user.roles.includes(r)))
    ?? ACCOUNTS.find((a) => a.orgId === orgId)!;
  return { account, orgId, perms: new Set(user.permissions as Permission[]), postIds: null };
}

/** Résout le contexte depuis la session — jamais depuis un paramètre client. */
function context(): Ctx | null {
  if (integrated) return integratedContext();
  const session = readSession();
  if (!session?.mfaPassed) return null;
  const account = ACCOUNTS.find((a) => a.id === session.accountId && a.is_active);
  if (!account) return null;
  const perms = new Set(permissionsForRoles(account.roles));
  const restricted = account.roles.length === 1 && account.roles[0] === "AGENT";
  const postIds = restricted && account.orgId
    ? new Set(postsOf(account.orgId).filter((p) => account.assigned_posts.includes(p.code)).map((p) => p.id))
    : null;
  return { account, orgId: account.orgId, perms, postIds };
}

type Guard = { ctx: Ctx; orgId: string } | { error: Response };

function guardOrg(permission: Permission): Guard {
  const ctx = context();
  if (!ctx) return { error: unauthenticated() };
  if (!ctx.orgId) return { error: forbidden() };
  if (!ctx.perms.has(permission)) return { error: forbidden() };
  return { ctx, orgId: ctx.orgId };
}

function toCurrentUser(account: MockAccount): CurrentUser {
  const org = ORGS.find((o) => o.id === account.orgId) ?? null;
  return {
    id: account.id,
    email: account.email,
    first_name: account.first_name,
    last_name: account.last_name,
    roles: account.roles,
    permissions: permissionsForRoles(account.roles),
    organization: org,
    mfa_enabled: account.mfa_enabled,
    mfa_required: account.roles.some((r) => MFA_REQUIRED_ROLES.includes(r)),
    assigned_post_ids: org ? postsOf(org.id).filter((p) => account.assigned_posts.includes(p.code)).map((p) => p.id) : [],
    last_login: account.last_login,
  };
}

function paginate<T>(rows: T[], url: URL, pageSize = 50): Paginated<T> {
  const page = Math.max(1, Number(url.searchParams.get("page") ?? 1) || 1);
  return { count: rows.length, page, page_size: pageSize, results: rows.slice((page - 1) * pageSize, page * pageSize) };
}

// ---------------------------------------------------------------------------
// Calculs simulés (en P3/P7 : agrégations SQL côté serveur)
// ---------------------------------------------------------------------------

const PERIOD_DAYS: Record<PeriodKey, number> = { today: 1, "7d": 7, "30d": 30, "90d": 90, "365d": 365 };

function parsePeriod(url: URL): PeriodKey {
  const p = url.searchParams.get("period");
  return p && p in PERIOD_DAYS ? (p as PeriodKey) : "7d";
}

function visiblePosts(ctx: Ctx, orgId: string) {
  return postsOf(orgId).filter((p) => !ctx.postIds || ctx.postIds.has(p.id));
}

function postScore(post: ReturnType<typeof postsOf>[number]): number {
  const open = ALERTS.filter((a) => a.border_post.id === post.id && !["CLOTUREE", "ECARTEE"].includes(a.status));
  if (open.length === 0) return 12 + (post.idx % 4) * 6;
  return Math.max(...open.map((a) => a.score));
}

function seriesFor(posts: ReturnType<typeof postsOf>, period: PeriodKey): TimePoint[] {
  const now = nowRef();
  if (period === "today") {
    const today = dayStartOffset(0);
    const lastWeek = dayStartOffset(7);
    return Array.from({ length: now.getHours() + 1 }, (_, h) => ({
      bucket: `${String(h).padStart(2, "0")} h`,
      value: posts.reduce((s, p) => s + hourlyVolume(p, today, h), 0),
      previous: posts.reduce((s, p) => s + hourlyVolume(p, lastWeek, h), 0),
    }));
  }
  const days = PERIOD_DAYS[period];
  const step = period === "365d" ? 30 : period === "90d" ? 7 : 1;
  const points: TimePoint[] = [];
  for (let start = days - 1; start >= 0; start -= step) {
    let value = 0;
    let previous = 0;
    for (let d = start; d > start - step && d >= 0; d--) {
      for (const p of posts) {
        value += d === 0 ? dayVolume(p, dayStartOffset(0), now.getHours()) : dayVolume(p, dayStartOffset(d));
        // Le jour en cours est comparé à la même plage horaire (journée partielle vs partielle).
        previous += d === 0 ? dayVolume(p, dayStartOffset(d + days), now.getHours()) : dayVolume(p, dayStartOffset(d + days));
      }
    }
    const date = dayStartOffset(start);
    points.push({
      bucket: step === 1 ? date.toISOString().slice(0, 10) : `${step === 7 ? "Sem." : "Mois"} ${date.toISOString().slice(5, 10).split("-").reverse().join("/")}`,
      value,
      previous,
    });
  }
  return points;
}

function dailyBrief(orgId: string, ctx: Ctx): DailyBrief {
  const posts = visiblePosts(ctx, orgId);
  const today = posts.map((p) => ({ p, v: dayVolume(p, dayStartOffset(0), nowRef().getHours()) }));
  const ref = posts.map((p) => {
    let s = 0;
    for (let w = 1; w <= 4; w++) s += dayVolume(p, dayStartOffset(7 * w), nowRef().getHours());
    return { p, v: s / 4 };
  });
  const total = today.reduce((s, x) => s + x.v, 0);
  const refTotal = ref.reduce((s, x) => s + x.v, 0) || 1;
  const top = [...today].sort((a, b) => b.v - a.v)[0];
  const variations = today
    .map((x, i) => ({ p: x.p, pct: ((x.v - (ref[i]?.v ?? 0)) / Math.max(1, ref[i]?.v ?? 1)) * 100 }))
    .sort((a, b) => b.pct - a.pct);
  const since = nowRef().getTime() - DAY;
  const newAlerts = ALERTS.filter((a) => a.orgId === orgId && new Date(a.detected_at).getTime() >= since);
  const toReview = ALERTS.filter((a) => a.orgId === orgId && (a.status === "NOUVELLE" || a.status === "EN_COURS") && (a.level === "ELEVE" || a.level === "CRITIQUE"));
  const pct = Math.round(((total - refTotal) / refTotal) * 100);
  const big = variations[0];
  return {
    generated_at: nowRef().toISOString(),
    items: [
      { heading: "Activité", text: `${pct >= 0 ? "+" : ""}${pct} % par rapport à la moyenne des 4 mêmes jours précédents` },
      { heading: "Alertes", text: `${newAlerts.length} nouvelle(s) alerte(s) sur 24 h (${newAlerts.filter((a) => a.level === "ELEVE").length} élevée(s), ${newAlerts.filter((a) => a.level === "CRITIQUE").length} critique(s))` },
      { heading: "Poste le plus actif", text: top ? top.p.name : "—" },
      { heading: "Variation importante", text: big ? `${big.pct >= 0 ? "+" : ""}${Math.round(big.pct)} % au ${big.p.name}` : "—" },
      { heading: "Points à examiner", text: `${toReview.length} situation(s) nécessitant une vérification` },
    ],
    disclaimer: "Synthèse analytique générée automatiquement — ne constitue pas une décision.",
  };
}

function alertsVisible(ctx: Ctx, orgId: string) {
  return ALERTS.filter((a) => a.orgId === orgId && (!ctx.postIds || a.assignee?.id === ctx.account.id));
}

function allowedTransitions(ctx: Ctx, status: AlertStatus): AlertStatus[] {
  const next = TRANSITIONS[status];
  if (ctx.perms.has(PERMISSIONS.alertsDecide)) return next;
  // Agent : jusqu'à EXAMINÉE uniquement (§7.2 D, §17.2)
  if (ctx.perms.has(PERMISSIONS.alertsTake)) return next.filter((s) => s === "EN_COURS" || s === "EXAMINEE");
  return [];
}

// ---------------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------------

export const handlers = [
  // --- Authentification ----------------------------------------------------
  http.get(`${BASE}/auth/csrf`, () => {
    // Le vrai backend pose le cookie par Set-Cookie ; la simulation l'écrit directement (valeur sans portée).
    if (typeof document !== "undefined") document.cookie = "csrftoken=mock-csrf-token; path=/; SameSite=Strict";
    return new HttpResponse(null, { status: 204, headers: MOCK_HEADERS });
  }),

  http.post(`${BASE}/auth/login`, async ({ request }) => {
    await delay(250);
    const body = (await request.json()) as { email?: string; password?: string };
    const account = ACCOUNTS.find((a) => a.email.toLowerCase() === (body.email ?? "").trim().toLowerCase());
    // Message générique : aucune indication sur l'existence du compte (écran 6)
    if (!account || !account.is_active || body.password !== MOCK_PASSWORD) {
      return problem(401, "Identifiants incorrects");
    }
    const org = PLATFORM_ORGS.find((o) => o.id === account.orgId);
    if (org && org.status === "SUSPENDUE") return problem(403, "Organisme suspendu", "L'accès de votre organisme est temporairement suspendu.");
    const mfa = account.mfa_enabled || account.roles.some((r) => MFA_REQUIRED_ROLES.includes(r));
    writeSession({ accountId: account.id, mfaPassed: !mfa });
    return json({ step: mfa ? "MFA_REQUIRED" : "AUTHENTICATED" });
  }),

  http.post(`${BASE}/auth/mfa/verify`, async ({ request }) => {
    await delay(200);
    const session = readSession();
    if (!session) return problem(401, "Session expirée", "Veuillez vous reconnecter.");
    const body = (await request.json()) as { code?: string };
    if (body.code !== MOCK_TOTP) return problem(400, "Code invalide ou expiré");
    writeSession({ ...session, mfaPassed: true });
    return json({ step: "AUTHENTICATED" });
  }),

  http.post(`${BASE}/auth/logout`, () => {
    writeSession(null);
    return new HttpResponse(null, { status: 204, headers: MOCK_HEADERS });
  }),

  http.post(`${BASE}/auth/password-reset`, async () => {
    await delay(300);
    // Réponse identique que le compte existe ou non (écran 8)
    return json({ detail: "Si un compte correspond, un lien de réinitialisation a été envoyé." }, 202);
  }),

  http.post(`${BASE}/auth/password-reset/confirm`, async ({ request }) => {
    await delay(300);
    const body = (await request.json()) as { token?: string; password?: string };
    if (body.token !== "demo-token") return problem(400, "Lien expiré ou invalide");
    if (!body.password || body.password.length < 12) {
      return problem(400, "Mot de passe non conforme", undefined, { password: ["12 caractères minimum."] });
    }
    return new HttpResponse(null, { status: 204, headers: MOCK_HEADERS });
  }),

  http.get(`${BASE}/me`, () => {
    const ctx = context();
    if (!ctx) return unauthenticated();
    return json(toCurrentUser(ctx.account) as unknown as JsonBodyType);
  }),

  // --- Public --------------------------------------------------------------
  http.post(`${BASE}/public/access-requests`, async ({ request }) => {
    await delay(400);
    const body = (await request.json()) as Record<string, string>;
    const errors: Record<string, string[]> = {};
    for (const field of ["organization", "role", "name", "email", "request_type"]) {
      if (!body[field]?.trim()) errors[field] = ["Champ obligatoire."];
    }
    if (body.email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(body.email)) errors.email = ["Adresse email invalide."];
    if (body.consent !== "true") errors.consent = ["Le consentement est requis."];
    if (Object.keys(errors).length) return problem(400, "Formulaire incomplet", undefined, errors);
    return json({ detail: "Demande enregistrée." }, 201);
  }),

  // --- Dashboard -----------------------------------------------------------
  http.get(`${BASE}/dashboard`, async ({ request }) => {
    const g = guardOrg(PERMISSIONS.dashboardView);
    if ("error" in g) return g.error;
    await delay(250);
    const url = new URL(request.url);
    const period = parsePeriod(url);
    const posts = visiblePosts(g.ctx, g.orgId);
    const series = seriesFor(posts, period);
    const activities = series.reduce((s, x) => s + x.value, 0);
    const prevActivities = series.reduce((s, x) => s + x.previous, 0);
    const from = period === "today" ? dayStartOffset(0).getTime() : nowRef().getTime() - PERIOD_DAYS[period] * DAY;
    const prevFrom = from - (period === "today" ? DAY : PERIOD_DAYS[period] * DAY);
    const orgAlerts = alertsVisible(g.ctx, g.orgId);
    const inPeriod = orgAlerts.filter((a) => new Date(a.detected_at).getTime() >= from);
    const inPrev = orgAlerts.filter((a) => {
      const t = new Date(a.detected_at).getTime();
      return t >= prevFrom && t < from;
    });
    const data: DashboardData = {
      period,
      kpis: {
        activities,
        controls: Math.round(activities * 0.249),
        vehicles: Math.round(activities * 0.61),
        events: eventsCount(g.orgId, from),
        alerts: inPeriod.length,
        critical_alerts: inPeriod.filter((a) => a.level === "CRITIQUE").length,
        open_alerts: orgAlerts.filter((a) => ["NOUVELLE", "EN_COURS", "EXAMINEE"].includes(a.status)).length,
        processed_alerts: orgAlerts.filter((a) => ["CONFIRMEE", "ECARTEE", "CLOTUREE"].includes(a.status)).length,
        active_posts: posts.filter((p) => p.status === "actif").length,
        total_posts: posts.length,
        previous: {
          activities: prevActivities,
          controls: Math.round(prevActivities * 0.249),
          vehicles: Math.round(prevActivities * 0.61),
          events: eventsCount(g.orgId, prevFrom) - eventsCount(g.orgId, from),
          alerts: inPrev.length,
        },
      },
      series,
      posts: posts.map((p) => {
        const score = postScore(p);
        return {
          id: p.id,
          code: p.code,
          name: p.name,
          location: { lat: p.lat, lng: p.lng, region: "Région Démo", locality: `Localité Démo ${p.idx + 1}` },
          level: levelFromScore(score),
          risk_score: score,
          open_alerts: orgAlerts.filter((a) => a.border_post.id === p.id && ["NOUVELLE", "EN_COURS", "EXAMINEE"].includes(a.status)).length,
        };
      }),
      recent_alerts: orgAlerts.slice(0, 6).map(stripAlert),
      brief: dailyBrief(g.orgId, g.ctx),
    };
    return json(data as unknown as JsonBodyType);
  }),

  // --- Postes --------------------------------------------------------------
  http.get(`${BASE}/border-posts`, async () => {
    const g = guardOrg(PERMISSIONS.postsView);
    if ("error" in g) return g.error;
    await delay(200);
    return json(visiblePosts(g.ctx, g.orgId).map((p) => toBorderPost(p, g.orgId)) as unknown as JsonBodyType);
  }),

  http.get(`${BASE}/border-posts/:id`, async ({ params }) => {
    const g = guardOrg(PERMISSIONS.postsView);
    if ("error" in g) return g.error;
    await delay(200);
    const post = visiblePosts(g.ctx, g.orgId).find((p) => p.id === params.id);
    if (!post) return notFound();
    const base = toBorderPost(post, g.orgId);
    const today = dayStartOffset(0);
    const hourly = Array.from({ length: 24 }, (_, h) => {
      let ref = 0;
      for (let w = 1; w <= 4; w++) ref += hourlyVolume(post, dayStartOffset(7 * w), h);
      return { hour: h, volume: h <= nowRef().getHours() ? hourlyVolume(post, today, h) : 0, reference: Math.round(ref / 4) };
    });
    const peak = Math.max(...hourly.map((x) => x.volume));
    const detail: BorderPostDetail = {
      ...base,
      opening_hours: post.post_type === "aeroportuaire" ? "05 h – 23 h" : "24 h / 24",
      assigned_agents: ACCOUNTS.filter((a) => a.orgId === g.orgId && a.assigned_posts.includes(post.code)).map((a) => ({ id: a.id, name: accountName(a) })),
      utilization_pct: post.capacity ? Math.round((peak / post.capacity) * 100) : 0,
      avg_processing_minutes: 11.4 + (post.idx % 5) * 1.7,
      controls_today: Math.round(base.today_volume * 0.249),
      hourly,
    };
    return json(detail as unknown as JsonBodyType);
  }),

  // --- Activités -----------------------------------------------------------
  http.get(`${BASE}/activities`, async ({ request }) => {
    const g = guardOrg(PERMISSIONS.activitiesView);
    if ("error" in g) return g.error;
    await delay(250);
    const url = new URL(request.url);
    const q = (url.searchParams.get("search") ?? "").trim().toLowerCase();
    const post = url.searchParams.get("post");
    const type = url.searchParams.get("activity_type");
    const level = url.searchParams.get("level");
    const status = url.searchParams.get("status");
    const rows = ACTIVITIES.filter(
      (a) =>
        a.orgId === g.orgId &&
        (!g.ctx.postIds || g.ctx.postIds.has(a.border_post.id)) &&
        (!q || a.reference.toLowerCase().includes(q) || (a.operational_ref ?? "").toLowerCase().includes(q)) &&
        (!post || a.border_post.id === post) &&
        (!type || a.activity_type === type) &&
        (!level || a.level === level) &&
        (!status || a.status === status),
    ).map(({ orgId: _o, ...rest }) => rest);
    return json(paginate(rows, url) as unknown as JsonBodyType);
  }),

  http.get(`${BASE}/activities/:id`, async ({ params }) => {
    const g = guardOrg(PERMISSIONS.activitiesView);
    if ("error" in g) return g.error;
    await delay(150);
    const row = ACTIVITIES.find((a) => a.id === params.id && a.orgId === g.orgId);
    if (!row || (g.ctx.postIds && !g.ctx.postIds.has(row.border_post.id))) return notFound();
    const { orgId: _o, ...activity } = row;
    const linked = ALERTS.filter((a) => a.orgId === g.orgId && a.border_post.id === row.border_post.id && row.level !== "NORMAL").slice(0, 2);
    const detail: ActivityDetail = {
      ...activity,
      import_job: activity.source.source_type === "fichier" ? { id: mockUuid(99, 1), file_name: "activites_demo_septembre.csv" } : null,
      linked_alerts: linked.map((a) => ({ id: a.id, reference: a.reference, title: a.title, level: a.level })),
      history: activity.status === "validee" ? [] : [{ at: activity.updated_at, actor: "Démo Agent A", field: "status", old_value: "enregistree", new_value: activity.status }],
    };
    return json(detail as unknown as JsonBodyType);
  }),

  // --- Alertes -------------------------------------------------------------
  http.get(`${BASE}/alerts`, async ({ request }) => {
    const g = guardOrg(PERMISSIONS.alertsView);
    if ("error" in g) return g.error;
    await delay(250);
    const url = new URL(request.url);
    const p = url.searchParams;
    const visible = alertsVisible(g.ctx, g.orgId);
    const rows = visible.filter(
      (a) =>
        (!p.get("status") || a.status === p.get("status")) &&
        (!p.get("level") || a.level === p.get("level")) &&
        (!p.get("alert_type") || a.alert_type === p.get("alert_type")) &&
        (!p.get("post") || a.border_post.id === p.get("post")),
    );
    const counts = Object.fromEntries(
      (["NOUVELLE", "EN_COURS", "EXAMINEE", "CONFIRMEE", "ECARTEE", "CLOTUREE"] as AlertStatus[]).map((s) => [s, visible.filter((a) => a.status === s).length]),
    );
    return json({ ...paginate(rows.map(stripAlert), url, 25), status_counts: counts, total: visible.length } as unknown as JsonBodyType);
  }),

  http.get(`${BASE}/alerts/:id`, async ({ params }) => {
    const g = guardOrg(PERMISSIONS.alertsView);
    if ("error" in g) return g.error;
    await delay(200);
    const alert = alertsVisible(g.ctx, g.orgId).find((a) => a.id === params.id);
    if (!alert) return notFound();
    return json(toAlertDetail(alert, g.ctx) as unknown as JsonBodyType);
  }),

  http.post(`${BASE}/alerts/:id/actions`, async ({ params, request }) => {
    const g = guardOrg(PERMISSIONS.alertsView);
    if ("error" in g) return g.error;
    await delay(250);
    const alert = alertsVisible(g.ctx, g.orgId).find((a) => a.id === params.id);
    if (!alert) return notFound();
    const body = (await request.json()) as { action: string; to_status?: AlertStatus; comment?: string };
    const actor = accountName(g.ctx.account);
    const at = new Date().toISOString();
    if (body.action === "OBSERVATION") {
      if (!g.ctx.perms.has(PERMISSIONS.alertsComment)) return forbidden();
      if (!body.comment?.trim()) return problem(400, "Observation vide", undefined, { comment: ["Champ obligatoire."] });
      alert.actions.push({ id: crypto.randomUUID(), at, actor, action: "OBSERVATION", from_status: null, to_status: null, comment: body.comment.trim() });
    } else if (body.action === "CHANGEMENT_STATUT" && body.to_status) {
      if (!allowedTransitions(g.ctx, alert.status).includes(body.to_status)) return forbidden();
      const needsReason = ["EXAMINEE", "CONFIRMEE", "ECARTEE", "CLOTUREE"].includes(body.to_status);
      if (needsReason && !body.comment?.trim()) return problem(400, "Motif obligatoire", undefined, { comment: ["Un motif est obligatoire pour ce changement de statut."] });
      alert.actions.push({ id: crypto.randomUUID(), at, actor, action: "CHANGEMENT_STATUT", from_status: alert.status, to_status: body.to_status, comment: body.comment?.trim() ?? null });
      if (body.to_status === "EN_COURS" && !alert.assignee) alert.assignee = { id: g.ctx.account.id, name: actor };
      alert.status = body.to_status;
    } else {
      return problem(400, "Action inconnue");
    }
    return json(toAlertDetail(alert, g.ctx) as unknown as JsonBodyType);
  }),

  // --- Analyse -------------------------------------------------------------
  http.get(`${BASE}/analytics/compare`, async ({ request }) => {
    const g = guardOrg(PERMISSIONS.analyticsView);
    if ("error" in g) return g.error;
    await delay(300);
    const url = new URL(request.url);
    const days = Math.min(90, Math.max(7, Number(url.searchParams.get("days") ?? 28) || 28));
    const posts = visiblePosts(g.ctx, g.orgId);
    const series = Array.from({ length: days }, (_, i) => {
      const d = days - i;
      return {
        bucket: dayStartOffset(d).toISOString().slice(0, 10),
        a: posts.reduce((s, p) => s + dayVolume(p, dayStartOffset(d)), 0),
        b: posts.reduce((s, p) => s + dayVolume(p, dayStartOffset(d + days)), 0),
      };
    });
    const heat = new Map<string, number>();
    for (let d = 1; d <= 28; d++) {
      const date = dayStartOffset(d);
      for (let h = 0; h < 24; h++) {
        const key = `${date.getDay()}-${h}`;
        heat.set(key, (heat.get(key) ?? 0) + posts.reduce((s, p) => s + hourlyVolume(p, date, h), 0));
      }
    }
    const byPost = posts.map((p) => {
      let a = 0;
      let b = 0;
      for (let d = 1; d <= days; d++) {
        a += dayVolume(p, dayStartOffset(d));
        b += dayVolume(p, dayStartOffset(d + days));
      }
      return { code: p.code, name: p.name, a, b, variation_pct: b ? ((a - b) / b) * 100 : 0 };
    });
    const totalA = byPost.reduce((s, x) => s + x.a, 0);
    const totalB = byPost.reduce((s, x) => s + x.b, 0);
    const shares = [0.34, 0.22, 0.17, 0.12, 0.09, 0.06];
    const data: AnalysisData = {
      period_a: `${days} derniers jours`,
      period_b: `${days} jours précédents`,
      series,
      heatmap: [...heat.entries()].map(([k, value]) => {
        const [day, hour] = k.split("-").map(Number);
        return { day: day ?? 0, hour: hour ?? 0, value: Math.round(value / 4) };
      }),
      by_post: byPost,
      by_category: ["Marchandises", "Passagers", "Transit", "Fret léger", "Hydrocarbures", "Agricole"].map((category, i) => ({
        category,
        a: Math.round(totalA * (shares[i] ?? 0)),
        b: Math.round(totalB * (shares[i] ?? 0) * (1 + (i % 2 ? 0.04 : -0.03))),
      })),
    };
    return json(data as unknown as JsonBodyType);
  }),

  // --- Rapports ------------------------------------------------------------
  http.get(`${BASE}/reports`, async () => {
    const g = guardOrg(PERMISSIONS.reportsView);
    if ("error" in g) return g.error;
    await delay(200);
    return json(REPORTS.filter((r) => r.orgId === g.orgId).map(({ orgId: _o, ...r }) => r) as unknown as JsonBodyType);
  }),

  http.post(`${BASE}/reports`, async ({ request }) => {
    const g = guardOrg(PERMISSIONS.reportsGenerate);
    if ("error" in g) return g.error;
    await delay(600);
    const body = (await request.json()) as { report_type?: ReportType; period_start?: string; period_end?: string; format?: "PDF" | "XLSX" | "CSV" };
    if (!body.report_type || !body.period_start || !body.period_end || !body.format) return problem(400, "Paramètres incomplets");
    if (body.period_end < body.period_start) return problem(400, "Période invalide", undefined, { period_end: ["La fin doit suivre le début."] });
    const report = {
      orgId: g.orgId,
      id: crypto.randomUUID(),
      title: `Rapport ${body.report_type} — ${ORGS.find((o) => o.id === g.orgId)?.name ?? ""}`,
      report_type: body.report_type,
      period_start: body.period_start,
      period_end: body.period_end,
      format: body.format,
      generated_by: accountName(g.ctx.account),
      created_at: new Date().toISOString(),
      // La génération réelle (WeasyPrint / openpyxl, asynchrone) est prévue en P8.
      status: "en_attente" as const,
    };
    REPORTS.unshift(report);
    const { orgId: _o, ...out } = report;
    return json(out, 202);
  }),

  // --- Notifications -------------------------------------------------------
  http.get(`${BASE}/notifications`, async () => {
    const ctx = context();
    if (!ctx) return unauthenticated();
    await delay(150);
    const rows = NOTIFICATIONS.filter((n) => n.recipientId === ctx.account.id).sort((a, b) => b.created_at.localeCompare(a.created_at));
    return json(rows.map(({ orgId: _o, recipientId: _r, ...n }) => n) as unknown as JsonBodyType);
  }),

  http.post(`${BASE}/notifications/:id/read`, ({ params }) => {
    const ctx = context();
    if (!ctx) return unauthenticated();
    const n = NOTIFICATIONS.find((x) => x.id === params.id && x.recipientId === ctx.account.id);
    if (!n) return notFound();
    n.read_at ??= new Date().toISOString();
    return new HttpResponse(null, { status: 204, headers: MOCK_HEADERS });
  }),

  http.post(`${BASE}/notifications/read-all`, () => {
    const ctx = context();
    if (!ctx) return unauthenticated();
    for (const n of NOTIFICATIONS) if (n.recipientId === ctx.account.id) n.read_at ??= new Date().toISOString();
    return new HttpResponse(null, { status: 204, headers: MOCK_HEADERS });
  }),

  // --- Audit ---------------------------------------------------------------
  http.get(`${BASE}/audit-logs`, async ({ request }) => {
    const ctx = context();
    if (!ctx) return unauthenticated();
    if (!ctx.perms.has(PERMISSIONS.auditView)) return forbidden();
    await delay(200);
    const url = new URL(request.url);
    const action = url.searchParams.get("action");
    const rows = AUDIT.filter((a) => a.orgId === ctx.orgId && (!action || a.action.startsWith(action))).map(({ orgId: _o, ...r }) => r);
    // Vérification de la chaîne SHA-256 implémentée côté serveur en P2/P9.
    return json({ ...paginate(rows, url), chain_integrity: "non_verifiee" } as unknown as JsonBodyType);
  }),

  // --- Utilisateurs --------------------------------------------------------
  http.get(`${BASE}/users`, async () => {
    const g = guardOrg(PERMISSIONS.usersView);
    if ("error" in g) return g.error;
    await delay(200);
    return json(ACCOUNTS.filter((a) => a.orgId === g.orgId).map(({ orgId: _o, ...u }) => u) as unknown as JsonBodyType);
  }),

  // --- Organisme & paramètres ----------------------------------------------
  http.get(`${BASE}/organization`, async () => {
    const g = guardOrg(PERMISSIONS.organizationView);
    if ("error" in g) return g.error;
    await delay(150);
    const org = PLATFORM_ORGS.find((o) => o.id === g.orgId);
    return org ? json(org as unknown as JsonBodyType) : notFound();
  }),

  http.get(`${BASE}/settings`, async () => {
    const g = guardOrg(PERMISSIONS.settingsView);
    if ("error" in g) return g.error;
    await delay(150);
    return json(SETTINGS[g.orgId] as unknown as JsonBodyType);
  }),

  http.patch(`${BASE}/settings`, async ({ request }) => {
    const g = guardOrg(PERMISSIONS.settingsManage);
    if ("error" in g) return g.error;
    await delay(300);
    const current = SETTINGS[g.orgId];
    if (!current) return notFound();
    const body = (await request.json()) as { thresholds?: { code: string; value: number }[]; retention_days?: number; comment?: string };
    if (body.retention_days !== undefined && (!Number.isInteger(body.retention_days) || body.retention_days <= 0)) {
      return problem(400, "Valeur invalide", undefined, { retention_days: ["Doit être un entier positif."] });
    }
    const next = {
      ...current,
      version: current.version + 1,
      updated_at: new Date().toISOString(),
      updated_by: accountName(g.ctx.account),
      retention_days: body.retention_days ?? current.retention_days,
      thresholds: current.thresholds.map((t) => ({ ...t, value: body.thresholds?.find((x) => x.code === t.code)?.value ?? t.value })),
      history: [{ version: current.version + 1, at: new Date().toISOString(), by: accountName(g.ctx.account), comment: body.comment?.trim() || "Mise à jour des paramètres" }, ...current.history],
    };
    SETTINGS[g.orgId] = next;
    return json(next as unknown as JsonBodyType);
  }),

  // --- Plateforme (Super Admin) ---------------------------------------------
  http.get(`${BASE}/platform/organizations`, async () => {
    const ctx = context();
    if (!ctx) return unauthenticated();
    if (!ctx.perms.has(PERMISSIONS.platformOrganizations)) return forbidden();
    await delay(200);
    return json({ organizations: PLATFORM_ORGS, access_requests: ACCESS_REQUESTS } as unknown as JsonBodyType);
  }),
];

// ---------------------------------------------------------------------------
// Sérialiseurs
// ---------------------------------------------------------------------------

function toBorderPost(p: ReturnType<typeof postsOf>[number], orgId: string): BorderPost {
  const today = dayVolume(p, dayStartOffset(0), nowRef().getHours());
  let ref = 0;
  for (let w = 1; w <= 4; w++) ref += dayVolume(p, dayStartOffset(7 * w), nowRef().getHours());
  ref /= 4;
  const score = postScore(p);
  return {
    id: p.id,
    code: p.code,
    name: p.name,
    post_type: p.post_type,
    status: p.status,
    capacity_per_hour: p.capacity,
    location: { lat: p.lat, lng: p.lng, region: "Région Démo", locality: `Localité Démo ${p.idx + 1}` },
    today_volume: today,
    variation_pct: ref ? ((today - ref) / ref) * 100 : 0,
    open_alerts: ALERTS.filter((a) => a.orgId === orgId && a.border_post.id === p.id && ["NOUVELLE", "EN_COURS", "EXAMINEE"].includes(a.status)).length,
    risk_score: score,
    level: levelFromScore(score) as Level,
  };
}

function stripAlert(a: (typeof ALERTS)[number]) {
  return {
    id: a.id,
    reference: a.reference,
    alert_type: a.alert_type,
    title: a.title,
    border_post: a.border_post,
    level: a.level,
    score: a.score,
    status: a.status,
    assignee: a.assignee,
    detected_at: a.detected_at,
  };
}

function toAlertDetail(a: (typeof ALERTS)[number], ctx: Ctx): AlertDetail {
  const post = postsOf(a.orgId).find((p) => p.id === a.border_post.id);
  const comparison = Array.from({ length: 7 }, (_, i) => {
    const d = 6 - i;
    const date = dayStartOffset(d);
    let ref = 0;
    for (let w = 1; w <= 4; w++) ref += post ? dayVolume(post, dayStartOffset(d + 7 * w)) : 0;
    return {
      label: date.toLocaleDateString("fr-FR", { weekday: "short", day: "2-digit" }),
      observed: post ? dayVolume(post, date, d === 0 ? nowRef().getHours() : 23) : 0,
      reference: Math.round(ref / 4),
    };
  });
  return {
    ...stripAlert(a),
    description: a.description,
    explanation: a.explanation,
    factors: a.factors,
    model_version: "org-v3",
    reference_period: "Moyenne des 4 mêmes jours de semaine précédents",
    comparison,
    linked_activities: ACTIVITIES.filter((x) => x.orgId === a.orgId && x.border_post.id === a.border_post.id)
      .slice(0, 5)
      .map((x) => ({ id: x.id, reference: x.reference, occurred_at: x.occurred_at, activity_type: x.activity_type })),
    actions: [...a.actions].sort((x, y) => y.at.localeCompare(x.at)),
    allowed_transitions: allowedTransitions(ctx, a.status),
    disclaimer: "Indicateur nécessitant une vérification — ne constitue pas une conclusion.",
  };
}

/**
 * Mode « tout simulé » : routes livrées par le backend mais non reproduites par la maquette (gestion des
 * comptes, enrôlement TOTP, cycle de vie des organismes…). Réponse explicite au lieu d'un 404 trompeur.
 */
handlers.push(
  http.all(`${BASE}/*`, () =>
    problem(501, "Action non simulée", "Cette action n'existe pas dans la maquette : utilisez la pile intégrée (API réelle)."),
  ),
);

/**
 * Modules métier reportés (P2.8, rapport « routes reportées ») : seuls simulés en mode intégré. Toute autre
 * route part vers l'API réelle. La liste est vérifiée contre le schéma OpenAPI (src/test/modes.test.ts) : une
 * route simulée ici ne doit PAS exister dans l'API réelle.
 */
export const DEFERRED_PATH_PREFIXES = [
  "/dashboard",
  "/border-posts",
  "/activities",
  "/alerts",
  "/analytics",
  "/reports",
  "/notifications",
  "/settings",
] as const;

export function isDeferredPath(path: string): boolean {
  return DEFERRED_PATH_PREFIXES.some((prefix) => path === prefix || path.startsWith(`${prefix}/`));
}

export const deferredHandlers = handlers.filter((handler) => {
  const path = String((handler.info as { path?: unknown }).path ?? "");
  return isDeferredPath(path.startsWith(BASE) ? path.slice(BASE.length) : path);
});
