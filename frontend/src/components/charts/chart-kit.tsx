"use client";

/**
 * Kit graphique partagé BlackTurf — thème light, look pro et cohérent.
 * Palette, presets d'axes/grille et tooltip carte réutilisables (recharts).
 */

// Palette de séries — cohérente sur tout le site
export const CHART_PALETTE = [
  "#F59E0B", // amber (brand)
  "#3B82F6", // blue
  "#10B981", // emerald
  "#8B5CF6", // violet
  "#EC4899", // pink
  "#06B6D4", // cyan
  "#FB923C", // orange
  "#84CC16", // lime
];

export const BRAND_GOLD = "#F59E0B";
export const POSITIVE = "#059669";
export const NEGATIVE = "#EF4444";

// Axes (light)
export const axisTick = { fontSize: 11, fill: "#9CA3AF", fontWeight: 500 } as const;
export const axisLine = false as const;
export const tickLine = false as const;

// Grille horizontale douce
export const GRID = {
  strokeDasharray: "3 3",
  stroke: "#EEF1F6",
  vertical: false as const,
} as const;

type TooltipEntry = {
  name?: string;
  value?: number;
  color?: string;
  dataKey?: string | number;
};

/**
 * Tooltip carte blanche arrondie avec ombre douce.
 * Usage : <Tooltip content={<ChartTooltip valueFormatter={...} />} />
 */
export function ChartTooltip({
  active,
  payload,
  label,
  valueFormatter,
  labelFormatter,
  labelMap,
  hideLabel,
}: {
  active?: boolean;
  payload?: TooltipEntry[];
  label?: string | number;
  valueFormatter?: (v: number, name: string) => string;
  labelFormatter?: (l: string | number) => string;
  labelMap?: Record<string, string>;
  hideLabel?: boolean;
}) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="rounded-xl border border-gray-100 bg-white/95 px-3 py-2 shadow-lg shadow-gray-300/40 backdrop-blur-sm">
      {!hideLabel && label !== undefined && label !== "" && (
        <p className="mb-1 text-[11px] font-semibold text-gray-400">
          {labelFormatter ? labelFormatter(label) : label}
        </p>
      )}
      <div className="space-y-1">
        {payload.map((e, i) => {
          const key = String(e.dataKey ?? e.name ?? i);
          const name = labelMap?.[key] ?? e.name ?? "";
          const val = typeof e.value === "number" ? e.value : Number(e.value ?? 0);
          return (
            <div key={i} className="flex items-center gap-2 text-xs">
              <span
                className="h-2.5 w-2.5 flex-shrink-0 rounded-full"
                style={{ background: e.color }}
              />
              {name && <span className="text-gray-500">{name}</span>}
              <span className="ml-auto pl-3 font-bold tabular-nums text-gray-900">
                {valueFormatter ? valueFormatter(val, e.name ?? "") : val}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
