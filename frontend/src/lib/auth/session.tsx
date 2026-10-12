import { createContext, useContext, useEffect, useMemo, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type { CurrentUser } from "@/lib/api/types";
import { API_MODE } from "@/lib/env";
import { publishIntegratedIdentity } from "@/lib/integratedIdentity";
import type { Permission } from "@/lib/permissions";

interface SessionValue {
  user: CurrentUser | null;
  isLoading: boolean;
  /** `/me` n'a pas pu être lu (réseau, service indisponible) : ni connecté ni déconnecté. */
  error: unknown;
  /** Permissions EFFECTIVES renvoyées par le backend (`GET /me`) : adaptation de l'interface uniquement. */
  can: (permission: Permission) => boolean;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

export const ME_QUERY_KEY = ["me"] as const;

/** Liste de permissions fiable : un champ absent ou mal formé ne donne AUCUNE permission. */
export function effectivePermissions(user: CurrentUser | null | undefined): Set<string> {
  const list = (user as { permissions?: unknown } | null | undefined)?.permissions;
  return new Set(Array.isArray(list) ? list.filter((item): item is string => typeof item === "string") : []);
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ME_QUERY_KEY,
    queryFn: async () => {
      let user: CurrentUser | null;
      try {
        user = await endpoints.me();
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 401) throw error;
        user = null;
      }
      // Publiée AVANT tout rendu des écrans : les modules simulés lisent l'identité réelle dès leur 1re requête.
      if (API_MODE === "integrated") publishIntegratedIdentity(user);
      return user;
    },
    staleTime: 60_000,
    retry: false,
  });

  useEffect(() => {
    // Session fermée (déconnexion, 401) : plus aucune identité pour les modules simulés.
    if (API_MODE === "integrated" && !data) publishIntegratedIdentity(null);
  }, [data]);

  const value = useMemo<SessionValue>(() => {
    const permissions = effectivePermissions(data);
    return {
      user: data ?? null,
      isLoading,
      error: data === undefined ? error : null,
      can: (permission) => permissions.has(permission),
      refresh: async () => {
        await queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY });
      },
      logout: async () => {
        try {
          await endpoints.logout();
        } finally {
          // Ordre important : la session passe à null AVANT la purge des autres données,
          // sans détacher l'observateur de session (un clear() complet le laisserait sur l'ancien utilisateur).
          queryClient.setQueryData(ME_QUERY_KEY, null);
          queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== ME_QUERY_KEY[0] });
        }
      },
    };
  }, [data, isLoading, error, queryClient]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession doit être utilisé dans <SessionProvider>");
  return ctx;
}
