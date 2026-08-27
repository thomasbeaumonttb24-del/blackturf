"use client";

/**
 * Classement de l'algorithme — la table centrale de la fiche course.
 *
 * Règle de fond : **rien d'affiché ici n'est décoratif ou reconstitué côté
 * client**. Chaque colonne vient d'un champ renvoyé par l'API et disparaît quand
 * ce champ est absent :
 *
 *   rang, probabilités, intervalle, cote figée, cote juste  → /predictions
 *   cote marché (live si dispo, sinon cote figée du prono)  → /courses/{id}/cotes-live
 *   signaux (atout / réserve / vigilance)                   → /courses/{id}/analyse
 *   position réelle                                          → /courses/{id}/resultats
 *
 * Aucun repli « plausible » : pas de cote juste recalculée à la volée, pas de
 * signal générique quand l'analyse n'en donne pas.
 *
 * Les seuls calculs faits ici sont des RESTITUTIONS de ces champs — une somme de
 * probabilités affichées, un écart entre deux cotes affichées, le rang du modèle
 * rapproché de l'arrivée réelle. Jamais une appréciation inventée.
 */

import { useEffect, useState } from "react";
import { ChevronDown, HelpCircle, Lock, TrendingUp, Clock3, Trophy } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ApercuAnalyse } from "@/components/courses/insights";

export interface ClassementPrediction {
  prediction_id: string;
  numero: number;
  nom_cheval: string;
  proba_top1: number;
  proba_top3: number;
  proba_top1_low: number | null;
  proba_top1_high: number | null;
  rang_predit: number;
  confidence_score: number | null;
  cote_pmu: number | null;
  /** Cote de marché relevée au moment du pronostic (peut différer de `cote_pmu`). */
  cote_figee?: number | null;
  cote_juste: number | null;
  value_bet: { ev_max: number; niveau: number; meilleure_source: string } | null;
}

export interface ClassementSignal {
  label: string;
  detail: string;
  sens: "positif" | "negatif" | "neutre";
  score: number;
}

/** Probabilité en pourcentage. Sous 0,5 %, on écrit « < 1 % » : arrondir à
 *  « 0 % » un cheval que le modèle chiffre à 0,3 % se lit comme un bug — et
 *  affirme une impossibilité que le modèle n'a jamais écrite. Mesuré en prod :
 *  ~8 % des cellules top-3 et ~11 % des cellules victoire tombaient dans ce cas. */
const pct = (x: number | null | undefined) =>
  x == null ? "—" : x < 0.005 ? "< 1 %" : `${Math.round(x * 100)} %`;

