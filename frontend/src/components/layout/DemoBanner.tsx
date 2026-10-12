import { API_MODE, APP_ENV } from "@/lib/env";

const MODE_LABEL = {
  mock: "API simulée — maquette Phase 1",
  integrated: "API réelle — modules métier simulés",
  live: null,
} as const;

/** Bandeau permanent d'environnement non productif (§9.1, §11.3, CA-21) et mode de l'API (P2.10). */
export function DemoBanner() {
  if (APP_ENV === "production") return null;
  const mode = MODE_LABEL[API_MODE];
  return (
    <div role="note" aria-label="Environnement" className="flex flex-wrap items-center justify-center gap-x-3 gap-y-0.5 bg-warn-soft px-4 py-1 text-center text-[11px] font-semibold tracking-wide text-warn-ink uppercase">
      <span>{APP_ENV === "staging" ? "Environnement de recette (STAGING)" : "Données de démonstration — aucune donnée réelle"}</span>
      {mode ? <span className="rounded bg-warn-ink px-1.5 py-px text-[10px] text-white">{mode}</span> : null}
    </div>
  );
}
