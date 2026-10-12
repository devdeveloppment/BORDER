/**
 * P2.10 — Modes de l'API (tout simulé / intégré / production) et alignement sur le contrat OpenAPI du backend.
 *
 * - Production : mocks absents du bundle PAR CONSTRUCTION (contrôle positif sur un build de démonstration).
 * - Chaque appel de `endpoints` vise une route du schéma OpenAPI versionné, ou un module reporté simulé ;
 *   jamais un module reporté présent dans l'API réelle (aucune donnée simulée ne masque une route réelle).
 * - La matrice rôles → permissions des mocks n'est importée par aucun module applicatif.
 */
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { build } from "vite";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { endpoints } from "@/lib/api/endpoints";
import { resolveApiMode, resolveAppEnv } from "@/lib/env";
import { deferredHandlers, isDeferredPath } from "@/mocks/handlers";

const ROOT = resolve(__dirname, "../..");
const OPENAPI = resolve(ROOT, "../backend/openapi/rbi-api-v1.yaml");

describe("résolution du mode", () => {
  it.each([
    ["demo", undefined, "mock"],
    ["demo", "true", "mock"],
    ["demo", "deferred", "integrated"],
    ["demo", "false", "live"],
    ["staging", "deferred", "integrated"],
    ["production", "true", "live"],
    ["production", "deferred", "live"],
    ["production", undefined, "live"],
  ] as const)("APP_ENV=%s, VITE_API_MOCKS=%s → %s", (env, raw, mode) => {
    expect(resolveApiMode(resolveAppEnv(env), raw)).toBe(mode);
  });

  it("toute valeur inconnue d'environnement est « demo » (bandeau affiché)", () => {
    expect(resolveAppEnv("prod")).toBe("demo");
    expect(resolveAppEnv(undefined)).toBe("demo");
  });
});

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

async function buildWith(appEnv: string, mocks: string): Promise<{ dir: string; text: string; names: string[] }> {
  const dir = mkdtempSync(join(tmpdir(), "rbi-bundle-"));
  const previous = { env: process.env.VITE_APP_ENV, mocks: process.env.VITE_API_MOCKS };
  process.env.VITE_APP_ENV = appEnv;
  process.env.VITE_API_MOCKS = mocks;
  try {
    await build({ root: ROOT, configFile: join(ROOT, "vite.config.ts"), logLevel: "silent", build: { outDir: dir, emptyOutDir: true } });
  } finally {
    process.env.VITE_APP_ENV = previous.env;
    process.env.VITE_API_MOCKS = previous.mocks;
  }
  const all = files(dir);
  return { dir, names: all.map((f) => f.slice(dir.length + 1).replace(/\\/g, "/")), text: all.map((f) => readFileSync(f, "utf-8")).join("\n") };
}

const MOCK_MARKERS = ["X-RBI-Mock", "rbi.mock.session", "Demo-RBI-2026!", "mockServiceWorker", "Action non simulée"];

describe("bundle de production", { timeout: 180_000 }, () => {
  it("ne contient ni le code des mocks, ni le service worker MSW, ni les comptes de démonstration", async () => {
    const production = await buildWith("production", "true");
    const demo = await buildWith("demo", "deferred");
    try {
      // Contrôle positif : le build de démonstration contient bien ce que l'on cherche (la recherche n'est pas vide).
      expect(demo.names).toContain("mockServiceWorker.js");
      expect(demo.text).toContain("X-RBI-Mock");
      expect(production.names).not.toContain("mockServiceWorker.js");
      for (const marker of MOCK_MARKERS) expect(production.text, marker).not.toContain(marker);
    } finally {
      rmSync(production.dir, { recursive: true, force: true });
      rmSync(demo.dir, { recursive: true, force: true });
    }
  });
});

// --- Contrat : routes appelées par le frontend ↔ schéma OpenAPI du backend --------------------------------

function openApiOperations(): Set<string> {
  expect(existsSync(OPENAPI), `schéma OpenAPI introuvable : ${OPENAPI}`).toBe(true);
  const text = readFileSync(OPENAPI, "utf-8");
  const paths = text.split("\npaths:\n")[1]!.split("\ncomponents:\n")[0]!;
  const operations = new Set<string>();
  let current = "";
  for (const line of paths.split("\n")) {
    const path = /^ {2}(\/\S+):$/.exec(line);
    if (path) current = path[1]!.replace(/^\/api\/v1/, "").replace(/\{[^}]+\}/g, "{}");
    const method = /^ {4}(get|post|patch|put|delete):$/.exec(line);
    if (method && current) operations.add(`${method[1]!.toUpperCase()} ${current}`);
  }
  return operations;
}

const ID = "00000000-0000-4000-8000-000000000001";

describe("contrat des routes", () => {
  const calls: string[] = [];

  beforeEach(() => {
    document.cookie = "csrftoken=test-token; path=/";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(String(input));
        calls.push(`${init?.method ?? "GET"} ${url.pathname.replace(/^\/api\/v1/, "").split("/").map((s) => (s === ID ? "{}" : s)).join("/")}`);
        return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
      }),
    );
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    calls.length = 0;
  });

  it("chaque appel vise une opération du schéma OpenAPI ou un module reporté absent de l'API réelle", async () => {
    for (const fn of Object.values(endpoints) as ((...args: unknown[]) => Promise<unknown>)[]) {
      await fn(ID, ID, ID).catch(() => undefined);
    }
    const operations = openApiOperations();
    expect(calls.length).toBeGreaterThanOrEqual(Object.keys(endpoints).length);
    const unknown: string[] = [];
    for (const call of calls) {
      const path = call.split(" ")[1]!;
      if (operations.has(call)) {
        expect(isDeferredPath(path), `${call} : route livrée déclarée comme reportée`).toBe(false);
      } else if (!isDeferredPath(path)) {
        unknown.push(call);
      }
    }
    expect(unknown, "appels hors contrat (ni livrés, ni reportés)").toEqual([]);
    // Aucun module reporté n'existe dans l'API réelle : sinon MSW masquerait des données réelles.
    for (const operation of operations) expect(isDeferredPath(operation.split(" ")[1]!), operation).toBe(false);
  });

  it("les handlers du mode intégré ne simulent que des modules reportés", () => {
    const delivered = /\/api\/v1\/(auth|me|users|roles|organization|audit-logs|platform|public)\b/;
    for (const handler of deferredHandlers) {
      const path = String((handler.info as { path?: unknown }).path ?? "");
      expect(path, path).not.toMatch(delivered);
      expect(isDeferredPath(path.replace("/api/v1", ""))).toBe(true);
    }
    expect(deferredHandlers.length).toBeGreaterThan(10);
  });
});

describe("aucune autorité locale sur les permissions", () => {
  it("la matrice rôles → permissions des mocks n'est importée que par les mocks et les tests", () => {
    const sources = files(join(ROOT, "src")).filter((f) => /\.(ts|tsx)$/.test(f) && !/[\\/](mocks|test)[\\/]/.test(f) && !/\.test\.tsx?$/.test(f));
    for (const file of sources) {
      const text = readFileSync(file, "utf-8");
      expect(text, file).not.toMatch(/mocks\/roles|MOCK_ROLE_PERMISSIONS|permissionsForRoles/);
      // Seul main.tsx charge les mocks, dynamiquement et jamais en production.
      if (!file.endsWith("main.tsx")) expect(text, file).not.toMatch(/from "@\/mocks\//);
    }
  });
});
