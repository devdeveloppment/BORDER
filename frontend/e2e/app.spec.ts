import { expect, test } from "@playwright/test";
import { expectAccessible, expectNoHorizontalOverflow, login } from "./helpers";

const SUPERVISOR_A = "superviseur@demo-a.rbi.test";
const ADMIN_A = "admin@demo-a.rbi.test";

test.describe("écrans publics", () => {
  for (const [path, heading] of [
    ["/", "Transformer les données frontalières en décisions intelligentes."],
    ["/contact", "Demander une démonstration ou un accès"],
    ["/connexion", "Connexion"],
    ["/connexion/recuperation", "Mot de passe oublié"],
  ] as const) {
    test(`${path} — accessible et responsive`, async ({ page }) => {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
      await expectNoHorizontalOverflow(page);
      await expectAccessible(page);
    });
  }

  test("le formulaire de contact valide les champs obligatoires", async ({ page }) => {
    await page.goto("/contact");
    await page.getByRole("button", { name: "Envoyer la demande" }).click();
    await expect(page.getByText("Champ obligatoire.").first()).toBeVisible();
    await expect(page.getByText("Le consentement est requis.")).toBeVisible();
  });
});

test.describe("parcours authentifié", () => {
  test("connexion MFA → tableau de bord avec bandeau de démonstration", async ({ page }) => {
    await login(page, SUPERVISOR_A);
    await expect(page.getByRole("heading", { level: 1, name: "Tableau de bord" })).toBeVisible();
    await expect(page.getByTestId("org-name")).toHaveText("Organisme Démo A");
    await expect(page.getByRole("note", { name: "Environnement" })).toContainText(/données de démonstration/i);
    await expect(page.getByText("Situation du jour")).toBeVisible();
    // Graphique ECharts réellement rendu (SVG)
    await expect(page.getByRole("img", { name: /Courbe d'activité/ }).locator("svg")).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await expectAccessible(page);
  });

  const SCREENS = [
    ["/app/alertes", "Alertes"],
    ["/app/postes", "Postes frontaliers"],
    ["/app/activites", "Registre des activités"],
    ["/app/analyse", "Analyse historique"],
    ["/app/rapports", "Rapports"],
    ["/app/notifications", "Notifications"],
    ["/app/audit", "Journal d'audit"],
    ["/app/admin/utilisateurs", "Utilisateurs"],
    ["/app/admin/organisme", "Organisme Démo A"],
    ["/app/admin/parametres", "Paramètres"],
    ["/app/profil", "Mon profil"],
  ] as const;

  test("tous les écrans applicatifs : accessibles et sans débordement", async ({ page }) => {
    test.setTimeout(150_000); // 11 écrans, chacun audité par axe-core
    await login(page, ADMIN_A);
    for (const [path, heading] of SCREENS) {
      await test.step(path, async () => {
        await page.goto(path);
        await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
        await expect(page.getByRole("status")).toHaveCount(0); // plus de squelette de chargement
        await expectNoHorizontalOverflow(page);
        await expectAccessible(page);
      });
    }
  });

  test("scénario de démonstration : alerte Poste Démo 07 expliquée et prise en charge", async ({ page }) => {
    await login(page, SUPERVISOR_A);
    await page.goto("/app/alertes");
    await page.getByText("ALR-2026-000123").first().click();
    await expect(page.getByRole("heading", { level: 1, name: /Poste Démo 07/ })).toBeVisible();
    await expect(page.getByText(/Niveau ÉLEVÉ \(72\/100\)/)).toBeVisible();
    await expect(page.getByText("72 / 100")).toBeVisible();
    await expectAccessible(page);

    if ((page.viewportSize()?.width ?? 0) < 1024) await page.getByRole("tab", { name: "Traitement" }).click();
    await page.getByRole("button", { name: "Prendre en charge" }).click();
    await expect(page.getByRole("button", { name: "Marquer comme examinée" })).toBeVisible();
  });

  test("navigation mobile par le tiroir de menu", async ({ page }) => {
    test.skip((page.viewportSize()?.width ?? 0) >= 1024, "Tiroir réservé aux écrans < 1024 px");
    await login(page, SUPERVISOR_A);
    await page.getByRole("button", { name: "Ouvrir le menu" }).click();
    const drawer = page.getByRole("dialog", { name: "Menu" });
    await expect(drawer).toBeVisible();
    await drawer.getByRole("link", { name: "Postes" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Postes frontaliers" })).toBeVisible();
    await expect(drawer).toBeHidden();
  });

  test("Agent : écran d'administration inaccessible par URL directe", async ({ page }) => {
    await login(page, "agent@demo-a.rbi.test");
    await page.goto("/app/admin/utilisateurs");
    await expect(page.getByRole("heading", { name: "Vous n'avez pas accès à cette ressource" })).toBeVisible();
  });

  test("navigation au clavier : lien d'évitement vers le contenu", async ({ page, browserName }) => {
    test.skip(browserName !== "chromium");
    await login(page, SUPERVISOR_A);
    const skip = page.getByRole("link", { name: "Aller au contenu" });
    // L'URL /app est atteinte avant le rendu du shell : la tabulation doit partir d'une page rendue.
    await expect(skip).toBeAttached();
    // Le bouton de connexion, retiré par la redirection, gardait le point de départ de la tabulation.
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
    await page.keyboard.press("Tab");
    await expect(skip).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator("#contenu")).toBeFocused();
  });
});
