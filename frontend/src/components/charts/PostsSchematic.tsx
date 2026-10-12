import { Link } from "react-router";
import type { DashboardData } from "@/lib/api/types";
import { LEVEL_LABEL } from "@/lib/labels";

const FILL = { NORMAL: "#2E7D32", ATTENTION: "#EF6C00", ELEVE: "#C62828", CRITIQUE: "#7F1010" } as const;
const SHAPE_LABEL = { NORMAL: "●", ATTENTION: "▲", ELEVE: "■", CRITIQUE: "◆" } as const;

/**
 * Aperçu SCHÉMATIQUE des postes (positions relatives, sans fond cartographique).
 * La carte interactive OpenStreetMap / MapLibre est l'objet de la Phase 4.
 * Chaque niveau combine couleur + forme + libellé (accessibilité daltonisme / niveaux de gris).
 */
export function PostsSchematic({ posts }: { posts: DashboardData["posts"] }) {
  if (posts.length === 0) return <p className="py-8 text-center text-[13px] text-ink-500">Aucun poste configuré.</p>;
  const lats = posts.map((p) => p.location.lat);
  const lngs = posts.map((p) => p.location.lng);
  const [minLat, maxLat, minLng, maxLng] = [Math.min(...lats), Math.max(...lats), Math.min(...lngs), Math.max(...lngs)];
  const x = (lng: number) => 40 + ((lng - minLng) / Math.max(0.0001, maxLng - minLng)) * 520;
  const y = (lat: number) => 200 - ((lat - minLat) / Math.max(0.0001, maxLat - minLat)) * 170;

  return (
    <div>
      <svg viewBox="0 0 600 230" className="h-auto w-full rounded-md bg-brand-50" role="group" aria-label="Aperçu schématique des postes et de leur niveau d'indicateur">
        <defs>
          <pattern id="grid" width="30" height="30" patternUnits="userSpaceOnUse">
            <path d="M 30 0 L 0 0 0 30" fill="none" stroke="#cfe0f5" strokeWidth="1" />
          </pattern>
        </defs>
        <rect width="600" height="230" fill="url(#grid)" />
        {posts.map((p) => {
          const cx = x(p.location.lng);
          const cy = y(p.location.lat);
          const fill = FILL[p.level];
          return (
            <Link key={p.id} to={`/app/postes/${p.id}`} aria-label={`${p.name} — niveau ${LEVEL_LABEL[p.level]} (${p.risk_score}/100), ${p.open_alerts} alerte(s) ouverte(s)`}>
              <g className="cursor-pointer">
                {p.level === "NORMAL" ? <circle cx={cx} cy={cy} r="8" fill={fill} /> : null}
                {p.level === "ATTENTION" ? <path d={`M ${cx} ${cy - 10} L ${cx + 9} ${cy + 7} L ${cx - 9} ${cy + 7} Z`} fill={fill} /> : null}
                {p.level === "ELEVE" ? <rect x={cx - 8} y={cy - 8} width="16" height="16" fill={fill} /> : null}
                {p.level === "CRITIQUE" ? <path d={`M ${cx} ${cy - 10} L ${cx + 10} ${cy} L ${cx} ${cy + 10} L ${cx - 10} ${cy} Z`} fill={fill} /> : null}
                <text x={cx} y={cy + 24} textAnchor="middle" fontSize="11" fill="#0B1F3A" fontWeight="600">
                  {p.code}
                </text>
              </g>
            </Link>
          );
        })}
      </svg>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-500" aria-label="Légende">
        {(Object.keys(FILL) as (keyof typeof FILL)[]).map((lvl) => (
          <li key={lvl} className="flex items-center gap-1">
            <span aria-hidden="true" style={{ color: FILL[lvl] }}>
              {SHAPE_LABEL[lvl]}
            </span>
            {LEVEL_LABEL[lvl]}
          </li>
        ))}
        <li className="ml-auto italic">Aperçu schématique — carte interactive en Phase 4</li>
      </ul>
    </div>
  );
}
