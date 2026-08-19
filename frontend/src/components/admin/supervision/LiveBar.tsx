"use client";

/**
 * Bandeau LIVE — ce qui bouge maintenant.
 *
 * Rafraîchi toutes les 15 s. L'âge affiché ne vient pas d'un compteur local :
 * chaque valeur porte l'horodatage renvoyé par le serveur, donc un bandeau qui
 * cesserait d'être alimenté VIEILLIT à l'écran au lieu de mentir.
 */

import { Activity, Flag, Radio, Timer, Wallet, Wifi } from "lucide-react";
import { signedEur, num, tone } from "./kit";
import type { PulsePayload } from "./types";

function age(min: number | null | undefined): string {
  if (min == null || !isFinite(min)) return "—";
  if (min < 1) return "à l'instant";
  if (min < 60) return `il y a ${Math.round(min)} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `il y a ${h} h`;
  return `il y a ${Math.floor(h / 24)} j`;
}

/** Vert < 30 min, ambre < 3 h, rouge au-delà : la fraîcheur est un signal. */
function freshCls(min: number | null | undefined): string {
  if (min == null) return "text-gray-400";
  if (min < 30) return "text-emerald-600";
  if (min < 180) return "text-amber-600";
  return "text-red-600";
}

function Cell({
  icon, label, value, sub, valueClass = "text-gray-900",
}: {
  icon: React.ReactNode; label: string; value: React.ReactNode;
  sub?: React.ReactNode; valueClass?: string;
}) {
  return (
    <div className="flex min-w-0 items-center gap-2.5 px-3 py-2.5">
      <span className="shrink-0 text-gray-300">{icon}</span>
      <div className="min-w-0">
        <div className="truncate text-[10px] font-semibold uppercase tracking-wide text-gray-400">
          {label}
        </div>
        <div className={`truncate text-sm font-bold tabular-nums ${valueClass}`}>{value}</div>
        {sub && <div className="truncate text-[10px] text-gray-400">{sub}</div>}
      </div>
    </div>
  );
}

export default function LiveBar({
  pulse, live, secondsSince,
}: {
  pulse?: PulsePayload;
  live: boolean;
  secondsSince: number;
}) {
  const c = pulse?.courses_du_jour;
  const k = pulse?.conseils_du_jour;
  const a = pulse?.apprentissage;
  const f = pulse?.fraicheur;
  const sourcesEnRetard = (f?.sources ?? []).filter((s) => (s.age_min ?? 0) > 180).length;

  return (
    <div className="overflow-hidden rounded-xl border border-gray-100 bg-white shadow-sm">
      <div className="flex items-center gap-2 border-b border-gray-50 bg-gray-50/60 px-3 py-1.5">
        <span className="relative flex h-2 w-2">
          {live && (
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
          )}
          <span
            className={`relative inline-flex h-2 w-2 rounded-full ${live ? "bg-emerald-500" : "bg-gray-400"}`}
          />
        </span>
        <span className="text-[11px] font-semibold text-gray-600">
          {live ? "En direct" : "Rafraîchissement en pause"}
        </span>
        <span className="text-[11px] text-gray-400">
          · données du serveur, actualisées {secondsSince < 5 ? "à l'instant" : `il y a ${secondsSince} s`}
        </span>
      </div>

      <div className="grid grid-cols-2 divide-x divide-y divide-gray-50 sm:grid-cols-3 lg:grid-cols-6 lg:divide-y-0">
        <Cell
          icon={<Flag className="h-4 w-4" />}
          label="Courses du jour"
          value={`${num(c?.terminees)} / ${num(c?.total)}`}
          sub={`${num(c?.a_venir)} à venir`}
        />
        <Cell
          icon={<Radio className="h-4 w-4" />}
          label="Conseils émis"
          value={num(k?.emis)}
          sub={`${num(k?.regles)} réglés`}
        />
        <Cell
          icon={<Wallet className="h-4 w-4" />}
          label="Net du jour"
          value={signedEur(k?.net, 2)}
          valueClass={tone(k?.net)}
          sub={`sur ${num(k?.mise)} € engagés`}
        />
        <Cell
          icon={<Timer className="h-4 w-4" />}
          label="Dernier règlement"
          value={age(k?.age_dernier_reglement_min)}
          valueClass={freshCls(k?.age_dernier_reglement_min)}
          sub="rapport PMU encaissé"
        />
        <Cell
          icon={<Activity className="h-4 w-4" />}
          label="Apprentissage 24 h"
          value={`${num(a?.courses_apprises_24h)} courses`}
          sub={`dernière analyse ${age(a?.age_derniere_analyse_min)}`}
        />
        <Cell
          icon={<Wifi className="h-4 w-4" />}
          label="Fraîcheur cotes"
          value={age(f?.cotes_age_min)}
          valueClass={freshCls(f?.cotes_age_min)}
          sub={
            sourcesEnRetard > 0
              ? `${sourcesEnRetard} source${sourcesEnRetard > 1 ? "s" : ""} > 3 h`
              : "toutes sources récentes"
          }
        />
      </div>
    </div>
  );
}
