"use client";

/**
 * Performances (accueil) : les chiffres clés en grille « bento » sombre.
 *
 * Un chiffre phare (gagnant dans notre Top-3, face au hasard), trois mesures
 * secondaires, puis la comparaison au hasard, la courbe des 7 derniers jours et
 * la précision par discipline. Règles reprises de l'ancien panneau :
 *  - état servi = état FINAL ; compteurs et barres n'animent que si le bloc
 *    était encore sous la ligne de flottaison (cf. `useReveal`) ;
 *  - le repère « hasard » vient de l'API (`hasard_top3` / `hasard_top1`, calculés
 *    sur le champ réel de chaque course), jamais posé à la main.
 */

import { useEffect, useRef, useState } from "react";
import { EchantillonNotice } from "@/components/stats/EchantillonNotice";
import { useReveal } from "@/components/track-record/effets";

export type PerformancesData = {
  accuracy_top3: number | null;
  favori_place_rate: number | null;
  favori_win_rate: number | null;
  nb_courses: number | null;
  mesure_depuis: string | null;
  hasard_top3: number | null;
  hasard_top1: number | null;
  by_discipline: Array<{ discipline: string; nb_courses: number; accuracy_top3: number }>;
  by_day: Array<{ jour: string; accuracy_top3: number; nb_predictions: number }>;
};

const DISC: Record<string, string> = {
  plat: "Plat", "attelé": "Trot attelé", attele: "Trot attelé",
  "monté": "Trot monté", monte: "Trot monté", obstacle: "Obstacle", autre: "Autre",
};

const nf = (n: number, d = 0) => n.toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d });
const borne = (n: number) => Math.max(0, Math.min(100, n));

function dateLongue(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null
    : d.toLocaleDateString("fr-FR", { timeZone: "Europe/Paris", day: "numeric", month: "long", year: "numeric" });
}

/** Compte de 0 à `cible` à l'entrée dans l'écran — uniquement si le bloc était armé. */
function useCompteur(cible: number | null, hidden: boolean, duree = 1400) {
  const [v, setV] = useState(cible);
  const arme = useRef(false);
  useEffect(() => {
    if (cible == null) { setV(null); return; }
    if (hidden) { arme.current = true; setV(0); return; }
    if (!arme.current) { setV(cible); return; }
    let raf = 0;
    const t0 = performance.now();
    const pas = (t: number) => {
      const p = Math.min(1, Math.max(0, (t - t0) / duree));
      setV(cible * (1 - Math.pow(1 - p, 3)));
      if (p < 1) raf = requestAnimationFrame(pas);
    };
    raf = requestAnimationFrame(pas);
    return () => cancelAnimationFrame(raf);
  }, [cible, hidden, duree]);
  return v;
}

const CARTE = "relative overflow-hidden rounded-[28px] bg-white/[0.035] p-6 ring-1 ring-inset ring-white/[0.08] backdrop-blur-sm sm:p-7";

function Chiffre({ valeur, decimales, suffixe, hidden, className }: {
  valeur: number | null; decimales: number; suffixe?: string; hidden: boolean; className: string;
}) {
  const v = useCompteur(valeur, hidden);
  return (
    <span className={`whitespace-nowrap font-display font-semibold tabular-nums tracking-[-0.04em] ${className}`}>
      {v == null ? "—" : nf(v, decimales)}
      {v != null && suffixe && <span className="ml-1 text-[0.45em] font-medium tracking-normal text-white/40">{suffixe}</span>}
    </span>
  );
}

