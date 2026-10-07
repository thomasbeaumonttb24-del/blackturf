"use client";

/**
 * Outsiders du jour — les grosses cotes (≥ 15) que le cerveau des outsiders
 * (backend `ml/outsider_brain.py`) juge capables de se placer.
 *
 * Honnêteté : on affiche une CHANCE DE PLACE estimée et le bilan réel des
 * outsiders affichés (figés à T-10). Jamais de promesse de gain : mesuré, ces
 * outsiders se placent 2 à 3 fois plus souvent que les autres, sans rendement
 * positif prouvé.
 */

import useSWR from "swr";
import Link from "next/link";
import { ArrowRight, Flame, Lock, Rocket, Sparkles, Target, Trophy } from "lucide-react";
import { outsidersApi } from "@/lib/api";

export interface Outsider {
  course_id: string;
  code: string;
  hippodrome: string | null;
  discipline: string | null;
  date_heure: string | null;
  est_quinte: boolean;
  numero: number | null;
  nom_cheval: string | null;
  cote_signal: number | null;
  cote_actuelle: number | null;
  chance_place: number | null;
  niveau: "fort" | "a_suivre";
  places_payees: number;
  raisons: string[];
  non_partant: boolean;
  termine: boolean;
  position: number | null;
  place: boolean | null;
  gagne: boolean | null;
  rapport_place: number | null;
  rapport_gagnant: number | null;
  verrouille: boolean;
}

interface JourResp {
  jour: string;
  acces_complet: boolean;
  outsiders: Outsider[];
}

interface BilanResp {
  jours: number;
  n: number;
  places: number;
  gagnes: number;
  taux_place: number | null;
  rendement_simple_place: number | null;
  par_niveau: Record<string, { n: number; places: number; taux_place: number | null }>;
  plus_beaux: Outsider[];
  validation: {
    entraine_le?: string;
    place_outsiders?: number;
    sel_a_suivre?: { n: number; places: number | null; par_jour: number };
    sel_fort?: { n: number; places: number | null; par_jour: number };
  } | null;
}

const pct = (v: number | null | undefined, d = 0) =>
  v == null ? "—" : `${(v * 100).toFixed(d).replace(".", ",")} %`;
const cote = (v: number | null | undefined) => (v == null ? "—" : v.toFixed(v < 10 ? 1 : 0).replace(".", ","));
const heure = (iso: string | null) =>
  iso ? new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Paris" }) : "";
const titre = (s: string | null) =>
  (s ?? "").toLowerCase().replace(/(^|[\s-])\p{L}/gu, (m) => m.toUpperCase());

export function useOutsidersJour() {
  return useSWR<JourResp>("outsiders-jour", () => outsidersApi.jour().then((r) => r.data), {
    refreshInterval: 120_000,
    revalidateOnFocus: true,
  });
}

export function useOutsidersBilan(jours = 30) {
  return useSWR<BilanResp>(`outsiders-bilan-${jours}`, () => outsidersApi.bilan(jours).then((r) => r.data), {
    refreshInterval: 300_000,
  });
}

function Badge({ o }: { o: Outsider }) {
  if (o.niveau === "fort")
    return (
      <span className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full bg-rose-50 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-rose-700 ring-1 ring-rose-200">
        <Flame className="h-3 w-3" aria-hidden /> Outsider fort
      </span>
    );
  return (
    <span className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-amber-800 ring-1 ring-amber-200">
      <Target className="h-3 w-3" aria-hidden /> À suivre
    </span>
  );
}

function Resultat({ o }: { o: Outsider }) {
  if (o.non_partant) return <span className="text-xs font-semibold text-gray-400">Non-partant</span>;
  if (!o.termine) return null;
  if (o.gagne)
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-emerald-600 px-2 py-0.5 text-xs font-bold text-white">
        <Trophy className="h-3 w-3" aria-hidden /> Gagnant{o.rapport_gagnant ? ` · ${cote(o.rapport_gagnant)} €` : ""}
      </span>
    );
  if (o.place)
    return (
      <span className="rounded-md bg-emerald-100 px-2 py-0.5 text-xs font-bold text-emerald-800">
        {o.position}e · placé{o.rapport_place ? ` ${o.rapport_place.toFixed(2).replace(".", ",")} €` : ""}
      </span>
    );
  return (
    <span className="rounded-md bg-gray-100 px-2 py-0.5 text-xs font-semibold text-gray-500">
      {o.position ? `${o.position}e` : "Non placé"}
    </span>
  );
}

