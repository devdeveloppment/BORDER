import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { MOCK_PASSWORD, MOCK_TOTP } from "@/mocks/db";
import { ACCOUNTS, renderApp, signIn } from "@/test/utils";

const mainNav = () => screen.getByRole("navigation", { name: "Navigation principale" });

describe("parcours de connexion", () => {
  it("redirige vers la connexion lorsqu'aucune session n'existe", async () => {
    const { router } = renderApp("/app/alertes");
    expect(await screen.findByRole("heading", { name: "Connexion" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/connexion");
  });

  it("connecte un superviseur avec MFA puis affiche le tableau de bord de son organisme", async () => {
    const user = userEvent.setup();
    const { router } = renderApp("/connexion");
    await user.type(await screen.findByLabelText(/Adresse email/), ACCOUNTS.supervisorA);
    await user.type(screen.getByLabelText(/Mot de passe/), MOCK_PASSWORD);
    await user.click(screen.getByRole("button", { name: "Se connecter" }));

    await user.type(await screen.findByLabelText(/Code de vérification/), MOCK_TOTP);
    const visited: string[] = [];
    router.subscribe((state) => visited.push(state.location.pathname));
    await user.click(screen.getByRole("button", { name: "Vérifier" }));

    expect(await screen.findByRole("heading", { name: "Tableau de bord" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/app");
    // Aucun aller-retour par la page de connexion (pas de scintillement après la MFA)
    expect(visited).toEqual(["/app"]);
    expect(screen.getByTestId("org-name")).toHaveTextContent("Organisme Démo A");
    expect(screen.getByRole("note", { name: "Environnement" })).toHaveTextContent(/Données de démonstration/i);
    // Les KPI proviennent de l'API (aucune valeur statique)
    expect(await screen.findByText("Activités")).toBeInTheDocument();
    expect(await screen.findByText("Situation du jour")).toBeInTheDocument();
  });

  it("affiche un message générique en cas d'identifiants incorrects", async () => {
    const user = userEvent.setup();
    renderApp("/connexion");
    await user.type(await screen.findByLabelText(/Adresse email/), ACCOUNTS.supervisorA);
    await user.type(screen.getByLabelText(/Mot de passe/), "incorrect-1234");
    await user.click(screen.getByRole("button", { name: "Se connecter" }));
    expect(await screen.findByText("Identifiants incorrects.")).toBeInTheDocument();
  });

  it("déconnecte l'utilisateur et protège de nouveau l'application", async () => {
    await signIn(ACCOUNTS.analystA);
    const user = userEvent.setup();
    const { router } = renderApp("/app");
    await user.click(await screen.findByRole("button", { name: "Menu du profil" }));
    await user.click(await screen.findByRole("menuitem", { name: /Se déconnecter/ }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/connexion"));
  });
});

describe("navigation selon le rôle (éléments masqués, §11.5)", () => {
  it("Admin institutionnel : accès à l'administration", async () => {
    await signIn(ACCOUNTS.adminA);
    renderApp("/app");
    await screen.findByRole("heading", { name: "Tableau de bord" });
    const nav = mainNav();
    for (const label of ["Tableau de bord", "Alertes", "Postes", "Activités", "Analyse", "Rapports", "Utilisateurs", "Organisme", "Paramètres", "Journal d'audit"]) {
      expect(within(nav).getByRole("link", { name: label })).toBeInTheDocument();
    }
    expect(within(nav).queryByRole("link", { name: "Organismes" })).not.toBeInTheDocument();
  });

  it("Agent : ni administration, ni audit, ni analyse", async () => {
    await signIn(ACCOUNTS.agentA);
    renderApp("/app");
    await screen.findByRole("heading", { name: "Tableau de bord" });
    const nav = mainNav();
    expect(within(nav).getByRole("link", { name: "Alertes" })).toBeInTheDocument();
    for (const label of ["Utilisateurs", "Paramètres", "Journal d'audit", "Analyse", "Rapports"]) {
      expect(within(nav).queryByRole("link", { name: label })).not.toBeInTheDocument();
    }
  });

  it("Agent : un accès direct par URL à un écran non autorisé affiche un 403", async () => {
    await signIn(ACCOUNTS.agentA);
    renderApp("/app/admin/utilisateurs");
    expect(await screen.findByRole("heading", { name: "Vous n'avez pas accès à cette ressource" })).toBeInTheDocument();
  });

  it("Auditeur : accès au journal d'audit en lecture", async () => {
    await signIn(ACCOUNTS.auditorA);
    renderApp("/app/audit");
    expect(await screen.findByRole("heading", { name: "Journal d'audit" })).toBeInTheDocument();
    expect(await screen.findByRole("table", { name: "Journal d'audit" })).toBeInTheDocument();
  });

  it("Super Admin : redirigé vers la gestion des organismes, sans tableau de bord opérationnel", async () => {
    await signIn(ACCOUNTS.superAdmin);
    const { router } = renderApp("/app");
    expect(await screen.findByRole("heading", { name: "Organismes" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/app/plateforme/organismes");
    expect(within(mainNav()).queryByRole("link", { name: "Tableau de bord" })).not.toBeInTheDocument();
  });
});

describe("isolation dans l'interface", () => {
  it("une alerte d'un autre organisme apparaît comme inaccessible", async () => {
    const { ALERTS, ORGS } = await import("@/mocks/db");
    const foreign = ALERTS.find((a) => a.orgId === ORGS[1]!.id)!;
    await signIn(ACCOUNTS.supervisorA);
    renderApp(`/app/alertes/${foreign.id}`);
    expect(await screen.findByText("Vous n'avez pas accès à cette ressource")).toBeInTheDocument();
    expect(screen.queryByText(foreign.reference)).not.toBeInTheDocument();
  });
});

describe("écrans principaux", () => {
  it.each([
    ["/app/alertes", "Alertes"],
    ["/app/postes", "Postes frontaliers"],
    ["/app/activites", "Registre des activités"],
    ["/app/analyse", "Analyse historique"],
    ["/app/rapports", "Rapports"],
    ["/app/notifications", "Notifications"],
    ["/app/profil", "Mon profil"],
    ["/app/admin/parametres", "Paramètres"],
  ])("%s se charge pour un administrateur institutionnel", async (path, heading) => {
    await signIn(ACCOUNTS.adminA);
    renderApp(path);
    expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeInTheDocument();
  });

  it("une route inconnue affiche la page 404", async () => {
    renderApp("/page-inexistante");
    expect(await screen.findByRole("heading", { name: "Page introuvable" })).toBeInTheDocument();
  });
});
