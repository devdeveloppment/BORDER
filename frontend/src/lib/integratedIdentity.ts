import type { CurrentUser } from "@/lib/api/types";

/**
 * Mode intégré (P2.10) : l'identité RÉELLE (`GET /api/v1/me`) est transmise aux mocks des modules reportés,
 * qui simulent leurs données avec les permissions effectives de l'utilisateur. Aucune donnée simulée ne
 * remonte vers l'API réelle ; ce relais n'a aucun effet en mode « tout simulé » ni en production.
 */
const KEY = "__rbiIntegratedIdentity";

type Holder = { [KEY]?: CurrentUser | null };

export function publishIntegratedIdentity(user: CurrentUser | null): void {
  (globalThis as Holder)[KEY] = user;
}

export function integratedIdentity(): CurrentUser | null {
  return (globalThis as Holder)[KEY] ?? null;
}
