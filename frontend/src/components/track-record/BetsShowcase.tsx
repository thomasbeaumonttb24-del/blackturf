"use client";

/**
 * Paris gagnés du palmarès : tickets (derniers paris, records) et podium 3D.
 *
 * Remplace l'ancien tableau à huit colonnes. Chaque pari devient un ticket :
 * talon à gauche avec le jour ET l'heure de départ de la course, corps avec le
 * pari joué, et le gain net en gros à droite. Le lien vers la course reste sur
 * chaque ligne : c'est lui qui fait d'un palmarès une preuve.
 */

import Link from "next/link";
import { ArrowUpRight, LockKeyhole, Clock3 } from "lucide-react";
import { cn } from "@/lib/utils";
import { Reveal, Tilt } from "./effets";

export interface WinningBet {
  profil: string;
  course_id: string;
  code: string | null;
  hippodrome: string;
  date: string | null;
  type_pari: string;
  chevaux: number[];
  mise: number;
  gain: number;
  benefice: number;
  rapport: number | null;
  // Rapport ANNONCÉ par le plan figé avant le départ. Différent du rapport réel :
  // la tranche d'un profil (prudent ×1,8-5, modéré ×4-15, risqué ≥×10) est un
  // engagement pris sur l'estimé, alors que le rapport parimutuel n'est connu
  // qu'après la clôture des paris. Afficher les deux évite un palmarès qui semble
  // contredire la tranche annoncée.
  rapport_vise?: number | null;
  fige_avant_course?: boolean;   // prono figé avant le départ (preuve d'intégrité)
  fige_le?: string | null;       // horodatage du gel pré-course
  regle_le?: string | null;      // horodatage du règlement post-arrivée
}

export const PROFIL_LABELS: Record<string, { label: string; cls: string; dark: string }> = {
  conservateur: { label: "Prudent", cls: "bg-emerald-50 text-emerald-700 ring-emerald-200", dark: "bg-emerald-400/10 text-emerald-300 ring-emerald-400/30" },
  equilibre: { label: "Modéré", cls: "bg-blue-50 text-blue-700 ring-blue-200", dark: "bg-sky-400/10 text-sky-300 ring-sky-400/30" },
  agressif: { label: "Risqué", cls: "bg-rose-50 text-rose-700 ring-rose-200", dark: "bg-rose-400/10 text-rose-300 ring-rose-400/30" },
};

const profilDe = (p: string) =>
  PROFIL_LABELS[p] ?? { label: p, cls: "bg-stone-100 text-stone-700 ring-stone-200", dark: "bg-white/10 text-white/80 ring-white/20" };

/** Montant en euros, séparateur de milliers et espace insécable avant « € ». */
export const eur = (n: number, d = 2) =>
  `${n.toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d })} €`;

const rapportFr = (n: number) => n.toLocaleString("fr-FR", { maximumFractionDigits: 1, minimumFractionDigits: 1 });

/**
 * Jour et heure de DÉPART de la course, toujours en heure de Paris : sans
 * `timeZone`, le rendu serveur (UTC) décalerait l'heure de deux heures.
 */
export function quandCourse(iso: string | null) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const tz = { timeZone: "Europe/Paris" } as const;
  return {
    jour: d.toLocaleDateString("fr-FR", { ...tz, weekday: "short", day: "numeric", month: "short" }),
    jourCourt: d.toLocaleDateString("fr-FR", { ...tz, day: "2-digit", month: "2-digit" }),
    heure: d.toLocaleTimeString("fr-FR", { ...tz, hour: "2-digit", minute: "2-digit" }).replace(":", "h"),
    complet: d.toLocaleString("fr-FR", { ...tz, dateStyle: "full", timeStyle: "short" }),
  };
}

/** Vrai si le rapport visé mérite d'être affiché à côté du rapport payé.
 *  On masque l'écart négligeable (< 0,1×) : répéter deux fois le même chiffre
 *  n'apprend rien et alourdit une ligne déjà dense. */
export function ecartVise(b: WinningBet): boolean {
  return (
    typeof b.rapport_vise === "number" && b.rapport_vise > 0 &&
    (b.rapport === null || Math.abs(b.rapport_vise - b.rapport) >= 0.1)
  );
}

