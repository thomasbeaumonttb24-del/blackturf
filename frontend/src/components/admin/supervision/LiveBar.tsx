"use client";

/**
 * Bandeau LIVE — ce qui bouge maintenant.
 *
 * Rafraîchi toutes les 15 s. L'âge affiché ne vient pas d'un compteur local :
 * chaque valeur porte l'horodatage renvoyé par le serveur, donc un bandeau qui
 * cesserait d'être alimenté VIEILLIT à l'écran au lieu de mentir.
 *
 * Refonte : six cellules séparées par des filets sur une grille à deux colonnes
 * donnaient, sur 390 px, six pavés de 11 px empilés sur trois rangées coupées
 * par des traits. Les cellules deviennent des tuiles à part entière, avec la
 * même échelle typographique que le reste de la console.
 */

import { Activity, Flag, Radio, Timer, Wallet, Wifi } from "lucide-react";
import { cn } from "@/lib/utils";
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
  if (min == null) return "text-muted-foreground";
  if (min < 30) return "text-emerald-700";
  if (min < 180) return "text-amber-700";
  return "text-red-700";
}

function Cellule({
  icon, label, value, sub, valueClass,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  valueClass?: string;
}) {
  return (
    <div className="min-w-0 rounded-xl border border-border bg-card p-3">
      <div className="flex items-center gap-1.5">
        <span className="shrink-0 text-muted-foreground/60">{icon}</span>
        <span className="text-[11px] font-semibold uppercase leading-tight tracking-[0.06em] text-muted-foreground">
          {label}
        </span>
      </div>
      <div className={cn("mt-1.5 truncate text-base font-semibold tabular-nums sm:text-lg", valueClass)}>
        {value}
      </div>
      {/* Pas de `truncate` : « dernière analyse il y a 22 min » se coupait en
          « dernière analyse il y … », c'est-à-dire en supprimant la mesure et
          en gardant l'étiquette. */}
      {sub && <div className="mt-0.5 text-xs leading-snug text-muted-foreground">{sub}</div>}
    </div>
  );
}

export default function LiveBar({
  pulse, live, secondsSince, derniereCourseIntegree,
}: {
  pulse?: PulsePayload;
  live: boolean;
  secondsSince: number;
  /** Règlement de course qui a déclenché le dernier recalcul des agrégats. */
  derniereCourseIntegree?: string | null;
}) {
  const c = pulse?.courses_du_jour;
  const k = pulse?.conseils_du_jour;
  const a = pulse?.apprentissage;
  const f = pulse?.fraicheur;
  const sourcesEnRetard = (f?.sources ?? []).filter((s) => (s.age_min ?? 0) > 180).length;

  return (
    <section
      aria-label="Activité en direct"
      className="overflow-hidden rounded-2xl border border-border bg-card shadow-sm"
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-border/60 bg-muted/30 px-4 py-2">
        <span className="relative flex h-2 w-2 shrink-0">
          {live && (
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
          )}
          <span className={cn("relative inline-flex h-2 w-2 rounded-full", live ? "bg-emerald-500" : "bg-muted-foreground/50")} />
        </span>
        <span className="text-xs font-semibold">
          {live ? "En direct" : "Rafraîchissement en pause"}
        </span>
        <span className="text-xs text-muted-foreground">
          · serveur interrogé {secondsSince < 5 ? "à l'instant" : `il y a ${secondsSince} s`}
        </span>
        {derniereCourseIntegree && (
          <span className="ml-auto rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700">
            recalculé après la course de{" "}
            {new Date(derniereCourseIntegree).toLocaleTimeString("fr-FR", {
              timeZone: "Europe/Paris", hour: "2-digit", minute: "2-digit",
            })}
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2.5 p-3 sm:grid-cols-3 sm:gap-3 sm:p-4 xl:grid-cols-6">
        <Cellule
          icon={<Flag className="h-3.5 w-3.5" />}
          label="Courses du jour"
          value={`${num(c?.terminees)} / ${num(c?.total)}`}
          sub={`${num(c?.a_venir)} à venir`}
        />
        <Cellule
          icon={<Radio className="h-3.5 w-3.5" />}
          label="Conseils émis"
          value={num(k?.emis)}
          sub={`${num(k?.regles)} réglés`}
        />
        <Cellule
          icon={<Wallet className="h-3.5 w-3.5" />}
          label="Net du jour"
          value={signedEur(k?.net, 2)}
          valueClass={tone(k?.net)}
          sub={`sur ${num(k?.mise)} € engagés`}
        />
        <Cellule
          icon={<Timer className="h-3.5 w-3.5" />}
          label="Dernier règlement"
          value={age(k?.age_dernier_reglement_min)}
          valueClass={freshCls(k?.age_dernier_reglement_min)}
          sub="rapport PMU encaissé"
        />
        <Cellule
          icon={<Activity className="h-3.5 w-3.5" />}
          label="Apprentissage 24 h"
          value={`${num(a?.courses_apprises_24h)} courses`}
          sub={`dernière analyse ${age(a?.age_derniere_analyse_min)}`}
        />
        <Cellule
          icon={<Wifi className="h-3.5 w-3.5" />}
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
    </section>
  );
}
