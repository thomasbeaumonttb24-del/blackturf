"use client";

/**
 * Preuves (accueil) : les quatre mesures du palmarès et la comparaison
 * « nous contre le hasard », en colonnes en relief qui montent à l'écran.
 *
 * Règles conservées :
 *  - l'état servi est l'état FINAL — chiffres pleins, colonnes à leur hauteur.
 *    Le compteur et la montée ne jouent que si le bloc était encore sous la
 *    ligne de flottaison quand le script a démarré (cf. `useReveal`) ;
 *  - le repère « hasard » n'est jamais posé à la main : c'est `hasard_top3`
 *    / `hasard_top1`, calculés course par course sur le champ réel. Sans
 *    lui, on n'affiche ni repère ni facteur.
 */

import { useEffect, useRef, useState, type CSSProperties } from "react";
import { EchantillonNotice } from "@/components/stats/EchantillonNotice";
import { Tilt, useReveal } from "@/components/track-record/effets";
import { cn } from "@/lib/utils";

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

const borne = (n: number) => Math.max(0, Math.min(100, n));

function formatDepuis(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? null
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
      const p = Math.min(1, (t - t0) / duree);
      setV(cible * (1 - Math.pow(1 - p, 3)));
      if (p < 1) raf = requestAnimationFrame(pas);
    };
    raf = requestAnimationFrame(pas);
    return () => cancelAnimationFrame(raf);
  }, [cible, hidden, duree]);
  return v;
}

// ─── Mesure ─────────────────────────────────────────────────────
function Mesure({ label, sub, valeur, decimales, suffixe, hasard, delai }: {
  label: string; sub: string; valeur: number | null; decimales: number; suffixe: string;
  hasard?: number | null; delai: number;
}) {
  const { ref, hidden } = useReveal<HTMLDivElement>(0.3);
  const v = useCompteur(valeur, hidden, 1300 + delai);
  return (
    <div ref={ref} className={cn("tr-reveal h-full", hidden && "tr-armed")} style={{ "--tr-delay": `${delai}ms` } as CSSProperties}>
      <Tilt max={8} className="h-full rounded-3xl bg-white p-6 ring-1 ring-stone-200/80 shadow-[0_30px_60px_-45px_rgba(28,25,23,.5)] transition-shadow hover:shadow-[0_40px_70px_-40px_rgba(28,25,23,.45)]">
        <p className="text-sm text-stone-500">{label}</p>
        <p className="mt-3 whitespace-nowrap font-display text-[2.6rem] font-medium leading-none tracking-tight text-stone-900 tabular-nums">
          {v == null ? "—" : nf(v, decimales)}
          {v != null && suffixe && <span className="ml-1 text-xl text-stone-400">{suffixe}</span>}
        </p>
        <p className="mt-3 text-sm leading-relaxed text-stone-500">{sub}</p>
        {valeur != null && hasard !== undefined && (
          <div className="mt-5" aria-hidden="true">
            <div className="relative h-1.5 rounded-full bg-stone-100">
              <div className="tr-bar absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-amber-500 to-amber-600" style={{ width: `${hidden ? 0 : borne(valeur)}%` }} />
              {hasard != null && <span className="absolute -top-1 h-3.5 w-0.5 rounded-full bg-stone-400" style={{ left: `${borne(hasard)}%` }} />}
            </div>
            {hasard != null && <p className="mt-2 text-xs text-stone-400">Hasard : {nf(hasard, 0)} %</p>}
          </div>
        )}
      </Tilt>
    </div>
  );
}

// ─── Colonne en relief ──────────────────────────────────────────
function Colonne({ pct, label, ton, hidden, delai }: {
  pct: number; label: string; ton: "or" | "gris"; hidden: boolean; delai: number;
}) {
  const v = useCompteur(pct, hidden, 1500 + delai);
  const faces = ton === "or"
    ? { face: "from-amber-400 to-amber-600", dessus: "bg-amber-200", cote: "bg-amber-700" }
    : { face: "from-stone-200 to-stone-300", dessus: "bg-stone-100", cote: "bg-stone-400" };
  return (
    <div className="flex h-full flex-col items-center justify-end">
      {/* Hauteur utile : la colonne se lit sur l'espace sous les étiquettes. */}
      <div className="relative flex h-[12rem] items-end">
        <div
          className="colonne3d relative w-14 sm:w-16"
          style={{ height: `${hidden ? 0 : Math.max(2, borne(pct))}%`, transitionDelay: `${delai}ms` }}
        >
          <span className={cn("absolute inset-0 bg-gradient-to-b", faces.face)} />
          <span className={cn("absolute bottom-full left-0 h-3.5 w-full origin-bottom-left -skew-x-[45deg]", faces.dessus)} />
          <span className={cn("absolute left-full top-0 h-full w-3.5 origin-top-left -skew-y-[45deg]", faces.cote)} />
          {/* Valeur posée sur le dessus de la colonne : elle monte avec elle. */}
          <span className={cn(
            "absolute bottom-full left-1/2 mb-6 -translate-x-1/2 whitespace-nowrap font-display text-xl font-medium tabular-nums",
            ton === "or" ? "text-stone-900" : "text-stone-400",
          )}>
            {nf(v ?? pct, 1)} %
          </span>
        </div>
      </div>
      <span className="mt-4 text-sm text-stone-500">{label}</span>
    </div>
  );
}