/** Numéros des chevaux joués, en jetons ronds. */
function Jetons({ nums, dark }: { nums: number[]; dark?: boolean }) {
  return (
    <span className="flex flex-wrap items-center gap-1" aria-label={`Chevaux ${nums.join(", ")}`}>
      {nums.map((n, i) => (
        <span
          key={`${n}-${i}`}
          className={cn(
            "inline-flex h-7 min-w-7 items-center justify-center rounded-full px-1.5 text-xs font-black tabular-nums shadow-[inset_0_-2px_0_rgba(0,0,0,.18),0_3px_8px_-3px_rgba(0,0,0,.35)]",
            dark
              ? "bg-gradient-to-b from-amber-300 to-amber-500 text-slate-950"
              : "bg-gradient-to-b from-slate-800 to-slate-950 text-amber-300",
          )}
        >
          {n}
        </span>
      ))}
    </span>
  );
}

// ─── Ticket ───────────────────────────────────────────────────
export function BetTicket({ b, rank, dark = false }: { b: WinningBet; rank?: number; dark?: boolean }) {
  const q = quandCourse(b.date);
  const pm = profilDe(b.profil);
  return (
    <Tilt
      max={5}
      className={cn(
        "h-full rounded-2xl",
        dark
          ? "bg-white/[0.045] ring-1 ring-white/10 shadow-[0_24px_50px_-30px_rgba(0,0,0,.9)] backdrop-blur-sm hover:ring-amber-300/40"
          : "bg-white ring-1 ring-stone-200/80 shadow-[0_18px_40px_-28px_rgba(17,24,39,.45)] hover:shadow-[0_28px_60px_-30px_rgba(180,83,9,.55)] hover:ring-amber-300",
      )}
    >
      <article className="flex h-full overflow-hidden rounded-2xl">
        {/* Talon : jour + heure de départ */}
        <div
          className={cn(
            "tr-notch relative flex w-[78px] shrink-0 flex-col items-center justify-center gap-0.5 border-r-2 border-dashed px-1.5 py-4 text-center sm:w-[96px]",
            dark
              ? "border-white/15 bg-gradient-to-b from-amber-400/20 via-amber-500/10 to-transparent [--tr-notch-bg:#0b1020]"
              : "border-amber-200 bg-gradient-to-b from-amber-50 via-amber-50/70 to-white",
          )}
          style={{ overflow: "visible" }}
        >
          {rank != null && (
            <span className={cn("mb-1 font-display text-[11px] font-black tabular-nums", dark ? "text-amber-300" : "text-amber-700")}>
              #{rank}
            </span>
          )}
          <span className={cn("text-[10px] font-semibold uppercase leading-tight tracking-wide", dark ? "text-white/60" : "text-stone-500")}>
            {q ? q.jour : "Date"}
          </span>
          <span
            className={cn("font-display text-xl font-black leading-none tabular-nums sm:text-2xl", dark ? "text-white" : "text-slate-900")}
            title={q ? `Départ ${q.complet}` : undefined}
          >
            {q ? q.heure : "—"}
          </span>
          <span className={cn("mt-0.5 inline-flex items-center gap-0.5 text-[9px] font-medium uppercase tracking-wider", dark ? "text-amber-300/80" : "text-amber-700")}>
            <Clock3 className="h-2.5 w-2.5" aria-hidden="true" /> départ
          </span>
        </div>

        {/* Corps */}
        <div className="flex min-w-0 flex-1 flex-col justify-between gap-3 p-3.5 sm:p-4">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <Link
                href={`/courses/${b.course_id}`}
                className={cn(
                  "group/l inline-flex items-center gap-1 font-display text-[15px] font-bold underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500",
                  dark ? "text-white hover:text-amber-300" : "text-slate-900 hover:text-amber-800",
                )}
              >
                {b.code ?? "Course"}
                <ArrowUpRight className="h-3.5 w-3.5 transition-transform group-hover/l:-translate-y-0.5 group-hover/l:translate-x-0.5" aria-hidden="true" />
              </Link>
              <p className={cn("break-words text-xs", dark ? "text-white/60" : "text-stone-500")}>{b.hippodrome}</p>
            </div>
            <span className={cn("inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1", dark ? pm.dark : pm.cls)}>
              {pm.label}
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
            <span className={cn("text-xs font-semibold", dark ? "text-white/85" : "text-slate-700")}>{b.type_pari}</span>
            <Jetons nums={b.chevaux} dark={dark} />
          </div>

          <div className={cn("flex items-end justify-between gap-3 border-t pt-2.5", dark ? "border-white/10" : "border-stone-100")}>
            <div className={cn("text-[11px] leading-tight tabular-nums", dark ? "text-white/60" : "text-stone-500")}>
              <span className="block">
                Mise <strong className={cn("font-semibold", dark ? "text-white/90" : "text-slate-800")}>{eur(b.mise, 0)}</strong>
                {b.rapport ? <> · payé <strong className={cn("font-semibold", dark ? "text-amber-300" : "text-amber-800")}>×{rapportFr(b.rapport)}</strong></> : null}
              </span>
              {ecartVise(b) && <span className="block text-[10px]">visé ×{rapportFr(b.rapport_vise!)}</span>}
              {b.fige_avant_course && (
                <span className={cn("mt-1 inline-flex items-center gap-1 text-[10px] font-medium", dark ? "text-emerald-300" : "text-emerald-700")}>
                  <LockKeyhole className="h-3 w-3" aria-hidden="true" /> Figé avant le départ
                </span>
              )}
            </div>
            <div className="text-right">
              <span className={cn(
                "block whitespace-nowrap font-display text-xl font-black leading-none tabular-nums sm:text-2xl",
                dark ? "bg-gradient-to-b from-emerald-200 to-emerald-400 bg-clip-text text-transparent" : "text-emerald-600",
              )}>
                +{eur(b.benefice)}
              </span>
              <span className={cn("mt-1 block text-[10px] uppercase tracking-wider", dark ? "text-white/50" : "text-stone-500")}>gain net</span>
            </div>
          </div>
        </div>
      </article>
    </Tilt>
  );
}

