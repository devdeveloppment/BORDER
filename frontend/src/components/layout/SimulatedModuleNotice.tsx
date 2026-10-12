import { FlaskConical } from "lucide-react";
import { useLocation } from "react-router";
import { API_MODE } from "@/lib/env";

/**
 * Écrans des modules métier non encore implémentés par le backend (P2.8 : routes reportées). En mode intégré,
 * leurs données viennent de MSW : elles ne doivent jamais passer pour des données de la base (P2.10).
 */
export const DEFERRED_APP_ROUTES = [
  "/app",
  "/app/alertes",
  "/app/postes",
  "/app/activites",
  "/app/analyse",
  "/app/rapports",
  "/app/notifications",
  "/app/admin/parametres",
] as const;

export function isDeferredAppRoute(pathname: string): boolean {
  const path = pathname.replace(/\/+$/, "") || "/";
  return DEFERRED_APP_ROUTES.some((route) => (route === "/app" ? path === "/app" : path === route || path.startsWith(`${route}/`)));
}

export const SIMULATED_NOTICE = "Données simulées — module non encore implémenté";

export function SimulatedModuleNotice() {
  const { pathname } = useLocation();
  if (API_MODE !== "integrated" || !isDeferredAppRoute(pathname)) return null;
  return (
    <div role="status" data-testid="simulated-module" className="mb-4 flex items-start gap-2 rounded-[var(--radius-card)] border border-warn bg-warn-soft px-4 py-3 text-[13px] text-warn-ink">
      <FlaskConical className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <p>
        <strong className="font-semibold">{SIMULATED_NOTICE}</strong>
        <span className="block text-warn-ink/90">
          Ces données sont générées dans le navigateur à titre de démonstration ; elles ne proviennent pas de la base de données et ne sont jamais
          envoyées au serveur.
        </span>
      </p>
    </div>
  );
}