const cote = (x: number) => x.toLocaleString("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

const ordinal = (n: number) => `${n}${n === 1 ? "er" : "e"}`;

/** Retire les puces / emojis en tête de libellé renvoyés par l'analyse. */
const nettoie = (s: string) => s.replace(/^[^A-Za-zÀ-ÿ0-9]+/, "").trim();

const SENS = {
  positif: { fg: "text-emerald-700", bg: "bg-emerald-50", ring: "ring-emerald-200/70", fleche: "▲" },
  negatif: { fg: "text-rose-700", bg: "bg-rose-50", ring: "ring-rose-200/70", fleche: "▼" },
  neutre: { fg: "text-amber-800", bg: "bg-amber-50", ring: "ring-amber-200/70", fleche: "●" },
} as const;

/** Borne haute de la cote juste appliquée côté API (predictions.py). Atteinte,
 *  elle signifie « le modèle ne chiffre plus », pas « cote de 100 ». */
const COTE_JUSTE_MAX = 100;

/** Écart minimal entre la cote affichée et la cote du pronostic pour rappeler
 *  cette dernière. En dessous, le rappel n'apprend rien et alourdit la ligne. */
const ECART_RAPPEL_COTE = 0.2;

/** Préférence d'affichage des signaux, conservée d'une course à l'autre. */
const CLE_SIGNAUX = "bt.classement.signaux";

/** Gabarit de colonnes partagé par l'en-tête et les lignes : une seule source,
 *  sinon les deux dérivent au premier ajustement. */
const COLS = {
  avecJuste: "sm:grid-cols-[40px_minmax(0,1fr)_74px_74px_104px_196px]",
  sansJuste: "sm:grid-cols-[40px_minmax(0,1fr)_74px_196px]",
} as const;

/* ────────────────────────────────────────────────────────────────────────── */
/*  Briques d'affichage                                                       */
/* ────────────────────────────────────────────────────────────────────────── */

/** Identité d'un cheval : le NUMÉRO d'abord, en gros et en gras, le nom ensuite.
 *  C'est le numéro qu'on coche sur un ticket, qu'annonce le commentaire de course
 *  et qu'on relit dans l'arrivée officielle ; le nom sert à reconnaître le cheval,
 *  pas à jouer. Une seule fabrique pour les quatre endroits où la paire apparaît,
 *  sinon les tailles dérivent au premier ajustement. */
function Identite({ numero, nom, taille = "normal", terne }: {
  numero: number;
  nom: string;
  taille?: "normal" | "grand";
  terne?: boolean;
}) {
  return (
    <span className="flex min-w-0 items-baseline gap-1.5">
      <span className={cn(
        "font-display font-bold tabular-nums",
        taille === "grand" ? "text-[16px]" : "text-[15px]",
        terne ? "text-stone-600" : "text-slate-900",
      )}>
        N°{numero}
      </span>
      <span className={cn("truncate", taille === "grand" ? "text-[13px]" : "text-[12.5px]", terne ? "text-stone-600" : "text-stone-700")}>
        {nom}
      </span>
    </span>
  );
}

/** Pastille de rang. Le dégradé de traitement (or → gris → contour seul) rend le
 *  podium du modèle lisible d'un coup d'œil, sans texte supplémentaire. */
function Rang({ rang, absent }: { rang: number; absent?: boolean }) {
  const fav = rang === 1;
  const podium = rang <= 3;
  return (
    <span
      className={cn(
        "flex h-8 w-8 items-center justify-center rounded-xl font-display text-[13px] font-bold tabular-nums ring-1 transition-colors",
        absent ? "bg-stone-50 text-stone-600 ring-stone-200"
          : fav ? "bg-amber-100 text-amber-900 ring-amber-300 shadow-[0_1px_0_rgba(180,120,20,.18)]"
          : podium ? "bg-slate-100 text-slate-700 ring-slate-200"
          : "bg-white text-stone-600 ring-stone-200",
      )}
    >
      {rang}
    </span>
  );
}

/** Barre de probabilité à échelle ABSOLUE (0–100 %), avec repères à 25/50/75 %.
 *  Une échelle relative au mieux noté donnerait une barre pleine à 22 % — plus
 *  jolie, mais fausse. Les repères suffisent à rendre lisibles les petites
 *  valeurs. La fourchette du modèle est dessinée en surimpression : c'est une
 *  donnée renvoyée par l'API, pas une marge décorative. */
function BarreProba({
  p, low, high, ton,
}: {
  p: number;
  low: number | null;
  high: number | null;
  ton: "or" | "podium" | "neutre";
}) {
  const w = Math.max(1.5, Math.min(100, p * 100));
  const aFourchette = low != null && high != null && high > low;
  const l = aFourchette ? Math.max(0, Math.min(100, low! * 100)) : 0;
  const h = aFourchette ? Math.max(0, Math.min(100, high! * 100)) : 0;

  return (
    <div className="relative h-2 w-full overflow-hidden rounded-full bg-stone-100">
      {/* Repères 25 / 50 / 75 % — donnent l'échelle sans axe ni chiffres */}
      {[25, 50, 75].map((t) => (
        <span key={t} className="absolute top-0 h-full w-px bg-white/90" style={{ left: `${t}%` }} aria-hidden="true" />
      ))}
      {aFourchette && (
        <span
          className={cn(
            "absolute top-0 h-full rounded-full",
            ton === "or" ? "bg-amber-200" : ton === "podium" ? "bg-slate-300" : "bg-stone-200",
          )}
          style={{ left: `${l}%`, width: `${Math.max(0.8, h - l)}%` }}
          aria-hidden="true"
        />
      )}
      <span
        className={cn(
          "absolute top-0 h-full rounded-full",
          ton === "or" ? "bg-amber-500" : ton === "podium" ? "bg-slate-500" : "bg-stone-400",
        )}
        style={{ width: `${w}%` }}
        aria-hidden="true"
      />
    </div>
  );
}

/** Lecture du prix : écart entre la cote payée par le marché et la cote juste du
 *  modèle. C'est le cœur du produit — jusqu'ici le lecteur devait le calculer de
 *  tête en comparant deux colonnes de chiffres.
 *
 *  Le pourcentage est l'écart relatif entre les deux cotes AFFICHÉES, rien de
 *  plus. Il ne remplace pas l'espérance de gain du modèle (badge « valeur »),
 *  qui, elle, tient compte de la calibration et des garde-fous. */
function LecturePrix({ marche, juste }: { marche: number | null; juste: number | null }) {
  if (marche == null || juste == null || juste <= 0) {
    return <span className="text-[13px] text-stone-300">—</span>;
  }
  // La cote juste est bornée à 100 côté API. Sur un cheval que le modèle chiffre
  // sous 1 %, la borne est ATTEINTE : comparer une cote de 242 à ce plafond
  // produisait un « +142 % » qui annonce une aubaine là où le modèle dit seulement
  // qu'il ne sait plus fixer de prix. On ne chiffre pas un écart contre une borne.
  if (juste >= COTE_JUSTE_MAX) {
    return (
      <span
        title="Le modèle chiffre ce cheval en dessous du seuil où sa cote juste reste mesurable (plafonnée à 100) : l'écart au marché n'a pas de sens ici."
        className="text-[11px] text-stone-600"
      >
        non chiffrable
      </span>
    );
  }
  const ecart = marche / juste - 1;
  const abs = Math.abs(Math.round(ecart * 100));
  if (abs < 8) {
    return (
      <span
        title={`Le marché paie ${cote(marche)}, le modèle estime la cote juste à ${cote(juste)} : prix conforme.`}
        className="inline-flex items-center rounded-md bg-stone-100 px-1.5 py-0.5 text-[10.5px] font-semibold text-stone-600"
      >
        au prix
      </span>
    );
  }
  const genereux = ecart > 0;
  return (
    <span
      title={
        genereux
          ? `Le marché paie ${cote(marche)} pour une cote juste estimée à ${cote(juste)} : ${abs} % au-dessus.`
          : `Le marché ne paie que ${cote(marche)} pour une cote juste estimée à ${cote(juste)} : ${abs} % en dessous du prix qui couvrirait le risque.`
      }
      className={cn(
        "inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-[10.5px] font-bold tabular-nums ring-1",
        genereux ? "bg-emerald-50 text-emerald-700 ring-emerald-200/70" : "bg-rose-50 text-rose-700 ring-rose-200/70",
      )}
    >
      {genereux ? "+" : "−"}{abs} %
    </span>
  );
}

function BadgeValeur({ ev, niveau }: { ev: number; niveau: number }) {
  return (
    <span
      title={`Espérance de gain ${ev > 0 ? "+" : ""}${Math.round(ev * 100)} % — signal de valeur niveau ${niveau}/4 retenu par le modèle`}
      className="inline-flex shrink-0 items-center gap-1 rounded-md bg-emerald-600 px-1.5 py-0.5 text-[10px] font-bold tabular-nums text-white"
    >
      <TrendingUp className="h-3 w-3" aria-hidden="true" />
      {ev > 0 ? "+" : ""}{Math.round(ev * 100)} %
    </span>
  );
}

function BadgeArrivee({ position }: { position: number }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-bold tabular-nums ring-1",
        position === 1 ? "bg-amber-100 text-amber-900 ring-amber-300"
          : position <= 3 ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
          : "bg-stone-100 text-slate-600 ring-stone-200",
      )}
      title="Position réelle à l'arrivée"
    >
      {position === 1 && <Trophy className="h-2.5 w-2.5" aria-hidden="true" />}
      {ordinal(position)}
    </span>
  );
}