export function TicketsGrid({ bets, rankOffset, dark }: { bets: WinningBet[]; rankOffset?: number; dark?: boolean }) {
  return (
    <ul className="grid gap-3 sm:gap-4 lg:grid-cols-2" aria-label="Paris gagnants réglés aux rapports PMU officiels">
      {bets.map((b, i) => (
        <Reveal as="li" key={`${b.course_id}-${b.profil}-${b.type_pari}-${i}`} delay={(i % 6) * 60}>
          <BetTicket b={b} dark={dark} rank={rankOffset != null ? rankOffset + i + 1 : undefined} />
        </Reveal>
      ))}
    </ul>
  );
}

// ─── Podium des trois plus gros gains ─────────────────────────
const MEDAILLES = [
  { nom: "Or", disque: "from-amber-200 via-amber-400 to-amber-700", texte: "text-amber-950", halo: "bg-amber-400/40", socle: "from-amber-300/40 to-amber-600/10", hauteur: "lg:h-28" },
  { nom: "Argent", disque: "from-slate-100 via-slate-300 to-slate-500", texte: "text-slate-900", halo: "bg-slate-300/30", socle: "from-slate-200/30 to-slate-500/10", hauteur: "lg:h-20" },
  { nom: "Bronze", disque: "from-orange-200 via-orange-400 to-orange-800", texte: "text-orange-950", halo: "bg-orange-400/30", socle: "from-orange-300/30 to-orange-700/10", hauteur: "lg:h-12" },
];

