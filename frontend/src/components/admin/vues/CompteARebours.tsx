"use client";

/**
 * Compte à rebours jusqu'à une échéance (prélèvement, fin d'essai, fin d'accès).
 * Barre pleine le jour J, vide à 30 jours : on voit d'un coup d'œil qui arrive
 * au bout, sans lire les dates.
 */

import { cn, formatDateTime } from "@/lib/utils";

type Nature = "renouvellement" | "premier_prelevement" | "fin_acces" | "impaye";

const dateCourte = (iso: string) =>
  new Date(iso).toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short" });

export default function CompteARebours({
  date, jours, nature, horizon = 30,
}: {
  date: string | null;
  jours: number | null;
  nature?: Nature;
  horizon?: number;
}) {
  if (!date || jours == null) return <span className="text-muted-foreground">—</span>;
  const j = Math.max(0, Math.ceil(jours));
  const urgent = j <= 3;
  const couleur = nature === "fin_acces" ? "from-slate-500 to-slate-300"
    : nature === "impaye" ? "from-red-600 to-red-400"
    : urgent ? "from-amber-600 to-amber-300" : "from-emerald-600 to-emerald-300";
  return (
    <div className="ml-auto w-full min-w-[9.5rem] max-w-[13rem] md:ml-0">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className={cn("font-bold tabular-nums", urgent ? "text-amber-300" : "text-white")}>
          {j === 0 ? "Aujourd'hui" : `J−${j}`}
        </span>
        <span className="text-white/50" title={formatDateTime(date)}>{dateCourte(date)}</span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-black/40 shadow-[inset_0_1px_2px_rgba(0,0,0,0.8)]">
        <div
          className={cn("h-full rounded-full bg-gradient-to-r", couleur)}
          style={{ width: `${Math.max(5, 100 - Math.min(100, (j / horizon) * 100))}%` }}
        />
      </div>
    </div>
  );
}

