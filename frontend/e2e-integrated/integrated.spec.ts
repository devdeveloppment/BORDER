/**
 * P2.10 — Parcours réels de la pile intégrée (navigateur → Nginx → frontend construit + API Django, PostgreSQL,
 * Redis, worker Celery, Mailpit), dans l'environnement jetable « rbi-e2e ». Aucun raccourci : session, CSRF,
 * MFA, RBAC et RLS du backend s'appliquent. Données exclusivement fictives (domaine .rbi.test, pays « ZZ »).
 *
 * 1. Super Administrateur (créé par la commande serveur) : connexion, enrôlement TOTP, codes de secours.
 * 2-5. Organismes A et B : enregistrement, autorisation, désignation de l'administrateur, activation.
 * 6-7. Administrateurs : lien de réinitialisation reçu dans Mailpit, mot de passe, connexion avec MFA.
 * 8. Gestion réelle d'un compte (création, rôles, désactivation, réactivation, réinitialisation MFA).
 * 9-10. Journal d'audit : consultation, filtres, export CSV, vérification d'intégrité ; adresse IP réelle.
 * 11. Isolation : aucune visibilité croisée entre A et B (écrans et requêtes directes).
 * + demande d'accès publique rejetée, suspension d'un organisme fermant ses sessions, mention des données
 *   simulées sur les modules reportés, aucune violation CSP.
 */
import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { acceptInvitation, cspViolations, env, newActor, pageFetch, signIn, type Actor } from "./support";

const SUPER_ADMIN = env("RBI_E2E_SUPERADMIN_EMAIL");
const SUPER_ADMIN_PASSWORD = env("RBI_E2E_SUPERADMIN_PASSWORD");
const PASSWORD = env("RBI_E2E_USER_PASSWORD");
const PROXY_IP = env("RBI_E2E_PROXY_IP");
const TODAY = new Date().toISOString().slice(0, 10);

const ORG_A = { name: "Organisme Démo A (E2E)", short: "DEMO-A-E2E", admin: "admin@demo-a.rbi.test" };
const ORG_B = { name: "Organisme Démo B (E2E)", short: "DEMO-B-E2E", admin: "admin@demo-b.rbi.test" };
const AGENT_A = "agent@demo-a.rbi.test";

test.describe.configure({ mode: "serial" });

let platform: Actor;
let adminA: Actor;
let adminB: Actor;
const orgIds: Record<string, string> = {};

test.beforeAll(async ({ browser }) => {
  platform = await newActor(browser);
  adminA = await newActor(browser);
  adminB = await newActor(browser);
});

test.afterAll(async () => {
  for (const actor of [platform, adminA, adminB]) await actor?.context.close();
});

async function registerOrganization(page: Page, org: typeof ORG_A): Promise<string> {
  await page.goto("/app/plateforme/organismes");
  await page.getByRole("button", { name: "Enregistrer un organisme" }).click();
  const dialog = page.getByRole("dialog", { name: "Enregistrer un organisme" });
  await dialog.getByLabel(/^Raison sociale/).fill(org.name);
  await dialog.getByLabel(/^Sigle/).fill(org.short);
  await dialog.getByLabel(/^Code pays/).fill("ZZ"); // code ISO réservé à l'usage privé : pays fictif
  await page.getByRole("button", { name: "Enregistrer", exact: true }).click();
  await page.waitForURL(/\/app\/plateforme\/organismes\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { name: org.name })).toBeVisible();
  await expect(page.getByText("En attente", { exact: true })).toBeVisible();

  await page.getByLabel(/^Référence de la convention/).fill(`CONV-${org.short}`);
  await page.getByLabel(/^Périmètre autorisé/).fill("Démonstration sur données fictives uniquement.");
  await page.getByLabel(/^Valide du/).fill(TODAY);
  await page.getByRole("button", { name: "Enregistrer l'autorisation" }).click();
  await expect(page.getByText("Autorisée", { exact: true })).toBeVisible();

  await page.getByLabel(/^Adresse email professionnelle/).fill(org.admin);
  await page.getByRole("button", { name: "Désigner l'administrateur" }).click();
  await expect(page.getByText("Administrateur désigné")).toBeVisible();

  await page.getByRole("button", { name: "Activer", exact: true }).click();
  await expect(page.getByText("Active", { exact: true })).toBeVisible();
  return page.url().split("/").pop()!;
}

