"use client";

/**
 * Écarts PMU / bookmakers — où le PMU paie plus (ou moins) que le prix juste
 * des bookmakers. Calcul et raisons côté API (`backend/services/ecarts_cotes.py`).
 *
 * Le parieur joue au PMU : une cote PMU PLUS HAUTE que le prix juste des
 * bookmakers lui fait gagner plus à mise égale (intéressant) ; plus basse, moins
 * (à éviter). Aucun ROI n'est annoncé : la mesure de référence porte sur des cotes
 * de clôture, que le parieur ne connaît pas au moment de jouer.
 */

import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { AlertTriangle, ArrowDownRight, ArrowUpRight, ChevronDown, Scale } from "lucide-react";
import { coursesApi } from "@/lib/api";
import { heureParis, titleCase } from "@/lib/seo";
import { cn } from "@/lib/utils";

export type Ecart = {
  numero: number;
  nom?: string | null;
  cote_pmu: number;
  cote_juste_bookmakers: number;
  ecart: number;
  niveau: "fort" | "net" | "a_confirmer" | "defavorable" | null;
  sources: string[];
  nb_sources: number;
  accord: "accord" | "partiel" | "desaccord" | null;
  cotes_bookmakers: Record<string, number>;
  raisons: string[];
  prudence: string[];
  // Liste du jour uniquement
  course_id?: string;
  code?: string | null;
  hippodrome?: string | null;
  depart?: string;
};

const fr1 = (x: number) => x.toLocaleString("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const pctSigne = (x: number) => `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.round(Math.abs(x) * 100)} %`;

const NIVEAU: Record<string, { l: string; cls: string }> = {
  fort: { l: "PMU paie nettement plus", cls: "bg-emerald-600 text-white" },
  net: { l: "PMU paie plus", cls: "bg-emerald-100 text-emerald-800" },
  a_confirmer: { l: "À confirmer", cls: "bg-stone-100 text-stone-700" },
  defavorable: { l: "PMU paie moins", cls: "bg-rose-100 text-rose-800" },
};

function Badge({ niveau }: { niveau: Ecart["niveau"] }) {
  if (!niveau) return null;
  const n = NIVEAU[niveau];
  return <span className={cn("whitespace-nowrap rounded-full px-2 py-0.5 text-[10.5px] font-semibold", n.cls)}>{n.l}</span>;
}

/** Une ligne dépliable : chiffres en tête, raisons et prudence au clic. */
function LigneEcart({ e, avecCourse }: { e: Ecart; avecCourse?: boolean }) {
  const [ouvert, setOuvert] = useState(false);
  const positif = e.ecart > 0;
  return (
    <li className="py-3">
      <button
        type="button"
        onClick={() => setOuvert((o) => !o)}
        aria-expanded={ouvert}
        className="flex w-full items-start gap-3 text-left"
      >
        <span className="mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-stone-900 text-xs font-bold tabular-nums text-white">
          {e.numero}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="truncate text-sm font-semibold text-stone-900">{e.nom ? titleCase(e.nom) : `N° ${e.numero}`}</span>
            <Badge niveau={e.niveau} />
          </span>
          {avecCourse && e.course_id && (
            <span className="mt-0.5 block text-[11.5px] text-stone-500">
              {e.depart ? `${heureParis(e.depart)} · ` : ""}{e.code ?? ""} {e.hippodrome ? titleCase(e.hippodrome) : ""}
            </span>
          )}
          <span className="mt-1 block text-[12.5px] text-stone-600">
            PMU <b className="tabular-nums text-stone-900">{fr1(e.cote_pmu)}</b>
            {" · "}prix juste bookmakers <b className="tabular-nums text-stone-900">{fr1(e.cote_juste_bookmakers)}</b>
          </span>
        </span>
        <span className={cn("flex shrink-0 items-center gap-0.5 text-sm font-bold tabular-nums",
          positif ? "text-emerald-700" : "text-rose-700")}>
          {positif ? <ArrowUpRight className="h-4 w-4" aria-hidden="true" /> : <ArrowDownRight className="h-4 w-4" aria-hidden="true" />}
          {pctSigne(e.ecart)}
        </span>
        <ChevronDown className={cn("mt-1 h-4 w-4 shrink-0 text-stone-400 transition-transform", ouvert && "rotate-180")} aria-hidden="true" />
      </button>
      {ouvert && (
        <div className="mt-2 space-y-2 pl-10 text-[12.5px] leading-relaxed">
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(e.cotes_bookmakers).map(([s, c]) => (
              <span key={s} className="rounded-md bg-stone-100 px-1.5 py-0.5 text-[11px] text-stone-600">
                {s} <b className="tabular-nums text-stone-800">{fr1(c)}</b>
              </span>
            ))}
          </div>
          <ul className="list-disc space-y-1 pl-4 text-stone-700">
            {e.raisons.map((r) => <li key={r}>{r}</li>)}
          </ul>
          {e.prudence.length > 0 && (
            <ul className="space-y-1 text-amber-800">
              {e.prudence.map((r) => (
                <li key={r} className="flex gap-1.5"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />{r}</li>
              ))}
            </ul>
          )}
          {avecCourse && e.course_id && (
            <Link href={`/courses/${e.course_id}#marche`} className="inline-block text-xs font-semibold text-stone-900 underline underline-offset-2">
              Voir la course
            </Link>
          )}
        </div>
      )}
    </li>
  );
}

