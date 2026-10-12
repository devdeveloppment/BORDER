/**
 * Captures d'écran du rapport de phase. Exécution manuelle uniquement :
 *   CAPTURE=1 npx playwright test e2e/screenshots.spec.ts --project=desktop --project=mobile
 */
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test.skip(!process.env.CAPTURE, "Captures générées uniquement à la demande (CAPTURE=1)");

const OUT = "../docs/phases/phase-1/captures";

test("captures des écrans clés", async ({ page }, info) => {
  test.setTimeout(120_000);
  const shot = async (name: string) => {
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${OUT}/${info.project.name}-${name}.jpg`, type: "jpeg", quality: 80, fullPage: info.project.name === "desktop" });
  };
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await shot("01-accueil");
  await page.goto("/connexion");
  await shot("02-connexion");
  await login(page, "superviseur@demo-a.rbi.test");
  await expect(page.getByText("Situation du jour")).toBeVisible();
  await shot("03-tableau-de-bord");
  await page.goto("/app/alertes");
  await expect(page.getByText("ALR-2026-000123").first()).toBeVisible();
  await shot("04-alertes");
  await page.getByText("ALR-2026-000123").first().click();
  await expect(page.getByText("72 / 100")).toBeVisible();
  await shot("05-alerte-explication");
  await page.goto("/app/postes");
  await expect(page.getByText("Poste Démo 07").first()).toBeVisible();
  await shot("06-postes");
  await page.goto("/app/analyse");
  await expect(page.getByRole("heading", { name: "Profil jour × heure" })).toBeVisible();
  await shot("07-analyse");
});
