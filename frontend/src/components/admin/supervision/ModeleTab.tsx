"use client";

/**
 * Onglet « Modèle » — la trajectoire de l'algorithme, version après version.
 *
 * Un réentraînement par nuit produit une nouvelle version : la question utile
 * n'est pas « quelle est la métrique aujourd'hui » mais « va-t-elle dans le bon
 * sens, et l'écart entre entraînement et walk-forward se creuse-t-il ».
 */

import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Cpu, GitBranch, Scale, TrendingDown, TrendingUp } from "lucide-react";
import { ChartTooltip, GRID, axisLine, axisTick, tickLine } from "@/components/charts/chart-kit";
import { cn } from "@/lib/utils";
import { Empty, Note, Section, StatTile, num, pct, signedPct } from "./kit";
import type { AlgoEvolutionPayload, VerdictMarche } from "./types";
import type { AvantageMarche } from "./OutilsApprentissage";

interface CalibBin { lo: number; hi: number; n: number; proba_moy: number; freq_reelle: number }
interface CalibPayload {
  reliable?: boolean; verdict?: string; n_obs?: number; ece?: number;
  brier?: number; base_rate?: number; bins?: CalibBin[];
}
interface ConvergencePayload {
  par_semaine?: Array<{ semaine: string; n: number; brier: number | null; precision_top3: number | null; precision_top1: number | null }>;
  edge_histo?: Array<{ date: string; win_filtre: number | null; win_baseline: number | null; roi: number | null; edge_ok: boolean }>;
}

// Sous ce nombre d'observations, l'écart annoncé/réel d'une tranche est du bruit.
const MIN_OBS_BIN = 30;

function delta(v: number | null | undefined, digits = 4, higherIsBetter = true) {
  if (v == null || !isFinite(v)) return <span className="text-muted-foreground">—</span>;
  const good = higherIsBetter ? v > 0 : v < 0;
  const Icon = v > 0 ? TrendingUp : TrendingDown;
  return (
    <span className={`inline-flex items-center gap-0.5 ${v === 0 ? "text-muted-foreground" : good ? "text-emerald-700" : "text-red-700"}`}>
      <Icon className="h-3 w-3" />
      {v > 0 ? "+" : "−"}{Math.abs(v).toFixed(digits)}
    </span>
  );
}

/** D'où vient le delta marché, et ce que ça autorise à en conclure. */
const SOURCES_RANG: Record<string, { label: string; aide: string }> = {
  hold_out: {
    label: "hold-out",
    aide: "Mesuré sur le modèle réellement déployé, sur les 20 % de courses les plus récentes qu'il n'a pas vues. C'est la mesure qui fait foi.",
  },
  h2h: {
    label: "duel champion/challenger",
    aide: "Même modèle, mais sur l'échantillon restreint du duel. Comparable, sur moins de courses.",
  },
  walk_forward: {
    label: "walk-forward",
    aide: "Mesuré sur un XGBoost jetable ré-entraîné fold par fold : il décrit le dataset, pas le modèle déployé. Non comparable à un hold-out.",
  },
};

/**
 * Le verdict que la page ne posait pas : le modèle apporte-t-il quelque chose que
 * la cote ne dit pas déjà ?
 *
 * Deux précautions tenues ici, parce que sans elles le chiffre serait pire
 * qu'absent :
 *
 *  1. La SOURCE est affichée. Les versions antérieures à la migration 0045
 *     portent un delta issu du walk-forward (≈ +0,019) qui n'est pas comparable
 *     au hold-out de la version courante (−0,0354). Une mesure non comparable
 *     est grisée et ne devient jamais un verdict vert ou rouge.
 *  2. Ce delta juge le MODÈLE NU, pas le produit servi. Le produit passe ensuite
 *     par le mélange avec le marché, qui rattrape ce déficit et le ramène à
 *     PARITÉ avec la cote (mesuré, cf. la bannière suivante : −0,0019, IC 95 %
 *     [−0,0051 ; +0,0014] sur 4 430 courses). Lire ce chiffre comme « le site
 *     conseille moins bien qu'un tri par cote » serait donc faux, et c'est
 *     l'erreur que la mention ci-dessous prévient.
 */
