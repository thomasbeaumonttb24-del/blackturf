"use client";

/**
 * Performances (accueil) : les chiffres clés en visuels 3D sur fond clair.
 *
 * Anneau doré en relief pour le chiffre phare (gagnant dans notre Top-3, avec
 * l'anneau du hasard à l'intérieur), deux anneaux pour le favori, colonnes en
 * relief pour la comparaison au hasard et les 7 derniers jours, tubes brillants
 * par discipline. Règles reprises de l'ancien panneau :
 *  - état servi = état FINAL ; compteurs, anneaux et colonnes n'animent que si
 *    le bloc était encore sous la ligne de flottaison (cf. `useReveal`) ;
 *  - le repère « hasard » vient de l'API (`hasard_top3` / `hasard_top1`, calculés
 *    sur le champ réel de chaque course), jamais posé à la main.
 */

import { useEffect, useId, useRef, useState } from "react";
import { EchantillonNotice } from "@/components/stats/EchantillonNotice";
import { Tilt, useReveal } from "@/components/track-record/effets";
import { cn } from "@/lib/utils";

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
function useCompteur(cible: number | null, hidden: boolean, duree = 1500) {
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

/** Carte claire « verre » qui s'incline en 3D au survol. */
function Carte({ children, className, max = 5 }: { children: React.ReactNode; className?: string; max?: number }) {
  return (
    <Tilt
      max={max}
      className={cn(
        "h-full rounded-[28px] bg-white/80 p-6 ring-1 ring-white shadow-[0_1px_0_rgba(255,255,255,.9)_inset,0_30px_70px_-38px_rgba(120,72,10,.45),0_8px_22px_-14px_rgba(28,25,23,.18)] backdrop-blur-xl sm:p-7",
        className,
      )}
    >
      {children}
    </Tilt>
  );
}

/** Anneau doré en relief : piste creusée, arc brillant, reflet, disque bombé et ombre au sol. */
function Anneau3D({ pct, hasard, hidden, taille = 240, epaisseur = 22, children, teinte = "or" }: {
  pct: number; hasard?: number | null; hidden: boolean; taille?: number; epaisseur?: number;
  children: React.ReactNode; teinte?: "or" | "emeraude";
}) {
  const id = useId().replace(/:/g, "");
  const r = 100 - epaisseur / 2 - 6;
  const c = 2 * Math.PI * r;
  const rh = r - epaisseur / 2 - 9;
  const ch = 2 * Math.PI * rh;
  const arc = teinte === "or" ? ["#FDE68A", "#F59E0B", "#B45309"] : ["#A7F3D0", "#10B981", "#047857"];
  return (
    <div className="relative mx-auto" style={{ width: taille, maxWidth: "100%" }}>
      {/* Ombre portée au sol */}
      <div aria-hidden className="absolute inset-x-[14%] -bottom-3 h-6 rounded-[50%] bg-amber-900/25 blur-xl" />
      <svg viewBox="0 0 200 200" className="relative h-auto w-full -rotate-90" aria-hidden>
        <defs>
          <linearGradient id={`arc-${id}`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor={arc[0]} /><stop offset="45%" stopColor={arc[1]} /><stop offset="100%" stopColor={arc[2]} />
          </linearGradient>
          <linearGradient id={`piste-${id}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#E7DFD0" /><stop offset="100%" stopColor="#F7F3EA" />
          </linearGradient>
          <radialGradient id={`disque-${id}`} cx="0.42" cy="0.38" r="0.7">
            <stop offset="0%" stopColor="#FFFFFF" /><stop offset="70%" stopColor="#FBF7EF" /><stop offset="100%" stopColor="#EFE6D4" />
          </radialGradient>
          <filter id={`ombre-${id}`} x="-20%" y="-20%" width="140%" height="140%">
            <feDropShadow dx="2" dy="0" stdDeviation="2.4" floodColor="#92400E" floodOpacity="0.35" />
          </filter>
        </defs>
        {/* Piste creusée */}
        <circle cx="100" cy="100" r={r} fill="none" stroke={`url(#piste-${id})`} strokeWidth={epaisseur} />
        <circle cx="100" cy="100" r={r - epaisseur / 2 + 0.6} fill="none" stroke="rgba(120,90,40,.12)" strokeWidth="1.2" />
        {/* Disque central bombé */}
        <circle cx="100" cy="100" r={r - epaisseur / 2 - 2} fill={`url(#disque-${id})`} />
        {/* Arc principal */}
        <circle className="tr-ring" cx="100" cy="100" r={r} fill="none" stroke={`url(#arc-${id})`} strokeWidth={epaisseur}
          strokeLinecap="round" strokeDasharray={c} strokeDashoffset={hidden ? c : c * (1 - borne(pct) / 100)} filter={`url(#ombre-${id})`} />
        {/* Reflet sur l'arc */}
        <circle className="tr-ring" cx="100" cy="100" r={r + epaisseur / 4} fill="none" stroke="rgba(255,255,255,.55)" strokeWidth={epaisseur / 5}
          strokeLinecap="round" strokeDasharray={c} strokeDashoffset={hidden ? c : c * (1 - (borne(pct) / 100) * 0.92)} />
        {hasard != null && (
          <>
            <circle cx="100" cy="100" r={rh} fill="none" stroke="#EDE7DB" strokeWidth="5" />
            <circle className="tr-ring" cx="100" cy="100" r={rh} fill="none" stroke="#A8A29E" strokeWidth="5" strokeLinecap="round"
              strokeDasharray={ch} strokeDashoffset={hidden ? ch : ch * (1 - borne(hasard) / 100)} />
          </>
        )}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center">{children}</div>
    </div>
  );
}

/** Colonne en relief (face, dessus, flanc), qui monte à l'écran. */
function Prisme({ pct, ton, hidden, delai = 0, hauteur = "h-40", largeur = "w-9 sm:w-11", etiquette }: {
  pct: number; ton: "or" | "gris"; hidden: boolean; delai?: number; hauteur?: string; largeur?: string; etiquette?: string;
}) {
  const f = ton === "or"
    ? { face: "from-amber-300 via-amber-500 to-amber-700", dessus: "bg-amber-200", flanc: "from-amber-600 to-amber-800", txt: "text-stone-900" }
    : { face: "from-stone-200 via-stone-300 to-stone-400", dessus: "bg-stone-100", flanc: "from-stone-400 to-stone-500", txt: "text-stone-400" };
  return (
    <div className={cn("relative flex items-end", hauteur)}>
      <div className={cn("colonne3d relative", largeur)} style={{ height: `${hidden ? 0 : Math.max(3, borne(pct))}%`, transitionDelay: `${delai}ms` }}>
        <span className={cn("absolute inset-0 rounded-b-[3px] bg-gradient-to-b shadow-[inset_1px_0_0_rgba(255,255,255,.5)]", f.face)} />
        <span className={cn("absolute bottom-full left-0 h-2.5 w-full origin-bottom-left -skew-x-[45deg]", f.dessus)} />
        <span className={cn("absolute left-full top-0 h-full w-2.5 origin-top-left -skew-y-[45deg] bg-gradient-to-b", f.flanc)} />
        {etiquette && (
          <span className={cn("absolute bottom-full left-1/2 mb-4 -translate-x-1/2 whitespace-nowrap font-display text-[13px] font-semibold tabular-nums", f.txt)}>
            {etiquette}
          </span>
        )}
      </div>
    </div>
  );
}

/** Socle en perspective sous une rangée de colonnes. */
const Socle = () => (
  <div aria-hidden className="absolute inset-x-0 bottom-[-10px] h-10 rounded-[50%] bg-gradient-to-b from-stone-200/80 to-stone-50/0 [transform:perspective(420px)_rotateX(60deg)]" />
);

function Chiffre({ valeur, decimales, hidden, className, suffixe = "%" }: {
  valeur: number | null; decimales: number; hidden: boolean; className: string; suffixe?: string;
}) {
  const v = useCompteur(valeur, hidden);
  return (
    <span className={cn("whitespace-nowrap font-display font-semibold tabular-nums tracking-[-0.04em] text-stone-950", className)}>
      {v == null ? "—" : nf(v, decimales)}
      {v != null && suffixe && <span className="ml-0.5 text-[0.45em] font-medium tracking-normal text-stone-400">{suffixe}</span>}
    </span>
  );
}

export function PerformancesBento({ m }: { m: PerformancesData }) {
  const { ref, hidden } = useReveal<HTMLDivElement>(0.15);
  const depuis = dateLongue(m.mesure_depuis);
  const facteur = m.accuracy_top3 != null && m.hasard_top3 ? m.accuracy_top3 / m.hasard_top3 : null;
  const moy = m.by_day.length ? m.by_day.reduce((s, d) => s + d.accuracy_top3, 0) / m.by_day.length : null;
  // Les colonnes des 7 jours se lisent mieux sur une échelle resserrée (40-80 %).
  const echelle = (v: number) => ((v - 40) / 40) * 100;

  return (
    <div ref={ref} className="grid grid-cols-2 gap-3 sm:gap-5 lg:grid-cols-3">
      {/* ── Chiffre phare ── */}
      {m.accuracy_top3 != null && (
        <div className="col-span-2 lg:row-span-2">
          <Carte max={4} className="relative overflow-hidden">
            <span aria-hidden className="pointer-events-none absolute -left-20 -top-24 h-72 w-72 rounded-full bg-amber-300/30 blur-3xl" />
            <div className="relative grid h-full items-center gap-8 sm:grid-cols-[auto_1fr]">
              <Anneau3D pct={m.accuracy_top3} hasard={m.hasard_top3} hidden={hidden} taille={250} epaisseur={24}>
                <Chiffre valeur={m.accuracy_top3} decimales={1} hidden={hidden} className="text-[3.4rem] leading-none" />
                <span className="mt-1 text-[11px] font-medium uppercase tracking-[0.14em] text-amber-700">Top 3</span>
              </Anneau3D>
              <div>
                <p className="inline-flex items-center gap-2 text-xs font-medium text-stone-500">
                  <span className="relative flex h-2 w-2">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60 motion-reduce:hidden" />
                    <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
                  </span>
                  Mesuré en continu{depuis ? ` depuis le ${depuis}` : ""}
                </p>
                <h3 className="mt-4 font-display text-2xl font-semibold leading-tight tracking-[-0.02em] text-stone-950 sm:text-[1.7rem]">
                  Le gagnant était dans le Top 3 de l&apos;algorithme.
                </h3>
                <p className="mt-2 text-[15px] leading-relaxed text-stone-500">Annoncé avant le départ, vérifié à l&apos;arrivée officielle PMU.</p>
                {facteur != null && (
                  <div className="mt-6 flex flex-wrap items-center gap-3">
                    <span className="rounded-2xl bg-gradient-to-b from-amber-300 to-amber-500 px-4 py-2 font-display text-2xl font-semibold tabular-nums text-stone-950 shadow-[inset_0_1px_0_rgba(255,255,255,.6),0_10px_22px_-10px_rgba(180,83,9,.7)]">
                      ×{nf(facteur, 1)}
                    </span>
                    <span className="text-sm leading-snug text-stone-600">
                      plus souvent qu&apos;un tirage au sort<br />
                      <span className="text-stone-400">anneau gris : hasard, {nf(m.hasard_top3!, 1)} %</span>
                    </span>
                  </div>
                )}
              </div>
            </div>
          </Carte>
        </div>
      )}

      {/* ── Favori placé / gagnant ── */}
      {[
        { l: "Favori placé", s: "Le n°1 de l'algo finit dans les 3", v: m.favori_place_rate, h: null as number | null, t: "emeraude" as const },
        { l: "Favori gagnant", s: m.hasard_top1 != null ? `Hasard : ${nf(m.hasard_top1, 1)} %` : "Le n°1 de l'algo gagne", v: m.favori_win_rate, h: m.hasard_top1, t: "or" as const },
      ].map((c) => c.v != null && (
        <Carte key={c.l} className="!p-5 sm:!p-6">
          <div className="flex flex-col items-center gap-4 text-center sm:flex-row sm:text-left lg:flex-col lg:text-center xl:flex-row xl:text-left">
            <Anneau3D pct={c.v} hasard={c.h} hidden={hidden} taille={112} epaisseur={20} teinte={c.t}>
              <Chiffre valeur={c.v} decimales={1} hidden={hidden} className="text-[1.45rem] leading-none" />
            </Anneau3D>
            <div>
              <p className="font-display text-base font-semibold text-stone-900">{c.l}</p>
              <p className="mt-1 text-xs leading-snug text-stone-500">{c.s}</p>
            </div>
          </div>
        </Carte>
      ))}

      {/* ── Face au hasard : duels de colonnes ── */}
      {m.accuracy_top3 != null && m.hasard_top3 != null && (
        <div className="col-span-2 lg:col-span-1">
          <Carte>
            <p className="font-display text-base font-semibold text-stone-900">Face au hasard</p>
            <p className="mt-1 text-xs text-stone-500">Or : BlackTurf · gris : tirage au sort</p>
            <div className="mt-12 grid grid-cols-2 gap-4">
              {[
                { t: "Top 3", n: m.accuracy_top3, h: m.hasard_top3 },
                ...(m.favori_win_rate != null && m.hasard_top1 != null ? [{ t: "Favori gagnant", n: m.favori_win_rate, h: m.hasard_top1 }] : []),
              ].map((d, i) => (
                <div key={d.t} className="flex flex-col items-center">
                  <div className="relative flex items-end justify-center gap-4 px-2">
                    <Socle />
                    <Prisme pct={d.n} ton="or" hidden={hidden} delai={i * 120} hauteur="h-36" etiquette={`${nf(d.n, 0)} %`} />
                    <Prisme pct={d.h} ton="gris" hidden={hidden} delai={i * 120 + 80} hauteur="h-36" etiquette={`${nf(d.h, 0)} %`} />
                  </div>
                  <p className="mt-5 text-xs font-medium text-stone-600">{d.t}</p>
                  <p className="font-display text-sm font-semibold tabular-nums text-amber-700">×{nf(d.n / d.h, 1)}</p>
                </div>
              ))}
            </div>
          </Carte>
        </div>
      )}

      {/* ── 7 derniers jours ── */}
      {m.by_day.length > 1 && (
        <div className="col-span-2 lg:col-span-1">
          <Carte>
            <div className="flex items-baseline justify-between gap-3">
              <p className="font-display text-base font-semibold text-stone-900">Top 3, jour par jour</p>
              {moy != null && <span className="rounded-full bg-amber-50 px-2.5 py-1 text-xs font-semibold tabular-nums text-amber-800 ring-1 ring-amber-200">moy. {nf(moy, 0)} %</span>}
            </div>
            <p className="mt-1 text-xs text-stone-500">7 derniers jours</p>
            <div className="relative mt-12 flex items-end justify-between gap-1.5 px-1">
              <Socle />
              {m.by_day.map((d, i) => (
                <div key={d.jour} className="flex flex-1 flex-col items-center">
                  <Prisme pct={echelle(d.accuracy_top3)} ton="or" hidden={hidden} delai={i * 70} hauteur="h-32" largeur="w-5 sm:w-6" etiquette={nf(d.accuracy_top3, 0)} />
                </div>
              ))}
            </div>
            <div className="mt-4 flex justify-between gap-1.5 px-1">
              {m.by_day.map((d) => <span key={d.jour} className="flex-1 text-center text-[10px] text-stone-400">{d.jour}</span>)}
            </div>
            <p className="mt-4 text-[11px] text-stone-400">Échelle des colonnes : de 40 à 80 %.</p>
          </Carte>
        </div>
      )}

      {/* ── Par discipline : tubes brillants ── */}
      {m.by_discipline.length > 0 && (
        <div className="col-span-2 lg:col-span-1">
          <Carte>
            <div className="flex items-baseline justify-between gap-3">
              <p className="font-display text-base font-semibold text-stone-900">Par discipline</p>
              {m.nb_courses != null && <span className="text-xs text-stone-500"><b className="font-semibold tabular-nums text-stone-900">{nf(m.nb_courses)}</b> courses</span>}
            </div>
            <ul className="mt-6 space-y-4">
              {m.by_discipline.map((d) => (
                <li key={d.discipline}>
                  <div className="flex items-baseline justify-between text-sm">
                    <span className="text-stone-700">{DISC[d.discipline] ?? d.discipline}</span>
                    <span className="font-display font-semibold tabular-nums text-stone-950">{nf(d.accuracy_top3, 1)} %</span>
                  </div>
                  <div className="relative mt-2 h-3.5 rounded-full bg-gradient-to-b from-stone-200 to-stone-100 shadow-[inset_0_1px_2px_rgba(0,0,0,.12)]">
                    <div className="tr-bar absolute inset-y-0 left-0 overflow-hidden rounded-full bg-gradient-to-b from-amber-300 via-amber-500 to-amber-700 shadow-[0_4px_10px_-4px_rgba(180,83,9,.7)]"
                      style={{ width: `${hidden ? 0 : borne(d.accuracy_top3)}%` }}>
                      <span className="absolute inset-x-2 top-[2px] h-[3px] rounded-full bg-white/60" />
                    </div>
                    {m.hasard_top3 != null && (
                      <span className="absolute -inset-y-1 w-0.5 rounded-full bg-stone-500/70" style={{ left: `${borne(m.hasard_top3)}%` }} />
                    )}
                  </div>
                </li>
              ))}
            </ul>
            {m.hasard_top3 != null && <p className="mt-5 text-[11px] text-stone-400">Trait gris : hasard ({nf(m.hasard_top3, 0)} %).</p>}
          </Carte>
        </div>
      )}

      <div className="col-span-2 lg:col-span-3">
        <EchantillonNotice nbCourses={m.nb_courses} mesureDepuis={m.mesure_depuis} />
      </div>
    </div>
  );
}
