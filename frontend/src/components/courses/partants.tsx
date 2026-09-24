"use client";

/* Section « Partants » de la fiche course : le tableau du champ et la fiche
   dépliée de chaque cheval. Aucune donnée neuve ni calcul métier : tout vient
   de `partant` (fiche + `analyse` calculée côté serveur) et de la prédiction du
   cheval. Le travail est de rendre chaque chiffre lisible sans légende externe :
   libellés en clair, verdicts en mots (« bon prix », « en progression »), et une
   mise en page propre au téléphone plutôt que des colonnes masquées. */
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
/* eslint-disable @next/next/no-img-element -- casaques PMU externes, déjà légères */
import {
  Activity, ArrowDownUp, ChevronDown, Gauge, HelpCircle, MapPin, Trophy,
  TrendingDown, TrendingUp, Users,
} from "lucide-react";
import { MusiqueDisplay, RunningStyleBadge } from "@/components/courses/badges";
import { formatMontantDevise, cn } from "@/lib/utils";
import { LecturePrix, formatCoteFr, formatCoteJusteFr } from "@/components/courses/classement";

const formatCote = (c: number | null | undefined) => (c ? formatCoteFr(c) : "—");
const formatCoteJuste = (c: number | null | undefined) => (c ? formatCoteJusteFr(c) : "—");

// ─── Types (sous-ensemble structurel des types de la page course) ────────────
type Analyse = {
  forme: { taux_top3: number | null; recent_win_rate: number | null; regularite: number | null; tendance: number | null };
  contexte: {
    pref_distance: number | null; pref_terrain: number | null; pref_hippodrome: number | null;
    nb_distance: number | null; nb_terrain: number | null; nb_hippodrome: number | null;
  };
  elo: { trend_30j: number | null; pct_rank: number | null };
  marche: { spi: number | null; steam: number | null; valeur_latente: number | null; decote: number | null };
  vitesse: { stamina: number | null };
  jockey_stats: { taux_victoire: number | null; taux_place: number | null; roi: number | null; victoires_saison: number | null; courses_saison: number | null } | null;
  entraineur_stats: { taux_victoire: number | null; taux_place: number | null; roi: number | null; victoires_saison: number | null; courses_saison: number | null } | null;
  points: { txt: string; type: string }[];
};

export type PartantFiche = {
  participation_id: string;
  numero: number;
  nom_cheval: string;
  age: number | null;
  sexe: string | null;
  jockey: string | null;
  entraineur: string | null;
  cote_pmu: number | null;
  cote_betfair_exchange: number | null;
  cote_min: number | null;
  cote_max: number | null;
  nb_sources: number;
  mouvement_cote_pct: number | null;
  musique: string | null;
  non_partant: boolean;
  elo_global: number | null;
  deferre: string | null;
  oeilleres: string | null;
  premier_deferre: boolean;
  premieres_oeilleres: boolean;
  running_style: string | null;
  changement_jockey: boolean;
  jours_depuis_derniere: number | null;
  poids_reel_pesee: number | null;
  handicap_poids: number | null;
  poids_prevu: number | null;
  numero_corde: number | null;
  casaque_image_url: string | null;
  gains_carriere: number | null;
  gains_carriere_devise: string | null;
  nb_victoires: number | null;
  nb_courses: number | null;
  pere: string | null;
  mere: string | null;
  pere_de_mere: string | null;
  asso_jockey_entraineur_taux: number | null;
  asso_jockey_entraineur_nb: number | null;
  jockey_suspendu: boolean;
  entraineur_suspendu: boolean;
  analyse?: Analyse | null;
};

export type PredictionFiche = {
  participation_id: string;
  rang_predit: number;
  proba_top1: number;
  proba_top3: number;
  cote_juste: number | null;
  value_bet: { ev_max: number } | null;
};

type EloChamp = { min: number; max: number; moy: number };

// ─── Helpers ─────────────────────────────────────────────────────────────────
const SG = { fontFamily: "var(--font-space-grotesk), sans-serif" } as const;
const pct = (v: number | null | undefined) => (v == null ? null : Math.round(v * 100));
const clamp = (v: number, lo = 0, hi = 100) => Math.max(lo, Math.min(hi, v));
const signe = (v: number) => (v >= 0 ? "+" : "−");

/** Trois paliers de lecture, partout les mêmes : bon / moyen / faible. */
type Ton = "bon" | "moyen" | "faible" | "neutre";
function tonDe(p: number | null, bon = 60, moyen = 40): Ton {
  if (p == null) return "neutre";
  return p >= bon ? "bon" : p >= moyen ? "moyen" : "faible";
}
const TON_BARRE: Record<Ton, string> = {
  bon: "bg-emerald-500", moyen: "bg-amber-400", faible: "bg-rose-400", neutre: "bg-stone-300",
};
const TON_TEXTE: Record<Ton, string> = {
  bon: "text-emerald-700", moyen: "text-amber-700", faible: "text-rose-700", neutre: "text-stone-500",
};
const TON_PASTILLE: Record<Ton, string> = {
  bon: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  moyen: "bg-amber-50 text-amber-800 ring-amber-200",
  faible: "bg-rose-50 text-rose-800 ring-rose-200",
  neutre: "bg-stone-50 text-stone-500 ring-stone-200",
};

/** Équipement des pieds, en français lisible. Les valeurs viennent du PMU en
 *  constantes tronquées à 30 caractères ; toute valeur inconnue retombe sur un
 *  nettoyage générique plutôt que sur du charabia. */
const LIBELLE_DEFERRE: Record<string, string> = {
  DEFERRE_ANTERIEURS_POSTERIEURS: "Déferré des 4 pieds",
  DEFERRE_ANTERIEURS: "Déferré des antérieurs",
  DEFERRE_POSTERIEURS: "Déferré des postérieurs",
  PROTEGE_ANTERIEURS_DEFERRRE_PO: "Protégé devant · déferré derrière",
  DEFERRE_ANTERIEURS_PROTEGE_POS: "Déferré devant · protégé derrière",
  PROTEGE_ANTERIEURS: "Protégé des antérieurs",
  PROTEGE_POSTERIEURS: "Protégé des postérieurs",
  PROTEGE_ANTERIEURS_POSTERIEURS: "Protégé des 4 pieds",
  REFERRE_ANTERIEURS_POSTERIEURS: "Referré des 4 pieds",
};
const LIBELLE_OEILLERES: Record<string, string> = {
  SANS_OEILLERES: "Sans",
  OEILLERES_CLASSIQUE: "Classiques",
  OEILLERES_AUSTRALIENNES: "Australiennes",
};
const libelleEquipement = (v: string | null | undefined, table: Record<string, string>, defaut: string) => {
  if (!v) return defaut;
  const cle = v.toUpperCase();
  return table[cle] ?? cle.replace(/_/g, " ").toLowerCase().replace(/^./, (c) => c.toUpperCase());
};
const SEXE: Record<string, string> = { M: "Mâle", H: "Hongre", F: "Femelle" };

