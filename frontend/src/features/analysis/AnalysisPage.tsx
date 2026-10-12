import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { baseAxis, CHART_COLORS, EChart } from "@/components/charts/EChart";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorState, Skeleton } from "@/components/ui/feedback";
import { Select } from "@/components/ui/form";
import { PageHeader } from "@/components/ui/page";
import { DataTable } from "@/components/ui/table";
import { endpoints } from "@/lib/api/endpoints";
import type { AnalysisData } from "@/lib/api/types";
import { formatNumber, formatPercent, variation } from "@/lib/format";

const DAYS = ["Dim.", "Lun.", "Mar.", "Mer.", "Jeu.", "Ven.", "Sam."];

function CompareChart({ data }: { data: AnalysisData }) {
  const option = useMemo(
    () => ({
      grid: { left: 52, right: 16, top: 32, bottom: 28 },
      tooltip: { trigger: "axis", valueFormatter: (v: number) => formatNumber(v) },
      legend: { top: 0, right: 0, textStyle: { color: CHART_COLORS.text, fontSize: 11 }, itemWidth: 14, itemHeight: 8 },
      xAxis: { type: "category", data: data.series.map((p) => `${p.bucket.slice(8, 10)}/${p.bucket.slice(5, 7)}`), ...baseAxis, splitLine: { show: false } },
      yAxis: { type: "value", ...baseAxis },
      series: [
        { name: `Période A — ${data.period_a}`, type: "line", smooth: true, symbol: "none", data: data.series.map((p) => p.a), lineStyle: { width: 2.5, color: CHART_COLORS.primary }, itemStyle: { color: CHART_COLORS.primary } },
        { name: `Période B — ${data.period_b}`, type: "line", smooth: true, symbol: "none", data: data.series.map((p) => p.b), lineStyle: { width: 1.5, type: "dashed", color: CHART_COLORS.reference }, itemStyle: { color: CHART_COLORS.reference } },
      ],
    }),
    [data],
  );
  return <EChart option={option} className="h-72" ariaLabel="Comparaison des volumes journaliers entre la période A et la période B" />;
}

function Heatmap({ data }: { data: AnalysisData }) {
  const option = useMemo(() => {
    const max = Math.max(...data.heatmap.map((h) => h.value), 1);
    return {
      grid: { left: 48, right: 16, top: 8, bottom: 56 },
      tooltip: { position: "top", formatter: (p: { value: [number, number, number] }) => `${DAYS[p.value[1]]} ${p.value[0]} h : ${formatNumber(p.value[2])}` },
      xAxis: { type: "category", data: Array.from({ length: 24 }, (_, h) => `${h}`), ...baseAxis, splitArea: { show: false } },
      yAxis: { type: "category", data: DAYS, ...baseAxis },
      visualMap: { min: 0, max, calculable: false, orient: "horizontal", left: "center", bottom: 0, itemHeight: 120, inRange: { color: ["#F2F4F7", "#9cc2ec", "#1565C0", "#0B1F3A"] }, textStyle: { color: CHART_COLORS.text, fontSize: 11 } },
      series: [{ type: "heatmap", data: data.heatmap.map((h) => [h.hour, h.day, h.value]), itemStyle: { borderColor: "#fff", borderWidth: 1 } }],
    };
  }, [data]);
  return <EChart option={option} className="h-72" ariaLabel="Carte de chaleur de l'activité moyenne par jour de semaine et par heure (4 dernières semaines)" />;
}

/** Écran 17 — Analyse : comparaison de périodes, heatmap jour × heure, variations par poste et catégorie. */
export function AnalysisPage() {
  const [days, setDays] = useState(28);
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ["analysis", days], queryFn: () => endpoints.analysis(days) });

  return (
    <>
      <PageHeader
        title="Analyse historique"
        description="Comparaisons à périmètre égal : période A (récente) vs période B (précédente de même durée)."
        actions={
          <label className="flex items-center gap-2 text-[13px] text-ink-700">
            Fenêtre
            <Select value={days} onChange={(e) => setDays(Number(e.target.value))} className="h-9 w-40">
              <option value={7}>7 jours</option>
              <option value={28}>28 jours</option>
              <option value={90}>90 jours</option>
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
          <Card>
            <CardHeader title="Volumes journaliers — période A vs B" />
            <CardBody>{isLoading || !data ? <Skeleton className="h-72" /> : <CompareChart data={data} />}</CardBody>
          </Card>
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
            <Card>
              <CardHeader title="Profil jour × heure" description="Activité moyenne sur les 4 dernières semaines" />
              <CardBody>{isLoading || !data ? <Skeleton className="h-72" /> : <Heatmap data={data} />}</CardBody>
            </Card>
            <Card>
              <CardHeader title="Par catégorie" />
              {isLoading || !data ? (
                <CardBody>
                  <Skeleton className="h-72" />
                </CardBody>
              ) : (
                <DataTable
                  caption="Variation par catégorie"
                  rows={data.by_category}
                  rowKey={(c) => c.category}
                  columns={[
                    { key: "c", header: "Catégorie", cell: (c) => c.category },
                    { key: "a", header: "Période A", numeric: true, cell: (c) => formatNumber(c.a) },
                    { key: "b", header: "Période B", numeric: true, cell: (c) => formatNumber(c.b) },
                    { key: "v", header: "Variation", numeric: true, cell: (c) => formatPercent(variation(c.a, c.b)) },
                  ]}
                  mobileCard={(c) => (
                    <div className="flex justify-between px-4 py-2.5 text-[13px]">
                      <span>{c.category}</span>
                      <span className="tabular">{formatPercent(variation(c.a, c.b))}</span>
                    </div>
                  )}
                />
              )}
            </Card>
          </div>
          <Card>
            <CardHeader title="Classement des postes" description="Triés par variation décroissante" />
            {isLoading || !data ? (
              <CardBody>
                <Skeleton className="h-60" />
              </CardBody>
            ) : (
              <DataTable
                caption="Variation par poste"
                rows={[...data.by_post].sort((x, y) => y.variation_pct - x.variation_pct)}
                rowKey={(p) => p.code}
                columns={[
                  { key: "code", header: "Code", cell: (p) => p.code },
                  { key: "name", header: "Poste", cell: (p) => p.name },
                  { key: "a", header: "Période A", numeric: true, cell: (p) => formatNumber(p.a) },
                  { key: "b", header: "Période B", numeric: true, cell: (p) => formatNumber(p.b) },
                  { key: "d", header: "Écart absolu", numeric: true, cell: (p) => formatNumber(p.a - p.b) },
                  { key: "v", header: "Variation", numeric: true, cell: (p) => <span className="font-semibold">{formatPercent(p.variation_pct)}</span> },
                ]}
                mobileCard={(p) => (
                  <div className="flex justify-between px-4 py-2.5 text-[13px]">
                    <span>{p.name}</span>
                    <span className="tabular font-semibold">{formatPercent(p.variation_pct)}</span>
                  </div>
                )}
              />
            )}
          </Card>
        </div>
      )}
    </>
  );
}
