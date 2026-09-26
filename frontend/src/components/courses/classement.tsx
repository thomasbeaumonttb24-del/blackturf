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

import { Anneau, BoutonAbonnement, CARTE_CLS, IconeTuile, IdentiteMasquee, Pastille, SG } from "@/components/courses/course-ui";
import { useState } from "react";
import { Brain, ChevronDown, HelpCircle, Lock, TrendingUp, Clock3, Trophy } from "lucide-react";
import { CasaqueNumero } from "@/components/courses/identite-cheval";
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
        "shrink-0 font-display font-bold tabular-nums",
        taille === "grand" ? "text-[16px]" : "text-[15px]",
        terne ? "text-stone-600" : "text-slate-900",
      )}>
        <CasaqueNumero numero={numero} />
      </span>
      {/* Nom entier, sur deux lignes au besoin : coupé (« JOYEUSE DE LA B… ») il ne
          servait plus à reconnaître le cheval, et le badge du numéro, non figé,
          se laissait écraser contre lui. */}
      <span className={cn("min-w-0 break-words leading-tight", taille === "grand" ? "text-[13px]" : "text-[12.5px]", terne ? "text-stone-600" : "text-stone-700")}>
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

/** Bandeau « lecture de la course ». Chaque chiffre est une restitution directe des
 *  lignes affichées (somme, compte, écart, rapprochement avec l'arrivée) — jamais un
 *  jugement ajouté par l'interface. Le podium du modèle n'y figure plus : les trois
 *  premiers sont déjà en tête de la table, avec leur médaille. Le bandeau décrit la
 *  COURSE — sa physionomie, l'avis du marché, les prix, le périmètre du calcul. */
