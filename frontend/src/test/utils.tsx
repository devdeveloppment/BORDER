import { render } from "@testing-library/react";
import axe from "axe-core";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { AppProviders, createQueryClient } from "@/app/providers";
import { routes } from "@/app/routes";
import { MOCK_PASSWORD, MOCK_TOTP } from "@/mocks/db";

export const ACCOUNTS = {
  supervisorA: "superviseur@demo-a.rbi.test",
  adminA: "admin@demo-a.rbi.test",
  agentA: "agent@demo-a.rbi.test",
  analystA: "analyste@demo-a.rbi.test",
  auditorA: "auditeur@demo-a.rbi.test",
  supervisorB: "superviseur@demo-b.rbi.test",
  superAdmin: "superadmin@plateforme.rbi.test",
} as const;

const api = (path: string) => new URL(`/api/v1${path}`, window.location.origin).href;

export async function apiPost(path: string, body?: unknown): Promise<Response> {
  return fetch(api(path), { method: "POST", headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
}

export async function apiGet(path: string): Promise<Response> {
  return fetch(api(path));
}

/** Ouvre une session simulée complète (mot de passe + MFA si requis). */
export async function signIn(email: string): Promise<void> {
  const res = await apiPost("/auth/login", { email, password: MOCK_PASSWORD });
  if (!res.ok) throw new Error(`Connexion impossible pour ${email} (${res.status})`);
  const { step } = (await res.json()) as { step: string };
  if (step === "MFA_REQUIRED") {
    const mfa = await apiPost("/auth/mfa/verify", { code: MOCK_TOTP });
    if (!mfa.ok) throw new Error("MFA refusée");
  }
}

export function renderApp(path: string) {
  // Client de l'application (gestion globale des 401, P2.10), sans nouvelle tentative ni péremption en test.
  const client = createQueryClient();
  client.setDefaultOptions({ ...client.getDefaultOptions(), queries: { ...client.getDefaultOptions().queries, retry: false, staleTime: Infinity } });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const view = render(
    <AppProviders client={client}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return { ...view, router };
}

/**
 * Audit axe-core (WCAG 2.1 A/AA). Le contraste des couleurs n'est pas calculable en jsdom :
 * il est vérifié dans les tests Playwright sur un vrai navigateur.
 */
export async function axeViolations(container: Element) {
  const result = await axe.run(container, {
    runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] },
    rules: { "color-contrast": { enabled: false } },
  });
  return result.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.length})`);
}
