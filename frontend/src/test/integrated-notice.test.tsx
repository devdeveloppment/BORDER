/** P2.10 — En mode intégré, tout écran d'un module reporté porte la mention visible des données simulées. */
import { render, screen } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { describe, expect, it, vi } from "vitest";
import { DEFERRED_APP_ROUTES, SIMULATED_NOTICE, SimulatedModuleNotice } from "@/components/layout/SimulatedModuleNotice";
import { DemoBanner } from "@/components/layout/DemoBanner";

vi.mock("@/lib/env", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/env")>()), API_MODE: "integrated" }));

function at(path: string) {
  const router = createMemoryRouter([{ path: "*", element: <><DemoBanner /><SimulatedModuleNotice /></> }], { initialEntries: [path] });
  return render(<RouterProvider router={router} />);
}

describe("mode intégré", () => {
  it("affiche « Données simulées — module non encore implémenté » sur chaque module reporté", () => {
    expect(SIMULATED_NOTICE).toBe("Données simulées — module non encore implémenté");
    for (const route of DEFERRED_APP_ROUTES) {
      const view = at(route);
      expect(screen.getByTestId("simulated-module")).toHaveTextContent(SIMULATED_NOTICE);
      view.unmount();
    }
  });

  it("n'affiche pas la mention sur les écrans servis par l'API réelle, et annonce le mode dans le bandeau", () => {
    for (const route of ["/app/audit", "/app/admin/utilisateurs", "/app/admin/organisme", "/app/plateforme/organismes", "/app/profil"]) {
      const view = at(route);
      expect(screen.queryByTestId("simulated-module")).not.toBeInTheDocument();
      expect(screen.getByRole("note", { name: "Environnement" })).toHaveTextContent("API réelle — modules métier simulés");
      view.unmount();
    }
  });
});
