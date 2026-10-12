import type { ProblemDetails } from "./types";

export const API_BASE = "/api/v1";

/** Réponse d'erreur de l'API (RFC 9457). `retryAfter` : secondes avant de réessayer (429, 503). */
export class ApiError extends Error {
  readonly status: number;
  readonly problem: ProblemDetails | null;
  readonly retryAfter: number | null;

  constructor(status: number, problem: ProblemDetails | null, retryAfter: number | null = null) {
    super(problem?.title ?? `HTTP ${status}`);
    this.status = status;
    this.problem = problem;
    this.retryAfter = retryAfter;
  }

  /** Erreurs de validation d'un champ (`errors`, clés « parent.child » pour les objets imbriqués). */
  fieldError(name: string): string | null {
    return this.problem?.errors?.[name]?.[0] ?? null;
  }
}

/** Le serveur n'a pas répondu (réseau, proxy indisponible) : aucune information sur la requête. */
export class NetworkError extends Error {
  constructor() {
    super("Service injoignable");
  }
}

function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match?.[1] ? decodeURIComponent(match[1]) : null;
}

type Query = Record<string, string | number | boolean | null | undefined>;

function buildUrl(path: string, query?: Query): string {
  const url = new URL(`${API_BASE}${path}`, window.location.origin);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, String(value));
  }
  return url.href;
}

function parseRetryAfter(value: string | null): number | null {
  if (!value) return null;
  const seconds = Number(value);
  return Number.isFinite(seconds) && seconds >= 0 ? Math.ceil(seconds) : null;
}

async function send(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, { ...init, credentials: "same-origin" });
  } catch {
    throw new NetworkError();
  }
}

async function failure(response: Response): Promise<ApiError> {
  const type = response.headers.get("Content-Type") ?? "";
  // Seul un corps JSON (RFC 9457) est lu : une page d'erreur HTML d'un intermédiaire n'est jamais affichée.
  const problem = type.includes("json") ? ((await response.json().catch(() => null)) as ProblemDetails | null) : null;
  return new ApiError(response.status, problem, parseRetryAfter(response.headers.get("Retry-After")));
}

let csrfRequest: Promise<void> | null = null;

/**
 * Protocole CSRF du backend (P2.5) : jeton dans le cookie `csrftoken` (lisible, non HttpOnly), renvoyé dans
 * l'en-tête `X-CSRFToken` de toute requête non sûre. Sans cookie, il est obtenu par `GET /auth/csrf`.
 */
export async function ensureCsrfToken(): Promise<string | null> {
  if (!readCookie("csrftoken")) {
    csrfRequest ??= send(buildUrl("/auth/csrf"), { method: "GET", headers: { Accept: "application/json" } })
      .then(async (response) => {
        if (!response.ok) throw await failure(response);
      })
      .finally(() => {
        csrfRequest = null;
      });
    await csrfRequest;
  }
  return readCookie("csrftoken");
}

/**
 * Client HTTP unique. Authentification par cookie de session HttpOnly (même origine, derrière Nginx) : aucun
 * jeton n'est stocké côté client. Le contexte organisationnel n'est JAMAIS envoyé par le client : il est déduit
 * côté serveur de l'utilisateur authentifié.
 */
export async function apiRequest<T>(
  method: "GET" | "POST" | "PATCH" | "DELETE",
  path: string,
  options: { query?: Query; body?: unknown } = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") {
    const csrf = await ensureCsrfToken();
    if (csrf) headers["X-CSRFToken"] = csrf;
  }

  const response = await send(buildUrl(path, options.query), {
    method,
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  if (!response.ok) throw await failure(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Téléchargement d'un fichier (export CSV) : erreurs au format RFC 9457 comme toute autre requête. */
export async function apiDownload(path: string, query?: Query): Promise<{ blob: Blob; filename: string }> {
  const response = await send(buildUrl(path, query), {
    method: "GET",
    headers: { Accept: "text/csv, application/problem+json" },
  });
  if (!response.ok) throw await failure(response);
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "export.csv";
  return { blob: await response.blob(), filename };
}

export const api = {
  get: <T>(path: string, query?: Query) => apiRequest<T>("GET", path, { query }),
  post: <T>(path: string, body?: unknown) => apiRequest<T>("POST", path, { body }),
  patch: <T>(path: string, body?: unknown) => apiRequest<T>("PATCH", path, { body }),
  delete: <T>(path: string) => apiRequest<T>("DELETE", path),
};

function waitLabel(seconds: number | null): string {
  if (!seconds) return "dans quelques instants";
  if (seconds < 90) return `dans ${seconds} s`;
  return `dans ${Math.ceil(seconds / 60)} min`;
}

/**
 * Message présentable pour une erreur d'API. Seuls le titre et le détail génériques du serveur (RFC 9457) sont
 * repris : jamais de trace, de corps brut ni d'information technique.
 */
export function describeError(error: unknown): string {
  if (error instanceof NetworkError) return "Le service est momentanément injoignable. Vérifiez votre connexion et réessayez.";
  if (!(error instanceof ApiError)) return "Une erreur inattendue s'est produite. Veuillez réessayer.";
  const { status, problem } = error;
  if (status === 401) return "Votre session a expiré. Veuillez vous reconnecter.";
  if (status === 403) return problem?.detail ?? "Vous n'avez pas accès à cette ressource.";
  if (status === 404) return "Ressource introuvable ou hors de votre périmètre.";
  if (status === 413) return "La requête est trop volumineuse.";
  if (status === 429) return `Trop de requêtes. Veuillez réessayer ${waitLabel(error.retryAfter)}.`;
  if (status === 501 && problem?.detail) return problem.detail;
  if (status >= 500) return "Le service est momentanément indisponible. Veuillez réessayer dans un instant.";
  const firstError = problem?.errors ? Object.values(problem.errors).flat()[0] : undefined;
  return problem?.detail ?? firstError ?? problem?.title ?? "La requête n'a pas pu être traitée.";
}
