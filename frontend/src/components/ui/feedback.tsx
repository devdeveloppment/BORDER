import { CheckCircle2, Inbox, RotateCw, ShieldAlert } from "lucide-react";
import type { ReactNode } from "react";
import { ApiError, NetworkError, describeError } from "@/lib/api/client";
import { cn } from "@/lib/cn";
import { Button } from "./button";

/** Squelette aux dimensions du composant — pas de spinner plein écran (§11.5). */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cn("animate-pulse rounded-md bg-ink-500/12", className)} />;
}

export function LoadingBlock({ label = "Chargement…", className, rows = 4 }: { label?: string; className?: string; rows?: number }) {
  return (
    <div role="status" aria-live="polite" className={cn("space-y-3", className)}>
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className={cn("h-9", i % 3 === 2 && "w-2/3")} />
      ))}
    </div>
  );
}

export function EmptyState({ title, description, action, positive, className }: { title: string; description?: string; action?: ReactNode; positive?: boolean; className?: string }) {
  const Icon = positive ? CheckCircle2 : Inbox;
  return (
    <div className={cn("flex flex-col items-center justify-center px-4 py-10 text-center", className)}>
      <Icon className={cn("mb-3 size-9", positive ? "text-ok" : "text-ink-500/70")} aria-hidden="true" />
      <p className={cn("font-semibold", positive ? "text-ok-ink" : "text-ink-900")}>{title}</p>
      {description ? <p className="mt-1 max-w-md text-[13px] text-ink-500">{description}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

/**
 * Erreur claire et non technique (§11.5). Un 403/404 ne révèle jamais l'existence d'une ressource.
 */
export function ErrorState({ error, onRetry, className }: { error: unknown; onRetry?: () => void; className?: string }) {
  const status = error instanceof ApiError ? error.status : 0;
  const denied = status === 403 || status === 404;
  const throttled = status === 429;
  return (
    <div role="alert" className={cn("flex flex-col items-center px-4 py-10 text-center", className)}>
      <ShieldAlert className="mb-3 size-9 text-ink-500/70" aria-hidden="true" />
      <p className="font-semibold text-ink-900">
        {denied ? "Vous n'avez pas accès à cette ressource" : "Le chargement n'a pas abouti"}
      </p>
      <p className="mt-1 max-w-md text-[13px] text-ink-500">
        {denied
          ? "Elle n'existe pas ou ne fait pas partie de votre périmètre."
          : throttled || error instanceof NetworkError || status >= 500
            ? describeError(error)
            : "Une erreur temporaire est survenue. Vous pouvez réessayer dans un instant."}
      </p>
      {!denied && onRetry ? (
        <Button variant="secondary" className="mt-4" onClick={onRetry}>
          <RotateCw aria-hidden="true" /> Réessayer
        </Button>
      ) : null}
    </div>
  );
}

export function Notice({ tone = "info", title, children, className }: { tone?: "info" | "warn" | "ok"; title?: string; children: ReactNode; className?: string }) {
  const tones = {
    info: "border-brand-600 bg-brand-50 text-navy-900",
    warn: "border-warn bg-warn-soft text-warn-ink",
    ok: "border-ok bg-ok-soft text-ok-ink",
  } as const;
  return (
    <div className={cn("rounded-[var(--radius-card)] border-l-4 px-4 py-3 text-[13px]", tones[tone], className)}>
      {title ? <p className="font-semibold">{title}</p> : null}
      <div className={title ? "mt-0.5" : undefined}>{children}</div>
    </div>
  );
}
