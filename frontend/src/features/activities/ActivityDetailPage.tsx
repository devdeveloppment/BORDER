import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { Badge, LevelBadge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/feedback";
import { DefinitionList, PageHeader } from "@/components/ui/page";
import { endpoints } from "@/lib/api/endpoints";
import { formatDateTime } from "@/lib/format";
import { ACTIVITY_TYPE_LABEL, SOURCE_TYPE_LABEL } from "@/lib/labels";

/** Écran 12 — Détail d'une activité (404 si inexistante ou hors organisme). */
export function ActivityDetailPage() {
  const { id = "" } = useParams();
  const { data: a, isLoading, error, refetch } = useQuery({ queryKey: ["activity", id], queryFn: () => endpoints.activity(id) });

  if (error) {
    return (
      <Card>
        <ErrorState error={error} onRetry={() => void refetch()} />
      </Card>
    );
  }
  if (isLoading || !a) return <LoadingBlock rows={8} />;

  return (
    <>
      <PageHeader breadcrumb={{ label: "Activités", to: "/app/activites" }} title={a.reference} description={`${ACTIVITY_TYPE_LABEL[a.activity_type]} · ${a.border_post.name}`} actions={<>{a.is_demo ? <Badge tone="warn">Donnée de démonstration</Badge> : null}<LevelBadge level={a.level} /></>} />
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardHeader title="Données" />
          <CardBody>
            <DefinitionList
              items={[
                { label: "Date et heure", value: formatDateTime(a.occurred_at) },
                { label: "Poste", value: <Link className="text-brand-700 hover:underline" to={`/app/postes/${a.border_post.id}`}>{a.border_post.code} — {a.border_post.name}</Link> },
                { label: "Type", value: ACTIVITY_TYPE_LABEL[a.activity_type] },
                { label: "Catégorie", value: a.category },
                { label: "Véhicule (référence pseudonymisée)", value: <span className="font-mono text-xs">{a.vehicle_ref ?? "—"}</span> },
                { label: "Référence opérationnelle", value: a.operational_ref ?? "—" },
                { label: "Temps de traitement", value: a.processing_minutes !== null ? `${String(a.processing_minutes).replace(".", ",")} min` : "—" },
                { label: "Statut", value: a.status },
              ]}
            />
          </CardBody>
        </Card>
        <div className="space-y-5">
          <Card>
            <CardHeader title="Source et traçabilité" />
            <CardBody>
              <DefinitionList
                items={[
                  { label: "Source", value: `${a.source.name} (${SOURCE_TYPE_LABEL[a.source.source_type]})` },
                  { label: "Import d'origine", value: a.import_job?.file_name ?? "—" },
                  { label: "Créée le", value: formatDateTime(a.created_at) },
                  { label: "Dernière modification", value: formatDateTime(a.updated_at) },
                ]}
              />
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Alertes liées" />
            {a.linked_alerts.length === 0 ? (
              <EmptyState positive title="Aucune alerte liée" />
            ) : (
              <ul className="divide-y divide-line">
                {a.linked_alerts.map((al) => (
                  <li key={al.id}>
                    <Link to={`/app/alertes/${al.id}`} className="flex items-center justify-between gap-2 px-4 py-2.5 text-[13px] hover:bg-brand-50">
                      <span className="font-medium text-brand-700">{al.reference}</span>
                      <LevelBadge level={al.level} />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card>
            <CardHeader title="Historique des modifications" />
            {a.history.length === 0 ? (
              <EmptyState title="Aucune modification" description="L'enregistrement n'a pas été modifié depuis sa création." />
            ) : (
              <ul className="divide-y divide-line">
                {a.history.map((h, i) => (
                  <li key={i} className="px-4 py-2.5 text-[13px]">
                    <p className="text-ink-900">
                      <span className="font-medium">{h.field}</span> : {h.old_value} → {h.new_value}
                    </p>
                    <p className="text-xs text-ink-500">
                      {formatDateTime(h.at)} · {h.actor}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}
