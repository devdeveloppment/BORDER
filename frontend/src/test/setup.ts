import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { createElement } from "react";
import { afterAll, afterEach, beforeAll, vi } from "vitest";
import { resetMockSession } from "@/mocks/handlers";
import { server } from "@/mocks/server";

// Les handlers MSW simulent une latence réseau réaliste (200–600 ms par appel).
configure({ asyncUtilTimeout: 5000 });

// jsdom n'implémente ni matchMedia ni ResizeObserver : polyfills minimaux.
// Les media queries `min-width` sont évaluées contre window.innerWidth (1024 px par défaut).
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => {
    const min = /min-width:\s*(\d+)px/.exec(query);
    return {
      matches: min ? window.innerWidth >= Number(min[1]) : false,
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    };
  },
});

globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// Les graphiques ECharts (rendu SVG/canvas) sont vérifiés dans Playwright ; en jsdom on rend un substitut accessible.
vi.mock("@/components/charts/EChart", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/components/charts/EChart")>();
  return {
    ...actual,
    EChart: ({ ariaLabel }: { ariaLabel: string }) => createElement("div", { role: "img", "aria-label": ariaLabel }),
  };
});

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
  resetMockSession();
  sessionStorage.clear();
});
afterAll(() => server.close());