/** Signaux d'un cheval — volontairement DISCRETS.
 *  Les pastilles pleines (fond vert / rouge) répétées sur huit lignes noyaient
 *  les colonnes chiffrées, qui sont l'information de décision. Le texte reste
 *  intégral ; seule la couleur est ramenée à la flèche, et deux signaux
 *  s'affichent — le reste tient derrière le compteur. */
function Signaux({ signaux }: { signaux: ClassementSignal[] }) {
  const [ouvert, setOuvert] = useState(false);
  if (!signaux.length) return null;
  const visibles = ouvert ? signaux : signaux.slice(0, 2);
  const reste = signaux.length - visibles.length;

  return (
    <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10.5px] leading-tight text-stone-600">
      {visibles.map((s, i) => {
        const st = SENS[s.sens] ?? SENS.neutre;
        return (
          <span key={`${s.label}-${i}`} title={s.detail || undefined} className="inline-flex cursor-help items-center gap-1">
            <span className={cn("text-[7px]", st.fg)} aria-hidden="true">{st.fleche}</span>
            {nettoie(s.label)}
          </span>
        );
      })}
      {reste > 0 && (
        <button
          type="button"
          onClick={() => setOuvert(true)}
          className="font-semibold text-stone-500 underline decoration-dotted underline-offset-2 transition-colors hover:text-slate-700"
        >
          +{reste}
        </button>
      )}
      {ouvert && signaux.length > 2 && (
        <button
          type="button"
          onClick={() => setOuvert(false)}
          className="text-stone-500 underline decoration-dotted underline-offset-2 transition-colors hover:text-slate-700"
        >
          réduire
        </button>
      )}
    </div>
  );
}

/** Bandeau de synthèse. Chaque chiffre est une restitution directe des lignes
 *  affichées (somme, écart, rapprochement avec l'arrivée) — jamais un jugement
 *  ajouté par l'interface. */
