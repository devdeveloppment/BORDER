import { setupWorker } from "msw/browser";
import type { ApiMode } from "@/lib/env";
import { deferredHandlers, handlers, setIntegratedMode } from "./handlers";

/** Démarre MSW : toutes les routes (`mock`) ou les seuls modules reportés (`integrated`, P2.10). */
export async function startMocks(mode: Exclude<ApiMode, "live">): Promise<void> {
  const integrated = mode === "integrated";
  setIntegratedMode(integrated);
  const worker = setupWorker(...(integrated ? deferredHandlers : handlers));
  await worker.start({ onUnhandledFrame: "bypass", quiet: true });
}
