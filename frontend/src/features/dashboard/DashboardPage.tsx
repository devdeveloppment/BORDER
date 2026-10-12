import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Info } from "lucide-react";
import { useMemo } from "react";
import { Link } from "react-router";
import { baseAxis, CHART_COLORS, EChart } from "@/components/charts/EChart";
import { PostsSchematic } from "@/components/charts/PostsSchematic";
import { AlertStatusBadge, LevelBadge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingBlock, Skeleton } from "@/components/ui/feedback";
import { Select } from "@/components/ui/form";
import { KpiCard } from "@/components/ui/kpi";
import { PageHeader } from "@/components/ui/page";
import { endpoints } from "@/lib/api/endpoints";
import type { DashboardData, PeriodKey } from "@/lib/api/types";
import { useSession } from "@/lib/auth/session";
import { ageLabel, formatDateTime, formatNumber } from "@/lib/format";
import { PERIOD_LABEL } from "@/lib/labels";
import { usePeriod } from "@/lib/period";
import { PERMISSIONS } from "@/lib/permissions";

function ActivityChart({ data }: { data: DashboardData }) {
  const option = useMemo(
    () => ({
      grid: { left: 48, right: 16, top: 32, bottom: 28 },
      tooltip: { trigger: "axis", valueFormatter: (v: number) => formatNumber(v) },
      legend: { top: 0, right: 0, textStyle: { color: CHART_COLORS.text, fontSize: 11 }, itemWidth: 14, itemHeight: 8 },
      xAxis: { type: "category", data: data.series.map((p) => (p.bucket.length === 10 ? p.bucket.slice(8, 10) + "/" + p.bucket.slice(5, 7) : p.bucket)), ...baseAxis, splitLine: { show: false } },
      yAxis: { type: "value", ...baseAxis, axisLabel: { ...baseAxis.axisLabel, formatter: (v: number) => formatNumber(v) } },
      series: [
        { name: "Période sélectionnée", type: "line", smooth: true, symbol: "none", data: data.series.map((p) => p.value), lineStyle: { width: 2.5, color: CHART_COLORS.primary }, itemStyle: { color: CHART_COLORS.primary }, areaStyle: { color: "rgba(21,101,192,0.08)" } },
        { name: "Période précédente", type: "line", smooth: true, symbol: "none", data: data.series.map((p) => p.previous), lineStyle: { width: 1.5, type: "dashed", color: CHART_COLORS.reference }, itemStyle: { color: CHART_COLORS.reference } },
      ],
    }),
    [data],
  );
  const total = data.series.reduce((s, p) => s + p.value, 0);
  const prev = data.series.reduce((s, p) => s + p.previous, 0);
  return (
    <EChart
      option={option}
      className="h-64"
      ariaLabel={`Courbe d'activité — ${PERIOD_LABEL[data.period]}`}
      summary={`Total ${formatNumber(total)} activités sur la période, contre ${formatNumber(prev)} sur la période précédente.`}
    />
  );
}

