import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { ApiError } from "@/lib/api/client";
import { ME_QUERY_KEY, SessionProvider } from "@/lib/auth/session";
import { PeriodProvider } from "@/lib/period";

export function createQueryClient(): QueryClient {
  // Session expirée ou fermée côté serveur (inactivité, désactivation, MFA réinitialisée…) : toute réponse 401
  // ramène la session à « anonyme » ; l'écran de connexion s'affiche (P2.10). Les données en cache sont purgées.
  const onUnauthorized = (error: unknown) => {
    if (!(error instanceof ApiError) || error.status !== 401) return;
    if (client.getQueryData(ME_QUERY_KEY) === null) return;
    client.setQueryData(ME_QUERY_KEY, null);
    client.removeQueries({ predicate: (query) => query.queryKey[0] !== ME_QUERY_KEY[0] });
  };
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({ onError: onUnauthorized }),
    mutationCache: new MutationCache({ onError: onUnauthorized }),
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        // Pas de nouvelle tentative sur 4xx (401/403/404 sont des réponses définitives).
        retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
      },
      // Aucune donnée sensible conservée après coup dans le cache des mutations (secret TOTP, codes de secours).
      mutations: { gcTime: 0 },
    },
  });
  return client;
}

export function AppProviders({ client, children }: { client: QueryClient; children: ReactNode }) {
  return (
    <QueryClientProvider client={client}>
      <SessionProvider>
        <PeriodProvider>{children}</PeriodProvider>
      </SessionProvider>
    </QueryClientProvider>
  );
}
