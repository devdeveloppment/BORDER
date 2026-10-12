export type AppEnv = "demo" | "staging" | "production";

/**
 * Mode de l'API (P2.10, ADR 0012) :
 * - `mock` : tout simulé par MSW (maquette Phase 1, tests qui en dépendent) — valeur par défaut hors production ;
 * - `integrated` : API réelle pour les routes livrées, MSW pour les seuls modules métier reportés
 *   (signalés « Données simulées — module non encore implémenté ») ;
 * - `live` : API réelle uniquement, aucun mock. Imposé en production : le code des mocks n'est alors pas inclus
 *   dans le bundle (voir `main.tsx`, `vite.config.ts` et `src/test/modes.test.ts`).
 */
export type ApiMode = "mock" | "integrated" | "live";

export function resolveAppEnv(raw: string | undefined): AppEnv {
  return raw === "staging" || raw === "production" ? raw : "demo";
}

export function resolveApiMode(appEnv: AppEnv, raw: string | undefined): ApiMode {
  if (appEnv === "production") return "live";
  if (raw === "deferred") return "integrated";
  if (raw === "false") return "live";
  return "mock";
}

/** Construction de production : expression remplacée par une constante à la construction (code mort éliminé). */
export const IS_PRODUCTION_BUILD = import.meta.env.VITE_APP_ENV === "production";

export const APP_ENV: AppEnv = IS_PRODUCTION_BUILD ? "production" : resolveAppEnv(import.meta.env.VITE_APP_ENV as string | undefined);

export const API_MODE: ApiMode = IS_PRODUCTION_BUILD ? "live" : resolveApiMode(APP_ENV, import.meta.env.VITE_API_MOCKS as string | undefined);

/** MSW actif (tout ou partie des routes). Jamais en production. */
export const MOCKS_ENABLED = API_MODE !== "live";

/** Toutes les routes sont simulées (maquette Phase 1). */
export const FULLY_MOCKED = API_MODE === "mock";