function Synthese({
  lignes, signauxParNumero, positionsReelles, calculeA, cotesFigees, coteLive, nonPartants,
}: {
  lignes: ClassementPrediction[];
  signauxParNumero: Record<number, ClassementSignal[]>;
  positionsReelles?: Record<number, number>;
  calculeA?: string | null;
  cotesFigees?: boolean;
  coteLive?: Record<number, number | null>;
  nonPartants?: Set<number>;
}) {
  const partants = lignes.filter((p) => !nonPartants?.has(p.numero));
  const nbNonPartants = lignes.length - partants.length;
  const favModele = partants[0];
  const marcheDe = (p: ClassementPrediction) => coteLive?.[p.numero] ?? p.cote_pmu;

  // Physionomie : part des chances de victoire des trois premiers, et nombre de
  // chevaux que le modèle crédite d'au moins une chance sur dix.
  const concentration = partants.slice(0, 3).reduce((s, p) => s + p.proba_top1, 0);
  const nbSerieux = partants.filter((p) => p.proba_top1 >= 0.1).length;
  const physionomie = concentration >= 0.6 ? "course fermée" : concentration >= 0.45 ? "course disputée" : "course ouverte";

  // Favori du marché : la plus petite cote affichée parmi les partants.
  const favMarche = partants.reduce<{ p: ClassementPrediction; c: number } | null>((best, p) => {
    const c = marcheDe(p);
    if (c == null || !Number.isFinite(c) || c <= 0) return best;
    return best && best.c <= c ? best : { p, c };
  }, null);
  const memeFavori = !!favMarche && !!favModele && favMarche.p.numero === favModele.numero;

  // Écarts de prix : même lecture que la colonne « Lecture du prix ».
  const ecarts = partants
    .map((p) => ({ p, e: ecartPrix(marcheDe(p), p.cote_juste) }))
    .filter((x): x is { p: ClassementPrediction; e: number } => x.e != null);
  const positifs = ecarts.filter((x) => x.e >= ECART_MEILLEUR_PRIX).sort((a, b) => b.e - a.e);

  // Signaux produits par l'analyse, comptés par sens.
  const tous = partants.flatMap((p) => (signauxParNumero[p.numero] ?? []).filter((s) => nettoie(s.label)));
  const nbAtouts = tous.filter((s) => s.sens === "positif").length;
  const nbReserves = tous.filter((s) => s.sens === "negatif").length;

  const gagnantNum = positionsReelles
    ? Number(Object.keys(positionsReelles).find((n) => positionsReelles[Number(n)] === 1))
    : NaN;
  const gagnant = Number.isFinite(gagnantNum) ? lignes.find((p) => p.numero === gagnantNum) : undefined;

  const horodatage = calculeA
    ? new Date(calculeA).toLocaleString("fr-FR", { timeZone: "Europe/Paris", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
    : null;

  const TEINTE_SEG = ["from-amber-300 to-amber-500", "from-slate-300 to-slate-500", "from-orange-300 to-orange-600"];
  const TUILE = "flex flex-col rounded-2xl bg-white px-3.5 py-3 ring-1 ring-[#ECE7DC] shadow-[inset_0_1px_0_#fff,0_1px_2px_rgba(17,24,39,.05),0_10px_22px_-18px_rgba(17,24,39,.4)]";
  const TITRE = "text-[10px] font-bold uppercase tracking-[.1em] text-stone-500";
  const CHIFFRE = "text-[22px] font-bold leading-none tabular-nums";

  return (
    <div className="px-4 pb-4 sm:px-5">
      <p className="mb-2.5 text-[10.5px] font-bold uppercase tracking-[.12em] text-amber-700">Lecture de la course</p>
      <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
        {/* 1 · Physionomie : toutes les chances de victoire en une barre — les trois
            premiers en couleur, le reste du peloton en gris. */}
        <div className={TUILE}>
          <p className={TITRE}>Physionomie</p>
          <p className="mt-1 flex items-baseline gap-1.5">
            <span className={cn(CHIFFRE, "text-stone-900")} style={SG}>{pct(concentration)}</span>
            <span className="text-[11.5px] text-stone-500">{physionomie}</span>
          </p>
          <div className="mt-2.5 flex h-2.5 overflow-hidden rounded-full bg-stone-100 shadow-[inset_0_1px_2px_rgba(0,0,0,.08)]" aria-hidden="true">
            {partants.map((p, i) => (
              <span
                key={p.numero}
                title={`N°${p.numero} : ${pct(p.proba_top1)}`}
                className={cn("h-full", i < 3 ? cn("bg-gradient-to-b", TEINTE_SEG[i]) : i % 2 ? "bg-stone-300" : "bg-stone-200", i > 0 && "border-l border-white/80")}
                style={{ width: `${Math.max(0.5, p.proba_top1 * 100)}%` }}
              />
            ))}
          </div>
          <p className="mt-1.5 text-[10.5px] leading-snug text-stone-500">
            chances des 3 premiers · <b className="font-semibold tabular-nums text-stone-700">{nbSerieux}</b> cheva{nbSerieux > 1 ? "ux" : "l"} à 10 % ou plus
          </p>
        </div>

        {/* 2 · Marché et modèle : désignent-ils le même favori ? */}
        <div className={TUILE}>
          <p className={TITRE}>Favori : marché et modèle</p>
          <div className="mt-1.5 space-y-1.5 text-[12px]">
            <p className="flex min-w-0 items-center justify-between gap-2">
              <span className="shrink-0 text-stone-500">Marché</span>
              {favMarche
                ? <span className="min-w-0 truncate font-semibold text-stone-900">N°{favMarche.p.numero} <span className="font-normal text-stone-500">à</span> <span className="tabular-nums">{cote(favMarche.c)}</span></span>
                : <span className="text-stone-400">cotes indisponibles</span>}
            </p>
            <p className="flex min-w-0 items-center justify-between gap-2">
              <span className="shrink-0 text-stone-500">Modèle</span>
              {favModele
                ? <span className="min-w-0 truncate font-semibold text-stone-900">N°{favModele.numero} <span className="font-normal text-stone-500">·</span> <span className="tabular-nums text-amber-700">{pct(favModele.proba_top1)}</span></span>
                : <span className="text-stone-400">—</span>}
            </p>
          </div>
          {favMarche && favModele && (
            <span className={cn(
              "mt-auto inline-flex w-fit items-center rounded-md px-1.5 py-0.5 text-[10.5px] font-semibold ring-1",
              memeFavori ? "bg-stone-100 text-stone-600 ring-stone-200" : "bg-amber-50 text-amber-800 ring-amber-200/70",
            )}>
              {memeFavori ? "même favori" : "favoris différents"}
            </span>
          )}
        </div>

        {/* 3 · Prix — ou, la course courue, son vainqueur. */}
        <div className={TUILE}>
          {gagnant ? (
            <>
              <p className={TITRE}>Vainqueur</p>
              <p className="mt-1.5 flex min-w-0 items-center gap-1.5 truncate">
                <Identite numero={gagnant.numero} nom={gagnant.nom_cheval} taille="grand" />
              </p>
              <p className={cn("mt-1 text-[12px] font-semibold", gagnant.rang_predit === 1 ? "text-emerald-700" : gagnant.rang_predit <= 3 ? "text-slate-600" : "text-stone-600")}>
                classé {ordinal(gagnant.rang_predit)} par le modèle
              </p>
            </>
          ) : (
            <>
              <p className={TITRE}>Écarts de prix</p>
              <p className="mt-1 flex items-baseline gap-1.5">
                <span className={cn(CHIFFRE, positifs.length > 0 ? "text-emerald-700" : "text-stone-900")} style={SG}>
                  {ecarts.length ? positifs.length : "—"}
                </span>
                <span className="text-[11.5px] leading-snug text-stone-500">
                  {!ecarts.length ? "cotes indisponibles" : positifs.length > 1 ? "chevaux payés au-dessus de leur chance" : positifs.length === 1 ? "cheval payé au-dessus de sa chance" : "aucun écart positif d’au moins 8 %"}
                </span>
              </p>
              {positifs.length > 0 && (
                <p className="mt-auto flex flex-wrap gap-1 pt-2">
                  {positifs.slice(0, 3).map(({ p, e }) => (
                    <span key={p.numero} className="inline-flex items-center gap-1 rounded-md bg-emerald-50 px-1.5 py-0.5 text-[10.5px] font-bold tabular-nums text-emerald-700 ring-1 ring-emerald-200/70">
                      N°{p.numero} <span className="font-semibold">+{Math.round(e * 100)} %</span>
                    </span>
                  ))}
                </p>
              )}
            </>
          )}
        </div>

        {/* 4 · Périmètre du calcul : partants, signaux, fraîcheur. */}
        <div className={TUILE}>
          <p className={TITRE}>Partants et signaux</p>
          <p className="mt-1 flex items-baseline gap-1.5">
            <span className={cn(CHIFFRE, "text-stone-900")} style={SG}>{partants.length}</span>
            <span className="text-[11.5px] text-stone-500">
              partant{partants.length > 1 ? "s" : ""}{nbNonPartants > 0 ? ` · ${nbNonPartants} non-partant${nbNonPartants > 1 ? "s" : ""}` : ""}
            </span>
          </p>
          {(nbAtouts > 0 || nbReserves > 0) && (
            <p className="mt-2 flex flex-wrap gap-1.5 text-[10.5px] font-semibold tabular-nums">
              <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 ring-1 ring-inset", SENS.positif.bg, SENS.positif.fg, SENS.positif.ring)}>
                <span className="text-[7px]" aria-hidden="true">▲</span>{nbAtouts} atout{nbAtouts > 1 ? "s" : ""}
              </span>
              <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 ring-1 ring-inset", SENS.negatif.bg, SENS.negatif.fg, SENS.negatif.ring)}>
                <span className="text-[7px]" aria-hidden="true">▼</span>{nbReserves} réserve{nbReserves > 1 ? "s" : ""}
              </span>
            </p>
          )}
          {horodatage && (
            <p className="mt-auto inline-flex items-center gap-1 pt-2 text-[10.5px] text-stone-500">
              <Clock3 className="h-3 w-3" aria-hidden="true" />
              calculé le {horodatage}{cotesFigees ? " · cotes figées" : ""}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/*  Médailles du classement                                                   */
/* ────────────────────────────────────────────────────────────────────────── */

const PODIUM = {
  1: { piece: "radial-gradient(circle at 32% 28%,#FFF7D6 0%,#FCD34D 32%,#D97706 72%,#92400E 100%)" },
  2: { piece: "radial-gradient(circle at 32% 28%,#FFFFFF 0%,#E2E8F0 34%,#94A3B8 74%,#475569 100%)" },
  3: { piece: "radial-gradient(circle at 32% 28%,#FFEAD5 0%,#FDBA74 34%,#C2410C 76%,#7C2D12 100%)" },
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

  // Les signaux sont TOUJOURS repliés à l'ouverture (deux pastilles puis « +N ») :
  // huit lignes de pastilles écrasaient les colonnes chiffrées, qui portent la
  // décision. Le choix n'est plus mémorisé d'une course à l'autre — un lecteur qui
  // avait déplié une fois retrouvait sinon toutes les fiches dépliées.
  const [signauxOuverts, setSignauxOuverts] = useState(false);
  const basculeSignaux = () => setSignauxOuverts((v) => !v);

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

      <Synthese
        lignes={lignes}
        signauxParNumero={signauxParNumero}
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
  apercu, onLegende, connecte = false, marche,
}: {
  apercu: ApercuAnalyse;
  onLegende?: () => void;
  /** Compte gratuit (true) ou visiteur (false) : décide de l'appel à l'abonnement. */
  connecte?: boolean;
  /** Favori du MARCHÉ (information publique : la plus petite cote du champ). */
  marche?: { numero: number; cote: number } | null;
}) {
  const lignes = apercu.classement ?? [];
  if (!lignes.length) return null;

  const revele = apercu.revele;
  const masquees = lignes.filter((l) => !l.revele);
  const nommees = lignes.filter((l) => l.revele);
  // Le haut du classement (5 lignes) suffit à montrer la distribution ; le reste
  // des lignes masquées tient dans une rangée, puis la queue nommée.
  const hautMasque = revele ? [] : masquees.slice(0, 5);
  const resteMasque = revele ? [] : masquees.slice(5);

  // ── Lecture de la course — mêmes tuiles que l'abonné, calculées sur ce que
  //    l'aperçu envoie déjà (probabilités de chaque rang, agrégats anonymes).
  const probas = lignes.map((l) => l.proba_top1 ?? 0);
  const concentration = probas.slice(0, 3).reduce((a, b) => a + b, 0);
  const nbSerieux = probas.filter((v) => v >= 0.1).length;
  const physionomie = concentration >= 0.6 ? "course fermée" : concentration >= 0.45 ? "course disputée" : "course ouverte";
  const sig = apercu.signaux_course;
  const TEINTE_SEG = ["from-amber-300 to-amber-500", "from-slate-300 to-slate-500", "from-orange-300 to-orange-600"];
  const TUILE = "flex flex-col rounded-2xl bg-white px-3.5 py-3 ring-1 ring-[#ECE7DC] shadow-[inset_0_1px_0_#fff,0_1px_2px_rgba(17,24,39,.05),0_10px_22px_-18px_rgba(17,24,39,.4)]";
  const TITRE = "text-[10px] font-bold uppercase tracking-[.1em] text-stone-500";
  const CHIFFRE = "text-[22px] font-bold leading-none tabular-nums";

  // Colonnes : les mêmes que la table abonné (#, cheval, cote, cote juste,
  // lecture du prix, victoire · top 3).
  const GRILLE = "grid-cols-[40px_minmax(0,1fr)_auto] sm:grid-cols-[40px_minmax(0,1fr)_64px_70px_92px_200px]";

  const LigneChiffres = ({ l, podium, terne }: { l: (typeof lignes)[number]; podium: boolean; terne?: boolean }) => (
    <div className="hidden items-center gap-3 sm:flex">
      <Anneau v={l.proba_top1 ?? 0} rang={podium ? l.rang : undefined} taille={44} />
      <div className="min-w-0 flex-1 space-y-1">
        <p className="flex items-baseline justify-between text-[10px] text-stone-500">
          <span>Victoire</span><b className="text-[12px] font-bold tabular-nums text-stone-900">{pct(l.proba_top1)}</b>
        </p>
        <BarreFine v={l.proba_top1 ?? 0} ton={terne ? "neutre" : l.rang === 1 ? "or" : podium ? "podium" : "neutre"} />
        <p className="flex items-baseline justify-between text-[10px] text-stone-500">
          <span>Top 3</span><b className="text-[12px] font-bold tabular-nums text-stone-900">{pct(l.proba_top3)}</b>
        </p>
        <BarreFine v={l.proba_top3 ?? 0} ton="place" />
      </div>
    </div>
  );

  return (
    <section className={cn("overflow-hidden", CARTE_CLS)}>
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 pb-3 pt-4 sm:px-5">
        <div className="flex min-w-0 items-center gap-2.5">
          <IconeTuile icone={Brain} />
          <div className="min-w-0">
            <h3 className="text-[16px] font-bold leading-tight text-stone-900" style={SG}>
              Le classement de l&apos;algorithme
            </h3>
            <p className="mt-0.5 text-[11.5px] text-stone-500">
              {lignes.length} chevaux notés · du plus probable au moins probable
            </p>
          </div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Pastille className={revele ? "bg-emerald-50 text-emerald-800 ring-emerald-200" : "bg-amber-50 text-amber-800 ring-amber-200"}>
            {revele ? "Course courue · classement ouvert" : <><Lock className="h-3 w-3" aria-hidden="true" />Aperçu gratuit</>}
          </Pastille>
          {onLegende && (
            <button
              type="button"
              onClick={onLegende}
              className="inline-flex min-h-8 items-center gap-1.5 rounded-full bg-white px-3 text-[11.5px] font-semibold text-slate-600 ring-1 ring-stone-200 shadow-[inset_0_1px_0_#fff,0_1px_2px_rgba(17,24,39,.06)] transition-colors hover:bg-amber-50/60 hover:text-amber-900 hover:ring-amber-300"
            >
              <HelpCircle className="h-3.5 w-3.5" aria-hidden="true" /> Comment lire
            </button>
          )}
        </div>
      </header>

      {/* ── Lecture de la course ── */}
      <div className="px-4 pb-4 sm:px-5">
        <p className="mb-2.5 text-[10.5px] font-bold uppercase tracking-[.12em] text-amber-700">Lecture de la course</p>
        <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
          <div className={TUILE}>
            <p className={TITRE}>Physionomie</p>
            <p className="mt-1 flex items-baseline gap-1.5">
              <span className={cn(CHIFFRE, "text-stone-900")} style={SG}>{pct(concentration)}</span>
              <span className="text-[11.5px] text-stone-500">{physionomie}</span>
            </p>
            <div className="mt-2.5 flex h-2.5 overflow-hidden rounded-full bg-stone-100 shadow-[inset_0_1px_2px_rgba(0,0,0,.08)]" aria-hidden="true">
              {probas.map((v, i) => (
                <span
                  key={i}
                  className={cn("h-full", i < 3 ? cn("bg-gradient-to-b", TEINTE_SEG[i]) : i % 2 ? "bg-stone-300" : "bg-stone-200", i > 0 && "border-l border-white/80")}
                  style={{ width: `${Math.max(0.5, v * 100)}%` }}
                />
              ))}
            </div>
            <p className="mt-1.5 text-[10.5px] leading-snug text-stone-500">
              chances des 3 premiers · <b className="font-semibold tabular-nums text-stone-700">{nbSerieux}</b> cheva{nbSerieux > 1 ? "ux" : "l"} à 10 % ou plus
            </p>
          </div>

          <div className={TUILE}>
            <p className={TITRE}>Favori : marché et modèle</p>
            <div className="mt-1.5 space-y-1.5 text-[12px]">
              <p className="flex min-w-0 items-center justify-between gap-2">
                <span className="shrink-0 text-stone-500">Marché</span>
                {marche
                  ? <span className="min-w-0 truncate font-semibold text-stone-900">N°{marche.numero} <span className="font-normal text-stone-500">à</span> <span className="tabular-nums">{cote(marche.cote)}</span></span>
                  : <span className="text-stone-400">cotes indisponibles</span>}
              </p>
              <p className="flex min-w-0 items-center justify-between gap-2">
                <span className="shrink-0 text-stone-500">Modèle</span>
                {revele && nommees[0]?.numero != null
                  ? <span className="min-w-0 truncate font-semibold text-stone-900">N°{nommees[0].numero} <span className="font-normal text-stone-500">·</span> <span className="tabular-nums text-amber-700">{pct(nommees[0].proba_top1)}</span></span>
                  : <span className="inline-flex min-w-0 items-center gap-1.5 font-semibold text-stone-900">
                      <span className="inline-flex items-center gap-1 rounded-md bg-slate-800 px-1.5 py-px text-[10.5px] font-bold text-white/85"><Lock className="h-2.5 w-2.5" aria-hidden="true" />N°?</span>
                      <span className="tabular-nums text-amber-700">{pct(apercu.proba_top1)}</span>
                    </span>}
              </p>
            </div>
            {apercu.accord_marche != null && (
              <span className={cn(
                "mt-auto inline-flex w-fit items-center rounded-md px-1.5 py-0.5 text-[10.5px] font-semibold ring-1",
                apercu.accord_marche ? "bg-stone-100 text-stone-600 ring-stone-200" : "bg-amber-50 text-amber-800 ring-amber-200/70",
              )}>
                {apercu.accord_marche ? "même favori" : "favoris différents"}
              </span>
            )}
          </div>

          <div className={TUILE}>
            <p className={TITRE}>Écarts de prix</p>
            <p className="mt-1 flex items-baseline gap-1.5">
              <span className={cn(CHIFFRE, apercu.nb_value_bets > 0 ? "text-emerald-700" : "text-stone-900")} style={SG}>{apercu.nb_value_bets}</span>
              <span className="text-[11.5px] leading-snug text-stone-500">
                {apercu.nb_value_bets > 1 ? "chevaux payés au-dessus de leur chance" : apercu.nb_value_bets === 1 ? "cheval payé au-dessus de sa chance" : "aucun pari de valeur détecté"}
              </span>
            </p>
            {apercu.nb_value_bets > 0 && (
              <p className="mt-auto flex flex-wrap items-center gap-1 pt-2">
                <span className="inline-flex items-center gap-1 rounded-md bg-slate-800 px-1.5 py-0.5 text-[10.5px] font-bold text-white/85">
                  <Lock className="h-2.5 w-2.5" aria-hidden="true" />N°?
                </span>
                {apercu.ev_max_pct != null && (
                  <span className="inline-flex items-center rounded-md bg-emerald-50 px-1.5 py-0.5 text-[10.5px] font-bold tabular-nums text-emerald-700 ring-1 ring-emerald-200/70">
                    jusqu&apos;à +{apercu.ev_max_pct} %
                  </span>
                )}
              </p>
            )}
          </div>

          <div className={TUILE}>
            <p className={TITRE}>Signaux du champ</p>
            <p className="mt-1 flex items-baseline gap-1.5">
              <span className={cn(CHIFFRE, "text-stone-900")} style={SG}>{sig?.total ?? lignes.length}</span>
              <span className="text-[11.5px] text-stone-500">{sig?.total ? "signaux retenus" : "chevaux notés"}</span>
            </p>
            {sig && sig.total > 0 && (
              <p className="mt-2 flex flex-wrap gap-1.5 text-[10.5px] font-semibold tabular-nums">
                <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 ring-1 ring-inset", SENS.positif.bg, SENS.positif.fg, SENS.positif.ring)}>
                  <span className="text-[7px]" aria-hidden="true">▲</span>{sig.pour} atout{sig.pour > 1 ? "s" : ""}
                </span>
                <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 ring-1 ring-inset", SENS.negatif.bg, SENS.negatif.fg, SENS.negatif.ring)}>
                  <span className="text-[7px]" aria-hidden="true">▼</span>{sig.contre} réserve{sig.contre > 1 ? "s" : ""}
                </span>
              </p>
            )}
            {apercu.nb_criteres > 0 && (
              <p className="mt-auto pt-2 text-[10.5px] text-stone-500">
                sur <b className="font-semibold tabular-nums text-stone-700">{apercu.nb_criteres}</b> critères par cheval
              </p>
            )}
          </div>
        </div>
      </div>

      {/* ── Classement ── */}
      <div className="border-t border-stone-100">
        <div className={cn("hidden items-end gap-3 border-b border-stone-200/70 bg-[#FCFAF5] px-5 py-2 text-[10px] font-bold uppercase tracking-[.1em] text-stone-500 sm:grid", GRILLE)}>
          <span className="text-center">#</span>
          <span>Cheval · signaux</span>
          <span className="text-right">Cote</span>
          <span className="text-right leading-tight" title="Cote à partir de laquelle le pari devient rentable selon le modèle">Cote<br />juste</span>
          <span className="text-right leading-tight" title="Écart entre la cote payée par le marché et la cote juste du modèle">Lecture<br />du prix</span>
          <span className="text-right">Victoire · Top 3</span>
        </div>

        <ol className={cn("divide-y divide-stone-100", revele && "max-h-[40rem] overflow-y-auto")}>
          {hautMasque.map((l) => {
            const podium = l.rang <= 3;
            return (
              <li key={`m${l.rang}`} className={cn("relative px-4 py-3 sm:px-5", l.rang === 1 && "bg-amber-50/40")}>
                {podium && (
                  <span
                    className={cn("absolute inset-y-2 left-0 w-1 rounded-r-full bg-gradient-to-b",
                      l.rang === 1 ? "from-amber-300 to-amber-600" : l.rang === 2 ? "from-slate-300 to-slate-500" : "from-orange-300 to-orange-600")}
                    aria-hidden="true"
                  />
                )}
                <div className={cn("grid items-center gap-x-3 gap-y-2", GRILLE)}>
                  {podium ? <span className="flex justify-center"><Piece rang={l.rang as 1 | 2 | 3} taille={30} /></span> : <Rang rang={l.rang} />}
                  <div className="min-w-0">
                    <IdentiteMasquee largeur={l.rang === 1 ? "10rem" : "8rem"} />
                    <p className="mt-1.5 flex flex-wrap items-center gap-1.5">
                      <span className="inline-flex items-center gap-1 rounded-full bg-stone-50 px-2 py-0.5 text-[10px] font-semibold text-stone-500 ring-1 ring-inset ring-stone-200">
                        <Lock className="h-2.5 w-2.5" aria-hidden="true" />cheval et signaux réservés
                      </span>
                    </p>
                  </div>
                  <span className="flex flex-col items-center sm:hidden">
                    <Anneau v={l.proba_top1 ?? 0} rang={podium ? l.rang : undefined} taille={46} />
                  </span>
                  <span className="hidden text-right text-[14px] tracking-widest text-stone-300 sm:block" aria-label="Cote réservée">•••</span>
                  <span className="hidden text-right text-[14px] tabular-nums text-slate-600 sm:block" style={SG}>
                    {l.cote_juste != null ? coteJuste(l.cote_juste) : "—"}
                  </span>
                  <span className="hidden justify-end sm:flex">
                    <span className="inline-flex items-center gap-1 rounded-md bg-stone-100 px-1.5 py-0.5 text-[10.5px] font-semibold text-stone-500">
                      <Lock className="h-2.5 w-2.5" aria-hidden="true" />réservé
                    </span>
                  </span>
                  <LigneChiffres l={l} podium={podium} />
                  {/* Téléphone */}
                  <dl className="col-span-3 grid grid-cols-3 gap-1.5 text-[11px] tabular-nums sm:hidden">
                    <div className="rounded-xl bg-[#FCFAF5] px-2.5 py-1.5 ring-1 ring-inset ring-[#EFE8D8]">
                      <dt className="text-[9.5px] font-semibold uppercase tracking-wide text-stone-500">Cote</dt>
                      <dd className="text-[13px] font-bold text-stone-300">•••</dd>
                    </div>
                    <div className="rounded-xl bg-[#FCFAF5] px-2.5 py-1.5 ring-1 ring-inset ring-[#EFE8D8]">
                      <dt className="text-[9.5px] font-semibold uppercase tracking-wide text-stone-500">Cote juste</dt>
                      <dd className="text-[13px] font-semibold text-slate-700" style={SG}>{l.cote_juste != null ? coteJuste(l.cote_juste) : "—"}</dd>
                    </div>
                    <div className="rounded-xl bg-[#FCFAF5] px-2.5 py-1.5 ring-1 ring-inset ring-[#EFE8D8]">
                      <dt className="text-[9.5px] font-semibold uppercase tracking-wide text-stone-500">Top 3</dt>
                      <dd className="text-[13px] font-bold text-slate-900" style={SG}>{pct(l.proba_top3)}</dd>
                      <BarreFine v={l.proba_top3 ?? 0} ton="place" />
                    </div>
                  </dl>
                </div>
              </li>
            );
          })}

          {/* Le reste des lignes masquées : une rangée de probabilités et l'appel. */}
          {resteMasque.length > 0 && (
            <li className="relative overflow-hidden bg-gradient-to-b from-[#FCFAF5] to-white px-4 py-4 sm:px-5">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4">
                <div className="min-w-0 sm:flex-1">
                  <p className="m-0 text-[13px] font-bold text-stone-900" style={SG}>
                    + {resteMasque.length} partants classés du {resteMasque[0].rang}ᵉ au {resteMasque[resteMasque.length - 1].rang}ᵉ
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1.5" aria-label="Chances de victoire des lignes suivantes">
                    {resteMasque.map((l) => (
                      <span key={l.rang} className="inline-flex items-center gap-1 rounded-lg bg-white px-2 py-1 text-[11px] ring-1 ring-inset ring-[#ECE7DC]">
                        <b className="font-bold tabular-nums text-stone-500">{l.rang}</b>
                        <span className="h-2.5 w-7 rounded-full" style={{ backgroundImage: "repeating-linear-gradient(115deg,#E7E1D3 0 5px,#F4EFE4 5px 10px)" }} aria-hidden="true" />
                        <b className="font-bold tabular-nums text-stone-900">{pct(l.proba_top1)}</b>
                      </span>
                    ))}
                  </div>
                </div>
                <BoutonAbonnement className="w-full sm:w-auto" connecte={connecte} libelle={connecte ? "Voir le classement nommé" : "Voir le classement — essai 7 jours"} />
              </div>
            </li>
          )}

          {!revele && nommees.length > 0 && (
            <li className="flex items-center gap-2 bg-white px-4 pb-1.5 pt-3 text-[10px] font-bold uppercase tracking-[.1em] text-stone-500 sm:px-5">
              <span className="h-px flex-1 bg-stone-200" aria-hidden="true" />
              Visible gratuitement · le bas du classement
              <span className="h-px flex-1 bg-stone-200" aria-hidden="true" />
            </li>
          )}

          {nommees.map((l) => {
            const podium = revele && l.rang <= 3;
            return (
              <li key={`r${l.rang}`} className={cn("relative px-4 py-3 sm:px-5", revele && l.rang === 1 && "bg-amber-50/40")}>
                {podium && (
                  <span
                    className={cn("absolute inset-y-2 left-0 w-1 rounded-r-full bg-gradient-to-b",
                      l.rang === 1 ? "from-amber-300 to-amber-600" : l.rang === 2 ? "from-slate-300 to-slate-500" : "from-orange-300 to-orange-600")}
                    aria-hidden="true"
                  />
                )}
                <div className={cn("grid items-center gap-x-3 gap-y-2", GRILLE)}>
                  {podium ? <span className="flex justify-center"><Piece rang={l.rang as 1 | 2 | 3} taille={30} /></span> : <Rang rang={l.rang} absent={!revele} />}
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      {l.numero != null && <Identite numero={l.numero} nom={l.nom ?? ""} terne={!revele} />}
                      {l.position != null && <BadgeArrivee position={l.position} />}
                      {!revele && (
                        <span className="rounded-md bg-stone-100 px-1.5 py-0.5 text-[10px] font-semibold text-stone-600">écarté par le modèle</span>
                      )}
                    </div>
                    {l.signaux && l.signaux.length > 0 && (
                      <div className="mt-1.5">
                        <PuceSignaux signaux={l.signaux.map((s) => ({ ...s, score: 0 }))} max={3} />
                      </div>
                    )}
                  </div>
                  <span className="flex flex-col items-center sm:hidden">
                    <Anneau v={l.proba_top1 ?? 0} rang={podium ? l.rang : undefined} taille={46} />
                  </span>
                  <span className="hidden text-right text-[14px] font-semibold tabular-nums text-slate-900 sm:block" style={SG}>
                    {l.cote != null ? cote(l.cote) : "—"}
                  </span>
                  <span className="hidden text-right text-[14px] tabular-nums text-slate-600 sm:block" style={SG}>
                    {l.cote_juste != null ? coteJuste(l.cote_juste) : "—"}
                  </span>
                  <span className="hidden text-right sm:block">
                    <LecturePrix marche={l.cote ?? null} juste={l.cote_juste ?? null} />
                  </span>
                  <LigneChiffres l={l} podium={podium} terne={!revele} />
                  <dl className="col-span-3 grid grid-cols-3 gap-1.5 text-[11px] tabular-nums sm:hidden">
                    <div className="rounded-xl bg-[#FCFAF5] px-2.5 py-1.5 ring-1 ring-inset ring-[#EFE8D8]">
                      <dt className="text-[9.5px] font-semibold uppercase tracking-wide text-stone-500">Cote</dt>
                      <dd className="text-[13px] font-bold text-slate-900" style={SG}>{l.cote != null ? cote(l.cote) : "—"}</dd>
                    </div>
                    <div className="rounded-xl bg-[#FCFAF5] px-2.5 py-1.5 ring-1 ring-inset ring-[#EFE8D8]">
                      <dt className="text-[9.5px] font-semibold uppercase tracking-wide text-stone-500">Juste · prix</dt>
                      <dd className="flex flex-wrap items-center gap-1">
                        <span className="text-[13px] font-semibold text-slate-700" style={SG}>{l.cote_juste != null ? coteJuste(l.cote_juste) : "—"}</span>
                        <LecturePrix marche={l.cote ?? null} juste={l.cote_juste ?? null} />
                      </dd>
                    </div>
                    <div className="rounded-xl bg-[#FCFAF5] px-2.5 py-1.5 ring-1 ring-inset ring-[#EFE8D8]">
                      <dt className="text-[9.5px] font-semibold uppercase tracking-wide text-stone-500">Top 3</dt>
                      <dd className="text-[13px] font-bold text-slate-900" style={SG}>{pct(l.proba_top3)}</dd>
                      <BarreFine v={l.proba_top3 ?? 0} ton="place" />
                    </div>
                  </dl>
                </div>
              </li>
            );
          })}
        </ol>
      </div>

      <footer className="flex flex-col gap-2 border-t border-stone-100 bg-[#FCFAF5] px-4 py-2.5 sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-4 sm:px-5">
        <p className="m-0 min-w-0 flex-1 text-[10.5px] text-stone-500">
          {revele
            ? "Ce classement était établi avant le départ. Aide à la décision — aucune garantie de gain."
            : "Rang, probabilités et cote juste sont ceux de la table abonné ; seuls les noms du haut du classement sont réservés."}
        </p>
      </footer>
    </section>
  );
}