function Synthese({
  lignes, positionsReelles, calculeA, cotesFigees,
}: {
  lignes: ClassementPrediction[];
  positionsReelles?: Record<number, number>;
  calculeA?: string | null;
  cotesFigees?: boolean;
}) {
  const fav = lignes[0];
  const concentration = lignes.slice(0, 3).reduce((s, p) => s + p.proba_top1, 0);
  const nbValeur = lignes.filter((p) => p.value_bet).length;

  const gagnantNum = positionsReelles
    ? Number(Object.keys(positionsReelles).find((n) => positionsReelles[Number(n)] === 1))
    : NaN;
  const gagnant = Number.isFinite(gagnantNum) ? lignes.find((p) => p.numero === gagnantNum) : undefined;

  const horodatage = calculeA
    ? new Date(calculeA).toLocaleString("fr-FR", { timeZone: "Europe/Paris", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
    : null;

  return (
    <div className="grid gap-px border-b border-stone-100 bg-stone-100 sm:grid-cols-3">
      <div className="bg-white px-4 py-3 sm:px-5">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-stone-600">Favori du modèle</p>
        {fav ? (
          <p className="mt-1 flex min-w-0 items-baseline gap-1.5 truncate">
            <Identite numero={fav.numero} nom={fav.nom_cheval} taille="grand" />
            <span className="shrink-0 text-[13px] font-semibold tabular-nums text-amber-700">{pct(fav.proba_top1)}</span>
          </p>
        ) : (
          <p className="mt-1 text-[13px] text-stone-600">—</p>
        )}
      </div>

      <div className="bg-white px-4 py-3 sm:px-5">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-stone-600">Concentration du top 3</p>
        <p className="mt-1 font-display text-[14px] font-bold tabular-nums text-slate-900">
          {pct(concentration)}
          <span className="ml-1.5 text-[11.5px] font-normal text-stone-600">
            des chances de victoire
          </span>
        </p>
      </div>

      <div className="bg-white px-4 py-3 sm:px-5">
        {gagnant ? (
          <>
            <p className="text-[10px] font-semibold uppercase tracking-wider text-stone-600">Vainqueur</p>
            <p className="mt-1 flex min-w-0 items-baseline gap-1.5 truncate">
              <Identite numero={gagnant.numero} nom={gagnant.nom_cheval} taille="grand" />
              <span
                className={cn(
                  "ml-1.5 text-[12px] font-semibold tabular-nums",
                  gagnant.rang_predit === 1 ? "text-emerald-700" : gagnant.rang_predit <= 3 ? "text-slate-600" : "text-stone-600",
                )}
              >
                classé {ordinal(gagnant.rang_predit)}
              </span>
            </p>
          </>
        ) : (
          <>
            <p className="text-[10px] font-semibold uppercase tracking-wider text-stone-600">Écarts de prix détectés</p>
            <p className="mt-1 font-display text-[14px] font-bold tabular-nums text-slate-900">
              {nbValeur}
              <span className="ml-1.5 text-[11.5px] font-normal text-stone-600">
                {nbValeur > 1 ? "chevaux payés au-dessus de leur chance" : nbValeur === 1 ? "cheval payé au-dessus de sa chance" : "— le marché est en ligne avec le modèle"}
              </span>
            </p>
          </>
        )}
        {horodatage && (
          <p className="mt-1 inline-flex items-center gap-1 text-[10.5px] text-stone-600">
            <Clock3 className="h-3 w-3" aria-hidden="true" />
            calculé le {horodatage}
            {cotesFigees ? " · cotes figées" : " · cotes suivies en direct"}
          </p>
        )}
      </div>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/*  Table des abonnés                                                         */
/* ────────────────────────────────────────────────────────────────────────── */

export function ClassementAlgo({
  predictions,
  signauxParNumero,
  positionsReelles,
  coteLive,
  nonPartants,
  nonClasses,
  calculeA,
  cotesFigees,
  onLegende,
}: {
  predictions: ClassementPrediction[];
  /** numero → signaux réellement produits par l'analyse (jamais inventés). */
  signauxParNumero: Record<number, ClassementSignal[]>;
  /** numero → position à l'arrivée, une fois la course courue. */
  positionsReelles?: Record<number, number>;
  /** numero → cote de marché la plus fraîche connue. */
  coteLive?: Record<number, number | null>;
  nonPartants?: Set<number>;
  /** Partis mais absents du classement final (disqualifié, tombé, arrêté). */
  nonClasses?: Set<number>;
  /** Horodatage du calcul, renvoyé par /predictions. */
  calculeA?: string | null;
  /** Le pronostic est-il figé (cotes arrêtées) ? Renvoyé par /predictions. */
  cotesFigees?: boolean;
  onLegende: () => void;
}) {
  const lignes = [...predictions].sort((a, b) => a.rang_predit - b.rang_predit);
  const aCoteJuste = lignes.some((p) => p.cote_juste != null);
  const grille = aCoteJuste ? COLS.avecJuste : COLS.sansJuste;
  const nbSignaux = lignes.reduce((n, p) => n + (signauxParNumero[p.numero]?.length ?? 0), 0);

  // Les signaux sont repliés par défaut : huit lignes de pastilles écrasaient les
  // colonnes chiffrées, qui portent la décision. Le choix est mémorisé, sinon le
  // lecteur qui les veut rouvre le tiroir à chaque course.
  const [signauxOuverts, setSignauxOuverts] = useState(false);
  useEffect(() => {
    try {
      if (window.localStorage.getItem(CLE_SIGNAUX) === "1") setSignauxOuverts(true);
    } catch { /* stockage indisponible : on reste sur le repli par défaut */ }
  }, []);
  const basculeSignaux = () => {
    setSignauxOuverts((v) => {
      try { window.localStorage.setItem(CLE_SIGNAUX, v ? "0" : "1"); } catch { /* idem */ }
      return !v;
    });
  };

  return (
    <section className="overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-[0_1px_2px_rgba(28,25,23,.04)]">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-4 pb-3 pt-4 sm:px-5">
        <div className="min-w-0">
          <h3 className="font-display text-[16px] font-bold leading-tight text-slate-900">
            Le classement de l&apos;algorithme
          </h3>
          <p
            className="mt-0.5 text-[11.5px] text-stone-600"
            title="Le rang vient d'un modèle d'ordonnancement dédié, entraîné à ordonner les partants d'une même course. Il ne suit donc pas toujours l'ordre des probabilités : deux chevaux peuvent afficher le même pourcentage sans être au même rang."
          >
            {lignes.length} chevaux notés · ordre du modèle de classement
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {nbSignaux > 0 && (
            <button
              type="button"
              onClick={basculeSignaux}
              aria-pressed={signauxOuverts}
              className="inline-flex min-h-8 items-center gap-1.5 rounded-full border border-stone-200 bg-white px-3 text-[11.5px] font-semibold text-slate-600 transition-colors hover:border-amber-300 hover:bg-amber-50/60 hover:text-amber-900"
            >
              <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", signauxOuverts && "rotate-180")} aria-hidden="true" />
              {signauxOuverts ? "Masquer les signaux" : "Signaux"}
            </button>
          )}
          <button
            type="button"
            onClick={onLegende}
            className="inline-flex min-h-8 items-center gap-1.5 rounded-full border border-stone-200 bg-white px-3 text-[11.5px] font-semibold text-slate-600 transition-colors hover:border-amber-300 hover:bg-amber-50/60 hover:text-amber-900"
          >
            <HelpCircle className="h-3.5 w-3.5" aria-hidden="true" /> Comment lire
          </button>
        </div>
      </header>

      <Synthese
        lignes={lignes}
        positionsReelles={positionsReelles}
        calculeA={calculeA}
        cotesFigees={cotesFigees}
      />

      <div className="max-h-[36rem] overflow-y-auto">
        {/* En-tête de colonnes — collant, masqué sur mobile où chaque ligne se lit en bloc */}
        <div
          className={cn(
            "sticky top-0 z-10 hidden items-end gap-3 border-b border-stone-200 bg-stone-50/95 px-5 py-2 text-[10px] font-semibold uppercase tracking-wider text-stone-600 backdrop-blur sm:grid",
            grille,
          )}
        >
          <span className="text-center">#</span>
          <span>Cheval</span>
          <span className="text-right">Cote</span>
          {aCoteJuste && (
            <span className="text-right leading-tight" title="Cote à partir de laquelle le pari devient rentable selon le modèle">
              Cote<br />juste
            </span>
          )}
          {aCoteJuste && (
            <span className="text-right leading-tight" title="Écart entre la cote payée par le marché et la cote juste du modèle">
              Lecture<br />du prix
            </span>
          )}
          <span className="text-right">Chances de victoire</span>
        </div>

        <ol className="divide-y divide-stone-100">
          {lignes.map((p) => {
            const fav = p.rang_predit === 1;
            const podium = p.rang_predit <= 3;
            const signaux = (signauxParNumero[p.numero] ?? []).filter((s) => nettoie(s.label));
            const position = positionsReelles?.[p.numero];
            const marche = coteLive?.[p.numero] ?? p.cote_pmu;
            const absent = nonPartants?.has(p.numero);
            const ton = absent ? "neutre" : fav ? "or" : podium ? "podium" : "neutre";
            // La cote du prono n'est rappelée que si elle diffère nettement de celle
            // affichée : sinon c'est du bruit. Au-delà du seuil, l'écart change la
            // lecture du prix, donc il doit être visible.
            const coteProno =
              p.cote_figee != null && marche != null
                && Math.abs(p.cote_figee / marche - 1) > ECART_RAPPEL_COTE
                ? p.cote_figee
                : null;
            // Présent dans l'arrivée SANS position = disqualifié, tombé, arrêté. Le
            // taire laissait croire à une donnée manquante — sur le favori du modèle
            // qui plus est, c'est-à-dire exactement là où le lecteur veut savoir.
            const nonClasse = nonClasses?.has(p.numero);

            return (
              <li
                key={p.prediction_id}
                className={cn(
                  "relative px-4 py-3.5 transition-colors hover:bg-stone-50/70 sm:px-5",
                  fav && !absent && "bg-amber-50/50",
                  absent && "opacity-60",
                )}
              >
                {/* Liseré de rang : repère le podium du modèle sans ajouter de texte */}
                {podium && !absent && (
                  <span
                    className={cn("absolute inset-y-0 left-0 w-[3px]", fav ? "bg-amber-400" : "bg-slate-300")}
                    aria-hidden="true"
                  />
                )}

                <div className={cn("grid items-center gap-x-3 gap-y-2 grid-cols-[40px_minmax(0,1fr)]", grille)}>
                  <Rang rang={p.rang_predit} absent={absent} />

                  {/* Cheval + signaux réels */}
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <Identite numero={p.numero} nom={p.nom_cheval} terne={absent} />
                      {p.value_bet && !absent && <BadgeValeur ev={p.value_bet.ev_max} niveau={p.value_bet.niveau} />}
                      {absent && (
                        <span className="rounded-md bg-stone-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-600">
                          Non-partant
                        </span>
                      )}
                      {position != null && <BadgeArrivee position={position} />}
                      {position == null && nonClasse && !absent && (
                        <span
                          className="rounded-md bg-stone-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-600 ring-1 ring-stone-200"
                          title="Parti mais absent du classement officiel : disqualifié, tombé ou arrêté."
                        >
                          non classé
                        </span>
                      )}
                    </div>

                    {signauxOuverts && <Signaux signaux={signaux} />}
                  </div>

                  {/* Cote de marché */}
                  <div className="hidden text-right sm:block">
                    <span className="font-display text-[14px] font-semibold tabular-nums text-slate-900">
                      {marche != null ? cote(marche) : "—"}
                    </span>
                    {coteProno != null && (
                      <span
                        className="block text-[10px] tabular-nums text-stone-600"
                        title="Cote de marché au moment où le modèle a calculé sa probabilité"
                      >
                        {cote(coteProno)} au prono
                      </span>
                    )}
                  </div>

                  {/* Cote juste du modèle */}
                  {aCoteJuste && (
                    <span
                      className={cn(
                        "hidden text-right font-display text-[14px] tabular-nums sm:block",
                        p.value_bet && !absent ? "font-bold text-emerald-700" : "text-slate-600",
                      )}
                      title={
                        p.cote_juste != null
                          ? `Cote juste du modèle : ${cote(p.cote_juste)} — le prix à partir duquel le pari devient rentable si la probabilité est exacte.`
                          : undefined
                      }
                    >
                      {p.cote_juste != null ? cote(p.cote_juste) : "—"}
                    </span>
                  )}

                  {/* Lecture du prix */}
                  {aCoteJuste && (
                    <span className="hidden text-right sm:block">
                      {absent ? <span className="text-[13px] text-stone-300">—</span>
                        : <LecturePrix marche={marche} juste={p.cote_juste} />}
                    </span>
                  )}

                  {/* Chances de victoire : barre + valeur + top-3 */}
                  <div className="col-span-2 sm:col-span-1">
                    <div className="flex items-center gap-2.5">
                      <BarreProba
                        p={p.proba_top1}
                        low={p.proba_top1_low}
                        high={p.proba_top1_high}
                        ton={ton}
                      />
                      <span className="w-11 shrink-0 text-right font-display text-[14px] font-bold tabular-nums text-slate-900">
                        {pct(p.proba_top1)}
                      </span>
                    </div>
                    <div className="mt-1 flex items-baseline justify-between gap-2 text-[10.5px] tabular-nums text-stone-600">
                      <span>
                        {p.proba_top1_low != null && p.proba_top1_high != null
                          ? `fourchette ${Math.round(p.proba_top1_low * 100)}–${Math.round(p.proba_top1_high * 100)} %`
                          : ""}
                      </span>
                      <span className="text-stone-600" title="Probabilité de terminer dans les trois premiers">
                        top-3 <strong className="font-semibold text-slate-700">{pct(p.proba_top3)}</strong>
                      </span>
                    </div>
                  </div>

                  {/* Chiffres repliés sous le nom sur mobile */}
                  <dl className="col-span-2 grid grid-cols-3 gap-2 rounded-lg bg-stone-50 px-2.5 py-2 text-[11px] tabular-nums sm:hidden">
                    <div>
                      <dt className="text-[9.5px] uppercase tracking-wide text-stone-600">Cote</dt>
                      <dd className="font-semibold text-slate-900">{marche != null ? cote(marche) : "—"}</dd>
                    </div>
                    <div>
                      <dt className="text-[9.5px] uppercase tracking-wide text-stone-600">Cote juste</dt>
                      <dd className="font-semibold text-slate-700">{p.cote_juste != null ? cote(p.cote_juste) : "—"}</dd>
                    </div>
                    <div>
                      <dt className="text-[9.5px] uppercase tracking-wide text-stone-600">Prix</dt>
                      <dd>{absent ? "—" : <LecturePrix marche={marche} juste={p.cote_juste} />}</dd>
                    </div>
                  </dl>
                </div>
              </li>
            );
          })}
        </ol>
      </div>

      {/* Pied minimal : la légende des pastilles et le détail du modèle vivent
          dans « Comment lire » (même contenu, en plus complet). Les répéter sous
          chaque table ajoutait un pavé que personne ne lit. Seule la mention
          obligatoire reste à vue. */}
      <footer className="border-t border-stone-100 bg-stone-50/60 px-4 py-2.5 text-[10.5px] text-stone-500 sm:px-5">
        Aide à la décision — aucune garantie de gain.
      </footer>
    </section>
  );
}

/** État verrouillé, affiché à la place de la table selon le plan de l'abonné. */
export function ClassementVerrouille({ titre, texte, action }: { titre: string; texte: string; action: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-stone-200 bg-white p-7 text-center">
      <span className="mx-auto mb-3 inline-flex h-11 w-11 items-center justify-center rounded-xl bg-amber-50 text-amber-800 ring-1 ring-amber-200">
        <Lock className="h-4 w-4" aria-hidden="true" />
      </span>
      <h3 className="font-display text-[15.5px] font-bold text-slate-900">{titre}</h3>
      <p className="mx-auto mt-2 max-w-md text-[13px] leading-6 text-stone-600">{texte}</p>
      <div className="mt-4">{action}</div>
    </section>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/*  Aperçu public                                                             */
/* ────────────────────────────────────────────────────────────────────────── */

/** Aperçu du classement pour un visiteur sans abonnement.
 *
 *  Le problème résolu : à la place de la table, ce visiteur ne voyait qu'un
 *  cadenas et un prix. Rien ne lui montrait ce qu'il achète, donc rien ne lui
 *  donnait envie de l'acheter.
 *
 *  Ce qui est montré, et pourquoi c'est sans risque :
 *    • la STRUCTURE réelle de la table (les mêmes colonnes que les abonnés) ;
 *    • le rang et les PROBABILITÉS de chaque ligne — la forme complète du
 *      classement, qui n'identifie aucun cheval ;
 *    • les DERNIÈRES lignes entièrement nommées, avec cote et cote juste :
 *      savoir quel cheval le modèle écarte prouve la profondeur de l'analyse
 *      sans construire le moindre pari.
 *  Ce qui reste payant : le haut du classement, c'est-à-dire la sélection.
 *
 *  Les identités masquées ne sont pas cachées en CSS : l'endpoint `apercu` ne
 *  les envoie pas au navigateur (cf. api/routes/predictions.py).
 */
export function ClassementApercu({
  apercu, connecte, onLegende,
}: {
  apercu: ApercuAnalyse;
  connecte: boolean;
  onLegende?: () => void;
}) {
  const lignes = apercu.classement ?? [];
  if (!lignes.length) return null;

  const revele = apercu.revele;
  const masquees = lignes.filter((l) => !l.revele);
  const nommees = lignes.filter((l) => l.revele);
  // Avant la course : on n'aligne que le haut du classement (5 lignes suffisent
  // à montrer la distribution) puis la queue nommée. Après la course, tout est
  // nommé, donc tout est montré.
  const hautMasque = revele ? [] : masquees.slice(0, 5);
  const resteMasque = revele ? 0 : masquees.length - hautMasque.length;

  const GRILLE = "grid-cols-[36px_minmax(0,1fr)_112px] sm:grid-cols-[36px_minmax(0,1fr)_74px_74px_180px]";

  return (
    <section className="overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-[0_1px_2px_rgba(28,25,23,.04)]">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-4 pb-3 pt-4 sm:px-5">
        <div className="min-w-0">
          <h3 className="font-display text-[16px] font-bold leading-tight text-slate-900">
            Le classement de l&apos;algorithme
          </h3>
          <p className="mt-0.5 text-[11.5px] text-stone-600">
            {lignes.length} chevaux notés · ordre du modèle de classement
          </p>
        </div>
        <span className="ml-auto rounded-full bg-amber-50 px-3 py-1 text-[11px] font-semibold text-amber-800 ring-1 ring-amber-200">
          {revele ? "course courue · classement complet" : "aperçu gratuit"}
        </span>
      </header>

      {/* Ce que le modèle dit de la course, avant même de nommer un cheval */}
      {!revele && (apercu.confiance != null || apercu.accord_marche != null || apercu.nb_ecartes > 0) && (
        <div className="grid gap-px border-y border-stone-100 bg-stone-100 sm:grid-cols-3">
          <div className="bg-white px-4 py-3 sm:px-5">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-stone-600">Confiance du modèle</p>
            <p className="mt-1 font-display text-[14px] font-bold tabular-nums text-slate-900">
              {apercu.confiance != null ? apercu.confiance : "—"}
              <span className="text-[11.5px] font-normal text-stone-600">/100</span>
            </p>
          </div>
          <div className="bg-white px-4 py-3 sm:px-5">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-stone-600">Lecture du marché</p>
            <p className="mt-1 text-[13px] font-semibold text-slate-900">
              {apercu.accord_marche == null ? "—"
                : apercu.accord_marche ? "confirme le favori du marché" : "ne suit pas le marché"}
            </p>
          </div>
          <div className="bg-white px-4 py-3 sm:px-5">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-stone-600">Chevaux écartés</p>
            <p className="mt-1 font-display text-[14px] font-bold tabular-nums text-slate-900">
              {apercu.nb_ecartes}
              <span className="ml-1.5 text-[11.5px] font-normal text-stone-600">sous 3 % de chances</span>
            </p>
          </div>
        </div>
      )}

      {/* En-tête de colonnes — les colonnes RÉELLES de la table des abonnés */}
      <div className={cn("hidden items-center gap-3 border-b border-stone-200 bg-stone-50/95 px-5 py-2 text-[10px] font-semibold uppercase tracking-wider text-stone-600 sm:grid", GRILLE)}>
        <span className="text-center">#</span>
        <span>Cheval</span>
        <span className="text-right">Cote</span>
        <span className="text-right" title="Cote à partir de laquelle le pari devient rentable selon le modèle">Cote juste</span>
        <span className="text-right">Chances de victoire</span>
      </div>

      <ol className={cn("divide-y divide-stone-100", revele && "max-h-[36rem] overflow-y-auto")}>
        {hautMasque.map((l) => (
          <li key={`m${l.rang}`} className={cn("relative px-4 py-3.5 sm:px-5", l.rang === 1 && "bg-amber-50/50")}>
            {l.rang <= 3 && (
              <span className={cn("absolute inset-y-0 left-0 w-[3px]", l.rang === 1 ? "bg-amber-400" : "bg-slate-300")} aria-hidden="true" />
            )}
            <div className={cn("grid items-center gap-3", GRILLE)}>
              <Rang rang={l.rang} />

              <span className="flex min-w-0 items-center gap-2">
                <span
                  className="h-5 w-full max-w-[9rem] rounded"
                  style={{ backgroundImage: "repeating-linear-gradient(115deg,#E7E5E4 0 6px,#F5F5F4 6px 12px)" }}
                  aria-hidden="true"
                />
                <span className="inline-flex flex-shrink-0 items-center gap-1 rounded-md bg-stone-100 px-1.5 py-0.5 text-[10px] font-semibold text-stone-600">
                  <Lock className="h-3 w-3" aria-hidden="true" /> réservé
                </span>
              </span>

              <span className="hidden text-right text-[13px] text-stone-300 sm:block" aria-hidden="true">•••</span>
              <span className="hidden text-right font-display text-[14px] tabular-nums text-slate-600 sm:block">
                {l.cote_juste != null ? cote(l.cote_juste) : "—"}
              </span>

              <div className="flex items-center gap-2.5">
                <BarreProba
                  p={l.proba_top1 ?? 0}
                  low={null}
                  high={null}
                  ton={l.rang === 1 ? "or" : l.rang <= 3 ? "podium" : "neutre"}
                />
                <span className="w-11 shrink-0 text-right font-display text-[14px] font-bold tabular-nums text-slate-900">
                  {pct(l.proba_top1)}
                </span>
              </div>
            </div>
          </li>
        ))}

        {resteMasque > 0 && (
          <li className="bg-stone-50/60 px-4 py-3 text-center text-[11.5px] text-stone-600 sm:px-5">
            + {resteMasque} lignes, avec leurs probabilités, cotes justes et signaux — réservées aux abonnés
          </li>
        )}

        {!revele && nommees.length > 0 && (
          <li className="bg-white px-4 py-2.5 text-[10px] font-semibold uppercase tracking-wider text-stone-600 sm:px-5">
            Visible gratuitement · le bas du classement
          </li>
        )}

        {nommees.map((l) => (
          <li key={`r${l.rang}`} className={cn("relative px-4 py-3.5 sm:px-5", revele && l.rang === 1 && "bg-amber-50/50")}>
            {revele && l.rang <= 3 && (
              <span className={cn("absolute inset-y-0 left-0 w-[3px]", l.rang === 1 ? "bg-amber-400" : "bg-slate-300")} aria-hidden="true" />
            )}
            <div className={cn("grid items-center gap-3", GRILLE)}>
              {revele ? <Rang rang={l.rang} /> : <Rang rang={l.rang} absent />}

              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  {l.numero != null && <Identite numero={l.numero} nom={l.nom ?? ""} terne={!revele} />}
                  {l.position != null && <BadgeArrivee position={l.position} />}
                  {!revele && (
                    <span className="rounded-md bg-stone-100 px-1.5 py-0.5 text-[10px] font-semibold text-stone-600">
                      écarté par le modèle
                    </span>
                  )}
                </div>
                <div className="mt-1.5 flex items-center gap-3 text-[11px] tabular-nums text-stone-600 sm:hidden">
                  {l.cote != null && <span>Cote {cote(l.cote)}</span>}
                  {l.cote_juste != null && <span>Juste {cote(l.cote_juste)}</span>}
                  {l.proba_top3 != null && <span>Top-3 {pct(l.proba_top3)}</span>}
                </div>
              </div>

              <span className="hidden text-right font-display text-[14px] font-semibold tabular-nums text-slate-900 sm:block">
                {l.cote != null ? cote(l.cote) : "—"}
              </span>
              <span className="hidden text-right font-display text-[14px] tabular-nums text-slate-600 sm:block">
                {l.cote_juste != null ? cote(l.cote_juste) : "—"}
              </span>

              <div className="flex items-center gap-2.5">
                <BarreProba
                  p={l.proba_top1 ?? 0}
                  low={null}
                  high={null}
                  ton={revele && l.rang === 1 ? "or" : "neutre"}
                />
                <span className="w-11 shrink-0 text-right font-display text-[14px] font-bold tabular-nums text-slate-900">
                  {pct(l.proba_top1)}
                </span>
              </div>
            </div>
          </li>
        ))}
      </ol>

      <footer className="border-t border-stone-100 bg-stone-50/60 px-4 py-4 sm:px-5">
        {revele ? (
          <p className="text-[12px] leading-5 text-stone-600">
            Ce classement était établi <strong className="text-slate-900">avant le départ</strong>. Sur les courses
            à venir, il est réservé aux abonnés — avec les signaux retenus pour et contre chaque cheval.
          </p>
        ) : (
          <p className="text-[12px] leading-5 text-stone-600">
            Le rang vient d&apos;un modèle d&apos;ordonnancement dédié : deux chevaux peuvent afficher
            la même probabilité sans être au même rang.{" "}
            Vous voyez la probabilité de victoire de chaque rang et la cote juste qui en découle,
            mais pas les chevaux. L&apos;abonnement ouvre les noms, la cote du marché en face de la
            cote juste — c&apos;est là que se voit un pari de valeur — et les signaux retenus{" "}
            <strong className="text-slate-900">pour comme contre</strong> chaque partant.
          </p>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <a
            href={connecte ? "/tarifs" : "/inscription"}
            className="inline-flex min-h-10 items-center rounded-xl bg-amber-500 px-4 text-[13px] font-semibold text-brand-dark transition-colors hover:bg-amber-600"
          >
            {connecte ? "Voir le classement complet — 12€/mois" : "Essayer 7 jours gratuitement"}
          </a>
          {onLegende && (
            <button
              type="button"
              onClick={onLegende}
              className="inline-flex items-center gap-1 text-[12px] font-medium text-stone-600 underline underline-offset-2 hover:text-amber-800"
            >
              <HelpCircle className="h-3.5 w-3.5" aria-hidden="true" /> Comment lire ce classement
            </button>
          )}
        </div>
      </footer>
    </section>
  );
}