test("1. Super Administrateur : connexion, enrôlement TOTP, codes de secours", async () => {
  await signIn(platform, SUPER_ADMIN, SUPER_ADMIN_PASSWORD);
  await expect(platform.page).toHaveURL(/\/app\/plateforme\/organismes$/);
  await expect(platform.page.getByRole("heading", { name: "Organismes" })).toBeVisible();
  const me = await pageFetch(platform.page, "/me");
  expect(me.status).toBe(200);
  expect(me.body).toMatchObject({ email: SUPER_ADMIN, organization: null, mfa_enabled: true });
  expect((me.body as { permissions: string[] }).permissions).toContain("platform.organizations");
});

test("demande d'accès publique, puis rejet motivé par la plateforme", async ({ browser }) => {
  const visitor = await newActor(browser);
  await visitor.page.goto("/contact");
  await visitor.page.getByLabel(/^Organisme/).fill("Organisme Démo C (E2E)");
  await visitor.page.getByLabel(/^Fonction/).fill("Chef de projet fictif");
  await visitor.page.getByLabel(/^Nom et prénom/).fill("Demandeur Fictif");
  await visitor.page.getByLabel(/^Email professionnel/).fill("demandeur@demo-c.rbi.test");
  await visitor.page.getByLabel(/J'accepte/).check();
  await visitor.page.getByRole("button", { name: "Envoyer la demande" }).click();
  await expect(visitor.page.getByText("Demande envoyée")).toBeVisible();
  expect(await cspViolations(visitor)).toEqual([]);
  await visitor.context.close();

  await platform.page.goto("/app/plateforme/organismes");
  const request = platform.page.getByRole("listitem").filter({ hasText: "Organisme Démo C (E2E)" });
  await request.getByRole("button", { name: "Rejeter" }).click();
  const dialog = platform.page.getByRole("dialog", { name: "Rejeter la demande" });
  await dialog.getByLabel(/^Motif/).fill("Demande de démonstration fictive (test E2E).");
  await dialog.getByRole("button", { name: "Rejeter" }).click();
  await expect(platform.page.getByText("Organisme Démo C (E2E)")).toHaveCount(0);
});

test("2-5. Organismes A et B : enregistrement, autorisation, administrateur, activation", async () => {
  orgIds.A = await registerOrganization(platform.page, ORG_A);
  orgIds.B = await registerOrganization(platform.page, ORG_B);
  expect(orgIds.A).not.toBe(orgIds.B);
});

test("6-7. Administrateurs : lien reçu dans Mailpit, mot de passe, connexion avec enrôlement MFA", async () => {
  await acceptInvitation(adminA, ORG_A.admin, PASSWORD);
  await signIn(adminA, ORG_A.admin, PASSWORD);
  await acceptInvitation(adminB, ORG_B.admin, PASSWORD);
  await signIn(adminB, ORG_B.admin, PASSWORD);
  for (const [actor, org] of [[adminA, ORG_A], [adminB, ORG_B]] as const) {
    const me = (await pageFetch(actor.page, "/me")).body as { organization: { name: string }; roles: string[]; mfa_enabled: boolean };
    expect(me.organization.name).toBe(org.name);
    expect(me.roles).toEqual(["ORG_ADMIN"]);
    expect(me.mfa_enabled).toBe(true);
  }
  // Accueil d'un organisme : tableau de bord simulé, signalé comme tel ; ses données viennent de MSW.
  await adminA.page.goto("/app");
  await expect(adminA.page.getByTestId("simulated-module")).toContainText("Données simulées — module non encore implémenté");
  await expect.poll(() => adminA.mocked.some((r) => r.endsWith("/api/v1/dashboard"))).toBe(true);
});

test("8. Gestion réelle d'un compte par l'Administrateur institutionnel", async () => {
  const { page } = adminA;
  await page.goto("/app/admin/utilisateurs");
  await expect(page.getByTestId("simulated-module")).toHaveCount(0); // écran servi par l'API réelle
  await page.getByRole("button", { name: "Créer un compte" }).click();
  const create = page.getByRole("dialog", { name: "Créer un compte" });
  await create.getByLabel(/^Adresse email professionnelle/).fill(AGENT_A);
  await create.getByLabel(/^Prénom/).fill("Agent");
  await create.getByLabel(/^Nom/).fill("Fictif");
  await create.getByLabel("Agent opérationnel").check();
  await page.getByRole("button", { name: "Créer le compte" }).click();
  await expect(create).toHaveCount(0);

  await page.getByRole("region", { name: "Utilisateurs de l'organisme" }).getByRole("cell", { name: AGENT_A, exact: true }).click();
  const detail = page.getByRole("dialog", { name: "Agent Fictif" });
  // Les rôles attribués sont lus dans la liste « Rôles » : l'option « Analyste » du sélecteur reste présente.
  const assigned = detail.locator("section[aria-labelledby='roles-title'] li");
  await detail.getByLabel("Rôle à attribuer").selectOption("ANALYST");
  await detail.getByRole("button", { name: "Attribuer" }).click();
  await expect(assigned.filter({ hasText: "Analyste" })).toHaveCount(1);
  await detail.getByRole("button", { name: "Retirer le rôle Analyste" }).click();
  await expect(assigned.filter({ hasText: "Analyste" })).toHaveCount(0);
  await detail.getByRole("button", { name: "Désactiver le compte" }).click();
  await expect(detail.getByText("Désactivé", { exact: true })).toBeVisible();
  await detail.getByRole("button", { name: "Réactiver le compte" }).click();
  await expect(detail.getByText("Actif", { exact: true })).toBeVisible();
  await detail.getByRole("button", { name: "Réinitialiser la MFA" }).click();
  await detail.getByRole("button", { name: "Confirmer la réinitialisation MFA" }).click();
  await expect(detail.getByText("Modification enregistrée.")).toBeVisible();
  await page.keyboard.press("Escape");

  // Aucune auto-administration : l'écran le signale, le backend le refuse.
  await page.getByRole("region", { name: "Utilisateurs de l'organisme" }).getByRole("cell", { name: ORG_A.admin, exact: true }).last().click(); // compte sans nom : la colonne Nom reprend l'adresse, la colonne Email est la dernière
  await expect(page.getByText("Vous ne pouvez pas modifier votre propre compte")).toBeVisible();
  const me = (await pageFetch(page, "/me")).body as { id: string };
  expect((await pageFetch(page, `/users/${me.id}`, { method: "PATCH", body: { is_active: false } })).status).toBe(403);
  await page.keyboard.press("Escape");
});

test("9-10. Journal d'audit : consultation, filtres, export CSV, intégrité, adresse IP réelle", async () => {
  const { page } = adminA;
  await page.goto("/app/audit");
  await expect(page.getByRole("heading", { name: "Journal d'audit" })).toBeVisible();
  await page.getByLabel("Type d'action").selectOption("user");
  await expect(page.getByRole("button", { name: "user.create" }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "user.deactivate" }).first()).toBeVisible();

  // Adresse inscrite = client réel de Nginx (jamais le proxy lui-même, jamais une valeur fournie par le client).
  const page1 = (await pageFetch(page, "/audit-logs?action=user.create")).body as { results: { ip_address: string | null }[] };
  const ip = page1.results[0]?.ip_address;
  expect(ip).toMatch(/^[0-9a-f.:]+$/);
  expect(ip).not.toBe(PROXY_IP);

  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Exporter (CSV)" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/^rbi-audit-.+\.csv$/);
  const csv = readFileSync((await file.path())!, "utf-8");
  expect(csv.split("\n")[0]).toContain("id,created_at,scope,organization_id,actor");
  expect(csv).toContain("user.create");
  expect(csv).not.toContain(ORG_B.admin);

  await page.getByRole("button", { name: "Vérifier l'intégrité" }).click();
  await expect(page.getByText("Intégrité de la chaîne : valide")).toBeVisible();

  // Journal plateforme : cycle de vie des organismes, chaîne intacte.
  await platform.page.goto("/app/plateforme/audit");
  await platform.page.getByLabel("Type d'action").selectOption("organization");
  await expect(platform.page.getByRole("button", { name: "organization.transition" }).first()).toBeVisible();
  await platform.page.getByRole("button", { name: "Vérifier l'intégrité" }).click();
  await expect(platform.page.getByText("Intégrité de la chaîne : valide")).toBeVisible();
});

