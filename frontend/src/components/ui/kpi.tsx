import { ArrowDownRight, ArrowRight, ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/cn";
import { formatNumber, formatPercent, variation } from "@/lib/format";

export function KpiCard({
  label,
  value,
  previous,
  suffix,
  accent = "brand",
  hint,
}: {
  label: string;
  value: number;
  previous?: number;
  suffix?: string;
  accent?: "brand" | "warn" | "danger" | "ok" | "navy";
  hint?: string;
}) {
  const accents = { brand: "border-l-brand-600", warn: "border-l-warn", danger: "border-l-danger", ok: "border-l-ok", navy: "border-l-navy-900" } as const;
  const delta = previous !== undefined ? variation(value, previous) : null;
  const Arrow = delta === null ? null : delta > 0.5 ? ArrowUpRight : delta < -0.5 ? ArrowDownRight : ArrowRight;
  return (
    <div className={cn("min-w-[9.5rem] sm:min-w-0 rounded-[var(--radius-card)] border border-l-4 border-line bg-white px-3.5 py-3 shadow-[var(--shadow-card)]", accents[accent])}>
      <p className="truncate text-xs font-medium text-ink-500">{label}</p>
      <p className="tabular mt-1 text-2xl font-semibold tracking-tight text-navy-900">
        {formatNumber(value)}
        {suffix ? <span className="text-base font-medium text-ink-500">{suffix}</span> : null}
      </p>
      {delta !== null && Arrow ? (
        <p className="tabular mt-0.5 flex flex-wrap items-center gap-x-1 text-xs text-ink-500">
          <Arrow className="size-3.5 shrink-0" aria-hidden="true" />
          <span className="font-medium whitespace-nowrap text-ink-700">{formatPercent(delta)}</span>
          <span className="whitespace-nowrap">vs période préc.</span>
        </p>
      ) : hint ? (
        <p className="mt-0.5 text-xs text-ink-500">{hint}</p>
      ) : null}
    </div>
  );
}
