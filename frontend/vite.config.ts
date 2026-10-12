import { rmSync } from "node:fs";
import { join } from "node:path";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";

/**
 * Production (VITE_APP_ENV=production) : le code des mocks est éliminé du bundle (main.tsx, env.ts) et le service
 * worker MSW, copié depuis public/, est retiré de la sortie — aucun moyen de l'activer (P2.10, ADR 0012).
 */
function noMocksInProduction(): Plugin {
  let production = false;
  return {
    name: "rbi-no-mocks-in-production",
    apply: "build",
    configResolved(config) {
      production = config.env.VITE_APP_ENV === "production"; // même source que import.meta.env (.env et environnement)
    },
    writeBundle(options) {
      if (production && options.dir) rmSync(join(options.dir, "mockServiceWorker.js"), { force: true });
    },
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss(), noMocksInProduction()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  // Derrière Nginx (P2.10, ADR 0012) : le rechargement à chaud se connecte au port du proxy ; sources montées
  // depuis Windows : surveillance par interrogation. Variables lues uniquement par le conteneur de développement.
  server: {
    port: 5173,
    strictPort: true,
    hmr: process.env.RBI_VITE_HMR_CLIENT_PORT ? { clientPort: Number(process.env.RBI_VITE_HMR_CLIENT_PORT) } : undefined,
    watch: process.env.RBI_VITE_POLLING === "true" ? { usePolling: true, interval: 300 } : undefined,
  },
  // Nonce de la CSP : marqueur remplacé par Nginx à chaque requête ($request_id) sur les balises <script> et
  // <style> générées par Vite. Sans proxy (npm run dev / preview), le marqueur reste inerte (pas de CSP).
  html: { cspNonce: "RBI_CSP_NONCE" },
  build: {
    sourcemap: false,
    rolldownOptions: {
      output: {
        // ECharts isolé dans son propre fichier (mis en cache indépendamment).
        // Les mocks MSW restent dans un chunk chargé dynamiquement, uniquement s'ils sont actifs.
        manualChunks(id: string) {
          if (id.includes("node_modules/echarts") || id.includes("node_modules/zrender")) return "charts";
        },
      },
    },
  },
});
