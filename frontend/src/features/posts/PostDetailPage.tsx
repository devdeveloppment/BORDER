import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { Link, useParams } from "react-router";
import { baseAxis, CHART_COLORS, EChart } from "@/components/charts/EChart";
import { AlertStatusBadge, Badge, LevelBadge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/feedback";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/overlay";
import { DefinitionList, PageHeader } from "@/components/ui/page";
import { endpoints } from "@/lib/api/endpoints";
import type { BorderPostDetail } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatDateTime, formatNumber, formatPercent } from "@/lib/format";
import { ACTIVITY_TYPE_LABEL, POST_STATUS_LABEL, POST_TYPE_LABEL } from "@/lib/labels";

function HourlyChart({ post }: { post: BorderPostDetail }) {
  const option = useMemo(
    () => ({
      grid: { left: 40, right: 12, top: 28, bottom: 28 },
      tooltip: { trigger: "axis" },
      legend: { top: 0, right: 0, textStyle: { color: CHART_COLORS.text, fontSize: 11 }, itemWidth: 12, itemHeight: 8 },
      xAxis: { type: "category", data: post.hourly.map((h) => `${String(h.hour).padStart(2, "0")} h`), ...baseAxis, splitLine: { show: false } },
      yAxis: { type: "value", ...baseAxis },
      series: [
        { name: "Aujourd'hui", type: "bar", data: post.hourly.map((h) => h.volume), itemStyle: { color: CHART_COLORS.primary, borderRadius: [2, 2, 0, 0] }, barMaxWidth: 14 },
        { name: "Profil habituel (moy. 4 sem.)", type: "line", data: post.hourly.map((h) => h.reference), symbol: "none", lineStyle: { color: CHART_COLORS.navy, type: "dashed" }, itemStyle: { color: CHART_COLORS.navy } },
      ],
    }),
    [post],
  );
  return <EChart option={option} className="h-60" ariaLabel={`Flux horaire du ${post.name} comparé au profil habituel`} />;
}

function CapacityGauge({ pct }: { pct: number }) {
  const tone = pct > 100 ? "bg-danger" : pct > 80 ? "bg-warn" : "bg-ok";
  const label = pct > 100 ? "Saturation" : pct > 80 ? "Charge élevée" : "Charge normale";
  return (
    <div>
      <div className="flex items-baseline justify-between text-[13px]">
        <span className="font-medium text-ink-700">Utilisation de la capacité (pic horaire)</span>
        <span className="tabular font-semibold text-navy-900">{pct} %</span>
      </div>
      <div className="mt-2 h-2.5 rounded-full bg-surface-alt" role="meter" aria-valuemin={0} aria-valuemax={150} aria-valuenow={pct} aria-label="Utilisation de la capacité">
        <div className={cn("h-2.5 rounded-full", tone)} style={{ width: `${Math.min(100, pct)}%` }} />
      </div>
      <p className="mt-1 text-xs text-ink-500">{label}</p>
    </div>
  );
}