/** Repos depuis la dernière course : 2 à 5 semaines = fenêtre idéale, plus de
 *  deux mois = retour de coupure (souvent en manque de rythme). */
function repos(j: number | null) {
  if (j == null) return null;
  if (j >= 14 && j <= 35) return { txt: `${j} j de repos`, cls: "text-emerald-700 font-semibold", aide: "Repos idéal (2 à 5 semaines)" };
  if (j > 60) return { txt: `${j} j de repos`, cls: "text-orange-700 font-semibold", aide: "Retour après une longue coupure" };
  return { txt: `${j} j de repos`, cls: "", aide: "Jours depuis sa dernière course" };
}

/** Les trois indicateurs du tableau : même calcul que l'ancienne mini-heatmap
 *  F / A / N, mais nommés en clair. */
function indicateurs(a: Analyse | null | undefined, elo: number | null, eloChamp: EloChamp | null) {
  if (!a) return null;
  const forme = pct(a.forme.taux_top3);
  const vals = [a.contexte.pref_distance, a.contexte.pref_terrain, a.contexte.pref_hippodrome].filter((v): v is number => v != null);
  const aptitude = vals.length ? Math.round((vals.reduce((s, v) => s + v, 0) / vals.length) * 100) : null;
  const niveauBrut = pct(a.elo.pct_rank) ?? (elo != null && eloChamp && eloChamp.max > eloChamp.min
    ? Math.round(((elo - eloChamp.min) / (eloChamp.max - eloChamp.min)) * 100)
    : null);
  // pct_rank peut sortir de [0,100] en bord de distribution : on borne à l'affichage.
  const niveau = niveauBrut == null ? null : clamp(niveauBrut);
  if (forme == null && aptitude == null && niveau == null) return null;
  return [
    { cle: "Forme", v: forme, aide: "Part de ses courses terminées dans les 3 premiers" },
    { cle: "Aptitude", v: aptitude, aide: "Réussite sur cette distance, ce terrain et cet hippodrome" },
    { cle: "Niveau", v: niveau, aide: "Niveau (ELO) situé dans le champ de cette course : 100 = le meilleur" },
  ];
}

// ─── Petites briques visuelles ───────────────────────────────────────────────
function Barre({ v, ton, className }: { v: number; ton: Ton; className?: string }) {
  return (
    <div className={cn("h-1.5 overflow-hidden rounded-full bg-stone-100", className)}>
      <div className={cn("h-full rounded-full transition-[width] duration-500", TON_BARRE[ton])} style={{ width: `${clamp(v, 3)}%` }} />
    </div>
  );
}

function Pastille({ children, className, title }: { children: ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset", className)}>
      {children}
    </span>
  );
}

function MouvementCote({ mv, compact = false }: { mv: number | null; compact?: boolean }) {
  // mouvement_cote_pct > 0 = la cote a BAISSÉ = le cheval est joué.
  if (mv == null || Math.abs(mv) < 5) return null;
  const joue = mv > 0;
  const Icone = joue ? TrendingDown : TrendingUp;
  return (
    <span
      title={joue ? `Cote en baisse de ${Math.abs(mv).toFixed(0)} % : le cheval est joué` : `Cote en hausse de ${Math.abs(mv).toFixed(0)} % : le cheval est délaissé`}
      className={cn("inline-flex items-center gap-0.5 whitespace-nowrap text-[11px] font-semibold", joue ? "text-emerald-700" : "text-rose-600")}
    >
      <Icone className="h-3 w-3" aria-hidden="true" />
      {Math.abs(mv).toFixed(0)} %{!compact && (joue ? " joué" : " délaissé")}
    </span>
  );
}

// ─── Section ─────────────────────────────────────────────────────────────────
type Tri = "numero" | "ia" | "cote";