export function OutsiderCarte({ o, compact = false }: { o: Outsider; compact?: boolean }) {
  const contenu = (
    <div
      className={`group relative h-full rounded-2xl border bg-white p-4 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md ${
        o.niveau === "fort" ? "border-rose-200" : "border-amber-200"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">
            {o.code} · {titre(o.hippodrome)} · {heure(o.date_heure)}
            {o.est_quinte ? " · Quinté+" : ""}
          </p>
          {o.verrouille ? (
            <p className="mt-1 flex items-center gap-1.5 font-display text-lg font-bold text-gray-400">
              <Lock className="h-4 w-4" aria-hidden /> Cheval réservé aux abonnés
            </p>
          ) : (
            <p className="mt-1 truncate font-display text-lg font-bold text-gray-900">
              <span className="mr-1.5 inline-flex h-6 min-w-6 items-center justify-center rounded-md bg-gray-900 px-1.5 text-sm text-white">
                {o.numero}
              </span>
              {titre(o.nom_cheval)}
            </p>
          )}
        </div>
        <Badge o={o} />
      </div>

      <div className="mt-3 flex items-end justify-between gap-3">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-gray-500">Cote</p>
          <p className="font-display text-2xl font-extrabold text-gray-900">
            {o.verrouille ? "15+" : cote(o.cote_actuelle ?? o.cote_signal)}
          </p>
        </div>
        <div className="text-right">
          <p className="text-[11px] uppercase tracking-wide text-gray-500">
            Chance de finir dans les {o.places_payees}
          </p>
          <p className={`font-display text-2xl font-extrabold ${o.niveau === "fort" ? "text-rose-600" : "text-amber-600"}`}>
            {o.verrouille ? "?" : pct(o.chance_place)}
          </p>
        </div>
      </div>

      {!compact && o.raisons.length > 0 && (
        <ul className="mt-3 space-y-1 border-t border-gray-100 pt-3">
          {o.raisons.map((r) => (
            <li key={r} className="flex gap-2 text-[13px] leading-5 text-gray-700">
              <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" aria-hidden />
              {r}
            </li>
          ))}
        </ul>
      )}
      <div className="mt-3 flex items-center justify-between">
        <Resultat o={o} />
        <span className="ml-auto inline-flex items-center gap-1 text-xs font-semibold text-gray-500 group-hover:text-gray-900">
          Voir la course <ArrowRight className="h-3 w-3" aria-hidden />
        </span>
      </div>
    </div>
  );
  return (
    <Link href={`/courses/${o.course_id}`} className="block h-full" aria-label={`Course ${o.code}`}>
      {contenu}
    </Link>
  );
}

/** Ligne « preuve » : taux réel des outsiders affichés sur 30 jours (ou validation). */
export function PreuveOutsiders({ bilan }: { bilan?: BilanResp }) {
  if (!bilan) return null;
  if (bilan.n >= 30 && bilan.taux_place != null) {
    return (
      <p className="text-sm text-gray-600">
        Sur {bilan.jours} jours : <strong className="text-gray-900">{bilan.places} outsiders placés sur {bilan.n}</strong>{" "}
        ({pct(bilan.taux_place)}), dont {bilan.gagnes} gagnant{bilan.gagnes > 1 ? "s" : ""}.
      </p>
    );
  }
  const v = bilan.validation;
  if (v?.sel_a_suivre?.places != null && v.place_outsiders != null) {
    return (
      <p className="text-sm text-gray-600">
        Testé sur 2 semaines de courses jamais vues : les outsiders retenus se sont placés{" "}
        <strong className="text-gray-900">{pct(v.sel_a_suivre.places)}</strong> du temps, contre{" "}
        {pct(v.place_outsiders)} pour un outsider moyen.
      </p>
    );
  }
  return null;
}

/** Bloc compact (accueil, programme). */
export function OutsidersDuJour({ titreNiveau = "h2", max = 6 }: { titreNiveau?: "h2" | "h3"; max?: number }) {
  const { data, isLoading } = useOutsidersJour();
  const { data: bilan } = useOutsidersBilan(30);
  const liste = (data?.outsiders ?? []).filter((o) => !o.non_partant);
  const aVenir = liste.filter((o) => !o.termine);
  const montres = [...aVenir, ...liste.filter((o) => o.termine)].slice(0, max);
  const H = titreNiveau;

  if (!isLoading && liste.length === 0) return null;

  return (
    <div>
      <div className="mb-5 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <span className="inline-flex items-center gap-2 rounded-full bg-rose-100/70 px-3 py-1 text-[11px] font-bold uppercase tracking-[0.16em] text-rose-800 ring-1 ring-rose-200">
            <Rocket className="h-3.5 w-3.5" aria-hidden /> Outsiders du jour
          </span>
          <H className="mt-2 font-display text-2xl font-extrabold tracking-tight text-gray-900 sm:text-3xl">
            Les grosses cotes capables de se placer
          </H>
          <p className="mt-1 max-w-2xl text-sm text-gray-600">
            Cotes à 15 et plus que notre cerveau des outsiders juge sous-estimées, avec leur chance estimée de
            finir dans les places. {aVenir.length > 0 ? `${aVenir.length} encore à courir aujourd'hui.` : ""}
          </p>
          <div className="mt-1">
            <PreuveOutsiders bilan={bilan} />
          </div>
        </div>
        <Link
          href="/outsiders"
          className="inline-flex shrink-0 items-center gap-1.5 rounded-xl bg-gray-900 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-800"
        >
          Tous les outsiders <ArrowRight className="h-4 w-4" aria-hidden />
        </Link>
      </div>
      {isLoading ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-36 animate-pulse rounded-2xl bg-gray-100" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {montres.map((o) => (
            <OutsiderCarte key={`${o.course_id}-${o.numero ?? o.code}-${o.chance_place}`} o={o} compact />
          ))}
        </div>
      )}
      {data && !data.acces_complet && aVenir.length > 0 && (
        <p className="mt-4 text-sm text-gray-600">
          <Lock className="mr-1 inline h-3.5 w-3.5" aria-hidden />
          Le nom, la cote et les raisons des outsiders à venir sont réservés aux abonnés.{" "}
          <Link href="/tarifs" className="font-semibold text-gray-900 underline underline-offset-2">
            Voir les formules
          </Link>
        </p>
      )}
    </div>
  );
}

