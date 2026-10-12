import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { useMediaQuery } from "@/lib/useMediaQuery";

export interface Column<T> {
  key: string;
  header: string;
  cell: (row: T) => ReactNode;
  className?: string;
  numeric?: boolean;
}

/**
 * Tableau responsive : tableau sémantique à partir de `md`, liste de cartes en dessous (§11.3 mobile).
 * Une seule des deux présentations est rendue (pas de contenu dupliqué pour les technologies d'assistance).
 */
export function DataTable<T>({
  caption,
  columns,
  rows,
  rowKey,
  mobileCard,
  onRowClick,
}: {
  caption: string;
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  mobileCard: (row: T) => ReactNode;
  onRowClick?: (row: T) => void;
}) {
  const isWide = useMediaQuery("(min-width: 768px)");
  if (isWide) {
    return (
      // Zone défilante focalisable au clavier (WCAG 2.1.1 — règle axe « scrollable-region-focusable »)
      <div className="overflow-x-auto" tabIndex={0} role="region" aria-label={caption}>
        <table className="w-full border-collapse text-left text-[13px]">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr className="border-b border-line bg-surface-alt/70">
              {columns.map((c) => (
                <th key={c.key} scope="col" className={cn("px-4 py-2.5 text-xs font-semibold tracking-wide text-ink-500 uppercase", c.numeric && "text-right", c.className)}>
                  {c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={rowKey(row)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={cn("border-b border-line last:border-0 even:bg-surface-alt/40", onRowClick && "cursor-pointer hover:bg-brand-50")}
              >
                {columns.map((c) => (
                  <td key={c.key} className={cn("px-4 py-2.5 align-middle", c.numeric && "tabular text-right", c.className)}>
                    {c.cell(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  return (
    <ul className="divide-y divide-line" aria-label={caption}>
      {rows.map((row) => (
        <li key={rowKey(row)}>{mobileCard(row)}</li>
      ))}
    </ul>
  );
}