function VerdictMarcheBanniere({ v }: { v?: VerdictMarche | null }) {
  if (!v) return null;
  const src = v.source ? SOURCES_RANG[v.source] : null;
  const mesure = v.delta != null;
  const conclut = mesure && v.comparable;
  const bat = v.bat_le_marche === true;

  const ton = !conclut
    ? "border-border bg-muted/40"
    : bat
      ? "border-emerald-200 bg-emerald-50/60"
      : "border-red-200 bg-red-50/60";
  const tonValeur = !conclut ? "text-muted-foreground" : bat ? "text-emerald-700" : "text-red-700";

  return (
    <section className={cn("rounded-2xl border p-4 sm:p-5", ton)}>
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold">
            <Scale className="h-4 w-4 text-muted-foreground/60" />
            Le modèle bat-il la cote&nbsp;?
          </h3>
          <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
            Écart entre son classement intra-course et celui d&apos;un simple tri par cote PMU,
            sur le même échantillon. Négatif, le classement serait meilleur sans modèle.
          </p>
        </div>
        <span
          title={src?.aide}
          className={cn(
            "shrink-0 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-semibold",
            v.comparable
              ? "border-border bg-card text-muted-foreground"
              : "border-amber-200 bg-amber-50 text-amber-800",
          )}
        >
          mesure&nbsp;: {src?.label ?? "non renseignée"}
        </span>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-xl border border-border bg-card p-3">
          <div className="text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">
            Écart
          </div>
          <div className={cn("mt-1 text-xl font-semibold tabular-nums", tonValeur)}>
            {mesure ? `${v.delta! > 0 ? "+" : "−"}${Math.abs(v.delta!).toFixed(4)}` : "—"}
          </div>
          <div className="mt-0.5 text-[11px] leading-snug text-muted-foreground">
            {!mesure
              ? "aucune mesure disponible"
              : !v.comparable
                ? "non comparable, aucun verdict"
                : bat
                  ? "le modèle apporte quelque chose"
                  : "la cote seule classerait mieux"}
          </div>
        </div>
        <div className="rounded-xl border border-border bg-card p-3">
          <div className="text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">
            Classement modèle
          </div>
          <div className="mt-1 text-xl font-semibold tabular-nums">
            {v.rank_auc?.toFixed(4) ?? "—"}
          </div>
          <div className="mt-0.5 text-[11px] text-muted-foreground">AUC intra-course</div>
        </div>
        <div className="rounded-xl border border-border bg-card p-3">
          <div className="text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">
            Classement cote
          </div>
          <div className="mt-1 text-xl font-semibold tabular-nums">
            {v.market_rank_auc?.toFixed(4) ?? "—"}
          </div>
          <div className="mt-0.5 text-[11px] text-muted-foreground">même échantillon</div>
        </div>
        <div className="rounded-xl border border-border bg-card p-3">
          <div className="text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">
            Porte sur
          </div>
          <div className="mt-1 text-base font-semibold">Le modèle seul</div>
          <div className="mt-0.5 text-[11px] leading-snug text-muted-foreground">
            avant le mélange avec le marché
          </div>
        </div>
      </div>

      <Note>
        Le modèle est entraîné sur le RÉSIDU du marché : la cote a été retirée de son vecteur
        d&apos;apprentissage, il n&apos;a donc jamais eu pour mission de battre la cote tout seul.
        Ce que reçoit l&apos;abonné est le mélange des deux, et c&apos;est la bannière suivante qui
        le mesure. Un écart négatif ici signale que le résidu appris s&apos;affaiblit — pas que
        les conseils sont moins bons qu&apos;un tri par cote.
      </Note>
    </section>
  );
}

