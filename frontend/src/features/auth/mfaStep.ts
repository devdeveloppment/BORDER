import type { AuthStep } from "@/lib/api/types";

/**
 * Étape MFA en cours (« saisir un code » ou « s'enrôler »), conservée le temps de la connexion pour survivre à
 * un rechargement de page. Aucune donnée sensible : ni code, ni secret, ni identifiant.
 */
const KEY = "rbi.auth.mfa-step";

export function rememberMfaStep(step: AuthStep): void {
  try {
    sessionStorage.setItem(KEY, step);
  } catch {
    /* stockage indisponible : l'étape reste celle de l'état de navigation */
  }
}

export function recalledMfaStep(): AuthStep | null {
  try {
    const value = sessionStorage.getItem(KEY);
    return value === "MFA_REQUIRED" || value === "MFA_ENROLLMENT_REQUIRED" ? value : null;
  } catch {
    return null;
  }
}

export function forgetMfaStep(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* rien à effacer */
  }
}
