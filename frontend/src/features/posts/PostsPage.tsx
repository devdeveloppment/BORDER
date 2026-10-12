import { useQuery } from "@tanstack/react-query";
import { LayoutGrid, Plus, Rows3 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { Badge, LevelBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/feedback";
import { PageHeader } from "@/components/ui/page";
import { DataTable } from "@/components/ui/table";
import { endpoints } from "@/lib/api/endpoints";
import type { BorderPost } from "@/lib/api/types";
import { useSession } from "@/lib/auth/session";
import { cn } from "@/lib/cn";
import { formatNumber, formatPercent } from "@/lib/format";
import { POST_STATUS_LABEL } from "@/lib/labels";
import { PERMISSIONS } from "@/lib/permissions";

function StatusBadge({ status }: { status: BorderPost["status"] }) {
  return <Badge tone={status === "actif" ? "brand" : "neutral"}>{POST_STATUS_LABEL[status]}</Badge>;
}

function Tile({ post }: { post: BorderPost }) {
  return (
    <Link to={`/app/postes/${post.id}`} className="block rounded-[var(--radius-card)] border border-line bg-white p-4 shadow-[var(--shadow-card)] transition-colors duration-150 hover:border-brand-600">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-xs font-semibold text-ink-500">{post.code}</p>
          <p className="truncate font-semibold text-navy-900">{post.name}</p>
        </div>
        <LevelBadge level={post.level} score={post.risk_score} />
      </div>
      <dl className="mt-4 grid grid-cols-3 gap-2 text-center">
        <div>
          <dt className="text-[11px] text-ink-500">Volume du jour</dt>
          <dd className="tabular text-lg font-semibold text-navy-900">{formatNumber(post.today_volume)}</dd>
        </div>
        <div>
          <dt className="text-[11px] text-ink-500">Variation</dt>
          <dd className="tabular text-lg font-semibold text-navy-900">{formatPercent(post.variation_pct)}</dd>
        </div>
        <div>
          <dt className="text-[11px] text-ink-500">Alertes</dt>
          <dd className="tabular text-lg font-semibold text-navy-900">{post.open_alerts}</dd>
        </div>
      </dl>
      <div className="mt-3 flex items-center justify-between text-xs text-ink-500">
        <StatusBadge status={post.status} />
        <span>Capacité {post.capacity_per_hour ?? "—"} / h</span>
      </div>
    </Link>
  );
}

/** Écran 15 — Référentiel des postes (vue tableau ou tuiles « jumeau numérique »). */
export function PostsPage() {
  const { can } = useSession();
  const navigate = useNavigate();
  const [view, setView] = useState<"tiles" | "table">("tiles");
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ["posts"], queryFn: endpoints.posts });

  return (
    <>
      <PageHeader
        title="Postes frontaliers"
        description="Postes suivis par votre organisme et indicateurs du jour."
        actions={
          <>
            <div role="group" aria-label="Mode d'affichage" className="flex rounded-[var(--radius-card)] border border-line bg-white p-0.5">
              {(
                [
                  ["tiles", "Tuiles", LayoutGrid],
                  ["table", "Tableau", Rows3],
                ] as const
              ).map(([key, label, Icon]) => (
                <button
                  key={key}
                  type="button"
                  aria-pressed={view === key}
                  onClick={() => setView(key)}
                  className={cn("flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[13px] font-medium", view === key ? "bg-brand-50 text-brand-700" : "text-ink-500 hover:text-ink-900")}
                >
                  <Icon className="size-4" aria-hidden="true" /> {label}
                </button>
              ))}
            </div>
            {can(PERMISSIONS.postsManage) ? (
              <Button disabled title="Création de poste : module métier non encore implémenté">
                <Plus aria-hidden="true" /> Créer un poste
              </Button>
            ) : null}
          </>
        }
      />
      {error ? (
        <Card>
          <ErrorState error={error} onRetry={() => void refetch()} />
        </Card>
      ) : isLoading || !data ? (
        <LoadingBlock rows={6} />
      ) : data.length === 0 ? (
        <Card>
          <EmptyState title="Aucun poste configuré" />
        </Card>
      ) : view === "tiles" ? (
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4" aria-label="Postes">
          {data.map((p) => (
            <li key={p.id}>
              <Tile post={p} />
            </li>
          ))}
        </ul>
      ) : (
        <Card>
          <DataTable<BorderPost>
            caption="Liste des postes"
            rows={data}
            rowKey={(p) => p.id}
            onRowClick={(p) => navigate(`/app/postes/${p.id}`)}
            columns={[
              { key: "code", header: "Code", cell: (p) => <Link to={`/app/postes/${p.id}`} className="font-medium text-brand-700 hover:underline" onClick={(e) => e.stopPropagation()}>{p.code}</Link> },
              { key: "name", header: "Nom", cell: (p) => p.name },
              { key: "status", header: "Statut", cell: (p) => <StatusBadge status={p.status} /> },
              { key: "volume", header: "Volume du jour", numeric: true, cell: (p) => formatNumber(p.today_volume) },
              { key: "var", header: "Variation", numeric: true, cell: (p) => formatPercent(p.variation_pct) },
              { key: "alerts", header: "Alertes ouvertes", numeric: true, cell: (p) => p.open_alerts },
              { key: "level", header: "Niveau", cell: (p) => <LevelBadge level={p.level} score={p.risk_score} /> },
            ]}
            mobileCard={(p) => (
              <div className="p-3">
                <Tile post={p} />
              </div>
            )}
          />
        </Card>
      )}
    </>
  );
}
