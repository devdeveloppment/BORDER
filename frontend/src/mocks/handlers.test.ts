/**
 * Tests du CONTRAT de l'API simulée. Ils fixent le comportement attendu que le backend Django
 * devra reproduire en P2 (les mêmes scénarios y seront rejoués contre la vraie API).
 */
import { describe, expect, it } from "vitest";
import type { AlertDetail, CurrentUser } from "@/lib/api/types";
import { ACCOUNTS as EMAILS, apiGet, apiPost, signIn } from "@/test/utils";
import { ALERTS, MOCK_PASSWORD, ORGS } from "./db";

const alertOf = (orgIndex: number) => ALERTS.find((a) => a.orgId === ORGS[orgIndex]!.id)!;

describe("authentification", () => {
  it("refuse l'accès sans session (401)", async () => {
    expect((await apiGet("/dashboard")).status).toBe(401);
    expect((await apiGet("/me")).status).toBe(401);
  });

  it("renvoie un message générique pour un compte inconnu ou un mauvais mot de passe", async () => {
    const unknown = await apiPost("/auth/login", { email: "inconnu@demo-a.rbi.test", password: MOCK_PASSWORD });
    const wrong = await apiPost("/auth/login", { email: EMAILS.supervisorA, password: "mauvais" });
    expect(unknown.status).toBe(401);
    expect(wrong.status).toBe(401);
    expect((await unknown.json()).title).toBe((await wrong.json()).title);
  });

  it("exige la MFA pour un rôle sensible avant tout accès", async () => {
    const res = await apiPost("/auth/login", { email: EMAILS.supervisorA, password: MOCK_PASSWORD });
    expect((await res.json()).step).toBe("MFA_REQUIRED");
    expect((await apiGet("/dashboard")).status).toBe(401);
    expect((await apiPost("/auth/mfa/verify", { code: "000000" })).status).toBe(400);
  });

  it("déduit l'organisme de la session, jamais du client", async () => {
    await signIn(EMAILS.supervisorA);
    const me = (await (await apiGet("/me")).json()) as CurrentUser;
    expect(me.organization?.name).toBe("Organisme Démo A");
  });
});

describe("cloisonnement des organismes (CA-03)", () => {
  it("renvoie 404 pour une alerte d'un autre organisme, sans en révéler l'existence", async () => {
    await signIn(EMAILS.supervisorA);
    expect((await apiGet(`/alerts/${alertOf(0).id}`)).status).toBe(200);
    expect((await apiGet(`/alerts/${alertOf(1).id}`)).status).toBe(404);
  });

  it("ignore un filtre manipulé pointant vers un poste d'un autre organisme", async () => {
    await signIn(EMAILS.supervisorA);
    const res = await apiGet(`/alerts?post=${alertOf(1).border_post.id}`);
    expect((await res.json()).count).toBe(0);
  });

  it("ne liste que les postes de l'organisme courant", async () => {
    await signIn(EMAILS.supervisorB);
    const posts = (await (await apiGet("/border-posts")).json()) as { id: string }[];
    const own = new Set(posts.map((p) => p.id));
    expect(posts).toHaveLength(10);
    expect(own.has(alertOf(0).border_post.id)).toBe(false);
  });

  it("n'expose aucune donnée opérationnelle au Super Admin", async () => {
    await signIn(EMAILS.superAdmin);
    expect((await apiGet("/dashboard")).status).toBe(403);
    expect((await apiGet("/activities")).status).toBe(403);
    expect((await apiGet("/platform/organizations")).status).toBe(200);
  });
});

describe("permissions (CA-16)", () => {
  it("interdit à l'Auditeur toute action sur une alerte", async () => {
    await signIn(EMAILS.auditorA);
    const res = await apiPost(`/alerts/${alertOf(0).id}/actions`, { action: "OBSERVATION", comment: "test" });
    expect(res.status).toBe(403);
  });

  it("limite l'Agent aux alertes qui lui sont assignées et à EXAMINÉE", async () => {
    await signIn(EMAILS.agentA);
    const list = (await (await apiGet("/alerts")).json()) as { results: { id: string; assignee: { name: string } | null }[] };
    expect(list.results.every((a) => a.assignee?.name === "Démo Agent A")).toBe(true);
    const own = list.results[0];
    if (own) {
      const detail = (await (await apiGet(`/alerts/${own.id}`)).json()) as AlertDetail;
      expect(detail.allowed_transitions).not.toContain("CONFIRMEE");
      expect(detail.allowed_transitions).not.toContain("ECARTEE");
    }
  });

  it("refuse la gestion des utilisateurs à un Superviseur", async () => {
    await signIn(EMAILS.supervisorA);
    expect((await apiGet("/users")).status).toBe(403);
  });

  it("exige un motif pour confirmer ou écarter", async () => {
    await signIn(EMAILS.supervisorA);
    const target = ALERTS.find((a) => a.orgId === ORGS[0]!.id && a.status === "EXAMINEE")!;
    const res = await apiPost(`/alerts/${target.id}/actions`, { action: "CHANGEMENT_STATUT", to_status: "CONFIRMEE" });
    expect(res.status).toBe(400);
  });
});