/** Un écart et son intervalle, avec la seule règle qui vaille : pas d'IC, pas de verdict. */
function Ecart({
  label, valeur, ic, conclut, aide, sensPositif = true,
}: {
  label: string;
  valeur?: number | null;
  ic?: [number, number] | null;
  conclut?: boolean;
  aide?: string;
  sensPositif?: boolean;
}) {
  const mesure = valeur != null;
  const bon = mesure && (sensPositif ? valeur > 0 : valeur < 0);
  return (
    <div className="rounded-xl border border-border bg-card p-3" title={aide}>
      <div className="text-[11px] font-semibold uppercase leading-tight tracking-[0.06em] text-muted-foreground">
        {label}
      </div>
      <div
        className={cn(
          "mt-1 text-xl font-semibold tabular-nums",
          // Non concluant = gris. Un écart dont l'intervalle traverse zéro n'est
          // pas un petit avantage, c'est une absence de résultat.
          !mesure || !conclut ? "text-muted-foreground" : bon ? "text-emerald-700" : "text-red-700",
        )}
      >
        {mesure ? `${valeur > 0 ? "+" : "−"}${Math.abs(valeur).toFixed(4)}` : "—"}
      </div>
      <div className="mt-0.5 text-[11px] leading-snug text-muted-foreground">
        {ic ? (
          <>
            IC 95 % {ic[0] > 0 ? "+" : "−"}{Math.abs(ic[0]).toFixed(4)} →{" "}
            {ic[1] > 0 ? "+" : "−"}{Math.abs(ic[1]).toFixed(4)}
            {!conclut && <> · contient zéro</>}
          </>
        ) : (
          "intervalle non calculable"
        )}
      </div>
    </div>
  );
}

/**
 * Le pendant honnête de la bannière précédente : ce n'est pas le modèle nu qu'on
 * sert. La probabilité affichée a traversé les calibrations et le MÉLANGE avec le
 * marché, et le mélange renverse la conclusion.
 *
 * Mesuré le 2026-09-07 sur 4 430 courses : le modèle nu est prouvé SOUS la cote
 * (−0,0168, IC [−0,0224 ; −0,0112]), le produit servi est à PARITÉ (−0,0019, IC
 * [−0,0051 ; +0,0014] — il contient zéro, donc aucun verdict), et la chaîne de
 * correction apporte +0,0146 (IC [+0,0108 ; +0,0185], concluant).
 *
 * Le troisième chiffre est le plus utile des trois : il est le seul resté nettement
 * positif sur toutes les fenêtres testées, et c'est lui qui justifie l'existence de
 * la chaîne de correction.
 */