test("11. Isolation : aucune visibilité croisée entre les organismes A et B", async () => {
  const usersA = (await pageFetch(adminA.page, "/users")).body as { id: string; email: string }[];
  const usersB = (await pageFetch(adminB.page, "/users")).body as { id: string; email: string }[];
  expect(usersA.map((u) => u.email).sort()).toEqual([ORG_A.admin, AGENT_A].sort());
  expect(usersB.map((u) => u.email)).toEqual([ORG_B.admin]);

  const agent = usersA.find((u) => u.email === AGENT_A)!;
  const adminBId = usersB[0]!.id;
  // Objet d'un autre organisme : indiscernable d'un objet inexistant (404), en lecture comme en écriture.
  expect((await pageFetch(adminB.page, `/users/${agent.id}`)).status).toBe(404);
  expect((await pageFetch(adminB.page, `/users/${agent.id}`, { method: "PATCH", body: { is_active: false } })).status).toBe(404);
  expect((await pageFetch(adminB.page, `/users/${agent.id}/roles`, { method: "POST", body: { role: "AUDITOR" } })).status).toBe(404);
  expect((await pageFetch(adminA.page, `/users/${adminBId}`)).status).toBe(404);
  // Le contexte d'organisme ne vient jamais du client : un identifiant fourni est sans effet.
  const own = (await pageFetch(adminB.page, `/organization?organization_id=${orgIds.A}`)).body as { id: string };
  expect(own.id).toBe(orgIds.B);
  // Un organisme n'atteint pas les routes de plateforme.
  expect((await pageFetch(adminA.page, "/platform/organizations")).status).toBe(403);

  await adminB.page.goto("/app/admin/utilisateurs");
  await expect(adminB.page.getByRole("cell", { name: ORG_B.admin, exact: true }).last()).toBeVisible();
  await expect(adminB.page.getByText(AGENT_A)).toHaveCount(0);
  const auditB = (await pageFetch(adminB.page, "/audit-logs?page_size=100")).body as { results: { organization_id: string | null }[] };
  expect(auditB.results.length).toBeGreaterThan(0);
  for (const entry of auditB.results) expect(entry.organization_id).toBe(orgIds.B);
});

test("suspension d'un organisme par la plateforme : les sessions de ses comptes sont fermées", async () => {
  await platform.page.goto(`/app/plateforme/organismes/${orgIds.B}`);
  await platform.page.getByRole("button", { name: "Suspendre" }).click();
  await platform.page.getByLabel(/^Motif/).fill("Suspension de démonstration (test E2E).");
  await platform.page.getByRole("button", { name: "Confirmer : suspendre" }).click();
  await expect(platform.page.getByText("Suspendue", { exact: true })).toBeVisible();

  await adminB.page.goto("/app/admin/utilisateurs");
  await expect(adminB.page).toHaveURL(/\/connexion$/);
  expect((await pageFetch(adminB.page, "/me")).status).toBe(401);
});

test("aucune violation CSP ; les routes livrées ne sont jamais servies par MSW", async () => {
  for (const actor of [platform, adminA, adminB]) {
    expect(await cspViolations(actor)).toEqual([]);
    const delivered = actor.mocked.filter((r) => /\/api\/v1\/(auth|me|users|roles|organization|audit-logs|platform|public)\b/.test(r));
    expect(delivered).toEqual([]);
  }
  expect(adminA.real.some((r) => r === "GET /api/v1/users")).toBe(true);
});
