"use client";

/**
 * Tableau de bord des preuves (accueil) : les quatre mesures du palmarès et
 * le duel « nous contre le hasard », sur un panneau sombre d'instrument.
 *
 * Mêmes règles que les jauges du palmarès :
 *  - l'état servi est l'état FINAL — chiffres pleins, anneaux remplis. Le
 *    compteur et le balayage ne jouent que si le bloc était encore sous la
 *    ligne de flottaison quand le script a démarré (cf. `useReveal`) ;
 *  - le repère « hasard » n'est jamais posé à la main : c'est `hasard_top3`
 *    / `hasard_top1`, calculés course par course sur le champ réel. Sans
 *    lui, on n'affiche ni repère ni facteur.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Database, Shield, Target, Trophy } from "lucide-react";
import { cn } from "@/lib/utils";
import { EchantillonNotice } from "@/components/stats/EchantillonNotice";
import { Tilt, useReveal } from "@/components/track-record/effets";

export type PreuvesMesures = {
  accuracy_top3: number | null;
  favori_place_rate: number | null;
  favori_win_rate: number | null;
  nb_courses: number | null;
  mesure_depuis: string | null;
  hasard_top3: number | null;
  hasard_top1: number | null;
};

const nf = (n: number, d = 0) =>
  n.toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d });

const TEINTES = {
  or: { a: "#FCD34D", b: "#F59E0B", c: "#B45309", texte: "text-amber-300", halo: "bg-amber-400/25", ombre: "rgba(245,158,11,.55)" },
  emeraude: { a: "#6EE7B7", b: "#10B981", c: "#047857", texte: "text-emerald-300", halo: "bg-emerald-400/25", ombre: "rgba(16,185,129,.55)" },
  ivoire: { a: "#F8FAFC", b: "#CBD5E1", c: "#64748B", texte: "text-white", halo: "bg-white/15", ombre: "rgba(255,255,255,.35)" },
  azur: { a: "#7DD3FC", b: "#38BDF8", c: "#0369A1", texte: "text-sky-300", halo: "bg-sky-400/25", ombre: "rgba(56,189,248,.55)" },
} as const;
type Teinte = keyof typeof TEINTES;

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
      const p = Math.min(1, (t - t0) / duree);
      setV(cible * (1 - Math.pow(1 - p, 3)));
      if (p < 1) raf = requestAnimationFrame(pas);
    };
    raf = requestAnimationFrame(pas);
    return () => cancelAnimationFrame(raf);
  }, [cible, hidden, duree]);
  return v;
}

function formatDepuis(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? null
    : d.toLocaleDateString("fr-FR", { timeZone: "Europe/Paris", day: "numeric", month: "short", year: "numeric" });
}

// ─── Barre segmentée avec repère « hasard » ─────────────────────
const SEGMENTS = 24;

function BarreSegments({ pct, hasard, teinte, hidden }: {
  pct: number; hasard: number | null; teinte: Teinte; hidden: boolean;
}) {
  const t = TEINTES[teinte];
  const allumes = Math.round((Math.max(0, Math.min(100, pct)) / 100) * SEGMENTS);
  return (
    <div className="relative mt-4" aria-hidden="true">
      <div className="flex gap-[3px]">
        {Array.from({ length: SEGMENTS }, (_, i) => {
          const on = i < allumes;
          return (
            <span
              key={i}
              className="h-2.5 flex-1 rounded-[2px] transition-[background-color,box-shadow] duration-500"
              style={{
                background: on && !hidden ? `linear-gradient(180deg, ${t.a}, ${t.b})` : "rgba(255,255,255,.07)",
                boxShadow: on && !hidden ? `0 0 8px ${t.ombre}` : "none",
                transitionDelay: hidden ? "0ms" : `${i * 35}ms`,
              }}
            />
          );
        })}
      </div>
      {hasard != null && (
        <span
          className="absolute -top-1.5 flex -translate-x-1/2 flex-col items-center"
          style={{ left: `${Math.max(0, Math.min(100, hasard))}%` }}
        >
          <span className="h-[22px] w-px bg-white/80 shadow-[0_0_6px_rgba(255,255,255,.9)]" />
        </span>
      )}
      {/* Étiquette posée sous le repère, bornée pour ne pas sortir de la tuile. */}
      <div className="relative mt-1.5 h-3 font-mono text-[9px] uppercase tracking-[0.12em] text-white/35">
        {hasard != null && (
          <span
            className="absolute top-0 -translate-x-1/2 whitespace-nowrap text-white/60"
            style={{ left: `clamp(2.4rem, ${Math.max(0, Math.min(100, hasard))}%, calc(100% - 2.4rem))` }}
          >
            hasard {nf(hasard, 0)} %
          </span>
        )}
      </div>
    </div>
  );
}

