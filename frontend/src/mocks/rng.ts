/** Générateur pseudo-aléatoire déterministe (mulberry32) : données de démonstration reproductibles. */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Hash entier stable de plusieurs entiers → [0, 1). */
export function noise(...values: number[]): number {
  let h = 2166136261;
  for (const v of values) {
    h ^= v;
    h = Math.imul(h, 16777619);
  }
  return mulberry32(h)();
}

/** UUID v4 déterministe pour les mocks. */
export function mockUuid(namespace: number, index: number): string {
  const rand = mulberry32(namespace * 1_000_003 + index);
  const hex = Array.from({ length: 32 }, () => Math.floor(rand() * 16).toString(16));
  hex[12] = "4";
  hex[16] = ((parseInt(hex[16] ?? "0", 16) & 0x3) | 0x8).toString(16);
  const s = hex.join("");
  return `${s.slice(0, 8)}-${s.slice(8, 12)}-${s.slice(12, 16)}-${s.slice(16, 20)}-${s.slice(20)}`;
}

export function pick<T>(items: readonly T[], r: number): T {
  return items[Math.min(items.length - 1, Math.floor(r * items.length))] as T;
}
