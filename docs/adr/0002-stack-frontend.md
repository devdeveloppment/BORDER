# ADR 0002 — Versions de la stack frontend (Phase 1)

- **Statut** : acceptée
- **Date** : 08/10/2026

## Choix et compatibilités vérifiées

| Paquet | Version | Justification |
|---|---|---|
| react / react-dom | 19.3.0 | Décision P3 |
| typescript | **6.0.3** (et non 7.0) | `typescript-eslint` 8.71 exige `typescript < 6.1` |
| vite | 8.3.4 | Compatible `@vitejs/plugin-react` 6 et `@tailwindcss/vite` 4.3 |
| tailwindcss | 4.3.3 | Décision P3 ; jetons du §11.2 déclarés dans `@theme` |
| react-router | 8.4.0 | API `createBrowserRouter` / `RouterProvider` (`react-router/dom`) |
| @tanstack/react-query | 5.104 | Cache client, compatible React 19 |
| msw | 3.0.2 | Option renommée `onUnhandledFrame` (ex-`onUnhandledRequest`) |
| echarts | 6.1 | Import modulaire, rendu SVG ; heatmap / boîtes à moustaches (§13) |
| Radix UI (dialog, dropdown, tabs) | 1.x / 2.x | Primitives accessibles, composants stylés « à la shadcn/ui » |
| vitest | **4.1.11** (et non 5.x) | Vitest 5 n'accepte pas Node 25 (`^22.12 \|\| ^24 \|\| >=26`) |
| jsdom | **29.1.1** (et non 30) | jsdom 30 exclut Node 25 |
| @playwright/test + @axe-core/playwright | 1.64 / 4.13 | E2E multi-formats et audit WCAG réel (contraste) |

## Notes

- **shadcn/ui** : la CLI (interactive) n'est pas utilisée ; les composants suivent les mêmes conventions
  (Radix + Tailwind + `class-variance-authority`) et sont versionnés dans `src/components/ui`.
- **Node** : la phase 1 a été développée sous Node 25.1 (non LTS). Le projet est désormais aligné sur
  **Node 24 LTS** (`.nvmrc` = 24, `engines` = `^24.0.0`). Vérification du 08/10/2026 sous Node 24.21.0 / npm 11.19.0 :
  `npm ci` sans avertissement de moteur, 0 vulnérabilité, typecheck, lint, Vitest 69/69, build, Playwright 32/32 (4 ignorés attendus) ;
  l'avertissement `--localstorage-file` propre à Node 25 a disparu. Le lockfile a été resynchronisé : aucune version
  installée modifiée, entrées orphelines (restes des rétrogradations Vitest/jsdom) supprimées.
- **Montées de version possibles sous Node 24** (non effectuées, hors périmètre) : Vitest 5 et jsdom 30 acceptent Node 24 ;
  TypeScript 7 reste bloqué par `typescript-eslint`.
- **Graphiques et accessibilité** : le module ARIA d'ECharts écrase l'`aria-label` du conteneur ; il est
  désactivé au profit d'un conteneur `role="img"` portant libellé et résumé chiffré, le rendu interne étant masqué.
