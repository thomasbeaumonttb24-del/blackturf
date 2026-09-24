"use client";

/* Section « Partants » de la fiche course : le tableau du champ et la fiche
   dépliée de chaque cheval. Aucune donnée neuve ni calcul métier : tout vient
   de `partant` (fiche + `analyse` calculée côté serveur) et de la prédiction du
   cheval. Le travail est de rendre chaque chiffre lisible sans légende externe :
   libellés en clair, verdicts en mots (« bon prix », « en progression »), et une
   mise en page propre au téléphone plutôt que des colonnes masquées. */
import { useEffect, useId, useMemo, useRef, useState, type PointerEvent, type ReactNode } from "react";
import {
  Activity, ArrowDownUp, ChevronDown, Crown, Gauge, HelpCircle, MapPin, Trophy,
  TrendingDown, TrendingUp, Users,
} from "lucide-react";
import { CasaqueNumero } from "@/components/courses/identite-cheval";
import { MusiqueDisplay, RunningStyleBadge } from "@/components/courses/badges";
import { formatMontantDevise, cn } from "@/lib/utils";
import { LecturePrix, formatCoteFr, formatCoteJusteFr } from "@/components/courses/classement";
import { BandeauOnglet, LienOnglet, Pastille, SG, difficulteCourse } from "@/components/courses/course-ui";

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

type OngletLie = "marche" | "plan";

