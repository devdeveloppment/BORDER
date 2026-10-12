/**
 * P2.10 — Comportements de l'intégration : session, permissions effectives, erreurs RFC 9457, CSRF et
 * confidentialité du secret TOTP et des codes de secours. Les réponses du backend sont reproduites par MSW
 * (`server.use`) ; les parcours réels sont rejoués de bout en bout par Playwright (e2e/integrated).
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { isDeferredAppRoute } from "@/components/layout/SimulatedModuleNotice";
import { ApiError, apiRequest, describeError, ensureCsrfToken, NetworkError } from "@/lib/api/client";
import type { CurrentUser } from "@/lib/api/types";
import { effectivePermissions } from "@/lib/auth/session";
import { server } from "@/mocks/server";
import { ACCOUNTS, renderApp, signIn } from "./utils";

const API = "/api/v1";
const SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP";
const URI = `otpauth://totp/RBI:admin%40demo-a.rbi.test?secret=${SECRET}&issuer=RBI`;
const CODES = ["ABCDE-FGHJK", "LMNPQ-RSTUV", "WXYZ2-34567", "89ABC-DEFGH"];

function clearCookies() {
  for (const cookie of document.cookie.split(";")) {
    const name = cookie.split("=")[0]?.trim();
    if (name) document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
  }
}

afterEach(() => {
  clearCookies();
  vi.restoreAllMocks();
});

describe("permissions effectives (GET /me)", () => {
  it("une liste absente ou mal formée ne donne aucune permission", () => {
    expect(effectivePermissions(null).size).toBe(0);
    expect(effectivePermissions(undefined).size).toBe(0);
    expect(effectivePermissions({ permissions: null } as unknown as CurrentUser).size).toBe(0);
    expect(effectivePermissions({ permissions: "users.view" } as unknown as CurrentUser).size).toBe(0);
    expect([...effectivePermissions({ permissions: ["users.view", 3, null] } as unknown as CurrentUser)]).toEqual(["users.view"]);
  });

  it("une permission retirée côté serveur masque l'entrée et refuse l'écran", async () => {
    await signIn(ACCOUNTS.adminA);
    const me = (await (await fetch(new URL(`${API}/me`, location.origin))).json()) as CurrentUser;
    server.use(http.get(`${API}/me`, () => HttpResponse.json({ ...me, permissions: me.permissions.filter((p) => p !== "users.view") })));
    renderApp("/app/admin/utilisateurs");
    expect(await screen.findByRole("heading", { name: /accès refusé|pas accès/i })).toBeInTheDocument();
    const nav = screen.getAllByRole("navigation", { name: "Navigation principale" })[0]!;
    expect(within(nav).queryByRole("link", { name: "Utilisateurs" })).not.toBeInTheDocument();
  });
});

describe("session", () => {
  it("une réponse 401 en cours de navigation (session expirée côté serveur) ramène à la connexion", async () => {
    await signIn(ACCOUNTS.adminA);
    server.use(http.get(`${API}/users`, () => HttpResponse.json({ type: "about:blank", title: "Authentification requise", status: 401 }, { status: 401 })));
    const { router } = renderApp("/app/admin/utilisateurs");
    await waitFor(() => expect(router.state.location.pathname).toBe("/connexion"));
  });

  it("un backend injoignable n'est pas confondu avec une absence de session", async () => {
    server.use(http.get(`${API}/me`, () => HttpResponse.error()));
    const { router } = renderApp("/app/admin/utilisateurs");
    expect(await screen.findByText(/momentanément injoignable/)).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/app/admin/utilisateurs");
  });

  it("le jeton de réinitialisation est retiré de l'URL dès sa lecture", async () => {
    const { router } = renderApp("/connexion/recuperation?token=jeton-fictif");
    expect(await screen.findByRole("heading", { name: "Définir un nouveau mot de passe" })).toBeInTheDocument();
    await waitFor(() => expect(router.state.location.search).toBe(""));
  });
});

describe("client HTTP", () => {
  it("obtient le cookie CSRF avant la première écriture et le renvoie en en-tête", async () => {
    const seen: (string | null)[] = [];
    server.use(
      http.get(`${API}/auth/csrf`, () => {
        document.cookie = "csrftoken=jeton-csrf-fictif; path=/";
        return new HttpResponse(null, { status: 204 });
      }),
      http.post(`${API}/auth/logout`, ({ request }) => {
        seen.push(request.headers.get("X-CSRFToken"));
        return new HttpResponse(null, { status: 204 });
      }),
    );
    await apiRequest("POST", "/auth/logout");
    expect(seen).toEqual(["jeton-csrf-fictif"]);
    expect(await ensureCsrfToken()).toBe("jeton-csrf-fictif");
  });

  it("lit Retry-After d'une réponse 429", async () => {
    server.use(
      http.get(`${API}/audit-logs`, () =>
        HttpResponse.json({ type: "about:blank", title: "Trop de requêtes", status: 429 }, { status: 429, headers: { "Retry-After": "120" } }),
      ),
    );
    const error = await apiRequest("GET", "/audit-logs").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).retryAfter).toBe(120);
    expect(describeError(error)).toBe("Trop de requêtes. Veuillez réessayer dans 2 min.");
  });

  it("n'affiche jamais une page d'erreur HTML d'un intermédiaire", async () => {
    server.use(http.get(`${API}/me`, () => new HttpResponse("<html><body>Traceback secret interne</body></html>", { status: 502, headers: { "Content-Type": "text/html" } })));
    const error = await apiRequest("GET", "/me").catch((e: unknown) => e);
    expect((error as ApiError).problem).toBeNull();
    expect(describeError(error)).not.toMatch(/Traceback|secret/);
  });

  it("présente les erreurs de validation et les refus sans détail technique", () => {
    const validation = new ApiError(400, { type: "about:blank", title: "Requête invalide", status: 400, errors: { email: ["Cette adresse ne peut pas être utilisée."] } });
    expect(validation.fieldError("email")).toBe("Cette adresse ne peut pas être utilisée.");
    expect(describeError(validation)).toBe("Cette adresse ne peut pas être utilisée.");
    expect(describeError(new ApiError(404, null))).toMatch(/introuvable/);
    expect(describeError(new NetworkError())).toMatch(/injoignable/);
  });
});

describe("enrôlement TOTP et codes de secours", () => {
  it("affiche le QR code, ne divulgue le secret ni dans l'URL, ni dans le stockage, ni dans la console, et montre les codes une seule fois", async () => {
    const consoleSpies = (["log", "info", "warn", "error", "debug"] as const).map((level) => vi.spyOn(console, level));
    server.use(
      http.post(`${API}/auth/login`, () => HttpResponse.json({ step: "MFA_ENROLLMENT_REQUIRED" })),
      http.post(`${API}/auth/mfa/enroll`, () => HttpResponse.json({ otpauth_uri: URI, secret: SECRET })),
      http.post(`${API}/auth/mfa/verify`, () => HttpResponse.json({ step: "AUTHENTICATED", backup_codes: CODES })),
    );
    const user = userEvent.setup();
    const { router, container } = renderApp("/connexion");
    await user.type(await screen.findByLabelText(/^Adresse email/), ACCOUNTS.adminA);
    await user.type(screen.getByLabelText(/^Mot de passe/), "mot-de-passe-fictif");
    await user.click(screen.getByRole("button", { name: "Se connecter" }));
    await user.click(await screen.findByRole("button", { name: "Commencer l'enrôlement" }));

    expect(await screen.findByTitle("QR code d'enrôlement de l'application d'authentification")).toBeInTheDocument();
    expect(container.innerHTML).not.toContain(SECRET.slice(0, 16).replace(/(.{4})/g, "$1 ").trim()); // clé masquée par défaut
    await user.click(screen.getByRole("button", { name: "Afficher la clé de saisie manuelle" }));
    expect(screen.getByTestId("totp-secret").textContent?.replace(/\s/g, "")).toBe(SECRET);

    await user.type(screen.getByLabelText(/Code de vérification/), "123456");
    await user.click(screen.getByRole("button", { name: "Confirmer l'enrôlement" }));
    const codes = await screen.findByTestId("backup-codes");
    for (const code of CODES) expect(within(codes).getByText(code)).toBeInTheDocument();
    expect(screen.queryByTestId("totp-secret")).not.toBeInTheDocument(); // secret effacé après confirmation

    const { pathname, search, hash } = router.state.location;
    const accessible = [`${pathname}${search}${hash}`, JSON.stringify(router.state.location.state ?? null), JSON.stringify({ ...sessionStorage }), JSON.stringify({ ...localStorage }), document.cookie];
    for (const value of accessible) {
      expect(value).not.toContain(SECRET);
      for (const code of CODES) expect(value).not.toContain(code);
    }
    const logged = consoleSpies.flatMap((spy) => spy.mock.calls.flat().map(String)).join("\n");
    expect(logged).not.toContain(SECRET);
    for (const code of CODES) expect(logged).not.toContain(code);

    // Continuer exige de confirmer la conservation des codes ; ensuite ils disparaissent de l'écran.
    const proceed = screen.getByRole("button", { name: "Accéder à l'application" });
    expect(proceed).toBeDisabled();
    await user.click(screen.getByLabelText("J'ai conservé ces codes de secours en lieu sûr."));
    await user.click(proceed);
    await waitFor(() => expect(screen.queryByTestId("backup-codes")).not.toBeInTheDocument());
    expect(container.innerHTML).not.toContain(CODES[0]);
  });
});

describe("modules reportés", () => {
  it.each([
    ["/app", true],
    ["/app/alertes/12", true],
    ["/app/postes", true],
    ["/app/admin/parametres", true],
    ["/app/notifications", true],
    ["/app/audit", false],
    ["/app/admin/utilisateurs", false],
    ["/app/admin/organisme", false],
    ["/app/plateforme/organismes", false],
    ["/app/profil", false],
    ["/app/alertes-x", false],
  ])("%s → simulé : %s", (path, expected) => {
    expect(isDeferredAppRoute(path)).toBe(expected);
  });
});