const EXPLICATION =
  "Vous jouez au PMU : quand sa cote est plus haute que le prix juste des bookmakers (Unibet, Bet365, Ladbrokes, Betfair, marge retirée), vous gagnez plus à mise égale. Plus basse, vous gagnez moins.";

/** Carte de la page course (onglet Marché). Rien si aucune source bookmaker. */
export function EcartsCotesCourse({ courseId, terminee }: { courseId: string; terminee?: boolean }) {
  const { data } = useSWR<{ ecarts: Ecart[] }>(
    ["ecarts-cotes", courseId],
    () => coursesApi.ecartsCotes(courseId).then((r) => r.data),
    { refreshInterval: terminee ? 0 : 60_000, revalidateOnFocus: !terminee, shouldRetryOnError: false },
  );
  const [voirMoins, setVoirMoins] = useState(false);
  const ecarts = data?.ecarts ?? [];
  if (ecarts.length === 0) return null;
  const plus = ecarts.filter((e) => e.niveau === "fort" || e.niveau === "net" || e.niveau === "a_confirmer");
  const moins = ecarts.filter((e) => e.niveau === "defavorable").sort((a, b) => a.ecart - b.ecart);
  return (
    <section aria-label="Écarts PMU et bookmakers" className="rounded-2xl bg-white p-4 ring-1 ring-stone-200 sm:p-5">
      <div className="flex items-center gap-2">
        <Scale className="h-4 w-4 text-stone-500" aria-hidden="true" />
        <h3 className="text-[15px] font-bold text-stone-800">Le PMU paie-t-il plus que les bookmakers&nbsp;?</h3>
      </div>
      <p className="mt-1.5 text-[12.5px] leading-relaxed text-stone-500">
        {EXPLICATION}{terminee ? " Cotes finales de la course." : ""}
      </p>
      {plus.length > 0 ? (
        <ul className="mt-2 divide-y divide-stone-100">
          {plus.map((e) => <LigneEcart key={e.numero} e={e} />)}
        </ul>
      ) : (
        <p className="mt-3 text-[12.5px] text-stone-600">Aucun cheval n&apos;est mieux payé au PMU que chez les bookmakers sur cette course.</p>
      )}
      {moins.length > 0 && (
        <div className="mt-2 border-t border-stone-100 pt-2">
          <button type="button" onClick={() => setVoirMoins((v) => !v)} aria-expanded={voirMoins}
            className="flex w-full items-center gap-1.5 text-left text-[12.5px] font-semibold text-rose-800">
            {moins.length} cheval{moins.length > 1 ? "x" : ""} moins bien payé{moins.length > 1 ? "s" : ""} au PMU
            <ChevronDown className={cn("h-4 w-4 transition-transform", voirMoins && "rotate-180")} aria-hidden="true" />
          </button>
          {voirMoins && <ul className="divide-y divide-stone-100">{moins.map((e) => <LigneEcart key={e.numero} e={e} />)}</ul>}
        </div>
      )}
      <p className="mt-3 text-[11px] leading-relaxed text-stone-400">
        Un écart se vérifie sur la durée, jamais sur un pari isolé. Pariez de façon responsable.
      </p>
    </section>
  );
}

/** Liste du jour : les plus grands écarts en faveur du PMU, courses à venir. */
export function EcartsCotesJour({ max = 12 }: { max?: number }) {
  const { data, isLoading } = useSWR<{ ecarts: Ecart[] }>(
    "ecarts-cotes-jour",
    () => coursesApi.ecartsCotesJour().then((r) => r.data),
    { refreshInterval: 120_000, shouldRetryOnError: false },
  );
  const [tout, setTout] = useState(false);
  const lignes = data?.ecarts ?? [];
  const visibles = tout ? lignes : lignes.slice(0, max);
  return (
    <section aria-label="Écarts PMU et bookmakers du jour" className="esp-panneau rounded-3xl p-4 sm:p-6">
      <div className="flex items-center gap-2">
        <Scale className="h-4 w-4 text-stone-500" aria-hidden="true" />
        <h3 className="text-base font-semibold text-stone-900">Mieux payés au PMU que chez les bookmakers</h3>
      </div>
      <p className="mt-1.5 max-w-3xl text-[13px] leading-relaxed text-stone-500">{EXPLICATION} Calcul sur les cotes du marché, indépendant de notre pronostic.</p>
      {isLoading ? (
        <div className="mt-4 h-24 animate-pulse rounded-2xl bg-stone-100" aria-busy="true" />
      ) : lignes.length === 0 ? (
        <p className="mt-4 text-[13px] text-stone-600">Aucun écart net pour les courses à venir aujourd&apos;hui.</p>
      ) : (
        <>
          <ul className="mt-2 divide-y divide-stone-100">
            {visibles.map((e) => <LigneEcart key={`${e.course_id}-${e.numero}`} e={e} avecCourse />)}
          </ul>
          {lignes.length > max && (
            <button type="button" onClick={() => setTout((t) => !t)} className="mt-2 text-xs font-semibold text-stone-700 hover:text-stone-900">
              {tout ? "Réduire" : `Voir les ${lignes.length} écarts`}
            </button>
          )}
        </>
      )}
    </section>
  );
}
