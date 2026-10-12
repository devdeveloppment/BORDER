const numberFmt = new Intl.NumberFormat("fr-FR");
const dateFmt = new Intl.DateTimeFormat("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric" });
const dateTimeFmt = new Intl.DateTimeFormat("fr-FR", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});
const timeFmt = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" });

/** Espaces insécables produites par Intl (U+202F, U+00A0), normalisées en espace simple. */
const NARROW_SPACES = new RegExp(`[${String.fromCharCode(0x202f, 0x00a0)}]`, "g");

/** Séparateur de milliers : espace (spécification interne non publiée §11.4). */
export function formatNumber(value: number): string {
  return numberFmt.format(value).replace(NARROW_SPACES, " ");
}

export function formatPercent(value: number, withSign = true): string {
  const rounded = Math.round(value * 10) / 10;
  const sign = withSign && rounded > 0 ? "+" : "";
  return `${sign}${String(rounded).replace(".", ",")} %`;
}

export function formatDate(iso: string): string {
  return dateFmt.format(new Date(iso));
}

export function formatDateTime(iso: string): string {
  return dateTimeFmt.format(new Date(iso)).replace(",", "");
}

export function formatTime(iso: string): string {
  return timeFmt.format(new Date(iso));
}

export function variation(current: number, previous: number): number {
  if (previous === 0) return current === 0 ? 0 : 100;
  return ((current - previous) / previous) * 100;
}

export function ageLabel(iso: string, now: Date = new Date()): string {
  const minutes = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 60000));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h`;
  return `${Math.round(hours / 24)} j`;
}
