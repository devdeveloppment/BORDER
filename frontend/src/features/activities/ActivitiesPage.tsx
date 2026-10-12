import { useQuery } from "@tanstack/react-query";
import { Download, Plus, Search } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Badge, LevelBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/feedback";
import { Input, Select } from "@/components/ui/form";
import { PageHeader, Pagination } from "@/components/ui/page";
import { DataTable } from "@/components/ui/table";
import { endpoints } from "@/lib/api/endpoints";
import type { Activity, ActivityType, Level } from "@/lib/api/types";
import { useSession } from "@/lib/auth/session";
import { formatDateTime, formatNumber } from "@/lib/format";
import { ACTIVITY_TYPE_LABEL, LEVEL_LABEL } from "@/lib/labels";
import { PERMISSIONS } from "@/lib/permissions";

const STATUS_LABEL: Record<Activity["status"], string> = { enregistree: "Enregistrée", validee: "Validée", rejetee: "Rejetée" };

function SearchForm({ initial, onSubmit }: { initial: string; onSubmit: (value: string) => void }) {
  const [value, setValue] = useState(initial);
  return (
    <form
      role="search"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(value.trim());
      }}
      className="relative"
    >
      <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-500" aria-hidden="true" />
      <Input type="search" aria-label="Rechercher une référence" placeholder="Référence ou réf. opérationnelle…" value={value} onChange={(e) => setValue(e.target.value)} className="pl-9" />
    </form>
  );
}

/** Écran 11 — Registre des activités (pagination serveur, 50 par page). */
export function ActivitiesPage() {
  const { can } = useSession();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const get = (k: string) => params.get(k) ?? "";
  const query = { search: get("search"), post: get("post"), activity_type: get("activity_type"), level: get("level"), status: get("status"), page: Number(get("page") || 1) };

  const { data, isLoading, error, refetch } = useQuery({ queryKey: ["activities", query], queryFn: () => endpoints.activities(query) });
  const { data: posts } = useQuery({ queryKey: ["posts"], queryFn: endpoints.posts });

  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next);
  };
  const hasFilters = ["search", "post", "activity_type", "level", "status"].some((k) => params.get(k));

  return (
    <>
      <PageHeader
        title="Registre des activités"
        description={data ? `${formatNumber(data.count)} activité(s) correspondant aux critères` : "Activités opérationnelles de votre organisme"}
        actions={
          <>
            {can(PERMISSIONS.activitiesExport) ? (
              <Button variant="secondary" disabled title="Export CSV / Excel journalisé : module métier non encore implémenté">
                <Download aria-hidden="true" /> Exporter
              </Button>
            ) : null}
            {can(PERMISSIONS.activitiesCreate) ? (
              <Button disabled title="Saisie manuelle : module métier non encore implémenté">
                <Plus aria-hidden="true" /> Nouvelle activité
              </Button>
            ) : null}
          </>
        }
      />
      <Card>
        <div className="grid grid-cols-1 gap-3 border-b border-line p-4 sm:grid-cols-2 xl:grid-cols-[2fr_1fr_1fr_1fr_1fr]">
          <SearchForm key={get("search")} initial={get("search")} onSubmit={(value) => update("search", value)} />
          <Select aria-label="Poste" value={get("post")} onChange={(e) => update("post", e.target.value)}>
            <option value="">Tous les postes</option>
            {posts?.map((p) => (
              <option key={p.id} value={p.id}>
                {p.code} — {p.name}
              </option>
            ))}
          </Select>
          <Select aria-label="Type d'activité" value={get("activity_type")} onChange={(e) => update("activity_type", e.target.value)}>
            <option value="">Tous les types</option>
            {(Object.keys(ACTIVITY_TYPE_LABEL) as ActivityType[]).map((t) => (
              <option key={t} value={t}>
                {ACTIVITY_TYPE_LABEL[t]}
              </option>
            ))}
          </Select>
          <Select aria-label="Niveau" value={get("level")} onChange={(e) => update("level", e.target.value)}>
            <option value="">Tous les niveaux</option>
            {(Object.keys(LEVEL_LABEL) as Level[]).map((l) => (
              <option key={l} value={l}>
                {LEVEL_LABEL[l]}
              </option>
            ))}
          </Select>
          <Select aria-label="Statut" value={get("status")} onChange={(e) => update("status", e.target.value)}>
            <option value="">Tous les statuts</option>
            {(Object.keys(STATUS_LABEL) as Activity["status"][]).map((s) => (
              <option key={s} value={s}>
                {STATUS_LABEL[s]}
              </option>
            ))}
          </Select>
        </div>

        {error ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : isLoading || !data ? (
          <LoadingBlock className="p-4" rows={10} />
        ) : data.results.length === 0 ? (
          <EmptyState
            title="Aucune activité ne correspond aux filtres"
            action={
              hasFilters ? (
                <Button variant="secondary" onClick={() => setParams(new URLSearchParams())}>
                  Réinitialiser les filtres
                </Button>
              ) : undefined
            }
          />
        ) : (
          <>
            <DataTable<Activity>
              caption="Registre des activités"
              rows={data.results}
              rowKey={(a) => a.id}
              onRowClick={(a) => navigate(`/app/activites/${a.id}`)}
              columns={[
                { key: "ref", header: "Référence", cell: (a) => <Link to={`/app/activites/${a.id}`} className="font-medium text-brand-700 hover:underline" onClick={(e) => e.stopPropagation()}>{a.reference}</Link> },
                { key: "date", header: "Date / heure", cell: (a) => <span className="tabular">{formatDateTime(a.occurred_at)}</span> },
                { key: "post", header: "Poste", cell: (a) => a.border_post.code },
                { key: "type", header: "Type", cell: (a) => ACTIVITY_TYPE_LABEL[a.activity_type] },
                { key: "cat", header: "Catégorie", cell: (a) => a.category },
                { key: "veh", header: "Véhicule (pseudo.)", cell: (a) => <span className="font-mono text-xs">{a.vehicle_ref ?? "—"}</span> },
                { key: "status", header: "Statut", cell: (a) => <Badge tone={a.status === "rejetee" ? "warn" : "neutral"}>{STATUS_LABEL[a.status]}</Badge> },
                { key: "level", header: "Niveau", cell: (a) => <LevelBadge level={a.level} /> },
                { key: "src", header: "Source", cell: (a) => <span className="text-ink-500">{a.source.name}</span> },
              ]}
              mobileCard={(a) => (
                <Link to={`/app/activites/${a.id}`} className="block px-4 py-3 hover:bg-brand-50">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[13px] font-medium text-brand-700">{a.reference}</span>
                    <LevelBadge level={a.level} />
                  </div>
                  <p className="mt-1 text-xs text-ink-500">
                    {formatDateTime(a.occurred_at)} · {a.border_post.code} · {ACTIVITY_TYPE_LABEL[a.activity_type]}
                  </p>
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
