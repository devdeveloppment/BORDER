/**
 * Charte de vocabulaire (§9.5, §17.3, CA-12) : aucun libellé accusatoire dans l'interface,
 * les mocks d'API ni les textes générés. Analyse statique de tout le code source frontend.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

// Vitest s'exécute depuis le dossier `frontend/`.
const SRC = join(process.cwd(), "src");
const SELF = join("test", "vocabulary.test.ts");

const FORBIDDEN: RegExp[] = [/fraude/i, /\bcriminels?\b/i, /suspect/i, /infraction/i, /coupable/i];

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.(ts|tsx|css)$/.test(name) ? [path] : [];
  });
}

describe("charte de vocabulaire", () => {
  it("n'utilise aucun terme interdit dans le code source", () => {
    const hits: string[] = [];
    for (const file of sourceFiles(SRC)) {
      if (relative(SRC, file) === SELF) continue;
      readFileSync(file, "utf8")
        .split("\n")
        .forEach((line, i) => {
          for (const re of FORBIDDEN) if (re.test(line)) hits.push(`${relative(SRC, file)}:${i + 1} → ${line.trim()}`);
        });
    }
    expect(hits).toEqual([]);
  });
});
