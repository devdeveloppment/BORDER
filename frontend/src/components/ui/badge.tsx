import { AlertOctagon, AlertTriangle, CheckCircle2, CircleAlert } from "lucide-react";
import type { ReactNode } from "react";
import type { AlertStatus, Level } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { ALERT_STATUS_LABEL, LEVEL_LABEL } from "@/lib/labels";

export function Badge({ children, className, tone = "neutral" }: { children: ReactNode; className?: string; tone?: "neutral" | "brand" | "navy" | "ok" | "warn" | "danger" }) {
  const tones = {
    neutral: "bg-surface-alt text-ink-700 border-line",
    brand: "bg-brand-50 text-brand-700 border-brand-100",
    navy: "bg-navy-900 text-white border-navy-900",
    ok: "bg-ok-soft text-ok-ink border-ok/20",
    warn: "bg-warn-soft text-warn-ink border-warn/25",
    danger: "bg-danger-soft text-danger-ink border-danger/20",
  } as const;
  return <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap", tones[tone], className)}>{children}</span>;
}

const LEVEL_STYLE: Record<Level, { cls: string; dot: string; Icon: typeof CheckCircle2 }> = {
  NORMAL: { cls: "bg-ok-soft text-ok-ink border-ok/25", dot: "bg-ok", Icon: CheckCircle2 },
  ATTENTION: { cls: "bg-warn-soft text-warn-ink border-warn/30", dot: "bg-warn", Icon: CircleAlert },
  ELEVE: { cls: "bg-danger-soft text-danger-ink border-danger/25", dot: "bg-danger", Icon: AlertTriangle },
  CRITIQUE: { cls: "bg-critical-soft text-critical border-critical/30", dot: "bg-critical", Icon: AlertOctagon },
};

export const LEVEL_DOT = Object.fromEntries(Object.entries(LEVEL_STYLE).map(([k, v]) => [k, v.dot])) as Record<Level, string>;

/** Niveau d'indicateur : couleur TOUJOURS doublée d'une icône et d'un libellé (§11.2). */
export function LevelBadge({ level, score, className }: { level: Level; score?: number; className?: string }) {
  const { cls, Icon } = LEVEL_STYLE[level];
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold whitespace-nowrap", cls, className)}>
      <Icon className="size-3.5" aria-hidden="true" />
      {LEVEL_LABEL[level]}
      {score !== undefined ? <span className="tabular font-medium opacity-90">· {score}</span> : null}
    </span>
  );
}

const STATUS_TONE: Record<AlertStatus, "brand" | "warn" | "neutral" | "danger" | "ok" | "navy"> = {
  NOUVELLE: "brand",
  EN_COURS: "warn",
  EXAMINEE: "neutral",
  CONFIRMEE: "danger",
  ECARTEE: "ok",
  CLOTUREE: "navy",
};

export function AlertStatusBadge({ status }: { status: AlertStatus }) {
  return <Badge tone={STATUS_TONE[status]}>{ALERT_STATUS_LABEL[status]}</Badge>;
}