/** Écran 16 — Fiche poste : POSTE → ACTIVITÉ → ALERTES → HISTORIQUE → STATISTIQUES. */
export function PostDetailPage() {
  const { id = "" } = useParams();
  const { data: post, isLoading, error, refetch } = useQuery({ queryKey: ["post", id], queryFn: () => endpoints.post(id) });
  const { data: activities } = useQuery({ queryKey: ["activities", { post: id }], queryFn: () => endpoints.activities({ post: id }), enabled: !!post });
  const { data: alerts } = useQuery({ queryKey: ["alerts", { post: id }], queryFn: () => endpoints.alerts({ post: id }), enabled: !!post });

  if (error) {
    return (
      <Card>
        <ErrorState error={error} onRetry={() => void refetch()} />
      </Card>
    );
  }
  if (isLoading || !post) return <LoadingBlock rows={10} />;

  return (
    <>
      <PageHeader breadcrumb={{ label: "Postes", to: "/app/postes" }} title={post.name} description={`${post.code} · ${post.location.locality}, ${post.location.region}`} actions={<LevelBadge level={post.level} score={post.risk_score} className="text-sm" />} />
      <Tabs defaultValue="poste">
        <TabsList aria-label="Sections du poste">
          <TabsTrigger value="poste">Poste</TabsTrigger>
          <TabsTrigger value="activite">Activité</TabsTrigger>
          <TabsTrigger value="alertes">Alertes</TabsTrigger>
          <TabsTrigger value="historique">Historique</TabsTrigger>
          <TabsTrigger value="statistiques">Statistiques</TabsTrigger>
        </TabsList>

        <TabsContent value="poste" className="grid grid-cols-1 gap-5 pt-5 xl:grid-cols-[1.4fr_1fr]">
          <Card>
            <CardHeader title="Fiche du poste" />
            <CardBody>
              <DefinitionList
                items={[
                  { label: "Code", value: post.code },
                  { label: "Type", value: POST_TYPE_LABEL[post.post_type] },
                  { label: "Statut", value: <Badge tone={post.status === "actif" ? "brand" : "neutral"}>{POST_STATUS_LABEL[post.status]}</Badge> },
                  { label: "Horaires", value: post.opening_hours },
                  { label: "Capacité théorique", value: post.capacity_per_hour ? `${post.capacity_per_hour} passages / heure` : "Non renseignée" },
                  { label: "Coordonnées (fictives)", value: <span className="tabular">{post.location.lat.toFixed(4)}, {post.location.lng.toFixed(4)}</span> },
                  { label: "Agents affectés", value: post.assigned_agents.length ? post.assigned_agents.map((a) => a.name).join(", ") : "Aucun" },
                ]}
              />
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Situation du jour" />
            <CardBody className="space-y-4">
              <dl className="grid grid-cols-2 gap-3">
                {[
                  ["Volume", formatNumber(post.today_volume)],
                  ["Variation", formatPercent(post.variation_pct)],
                  ["Contrôles", formatNumber(post.controls_today)],
                  ["Temps moyen", `${post.avg_processing_minutes.toFixed(1).replace(".", ",")} min`],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-md bg-surface-alt px-3 py-2">
                    <dt className="text-[11px] text-ink-500">{label}</dt>
                    <dd className="tabular text-lg font-semibold text-navy-900">{value}</dd>
                  </div>
                ))}
              </dl>
              <CapacityGauge pct={post.utilization_pct} />
            </CardBody>
          </Card>
        </TabsContent>

        <TabsContent value="activite" className="pt-5">
          <Card>
            <CardHeader title="Flux horaire" description="Aujourd'hui, comparé au profil habituel du même jour de semaine" />
            <CardBody>
              <HourlyChart post={post} />
            </CardBody>
          </Card>
        </TabsContent>

        <TabsContent value="alertes" className="pt-5">
          <Card>
            {!alerts ? (
              <LoadingBlock className="p-4" />
            ) : alerts.results.length === 0 ? (
              <EmptyState positive title="Aucune alerte" />
            ) : (
              <ul className="divide-y divide-line">
                {alerts.results.map((a) => (
                  <li key={a.id}>
                    <Link to={`/app/alertes/${a.id}`} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 hover:bg-brand-50">
                      <span className="text-[13px] font-medium text-ink-900">
                        {a.reference} — {a.title}
                      </span>
                      <span className="flex gap-2">
                        <LevelBadge level={a.level} score={a.score} />
                        <AlertStatusBadge status={a.status} />
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </TabsContent>

        <TabsContent value="historique" className="pt-5">
          <Card>
            <CardHeader title="Dernières activités enregistrées" />
            {!activities ? (
              <LoadingBlock className="p-4" />
            ) : (
              <ul className="divide-y divide-line">
                {activities.results.slice(0, 15).map((a) => (
                  <li key={a.id}>
                    <Link to={`/app/activites/${a.id}`} className="flex items-center justify-between gap-3 px-4 py-2.5 text-[13px] hover:bg-brand-50">
                      <span className="font-medium text-brand-700">{a.reference}</span>
                      <span className="text-ink-500">
                        {ACTIVITY_TYPE_LABEL[a.activity_type]} · {formatDateTime(a.occurred_at)}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </TabsContent>

        <TabsContent value="statistiques" className="pt-5">
          <Card>
            <CardBody>
              <DefinitionList
                items={[
                  { label: "Activités enregistrées (30 j)", value: activities ? formatNumber(activities.count) : "…" },
                  { label: "Alertes (toutes périodes)", value: alerts ? formatNumber(alerts.total) : "…" },
                  { label: "Pic horaire aujourd'hui", value: formatNumber(Math.max(...post.hourly.map((h) => h.volume))) },
                  { label: "Indicateur courant", value: <LevelBadge level={post.level} score={post.risk_score} /> },
                ]}
              />
            </CardBody>
          </Card>
        </TabsContent>
      </Tabs>
    </>
  );
}
