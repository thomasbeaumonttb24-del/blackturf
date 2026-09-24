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

import { Anneau, CARTE_CLS, INCLINABLE_CLS, IconeTuile, Reflet, SG, inclinerCarte, redresserCarte } from "@/components/courses/course-ui";
import { useEffect, useState } from "react";
import { Brain, ChevronDown, HelpCircle, Lock, TrendingUp, Clock3, Trophy } from "lucide-react";
import { CasaqueNumero } from "@/components/courses/identite-cheval";
import { cn } from "@/lib/utils";
import type { ApercuAnalyse, ApercuSignal } from "@/components/courses/insights";

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

/** La cote JUSTE n'est pas une cote de bookmaker : c'est 1/proba, et sa précision
 *  utile dépend de l'ordre de grandeur. À 1 décimale fixe, deux chevaux séparés de
 *  2 % de probabilité s'affichaient au même prix. Même règle que l'API
 *  (backend/services/cote_juste.py) — les deux doivent rester synchronisées. */
const coteJuste = (x: number) =>
  x.toLocaleString("fr-FR", {
    minimumFractionDigits: x < 10 ? 2 : x < 100 ? 1 : 0,
    maximumFractionDigits: x < 10 ? 2 : x < 100 ? 1 : 0,
  });

const ordinal = (n: number) => `${n}${n === 1 ? "er" : "e"}`;

/** Retire les puces / emojis en tête de libellé renvoyés par l'analyse. */
const nettoie = (s: string) => s.replace(/^[^A-Za-zÀ-ÿ0-9]+/, "").trim();

const SENS = {
  positif: { fg: "text-emerald-700", bg: "bg-emerald-50", ring: "ring-emerald-200/70", fleche: "▲" },
  negatif: { fg: "text-rose-700", bg: "bg-rose-50", ring: "ring-rose-200/70", fleche: "▼" },
  neutre: { fg: "text-amber-800", bg: "bg-amber-50", ring: "ring-amber-200/70", fleche: "●" },
} as const;

/** Borne haute de la cote juste appliquée côté API (services/cote_juste.py). Atteinte,
 *  elle signifie « le modèle ne chiffre plus », pas « cote de 999 ». Le plafond est
 *  passé de 100 à 999 : écraser tous les gros outsiders sur 100 créait des ex æquo
 *  cosmétiques entre des chevaux que le modèle sépare d'un facteur 3. */
const COTE_JUSTE_MAX = 999;

/** Formats partagés avec la section Partants : mêmes cotes, même écriture. */
export { cote as formatCoteFr, coteJuste as formatCoteJusteFr };

/** Écart minimal entre la cote affichée et la cote du pronostic pour rappeler
 *  cette dernière. En dessous, le rappel n'apprend rien et alourdit la ligne. */
const ECART_RAPPEL_COTE = 0.2;

/** Écart marché/cote juste en deçà duquel LecturePrix écrit « au prix ». Même seuil
 *  pour le repère « meilleur écart » : désigner un meilleur cheval là où le modèle
 *  dit que tout est au prix inventerait une hiérarchie qu'il n'écrit pas. */
const ECART_MEILLEUR_PRIX = 0.08;

/** Même comparaison que la colonne « Lecture du prix », à partir de la cote
 * actuellement affichée. Les value bets enregistrés lors du pronostic sont
 * distincts et ne doivent pas servir à compter ces écarts mouvants. */
export function ecartPrix(marche: number | null | undefined, juste: number | null | undefined): number | null {
  if (marche == null || !Number.isFinite(marche) || marche <= 0 ||
      juste == null || !Number.isFinite(juste) || juste <= 0 || juste >= COTE_JUSTE_MAX) return null;
  return marche / juste - 1;
}

/** Préférence d'affichage des signaux, conservée d'une course à l'autre. */
const CLE_SIGNAUX = "bt.classement.signaux";

/** Gabarit de colonnes partagé par l'en-tête et les lignes : une seule source,
 *  sinon les deux dérivent au premier ajustement. */