/** Écran 9 — Tableau de bord. Toutes les valeurs proviennent de l'API (simulée en Phase 1). */
export function DashboardPage() {
  const { user, can } = useSession();
  const { period, setPeriod } = usePeriod();
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ["dashboard", period], queryFn: () => endpoints.dashboard(period) });

  return (
    <>
      <PageHeader
        title="Tableau de bord"
        description={`Situation de ${user?.organization?.name ?? "l'organisme"} — ${PERIOD_LABEL[period].toLowerCase()}`}
        actions={
          <label className="md:hidden">
            <span className="sr-only">Période</span>
            <Select value={period} onChange={(e) => setPeriod(e.target.value as PeriodKey)} className="h-9 text-[13px]">
              {(Object.keys(PERIOD_LABEL) as PeriodKey[]).map((p) => (
                <option key={p} value={p}>
                  {PERIOD_LABEL[p]}
                </option>
              ))}
            </Select>
          </label>
        }
      />

      {error ? (
        <Card>
          <ErrorState error={error} onRetry={() => void refetch()} />
        </Card>
      ) : (
        <div className="space-y-5">
          <section aria-label="Indicateurs clés">
            {isLoading || !data ? (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5 min-[1500px]:grid-cols-9" role="status" aria-label="Chargement des indicateurs">
                {Array.from({ length: 9 }, (_, i) => (
                  <Skeleton key={i} className="h-[92px]" />
                ))}
              </div>
            ) : (
              <div tabIndex={0} role="region" aria-label="Liste des indicateurs" className="-mx-4 flex snap-x gap-3 overflow-x-auto px-4 pb-1 sm:mx-0 sm:grid sm:grid-cols-3 sm:overflow-visible sm:px-0 lg:grid-cols-5 min-[1500px]:grid-cols-9 [&>*]:snap-start">
                <KpiCard label="Activités" value={data.kpis.activities} previous={data.kpis.previous.activities} />
                <KpiCard label="Contrôles" value={data.kpis.controls} previous={data.kpis.previous.controls} />
                <KpiCard label="Véhicules" value={data.kpis.vehicles} previous={data.kpis.previous.vehicles} />
                <KpiCard label="Événements" value={data.kpis.events} previous={data.kpis.previous.events} accent="navy" />
                <KpiCard label="Alertes" value={data.kpis.alerts} previous={data.kpis.previous.alerts} accent="warn" />
                <KpiCard label="Alertes critiques" value={data.kpis.critical_alerts} accent="danger" hint="Sur la période" />
                <KpiCard label="Alertes en cours" value={data.kpis.open_alerts} accent="warn" hint="Tous statuts ouverts" />
                <KpiCard label="Alertes traitées" value={data.kpis.processed_alerts} accent="ok" hint="Confirmées, écartées, clôturées" />
                <KpiCard label="Postes actifs" value={data.kpis.active_posts} suffix={` / ${data.kpis.total_posts}`} accent="ok" hint="Postes en service" />
              </div>
            )}
          </section>

          <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.6fr_1fr]">
            <Card>
              <CardHeader title="Activité par période" description="Comparaison avec la période précédente de même durée" />
              <CardBody>{isLoading || !data ? <Skeleton className="h-64" /> : data.series.length ? <ActivityChart data={data} /> : <EmptyState title="Aucune donnée pour cette période" />}</CardBody>
            </Card>

            <Card aria-labelledby="brief-title">
              <CardHeader id="brief-title" title="Situation du jour" description={data ? `Générée le ${formatDateTime(data.brief.generated_at)}` : undefined} />
              <CardBody>
                {isLoading || !data ? (
                  <LoadingBlock rows={5} />
                ) : (
                  <>
                    <dl className="divide-y divide-line">
                      {data.brief.items.map((item) => (
                        <div key={item.heading} className="grid grid-cols-[8.5rem_1fr] gap-3 py-2 text-[13px]">
                          <dt className="font-medium text-ink-500">{item.heading}</dt>
                          <dd className="text-ink-900">{item.text}</dd>
                        </div>
                      ))}
                    </dl>
                    <p className="mt-3 flex items-start gap-1.5 text-xs text-ink-500">
                      <Info className="mt-px size-3.5 shrink-0" aria-hidden="true" />
                      {data.brief.disclaimer}
                    </p>
                  </>
                )}
              </CardBody>
            </Card>
          </div>

          <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.6fr_1fr]">
            <Card>
              <CardHeader
                title="Postes et niveaux d'indicateur"
                actions={
                  can(PERMISSIONS.postsView) ? (
                    <Link to="/app/postes" className="inline-flex items-center gap-1 text-[13px] font-medium text-brand-700 hover:underline">
                      Tous les postes <ArrowRight className="size-4" aria-hidden="true" />
                    </Link>
                  ) : null
                }
              />
              <CardBody>{isLoading || !data ? <Skeleton className="h-60" /> : <PostsSchematic posts={data.posts} />}</CardBody>
            </Card>

            <Card>
              <CardHeader
                title="Alertes récentes"
                actions={
                  <Link to="/app/alertes" className="inline-flex items-center gap-1 text-[13px] font-medium text-brand-700 hover:underline">
                    Toutes <ArrowRight className="size-4" aria-hidden="true" />
                  </Link>
                }
              />
              {isLoading || !data ? (
                <CardBody>
                  <LoadingBlock rows={5} />
                </CardBody>
              ) : data.recent_alerts.length === 0 ? (
                <EmptyState positive title="Aucune alerte" description="Aucun indicateur ne nécessite de vérification." />
              ) : (
                <ul className="divide-y divide-line">
                  {data.recent_alerts.map((a) => (
                    <li key={a.id}>
                      <Link to={`/app/alertes/${a.id}`} className="flex items-start gap-3 px-4 py-3 hover:bg-brand-50">
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-[13px] font-medium text-ink-900">{a.title}</p>
                          <p className="mt-0.5 text-xs text-ink-500">
                            {a.reference} · il y a {ageLabel(a.detected_at)}
                          </p>
                        </div>
                        <div className="flex shrink-0 flex-col items-end gap-1">
                          <LevelBadge level={a.level} score={a.score} />
                          <AlertStatusBadge status={a.status} />
                        </div>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </div>
      )}
    </>
  );
}