/** Deux barres fines : nous (or) face au tirage au sort (gris). */
function Face({ titre, nous, hasard, hidden }: { titre: string; nous: number; hasard: number; hidden: boolean }) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-[15px] text-white/80">{titre}</p>
        <p className="font-display text-lg font-semibold tabular-nums text-amber-300">×{nf(nous / hasard, 1)}</p>
      </div>
      <div className="mt-3 space-y-2">
        {[
          { l: "BlackTurf", v: nous, c: "bg-gradient-to-r from-amber-500 to-amber-300", t: "text-white" },
          { l: "Hasard", v: hasard, c: "bg-white/25", t: "text-white/45" },
        ].map((b) => (
          <div key={b.l} className="flex items-center gap-3">
            <span className={`w-[72px] shrink-0 text-xs ${b.t}`}>{b.l}</span>
            <div className="relative h-2 flex-1 overflow-hidden rounded-full bg-white/[0.06]">
              <div className={`tr-bar absolute inset-y-0 left-0 rounded-full ${b.c}`} style={{ width: `${hidden ? 0 : borne(b.v)}%` }} />
            </div>
            <span className={`w-12 shrink-0 text-right text-xs tabular-nums ${b.t}`}>{nf(b.v, 1)} %</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Courbe lissée des 7 derniers jours, sans librairie. */
function Courbe({ jours }: { jours: PerformancesData["by_day"] }) {
  const vals = jours.map((d) => d.accuracy_top3);
  const min = Math.min(...vals) - 6, max = Math.max(...vals) + 6;
  const W = 300, H = 110;
  const pts = vals.map((v, i) => [jours.length > 1 ? (i / (jours.length - 1)) * W : W / 2, H - ((v - min) / (max - min)) * H] as const);
  const ligne = pts.map(([x, y], i) => {
    if (i === 0) return `M${x},${y}`;
    const [px, py] = pts[i - 1];
    const cx = (px + x) / 2;
    return `C${cx},${py} ${cx},${y} ${x},${y}`;
  }).join(" ");
  const moy = vals.reduce((s, v) => s + v, 0) / vals.length;
  const yMoy = H - ((moy - min) / (max - min)) * H;
  return (
    <div>
      <svg viewBox={`-6 -14 ${W + 12} ${H + 22}`} className="h-auto w-full overflow-visible" role="img"
        aria-label={`Gagnant dans le Top-3, jour par jour : ${jours.map((d) => `${d.jour} ${nf(d.accuracy_top3, 0)} %`).join(", ")}`}>
        <defs>
          <linearGradient id="bento-aire" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#FBBF24" stopOpacity="0.28" />
            <stop offset="100%" stopColor="#FBBF24" stopOpacity="0" />
          </linearGradient>
        </defs>
        <line x1="0" x2={W} y1={yMoy} y2={yMoy} stroke="rgba(255,255,255,.18)" strokeDasharray="3 4" />
        <path d={`${ligne} L${W},${H + 8} L0,${H + 8} Z`} fill="url(#bento-aire)" />
        <path d={ligne} fill="none" stroke="#FCD34D" strokeWidth="2.2" strokeLinecap="round" />
        {pts.map(([x, y], i) => (
          <g key={jours[i].jour}>
            <circle cx={x} cy={y} r="3.2" fill="#0B0A08" stroke="#FCD34D" strokeWidth="1.8" />
            <text x={x} y={y - 9} textAnchor="middle" className="fill-white/70 text-[9px] font-semibold tabular-nums">{nf(vals[i], 0)}</text>
          </g>
        ))}
      </svg>
      <div className="mt-2 flex justify-between text-[10px] text-white/35">
        {jours.map((d) => <span key={d.jour}>{d.jour}</span>)}
      </div>
    </div>
  );
}

export function PerformancesBento({ m }: { m: PerformancesData }) {
  const { ref, hidden } = useReveal<HTMLDivElement>(0.2);
  const depuis = dateLongue(m.mesure_depuis);
  const facteur = m.accuracy_top3 != null && m.hasard_top3 ? m.accuracy_top3 / m.hasard_top3 : null;

  return (
    <div ref={ref}>
      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-3">
        {/* Chiffre phare */}
        <div className={`${CARTE} col-span-2 lg:row-span-2 flex flex-col justify-between`}>
          <span aria-hidden className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-amber-500/20 blur-3xl" />
          <div className="relative">
            <p className="inline-flex items-center gap-2 text-xs font-medium text-white/50">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60 motion-reduce:hidden" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
              </span>
              Mesuré en continu{depuis ? ` depuis le ${depuis}` : ""}
            </p>
            <p className="mt-8 leading-none">
              <Chiffre valeur={m.accuracy_top3} decimales={1} suffixe="%" hidden={hidden} className="text-[4.5rem] text-white sm:text-[7rem]" />
            </p>
            <p className="mt-4 max-w-md text-lg leading-snug text-white/70">
              des courses : le gagnant était dans le <b className="font-semibold text-white">Top 3 de l&apos;algorithme</b>, annoncé avant le départ.
            </p>
          </div>
          {m.accuracy_top3 != null && m.hasard_top3 != null && (
            <div className="relative mt-10 flex flex-wrap items-end gap-x-8 gap-y-3 border-t border-white/10 pt-6">
              <div>
                <p className="font-display text-3xl font-semibold tabular-nums text-amber-300">×{nf(facteur!, 1)}</p>
                <p className="mt-1 text-xs text-white/45">plus souvent qu&apos;un tirage au sort</p>
              </div>
              <div>
                <p className="font-display text-3xl font-semibold tabular-nums text-white/35">{nf(m.hasard_top3, 1)} %</p>
                <p className="mt-1 text-xs text-white/45">trois chevaux tirés au sort</p>
              </div>
            </div>
          )}
        </div>

        {/* Mesures secondaires */}
        {[
          { l: "Notre favori placé", s: "Le n°1 de l'algo finit dans les 3 premiers.", v: m.favori_place_rate, d: 1, x: "%" },
          { l: "Notre favori gagnant", s: m.hasard_top1 != null ? `Hasard : ${nf(m.hasard_top1, 1)} %` : "Le n°1 de l'algo remporte la course.", v: m.favori_win_rate, d: 1, x: "%" },
        ].map((c) => (
          <div key={c.l} className={`${CARTE} !p-5 sm:!p-7`}>
            <p className="text-[13px] text-white/55 sm:text-sm">{c.l}</p>
            <p className="mt-3 leading-none">
              <Chiffre valeur={c.v} decimales={c.d} suffixe={c.x} hidden={hidden} className="text-[2.25rem] text-white sm:text-[3rem]" />
            </p>
            <p className="mt-3 text-xs text-white/40">{c.s}</p>
          </div>
        ))}

        {/* Face au hasard */}
        {m.accuracy_top3 != null && m.hasard_top3 != null && (
          <div className={`${CARTE} col-span-2 space-y-6 lg:col-span-1`}>
            <p className="text-sm text-white/55">Face au hasard</p>
            <Face titre="Gagnant dans le Top 3" nous={m.accuracy_top3} hasard={m.hasard_top3} hidden={hidden} />
            {m.favori_win_rate != null && m.hasard_top1 != null && (
              <Face titre="Favori gagnant" nous={m.favori_win_rate} hasard={m.hasard_top1} hidden={hidden} />
            )}
          </div>
        )}

        {/* 7 derniers jours */}
        {m.by_day.length > 1 && (
          <div className={`${CARTE} col-span-2 lg:col-span-1`}>
            <div className="flex items-baseline justify-between gap-3">
              <p className="text-sm text-white/55">Top 3 · 7 derniers jours</p>
              <p className="text-xs tabular-nums text-white/40">
                moy. {nf(m.by_day.reduce((s, d) => s + d.accuracy_top3, 0) / m.by_day.length, 0)} %
              </p>
            </div>
            <div className="mt-5"><Courbe jours={m.by_day} /></div>
          </div>
        )}

        {/* Par discipline + volume */}
        <div className={`${CARTE} col-span-2 lg:col-span-1`}>
          <div className="flex items-baseline justify-between gap-3">
            <p className="text-sm text-white/55">Par discipline</p>
            {m.nb_courses != null && (
              <p className="text-xs text-white/40"><span className="font-semibold text-white/80 tabular-nums">{nf(m.nb_courses)}</span> courses vérifiées</p>
            )}
          </div>
          <ul className="mt-5 space-y-3.5">
            {m.by_discipline.map((d) => (
              <li key={d.discipline}>
                <div className="flex items-baseline justify-between text-xs">
                  <span className="text-white/75">{DISC[d.discipline] ?? d.discipline}</span>
                  <span className="font-semibold tabular-nums text-white">{nf(d.accuracy_top3, 1)} %</span>
                </div>
                <div className="relative mt-1.5 h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
                  <div className="tr-bar absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-amber-500 to-amber-300" style={{ width: `${hidden ? 0 : borne(d.accuracy_top3)}%` }} />
                  {m.hasard_top3 != null && <span className="absolute inset-y-0 w-px bg-white/50" style={{ left: `${borne(m.hasard_top3)}%` }} />}
                </div>
              </li>
            ))}
          </ul>
          {m.hasard_top3 != null && <p className="mt-4 text-[11px] text-white/35">Trait blanc : hasard ({nf(m.hasard_top3, 0)} %).</p>}
        </div>
      </div>

      <EchantillonNotice nbCourses={m.nb_courses} mesureDepuis={m.mesure_depuis} variante="sombre" />
    </div>
  );
}