const COLS = {
  avecJuste: "sm:grid-cols-[40px_minmax(0,1fr)_64px_70px_92px_200px]",
  sansJuste: "sm:grid-cols-[40px_minmax(0,1fr)_64px_200px]",
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
    <span className="flex min-w-0 items-center gap-1.5">
      <span className={cn(
        "font-display font-bold tabular-nums",
        taille === "grand" ? "text-[16px]" : "text-[15px]",
        terne ? "text-stone-600" : "text-slate-900",
      )}>
        <CasaqueNumero numero={numero} />
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
export function LecturePrix({ marche, juste }: { marche: number | null; juste: number | null }) {
  const ecart = ecartPrix(marche, juste);
  if (marche == null || !Number.isFinite(marche) || marche <= 0 || juste == null || !Number.isFinite(juste) || juste <= 0) {
    return <span className="text-[13px] text-stone-300">—</span>;
  }
  // La cote juste est bornée côté API. Sur un cheval que le modèle chiffre sous
  // 0,1 %, la borne est ATTEINTE : comparer une cote de marché à ce plafond
  // produisait un écart qui annonce une aubaine là où le modèle dit seulement
  // qu'il ne sait plus fixer de prix. On ne chiffre pas un écart contre une borne.
  if (juste >= COTE_JUSTE_MAX) {
    return (
      <span
        title="Le modèle chiffre ce cheval en dessous du seuil où sa cote juste reste mesurable (plafonnée à 999) : l'écart au marché n'a pas de sens ici."
        className="text-[11px] text-stone-600"
      >
        non chiffrable
      </span>
    );
  }
  const abs = Math.abs(Math.round((ecart ?? 0) * 100));
  if (Math.abs(ecart ?? 0) < ECART_MEILLEUR_PRIX) {
    return (
      <span
        title={`Le marché paie ${cote(marche)}, le modèle estime la cote juste à ${coteJuste(juste)} : prix conforme.`}
        className="inline-flex items-center rounded-md bg-stone-100 px-1.5 py-0.5 text-[10.5px] font-semibold text-stone-600"
      >
        au prix
      </span>
    );
  }
  const genereux = (ecart ?? 0) > 0;
  return (
    <span
      title={
        genereux
          ? `Le marché paie ${cote(marche)} pour une cote juste estimée à ${coteJuste(juste)} : ${abs} % au-dessus.`
          : `Le marché ne paie que ${cote(marche)} pour une cote juste estimée à ${coteJuste(juste)} : ${abs} % en dessous du prix qui couvrirait le risque.`
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
  lignes, positionsReelles, calculeA, cotesFigees, coteLive, nonPartants,
}: {
  lignes: ClassementPrediction[];
  positionsReelles?: Record<number, number>;
  calculeA?: string | null;
  cotesFigees?: boolean;
  coteLive?: Record<number, number | null>;
  nonPartants?: Set<number>;
}) {
  const fav = lignes[0];
  const concentration = lignes.slice(0, 3).reduce((s, p) => s + p.proba_top1, 0);
  const ecarts = lignes.filter((p) => !nonPartants?.has(p.numero))
    .map((p) => ecartPrix(coteLive?.[p.numero] ?? p.cote_pmu, p.cote_juste))
    .filter((ecart): ecart is number => ecart != null);
  const nbEcarts = ecarts.filter((ecart) => ecart >= ECART_MEILLEUR_PRIX).length;

  const gagnantNum = positionsReelles
    ? Number(Object.keys(positionsReelles).find((n) => positionsReelles[Number(n)] === 1))
    : NaN;
  const gagnant = Number.isFinite(gagnantNum) ? lignes.find((p) => p.numero === gagnantNum) : undefined;

  const horodatage = calculeA
    ? new Date(calculeA).toLocaleString("fr-FR", { timeZone: "Europe/Paris", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
    : null;

  const top3 = lignes.slice(0, 3);
  const TEINTE_SEG = ["from-amber-300 to-amber-500", "from-slate-300 to-slate-500", "from-orange-300 to-orange-600"];
  const TUILE = "rounded-2xl bg-white px-3.5 py-3 ring-1 ring-[#ECE7DC] shadow-[inset_0_1px_0_#fff,0_1px_2px_rgba(17,24,39,.05),0_10px_22px_-18px_rgba(17,24,39,.4)]";

  return (
    <div className="grid gap-2.5 px-4 pb-4 sm:grid-cols-3 sm:px-5">
      {/* Concentration du top 3 : la part des chances de victoire des trois premiers,
          dessinée en trois segments — le lecteur voit d'un coup si la course est jouée
          d'avance ou ouverte. */}
      <div className={TUILE}>
        <p className="text-[10px] font-bold uppercase tracking-[.1em] text-stone-500">Concentration du top 3</p>
        <p className="mt-1 flex items-baseline gap-1.5">
          <span className="text-[22px] font-bold leading-none tabular-nums text-stone-900" style={SG}>{pct(concentration)}</span>
          <span className="text-[11.5px] text-stone-500">
            {concentration >= 0.6 ? "course serrée" : concentration >= 0.45 ? "course disputée" : "course ouverte"}
          </span>
        </p>
        <div className="mt-2.5 flex h-2.5 overflow-hidden rounded-full bg-stone-100 shadow-[inset_0_1px_2px_rgba(0,0,0,.08)]" aria-hidden="true">
          {top3.map((p, i) => (
            <span
              key={p.numero}
              title={`N°${p.numero} : ${pct(p.proba_top1)}`}
              className={cn("h-full bg-gradient-to-b", TEINTE_SEG[i], i > 0 && "border-l border-white/80")}
              style={{ width: `${Math.max(1, p.proba_top1 * 100)}%` }}
            />
          ))}
        </div>
        <p className="mt-1.5 flex flex-wrap gap-x-2.5 text-[10.5px] tabular-nums text-stone-500">
          {top3.map((p, i) => (
            <span key={p.numero} className="inline-flex items-center gap-1">
              <span className={cn("h-2 w-2 rounded-full bg-gradient-to-b", TEINTE_SEG[i])} />N°{p.numero} {pct(p.proba_top1)}
            </span>
          ))}
        </p>
      </div>

      <div className={TUILE}>
        {gagnant ? (
          <>
            <p className="text-[10px] font-bold uppercase tracking-[.1em] text-stone-500">Vainqueur</p>
            <p className="mt-1.5 flex min-w-0 items-center gap-1.5 truncate">
              <Identite numero={gagnant.numero} nom={gagnant.nom_cheval} taille="grand" />
            </p>
            <p className={cn("mt-1 text-[12px] font-semibold", gagnant.rang_predit === 1 ? "text-emerald-700" : gagnant.rang_predit <= 3 ? "text-slate-600" : "text-stone-600")}>
              classé {ordinal(gagnant.rang_predit)} par le modèle
            </p>
          </>
        ) : (
          <>
            <p className="text-[10px] font-bold uppercase tracking-[.1em] text-stone-500">Écarts de prix détectés</p>
            <p className="mt-1 flex items-baseline gap-1.5">
              <span className={cn("text-[22px] font-bold leading-none tabular-nums", nbEcarts > 0 ? "text-emerald-700" : "text-stone-900")} style={SG}>
                {ecarts.length ? nbEcarts : "—"}
              </span>
              <span className="text-[11.5px] leading-snug text-stone-500">
                {!ecarts.length ? "cotes indisponibles" : nbEcarts > 1 ? "chevaux payés au-dessus de leur chance" : nbEcarts === 1 ? "cheval payé au-dessus de sa chance" : "aucun écart positif d’au moins 8 %"}
              </span>
            </p>
          </>
        )}
      </div>

      <div className={TUILE}>
        <p className="text-[10px] font-bold uppercase tracking-[.1em] text-stone-500">Favori du modèle</p>
        {fav ? (
          <p className="mt-1.5 flex min-w-0 items-center gap-1.5 truncate">
            <Identite numero={fav.numero} nom={fav.nom_cheval} taille="grand" />
            <span className="shrink-0 text-[13px] font-bold tabular-nums text-amber-700">{pct(fav.proba_top1)}</span>
          </p>
        ) : <p className="mt-1 text-[13px] text-stone-600">—</p>}
        {horodatage && (
          <p className="mt-1.5 inline-flex items-center gap-1 text-[10.5px] text-stone-500">
            <Clock3 className="h-3 w-3" aria-hidden="true" />
            calculé le {horodatage}{cotesFigees ? " · cotes figées" : ""}
          </p>
        )}
      </div>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/*  Podium du modèle                                                          */
/* ────────────────────────────────────────────────────────────────────────── */

const PODIUM = {
  1: { piece: "radial-gradient(circle at 32% 28%,#FFF7D6 0%,#FCD34D 32%,#D97706 72%,#92400E 100%)", fond: "from-amber-50 via-white to-white", ring: "ring-amber-200", libelle: "1er" },
  2: { piece: "radial-gradient(circle at 32% 28%,#FFFFFF 0%,#E2E8F0 34%,#94A3B8 74%,#475569 100%)", fond: "from-slate-50 via-white to-white", ring: "ring-slate-200", libelle: "2e" },
  3: { piece: "radial-gradient(circle at 32% 28%,#FFEAD5 0%,#FDBA74 34%,#C2410C 76%,#7C2D12 100%)", fond: "from-orange-50/80 via-white to-white", ring: "ring-orange-200", libelle: "3e" },
} as const;

/** Pièce de podium en relief (or / argent / bronze). */
function Piece({ rang, taille = 30 }: { rang: 1 | 2 | 3; taille?: number }) {
  return (
    <span
      aria-hidden="true"
      className="inline-flex shrink-0 items-center justify-center rounded-full font-extrabold text-white shadow-[inset_0_-2px_2px_rgba(0,0,0,.25),inset_0_2px_2px_rgba(255,255,255,.7),0_4px_10px_-3px_rgba(0,0,0,.35)] [text-shadow:0_1px_1px_rgba(0,0,0,.35)]"
      style={{ width: taille, height: taille, fontSize: taille * 0.45, background: PODIUM[rang].piece }}
    >
      {rang}
    </span>
  );
}

/** Barre fine en relief (top 3). */
function BarreFine({ v, ton }: { v: number; ton: "or" | "podium" | "neutre" | "place" }) {
  return (
    <span className="relative block h-1.5 w-full overflow-hidden rounded-full bg-stone-100 shadow-[inset_0_1px_1px_rgba(0,0,0,.08)]" aria-hidden="true">
      <span
        className={cn("absolute inset-y-0 left-0 rounded-full bg-gradient-to-r",
          ton === "or" ? "from-amber-300 to-amber-600" : ton === "podium" ? "from-slate-300 to-slate-600" : ton === "place" ? "from-sky-300 to-sky-600" : "from-stone-300 to-stone-500")}
        style={{ width: `${Math.max(2, Math.min(100, v * 100))}%` }}
      />
    </span>
  );
}

/** Carte d'un cheval du podium : médaille, jauge victoire, top 3, prix, signaux. */
function CartePodium({ p, marche, signaux, position, grand = false }: {
  p: ClassementPrediction;
  marche: number | null;
  signaux: ClassementSignal[];
  position?: number;
  grand?: boolean;
}) {
  const rang = p.rang_predit as 1 | 2 | 3;
  const m = PODIUM[rang];
  return (
    <div
      onPointerMove={(e) => inclinerCarte(e, grand ? 0.8 : 1)}
      onPointerLeave={redresserCarte}
      className={cn(
        "group/reflet relative overflow-hidden rounded-2xl bg-gradient-to-b p-3.5 ring-1 sm:p-4",
        m.fond, m.ring, INCLINABLE_CLS,
        "shadow-[inset_0_1px_0_#fff,0_2px_4px_rgba(17,24,39,.05),0_18px_36px_-24px_rgba(17,24,39,.55)] hover:shadow-[inset_0_1px_0_#fff,0_4px_8px_rgba(17,24,39,.06),0_28px_48px_-26px_rgba(146,64,14,.55)]",
        grand && "sm:-mt-3",
      )}
    >
      <Reflet />
      <div className="relative flex items-start gap-2.5">
        <Piece rang={rang} taille={grand ? 34 : 30} />
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-bold uppercase tracking-[.12em] text-stone-500">{m.libelle} du modèle</p>
          <div className="mt-1 min-w-0"><Identite numero={p.numero} nom={p.nom_cheval} taille="grand" /></div>
        </div>
        {position != null && <BadgeArrivee position={position} />}
      </div>

      <div className="relative mt-3 flex items-center gap-3">
        <Anneau v={p.proba_top1} rang={rang} taille={grand ? 64 : 56} />
        <div className="min-w-0 flex-1 space-y-2">
          <div>
            <p className="flex items-baseline justify-between text-[10.5px] text-stone-500">
              <span>Victoire</span>
              <b className="text-[12.5px] font-bold tabular-nums text-stone-900">{pct(p.proba_top1)}</b>
            </p>
            <BarreFine v={p.proba_top1} ton={rang === 1 ? "or" : "podium"} />
          </div>
          <div>
            <p className="flex items-baseline justify-between text-[10.5px] text-stone-500">
              <span>Top 3</span>
              <b className="text-[12.5px] font-bold tabular-nums text-stone-900">{pct(p.proba_top3)}</b>
            </p>
            <BarreFine v={p.proba_top3} ton="place" />
          </div>
        </div>
      </div>

      <div className="relative mt-3 flex flex-wrap items-center gap-1.5 border-t border-black/[.05] pt-2.5 text-[11.5px] text-stone-500">
        <span>Cote <b className="font-bold tabular-nums text-stone-900">{marche != null ? cote(marche) : "—"}</b></span>
        {p.cote_juste != null && (
          <span>· juste <b className="font-semibold tabular-nums text-stone-700">{coteJuste(p.cote_juste)}</b></span>
        )}
        <LecturePrix marche={marche} juste={p.cote_juste} />
        {p.value_bet && <BadgeValeur ev={p.value_bet.ev_max} niveau={p.value_bet.niveau} />}
      </div>
      {signaux.length > 0 && <div className="relative mt-2"><PuceSignaux signaux={signaux} max={2} /></div>}
    </div>
  );
}

/** Signaux en pastilles (atout / réserve / vigilance), `max` visibles puis « +N ». */
function PuceSignaux({ signaux, max = 2 }: { signaux: ClassementSignal[]; max?: number }) {
  const [ouvert, setOuvert] = useState(false);
  if (!signaux.length) return null;
  const visibles = ouvert ? signaux : signaux.slice(0, max);
  const reste = signaux.length - visibles.length;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {visibles.map((s, i) => {
        const st = SENS[s.sens] ?? SENS.neutre;
        return (
          <span
            key={`${s.label}-${i}`}
            title={s.detail || undefined}
            className={cn("inline-flex cursor-help items-center gap-1 rounded-full px-2 py-0.5 text-[10.5px] font-semibold ring-1 ring-inset", st.bg, st.fg, st.ring)}
          >
            <span className="text-[7px]" aria-hidden="true">{st.fleche}</span>
            {nettoie(s.label)}
          </span>
        );
      })}
      {reste > 0 && (
        <button type="button" onClick={() => setOuvert(true)} className="rounded-full bg-white px-2 py-0.5 text-[10.5px] font-bold text-stone-600 ring-1 ring-inset ring-stone-200 hover:text-stone-900">
          +{reste}
        </button>
      )}
      {ouvert && signaux.length > max && (
        <button type="button" onClick={() => setOuvert(false)} className="text-[10.5px] font-semibold text-stone-500 underline decoration-dotted underline-offset-2 hover:text-stone-800">
          réduire
        </button>
      )}
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

  // Le cheval le MIEUX ÉVALUÉ par la cote juste : celui dont le marché paie le plus
  // au-dessus du prix du modèle. C'est la lecture que la colonne « Lecture du prix »
  // rend ligne à ligne mais qu'il fallait reconstituer de tête sur douze partants.
  // Restitution d'un écart entre deux valeurs DÉJÀ affichées — aucune appréciation
  // ajoutée, et le repère disparaît si aucun écart n'atteint le seuil de lisibilité
  // (le même que celui du « au prix » de LecturePrix).
  const meilleurPrix = lignes.reduce<{ numero: number; ecart: number } | null>((best, p) => {
    const m = coteLive?.[p.numero] ?? p.cote_pmu;
    if (nonPartants?.has(p.numero) || m == null || p.cote_juste == null) return best;
    if (p.cote_juste >= COTE_JUSTE_MAX) return best;   // borne atteinte : non chiffrable
    const ecart = ecartPrix(m, p.cote_juste);
    if (ecart == null || ecart < ECART_MEILLEUR_PRIX) return best;
    return best && best.ecart >= ecart ? best : { numero: p.numero, ecart };
  }, null);
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

  const podium = lignes.filter((p) => p.rang_predit <= 3 && !nonPartants?.has(p.numero)).slice(0, 3);
  const signauxDe = (n: number) => (signauxParNumero[n] ?? []).filter((s) => nettoie(s.label));

  return (
    <section className={cn("overflow-hidden", CARTE_CLS)}>
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 pb-3 pt-4 sm:px-5">
        <div className="flex min-w-0 items-center gap-2.5">
          <IconeTuile icone={Brain} />
          <div className="min-w-0">
            <h3 className="text-[16px] font-bold leading-tight text-stone-900" style={SG}>
              Le classement de l&apos;algorithme
            </h3>
            <p
              className="mt-0.5 text-[11.5px] text-stone-500"
              title="Le rang suit la probabilité de victoire : le n°1 est le cheval le plus probable, donc celui dont la cote juste est la plus basse. Cette probabilité combine le modèle et le marché, avec des poids réappris chaque nuit sur les arrivées réelles."
            >
              {lignes.length} chevaux notés · du plus probable au moins probable
            </p>
          </div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {nbSignaux > 0 && (
            <button
              type="button"
              onClick={basculeSignaux}
              aria-pressed={signauxOuverts}
              className="inline-flex min-h-8 items-center gap-1.5 rounded-full bg-white px-3 text-[11.5px] font-semibold text-slate-600 ring-1 ring-stone-200 shadow-[inset_0_1px_0_#fff,0_1px_2px_rgba(17,24,39,.06)] transition-colors hover:bg-amber-50/60 hover:text-amber-900 hover:ring-amber-300"
            >
              <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", signauxOuverts && "rotate-180")} aria-hidden="true" />
              {signauxOuverts ? "Moins de signaux" : "Tous les signaux"}
            </button>
          )}
          <button
            type="button"
            onClick={onLegende}
            className="inline-flex min-h-8 items-center gap-1.5 rounded-full bg-white px-3 text-[11.5px] font-semibold text-slate-600 ring-1 ring-stone-200 shadow-[inset_0_1px_0_#fff,0_1px_2px_rgba(17,24,39,.06)] transition-colors hover:bg-amber-50/60 hover:text-amber-900 hover:ring-amber-300"
          >
            <HelpCircle className="h-3.5 w-3.5" aria-hidden="true" /> Comment lire
          </button>
        </div>
      </header>

      {/* ── Podium du modèle : le 1er au centre et plus haut sur ordinateur ── */}
      {podium.length === 3 && (
        <div className="px-4 pb-4 sm:px-5">
          <p className="mb-2.5 text-[10.5px] font-bold uppercase tracking-[.12em] text-amber-700">Podium du modèle</p>
          <div className="grid grid-cols-1 gap-2.5 min-[480px]:grid-cols-2 sm:grid-cols-3 sm:items-end [perspective:1200px]">
            {[podium[1], podium[0], podium[2]].map((p) => (
              <div key={p.prediction_id} className={cn(p.rang_predit === 1 ? "order-first min-[480px]:col-span-2 sm:order-none sm:col-span-1" : "")}>
                <CartePodium
                  p={p}
                  marche={coteLive?.[p.numero] ?? p.cote_pmu}
                  signaux={signauxDe(p.numero)}
                  position={positionsReelles?.[p.numero]}
                  grand={p.rang_predit === 1}
                />
              </div>
            ))}
          </div>
        </div>
      )}

      <Synthese
        lignes={lignes}
        positionsReelles={positionsReelles}
        calculeA={calculeA}
        cotesFigees={cotesFigees}
        coteLive={coteLive}
        nonPartants={nonPartants}
      />

      {/* ── Classement complet ── */}
      <div className="border-t border-stone-100">
        <div
          className={cn(
            "hidden items-end gap-3 border-b border-stone-200/70 bg-[#FCFAF5] px-5 py-2 text-[10px] font-bold uppercase tracking-[.1em] text-stone-500 sm:grid",
            grille,
          )}
        >
          <span className="text-center">#</span>
          <span>Cheval · signaux</span>
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
          <span className="text-right">Victoire · Top 3</span>
        </div>

        <ol className="divide-y divide-stone-100">
          {lignes.map((p) => {
            const fav = p.rang_predit === 1;
            const podiumRang = p.rang_predit <= 3;
            const signaux = signauxDe(p.numero);
            const position = positionsReelles?.[p.numero];
            const marche = coteLive?.[p.numero] ?? p.cote_pmu;
            const absent = nonPartants?.has(p.numero);
            // La cote du prono n'est rappelée que si elle diffère nettement de celle
            // affichée : sinon c'est du bruit. Au-delà du seuil, l'écart change la
            // lecture du prix, donc il doit être visible.
            const coteProno =
              p.cote_figee != null && marche != null
                && Math.abs(p.cote_figee / marche - 1) > ECART_RAPPEL_COTE
                ? p.cote_figee
                : null;
            // Présent dans l'arrivée SANS position = disqualifié, tombé, arrêté.
            const nonClasse = nonClasses?.has(p.numero);
            const fourchette = p.proba_top1_low != null && p.proba_top1_high != null
              ? `fourchette du modèle ${Math.round(p.proba_top1_low * 100)}–${Math.round(p.proba_top1_high * 100)} %`
              : undefined;

            return (
              <li
                key={p.prediction_id}
                className={cn(
                  "relative px-4 py-3 transition-colors hover:bg-[#FCFAF5] sm:px-5",
                  fav && !absent && "bg-amber-50/40",
                  absent && "opacity-60",
                )}
              >
                {podiumRang && !absent && (
                  <span
                    className={cn("absolute inset-y-2 left-0 w-1 rounded-r-full bg-gradient-to-b",
                      p.rang_predit === 1 ? "from-amber-300 to-amber-600" : p.rang_predit === 2 ? "from-slate-300 to-slate-500" : "from-orange-300 to-orange-600")}
                    aria-hidden="true"
                  />
                )}

                <div className={cn("grid items-center gap-x-3 gap-y-2 grid-cols-[40px_minmax(0,1fr)_auto]", grille)}>
                  {podiumRang && !absent ? (
                    <span className="flex justify-center"><Piece rang={p.rang_predit as 1 | 2 | 3} taille={30} /></span>
                  ) : <Rang rang={p.rang_predit} absent={absent} />}

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
                    {signaux.length > 0 && !absent && (
                      <div className="mt-1.5"><PuceSignaux signaux={signaux} max={signauxOuverts ? 8 : 2} /></div>
                    )}
                  </div>

                  {/* Téléphone : jauge de victoire à droite du nom */}
                  <span className="flex flex-col items-center sm:hidden">
                    {!absent && <Anneau v={p.proba_top1} rang={p.rang_predit} taille={46} />}
                  </span>

                  {/* Cote de marché */}
                  <div className="hidden text-right sm:block">
                    <span className="text-[14px] font-semibold tabular-nums text-slate-900" style={SG}>
                      {marche != null ? cote(marche) : "—"}
                    </span>
                    {coteProno != null && (
                      <span
                        className="block text-[10px] tabular-nums text-stone-500"
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
                        "hidden text-right text-[14px] tabular-nums sm:block",
                        p.value_bet && !absent ? "font-bold text-emerald-700" : "text-slate-600",
                      )}
                      style={SG}
                      title={
                        p.cote_juste != null
                          ? `Cote juste du modèle : ${coteJuste(p.cote_juste)} — le prix à partir duquel le pari devient rentable si la probabilité est exacte.`
                          : undefined
                      }
                    >
                      {p.cote_juste != null ? coteJuste(p.cote_juste) : "—"}
                      {meilleurPrix?.numero === p.numero && (
                        <span
                          className="mt-0.5 block text-[9.5px] font-semibold uppercase tracking-wider text-emerald-700"
                          title={`Sur cette course, c'est l'écart le plus large entre le prix payé par le marché et la cote juste du modèle : +${Math.round(meilleurPrix.ecart * 100)} %.`}
                        >
                          meilleur écart
                        </span>
                      )}
                    </span>
                  )}

                  {/* Lecture du prix */}
                  {aCoteJuste && (
                    <span className="hidden text-right sm:block">
                      {absent ? <span className="text-[13px] text-stone-300">—</span>
                        : <LecturePrix marche={marche} juste={p.cote_juste} />}
                    </span>
                  )}

                  {/* Victoire · Top 3 (ordinateur) */}
                  <div className="hidden items-center gap-3 sm:flex" title={fourchette}>
                    {!absent && <Anneau v={p.proba_top1} rang={p.rang_predit} taille={44} />}
                    <div className="min-w-0 flex-1 space-y-1">
                      <p className="flex items-baseline justify-between text-[10px] text-stone-500">
                        <span>Victoire</span><b className="text-[12px] font-bold tabular-nums text-stone-900">{pct(p.proba_top1)}</b>
                      </p>
                      <BarreFine v={p.proba_top1} ton={absent ? "neutre" : fav ? "or" : podiumRang ? "podium" : "neutre"} />
                      <p className="flex items-baseline justify-between text-[10px] text-stone-500">
                        <span>Top 3</span><b className="text-[12px] font-bold tabular-nums text-stone-900">{pct(p.proba_top3)}</b>
                      </p>
                      <BarreFine v={p.proba_top3} ton="place" />
                    </div>
                  </div>

                  {/* Téléphone : chiffres en tuiles sous le nom */}
                  <dl className="col-span-3 grid grid-cols-3 gap-1.5 text-[11px] tabular-nums sm:hidden">
                    <div className="rounded-xl bg-[#FCFAF5] px-2.5 py-1.5 ring-1 ring-inset ring-[#EFE8D8]">
                      <dt className="text-[9.5px] font-semibold uppercase tracking-wide text-stone-500">Cote</dt>
                      <dd className="text-[13px] font-bold text-slate-900" style={SG}>{marche != null ? cote(marche) : "—"}</dd>
                    </div>
                    <div className="rounded-xl bg-[#FCFAF5] px-2.5 py-1.5 ring-1 ring-inset ring-[#EFE8D8]">
                      <dt className="text-[9.5px] font-semibold uppercase tracking-wide text-stone-500">Juste · prix</dt>
                      <dd className="flex flex-wrap items-center gap-1">
                        <span className="text-[13px] font-semibold text-slate-700" style={SG}>{p.cote_juste != null ? coteJuste(p.cote_juste) : "—"}</span>
                        {!absent && <LecturePrix marche={marche} juste={p.cote_juste} />}
                      </dd>
                    </div>
                    <div className="rounded-xl bg-[#FCFAF5] px-2.5 py-1.5 ring-1 ring-inset ring-[#EFE8D8]">
                      <dt className="text-[9.5px] font-semibold uppercase tracking-wide text-stone-500">Top 3</dt>
                      <dd className="text-[13px] font-bold text-slate-900" style={SG}>{pct(p.proba_top3)}</dd>
                      <BarreFine v={p.proba_top3} ton="place" />
                    </div>
                  </dl>
                </div>
              </li>
            );
          })}
        </ol>
      </div>

      {/* Pied minimal : la légende vit dans « Comment lire ». Seule la mention
          obligatoire reste à vue. */}
      <footer className="border-t border-stone-100 bg-[#FCFAF5] px-4 py-2.5 text-[10.5px] text-stone-500 sm:px-5">
        Aide à la décision — aucune garantie de gain.
      </footer>
    </section>
  );
}

/** État verrouillé, affiché à la place de la table selon le plan de l'abonné. */
export function ClassementVerrouille({ titre, texte, action }: { titre: string; texte: string; action: React.ReactNode }) {
  return (
    <section className={cn("p-7 text-center", CARTE_CLS)}>
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

/** Signaux d'une ligne RÉVÉLÉE de l'aperçu.
 *
 *  Même vocabulaire et mêmes couleurs que la table des abonnés (`Signaux`) —
 *  c'est le but : ce que voit ici un prospect sur un cheval écarté est
 *  exactement ce qu'il lira sur les seize autres en s'abonnant. Rien n'est
 *  reconstitué côté client : le serveur ne joint ces signaux qu'aux lignes
 *  qu'il a déjà décidé de nommer. */
function SignauxApercu({ signaux }: { signaux?: ApercuSignal[] }) {
  if (!signaux?.length) return null;
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[10.5px] leading-tight text-stone-600">
      {signaux.map((s, i) => {
        const st = SENS[s.sens] ?? SENS.neutre;
        return (
          <span key={`${s.label}-${i}`} title={s.detail || undefined} className="inline-flex cursor-help items-center gap-1">
            <span className={cn("text-[7px]", st.fg)} aria-hidden="true">{st.fleche}</span>
            {nettoie(s.label)}
          </span>
        );
      })}
    </div>
  );
}

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
 *    • les DERNIÈRES lignes entièrement nommées, avec cote, cote juste et les
 *      SIGNAUX réellement retenus contre elles : savoir quel cheval le modèle
 *      écarte, et pourquoi, prouve la profondeur de l'analyse sans construire
 *      le moindre pari.
 *  Ce qui reste payant : le haut du classement, c'est-à-dire la sélection.
 *
 *  Les identités masquées ne sont pas cachées en CSS : l'endpoint `apercu` ne
 *  les envoie pas au navigateur (cf. api/routes/predictions.py).
 */
export function ClassementApercu({
  apercu, onLegende,
}: {
  apercu: ApercuAnalyse;
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
    <section className={cn("overflow-hidden", CARTE_CLS)}>
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-4 pb-3 pt-4 sm:px-5">
        <div className="min-w-0">
          <h3 className="font-display text-[16px] font-bold leading-tight text-slate-900">
            Le classement de l&apos;algorithme
          </h3>
          <p className="mt-0.5 text-[11.5px] text-stone-600">
            {lignes.length} chevaux notés · ordre du modèle de classement
            {!revele && apercu.nb_ecartes > 0
              ? ` · ${apercu.nb_ecartes} écartés sous 3 % de chances`
              : ""}
          </p>
        </div>
        <span className="ml-auto rounded-full bg-amber-50 px-3 py-1 text-[11px] font-semibold text-amber-800 ring-1 ring-amber-200">
          {revele ? "course courue · classement complet" : "aperçu gratuit"}
        </span>
      </header>

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
                {l.cote_juste != null ? coteJuste(l.cote_juste) : "—"}
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
                  {l.cote_juste != null && <span>Juste {coteJuste(l.cote_juste)}</span>}
                  {l.proba_top3 != null && <span>Top-3 {pct(l.proba_top3)}</span>}
                </div>
                <SignauxApercu signaux={l.signaux} />
              </div>

              <span className="hidden text-right font-display text-[14px] font-semibold tabular-nums text-slate-900 sm:block">
                {l.cote != null ? cote(l.cote) : "—"}
              </span>
              <span className="hidden text-right font-display text-[14px] tabular-nums text-slate-600 sm:block">
                {l.cote_juste != null ? coteJuste(l.cote_juste) : "—"}
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

      {/* Le pied ne vend plus : l'unique appel à l'abonnement de l'onglet vit
          dans son propre bandeau, sous la démonstration. Ici, une phrase — celle
          qui évite le contresens le plus fréquent sur cette table. */}
      <footer className="flex flex-col gap-2 border-t border-stone-100 bg-stone-50/60 px-4 py-3 sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-4 sm:px-5">
        <p className="min-w-0 flex-1 text-[11.5px] leading-5 text-stone-600">
          {revele
            ? "Ce classement était établi avant le départ."
            : "Le rang vient d'un modèle d'ordonnancement dédié : deux chevaux peuvent afficher la même probabilité sans être au même rang."}
        </p>
        {onLegende && (
          <button
            type="button"
            onClick={onLegende}
            className="inline-flex shrink-0 items-center gap-1 text-[12px] font-medium text-stone-600 underline underline-offset-2 hover:text-amber-800"
          >
            <HelpCircle className="h-3.5 w-3.5" aria-hidden="true" /> Comment lire ce classement
          </button>
        )}
      </footer>
    </section>
  );
}
