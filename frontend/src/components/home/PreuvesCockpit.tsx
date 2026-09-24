"use client";

/**
 * Preuves (accueil) : les quatre mesures du palmarès et la comparaison
 * « nous contre le hasard », dans une mise en page claire et sobre.
 *
 * Règles conservées :
 *  - l'état servi est l'état FINAL — chiffres pleins, barres remplies. Les
 *    barres ne se remplissent à l'écran que si le bloc était encore sous la
 *    ligne de flottaison quand le script a démarré (cf. `useReveal`) ;
 *  - le repère « hasard » n'est jamais posé à la main : c'est `hasard_top3`
 *    / `hasard_top1`, calculés course par course sur le champ réel. Sans
 *    lui, on n'affiche ni repère ni facteur.
 */

import { EchantillonNotice } from "@/components/stats/EchantillonNotice";
import { useReveal } from "@/components/track-record/effets";

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

// ─── Mesure ─────────────────────────────────────────────────────
function Mesure({ label, sub, valeur, decimales, suffixe, hasard, hidden }: {
  label: string; sub: string; valeur: number | null; decimales: number; suffixe: string;
  hasard?: number | null; hidden: boolean;
}) {
  return (
    <div className="border-t border-stone-200 pt-5">
      <p className="text-sm text-stone-500">{label}</p>
      <p className="mt-2 font-display text-4xl font-medium tracking-tight text-stone-900 tabular-nums sm:text-[2.6rem]">
        {valeur == null ? "—" : nf(valeur, decimales)}
        {valeur != null && suffixe && <span className="ml-1 text-xl text-stone-400">{suffixe}</span>}
      </p>
      <p className="mt-2 text-sm leading-relaxed text-stone-500">{sub}</p>
      {valeur != null && hasard !== undefined && (
        <div className="mt-5" aria-hidden="true">
          <div className="relative h-1 rounded-full bg-stone-100">
            <div
              className="tr-bar absolute inset-y-0 left-0 rounded-full bg-stone-800"
              style={{ width: `${hidden ? 0 : borne(valeur)}%` }}
            />
            {hasard != null && (
              <span
                className="absolute -top-1 h-3 w-px bg-stone-400"
                style={{ left: `${borne(hasard)}%` }}
              />
            )}
          </div>
          {hasard != null && (
            <p className="mt-2 text-xs text-stone-400">Hasard : {nf(hasard, 0)} %</p>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Comparaison « nous contre le hasard » ──────────────────────
function Comparaison({ label, aide, nous, hasard, hidden }: {
  label: string; aide: string; nous: number; hasard: number | null; hidden: boolean;
}) {
  const facteur = hasard && hasard > 0 ? nous / hasard : null;
  return (
    <div className="py-8 first:pt-0 last:pb-0">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between sm:gap-6">
        <h4 className="font-display text-lg font-medium text-stone-900">{label}</h4>
        {facteur != null && (
          <p className="text-sm text-stone-500">
            <span className="font-medium text-amber-700">{nf(facteur, 1)} fois</span> plus souvent que le hasard
          </p>
        )}
      </div>
      <p className="mt-1 text-sm text-stone-500">{aide}</p>

      <dl className="mt-6 space-y-4">
        <div className="grid grid-cols-[7.5rem_1fr_3.5rem] items-center gap-4 sm:grid-cols-[9rem_1fr_4rem]">
          <dt className="text-sm text-stone-700">BlackTurf</dt>
          <div className="h-2 rounded-full bg-stone-100" aria-hidden="true">
            <div className="tr-bar h-full rounded-full bg-amber-600" style={{ width: `${hidden ? 0 : borne(nous)}%` }} />
          </div>
          <dd className="text-right text-sm font-medium tabular-nums text-stone-900">{nf(nous, 1)} %</dd>
        </div>
        {hasard != null && (
          <div className="grid grid-cols-[7.5rem_1fr_3.5rem] items-center gap-4 sm:grid-cols-[9rem_1fr_4rem]">
            <dt className="text-sm text-stone-500">Tirage au sort</dt>
            <div className="h-2 rounded-full bg-stone-100" aria-hidden="true">
              <div className="tr-bar h-full rounded-full bg-stone-300" style={{ width: `${hidden ? 0 : borne(hasard)}%` }} />
            </div>
            <dd className="text-right text-sm tabular-nums text-stone-500">{nf(hasard, 1)} %</dd>
          </div>
        )}
      </dl>
    </div>
  );
}

// ─── Panneau complet ────────────────────────────────────────────
export function PreuvesCockpit({ m }: { m: PreuvesMesures }) {
  const depuis = formatDepuis(m.mesure_depuis);
  const { ref: refMesures, hidden: mesuresCachees } = useReveal<HTMLDivElement>(0.3);
  const { ref: refDuel, hidden: duelCache } = useReveal<HTMLDivElement>(0.3);

  return (
    <div className="rounded-3xl bg-white p-6 ring-1 ring-stone-200/70 sm:p-10 lg:p-12">
      <div className="mb-8 flex flex-wrap items-center justify-between gap-2 text-sm text-stone-500">
        <span className="inline-flex items-center gap-2">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden="true" />
          Mesuré en continu, réglé aux rapports PMU officiels
        </span>
        <span>{depuis ? `Depuis le ${depuis}` : "Cohorte pré-course"}</span>
      </div>

      <div
        ref={refMesures}
        className="grid gap-x-8 gap-y-10 sm:grid-cols-2 lg:grid-cols-4"
      >
        {/* `accuracy_top3` mesure la présence du GAGNANT RÉEL dans notre top-3 —
            pas « un de nos 3 favoris finit dans les 3 », évènement bien plus facile. */}
        <Mesure label="Gagnant dans le Top-3" sub="Le cheval qui gagne est parmi nos trois premiers choix."
          valeur={m.accuracy_top3} decimales={1} suffixe="%" hasard={m.hasard_top3} hidden={mesuresCachees} />
        {/* Qu'un cheval tiré au sort finisse dans les 3 vaut aussi 3/partants :
            le repère est donc `hasard_top3`. */}
        <Mesure label="Notre favori placé" sub="Notre n°1 termine dans les trois premiers."
          valeur={m.favori_place_rate} decimales={1} suffixe="%" hasard={m.hasard_top3} hidden={mesuresCachees} />
        <Mesure label="Notre favori gagnant" sub="Notre n°1 remporte la course."
          valeur={m.favori_win_rate} decimales={1} suffixe="%" hasard={m.hasard_top1} hidden={mesuresCachees} />
        <Mesure label="Courses vérifiées" sub="Aucun pronostic réécrit. Mise à jour toutes les 15 minutes."
          valeur={m.nb_courses} decimales={0} suffixe="" hidden={mesuresCachees} />
      </div>

      <EchantillonNotice nbCourses={m.nb_courses} mesureDepuis={m.mesure_depuis} />

      {/* ── Ce que vaut le classement, face au hasard ──────────────────── */}
      {m.hasard_top3 != null && m.accuracy_top3 != null && (
        <div ref={refDuel} className="mt-14 grid gap-10 lg:grid-cols-[1fr_1.6fr] lg:gap-16">
          <div>
            <h3 className="font-display text-2xl font-medium tracking-tight text-stone-900">Face au hasard</h3>
            <p className="mt-3 text-sm leading-relaxed text-stone-500">
              Chaque mesure est comparée à un tirage au sort sur le champ réel de chaque course.
              Le repère est recalculé selon le nombre de partants : dans un champ de huit il vaut
              plus que dans un champ de seize. L&apos;écart mesure donc bien l&apos;analyse, pas la
              taille des pelotons.
            </p>
          </div>
          <div className="divide-y divide-stone-200/70">
            <Comparaison
              label="Le gagnant est dans notre Top-3"
              aide="Comparé à un tirage au sort de trois chevaux."
              nous={m.accuracy_top3}
              hasard={m.hasard_top3}
              hidden={duelCache}
            />
            {m.favori_win_rate != null && (
              <Comparaison
                label="Notre favori gagne la course"
                aide="Comparé à un cheval tiré au sort."
                nous={m.favori_win_rate}
                hasard={m.hasard_top1}
                hidden={duelCache}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
