import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";
import { ErrorState, LoadingBlock } from "@/components/ui/feedback";
import { useSession } from "@/lib/auth/session";
import { PERMISSIONS, type Permission } from "@/lib/permissions";
import { ForbiddenPage } from "@/features/errors/ErrorPages";

/** Exige une session authentifiée (MFA validée). Le contrôle décisif reste côté API. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, isLoading, error, refresh } = useSession();
  const location = useLocation();
  if (error) {
    // Service injoignable : ni connecté ni déconnecté — aucune redirection trompeuse vers la connexion.
    return (
      <div className="mx-auto max-w-3xl p-8">
        <ErrorState error={error} onRetry={() => void refresh()} />
      </div>
    );
  }
  if (isLoading) {
    return (
      <div className="mx-auto max-w-3xl p-8">
        <LoadingBlock label="Vérification de la session…" rows={6} />
      </div>
    );
  }
  if (!user) return <Navigate to="/connexion" replace state={{ from: location.pathname + location.search }} />;
  return <>{children}</>;
}

/** Masque un écran non autorisé (403 sans révéler l'existence de la ressource). */
export function RequirePermission({ permission, children }: { permission: Permission; children: ReactNode }) {
  const { can } = useSession();
  return can(permission) ? <>{children}</> : <ForbiddenPage />;
}

/** Page d'accueil applicative selon le niveau : plateforme (selon ses permissions) ou organisme. */
export function HomeRedirect({ children }: { children: ReactNode }) {
  const { user, can } = useSession();
  if (user && !user.organization) {
    if (can(PERMISSIONS.platformOrganizations)) return <Navigate to="/app/plateforme/organismes" replace />;
    if (can(PERMISSIONS.platformAudit)) return <Navigate to="/app/plateforme/audit" replace />;
    return <Navigate to="/app/profil" replace />;
  }
  return <>{children}</>;
}
