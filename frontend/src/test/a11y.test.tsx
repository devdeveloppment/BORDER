import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ALERTS } from "@/mocks/db";
import { ACCOUNTS, axeViolations, renderApp, signIn } from "./utils";

/** Audit axe-core WCAG 2.1 A/AA des écrans (structure, libellés, ARIA). */
describe("accessibilité (axe-core)", () => {
  it.each([
    ["/", "Transformer les données frontalières en décisions intelligentes."],
    ["/contact", "Demander une démonstration ou un accès"],
    ["/connexion", "Connexion"],
    ["/connexion/recuperation", "Mot de passe oublié"],
  ])("écran public %s", async (path, heading) => {
    const { container } = renderApp(path);
    await screen.findByRole("heading", { level: 1, name: heading });
    expect(await axeViolations(container)).toEqual([]);
  });

  const scenario = ALERTS.find((a) => a.reference === "ALR-2026-000123")!;

  it.each([
    ["/app", "Tableau de bord"],
    ["/app/alertes", "Alertes"],
    [`/app/alertes/${scenario.id}`, scenario.title],
    ["/app/postes", "Postes frontaliers"],
    ["/app/activites", "Registre des activités"],
    ["/app/analyse", "Analyse historique"],
    ["/app/rapports", "Rapports"],
    ["/app/notifications", "Notifications"],
    ["/app/audit", "Journal d'audit"],
    ["/app/admin/utilisateurs", "Utilisateurs"],
    ["/app/admin/parametres", "Paramètres"],
    ["/app/admin/organisme", "Organisme Démo A"],
    ["/app/profil", "Mon profil"],
  ])("écran applicatif %s", async (path, heading) => {
    await signIn(ACCOUNTS.adminA);
    const { container } = renderApp(path);
    await screen.findByRole("heading", { level: 1, name: heading });
    // laisse les requêtes secondaires se résoudre
    await new Promise((r) => setTimeout(r, 400));
    expect(await axeViolations(container)).toEqual([]);
  });
});
