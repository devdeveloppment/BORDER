import { defineConfig, devices } from "@playwright/test";

/**
 * Tests E2E de la pile INTÉGRÉE (P2.10, ADR 0012) : navigateur → Nginx → frontend construit + API Django réelle,
 * PostgreSQL, Redis, worker Celery et Mailpit. Lancés UNIQUEMENT par `scripts/e2e.py`, qui crée l'environnement
 * jetable (projet Docker « rbi-e2e ») et fournit les variables RBI_E2E_*.
 */
const baseURL = process.env.RBI_E2E_BASE_URL;
if (!baseURL) throw new Error("RBI_E2E_BASE_URL absent : lancer les tests par « py scripts/e2e.py ».");

export default defineConfig({
  testDir: "./e2e-integrated",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 180_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  use: { baseURL, trace: "retain-on-failure", ...devices["Desktop Chrome"], viewport: { width: 1366, height: 768 } },
});