function AvantageServiBanniere({ a }: { a?: AvantageMarche | null }) {
  if (!a) return null;
  if (!a.mesure_disponible) {
    return (
      <div className="rounded-2xl border border-border bg-muted/40 p-4 text-[11px] leading-relaxed text-muted-foreground sm:p-5">
        <b className="text-foreground">Avantage du produit servi : pas encore mesurable.</b>{" "}
        {a.raison ?? "mesure indisponible"}. Aucune valeur n&apos;est affichée à la place — un
        échantillon trop court ne devient pas un verdict en étant arrondi.
      </div>
    );
  }
  return (
    <section className="rounded-2xl border border-border bg-card p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold">
            <Scale className="h-4 w-4 text-muted-foreground/60" />
            Et le produit RÉELLEMENT servi&nbsp;?
          </h3>
          <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
            Ce que voit l&apos;abonné n&apos;est pas le modèle nu : la probabilité affichée a traversé
            les calibrations et le mélange avec le marché. Comparaison appariée, course par
            course, sur les prédictions figées avant le départ.
          </p>
        </div>
        <span className="shrink-0 whitespace-nowrap rounded-full border border-border bg-muted px-2 py-0.5 text-[11px] font-semibold text-muted-foreground">
          {num(a.n_courses)} courses · {a.fenetre_jours} j
        </span>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Ecart
          label="Produit servi vs cote"
          valeur={a.delta_servi_vs_marche}
          ic={a.ic95_servi_vs_marche}
          conclut={a.conclut}
          aide="Classement de la probabilité affichée moins celui d'un tri par cote, sur les mêmes courses."
        />
        <Ecart
          label="Modèle nu vs cote"
          valeur={a.delta_brut_vs_marche}
          ic={a.ic95_brut_vs_marche}
          conclut={a.ic95_brut_vs_marche ? a.ic95_brut_vs_marche[1] < 0 || a.ic95_brut_vs_marche[0] > 0 : false}
          aide="La sortie du modèle avant toute correction. Négatif et concluant : attendu, il apprend le résidu du marché."
        />
        <Ecart
          label="Apport de la chaîne"
          valeur={a.apport_de_la_chaine}
          ic={a.ic95_apport_de_la_chaine}
          conclut={a.apport_conclut}
          aide="Ce que les calibrations et le mélange ajoutent au modèle nu. C'est ce qui justifie leur existence."
        />
      </div>

      <Note>
        Un écart dont l&apos;intervalle contient zéro n&apos;est PAS un petit avantage : c&apos;est
        une absence de résultat, et il reste gris. En l&apos;état le produit servi est à parité
        avec la cote — ni au-dessus, ni en dessous, de façon prouvée — pendant que la chaîne de
        correction, elle, rattrape un déficit du modèle nu qui est bien réel.
        {a.mesure_le && (
          <> Mesuré le {new Date(a.mesure_le).toLocaleString("fr-FR", { timeZone: "Europe/Paris", dateStyle: "short", timeStyle: "short" })}.</>
        )}
      </Note>
    </section>
  );
}