export function PartantsSection({ partants, predictions, liveCoteMap, confGlobal }: {
  partants: PartantFiche[];
  predictions: PredictionFiche[] | null | undefined;
  liveCoteMap: Record<number, number | null>;
  confGlobal: number | null;
}) {
  const avecPreds = !!predictions && predictions.length > 0;
  const [tri, setTri] = useState<Tri>("numero");
  const [ouvert, setOuvert] = useState<string | null>(null);

  const predPar = useMemo(() => {
    const m = new Map<string, PredictionFiche>();
    for (const p of predictions ?? []) m.set(p.participation_id, p);
    return m;
  }, [predictions]);

  // Échelle ELO DU LOT : un ELO de 960 ne dit rien dans l'absolu, il dit tout
  // comparé aux autres partants. On écarte l'extrême de chaque bout dès 6
  // chevaux, sinon un seul crack tasse tout le champ sur le premier tiers.
  const eloChamp = useMemo<EloChamp | null>(() => {
    const elos = partants.filter((p) => !p.non_partant && p.elo_global != null)
      .map((p) => p.elo_global as number).sort((a, b) => a - b);
    if (elos.length < 3) return null;
    return {
      min: elos.length >= 6 ? elos[1] : elos[0],
      max: elos.length >= 6 ? elos[elos.length - 2] : elos[elos.length - 1],
      moy: elos.reduce((a, b) => a + b, 0) / elos.length,
    };
  }, [partants]);

  // Toutes les barres de victoire partagent la MÊME échelle (le favori du
  // modèle = barre pleine), sinon deux barres égales porteraient deux probas.
  const probaMax = Math.max(...(predictions ?? []).map((p) => p.proba_top1 || 0), 0.01);

  const coteDe = (p: PartantFiche) => liveCoteMap[p.numero] ?? p.cote_pmu;
  const lignes = useMemo(() => {
    const cle = (p: PartantFiche) =>
      tri === "ia" ? (predPar.get(p.participation_id)?.rang_predit ?? 999)
      : tri === "cote" ? (coteDe(p) ?? 9999)
      : p.numero;
    // Non-partants toujours en bas (indiqués, hors pronostic).
    return [...partants].sort((a, b) =>
      Number(!!a.non_partant) - Number(!!b.non_partant) || cle(a) - cle(b) || a.numero - b.numero);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [partants, tri, predPar, liveCoteMap]);

  const nbNP = partants.filter((p) => p.non_partant).length;
  const difficulte = confGlobal == null ? null
    : confGlobal >= 70 ? { txt: "Favori clair", cls: "bg-emerald-50 text-emerald-800 ring-emerald-200" }
    : confGlobal >= 50 ? { txt: "Course ouverte", cls: "bg-amber-50 text-amber-800 ring-amber-200" }
    : { txt: "Course serrée", cls: "bg-rose-50 text-rose-800 ring-rose-200" };

  const TRIS: { cle: Tri; txt: string }[] = [
    { cle: "numero", txt: "N°" },
    ...(avecPreds ? [{ cle: "ia" as Tri, txt: "Pronostic" }] : []),
    { cle: "cote", txt: "Cote" },
  ];

  return (
    <section aria-labelledby="partants-titre" className="overflow-hidden rounded-[20px] border border-[#ECE7DC] bg-white shadow-[0_1px_2px_rgba(0,0,0,.03),0_18px_40px_-32px_rgba(17,24,39,.35)]">
      {/* ── En-tête ── */}
      <header className="flex flex-wrap items-center gap-x-3 gap-y-3 px-4 pb-3 pt-4 sm:px-5">
        <div className="min-w-0">
          <h2 id="partants-titre" className="text-[17px] font-bold leading-tight text-stone-900" style={SG}>Partants</h2>
          <p className="mt-0.5 text-xs text-stone-500">
            {partants.length - nbNP} au départ{nbNP > 0 ? ` · ${nbNP} non-partant${nbNP > 1 ? "s" : ""}` : ""}
            <span className="hidden sm:inline"> · touchez un cheval pour sa fiche complète</span>
          </p>
        </div>
        {difficulte && (
          <Pastille className={cn("ml-auto", difficulte.cls)} title={`Confiance du modèle sur son favori : ${Math.round(confGlobal!)} %`}>
            {difficulte.txt}
          </Pastille>
        )}
        <div className="flex w-full flex-wrap items-center justify-between gap-2">
          <div role="group" aria-label="Trier les partants" className="inline-flex items-center gap-1 rounded-xl bg-stone-100 p-1">
            <ArrowDownUp className="ml-1.5 mr-0.5 h-3.5 w-3.5 text-stone-400" aria-hidden="true" />
            {TRIS.map((t) => (
              <button
                key={t.cle}
                type="button"
                aria-pressed={tri === t.cle}
                onClick={() => setTri(t.cle)}
                className={cn(
                  "rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-700",
                  tri === t.cle ? "bg-white text-stone-900 shadow-sm" : "text-stone-500 hover:text-stone-800",
                )}
              >
                {t.txt}
              </button>
            ))}
          </div>
          <Legende avecPreds={avecPreds} />
        </div>
      </header>

      {/* ── En-tête des colonnes (ordinateur) ── */}
      <div className={cn(
        "hidden items-end gap-4 border-y border-[#F3EFE6] bg-[#FCFAF5] px-5 py-2 text-[10.5px] font-bold uppercase tracking-[.07em] text-stone-400 md:grid",
        avecPreds ? "md:grid-cols-[72px_minmax(0,1fr)_84px_96px_128px_20px]" : "md:grid-cols-[72px_minmax(0,1fr)_84px_20px]",
      )}>
        <span className="text-center">N°</span>
        <span>Cheval</span>
        <span className="text-right" title="Cote du marché PMU — en direct tant que la course n'est pas partie">Cote</span>
        {avecPreds && (
          <>
            <span className="text-right" title="Cote à partir de laquelle le pari devient rentable selon le modèle (1 / probabilité)">Cote juste</span>
            <span className="text-right" title="Probabilité de victoire calculée par le modèle">Victoire</span>
          </>
        )}
        <span />
      </div>

      <ul className="divide-y divide-[#F3EFE6]">
        {lignes.map((p) => (
          <LignePartant
            key={p.participation_id}
            partant={p}
            pred={predPar.get(p.participation_id)}
            cote={coteDe(p)}
            live={liveCoteMap[p.numero] != null}
            avecPreds={avecPreds}
            probaMax={probaMax}
            eloChamp={eloChamp}
            ouvert={ouvert === p.participation_id}
            onToggle={() => setOuvert(ouvert === p.participation_id ? null : p.participation_id)}
          />
        ))}
      </ul>
    </section>
  );
}

// ─── Légende ─────────────────────────────────────────────────────────────────
function Legende({ avecPreds }: { avecPreds: boolean }) {
  return (
    <details className="group relative w-full sm:w-auto">
      <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs font-semibold text-stone-500 hover:text-stone-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-700 [&::-webkit-details-marker]:hidden">
        <HelpCircle className="h-3.5 w-3.5" aria-hidden="true" /> Comment lire ?
      </summary>
      <div className="mt-2 rounded-2xl border border-[#ECE7DC] bg-white p-4 text-xs leading-relaxed text-stone-600 sm:absolute sm:right-0 sm:z-20 sm:w-[340px] sm:shadow-xl">
        <dl className="space-y-2.5">
          <div><dt className="font-bold text-stone-800">Cote</dt><dd>Ce que paie le PMU pour 1 € joué gagnant. La flèche indique si le cheval est joué (cote en baisse) ou délaissé.</dd></div>
          {avecPreds && (
            <>
              <div><dt className="font-bold text-stone-800">Cote juste</dt><dd>Le prix « normal » selon notre modèle. En dessous, l&apos;écart avec la cote du PMU : <b className="text-emerald-700">+ %</b> = le PMU paie plus que la chance du cheval, <b className="text-rose-700">− %</b> = il paie moins, « au prix » = conforme.</dd></div>
              <div><dt className="font-bold text-stone-800">Victoire</dt><dd>Chance de gagner selon le modèle, et en dessous, chance de finir dans les 3.</dd></div>
            </>
          )}
          <div>
            <dt className="font-bold text-stone-800">Forme · Aptitude · Niveau</dt>
            <dd>Forme = % de courses dans les 3 ; Aptitude = réussite sur cette distance, ce terrain et cet hippodrome ; Niveau = rang dans ce champ (100 = le meilleur).</dd>
            <dd className="mt-1.5 flex flex-wrap gap-1.5">
              <Pastille className={TON_PASTILLE.bon}>≥ 60 bon</Pastille>
              <Pastille className={TON_PASTILLE.moyen}>40–59 moyen</Pastille>
              <Pastille className={TON_PASTILLE.faible}>&lt; 40 faible</Pastille>
            </dd>
          </div>
          <div>
            <dt className="font-bold text-stone-800">Musique</dt>
            <dd>Ses dernières places, de la plus récente à la plus ancienne. Or = victoire, bleu = 2ᵉ ou 3ᵉ, rose = non classé ou disqualifié.</dd>
          </div>
        </dl>
      </div>
    </details>
  );
}

// ─── Ligne ───────────────────────────────────────────────────────────────────
function LignePartant({ partant: p, pred, cote, live, avecPreds, probaMax, eloChamp, ouvert, onToggle }: {
  partant: PartantFiche;
  pred: PredictionFiche | undefined;
  cote: number | null;
  live: boolean;
  avecPreds: boolean;
  probaMax: number;
  eloChamp: EloChamp | null;
  ouvert: boolean;
  onToggle: () => void;
}) {
  const panneauId = useId();
  const np = !!p.non_partant;
  const rang = pred?.rang_predit;
  const ind = np ? null : indicateurs(p.analyse, p.elo_global, eloChamp);
  const rep = repos(p.jours_depuis_derniere);
  // Espérance pour 1 € joué : cote × proba − 1 (affichée seulement si le cheval
  // n'est pas déjà signalé comme value bet, qui porte sa propre espérance).
  const ev = !pred?.value_bet && pred && cote && cote > 1 && pred.proba_top1 > 0 ? cote * pred.proba_top1 - 1 : null;
  const probaTxt = pred ? (pred.proba_top1 < 0.005 ? "< 1" : (pred.proba_top1 * 100).toFixed(0)) : null;
  const probaLarg = pred ? clamp((pred.proba_top1 / Math.max(probaMax, 0.01)) * 100, 3) : 0;
  const barreProba = rang === 1 ? "bg-amber-500" : rang != null && rang <= 3 ? "bg-slate-500" : "bg-stone-300";

  const badges = (
    <>
      {np && <Pastille className="bg-stone-200 text-stone-600 ring-stone-300" title="Déclaré non-partant — retiré du pronostic">Non partant</Pastille>}
      {!np && rang != null && rang <= 3 && (
        <Pastille
          className={rang === 1 ? "bg-amber-100 text-amber-900 ring-amber-300" : "bg-slate-100 text-slate-700 ring-slate-200"}
          title={`Classé ${rang === 1 ? "1er" : `${rang}ᵉ`} par le pronostic`}
        >
          {rang === 1 ? "1er" : `${rang}ᵉ`} du prono
        </Pastille>
      )}
      {pred?.value_bet && (
        <Pastille className="bg-emerald-50 text-emerald-800 ring-emerald-200" title="Value bet : le marché paie plus que la chance réelle du cheval">
          ★ Value +{Math.round(pred.value_bet.ev_max * 100)} %
        </Pastille>
      )}
      {ev != null && ev >= 0.05 && (
        <Pastille className="hidden bg-white text-emerald-700 ring-emerald-200 sm:inline-flex" title="Espérance de gain pour 1 € joué gagnant, selon le modèle">
          +{Math.round(ev * 100)} % d&apos;espérance
        </Pastille>
      )}
      {p.changement_jockey && (
        <Pastille className="bg-orange-50 text-orange-800 ring-orange-200" title="Jockey différent de sa dernière course">Nouveau jockey</Pastille>
      )}
      {(p.jockey_suspendu || p.entraineur_suspendu) && (
        <Pastille className="bg-rose-50 text-rose-800 ring-rose-200">{p.jockey_suspendu ? "Jockey suspendu" : "Entraîneur suspendu"}</Pastille>
      )}
      {p.premier_deferre && <Pastille className="bg-amber-50 text-amber-800 ring-amber-200" title="Déferré pour la première fois : souvent un signe d'ambition">1ʳᵉ fois déferré</Pastille>}
      {p.premieres_oeilleres && <Pastille className="hidden bg-amber-50 text-amber-800 ring-amber-200 sm:inline-flex" title="Porte des œillères pour la première fois">1ʳᵉˢ œillères</Pastille>}
      {!np && p.running_style && <span className="hidden sm:inline-flex"><RunningStyleBadge style={p.running_style} /></span>}
      {/* Téléphone : la lecture du prix remplace la colonne « Cote juste ». */}
      {!np && pred?.cote_juste && (
        <span className="inline-flex items-center gap-1 text-[11.5px] text-stone-500 md:hidden" title="Cote juste du modèle et écart avec la cote du PMU">
          Cote juste <b className="font-semibold tabular-nums text-stone-700">{formatCoteJuste(pred.cote_juste)}</b>
          <LecturePrix marche={cote} juste={pred.cote_juste} />
        </span>
      )}
    </>
  );

  // Téléphone : jockey sur sa ligne, puis âge · repos (le « · » de tête d'une
  // ligne renvoyée à la ligne se lisait comme une erreur).
  const meta = (
    <span className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[12.5px] text-stone-500">
      {p.jockey && <span className={cn("w-full font-medium text-stone-700 sm:w-auto", p.jockey_suspendu && "line-through")}>{p.jockey}</span>}
      {p.entraineur && (
        <span className={cn("hidden sm:inline", p.entraineur_suspendu && "line-through")}>
          <span className="text-stone-300" aria-hidden="true">· </span>{p.entraineur}
        </span>
      )}
      {(p.age != null || rep) && (
        <span className="whitespace-nowrap">
          {p.age != null && (
            <><span className="hidden text-stone-300 sm:inline" aria-hidden="true">· </span>{p.age} ans{p.sexe ? ` · ${SEXE[p.sexe] ?? p.sexe}` : ""}</>
          )}
          {rep && (
            <span className={rep.cls} title={rep.aide}>
              <span className={cn("font-normal text-stone-300", p.age == null && "hidden sm:inline")} aria-hidden="true"> · </span>{rep.txt}
            </span>
          )}
        </span>
      )}
    </span>
  );

  const blocCote = np ? (
    <span className="text-sm font-semibold text-stone-400">NP</span>
  ) : (
    <>
      <div className="flex items-center justify-end gap-1.5">
        {live && (
          <span className="relative flex h-1.5 w-1.5" title="Cote en direct">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60 motion-reduce:animate-none" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
          </span>
        )}
        <span className="text-[17px] font-bold tabular-nums leading-none text-stone-900" style={SG}>{formatCote(cote)}</span>
      </div>
      <div className="mt-1 flex justify-end"><MouvementCote mv={p.mouvement_cote_pct} compact /></div>
    </>
  );

  const blocCoteJuste = !pred?.cote_juste ? <span className="text-stone-300">—</span> : (
    <>
      <div className="text-[15px] font-semibold tabular-nums leading-none text-stone-600" style={SG}>
        {formatCoteJuste(pred.cote_juste)}
      </div>
      {!np && (
        <div className="mt-1 flex justify-end">
          <LecturePrix marche={cote} juste={pred.cote_juste} />
        </div>
      )}
    </>
  );

  const blocVictoire = !pred || np ? <span className="text-stone-300">—</span> : (
    <>
      <div className={cn("text-[17px] font-bold tabular-nums leading-none", rang === 1 ? "text-amber-700" : "text-stone-900")} style={SG}>
        {probaTxt} %
      </div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-stone-100">
        <div className={cn("h-full rounded-full", barreProba)} style={{ width: `${probaLarg}%` }} />
      </div>
      <div className="mt-1 text-[11px] text-stone-500" title="Probabilité de finir dans les trois premiers">
        Top 3 : <b className="font-semibold text-stone-700">{(pred.proba_top3 * 100).toFixed(0)} %</b>
      </div>
    </>
  );

  return (
    <li className={cn(np && "opacity-60")}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={ouvert}
        aria-controls={panneauId}
        className={cn(
          "group block w-full px-4 py-3.5 text-left transition-colors sm:px-5 md:grid md:items-center md:gap-4",
          avecPreds ? "md:grid-cols-[72px_minmax(0,1fr)_84px_96px_128px_20px]" : "md:grid-cols-[72px_minmax(0,1fr)_84px_20px]",
          ouvert ? "bg-[#FAF7EF]" : "hover:bg-[#FCFAF5]",
          "focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-amber-700",
        )}
      >
        {/* Identité : casaque + n° (+ nom sur mobile) */}
        <div className="flex items-start gap-3 md:contents">
          <div className="flex shrink-0 justify-center md:w-full">
            <Casaque numero={p.numero} url={p.casaque_image_url} np={np} />
          </div>

          <div className="min-w-0 flex-1">
            <div className="flex items-start gap-2">
              <span className="block min-w-0 flex-1">
                <span className={cn("block text-[15.5px] font-bold leading-snug text-stone-900", np && "text-stone-500 line-through")} style={SG}>
                  {p.nom_cheval}
                </span>
                {meta}
              </span>
              {/* Téléphone : les deux chiffres qu'on cherche d'abord, sans ouvrir la fiche. */}
              <span className="shrink-0 text-right md:hidden">
                {avecPreds && pred && !np && (
                  <span className="block leading-none" title={`Chance de victoire selon le modèle · top 3 : ${(pred.proba_top3 * 100).toFixed(0)} %`}>
                    <b className={cn("text-[18px] font-bold tabular-nums", rang === 1 ? "text-amber-700" : "text-stone-900")} style={SG}>{probaTxt} %</b>
                    <span className="ml-1 text-[10.5px] text-stone-500">victoire</span>
                  </span>
                )}
                <span className={cn("flex items-center justify-end gap-1 text-[12px] text-stone-500", avecPreds && pred && !np && "mt-1")}>
                  {np ? "NP" : (
                    <>
                      {live && <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" title="Cote en direct" />}
                      cote <b className="text-[14px] font-bold tabular-nums text-stone-900" style={SG}>{formatCote(cote)}</b>
                    </>
                  )}
                </span>
                {!np && <span className="mt-1 flex justify-end"><MouvementCote mv={p.mouvement_cote_pct} compact /></span>}
              </span>
              <ChevronDown
                aria-hidden="true"
                className={cn("mt-0.5 h-4 w-4 shrink-0 text-stone-400 transition-transform md:hidden", ouvert && "rotate-180")}
              />
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-1.5">{badges}</div>

            {(ind || p.musique) && (
              <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-2">
                {ind && (
                  <div className="flex flex-wrap gap-1.5">
                    {ind.map((i) => (
                      <Pastille key={i.cle} className={TON_PASTILLE[tonDe(i.v)]} title={`${i.aide}${i.v != null ? ` : ${i.v} %` : " : non disponible"}`}>
                        <span className="font-medium opacity-80">{i.cle}</span>
                        <span className="tabular-nums">{i.v != null ? i.v : "—"}</span>
                      </Pastille>
                    ))}
                  </div>
                )}
                {p.musique && (
                  <div className="md:hidden lg:block" title="Musique : dernières places, la plus récente à gauche">
                    <MusiqueDisplay musique={abregerMusique(p.musique, 5)} />
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Colonnes chiffrées — ordinateur */}
        <div className="hidden text-right md:block">{blocCote}</div>
        {avecPreds && <div className="hidden text-right md:block">{blocCoteJuste}</div>}
        {avecPreds && <div className="hidden text-right md:block">{blocVictoire}</div>}
        <ChevronDown
          aria-hidden="true"
          className={cn("hidden h-5 w-5 text-stone-400 transition-transform group-hover:text-stone-600 md:block", ouvert && "rotate-180")}
        />
      </button>

      <div id={panneauId} hidden={!ouvert}>
        {ouvert && (
          <div className="border-t border-[#F3EFE6] bg-[#FAF7EF] px-3 pb-5 pt-4 sm:px-5">
            <FichePartant partant={p} cote={cote} eloChamp={eloChamp} />
          </div>
        )}
      </div>
    </li>
  );
}

/** Casaque en vignette, numéro en pastille dans le coin : le numéro reste ce
 *  qu'on coche sur un ticket, la casaque ce qu'on reconnaît pendant la course.
 *  Sans image (ou si elle ne charge pas), seul le numéro s'affiche, en grand. */
function Casaque({ numero, url, np }: { numero: number; url: string | null; np: boolean }) {
  const [echec, setEchec] = useState<string | null>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  // Une image en échec AVANT l'hydratation ne déclenche jamais `onError` côté
  // React : on la détecte au montage, sinon le texte alternatif s'affiche.
  useEffect(() => {
    const el = imgRef.current;
    if (el && url && el.complete && el.naturalWidth === 0) setEchec(url);
  }, [url]);
  const image = !!url && echec !== url;
  if (!image) {
    return (
      <span
        aria-label={`Numéro ${numero}`}
        className={cn("inline-flex h-11 w-11 items-center justify-center rounded-xl text-[17px] font-bold tabular-nums text-white md:h-12 md:w-12",
          np ? "bg-stone-400" : "bg-[#172033]")}
        style={SG}
      >
        {numero}
      </span>
    );
  }
  return (
    <span className="inline-flex flex-col items-center">
      <span className={cn("inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-b from-white to-stone-100 ring-1 ring-inset ring-[#ECE7DC] md:h-14 md:w-14", np && "grayscale")}>
        <img
          ref={imgRef}
          src={url!}
          alt={`Casaque du n°${numero}`}
          width={40}
          height={40}
          loading="lazy"
          onError={() => setEchec(url)}
          className="h-10 w-10 object-contain drop-shadow-[0_1px_1px_rgba(0,0,0,.18)] md:h-11 md:w-11"
        />
      </span>
      <span
        aria-label={`Numéro ${numero}`}
        className={cn("relative -mt-2 inline-flex h-6 min-w-7 items-center justify-center rounded-lg px-1.5 text-[13px] font-bold tabular-nums text-white ring-2 ring-white",
          np ? "bg-stone-400" : "bg-[#172033]")}
        style={SG}
      >
        {numero}
      </span>
    </span>
  );
}

/** Garde les `n` premières performances de la musique (les plus récentes). */
function abregerMusique(musique: string, n: number) {
  const tokens = musique.match(/\(\d{2,4}\)|[0-9A-Za-z][a-z]/g) || [];
  const perfs = tokens.filter((t) => !t.startsWith("("));
  return perfs.slice(0, n).join("");
}

// ─── Fiche dépliée ───────────────────────────────────────────────────────────
function Carte({ icone: Icone, titre, children, className }: {
  icone: typeof Activity; titre: string; children: ReactNode; className?: string;
}) {
  return (
    <section className={cn("rounded-2xl border border-[#ECE7DC] bg-white p-4", className)}>
      <h4 className="mb-3 flex items-center gap-2 text-[11px] font-bold uppercase tracking-[.08em] text-stone-500">
        <span className="inline-flex h-6 w-6 items-center justify-center rounded-lg bg-amber-50 text-amber-700 ring-1 ring-amber-200">
          <Icone className="h-3.5 w-3.5" aria-hidden="true" />
        </span>
        {titre}
      </h4>
      {children}
    </section>
  );
}

/** Ligne libellé → valeur, avec barre optionnelle. */
function Mesure({ libelle, valeur, detail, barre, ton = "neutre" }: {
  libelle: string; valeur: ReactNode; detail?: string; barre?: number | null; ton?: Ton;
}) {
  return (
    <div className="py-1.5">
      <div className="flex items-baseline gap-2 text-[13px]">
        <span className="text-stone-600">{libelle}</span>
        {detail && <span className="text-[11px] text-stone-400">{detail}</span>}
        <span className={cn("ml-auto font-bold tabular-nums", TON_TEXTE[ton] === TON_TEXTE.neutre ? "text-stone-900" : TON_TEXTE[ton])} style={SG}>{valeur}</span>
      </div>
      {barre != null && <Barre v={barre} ton={ton} className="mt-1.5" />}
    </div>
  );
}

function Tendance({ v, haut, bas }: { v: number; haut: string; bas: string }) {
  const up = v > 0;
  const Icone = up ? TrendingUp : TrendingDown;
  return (
    <p className={cn("mt-2 inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset",
      up ? "bg-emerald-50 text-emerald-800 ring-emerald-200" : "bg-rose-50 text-rose-800 ring-rose-200")}>
      <Icone className="h-3.5 w-3.5" aria-hidden="true" /> {up ? haut : bas}
    </p>
  );
}

function FichePartant({ partant: p, cote, eloChamp }: { partant: PartantFiche; cote: number | null; eloChamp: EloChamp | null }) {
  const a = p.analyse;
  const js = a?.jockey_stats, es = a?.entraineur_stats;
  const elo = p.elo_global;
  const top3 = pct(a?.forme.taux_top3);
  const vicRec = pct(a?.forme.recent_win_rate);
  const regul = pct(a?.forme.regularite);
  const aptitudes = a ? ([
    ["Distance", pct(a.contexte.pref_distance), a.contexte.nb_distance],
    ["Terrain", pct(a.contexte.pref_terrain), a.contexte.nb_terrain],
    ["Hippodrome", pct(a.contexte.pref_hippodrome), a.contexte.nb_hippodrome],
  ] as const).filter(([, v]) => v != null) : [];
  const eloPos = elo != null && eloChamp && eloChamp.max > eloChamp.min
    ? clamp(((elo - eloChamp.min) / (eloChamp.max - eloChamp.min)) * 100) : null;
  const moyPos = eloChamp && eloChamp.max > eloChamp.min
    ? clamp(((eloChamp.moy - eloChamp.min) / (eloChamp.max - eloChamp.min)) * 100) : null;
  const tauxCarriere = p.nb_courses ? Math.round(((p.nb_victoires ?? 0) / p.nb_courses) * 100) : null;
  const signaux = a ? [
    a.marche.spi != null && a.marche.spi >= 0.15 && { txt: `Argent des pros (${Math.round(a.marche.spi * 100)} %)`, aide: "Part des mises venant de parieurs professionnels" },
    a.marche.valeur_latente != null && a.marche.valeur_latente >= 0.2 && { txt: "Sous-coté", aide: "Le marché le sous-estime par rapport à ses chances" },
    a.marche.steam != null && a.marche.steam >= 0.2 && { txt: "Mouvement de cote brutal", aide: "Grosse vague de mises en peu de temps" },
    a.marche.decote != null && a.marche.decote >= 0.2 && { txt: "Décote détectée", aide: "Sa cote a nettement baissé" },
  ].filter(Boolean) as { txt: string; aide: string }[] : [];
  const gapBetfair = p.cote_betfair_exchange != null && cote != null && p.cote_betfair_exchange > 1
    ? (cote - p.cote_betfair_exchange) / p.cote_betfair_exchange : null;

  return (
    <div>
      {/* Points clés — le « pourquoi » en une ligne */}
      {a?.points && a.points.length > 0 && (
        <div className="mb-4">
          <p className="mb-2 text-[11px] font-bold uppercase tracking-[.08em] text-stone-500">À retenir</p>
          <ul className="flex flex-wrap gap-2">
            {a.points.map((pt, i) => {
              const cls = pt.type === "+" ? "bg-emerald-50 text-emerald-800 ring-emerald-200"
                : pt.type === "-" ? "bg-rose-50 text-rose-800 ring-rose-200"
                : "bg-amber-50 text-amber-800 ring-amber-200";
              const sym = pt.type === "+" ? "▲" : pt.type === "-" ? "▼" : "●";
              return (
                <li key={i} className={cn("inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[12.5px] font-semibold ring-1 ring-inset", cls)}>
                  <span aria-hidden="true" className="text-[10px]">{sym}</span>{pt.txt}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {/* Forme */}
        <Carte icone={Activity} titre="Forme récente">
          {p.musique ? (
            <>
              <MusiqueDisplay musique={p.musique} />
              <p className="mt-1.5 text-[11px] text-stone-400">La plus récente à gauche · or = victoire · bleu = 2ᵉ-3ᵉ</p>
            </>
          ) : <p className="text-[13px] text-stone-500">Pas encore de musique connue.</p>}
          {(top3 != null || vicRec != null || regul != null) && (
            <div className="mt-3 border-t border-stone-100 pt-2">
              {top3 != null && <Mesure libelle="Termine dans les 3" valeur={`${top3} %`} barre={top3} ton={tonDe(top3)} />}
              {vicRec != null && <Mesure libelle="Victoires récentes" valeur={`${vicRec} %`} />}
              {regul != null && <Mesure libelle="Régularité" valeur={`${regul} %`} ton={tonDe(regul)} />}
            </div>
          )}
          {a?.forme.tendance != null && Math.abs(a.forme.tendance) > 0.05 && (
            <Tendance v={a.forme.tendance} haut="En progression" bas="En baisse de forme" />
          )}
        </Carte>

        {/* Aptitudes */}
        {aptitudes.length > 0 && (
          <Carte icone={MapPin} titre="Conditions du jour">
            <p className="mb-1 text-[12px] text-stone-500">Sa réussite dans les mêmes conditions qu&apos;aujourd&apos;hui :</p>
            {aptitudes.map(([lbl, v, nb]) => (
              <Mesure
                key={lbl}
                libelle={lbl}
                detail={nb ? `sur ${nb} course${nb > 1 ? "s" : ""}` : undefined}
                valeur={`${v} %`}
                barre={v}
                ton={tonDe(v)}
              />
            ))}
          </Carte>
        )}

        {/* Niveau */}
        {(elo != null || p.running_style || a?.vitesse.stamina != null) && (
          <Carte icone={Gauge} titre="Niveau">
            {elo != null && (
              <>
                <div className="flex items-end gap-2">
                  <span className={cn("text-[26px] font-bold leading-none tabular-nums", eloChamp && elo >= eloChamp.moy ? "text-amber-700" : "text-stone-900")} style={SG}>
                    {Math.round(elo)}
                  </span>
                  <span className="pb-0.5 text-xs text-stone-500">points ELO</span>
                  {eloChamp && (
                    <span className={cn("ml-auto rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset",
                      elo >= eloChamp.moy ? "bg-emerald-50 text-emerald-800 ring-emerald-200" : "bg-stone-50 text-stone-600 ring-stone-200")}>
                      {elo >= eloChamp.moy ? "Au-dessus du lot" : "Sous la moyenne"}
                    </span>
                  )}
                </div>
                {eloPos != null && eloChamp && (
                  <div className="mt-4">
                    <div className="relative h-2 rounded-full bg-gradient-to-r from-stone-100 via-stone-200 to-amber-200">
                      {moyPos != null && (
                        <span className="absolute -top-1 bottom-[-4px] w-0.5 rounded bg-stone-400" style={{ left: `${moyPos}%` }} title={`Moyenne du champ : ${Math.round(eloChamp.moy)}`} />
                      )}
                      <span
                        className="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-amber-600 shadow"
                        style={{ left: `${eloPos}%` }}
                        aria-hidden="true"
                      />
                    </div>
                    <div className="mt-1.5 flex justify-between text-[11px] text-stone-400 tabular-nums">
                      <span>Plus faible {Math.round(eloChamp.min)}</span>
                      <span>moy. {Math.round(eloChamp.moy)}</span>
                      <span>Plus fort {Math.round(eloChamp.max)}</span>
                    </div>
                  </div>
                )}
              </>
            )}
            {a?.elo.trend_30j != null && Math.abs(a.elo.trend_30j) >= 2 && (
              <Tendance v={a.elo.trend_30j} haut="Niveau en hausse sur 30 j" bas="Niveau en baisse sur 30 j" />
            )}
            <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[12px] text-stone-600">
              {p.running_style && <RunningStyleBadge style={p.running_style} />}
              {a?.vitesse.stamina != null && Math.abs(a.vitesse.stamina) >= 0.25 && (
                <span>{a.vitesse.stamina > 0 ? "Tient bien la distance" : "Plus à l'aise sur la vitesse"}</span>
              )}
            </div>
          </Carte>
        )}

        {/* Marché */}
        {cote != null && (
          <Carte icone={TrendingUp} titre="Marché">
            <div className="flex flex-wrap items-end gap-x-3 gap-y-1">
              <span className="text-[26px] font-bold leading-none tabular-nums text-stone-900" style={SG}>{formatCote(cote)}</span>
              <MouvementCote mv={p.mouvement_cote_pct} />
            </div>
            <div className="mt-3 border-t border-stone-100 pt-2">
              {p.cote_min != null && p.cote_max != null && p.cote_min !== p.cote_max && (
                <Mesure libelle="Fourchette" detail={p.nb_sources ? `${p.nb_sources} sources` : undefined} valeur={`${formatCote(p.cote_min)} – ${formatCote(p.cote_max)}`} />
              )}
              {gapBetfair != null && (
                <Mesure
                  libelle="Betfair"
                  detail={Math.abs(gapBetfair) >= 0.08 ? (gapBetfair > 0 ? `PMU ${signe(gapBetfair)}${Math.abs(Math.round(gapBetfair * 100))} % : plus généreux` : `PMU ${signe(gapBetfair)}${Math.abs(Math.round(gapBetfair * 100))} % : moins généreux`) : "même prix qu'au PMU"}
                  valeur={formatCote(p.cote_betfair_exchange)}
                  ton={gapBetfair >= 0.08 ? "bon" : gapBetfair <= -0.08 ? "faible" : "neutre"}
                />
              )}
            </div>
            {signaux.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {signaux.map((s) => <Pastille key={s.txt} className="bg-amber-50 text-amber-800 ring-amber-200" title={s.aide}>{s.txt}</Pastille>)}
              </div>
            )}
          </Carte>
        )}

        {/* Jockey & entraîneur */}
        <Carte icone={Users} titre="Jockey & entraîneur">
          <Personne
            role="Jockey"
            nom={p.jockey}
            marque={p.jockey_suspendu ? "Suspendu" : p.changement_jockey ? "Nouveau" : null}
            marqueCls={p.jockey_suspendu ? "bg-rose-50 text-rose-800 ring-rose-200" : "bg-orange-50 text-orange-800 ring-orange-200"}
            stats={js}
          />
          <div className="my-3 border-t border-stone-100" />
          <Personne
            role="Entraîneur"
            nom={p.entraineur}
            marque={p.entraineur_suspendu ? "Suspendu" : null}
            marqueCls="bg-rose-50 text-rose-800 ring-rose-200"
            stats={es}
          />
          {p.asso_jockey_entraineur_taux != null && p.asso_jockey_entraineur_nb != null && p.asso_jockey_entraineur_nb >= 3 && (
            <p className={cn("mt-3 flex items-center gap-2 rounded-xl px-3 py-2 text-xs ring-1 ring-inset",
              p.asso_jockey_entraineur_taux > 0 ? "bg-amber-50 text-amber-900 ring-amber-200" : "bg-stone-50 text-stone-600 ring-stone-200")}>
              <Users className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              <span>Ensemble : <b>{(p.asso_jockey_entraineur_taux * 100).toFixed(0)} % de victoires</b> sur {p.asso_jockey_entraineur_nb} courses</span>
            </p>
          )}
        </Carte>

        {/* Carrière & équipement */}
        <Carte icone={Trophy} titre="Carrière & équipement">
          {p.nb_courses ? (
            <>
              <p className="text-[13px] text-stone-600">
                <b className="text-[22px] font-bold text-stone-900" style={SG}>{p.nb_victoires ?? 0}</b>
                {" "}victoire{(p.nb_victoires ?? 0) > 1 ? "s" : ""} en <b className="text-stone-900">{p.nb_courses}</b> courses
              </p>
              <Mesure libelle="Taux de victoire" valeur={`${tauxCarriere} %`} barre={tauxCarriere} ton={tonDe(tauxCarriere, 20, 10)} />
              {/* Le PMU renvoie les gains dans la devise LOCALE de la réunion : sans
                  devise connue on n'affiche rien plutôt qu'une unité inventée. */}
              {p.gains_carriere != null && p.gains_carriere > 0 && p.gains_carriere_devise && (
                <Mesure libelle="Gains" valeur={formatMontantDevise(p.gains_carriere, p.gains_carriere_devise)} />
              )}
            </>
          ) : null}
          {(p.pere || p.mere) && (
            <p className="mt-1 text-[12px] leading-relaxed text-stone-500">
              <span className="font-semibold text-stone-700">Origines :</span>{" "}
              {p.pere ?? "?"} et {p.mere ?? "?"}{p.pere_de_mere ? ` (par ${p.pere_de_mere})` : ""}
            </p>
          )}
          <div className={cn(!!(p.nb_courses || p.pere || p.mere) && "mt-3 border-t border-stone-100 pt-3")}>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
              <Info libelle="Ferrure" valeur={libelleEquipement(p.deferre, LIBELLE_DEFERRE, "Non déferré")} neuf={p.premier_deferre} />
              <Info libelle="Œillères" valeur={libelleEquipement(p.oeilleres, LIBELLE_OEILLERES, "Sans")} neuf={p.premieres_oeilleres} />
              {(p.handicap_poids ?? p.poids_prevu) != null && (
                <Info libelle="Poids" valeur={`${p.handicap_poids ?? p.poids_prevu} kg${p.poids_reel_pesee != null ? ` (pesée ${p.poids_reel_pesee})` : ""}`} />
              )}
              {p.numero_corde != null && <Info libelle="Corde" valeur={String(p.numero_corde)} />}
              {p.age != null && <Info libelle="Âge" valeur={`${p.age} ans${p.sexe ? ` · ${SEXE[p.sexe] ?? p.sexe}` : ""}`} />}
              {p.jours_depuis_derniere != null && <Info libelle="Dernière course" valeur={`il y a ${p.jours_depuis_derniere} j`} />}
            </dl>
          </div>
        </Carte>
      </div>
    </div>
  );
}

function Personne({ role, nom, marque, marqueCls, stats }: {
  role: string;
  nom: string | null;
  marque: string | null;
  marqueCls: string;
  stats: { taux_victoire: number | null; taux_place: number | null; roi: number | null; victoires_saison: number | null; courses_saison: number | null } | null | undefined;
}) {
  const v = pct(stats?.taux_victoire), pl = pct(stats?.taux_place);
  const roi = stats?.roi != null ? Math.round(stats.roi * 100) : null;
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-stone-400">{role}</span>
        {marque && <Pastille className={marqueCls}>{marque}</Pastille>}
      </div>
      <p className="mt-0.5 text-[14px] font-bold text-stone-900">{nom || "—"}</p>
      {v != null && (
        <div className="mt-2 grid grid-cols-3 gap-2 text-center">
          <MiniKpi titre="Victoires" valeur={`${v} %`} aide={stats?.victoires_saison != null && stats.courses_saison ? `${stats.victoires_saison} sur ${stats.courses_saison} cette saison` : "Taux de victoire cette saison"} />
          <MiniKpi titre="Placé" valeur={pl != null ? `${pl} %` : "—"} aide="Taux de places cette saison" />
          <MiniKpi
            titre="Rentabilité"
            valeur={roi != null ? `${signe(roi)}${Math.abs(roi)} %` : "—"}
            aide="Gain ou perte pour 1 € joué sur chacune de ses courses cette saison"
            cls={roi == null ? undefined : roi >= 0 ? "text-emerald-700" : "text-rose-600"}
          />
        </div>
      )}
    </div>
  );
}

function MiniKpi({ titre, valeur, aide, cls }: { titre: string; valeur: string; aide: string; cls?: string }) {
  return (
    <div className="rounded-xl bg-stone-50 px-1.5 py-2" title={aide}>
      <div className={cn("text-[14px] font-bold tabular-nums text-stone-900", cls)} style={SG}>{valeur}</div>
      <div className="mt-0.5 text-[10.5px] text-stone-500">{titre}</div>
    </div>
  );
}

function Info({ libelle, valeur, neuf = false }: { libelle: string; valeur: string; neuf?: boolean }) {
  return (
    <div>
      <dt className="text-[11px] text-stone-500">{libelle}</dt>
      <dd className="mt-0.5 text-[13px] font-semibold text-stone-900">
        {valeur}
        {neuf && <span className="ml-1.5 rounded-full bg-amber-50 px-1.5 py-px text-[10px] font-bold text-amber-800 ring-1 ring-inset ring-amber-200">1ʳᵉ fois</span>}
      </dd>
    </div>
  );
}
