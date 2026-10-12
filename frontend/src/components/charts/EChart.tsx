import { BarChart, HeatmapChart, LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent, VisualMapComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { SVGRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";
import { cn } from "@/lib/cn";

// Import modulaire : seuls les graphiques utilisés sont embarqués.
echarts.use([LineChart, BarChart, HeatmapChart, GridComponent, TooltipComponent, LegendComponent, VisualMapComponent, SVGRenderer]);

export type EChartOption = echarts.EChartsCoreOption;

/** Palette institutionnelle des séries (non fonctionnelle : pas de vert/orange/rouge de statut). */
export const CHART_COLORS = { primary: "#1565C0", reference: "#9AA4B2", navy: "#0B1F3A", grid: "#E6E9EE", text: "#5F6B7A" };

export const baseAxis = {
  axisLine: { lineStyle: { color: CHART_COLORS.grid } },
  axisTick: { show: false },
  axisLabel: { color: CHART_COLORS.text, fontSize: 11, fontFamily: "Inter Variable, system-ui" },
  splitLine: { lineStyle: { color: CHART_COLORS.grid } },
};

/**
 * Graphique ECharts accessible : le conteneur expose `ariaLabel` (et `summary`, résumé chiffré)
 * comme une image ; le rendu SVG interne (axes, étiquettes) est masqué aux technologies d'assistance.
 */
export function EChart({ option, ariaLabel, summary, className }: { option: EChartOption; ariaLabel: string; summary?: string; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const instance = echarts.init(ref.current, undefined, { renderer: "svg" });
    chart.current = instance;
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(ref.current);
    return () => {
      observer.disconnect();
      instance.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    chart.current?.setOption(
      {
        textStyle: { fontFamily: "Inter Variable, system-ui" },
        animationDuration: 150,
        ...option,
      },
      true,
    );
  }, [option]);

  return (
    <div role="img" aria-label={summary ? `${ariaLabel}. ${summary}` : ariaLabel} className={cn("relative", className)}>
      <div ref={ref} aria-hidden="true" className="size-full" />
    </div>
  );
}