/** Encart de la fiche course : les outsiders repérés dans CETTE course. */
export function OutsidersCourse({ courseId }: { courseId: string }) {
  const { data } = useSWR<{ acces_complet: boolean; outsiders: Outsider[] }>(
    `outsiders-course-${courseId}`,
    () => outsidersApi.course(courseId).then((r) => r.data),
    { refreshInterval: 120_000 },
  );
  const liste = (data?.outsiders ?? []).filter((o) => !o.non_partant);
  if (liste.length === 0) return null;
  return (
    <section className="rounded-2xl border border-rose-200 bg-gradient-to-br from-rose-50 to-white p-4 sm:p-5">
      <h2 className="flex items-center gap-2 font-display text-lg font-bold text-gray-900">
        <Rocket className="h-5 w-5 text-rose-600" aria-hidden />
        {liste.length > 1 ? "Outsiders repérés dans cette course" : "Outsider repéré dans cette course"}
      </h2>
      <p className="mt-1 text-sm text-gray-600">
        Cote 15 ou plus, que le cerveau des outsiders juge capable de finir dans les {liste[0].places_payees}.
      </p>
      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
        {liste.map((o) => (
          <OutsiderCarte key={`${o.numero ?? "x"}-${o.chance_place}`} o={o} />
        ))}
      </div>
      {data && !data.acces_complet && !liste[0].termine && (
        <Link href="/tarifs" className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-rose-700 underline underline-offset-2">
          Débloquer le nom et les raisons <ArrowRight className="h-3.5 w-3.5" aria-hidden />
        </Link>
      )}
    </section>
  );
}

