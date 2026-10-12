import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ALERTS } from "@/mocks/db";
import { ACCOUNTS, renderApp, signIn } from "@/test/utils";

const scenario = ALERTS.find((a) => a.reference === "ALR-2026-000123")!;

describe("alerte scénarisée — Poste Démo 07 (§26.1, §30)", () => {
  it("explique le score 72 facteur par facteur (CA-11)", async () => {
    await signIn(ACCOUNTS.supervisorA);
    renderApp(`/app/alertes/${scenario.id}`);
    expect(await screen.findByRole("heading", { level: 1, name: /Poste Démo 07/ })).toBeInTheDocument();
    expect(screen.getByText(/Niveau ÉLEVÉ \(72\/100\)/)).toBeInTheDocument();
    for (const [label, pts] of [["Variation de volume", "+20"], ["Écart horaire", "+15"], ["Anomalie historique", "+17"], ["Répétition d'événements", "+20"]] as const) {
      const row = screen.getByText(label).closest("li")!;
      expect(within(row).getByText(pts)).toBeInTheDocument();
    }
    expect(screen.getByText("72 / 100")).toBeInTheDocument();
    expect(screen.getByText(/ne constitue pas une conclusion/)).toBeInTheDocument();
  });

  it("suit le cycle NOUVELLE → EN COURS → EXAMINÉE avec motif obligatoire", async () => {
    await signIn(ACCOUNTS.supervisorA);
    const user = userEvent.setup();
    renderApp(`/app/alertes/${scenario.id}`);

    await user.click(await screen.findByRole("button", { name: "Prendre en charge" }));
    expect(await screen.findByRole("button", { name: "Marquer comme examinée" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Marquer comme examinée" }));
    const dialog = await screen.findByRole("dialog");
    const confirm = within(dialog).getByRole("button", { name: "Valider" });
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/Motif/), "Vérification des enregistrements nocturnes effectuée.");
    await user.click(confirm);

    expect(await screen.findByRole("button", { name: "Confirmer l'écart" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Écarter" })).toBeInTheDocument();
    expect(screen.getByText("Vérification des enregistrements nocturnes effectuée.")).toBeInTheDocument();
  });

  it("présente l'alerte en lecture seule à l'Analyste", async () => {
    await signIn(ACCOUNTS.analystA);
    renderApp(`/app/alertes/${scenario.id}`);
    expect(await screen.findByText(/lecture seule/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Prendre en charge" })).not.toBeInTheDocument();
  });
});