// ─── Tuile de mesure ────────────────────────────────────────────
function Tuile({ index, code, icon, label, sub, valeur, decimales, suffixe, teinte, delai, children }: {
  index: string; code: string; icon: ReactNode; label: string; sub: string;
  valeur: number | null; decimales: number; suffixe: string; teinte: Teinte; delai: number;
  children?: (hidden: boolean) => ReactNode;
}) {
  const { ref, hidden } = useReveal<HTMLDivElement>(0.3);
  const v = useCompteur(valeur, hidden, 1400 + delai);
  const t = TEINTES[teinte];
  return (
    <div ref={ref} className="h-full">
      <Tilt
        max={6}
        className="group h-full overflow-hidden rounded-2xl bg-gradient-to-b from-white/[.07] to-white/[.02] p-4 ring-1 ring-white/10 backdrop-blur-sm transition-shadow hover:ring-white/20 sm:p-5"
      >
        <span className={cn("pointer-events-none absolute -right-10 -top-10 h-28 w-28 rounded-full blur-2xl transition-opacity group-hover:opacity-100 opacity-70", t.halo)} aria-hidden="true" />
        <span className="pointer-events-none absolute inset-x-4 top-0 h-px bg-gradient-to-r from-transparent via-white/30 to-transparent" aria-hidden="true" />
        <div className="relative flex items-center justify-between">
          <span className="whitespace-nowrap font-mono text-[10px] uppercase tracking-[0.08em] text-white/45 sm:tracking-[0.16em]">
            {index} <span className="text-white/25">/</span> {code}
          </span>
          <span
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg ring-1 ring-white/15"
            style={{ background: `linear-gradient(135deg, ${t.b}33, ${t.c}22)`, color: t.a }}
          >
            {icon}
          </span>
        </div>
        <div
          className={cn("tr-pop relative mt-3 font-display text-[1.9rem] font-black leading-none tabular-nums sm:text-[2.4rem]", t.texte)}
          style={{ textShadow: `0 0 24px ${t.ombre}` }}
        >
          {v == null ? "—" : nf(v, decimales)}
          {v != null && suffixe && <span className="ml-0.5 text-[.55em] font-bold opacity-80">{suffixe}</span>}
        </div>
        <p className="relative mt-2 text-sm font-semibold text-white">{label}</p>
        <p className="relative mt-0.5 text-xs leading-snug text-white/55">{sub}</p>
        {children?.(hidden)}
      </Tilt>
    </div>
  );
}

// ─── Cadran « nous contre le hasard » ───────────────────────────
const GRADUATIONS = 60;
// Arrondi au centième : le serveur et le navigateur ne rendent pas les mêmes
// derniers chiffres d'un cosinus, et React refuse alors l'hydratation.
const px = (n: number) => Math.round(n * 100) / 100;