/** Page complète /outsiders. */
export function OutsidersPage() {
  const { data, isLoading } = useOutsidersJour();
  const { data: bilan } = useOutsidersBilan(30);
  const liste = (data?.outsiders ?? []).filter((o) => !o.non_partant);
  const aVenir = liste.filter((o) => !o.termine);
  const finis = liste.filter((o) => o.termine);
  const v = bilan?.validation;

  return (
    <div className="space-y-12">
      <section>
        <h2 className="font-display text-2xl font-bold text-gray-900">À courir aujourd&apos;hui</h2>
        {isLoading ? (
          <div className="mt-4 h-40 animate-pulse rounded-2xl bg-gray-100" />
        ) : aVenir.length === 0 ? (
          <p className="mt-3 text-gray-600">
            Aucun outsider retenu pour les courses restantes. Le cerveau ne force jamais : pas de grosse cote
            assez solide, pas de signal.
          </p>
        ) : (
          <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
            {aVenir.map((o) => (
              <OutsiderCarte key={`${o.course_id}-${o.numero ?? o.chance_place}`} o={o} />
            ))}
          </div>
        )}
        {data && !data.acces_complet && aVenir.length > 0 && (
          <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-gray-700">
            <Lock className="mr-1 inline h-4 w-4" aria-hidden /> Le nom, la cote et les raisons des outsiders à
            venir sont réservés aux abonnés.{" "}
            <Link href="/tarifs" className="font-semibold text-gray-900 underline underline-offset-2">
              Voir les formules
            </Link>
          </div>
        )}
      </section>

      {finis.length > 0 && (
        <section>
          <h2 className="font-display text-2xl font-bold text-gray-900">Déjà courus aujourd&apos;hui</h2>
          <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
            {finis.map((o) => (
              <OutsiderCarte key={`${o.course_id}-${o.numero}`} o={o} />
            ))}
          </div>
        </section>
      )}

      <section>
        <h2 className="font-display text-2xl font-bold text-gray-900">Le bilan réel, sans filtre</h2>
        <p className="mt-1 text-sm text-gray-600">
          Chaque outsider est figé 10 minutes avant le départ. Le bilan compte tous ceux affichés, placés ou
          non.
        </p>
        {bilan && bilan.n > 0 ? (
          <>
            <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                { l: "outsiders affichés", v: String(bilan.n) },
                { l: "se sont placés", v: `${bilan.places} (${pct(bilan.taux_place)})` },
                { l: "ont gagné", v: String(bilan.gagnes) },
                {
                  l: "« Outsider fort » placés",
                  v: pct(bilan.par_niveau?.fort?.taux_place),
                },
              ].map((k) => (
                <div key={k.l} className="rounded-2xl border border-gray-200 bg-white p-4">
                  <p className="font-display text-xl font-extrabold text-gray-900">{k.v}</p>
                  <p className="text-xs text-gray-500">{k.l}</p>
                </div>
              ))}
            </div>
            {bilan.plus_beaux.length > 0 && (
              <>
                <h3 className="mt-6 font-display text-lg font-bold text-gray-900">Les plus beaux coups</h3>
                <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                  {bilan.plus_beaux.map((o) => (
                    <OutsiderCarte key={`${o.course_id}-${o.numero}`} o={o} compact />
                  ))}
                </div>
              </>
            )}
          </>
        ) : (
          <p className="mt-3 text-gray-600">Le bilan se remplit au fil des courses.</p>
        )}
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white p-5 sm:p-6">
        <h2 className="font-display text-2xl font-bold text-gray-900">Comment le cerveau repère un outsider</h2>
        <div className="mt-3 space-y-3 text-[15px] leading-7 text-gray-700">
          <p>
            Un modèle dédié, entraîné chaque nuit uniquement sur les chevaux cotés 10 ou plus, estime la chance de
            finir dans les places payées (les 3 premiers, les 2 premiers à 7 partants ou moins). Il lit, tels
            qu&apos;ils étaient avant le départ :
          </p>
          <ul className="list-disc space-y-1 pl-5">
            <li>
              <strong>Le marché au-delà du PMU</strong> : un cheval coté 25 au PMU mais 14 chez les bookmakers ou
              sur Betfair est sous-coté au PMU.
            </li>
            <li>
              <strong>L&apos;argent qui arrive</strong> : un outsider dont la cote baisse depuis le matin est joué.
            </li>
            <li>
              <strong>Sa valeur propre</strong> : forme, niveau (ELO), gains, jockey, entraîneur, terrain,
              distance, ferrure, presse.
            </li>
            <li>
              <strong>Notre pronostic général</strong>, et sa place parmi les autres outsiders de la course.
            </li>
          </ul>
          <p>
            Il ne retient que les cotes à 15 et plus dont la chance de place atteint 22 % (« À suivre »), ou 28 %
            (« Outsider fort »), au plus deux par course. Il est remis en service chaque nuit seulement s&apos;il
            fait au moins aussi bien que notre modèle général sur deux semaines de courses jamais vues.
          </p>
          {v?.sel_a_suivre?.places != null && v.place_outsiders != null && (
            <p className="rounded-xl bg-gray-50 p-3 text-sm">
              Dernier test sur courses jamais vues : retenus placés <strong>{pct(v.sel_a_suivre.places)}</strong>
              {v.sel_fort?.places != null && (
                <>
                  , « Outsider fort » <strong>{pct(v.sel_fort.places)}</strong>
                </>
              )}
              , contre {pct(v.place_outsiders)} pour un outsider moyen.
            </p>
          )}
          <p className="text-sm text-gray-500">
            Soyons clairs : un outsider reste un outsider. Même bien choisis, la plupart ne se placent pas, et
            les jouer systématiquement ne garantit aucun gain. C&apos;est un repérage, pas une promesse.
          </p>
        </div>
      </section>
    </div>
  );
}