export default function ModeleTab({
  algo, calib, converge, avantage,
}: {
  algo?: AlgoEvolutionPayload;
  calib?: CalibPayload;
  converge?: ConvergencePayload;
  avantage?: AvantageMarche | null;
}) {
  if (!algo) return <Empty>Chargement de la trajectoire du modèle…</Empty>;

  const versions = algo.versions ?? [];
  const active = algo.active;
  const d = algo.delta_vs_precedente;
  const semaines = converge?.par_semaine ?? [];

  return (
    <div className="space-y-5">
      {/* Version active */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <StatTile
          label="Version active"
          value={active ? `v${active.version}` : "—"}
          sub={active?.date ? new Date(active.date).toLocaleString("fr-FR", { timeZone: "Europe/Paris", dateStyle: "medium", timeStyle: "short" }) : "—"}
          icon={<Cpu className="h-3.5 w-3.5 text-muted-foreground/40" />}
          footer={
            <span className="text-[11px] text-muted-foreground">
              {num(algo.total_versions)} versions entraînées au total
            </span>
          }
        />
        <StatTile
          label="AUC-ROC"
          value={active?.auc_roc?.toFixed(4) ?? "—"}
          sub={<>vs version précédente {delta(d?.auc_roc)}</>}
          hint="Capacité à classer un gagnant devant un perdant. 0,5 = hasard, 1 = parfait."
        />
        <StatTile
          label="AUC walk-forward"
          value={active?.walk_forward_auc?.toFixed(4) ?? "—"}
          sub={<>vs précédente {delta(d?.walk_forward_auc)}</>}
          // Elle était présentée comme « la seule qui compte vraiment ». Le
          // walk-forward ré-entraîne un XGBoost jetable fold par fold : il décrit
          // le DATASET, pas le modèle qu'on déploie. L'arbitre est le verdict
          // marché affiché juste en dessous.
          hint="AUC d'un modèle jetable ré-entraîné fold par fold : elle mesure le dataset, pas le modèle servi. L'arbitre est le verdict marché ci-dessous."
        />
        <StatTile
          label="Brier"
          value={active?.brier?.toFixed(4) ?? "—"}
          sub={<>vs précédente {delta(d?.brier, 4, false)}</>}
          hint="Écart entre probabilité annoncée et réalité. Plus BAS = mieux calibré."
        />
        <StatTile
          label="Courses d'entraînement"
          value={num(active?.courses_train)}
          sub={`précision top-3 ${pct(active?.precision_top3)}`}
        />
      </div>

      <VerdictMarcheBanniere v={algo.verdict_marche} />
      <AvantageServiBanniere a={avantage} />

      {/* Trajectoire AUC — entraînement vs walk-forward, même unité, même axe */}
      <Section
        title="Trajectoire de l'AUC, version après version"
        desc="Les deux courbes sont dans la même unité. Un écart qui se creuse entre l'AUC d'entraînement et l'AUC walk-forward signale du surapprentissage."
        right={<span className="text-[11px] text-muted-foreground">{versions.length} dernières versions</span>}
      >
        {versions.length < 2 ? (
          <Empty>Moins de deux versions non synthétiques enregistrées.</Empty>
        ) : (
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={versions} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid {...GRID} />
              <XAxis
                dataKey="version" tick={axisTick} axisLine={axisLine} tickLine={tickLine}
                minTickGap={26} tickFormatter={(v) => `v${v}`}
              />
              <YAxis domain={[0.6, 0.9]} tick={axisTick} axisLine={axisLine} tickLine={tickLine} width={44} tickFormatter={(v) => v.toFixed(2)} />
              <ReferenceLine y={0.5} stroke="#EF4444" strokeDasharray="3 3" label={{ value: "hasard", fontSize: 10, fill: "#EF4444", position: "insideTopLeft" }} />
              <Tooltip
                labelFormatter={(l) => `Version ${l}`}
                content={<ChartTooltip valueFormatter={(v) => v.toFixed(4)} labelFormatter={(l) => `Version v${l}`} />}
              />
              <Legend verticalAlign="bottom" height={28} wrapperStyle={{ fontSize: 11, paddingTop: 8 }} />
              <Line type="monotone" dataKey="auc_roc" name="AUC entraînement" stroke="#F59E0B" strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
              <Line type="monotone" dataKey="walk_forward_auc" name="AUC walk-forward" stroke="#3B82F6" strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
        <Note>
          Un décrochage brutal des deux courbes accompagne souvent un changement du volume
          d&apos;entraînement plutôt qu&apos;une régression du code : la colonne « courses » du tableau
          ci-dessous permet de le vérifier version par version avant de conclure.
        </Note>
      </Section>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <Section
          title="Erreur de calibration (Brier), version après version"
          desc="Plus bas = probabilités plus justes. Échelle propre : le Brier n'est pas superposé à l'AUC."
        >
          {versions.length < 2 ? (
            <Empty>Pas assez de versions.</Empty>
          ) : (
            <ResponsiveContainer width="100%" height={210}>
              <LineChart data={versions} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                <CartesianGrid {...GRID} />
                <XAxis dataKey="version" tick={axisTick} axisLine={axisLine} tickLine={tickLine} minTickGap={26} tickFormatter={(v) => `v${v}`} />
                <YAxis domain={["dataMin - 0.01", "dataMax + 0.01"]} tick={axisTick} axisLine={axisLine} tickLine={tickLine} width={48} tickFormatter={(v) => v.toFixed(3)} />
                <Tooltip content={<ChartTooltip valueFormatter={(v) => v.toFixed(4)} labelFormatter={(l) => `Version v${l}`} />} />
                <Line type="monotone" dataKey="brier" name="Brier" stroke="#8B5CF6" strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </Section>

        <Section
          title="Cadence de réentraînement (30 jours)"
          desc="Une barre = un modèle PROMU cette nuit-là. Une journée vide ne dit pas que le réentraînement n'a pas tourné : un challenger rejeté ne laisse aucune barre. L'issue de la dernière nuit est dans l'onglet Outils."
        >
          {(algo.cadence_30j ?? []).length === 0 ? (
            <Empty>Aucun réentraînement sur 30 jours.</Empty>
          ) : (
            <ResponsiveContainer width="100%" height={210}>
              <BarChart data={algo.cadence_30j} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid {...GRID} />
                <XAxis
                  dataKey="jour" tick={axisTick} axisLine={axisLine} tickLine={tickLine} minTickGap={20}
                  tickFormatter={(v: string) => v.slice(8) + "/" + v.slice(5, 7)}
                />
                <YAxis allowDecimals={false} tick={axisTick} axisLine={axisLine} tickLine={tickLine} width={32} />
                <Tooltip cursor={{ fill: "rgba(148,163,184,0.08)" }} content={<ChartTooltip valueFormatter={(v) => `${v} version${v > 1 ? "s" : ""}`} />} />
                <Bar dataKey="n" name="Versions entraînées" fill="#10B981" radius={[3, 3, 0, 0]} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Section>
      </div>

      {/* Convergence : deux graphiques, jamais un double axe */}
      {semaines.length > 1 && (
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
          <Section
            title="Précision, semaine par semaine"
            desc="Part des courses où le gagnant réel figurait dans les 3 (ou en 1re position) du classement prédit. Mesuré sur les courses terminées."
          >
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={semaines} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                <CartesianGrid {...GRID} />
                <XAxis dataKey="semaine" tick={axisTick} axisLine={axisLine} tickLine={tickLine} />
                <YAxis domain={[0, 100]} tick={axisTick} axisLine={axisLine} tickLine={tickLine} width={46} tickFormatter={(v) => `${v} %`} />
                <Tooltip content={<ChartTooltip valueFormatter={(v) => pct(v)} />} />
                <Legend verticalAlign="bottom" height={28} wrapperStyle={{ fontSize: 11, paddingTop: 8 }} />
                <Line type="monotone" dataKey="precision_top3" name="Gagnant dans le top 3" stroke="#F59E0B" strokeWidth={2.5} dot={{ r: 2.5 }} connectNulls isAnimationActive={false} />
                <Line type="monotone" dataKey="precision_top1" name="Gagnant en tête" stroke="#EC4899" strokeWidth={2} dot={{ r: 2 }} connectNulls isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </Section>

          <Section
            title="Erreur Brier, semaine par semaine"
            desc="Plus bas = probabilités mieux calibrées. Graphique séparé : l'erreur et la précision ne se lisent pas sur la même échelle."
          >
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={semaines} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                <CartesianGrid {...GRID} />
                <XAxis dataKey="semaine" tick={axisTick} axisLine={axisLine} tickLine={tickLine} />
                <YAxis domain={[0, 0.4]} tick={axisTick} axisLine={axisLine} tickLine={tickLine} width={44} tickFormatter={(v) => v.toFixed(2)} />
                <ReferenceLine y={0.18} stroke="#10B981" strokeDasharray="4 4" label={{ value: "cible 0,18", fontSize: 10, fill: "#10B981", position: "insideTopRight" }} />
                <Tooltip content={<ChartTooltip valueFormatter={(v) => v.toFixed(4)} />} />
                <Line type="monotone" dataKey="brier" name="Erreur Brier" stroke="#3B82F6" strokeWidth={2.5} dot={{ r: 2.5 }} connectNulls isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </Section>
        </div>
      )}

      {/* Qualité de calibration */}
      {calib?.reliable && (
        <Section
          title="Les probabilités annoncées sont-elles justes ?"
          desc="Pour chaque tranche de probabilité annoncée, la fréquence réellement observée. Une calibration parfaite aligne les deux colonnes."
          right={
            <span className="rounded-full border border-violet-200 bg-violet-50 px-2 py-0.5 text-[11px] font-semibold text-violet-700">
              {calib.verdict} · {num(calib.n_obs)} observations
            </span>
          }
        >
          <div className="grid grid-cols-3 gap-3">
            <StatTile label="Erreur de calibration (ECE)" value={pct((calib.ece ?? 0) * 100)} sub="écart moyen annoncé/réel" />
            <StatTile label="Brier (victoire)" value={calib.brier?.toFixed(4) ?? "—"} sub="plus bas = mieux" />
            <StatTile label="Taux de victoire moyen" value={pct((calib.base_rate ?? 0) * 100)} sub="base de comparaison" />
          </div>
          <div className="mt-4 space-y-1.5">
            {(calib.bins ?? []).filter((b) => b.n > 0).map((b, i) => {
              const ecart = (b.freq_reelle - b.proba_moy) * 100;
              // Une tranche à 9 observations produit un écart de ±22 % par pur
              // hasard : le chiffre reste affiché, l'écart n'est pas colorié.
              const solide = b.n >= MIN_OBS_BIN;
              return (
                <div key={i} className={`flex items-center gap-3 text-[11px] ${solide ? "" : "opacity-55"}`}>
                  <span className="w-16 shrink-0 tabular-nums text-muted-foreground">
                    {Math.round(b.lo * 100)}–{Math.round(b.hi * 100)} %
                  </span>
                  <div className="flex-1">
                    <div className="flex items-center gap-1.5">
                      <div className="h-2 rounded-full bg-blue-500" style={{ width: `${b.proba_moy * 100}%`, minWidth: 2 }} />
                      <span className="text-[11px] text-muted-foreground">annoncé {pct(b.proba_moy * 100, 0)}</span>
                    </div>
                    <div className="mt-0.5 flex items-center gap-1.5">
                      <div className="h-2 rounded-full bg-amber-500" style={{ width: `${b.freq_reelle * 100}%`, minWidth: 2 }} />
                      <span className="text-[11px] text-muted-foreground">réel {pct(b.freq_reelle * 100, 0)}</span>
                    </div>
                  </div>
                  <span className={`w-16 shrink-0 text-right font-mono font-bold tabular-nums ${!solide || Math.abs(ecart) < 3 ? "text-muted-foreground" : ecart > 0 ? "text-emerald-700" : "text-red-700"}`}>
                    {signedPct(ecart, 0)}
                  </span>
                  <span
                    className="w-20 shrink-0 text-right tabular-nums text-muted-foreground/40"
                    title={solide ? `${b.n} observations` : `${b.n} observations — sous ${MIN_OBS_BIN}, l'écart n'est pas interprétable`}
                  >
                    {num(b.n)}{!solide && <span className="ml-1 text-amber-700">·peu</span>}
                  </span>
                </div>
              );
            })}
          </div>
          <Note>
            Bleu = probabilité annoncée par le modèle, ambre = fréquence réellement observée sur les
            courses terminées. Un écart positif signifie que le modèle sous-estime cette tranche.
            Les lignes estompées comptent moins de {MIN_OBS_BIN} observations : leur écart est du
            bruit d&apos;échantillonnage, pas un défaut de calibration.
          </Note>
        </Section>
      )}

      {/* Tableau des versions */}
      <Section title="Historique des versions" desc="Les 60 dernières versions non synthétiques, de la plus récente à la plus ancienne.">
        <div role="region" tabIndex={0} aria-label="Tableau de données, défilement" className="-mx-4 max-h-[26rem] overflow-auto overscroll-contain px-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring sm:-mx-5 sm:px-5">
          <table className="w-full min-w-[640px] text-xs">
            <thead className="sticky top-0 bg-card">
              <tr className="border-b border-border/70 text-[11px] uppercase tracking-wide text-muted-foreground">
                <th className="py-2 pr-3 text-left font-semibold">Version</th>
                <th className="px-2 py-2 text-left font-semibold">Date</th>
                <th className="px-2 py-2 text-right font-semibold">AUC</th>
                <th className="px-2 py-2 text-right font-semibold">Walk-forward</th>
                <th className="px-2 py-2 text-right font-semibold">Brier</th>
                <th className="px-2 py-2 text-right font-semibold" title="Classement du modèle moins celui d'un simple tri par cote PMU, sur le même échantillon.">
                  vs cote
                </th>
                <th className="px-2 py-2 text-right font-semibold">Top-3</th>
                <th className="px-2 py-2 text-right font-semibold">Courses</th>
                <th className="py-2 pl-2 text-left font-semibold">État</th>
              </tr>
            </thead>
            <tbody>
              {[...versions].reverse().map((v) => (
                <tr key={v.version} className={`border-b border-border/50 ${v.actif ? "bg-emerald-50/50" : ""}`}>
                  <td className="py-2 pr-3 font-mono font-semibold text-foreground">v{v.version}</td>
                  <td className="px-2 py-2 text-muted-foreground">
                    {v.date ? new Date(v.date).toLocaleDateString("fr-FR", { timeZone: "Europe/Paris", day: "2-digit", month: "2-digit", year: "2-digit" }) : "—"}
                  </td>
                  <td className="px-2 py-2 text-right font-mono tabular-nums text-foreground">{v.auc_roc?.toFixed(4) ?? "—"}</td>
                  <td className="px-2 py-2 text-right font-mono tabular-nums text-foreground">{v.walk_forward_auc?.toFixed(4) ?? "—"}</td>
                  <td className="px-2 py-2 text-right font-mono tabular-nums text-foreground">{v.brier?.toFixed(4) ?? "—"}</td>
                  {/* Une valeur sans `rank_source` vient du walk-forward : elle est
                      grisée et suivie d'un astérisque, jamais colorée comme un
                      verdict — comparer un walk-forward à un hold-out revient à
                      comparer deux datasets. */}
                  <td
                    className={cn(
                      "px-2 py-2 text-right font-mono tabular-nums",
                      v.rank_delta_market == null
                        ? "text-muted-foreground"
                        : v.rank_source == null
                          ? "text-muted-foreground/60"
                          : v.rank_delta_market > 0
                            ? "text-emerald-700"
                            : "text-red-700",
                    )}
                    title={
                      v.rank_source
                        ? SOURCES_RANG[v.rank_source]?.aide
                        : "Mesure issue du walk-forward : elle décrit le dataset, pas le modèle déployé. Non comparable aux versions mesurées sur hold-out."
                    }
                  >
                    {v.rank_delta_market == null
                      ? "—"
                      : `${v.rank_delta_market > 0 ? "+" : "−"}${Math.abs(v.rank_delta_market).toFixed(4)}${v.rank_source ? "" : " *"}`}
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums text-muted-foreground">{v.precision_top3 != null ? pct(v.precision_top3) : "—"}</td>
                  <td className="px-2 py-2 text-right tabular-nums text-muted-foreground">{num(v.courses_train)}</td>
                  <td className="py-2 pl-2">
                    {v.actif ? (
                      <span className="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700">
                        <GitBranch className="h-3 w-3" /> active
                      </span>
                    ) : v.rollback ? (
                      <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-700">rollback</span>
                    ) : (
                      <span className="text-[11px] text-muted-foreground/40">archivée</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Note>
          « Top-3 » vide sur les anciennes versions = la métrique n&apos;était pas encore mesurée à
          l&apos;époque, pas une précision nulle. Un « vs cote » suivi d&apos;un astérisque vient du
          walk-forward : il décrit le dataset et non le modèle déployé, il n&apos;est donc pas
          comparable aux valeurs colorées et n&apos;autorise aucun verdict.
        </Note>
      </Section>
    </div>
  );
}