function Cadran({ label, aide, nous, hasard, teinte }: {
  label: string; aide: string; nous: number; hasard: number | null; teinte: Teinte;
}) {
  const { ref, hidden } = useReveal<HTMLDivElement>(0.35);
  const compte = useCompteur(nous, hidden, 1600) ?? nous;
  const t = TEINTES[teinte];
  const id = `cadran-${teinte}`;
  const v = Math.max(0, Math.min(100, nous));
  const h = hasard != null ? Math.max(0, Math.min(100, hasard)) : null;
  const facteur = hasard && hasard > 0 ? nous / hasard : null;
  const ecart = hasard != null ? nous - hasard : null;

  const R = 92, r = 72;
  const C = 2 * Math.PI * R, c = 2 * Math.PI * r;
  const angle = (p: number) => ((p / 100) * 360 - 90) * (Math.PI / 180);
  const bout = { x: px(120 + R * Math.cos(angle(v))), y: px(120 + R * Math.sin(angle(v))) };

  return (
    <div ref={ref} className="h-full">
      <Tilt
        max={5}
        className="h-full overflow-hidden rounded-3xl bg-gradient-to-br from-white/[.08] via-white/[.03] to-transparent p-5 ring-1 ring-white/10 sm:p-6"
      >
        <span className={cn("tr-glow pointer-events-none absolute -left-16 top-1/4 h-56 w-56 rounded-full blur-3xl", t.halo)} aria-hidden="true" />
        <div className="relative flex flex-col items-center gap-5 sm:flex-row sm:gap-6 lg:flex-col xl:flex-row">
          <div className="relative w-full max-w-[230px] shrink-0 sm:w-[42%] lg:w-full xl:w-[44%]">
            <svg viewBox="0 0 240 240" className="h-auto w-full" role="img"
              aria-label={`${label} : ${nf(nous, 1)} %${hasard != null ? `, contre ${nf(hasard, 1)} % pour le hasard` : ""}`}>
              <defs>
                <linearGradient id={`${id}-g`} x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" stopColor={t.a} />
                  <stop offset="60%" stopColor={t.b} />
                  <stop offset="100%" stopColor={t.c} />
                </linearGradient>
                <radialGradient id={`${id}-coeur`}>
                  <stop offset="0%" stopColor="rgba(255,255,255,.07)" />
                  <stop offset="100%" stopColor="rgba(255,255,255,0)" />
                </radialGradient>
                <filter id={`${id}-halo`} x="-30%" y="-30%" width="160%" height="160%">
                  <feGaussianBlur stdDeviation="4" result="b" />
                  <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
                </filter>
              </defs>

              {/* Graduations : allumées jusqu'à notre valeur, repère hasard en blanc. */}
              {Array.from({ length: GRADUATIONS }, (_, i) => {
                const p = (i / GRADUATIONS) * 100;
                const a = angle(p);
                const majeure = i % 5 === 0;
                const r1 = 108, r2 = majeure ? 116 : 113;
                const on = p < v && !hidden;
                return (
                  <line
                    key={i}
                    x1={px(120 + r1 * Math.cos(a))} y1={px(120 + r1 * Math.sin(a))}
                    x2={px(120 + r2 * Math.cos(a))} y2={px(120 + r2 * Math.sin(a))}
                    stroke={on ? t.a : "rgba(255,255,255,.14)"}
                    strokeWidth={majeure ? 2 : 1.2}
                    strokeLinecap="round"
                    style={{ transition: "stroke .4s ease", transitionDelay: hidden ? "0ms" : `${i * 18}ms` }}
                  />
                );
              })}

              <circle cx="120" cy="120" r={R} fill="none" stroke="rgba(255,255,255,.06)" strokeWidth="12" />
              <circle
                cx="120" cy="120" r={R} fill="none"
                stroke={`url(#${id}-g)`} strokeWidth="12" strokeLinecap="round"
                strokeDasharray={C} strokeDashoffset={hidden ? C : C * (1 - v / 100)}
                transform="rotate(-90 120 120)" className="tr-ring" filter={`url(#${id}-halo)`}
              />
              {h != null && (
                <>
                  <circle cx="120" cy="120" r={r} fill="none" stroke="rgba(255,255,255,.05)" strokeWidth="5" />
                  <circle
                    cx="120" cy="120" r={r} fill="none"
                    stroke="#94A3B8" strokeWidth="5" strokeLinecap="round"
                    strokeDasharray={c} strokeDashoffset={hidden ? c : c * (1 - h / 100)}
                    transform="rotate(-90 120 120)" className="tr-ring"
                  />
                </>
              )}
              <circle cx="120" cy="120" r="62" fill={`url(#${id}-coeur)`} />
              <circle cx="120" cy="120" r="58" fill="none" stroke="rgba(255,255,255,.08)" strokeDasharray="2 4" />
              {/* Tête de l'arc : un point lumineux au bout de notre valeur. */}
              <circle
                cx={bout.x} cy={bout.y} r="7.5" fill="#fff"
                style={{ opacity: hidden ? 0 : 1, transition: "opacity .4s ease 1.3s", filter: `drop-shadow(0 0 6px ${t.a})` }}
              />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="font-mono text-[9px] uppercase tracking-[0.2em] text-white/40">BlackTurf</span>
              <span className={cn("font-display text-[2.2rem] font-black leading-none tabular-nums", t.texte)} style={{ textShadow: `0 0 22px ${t.ombre}` }}>
                {nf(compte, 1)}<span className="text-base"> %</span>
              </span>
              {hasard != null && (
                <span className="mt-1.5 rounded-full bg-white/5 px-2 py-0.5 font-mono text-[10px] tabular-nums text-slate-300 ring-1 ring-white/10">
                  hasard {nf(hasard, 1)} %
                </span>
              )}
            </div>
          </div>

          <div className="flex w-full min-w-0 flex-1 flex-col text-center sm:text-left lg:text-center xl:text-left">
            <h4 className="font-display text-lg font-bold leading-snug text-white">{label}</h4>
            <p className="mt-1 text-sm leading-6 text-white/60">{aide}</p>

            {facteur != null && ecart != null && (
              <div className="mt-4 grid grid-cols-2 gap-2">
                <div className="rounded-xl bg-white/[.04] px-3 py-2.5 ring-1 ring-white/10">
                  <p className="font-mono text-[9px] uppercase tracking-[0.16em] text-white/45">Multiplicateur</p>
                  <p className={cn("mt-0.5 font-display text-2xl font-black tabular-nums", t.texte)}>×{nf(facteur, 1)}</p>
                </div>
                <div className="rounded-xl bg-white/[.04] px-3 py-2.5 ring-1 ring-white/10">
                  <p className="font-mono text-[9px] uppercase tracking-[0.16em] text-white/45">Écart</p>
                  <p className="mt-0.5 font-display text-2xl font-black tabular-nums text-white">
                    {ecart >= 0 ? "+" : "−"}{nf(Math.abs(ecart), 1)}<span className="ml-1 text-xs font-bold text-white/60">pts</span>
                  </p>
                </div>
              </div>
            )}

            {/* Duel en barres : les deux valeurs sur la même échelle 0-100. */}
            <div className="mt-4 space-y-2.5" aria-hidden="true">
              <div>
                <div className="mb-1 flex justify-between font-mono text-[10px] uppercase tracking-[0.12em] text-white/55">
                  <span className="inline-flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full" style={{ background: t.b, boxShadow: `0 0 6px ${t.b}` }} /> BlackTurf
                  </span>
                  <span className="tabular-nums text-white/80">{nf(nous, 1)} %</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-white/[.06]">
                  <div className="tr-bar h-full rounded-full" style={{ width: `${hidden ? 0 : v}%`, background: `linear-gradient(90deg, ${t.c}, ${t.a})` }} />
                </div>
              </div>
              {h != null && (
                <div>
                  <div className="mb-1 flex justify-between font-mono text-[10px] uppercase tracking-[0.12em] text-white/55">
                    <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-slate-400" /> Tirage au sort</span>
                    <span className="tabular-nums text-white/80">{nf(hasard!, 1)} %</span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-white/[.06]">
                    <div className="tr-bar h-full rounded-full bg-slate-400" style={{ width: `${hidden ? 0 : h}%` }} />
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </Tilt>
    </div>
  );
}

// ─── Panneau complet ────────────────────────────────────────────
export function PreuvesCockpit({ m }: { m: PreuvesMesures }) {
  const depuis = formatDepuis(m.mesure_depuis);
  const ico = "h-4 w-4";

  return (
    <div className="relative isolate overflow-hidden rounded-[2rem] bg-slate-950 p-4 text-white shadow-[0_50px_100px_-50px_rgba(15,23,42,.9)] ring-1 ring-slate-900 sm:p-7 lg:p-9">
      {/* Décor : quadrillage d'instrument, halos, liseré lumineux. */}
      <div
        className="pointer-events-none absolute inset-0 -z-10 opacity-60"
        style={{
          backgroundImage: "linear-gradient(rgba(255,255,255,.045) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.045) 1px, transparent 1px)",
          backgroundSize: "36px 36px",
          WebkitMaskImage: "radial-gradient(ellipse at 50% 30%, #000 30%, transparent 78%)",
          maskImage: "radial-gradient(ellipse at 50% 30%, #000 30%, transparent 78%)",
        }}
        aria-hidden="true"
      />
      <span className="tr-glow pointer-events-none absolute -top-32 left-1/4 -z-10 h-72 w-72 rounded-full bg-amber-500/20 blur-3xl" aria-hidden="true" />
      <span className="tr-glow pointer-events-none absolute -bottom-32 right-1/4 -z-10 h-72 w-72 rounded-full bg-emerald-500/15 blur-3xl" aria-hidden="true" />
      <span className="pointer-events-none absolute inset-x-10 top-0 h-px bg-gradient-to-r from-transparent via-amber-300/60 to-transparent" aria-hidden="true" />

      {/* Barre d'état */}
      <div className="mb-5 flex flex-wrap items-center justify-between gap-2 border-b border-white/10 pb-4 font-mono text-[10px] uppercase tracking-[0.18em] text-white/50 sm:mb-6">
        <span className="inline-flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60 motion-reduce:hidden" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
          </span>
          Mesure en continu
        </span>
        <span className="hidden sm:inline">Réglé aux rapports PMU officiels</span>
        <span>{depuis ? `Depuis le ${depuis}` : "Cohorte pré-course"}</span>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
        {/* `accuracy_top3` mesure la présence du GAGNANT RÉEL dans notre top-3 —
            pas « un de nos 3 favoris finit dans les 3 », évènement bien plus facile. */}
        <Tuile index="01" code="Top-3" icon={<Target className={ico} />} teinte="or" delai={0}
          label="Gagnant dans le Top-3" sub="le cheval qui gagne est parmi nos 3 premiers choix"
          valeur={m.accuracy_top3} decimales={1} suffixe="%">
          {(hidden) => m.accuracy_top3 != null && <BarreSegments pct={m.accuracy_top3} hasard={m.hasard_top3} teinte="or" hidden={hidden} />}
        </Tuile>
        {/* Qu'un cheval tiré au sort finisse dans les 3 vaut aussi 3/partants :
            le repère est donc `hasard_top3`. */}
        <Tuile index="02" code="Placé" icon={<Shield className={ico} />} teinte="emeraude" delai={80}
          label="Notre favori placé" sub="notre n°1 dans les 3 premiers"
          valeur={m.favori_place_rate} decimales={1} suffixe="%">
          {(hidden) => m.favori_place_rate != null && <BarreSegments pct={m.favori_place_rate} hasard={m.hasard_top3} teinte="emeraude" hidden={hidden} />}
        </Tuile>
        <Tuile index="03" code="Gagnant" icon={<Trophy className={ico} />} teinte="ivoire" delai={160}
          label="Notre favori gagnant" sub="notre n°1 remporte la course"
          valeur={m.favori_win_rate} decimales={1} suffixe="%">
          {(hidden) => m.favori_win_rate != null && <BarreSegments pct={m.favori_win_rate} hasard={m.hasard_top1} teinte="ivoire" hidden={hidden} />}
        </Tuile>
        <Tuile index="04" code="Volume" icon={<Database className={ico} />} teinte="azur" delai={240}
          label="Courses vérifiées" sub="réglées aux résultats PMU officiels"
          valeur={m.nb_courses} decimales={0} suffixe="">
          {() => (
            <div className="mt-4 space-y-1.5 font-mono text-[9px] uppercase tracking-[0.04em] text-white/50 sm:text-[10px] sm:tracking-[0.12em]">
              <div className="flex items-center justify-between gap-2 whitespace-nowrap border-t border-white/10 pt-2">
                <span>Réécriture</span><span className="text-emerald-300">aucune</span>
              </div>
              <div className="flex items-center justify-between gap-2 whitespace-nowrap border-t border-white/10 pt-2">
                <span>Mise à jour</span><span className="text-sky-300">15 min</span>
              </div>
            </div>
          )}
        </Tuile>
      </div>

      <EchantillonNotice nbCourses={m.nb_courses} mesureDepuis={m.mesure_depuis} variante="sombre" />

      {/* ── Ce que vaut le classement, face au hasard ──────────────────── */}
      {m.hasard_top3 != null && m.accuracy_top3 != null && (
        <div className="mt-8 sm:mt-10">
          <div className="mb-5 flex flex-col items-center gap-1 text-center">
            <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-amber-300/80">Banc d&apos;essai</span>
            <h3 className="font-display text-xl font-bold text-white sm:text-2xl">Face au hasard</h3>
            <p className="max-w-xl text-sm text-white/60">
              L&apos;anneau coloré, c&apos;est nous ; l&apos;anneau gris, un tirage au sort sur le champ réel de chaque course.
            </p>
          </div>
          <div className="grid gap-4 lg:grid-cols-2 lg:gap-5">
            <Cadran
              label="Le gagnant est dans notre Top-3"
              aide="Comparé à un tirage au sort de 3 chevaux sur le champ réel."
              nous={m.accuracy_top3}
              hasard={m.hasard_top3}
              teinte="or"
            />
            {m.favori_win_rate != null && (
              <Cadran
                label="Notre favori gagne la course"
                aide="Comparé à un cheval tiré au sort dans le champ réel."
                nous={m.favori_win_rate}
                hasard={m.hasard_top1}
                teinte="emeraude"
              />
            )}
          </div>
          <p className="mx-auto mt-5 max-w-3xl text-center text-xs leading-relaxed text-white/50">
            Le repère « hasard » est recalculé sur le nombre réel de partants de chaque course :
            dans un champ de huit il vaut plus que dans un champ de seize. C&apos;est ce qui rend
            la comparaison honnête — et ce qui fait que l&apos;écart mesure bien
            l&apos;analyse, pas la taille des pelotons.
          </p>
        </div>
      )}
    </div>
  );
}