export function PartantsSection({ partants, predictions, liveCoteMap, confGlobal, chevalOuvert, onAller }: {
  partants: PartantFiche[];
  predictions: PredictionFiche[] | null | undefined;
  liveCoteMap: Record<number, number | null>;
  confGlobal: number | null;
  /** Numéro du cheval dont la fiche s'ouvre à l'arrivée (lien depuis un autre onglet). */
  chevalOuvert?: number | null;
  /** Aller à un autre onglet depuis la fiche d'un cheval. */
  onAller?: (cle: OngletLie) => void;
}) {
  const avecPreds = !!predictions && predictions.length > 0;
  const [tri, setTri] = useState<Tri>("numero");
  const [ouvert, setOuvert] = useState<string | null>(
    () => partants.find((p) => chevalOuvert != null && p.numero === chevalOuvert)?.participation_id ?? null,
  );
  // Arrivée depuis un autre onglet : on amène la fiche ouverte à l'écran,
  // sous la barre d'onglets collante.
  useEffect(() => {
    if (chevalOuvert == null) return;
    const cible = partants.find((p) => p.numero === chevalOuvert);
    if (!cible) return;
    setOuvert(cible.participation_id);
    const t = window.setTimeout(() => {
      const el = document.getElementById(`partant-${cible.participation_id}`);
      if (!el) return;
      window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 130, behavior: "smooth" });
    }, 80);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chevalOuvert]);

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
  const difficulte = difficulteCourse(confGlobal);
  const favori = avecPreds
    ? partants.find((p) => !p.non_partant && predPar.get(p.participation_id)?.rang_predit === 1)
    : undefined;
  const probaFavori = favori ? predPar.get(favori.participation_id)?.proba_top1 : undefined;

  const TRIS: { cle: Tri; txt: string }[] = [
    { cle: "numero", txt: "N°" },
    ...(avecPreds ? [{ cle: "ia" as Tri, txt: "Pronostic" }] : []),
    { cle: "cote", txt: "Cote" },
  ];

  return (
    <section aria-labelledby="partants-titre" className="space-y-3">
      {/* ── Bandeau d'onglet : panneau teinté et plat, distinct des cartes ── */}
      <BandeauOnglet
        id="partants-titre"
        icone={Users}
        titre="Partants"
        className="mb-5"
        sousTitre={
          <>
            <b className="font-semibold text-stone-900">{partants.length - nbNP}</b> au départ
            {nbNP > 0 ? <> · <b className="font-semibold text-stone-700">{nbNP}</b> non-partant{nbNP > 1 ? "s" : ""}</> : null}
            <span className="hidden sm:inline"> · touchez un cheval pour sa fiche</span>
          </>
        }
        droite={
          <>
            {difficulte && (
              <Pastille className={difficulte.cls} title={`Confiance du modèle sur son favori : ${Math.round(confGlobal!)} %`}>
                {difficulte.txt}
              </Pastille>
            )}
            {favori && probaFavori != null && (
              <span className="inline-flex items-center gap-2 rounded-lg bg-white px-2.5 py-1 ring-1 ring-inset ring-[#E6DCC6]" title="Le cheval que le modèle voit gagner">
                <Crown className="h-3.5 w-3.5 text-amber-600" aria-hidden="true" />
                <span className="text-[11px] text-stone-500">Favori</span>
                <span className="text-[12.5px] font-semibold text-stone-900">N°{favori.numero} {favori.nom_cheval}</span>
                <span className="text-[12.5px] font-bold text-amber-700 tabular-nums">{Math.round(probaFavori * 100)} %</span>
              </span>
            )}
          </>
        }
        bas={
          <>
            <div role="group" aria-label="Trier les partants" className="inline-flex items-center gap-1 rounded-lg bg-white/70 p-0.5 ring-1 ring-inset ring-[#E6DCC6]">
              <ArrowDownUp className="ml-1.5 mr-0.5 h-3.5 w-3.5 text-stone-400" aria-hidden="true" />
              {TRIS.map((t) => (
                <button
                  key={t.cle}
                  type="button"
                  aria-pressed={tri === t.cle}
                  onClick={() => setTri(t.cle)}
                  className={cn(
                    "rounded-md px-3 py-1.5 text-xs font-semibold transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-700",
                    tri === t.cle
                      ? "bg-stone-900 text-white shadow-sm"
                      : "text-stone-500 hover:text-stone-900",
                  )}
                >
                  {t.txt}
                </button>
              ))}
            </div>
            <Legende avecPreds={avecPreds} />
          </>
        }
      />

      {/* ── En-tête des colonnes (ordinateur) ── */}
      <div className={cn(
        "hidden items-end gap-4 px-5 pt-1 text-[10.5px] font-bold uppercase tracking-[.1em] text-stone-400 md:grid",
        avecPreds ? COLS_PREDS : COLS_SANS,
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

      <ul className="space-y-2.5 [perspective:1600px]">
        {lignes.map((p) => (
          <LignePartant
            key={p.participation_id}
            partant={p}
            pred={predPar.get(p.participation_id)}
            cote={coteDe(p)}
            live={liveCoteMap[p.numero] != null}
            avecPreds={avecPreds}
            eloChamp={eloChamp}
            ouvert={ouvert === p.participation_id}
            onToggle={() => setOuvert(ouvert === p.participation_id ? null : p.participation_id)}
            onAller={onAller}
          />
        ))}
      </ul>
    </section>
  );
}

/** Gabarit de colonnes partagé par l'en-tête et les cartes (ordinateur). */
const COLS_PREDS = "md:grid-cols-[72px_minmax(0,1fr)_92px_96px_132px_20px]";
const COLS_SANS = "md:grid-cols-[72px_minmax(0,1fr)_92px_20px]";

// ─── Légende ─────────────────────────────────────────────────────────────────
function Legende({ avecPreds }: { avecPreds: boolean }) {
  return (
    <details className="group relative w-full sm:w-auto">
      <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs font-semibold text-stone-500 hover:text-stone-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-700 [&::-webkit-details-marker]:hidden">
        <HelpCircle className="h-3.5 w-3.5" aria-hidden="true" /> Comment lire ?
      </summary>
      <div className="mt-2 rounded-2xl border border-[#ECE7DC] bg-white p-4 text-xs shadow-xl leading-relaxed text-stone-600 sm:absolute sm:right-0 sm:z-20 sm:w-[340px] sm:shadow-xl">
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
/** Médaille du podium du pronostic : or, argent, bronze. */
const PODIUM: Record<number, { txt: string; piece: string; barre: string; fond: string }> = {
  1: { txt: "1er du prono", piece: "radial-gradient(circle at 32% 28%,#FFF7D6 0%,#FCD34D 32%,#D97706 72%,#92400E 100%)", barre: "from-amber-300 via-amber-500 to-amber-700", fond: "bg-gradient-to-r from-amber-50 via-white to-white" },
  2: { txt: "2ᵉ du prono", piece: "radial-gradient(circle at 32% 28%,#FFFFFF 0%,#E2E8F0 34%,#94A3B8 74%,#475569 100%)", barre: "from-slate-200 via-slate-400 to-slate-600", fond: "bg-gradient-to-r from-slate-50 via-white to-white" },
  3: { txt: "3ᵉ du prono", piece: "radial-gradient(circle at 32% 28%,#FFEAD5 0%,#FDBA74 34%,#C2410C 76%,#7C2D12 100%)", barre: "from-orange-200 via-orange-400 to-orange-700", fond: "bg-gradient-to-r from-orange-50/70 via-white to-white" },
};

function Medaille({ rang }: { rang: number }) {
  const m = PODIUM[rang];
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full bg-white py-0.5 pl-0.5 pr-2 text-[11px] font-bold text-stone-800 shadow-[0_1px_2px_rgba(17,24,39,.08)] ring-1 ring-inset ring-stone-200" title={`Classé ${m.txt.replace(" du prono", "")} par le pronostic`}>
      <span
        aria-hidden="true"
        className="inline-flex h-[18px] w-[18px] items-center justify-center rounded-full text-[10px] font-extrabold text-white shadow-[inset_0_-1px_1px_rgba(0,0,0,.25),inset_0_1px_1px_rgba(255,255,255,.7),0_1px_2px_rgba(0,0,0,.25)] [text-shadow:0_1px_1px_rgba(0,0,0,.35)]"
        style={{ background: m.piece }}
      >
        {rang}
      </span>
      {m.txt}
    </span>
  );
}

/** Jauge circulaire de la chance de victoire : l'arc est la VRAIE probabilité
 *  (25 % = un quart de tour), pas une échelle relative au favori. */
export function Anneau({ v, rang, taille }: { v: number; rang: number | undefined; taille: number }) {
  const id = useId();
  const r = taille / 2 - 4;
  const c = 2 * Math.PI * r;
  const couleurs = rang === 1 ? ["#FCD34D", "#D97706"] : rang != null && rang <= 3 ? ["#94A3B8", "#334155"] : ["#D6D3D1", "#78716C"];
  const txt = v < 0.005 ? "<1" : String(Math.round(v * 100));
  return (
    <span
      className="relative inline-flex shrink-0 items-center justify-center rounded-full bg-gradient-to-b from-white to-stone-100 shadow-[inset_0_1px_0_#fff,0_1px_1px_rgba(17,24,39,.06),0_6px_14px_-8px_rgba(17,24,39,.35)]"
      style={{ width: taille, height: taille }}
      role="img"
      aria-label={`${txt} % de chance de victoire`}
    >
      <svg width={taille} height={taille} className="absolute inset-0 -rotate-90" aria-hidden="true">
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor={couleurs[0]} />
            <stop offset="100%" stopColor={couleurs[1]} />
          </linearGradient>
        </defs>
        <circle cx={taille / 2} cy={taille / 2} r={r} fill="none" stroke="#F1EEE6" strokeWidth="4" />
        <circle
          cx={taille / 2} cy={taille / 2} r={r} fill="none" stroke={`url(#${id})`} strokeWidth="4" strokeLinecap="round"
          strokeDasharray={`${Math.max(0.02, Math.min(1, v)) * c} ${c}`}
          className="transition-[stroke-dasharray] duration-700"
        />
      </svg>
      <span className={cn("relative font-bold tabular-nums leading-none", rang === 1 ? "text-amber-700" : "text-stone-900")} style={{ ...SG, fontSize: taille >= 52 ? 14 : 13 }}>
        {txt}<span className="text-[0.75em]">%</span>
      </span>
    </span>
  );
}

/** Cote façon ticket : chiffre en relief, flèche de mouvement dessous. */
function TicketCote({ cote, live, mv, compact = false }: { cote: number | null; live: boolean; mv: number | null; compact?: boolean }) {
  return (
    <span className={cn(
      "inline-flex items-center gap-1.5 rounded-xl bg-gradient-to-b from-white to-[#F7F3EA] ring-1 ring-inset ring-[#E7E1D3] shadow-[inset_0_1px_0_#fff,0_1px_2px_rgba(17,24,39,.06)]",
      compact ? "px-2 py-1" : "flex-col items-end gap-0.5 px-2.5 py-1.5",
    )}>
      <span className="inline-flex items-center gap-1.5">
        {compact && <span className="text-[10.5px] font-semibold uppercase tracking-wide text-stone-400">Cote</span>}
        {live && (
          <span className="relative flex h-1.5 w-1.5" title="Cote en direct">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60 motion-reduce:animate-none" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
          </span>
        )}
        <span className={cn("font-bold tabular-nums leading-none text-stone-900", compact ? "text-[14px]" : "text-[17px]")} style={SG}>{formatCote(cote)}</span>
      </span>
      <MouvementCote mv={mv} compact />
    </span>
  );
}

function LignePartant({ partant: p, pred, cote, live, avecPreds, eloChamp, ouvert, onToggle, onAller }: {
  partant: PartantFiche;
  pred: PredictionFiche | undefined;
  cote: number | null;
  live: boolean;
  avecPreds: boolean;
  eloChamp: EloChamp | null;
  ouvert: boolean;
  onToggle: () => void;
  onAller?: (cle: OngletLie) => void;
}) {
  const panneauId = useId();
  const carte = useRef<HTMLLIElement>(null);
  const np = !!p.non_partant;
  const rang = pred?.rang_predit;
  const podium = !np && rang != null && rang <= 3 ? PODIUM[rang] : null;
  const ind = np ? null : indicateurs(p.analyse, p.elo_global, eloChamp);
  const rep = repos(p.jours_depuis_derniere);
  // Espérance pour 1 € joué : cote × proba − 1 (affichée seulement si le cheval
  // n'est pas déjà signalé comme value bet, qui porte sa propre espérance).
  const ev = !pred?.value_bet && pred && cote && cote > 1 && pred.proba_top1 > 0 ? cote * pred.proba_top1 - 1 : null;

  // Inclinaison 3D qui suit la souris — ordinateur uniquement (au doigt, la carte
  // s'enfonce légèrement à la pression), coupée carte ouverte et si l'utilisateur
  // demande moins d'animations. Écrit directement les variables CSS : aucun rendu.
  const incliner = (e: PointerEvent<HTMLLIElement>) => {
    const el = carte.current;
    if (!el || e.pointerType !== "mouse" || ouvert) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const r = el.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
    el.style.setProperty("--rx", `${((0.5 - y) * 3).toFixed(2)}deg`);
    el.style.setProperty("--ry", `${((x - 0.5) * 2.4).toFixed(2)}deg`);
    el.style.setProperty("--mx", `${(x * 100).toFixed(1)}%`);
    el.style.setProperty("--my", `${(y * 100).toFixed(1)}%`);
    el.style.setProperty("--lift", "-3px");
  };
  const redresser = () => {
    const el = carte.current;
    if (!el) return;
    el.style.setProperty("--rx", "0deg");
    el.style.setProperty("--ry", "0deg");
    el.style.setProperty("--lift", "0px");
  };

  const badges = (
    <>
      {np && <Pastille className="bg-stone-200 text-stone-600 ring-stone-300" title="Déclaré non-partant — retiré du pronostic">Non partant</Pastille>}
      {podium && <Medaille rang={rang!} />}
      {pred?.value_bet && (
        <Pastille className="bg-gradient-to-b from-emerald-50 to-emerald-100/70 text-emerald-800 ring-emerald-200 shadow-[0_1px_2px_rgba(4,120,87,.12)]" title="Value bet : le marché paie plus que la chance réelle du cheval">
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
    </>
  );

  // Téléphone : jockey sur sa ligne, puis âge · repos (le « · » de tête d'une
  // ligne renvoyée à la ligne se lisait comme une erreur).
  const meta = (
    <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[12.5px] text-stone-500 sm:gap-x-1.5">
      {p.jockey && <span className={cn("w-full font-medium text-stone-700 sm:w-auto", p.jockey_suspendu && "line-through")}>{p.jockey}</span>}
      {p.entraineur && (
        <span className={cn("hidden sm:inline", p.entraineur_suspendu && "line-through")}>
          <span className="text-stone-300" aria-hidden="true">· </span>{p.entraineur}
        </span>
      )}
      {/* Âge et repos en deux morceaux insécables : sur un petit écran le repos
          passe à la ligne entier, sans « · » orphelin en tête de ligne. */}
      {p.age != null && (
        <span className="whitespace-nowrap">
          <span className="hidden text-stone-300 sm:inline" aria-hidden="true">· </span>{p.age} ans{p.sexe ? ` · ${SEXE[p.sexe] ?? p.sexe}` : ""}
        </span>
      )}
      {rep && (
        <span className={cn("whitespace-nowrap", rep.cls)} title={rep.aide}>
          <span className="hidden font-normal text-stone-300 sm:inline" aria-hidden="true">· </span>{rep.txt}
        </span>
      )}
    </span>
  );

  return (
    <li
      id={`partant-${p.participation_id}`}
      ref={carte}
      onPointerMove={incliner}
      onPointerLeave={redresser}
      className={cn(
        "group/carte relative overflow-hidden rounded-2xl ring-1 transition-[transform,box-shadow] duration-300 ease-out [transform-style:preserve-3d]",
        "[transform:translateY(var(--lift,0px))_rotateX(var(--rx,0deg))_rotateY(var(--ry,0deg))] motion-reduce:transition-none",
        "shadow-[inset_0_1px_0_#fff,0_1px_2px_rgba(17,24,39,.05),0_12px_28px_-22px_rgba(17,24,39,.45)] hover:shadow-[inset_0_1px_0_#fff,0_2px_4px_rgba(17,24,39,.05),0_26px_44px_-26px_rgba(146,64,14,.45)]",
        podium ? cn(podium.fond, "ring-[#EADFC6]") : "bg-white ring-[#ECE7DC]",
        np && "opacity-60 saturate-50",
      )}
    >
      {/* Reflet qui suit la souris */}
      <span aria-hidden="true" className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-300 group-hover/carte:opacity-100 [background:radial-gradient(420px_circle_at_var(--mx,50%)_var(--my,50%),rgba(251,191,36,.10),transparent_45%)]" />
      {podium && <span aria-hidden="true" className={cn("absolute inset-y-3 left-0 w-1 rounded-r-full bg-gradient-to-b", podium.barre)} />}

      <button
        type="button"
        onClick={onToggle}
        aria-expanded={ouvert}
        aria-controls={panneauId}
        className={cn(
          "relative block w-full px-3.5 py-3.5 text-left transition-transform active:scale-[.985] sm:px-5 md:grid md:items-center md:gap-4 md:active:scale-100",
          avecPreds ? COLS_PREDS : COLS_SANS,
          "rounded-2xl focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-amber-700",
        )}
      >
        {/* Identité : casaque + n° + nom (+ jauge sur téléphone) */}
        <div className="flex items-start gap-3 md:contents">
          <div className="flex shrink-0 justify-center md:w-full">
            <CasaqueNumero numero={p.numero} imgUrl={p.casaque_image_url} vertical />
          </div>

          <div className="min-w-0 flex-1">
            <div className="flex items-start gap-2.5">
              <span className="block min-w-0 flex-1">
                <span className={cn("block text-[16px] font-bold leading-snug tracking-tight text-stone-900", np && "text-stone-500 line-through")} style={SG}>
                  {p.nom_cheval}
                </span>
                {meta}
              </span>
              {/* Téléphone : la chance de victoire en jauge, lisible d'un coup d'œil. */}
              {avecPreds && pred && !np && (
                <span className="flex shrink-0 flex-col items-center md:hidden">
                  <Anneau v={pred.proba_top1} rang={rang} taille={50} />
                  <span className="mt-1 text-[10px] font-semibold uppercase tracking-wide text-stone-400">Victoire</span>
                  <span className="mt-0.5 whitespace-nowrap text-[11px] text-stone-500" title="Probabilité de finir dans les trois premiers">
                    Top 3 <b className="font-bold tabular-nums text-stone-800">{(pred.proba_top3 * 100).toFixed(0)} %</b>
                  </span>
                </span>
              )}
              <ChevronDown
                aria-hidden="true"
                className={cn("mt-0.5 h-4 w-4 shrink-0 text-stone-400 transition-transform md:hidden", ouvert && "rotate-180")}
              />
            </div>

            {/* Téléphone : la ligne du prix — cote du PMU puis lecture du prix. */}
            {!np && (
              <div className="mt-2.5 flex flex-wrap items-center gap-2 md:hidden">
                <TicketCote cote={cote} live={live} mv={p.mouvement_cote_pct} compact />
                {pred?.cote_juste && (
                  <span className="inline-flex items-center gap-1 text-[11.5px] text-stone-500" title="Cote juste du modèle et écart avec la cote du PMU">
                    juste <b className="font-semibold tabular-nums text-stone-700">{formatCoteJuste(pred.cote_juste)}</b>
                    <LecturePrix marche={cote} juste={pred.cote_juste} />
                  </span>
                )}
              </div>
            )}

            <div className="mt-2 flex flex-wrap items-center gap-1.5">{badges}</div>

            {(ind || p.musique) && (
              <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-2">
                {ind && (
                  <div className="flex flex-wrap gap-1.5">
                    {ind.map((i) => (
                      <Pastille key={i.cle} className={cn(TON_PASTILLE[tonDe(i.v)], "shadow-[inset_0_1px_0_rgba(255,255,255,.8)]")} title={`${i.aide}${i.v != null ? ` : ${i.v} %` : " : non disponible"}`}>
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
        <div className="hidden text-right md:block">
          {np ? <span className="text-sm font-semibold text-stone-400">NP</span> : <TicketCote cote={cote} live={live} mv={p.mouvement_cote_pct} />}
        </div>
        {avecPreds && (
          <div className="hidden text-right md:block">
            {!pred?.cote_juste ? <span className="text-stone-300">—</span> : (
              <>
                <div className="text-[15px] font-semibold tabular-nums leading-none text-stone-600" style={SG}>{formatCoteJuste(pred.cote_juste)}</div>
                {!np && <div className="mt-1.5 flex justify-end"><LecturePrix marche={cote} juste={pred.cote_juste} /></div>}
              </>
            )}
          </div>
        )}
        {avecPreds && (
          <div className="hidden md:flex md:items-center md:justify-end md:gap-3">
            {!pred || np ? <span className="text-stone-300">—</span> : (
              <>
                <span className="text-right text-[11px] leading-tight text-stone-500" title="Probabilité de finir dans les trois premiers">
                  Top 3<br /><b className="text-[13px] font-bold tabular-nums text-stone-800" style={SG}>{(pred.proba_top3 * 100).toFixed(0)} %</b>
                </span>
                <Anneau v={pred.proba_top1} rang={rang} taille={56} />
              </>
            )}
          </div>
        )}
        <ChevronDown
          aria-hidden="true"
          className={cn("hidden h-5 w-5 text-stone-400 transition-transform group-hover/carte:text-stone-600 md:block", ouvert && "rotate-180")}
        />
      </button>

      <div id={panneauId} hidden={!ouvert}>
        {ouvert && (
          <div className="relative border-t border-[#EFE8D8] bg-[#FAF7EF]/80 px-3 pb-5 pt-4 sm:px-5">
            <FichePartant partant={p} cote={cote} eloChamp={eloChamp} />
            {onAller && !np && (
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <span className="text-[12px] text-stone-500">Aller plus loin :</span>
                <LienOnglet onClick={() => onAller("marche")}>Voir le marché</LienOnglet>
                <LienOnglet onClick={() => onAller("plan")}>Mon plan de mise</LienOnglet>
              </div>
            )}
          </div>
        )}
      </div>
    </li>
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
    <section className={cn("rounded-2xl bg-gradient-to-b from-white to-[#FDFBF6] p-4 ring-1 ring-[#ECE7DC] shadow-[inset_0_1px_0_#fff,0_1px_2px_rgba(17,24,39,.04),0_14px_26px_-22px_rgba(17,24,39,.4)]", className)}>
      <h4 className="mb-3 flex items-center gap-2 text-[11px] font-bold uppercase tracking-[.08em] text-stone-500">
        <span className="inline-flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-b from-amber-50 to-amber-100 text-amber-700 ring-1 ring-inset ring-amber-200 shadow-[inset_0_1px_0_#fff,0_2px_4px_-1px_rgba(146,64,14,.25)]">
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