function CartePodium({ b, place }: { b: WinningBet; place: 0 | 1 | 2 }) {
  const m = MEDAILLES[place];
  const q = quandCourse(b.date);
  const pm = profilDe(b.profil);
  return (
    <div className="flex flex-col">
      <Tilt
        max={9}
        className={cn(
          "flex-1 rounded-3xl bg-gradient-to-b from-white/[0.09] to-white/[0.02] p-5 ring-1 backdrop-blur-md sm:p-6",
          place === 0 ? "ring-amber-300/50 shadow-[0_40px_80px_-40px_rgba(245,158,11,.75)]" : "ring-white/15 shadow-[0_30px_60px_-40px_rgba(0,0,0,.9)]",
        )}
      >
        <span className="tr-shine" aria-hidden="true" />
        <div className="flex items-start justify-between gap-3">
          <div className="relative tr-pop">
            <span className={cn("tr-glow absolute -inset-3 rounded-full blur-xl", m.halo)} aria-hidden="true" />
            <span
              className={cn(
                "tr-medal relative flex h-14 w-14 items-center justify-center rounded-full bg-gradient-to-br font-display text-xl font-black shadow-[inset_0_2px_0_rgba(255,255,255,.6),inset_0_-4px_0_rgba(0,0,0,.25),0_12px_24px_-8px_rgba(0,0,0,.6)] ring-4 ring-white/10",
                m.disque, m.texte,
              )}
              style={{ animationDelay: `${place * 0.6}s` }}
              aria-label={`${place + 1}${place === 0 ? "er" : "e"} plus gros gain`}
            >
              {place + 1}
            </span>
          </div>
          <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1", pm.dark)}>{pm.label}</span>
        </div>

        <p className="mt-5 text-[11px] font-semibold uppercase tracking-[0.18em] text-white/50">Gain net</p>
        <p className="tr-pop mt-1 whitespace-nowrap font-display text-[2.1rem] font-black leading-none tabular-nums sm:text-[2.5rem]">
          <span className="bg-gradient-to-b from-amber-100 via-amber-300 to-amber-500 bg-clip-text text-transparent">+{eur(b.benefice)}</span>
        </p>
        {b.rapport && (
          <p className="mt-2 text-sm text-white/70">
            Rapport payé <strong className="font-bold text-amber-300">×{rapportFr(b.rapport)}</strong>
            <span className="text-white/40"> · mise {eur(b.mise, 0)}</span>
          </p>
        )}

        <div className="mt-5 flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold text-white/85">{b.type_pari}</span>
          <Jetons nums={b.chevaux} dark />
        </div>

        <div className="mt-5 flex items-end justify-between gap-3 border-t border-white/10 pt-4">
          <div className="min-w-0">
            <Link
              href={`/courses/${b.course_id}`}
              className="inline-flex items-center gap-1 font-display font-bold text-white underline-offset-4 hover:text-amber-300 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
            >
              {b.code ?? "Course"} <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />
            </Link>
            <p className="break-words text-xs text-white/55">{b.hippodrome}</p>
          </div>
          <div className="shrink-0 text-right">
            <p className="font-display text-lg font-black leading-none tabular-nums text-white">{q ? q.heure : "—"}</p>
            <p className="mt-1 text-[10px] uppercase tracking-wider text-white/50">{q ? q.jour : ""}</p>
          </div>
        </div>
        {b.fige_avant_course && (
          <p className="mt-3 inline-flex items-center gap-1 text-[10px] font-medium text-emerald-300">
            <LockKeyhole className="h-3 w-3" aria-hidden="true" /> Figé avant le départ · réglé au rapport PMU
          </p>
        )}
      </Tilt>
      {/* Marche du podium, en relief (bureau uniquement) */}
      <div className={cn("relative mx-4 hidden rounded-b-2xl bg-gradient-to-b lg:block", m.socle, m.hauteur)} aria-hidden="true">
        <span className="absolute inset-x-0 top-0 h-px bg-white/25" />
        <span className="absolute inset-0 flex items-center justify-center font-display text-4xl font-black text-white/15">{place + 1}</span>
      </div>
    </div>
  );
}

export function Podium({ bets }: { bets: WinningBet[] }) {
  const top = bets.slice(0, 3);
  // Bureau : 2e – 1er – 3e, comme un vrai podium. Mobile : 1er, 2e, 3e empilés.
  const ordreBureau = ["lg:order-2", "lg:order-1", "lg:order-3"];
  return (
    <ol className="grid items-end gap-4 lg:grid-cols-3 lg:gap-5" aria-label="Les trois plus gros gains">
      {top.map((b, i) => (
        <Reveal as="li" key={`${b.course_id}-${i}`} delay={i * 140} className={ordreBureau[i]}>
          <CartePodium b={b} place={i as 0 | 1 | 2} />
        </Reveal>
      ))}
    </ol>
  );
}
