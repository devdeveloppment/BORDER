import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";

export const PASSWORD = "Demo-RBI-2026!";
export const TOTP = "123456";

/** Connexion par l'interface (mot de passe + MFA si demandée). */
export async function login(page: Page, email: string): Promise<void> {
  await page.goto("/connexion");
  await page.getByLabel("Adresse email").fill(email);
  await page.getByLabel("Mot de passe").fill(PASSWORD);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await page.waitForURL(/\/(app|connexion\/mfa)/);
  if (page.url().includes("/connexion/mfa")) {
    await page.getByLabel("Code de vérification").fill(TOTP);
    await page.getByRole("button", { name: "Vérifier" }).click();
  }
  await expect(page).toHaveURL(/\/app/);
}

/** Audit WCAG 2.1 A/AA complet, y compris le contraste des couleurs (vrai moteur de rendu). */
export async function expectAccessible(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const summary = results.violations.map((v) => `${v.id} (${v.impact}): ${v.help} → ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
  expect(summary, "violations d'accessibilité").toEqual([]);
}

/** Aucun défilement horizontal de page (responsive, §11.3). */
export async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, "débordement horizontal (px)").toBeLessThanOrEqual(1);
}
