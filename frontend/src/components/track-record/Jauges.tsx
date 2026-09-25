"use client";

/**
 * Jauges du palmarès : « nous contre le hasard » en anneaux concentriques, et
 * le score de Brier placé sur son échelle.
 *
 * Même principe que les anciennes barres : les deux valeurs sur la MÊME
 * échelle 0-100, parce que c'est l'écart avec le hasard qui informe, pas le
 * pourcentage seul. Les anneaux se remplissent à l'entrée dans l'écran ; sans
 * script, ils s'affichent directement pleins à leur vraie valeur.
 */

import { TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";
import { Tilt, useReveal } from "./effets";

const nf = (n: number, d = 0) =>
  n.toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d });

function Anneau({ r, largeur, pct, trait, fond, masque, id }: {
  r: number; largeur: number; pct: number; trait: string; fond: string; masque: boolean; id?: string;
}) {
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(100, pct));
  return (
    <>
      <circle cx="100" cy="100" r={r} fill="none" stroke={fond} strokeWidth={largeur} />
      <circle
        id={id}
        cx="100" cy="100" r={r} fill="none"
        stroke={trait} strokeWidth={largeur} strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={masque ? c : c * (1 - v / 100)}
        className="tr-ring"
        transform="rotate(-90 100 100)"
      />
    </>
  );
}

export function JaugeHasard({ label, aide, nous, hasard, facteur, teinte = "or" }: {
  label: string;
  aide: string;
  nous: number;
  hasard: number | null;
  facteur: number | null;
  teinte?: "or" | "emeraude";
}) {
  const { ref, hidden } = useReveal<HTMLDivElement>(0.35);
  const grad = `jauge-${teinte}`;
  const couleurs = teinte === "or"
    ? { a: "#FCD34D", b: "#D97706", texte: "text-amber-700", badge: "bg-amber-50 text-amber-900 ring-amber-200" }
    : { a: "#6EE7B7", b: "#059669", texte: "text-emerald-700", badge: "bg-emerald-50 text-emerald-900 ring-emerald-200" };

  return (
    <Tilt max={6} className="h-full rounded-3xl bg-white p-6 ring-1 ring-stone-200/80 shadow-[0_30px_60px_-40px_rgba(17,24,39,.45)] sm:p-7">
      <div ref={ref} className="flex h-full flex-col items-center text-center">
        <div className="relative tr-pop w-full max-w-[220px]">
          <svg viewBox="0 0 200 200" className="h-auto w-full drop-shadow-[0_10px_18px_rgba(180,83,9,.18)]" role="img"
            aria-label={`${label} : ${nf(nous, 1)} %${hasard != null ? `, contre ${nf(hasard, 1)} % pour le hasard` : ""}`}>
            <defs>
              <linearGradient id={grad} x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stopColor={couleurs.a} />
                <stop offset="100%" stopColor={couleurs.b} />
              </linearGradient>
            </defs>
            <Anneau r={84} largeur={16} pct={nous} trait={`url(#${grad})`} fond="#F5F1E8" masque={hidden} />
            {hasard != null && <Anneau r={60} largeur={9} pct={hasard} trait="#94A3B8" fond="#F1F5F9" masque={hidden} />}
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className={cn("font-display text-[2.1rem] font-black leading-none tabular-nums", couleurs.texte)}>
              {nf(nous, 1)}<span className="text-lg"> %</span>
            </span>
            {hasard != null && (
              <span className="mt-1.5 text-[11px] font-medium text-slate-500 tabular-nums">hasard {nf(hasard, 1)} %</span>
            )}
          </div>
        </div>

        <h3 className="mt-5 font-display text-lg font-bold leading-snug text-slate-900">{label}</h3>
        <p className="mt-1.5 max-w-xs text-sm leading-6 text-muted-foreground">{aide}</p>

        <div className="mt-4 flex flex-wrap items-center justify-center gap-x-4 gap-y-2 text-[11px] text-slate-600">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: `linear-gradient(135deg, ${couleurs.a}, ${couleurs.b})` }} /> BlackTurf
          </span>
          {hasard != null && (
            <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-slate-400" /> Tirage au sort</span>
          )}
        </div>

        {facteur && (
          <div className="mt-auto pt-5">
            <p className={cn("inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-bold ring-1", couleurs.badge)}>
              <TrendingUp className="h-3.5 w-3.5" aria-hidden="true" /> {nf(facteur, 1)} fois mieux que le hasard
            </p>
          </div>
        )}
      </div>
    </Tilt>
  );
}

// ─── Échelle de Brier ─────────────────────────────────────────
// Un score de Brier nu n'évoque rien : on le place sur son échelle, entre la
// prédiction parfaite (0) et le pile ou face (0,33).
const BRIER_PILE_OU_FACE = 0.33;

export function JaugeBrier({ value }: { value: number }) {
  const { ref, hidden } = useReveal<HTMLDivElement>(0.4);
  const position = Math.max(0, Math.min(1, value / BRIER_PILE_OU_FACE)) * 100;
  return (
    <div ref={ref} className="relative overflow-hidden rounded-3xl bg-slate-950 p-6 text-white ring-1 ring-white/10 sm:p-7">
      <span className="tr-glow pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-emerald-400/20 blur-3xl" aria-hidden="true" />
      <div className="relative flex items-start justify-between gap-4">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-emerald-300">Calibration</p>
          <h3 className="mt-1 font-display text-lg font-bold">Des probabilités justes</h3>
        </div>
        <p className="font-display text-3xl font-black tabular-nums text-white">{nf(value, 3)}</p>
      </div>
      <p className="relative mt-2 text-sm leading-6 text-white/70">
        Score de Brier : l&apos;écart moyen entre la probabilité annoncée et ce qui s&apos;est réellement
        produit. Plus il est bas, mieux c&apos;est. Une probabilité juste vaut autant qu&apos;un bon
        classement — c&apos;est elle qui décide d&apos;une mise.
      </p>
      <div className="relative mt-8">
        <div className="h-3 rounded-full bg-gradient-to-r from-emerald-400 via-amber-300 to-rose-400 shadow-[inset_0_1px_2px_rgba(0,0,0,.4)]" />
        <span
          className="tr-slide absolute -top-7 flex -translate-x-1/2 flex-col items-center"
          style={{ left: `${hidden ? 100 : position}%` }}
          aria-hidden="true"
        >
          <span className="rounded-md bg-white px-1.5 py-0.5 text-[10px] font-bold tabular-nums text-slate-900 shadow">nous</span>
          <span className="mt-0.5 h-6 w-1 rounded-full bg-white shadow-[0_0_12px_rgba(255,255,255,.8)]" />
        </span>
      </div>
      <div className="relative mt-3 flex justify-between text-[10px] font-medium uppercase tracking-wider text-white/55">
        <span>0 · parfait</span>
        <span>0,33 · pile ou face</span>
      </div>
    </div>
  );
}
