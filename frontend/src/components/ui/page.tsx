import { ChevronLeft, ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { formatNumber } from "@/lib/format";
import { Button } from "./button";

export function PageHeader({ title, description, actions, breadcrumb }: { title: string; description?: ReactNode; actions?: ReactNode; breadcrumb?: { label: string; to: string } }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        {breadcrumb ? (
          <Link to={breadcrumb.to} className="mb-1 inline-flex items-center gap-1 text-[13px] font-medium text-brand-700 hover:underline">
            <ChevronLeft className="size-4" aria-hidden="true" /> {breadcrumb.label}
          </Link>
        ) : null}
        <h1 className="text-xl font-semibold tracking-tight text-navy-900 sm:text-2xl">{title}</h1>
        {description ? <p className="mt-1 text-[13px] text-ink-500">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function Pagination({ page, pageSize, count, onPage }: { page: number; pageSize: number; count: number; onPage: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(count / pageSize));
  const from = count === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(count, page * pageSize);
  return (
    <nav aria-label="Pagination" className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3 text-[13px] text-ink-500">
      <p className="tabular">
        {formatNumber(from)}–{formatNumber(to)} sur {formatNumber(count)}
      </p>
      <div className="flex items-center gap-2">
        <Button variant="secondary" size="sm" onClick={() => onPage(page - 1)} disabled={page <= 1}>
          <ChevronLeft aria-hidden="true" /> Précédent
        </Button>
        <span className="tabular" aria-current="page">
          Page {page} / {pages}
        </span>
        <Button variant="secondary" size="sm" onClick={() => onPage(page + 1)} disabled={page >= pages}>
          Suivant <ChevronRight aria-hidden="true" />
        </Button>
      </div>
    </nav>
  );
}

/** Tableau de définition clé / valeur (fiches détail). */
export function DefinitionList({ items }: { items: { label: string; value: ReactNode }[] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
      {items.map((item) => (
        <div key={item.label} className="min-w-0">
          <dt className="text-xs font-medium text-ink-500">{item.label}</dt>
          <dd className="mt-0.5 break-words text-sm text-ink-900">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
