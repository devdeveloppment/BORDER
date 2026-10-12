import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router";
import { AlertStatusBadge, LevelBadge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/feedback";
import { Select } from "@/components/ui/form";
import { PageHeader, Pagination } from "@/components/ui/page";
import { DataTable } from "@/components/ui/table";
import { endpoints } from "@/lib/api/endpoints";
import type { Alert, AlertStatus, AlertType, Level } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { ageLabel, formatDateTime, formatNumber } from "@/lib/format";
import { ALERT_STATUS_LABEL, ALERT_TYPE_LABEL, LEVEL_LABEL } from "@/lib/labels";

const STATUS_TABS: (AlertStatus | "")[] = ["", "NOUVELLE", "EN_COURS", "EXAMINEE", "CONFIRMEE", "ECARTEE", "CLOTUREE"];

/** Écran 13 — Liste des alertes. Les filtres sont portés par l'URL (partageables, retour arrière). */
export function AlertsPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const level = params.get("level") ?? "";
  const type = params.get("alert_type") ?? "";
  const post = params.get("post") ?? "";
  const page = Number(params.get("page") ?? 1) || 1;

  const query = { status, level, alert_type: type, post, page };
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ["alerts", query], queryFn: () => endpoints.alerts(query) });
  const { data: posts } = useQuery({ queryKey: ["posts"], queryFn: endpoints.posts });

  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next);
  };

  return (
    <>
      <PageHeader title="Alertes" description="Indicateurs nécessitant une vérification humaine. Une alerte n'est jamais une conclusion." />
      <Card>
        <div role="group" aria-label="Filtrer par statut" className="flex gap-1 overflow-x-auto border-b border-line px-2">
          {STATUS_TABS.map((s) => {
            const count = s ? data?.status_counts[s] : data?.total;
            const active = status === s;
            return (
              <button
                key={s || "all"}
                type="button"
                aria-pressed={active}
                onClick={() => update("status", s)}
                className={cn("-mb-px flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2.5 text-[13px] font-medium", active ? "border-brand-600 text-brand-700" : "border-transparent text-ink-500 hover:text-ink-900")}
              >
                {s ? ALERT_STATUS_LABEL[s] : "Toutes"}
                {count !== undefined ? <span className="tabular rounded-full bg-surface-alt px-1.5 text-[11px] text-ink-700">{formatNumber(count)}</span> : null}
              </button>
            );
          })}
        </div>

        <div className="grid grid-cols-1 gap-3 border-b border-line p-4 sm:grid-cols-3">
          <label className="space-y-1">
            <span className="text-xs font-medium text-ink-500">Niveau</span>
            <Select value={level} onChange={(e) => update("level", e.target.value)}>
              <option value="">Tous les niveaux</option>
              {(Object.keys(LEVEL_LABEL) as Level[]).filter((l) => l !== "NORMAL").map((l) => (
                <option key={l} value={l}>
                  {LEVEL_LABEL[l]}
                </option>
              ))}
            </Select>
          </label>
          <label className="space-y-1">
            <span className="text-xs font-medium text-ink-500">Type</span>
            <Select value={type} onChange={(e) => update("alert_type", e.target.value)}>
              <option value="">Tous les types</option>
              {(Object.keys(ALERT_TYPE_LABEL) as AlertType[]).map((t) => (
                <option key={t} value={t}>
                  {ALERT_TYPE_LABEL[t]}
                </option>
              ))}
            </Select>
          </label>
          <label className="space-y-1">
            <span className="text-xs font-medium text-ink-500">Poste</span>
            <Select value={post} onChange={(e) => update("post", e.target.value)}>
              <option value="">Tous les postes</option>
              {posts?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.code} — {p.name}
                </option>
              ))}
            </Select>
          </label>
        </div>

        {error ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : isLoading || !data ? (
          <LoadingBlock className="p-4" rows={8} />
        ) : data.results.length === 0 ? (
          <EmptyState positive title="Aucune alerte" description="Aucune alerte ne correspond à ces critères." />
        ) : (
          <>
            <DataTable<Alert>
              caption="Liste des alertes"
              rows={data.results}
              rowKey={(a) => a.id}
              onRowClick={(a) => navigate(`/app/alertes/${a.id}`)}
              columns={[
                { key: "ref", header: "Référence", cell: (a) => <Link to={`/app/alertes/${a.id}`} className="font-medium text-brand-700 hover:underline" onClick={(e) => e.stopPropagation()}>{a.reference}</Link> },
                { key: "date", header: "Détectée", cell: (a) => <span className="tabular">{formatDateTime(a.detected_at)}</span> },
                { key: "type", header: "Type", cell: (a) => ALERT_TYPE_LABEL[a.alert_type] },
                { key: "post", header: "Poste", cell: (a) => a.border_post.name },
                { key: "level", header: "Niveau", cell: (a) => <LevelBadge level={a.level} score={a.score} /> },
                { key: "status", header: "Statut", cell: (a) => <AlertStatusBadge status={a.status} /> },
                { key: "assignee", header: "Responsable", cell: (a) => a.assignee?.name ?? <span className="text-ink-500">Non assignée</span> },
                { key: "age", header: "Ancienneté", numeric: true, cell: (a) => ageLabel(a.detected_at) },
              ]}
              mobileCard={(a) => (
                <Link to={`/app/alertes/${a.id}`} className="block px-4 py-3 hover:bg-brand-50">
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-[13px] font-medium text-ink-900">{a.title}</p>
                    <LevelBadge level={a.level} score={a.score} />
                  </div>
                  <div className="mt-1.5 flex items-center justify-between gap-2 text-xs text-ink-500">
                    <span>
                      {a.reference} · {ageLabel(a.detected_at)}
                    </span>
                    <AlertStatusBadge status={a.status} />
                  </div>
                </Link>
              )}
            />
            <Pagination page={data.page} pageSize={data.page_size} count={data.count} onPage={(p) => update("page", String(p))} />
          </>
        )}
      </Card>
    </>
  );
}
