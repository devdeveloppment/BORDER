import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { AppProviders, createQueryClient } from "@/app/providers";
import { routes } from "@/app/routes";
import { API_MODE } from "@/lib/env";
import "@/styles/index.css";

// Nonce de la page (CSP stricte) : les feuilles de style créées à l'exécution (verrouillage du défilement des
// fenêtres modales, bibliothèque Radix) doivent le porter, sinon le navigateur les bloque. Lu sur le script de
// l'application, fourni par le proxy à chaque réponse ; sans nonce (développement sans proxy), rien n'est défini.
const pageNonce = document.querySelector<HTMLScriptElement>("script[nonce]")?.nonce;
if (pageNonce) (globalThis as { __webpack_nonce__?: string }).__webpack_nonce__ = pageNonce;

async function enableMocks(): Promise<void> {
  // Production : condition évaluée à la construction (remplacement statique de import.meta.env) ; la branche
  // et le module des mocks disparaissent du bundle (vérifié par src/test/modes.test.ts, P2.10).
  if (import.meta.env.VITE_APP_ENV === "production") return;
  if (API_MODE === "live") return;
  // Import dynamique : le code des mocks n'est chargé que lorsqu'ils sont actifs.
  const { startMocks } = await import("@/mocks/browser");
  await startMocks(API_MODE);
}

void enableMocks().then(() => {
  const router = createBrowserRouter(routes);
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <AppProviders client={createQueryClient()}>
        <RouterProvider router={router} />
      </AppProviders>
    </StrictMode>,
  );
});