function Duel({ titre, aide, nous, hasard }: { titre: string; aide: string; nous: number; hasard: number | null }) {
  const { ref, hidden } = useReveal<HTMLDivElement>(0.35);
  const facteur = hasard && hasard > 0 ? nous / hasard : null;
  return (
    <div ref={ref} className="h-full">
      <Tilt max={5} className="h-full rounded-3xl bg-white p-6 ring-1 ring-stone-200/80 shadow-[0_30px_60px_-45px_rgba(28,25,23,.5)] sm:p-8">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h4 className="font-display text-lg font-medium text-stone-900">{titre}</h4>
            <p className="mt-1 text-sm text-stone-500">{aide}</p>
          </div>
          {facteur != null && (
            <span className="shrink-0 rounded-full bg-amber-50 px-3 py-1.5 font-display text-lg font-medium tabular-nums text-amber-700 ring-1 ring-amber-200/70">
              ×{nf(facteur, 1)}
            </span>
          )}
        </div>
        <div className="relative mt-14" aria-hidden="true">
          {/* Sol en perspective sous les colonnes. */}
          <div className="absolute inset-x-6 bottom-8 h-16 rounded-[50%] bg-gradient-to-b from-stone-100 to-stone-50 [transform:perspective(500px)_rotateX(62deg)]" />
          <div className="relative flex items-end justify-center gap-16 sm:gap-24">
            <Colonne pct={nous} label="BlackTurf" ton="or" hidden={hidden} delai={0} />
            {hasard != null && <Colonne pct={hasard} label="Tirage au sort" ton="gris" hidden={hidden} delai={150} />}
          </div>
        </div>
        {facteur != null && (
          <p className="mt-6 text-center text-sm text-stone-500">
            <span className="font-medium text-stone-900">{nf(facteur, 1)} fois</span> plus souvent qu&apos;un tirage au sort
          </p>
        )}
        <span className="sr-only">BlackTurf {nf(nous, 1)} %{hasard != null ? `, tirage au sort ${nf(hasard, 1)} %` : ""}.</span>
      </Tilt>
    </div>
  );
}

// ─── Panneau complet ────────────────────────────────────────────
export function PreuvesCockpit({ m }: { m: PreuvesMesures }) {
  const depuis = formatDepuis(m.mesure_depuis);

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center justify-center gap-x-4 gap-y-1 text-sm text-stone-500">
        <span className="inline-flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60 motion-reduce:hidden" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
          </span>
          Mesuré en continu, réglé aux rapports PMU officiels
        </span>
        <span className="text-stone-300" aria-hidden="true">·</span>
        <span>{depuis ? `Depuis le ${depuis}` : "Cohorte pré-course"}</span>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {/* `accuracy_top3` mesure la présence du GAGNANT RÉEL dans notre top-3 —
            pas « un de nos 3 favoris finit dans les 3 », évènement bien plus facile. */}
        <Mesure label="Gagnant dans le Top-3" sub="Le cheval qui gagne est parmi nos trois premiers choix."
          valeur={m.accuracy_top3} decimales={1} suffixe="%" hasard={m.hasard_top3} delai={0} />
        {/* Qu'un cheval tiré au sort finisse dans les 3 vaut aussi 3/partants :
            le repère est donc `hasard_top3`. */}
        <Mesure label="Notre favori placé" sub="Notre n°1 termine dans les trois premiers."
          valeur={m.favori_place_rate} decimales={1} suffixe="%" hasard={m.hasard_top3} delai={80} />
        <Mesure label="Notre favori gagnant" sub="Notre n°1 remporte la course."
          valeur={m.favori_win_rate} decimales={1} suffixe="%" hasard={m.hasard_top1} delai={160} />
        <Mesure label="Courses vérifiées" sub="Aucun pronostic réécrit. Mise à jour toutes les 15 minutes."
          valeur={m.nb_courses} decimales={0} suffixe="" delai={240} />
      </div>

      <EchantillonNotice nbCourses={m.nb_courses} mesureDepuis={m.mesure_depuis} />

      {/* ── Ce que vaut le classement, face au hasard ──────────────────── */}
      {m.hasard_top3 != null && m.accuracy_top3 != null && (
        <div className="mt-20">
          <div className="mx-auto mb-10 max-w-2xl text-center">
            <h3 className="font-display text-2xl font-medium tracking-tight text-stone-900 sm:text-3xl">Face au hasard</h3>
            <p className="mt-3 text-sm leading-relaxed text-stone-500">
              Chaque mesure est comparée à un tirage au sort sur le champ réel de chaque course.
              Le repère est recalculé selon le nombre de partants : l&apos;écart mesure donc bien
              l&apos;analyse, pas la taille des pelotons.
            </p>
          </div>
          <div className="grid gap-5 lg:grid-cols-2">
            <Duel
              titre="Le gagnant est dans notre Top-3"
              aide="Face à trois chevaux tirés au sort."
              nous={m.accuracy_top3}
              hasard={m.hasard_top3}
            />
            {m.favori_win_rate != null && (
              <Duel
                titre="Notre favori gagne la course"
                aide="Face à un cheval tiré au sort."
                nous={m.favori_win_rate}
                hasard={m.hasard_top1}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
