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
  const couleur = nature === "fin_acces" ? "#b9bec6"
    : nature === "impaye" ? "#b42318"
    : urgent ? "#a8741a" : "#27456b";
  return (
    <div className="ml-auto w-full min-w-[9.5rem] max-w-[13rem] md:ml-0">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className={cn("font-semibold tabular-nums", urgent && nature !== "fin_acces" ? "text-[#8a5a10]" : "text-foreground")}>
          {j === 0 ? "Aujourd'hui" : `dans ${j} j`}
        </span>
        <span className="text-muted-foreground" title={formatDateTime(date)}>{dateCourte(date)}</span>
      </div>
      <div className="mt-1 h-1 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full"
          style={{ background: couleur, width: `${Math.max(4, 100 - Math.min(100, (j / horizon) * 100))}%` }}
        />
      </div>
    </div>
  );
}
