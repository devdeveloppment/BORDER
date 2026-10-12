import { useSyncExternalStore } from "react";

/** Abonnement à une media query CSS (ex. `(min-width: 1024px)` = breakpoint `lg`). */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const mql = window.matchMedia(query);
      mql.addEventListener("change", onChange);
      return () => mql.removeEventListener("change", onChange);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}
