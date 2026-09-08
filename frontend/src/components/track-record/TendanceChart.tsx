"use client";

/**
 * Courbe de tendance 30 jours du palmarès — sortie de `page.tsx` pour être
 * chargée à la demande.
 *
 * Recharts pèse ~100 ko de JavaScript et n'était utilisé QUE par ce graphique,
 * situé très bas dans la page. Importé au niveau du module, il entrait dans le
 * lot d'hydratation initial : le fil principal restait occupé pendant que
 * l'image du hero, pourtant téléchargée en 1,4 s, attendait une frame libre pour
 * être peinte. Le LCP mesurait 4,1 s pour un « délai de rendu » de 2,7 s — la
 * page n'attendait pas ses octets, elle attendait son processeur.
 *
 * Chargé via `next/dynamic` avec `ssr: false` et un substitut de MÊME hauteur :
 * un graphique n'est pas du contenu indexable (les mêmes chiffres sont écrits en
 * toutes lettres dans la doublure SSR du palmarès), et la hauteur fixe garde le
 * CLS à zéro.
 */

import {
  Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { axisTick, GRID, ChartTooltip } from "@/components/charts/chart-kit";

export type PointTendance = { jour: string; top3: number | null; nb: number };

const nf = (n: number, d = 0) =>
  n.toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d });

export default function TendanceChart({ data, moyenne, hasard }: {
  data: PointTendance[]; moyenne: number; hasard: number | null;
}) {
  return (
    <div className="h-[260px] w-full sm:h-[300px]">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 12, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="tendanceFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#F59E0B" stopOpacity={0.35} />
              <stop offset="100%" stopColor="#F59E0B" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid {...GRID} />
          <XAxis
            dataKey="jour"
            tick={axisTick}
            axisLine={false}
            tickLine={false}
            interval="preserveStartEnd"
            minTickGap={28}
          />
          <YAxis
            domain={[0, 100]}
            ticks={[0, 25, 50, 75, 100]}
            tick={axisTick}
            axisLine={false}
            tickLine={false}
            width={52}
            tickFormatter={(v: number) => `${v}%`}
          />
          {hasard != null && (
            <ReferenceLine
              y={hasard}
              stroke="#94A3B8"
              strokeDasharray="4 4"
              label={{ value: `hasard ${nf(hasard, 0)} %`, position: "insideBottomRight", fontSize: 10, fill: "#94A3B8" }}
            />
          )}
          <ReferenceLine
            y={moyenne}
            stroke="#059669"
            strokeDasharray="5 3"
            label={{ value: `moyenne ${nf(moyenne, 1)} %`, position: "insideTopRight", fontSize: 10, fill: "#059669" }}
          />
          <Tooltip
            content={
              <ChartTooltip
                labelMap={{ top3: "Top-3" }}
                valueFormatter={(v) => `${nf(v, 1)} %`}
              />
            }
          />
          <Area
            type="monotone"
            dataKey="top3"
            name="Top-3"
            stroke="#B45309"
            strokeWidth={2}
            fill="url(#tendanceFill)"
            connectNulls={false}
            isAnimationActive={false}
            dot={false}
            activeDot={{ r: 4, strokeWidth: 2, stroke: "#fff" }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
