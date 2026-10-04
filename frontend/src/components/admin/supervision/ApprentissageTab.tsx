"use client";

/**
 * Onglet « Apprentissage » — ce que le système corrige tout seul, et sur quoi.
 *
 * Température de calibration, détecteur de dérive, corrections appliquées à
 * l'inférence, pronostic servi contre le marché, poids appris par profil, ROI par
 * signal, biais contextuels, journal course par course. Tout provient d'états
 * réellement persistés : un module qui n'a pas encore assez de données affiche
 * « en attente », jamais une valeur neutre déguisée en mesure.
 *
 * Audit du 2026-10-04 — ce que la page affirmait à tort :
 *  - « Calibration longshots : active » alors que BT_COLLAPSE_LONGSHOT la saute à
 *    chaque pronostic (le badge testait seulement l'existence de la table) ;
 *  - « confiance −0,05 appliquée » sur des biais contextuels que l'inférence
 *    ignore dès que le méta-apprenant est chargé ;
 *  - un détecteur de dérive TOUJOURS « Stable » : la page lisait `severity`,
 *    l'API renvoie `status` ;
 *  - « Courses de test : 45 494 » qui comptait des chevaux ;
 *  - un « filtre de conviction » qui ne retenait plus que 7 paris et ne mesurait
 *    pas ce que le site sert — remplacé par le pronostic servi contre le marché.
 */

import { useState, type ReactNode } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronUp, Scale, Thermometer, Zap } from "lucide-react";
import { format } from "date-fns";
import { ChartTooltip, GRID, axisLine, axisTick, tickLine } from "@/components/charts/chart-kit";
import {
  DIVERGING_NEG, DIVERGING_POS, Empty, Note, Section, StatTile,
  num, pct, signedPct, tone,
} from "./kit";

/** Dérive d'un groupe de features : poids courant vs poids par défaut du groupe.
 *  Les poids ne gravitent PAS autour de 0 — chaque groupe a son propre défaut
 *  (cotes 1,2 · equip 0,6 · elo 1,0…). Comparer un poids à 0 n'a aucun sens ;
 *  seule la dérive par rapport au défaut du groupe en a un. */
interface FeatureDrift { groupe: string; poids_actuel: number; poids_défaut: number; drift: number }
interface HistoryEntry {
  log_id: string; course_id?: string; hippodrome?: string; discipline?: string;
  brier_score?: number; brier_marche?: number | null; was_surprise?: boolean;
  gagnant_proba_ia?: number; gagnant_rang_predit?: number;
  hors_top3?: boolean; nb_partants?: number; analyzed_at: string;
}
interface BiasRow {
  contexte: string; discipline?: string; terrain?: string; hippodrome?: string;
  nb_courses: number; nb_surprises?: number; taux_surprise: number;
  correction_factor: number; correction_appliquee?: boolean; meta_actif?: boolean;
  seuil_courses?: number; updated_at?: string;
}
interface Ecart { moyen: number; ic_bas: number; ic_haut: number; verdict: string }
interface FenetreSvm {
  n_courses: number; n_courses_cote_finale?: number;
  logloss_servi?: number; logloss_marche_fige?: number; logloss_marche_final?: number;
  ecart_fige?: Ecart; ecart_final?: Ecart;
  top1_servi_pct?: number; top1_favori_pct?: number;
  roi_servi_pct?: number | null; roi_favori_pct?: number | null; partants_moyen?: number;
}
interface SemaineSvm {
  semaine: string; n: number; logloss_servi: number; logloss_marche_fige: number;
  logloss_marche_final: number | null; top1_servi_pct: number; top1_favori_pct: number;
}
interface ServiVsMarche {
  fenetres: Record<string, FenetreSvm>; par_semaine: SemaineSvm[]; mesure_le?: string;
}

/** Statut renvoyé par `DriftDetector.get_drift_report()` : healthy | warning |
 *  critical. La page lisait une clé `severity` qui n'existe pas — la carte
 *  restait « Stable » quoi qu'il arrive. */
const DERIVE: Record<string, { label: string; cls: string; aide: string; ok: boolean }> = {
  critical: {
    label: "Dérive critique",
    cls: "border-red-200 bg-red-50 text-red-700",
    aide: "ADWIN et/ou Page-Hinkley ont détecté une rupture nette de la qualité des probabilités.",
    ok: false,
  },
  warning: {
    label: "Avertissement",
    cls: "border-amber-200 bg-amber-50 text-amber-700",
    aide: "Signal de dérive naissant — à surveiller, pas encore une rupture.",
    ok: false,
  },
  healthy: {
    label: "Stable",
    cls: "border-emerald-200 bg-emerald-50 text-emerald-700",
    aide: "Aucune rupture détectée sur la fenêtre glissante.",
    ok: true,
  },
};

const BADGE = {
  vert: "border-emerald-200 bg-emerald-50 text-emerald-700",
  ambre: "border-amber-200 bg-amber-50 text-amber-800",
  rouge: "border-red-200 bg-red-50 text-red-700",
  gris: "border-border bg-muted/40 text-muted-foreground",
  bleu: "border-blue-200 bg-blue-50 text-blue-700",
} as const;

function Pastille({ ton, children, title }: { ton: keyof typeof BADGE; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-semibold ${BADGE[ton]}`}>
      {children}
    </span>
  );
}

const VERDICT_MARCHE: Record<string, { label: string; ton: keyof typeof BADGE; aide: string }> = {
  meilleur: { label: "Bat le marché", ton: "vert", aide: "Intervalle de confiance à 95 % entièrement du bon côté." },
  egal: { label: "Égal au marché", ton: "gris", aide: "L'intervalle de confiance à 95 % contient zéro : aucune différence mesurable." },
  moins_bon: { label: "Moins bon que le marché", ton: "rouge", aide: "Intervalle de confiance à 95 % entièrement du mauvais côté." },
  insuffisant: { label: "Échantillon insuffisant", ton: "ambre", aide: "Moins de 100 courses : pas de verdict." },
};

/** Écart de log-loss (servi − marché) → écart de proba donnée au vrai gagnant.
 *  exp(−Δ) − 1 : +5 % = le pronostic servi donnait en moyenne (géométrique) 5 %
 *  de proba EN PLUS au cheval qui a gagné. Plus parlant qu'un écart de log-loss,
 *  et c'est la même information, IC compris (transformation monotone). */
function gainProba(dLogloss: number | undefined | null): number | null {
  return dLogloss == null || !isFinite(dLogloss) ? null : (Math.exp(-dLogloss) - 1) * 100;
}

/** Proba moyenne géométrique donnée au vrai gagnant, en %. */
function probaGagnant(logloss: number | null | undefined): number | null {
  return logloss == null || !isFinite(logloss) ? null : Math.exp(-logloss) * 100;
}

/** « HIPPODROME DE LYON-PARILLY » / « hippodrome d'ascot gb » → « Lyon-Parilly » /
 *  « Ascot GB ». Les noms arrivent tantôt en capitales (PMU), tantôt en minuscules
 *  (clé de la matrice des biais) ; `capitalize` CSS rendait « D'ascot Gb ». */
function lieu(nom?: string | null): string {
  if (!nom) return "—";
  const court = nom.trim().replace(/\s+/g, " ").toLowerCase().replace(/^hippodrome\s+(de\s+la\s+|de\s+|du\s+|des\s+|d['’]\s*)?/, "");
  return court
    .split(/(\s+|-)/)
    .map((m) => (/^[a-z]{2}$/.test(m) && ["gb", "us", "ie"].includes(m) ? m.toUpperCase() : m.charAt(0).toUpperCase() + m.slice(1)))
    .join("");
}

function dateFr(iso?: string | null): string {
  return iso ? new Date(iso).toLocaleDateString("fr-FR", { timeZone: "Europe/Paris" }) : "—";
}

/** 99 = sentinelle « gagnant hors du top-3 prédit » posée par post_race_analyzer,
 *  pas une 99e place. L'afficher tel quel serait un chiffre inventé. */
function hors3(h: HistoryEntry): boolean {
  return h.hors_top3 === true || h.gagnant_rang_predit === 99 || (h.gagnant_rang_predit ?? 0) > 3;
}

function TemperatureGauge({ temp }: { temp?: number | null }) {
  const t = typeof temp === "number" && isFinite(temp) ? temp : null;
  const pctPos = t == null ? 0 : Math.min(Math.max(((t - 0.5) / 1.5) * 100, 0), 100);
  const color = t == null ? "#9CA3AF" : t < 0.85 ? "#3B82F6" : t > 1.2 ? "#EF4444" : "#10B981";
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
        <span>0,5 — tranchées</span>
        <span className="font-mono text-sm font-bold" style={{ color }}>{t == null ? "—" : t.toFixed(4)}</span>
        <span>2,0 — prudentes</span>
      </div>
      <div className="relative h-2.5 overflow-hidden rounded-full bg-muted">
        {/* Repère 1,0 = aucune correction : (1 − 0,5) / 1,5 = un tiers. */}
        <div className="absolute inset-y-0 left-1/3 z-10 w-px bg-foreground/40" title="1,0 = aucune correction" />
        <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pctPos}%`, backgroundColor: color }} />
      </div>
    </div>
  );
}

function LigneCorrection({ nom, detail, badge, aide }: { nom: string; detail: ReactNode; badge: ReactNode; aide?: string }) {
  return (
    <div className="flex items-start justify-between gap-2" title={aide}>
      <div className="min-w-0">
        <div className="leading-snug text-foreground">{nom}</div>
        <div className="text-[11px] text-muted-foreground">{detail}</div>
      </div>
      <div className="shrink-0 pt-0.5">{badge}</div>
    </div>
  );
}

function ServiContreMarche({ svm }: { svm?: ServiVsMarche | null }) {
  const [fen, setFen] = useState<"30j" | "90j">("30j");
  if (!svm) {
    return (
      <Section
        title={<span className="flex items-center gap-2"><Scale className="h-4 w-4 text-amber-700" />Le pronostic servi bat-il le marché ?</span>}
        desc="Calculé chaque nuit après le réentraînement."
      >
        <Empty>Pas encore de mesure : la première sera calculée par la tâche de nuit.</Empty>
      </Section>
    );
  }
  const f = svm.fenetres?.[fen];
  const vFige = VERDICT_MARCHE[f?.ecart_fige?.verdict ?? "insuffisant"] ?? VERDICT_MARCHE.insuffisant;
  const vFinal = VERDICT_MARCHE[f?.ecart_final?.verdict ?? "insuffisant"] ?? VERDICT_MARCHE.insuffisant;
  const g = gainProba(f?.ecart_fige?.moyen);
  // L'IC s'inverse avec le signe : un écart de log-loss bas = un gain de proba haut.
  const gLo = gainProba(f?.ecart_fige?.ic_haut);
  const gHi = gainProba(f?.ecart_fige?.ic_bas);
  const gF = gainProba(f?.ecart_final?.moyen);
  const gFLo = gainProba(f?.ecart_final?.ic_haut);
  const gFHi = gainProba(f?.ecart_final?.ic_bas);
  const ton = (v: string | undefined) =>
    v === "meilleur" ? "text-emerald-700" : v === "moins_bon" ? "text-red-700" : "text-foreground";

  const serie = (svm.par_semaine ?? []).map((s) => ({
    semaine: format(new Date(`${s.semaine}T12:00:00`), "dd/MM"),
    n: s.n,
    servi: probaGagnant(s.logloss_servi),
    fige: probaGagnant(s.logloss_marche_fige),
    final: probaGagnant(s.logloss_marche_final),
  }));

  return (
    <Section
      title={<span className="flex items-center gap-2"><Scale className="h-4 w-4 text-amber-700" />Le pronostic servi bat-il le marché ?</span>}
      desc="Dernier pronostic figé AVANT le départ (instantané non modifiable), comparé aux cotes PMU sur les courses réellement courues."
      right={
        <div className="flex items-center gap-1">
          {(["30j", "90j"] as const).map((k) => (
            <button
              key={k}
              onClick={() => setFen(k)}
              className={`inline-flex min-h-[2.25rem] min-w-[2.75rem] items-center justify-center rounded-lg px-2 text-[11px] font-semibold transition-colors ${fen === k ? "bg-foreground text-background" : "text-muted-foreground hover:bg-muted hover:text-foreground"}`}
            >
              {k === "30j" ? "30 j" : "90 j"}
            </button>
          ))}
        </div>
      }
    >
      {!f || !f.n_courses ? (
        <Empty>Aucune course mesurée sur cette fenêtre.</Empty>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatTile
              label="Vs marché au même instant"
              value={signedPct(g)}
              valueClass={ton(f.ecart_fige?.verdict)}
              sub={<span>proba donnée au gagnant · IC 95 % [{signedPct(gLo, 2)} ; {signedPct(gHi, 2)}]</span>}
              hint="La cote que le modèle voyait au moment de calculer : la comparaison loyale. +x % = le prono servi donnait au cheval gagnant x % de proba de plus que le marché (moyenne géométrique sur les courses)."
              footer={<Pastille ton={vFige.ton} title={vFige.aide}>{vFige.label}</Pastille>}
            />
            <StatTile
              label="Vs cote finale PMU"
              value={signedPct(gF)}
              valueClass={ton(f.ecart_final?.verdict)}
              sub={<span>IC 95 % [{signedPct(gFLo, 2)} ; {signedPct(gFHi, 2)}]</span>}
              hint="La cote de clôture intègre l'argent des dernières minutes : elle sait plus que le modèle au moment du pronostic. La battre est bien plus dur."
              footer={<Pastille ton={vFinal.ton} title={vFinal.aide}>{vFinal.label}</Pastille>}
            />
            <StatTile
              label="N°1 servi gagne"
              value={pct(f.top1_servi_pct)}
              valueClass={(f.top1_servi_pct ?? 0) > (f.top1_favori_pct ?? 0) ? "text-emerald-700" : "text-foreground"}
              sub={<span>favori du marché : <b className="text-foreground">{pct(f.top1_favori_pct)}</b></span>}
              hint="Part des courses où le cheval classé 1er par le pronostic a gagné, contre le favori du marché au même instant."
            />
            <StatTile
              label="Simple gagnant 1 € sur le n°1"
              value={signedPct(f.roi_servi_pct)}
              valueClass={tone(f.roi_servi_pct)}
              sub={<span>sur le favori : <b className={tone(f.roi_favori_pct)}>{signedPct(f.roi_favori_pct)}</b></span>}
              hint="Rendement d'une mise plate de 1 € en simple gagnant, à la cote finale PMU. Le prélèvement (~15-20 %) rend ce chiffre négatif pour presque toute stratégie : c'est l'écart au favori qui compte."
            />
          </div>

          {serie.length > 1 && (
            <div className="mt-4">
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Proba moyenne donnée au vrai gagnant, semaine par semaine (plus haut = mieux)
              </div>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={serie} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid {...GRID} />
                  <XAxis dataKey="semaine" tick={axisTick} axisLine={axisLine} tickLine={tickLine} />
                  <YAxis
                    domain={["auto", "auto"]} tick={axisTick} axisLine={axisLine} tickLine={tickLine}
                    width={44} tickFormatter={(v) => `${Math.round(v)} %`}
                  />
                  <Tooltip
                    content={
                      <ChartTooltip
                        valueFormatter={(v) => pct(v)}
                        labelFormatter={(l) => `Semaine du ${l}`}
                      />
                    }
                  />
                  <Legend wrapperStyle={{ fontSize: 11 }} iconType="plainline" />
                  <Line type="monotone" dataKey="servi" name="Pronostic servi" stroke="#F59E0B" strokeWidth={2.5} dot={{ r: 3 }} isAnimationActive={false} />
                  <Line type="monotone" dataKey="fige" name="Marché au même instant" stroke="#3B82F6" strokeWidth={1.5} dot={false} isAnimationActive={false} />
                  <Line type="monotone" dataKey="final" name="Cote finale" stroke="#6B7280" strokeWidth={1.5} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          <Note>
            {num(f.n_courses)} courses ({num(f.partants_moyen)} partants en moyenne), mesuré le {dateFr(svm.mesure_le)}.
            Les probas du marché sont les inverses des cotes, prélèvement retiré. Mesure démarrée le
            17/08 (premiers instantanés figés). L&apos;ancien « filtre de conviction » reste calculé
            pour la gate de déploiement, mais il ne retient plus que quelques paris par trimestre et
            ne mesure pas ce que le site sert : il n&apos;est plus affiché ici.
          </Note>
        </>
      )}
    </Section>
  );
}

export default function ApprentissageTab({
  alState, mlStatus, learning, history, biasMatrix, histLimit, setHistLimit, loadingHistory,
}: {
  alState?: Record<string, any>;
  mlStatus?: Record<string, any>;
  learning?: Record<string, any>;
  history?: HistoryEntry[];
  biasMatrix?: BiasRow[];
  histLimit: number;
  setHistLimit: (n: number) => void;
  loadingHistory: boolean;
}) {
  const [showBiasAll, setShowBiasAll] = useState(false);

  // `/adaptive-learning/state` renvoie l'état à PLAT (temperature, brier_ema,
  // n_races_processed…), pas sous une clé `adaptive_learning`. Le repli sur
  // `ml-status` ne sert donc que si l'appel admin échoue — et il est mis en
  // cache 5 min côté serveur, donc jamais le « direct » qu'on veut afficher.
  const alDirect = alState?.temperature != null ? alState : null;
  const alFallback = mlStatus?.adaptive_learning ?? {};
  const temperature = alDirect?.temperature ?? alFallback.temperature;
  const brierEma = alDirect?.brier_ema ?? alFallback.brier_ema;
  const nRaces = alDirect?.n_races_processed ?? alFallback.n_races;

  const dd = alState?.drift_detector ?? mlStatus?.drift_detector ?? {};
  const derive = DERIVE[dd.status ?? "healthy"] ?? DERIVE.healthy;
  const drifts: FeatureDrift[] = alState?.top_feature_drifts ?? [];
  const calibration = alState?.calibration;
  const meta = alState?.meta_apprenant;

  const histPoints = (history ?? []).slice().reverse().map((h) => ({
    date: h.analyzed_at ? format(new Date(h.analyzed_at), "dd/MM HH:mm") : "",
    lieu: h.hippodrome ? lieu(h.hippodrome) : "",
    brier: h.brier_score ?? null,
    marche: h.brier_marche ?? null,
    surprise: !!h.was_surprise,
  }));
  const paires = (history ?? []).filter((h) => h.brier_score != null && h.brier_marche != null);
  const moyServi = paires.length ? paires.reduce((s, h) => s + (h.brier_score as number), 0) / paires.length : null;
  const moyMarche = paires.length ? paires.reduce((s, h) => s + (h.brier_marche as number), 0) / paires.length : null;
  const nMieux = paires.filter((h) => (h.brier_score as number) < (h.brier_marche as number)).length;

  const biasRows = (biasMatrix ?? []).slice(0, showBiasAll ? 100 : 12);
  const biaisMetaActif = (biasMatrix ?? []).some((b) => b.meta_actif);
  const ilYa30j = Date.now() - 30 * 86_400_000;

  return (
    <div className="space-y-5">
      {/* État du moteur */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        <div className={`rounded-xl border p-4 ${derive.cls}`} title={derive.aide}>
          <div className="flex items-center gap-2">
            {derive.ok ? <CheckCircle2 className="h-5 w-5" /> : <AlertTriangle className="h-5 w-5" />}
            <div>
              <div className="text-sm font-bold">{derive.label}</div>
              <div className="text-[11px] opacity-80">Détecteur de dérive ADWIN + Page-Hinkley</div>
            </div>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] opacity-90">
            <span title="Erreur moyenne de la proba top 3 sur la fenêtre ADWIN (plus bas = mieux)">
              Brier top 3 <b className="font-mono">{dd.brier_mean?.toFixed(4) ?? "—"}</b>
            </span>
            <span>Surprises <b>{dd.surprise_rate != null ? pct(dd.surprise_rate * 100) : "—"}</b></span>
            <span className="opacity-80">sur {num(dd.brier_window_size)} dernières courses</span>
            <span className="opacity-80">sur 100 dernières courses</span>
          </div>
          <div className="mt-2 text-[11px] opacity-80">
            {dd.total_drift_events
              ? <>{num(dd.total_drift_events)} rupture(s) détectée(s) · dernière le {dateFr(dd.last_drift_time)}</>
              : <>Aucune rupture depuis {num(dd.total_observations)} courses observées</>}
          </div>
        </div>

        <div className="bt-verre rounded-xl p-4 shadow-sm">
          <div className="mb-3 flex items-center gap-2">
            <Thermometer className="h-4 w-4 text-amber-700" />
            <span className="text-sm font-bold text-foreground">Température de calibration</span>
          </div>
          <TemperatureGauge temp={temperature} />
          <p className="mt-2 text-[11px] text-muted-foreground">
            {typeof temperature === "number"
              ? temperature < 0.97
                ? "Sous 1 : les probas du modèle étaient trop timides, elles sont accentuées."
                : temperature > 1.03
                  ? "Au-dessus de 1 : les probas du modèle étaient trop sûres d'elles, elles sont adoucies."
                  : "Proche de 1 : le modèle est déjà bien calibré, la correction est faible."
              : "Température indisponible."}
          </p>
          <div className="mt-2 flex justify-between gap-2 text-[11px] text-muted-foreground">
            <span>{num(nRaces)} courses apprises</span>
            <span title="Moyenne lissée exponentiellement : ≈ 10 dernières courses">
              Brier lissé (≈10 courses) <b className="font-mono text-foreground">{typeof brierEma === "number" ? brierEma.toFixed(3) : "—"}</b>
            </span>
          </div>
        </div>

        <div className="bt-verre rounded-xl p-4 shadow-sm">
          <div className="mb-3 text-sm font-bold text-foreground">Corrections réellement appliquées</div>
          {!calibration ? (
            <p className="text-[11px] text-muted-foreground">État de calibration indisponible.</p>
          ) : (
            <div className="space-y-2.5 text-xs">
              <LigneCorrection
                nom="Calibration isotonique"
                detail={`${num(calibration.isotonique?.n_points)} points · ${num(calibration.isotonique?.n_obs)} obs · ${dateFr(calibration.isotonique?.updated_at)}`}
                badge={calibration.isotonique?.actif ? <Pastille ton="vert">appliquée</Pastille> : <Pastille ton="gris">en attente</Pastille>}
              />
              <LigneCorrection
                nom="Calibration longshots"
                detail={calibration.longshots?.calculee ? `calculée chaque nuit · ${num(calibration.longshots?.n_obs)} obs` : "jamais calculée"}
                aide={calibration.longshots?.raison ?? undefined}
                badge={calibration.longshots?.actif
                  ? <Pastille ton="vert">appliquée</Pastille>
                  : <Pastille ton="gris" title={calibration.longshots?.raison ?? undefined}>désactivée</Pastille>}
              />
              <LigneCorrection
                nom="Tilt des poids de features"
                detail={`appliqué · ${num(calibration.feature_weight_tilt?.courses_apprises)} courses · ±16 % max`}
                aide="Appliqué à chaque pronostic, mais aucun banc avec / sans n'a encore mesuré qu'il améliore la précision."
                badge={!calibration.feature_weight_tilt?.actif
                  ? <Pastille ton="gris">en attente</Pastille>
                  : calibration.feature_weight_tilt?.gain_mesure
                    ? <Pastille ton="vert">appliqué</Pastille>
                    : <Pastille ton="ambre">non prouvé</Pastille>}
              />
              <LigneCorrection
                nom="Correction de contexte"
                detail={meta?.actif
                  ? `méta-apprenant · ${num(meta.n_echantillons)} ex. · ${dateFr(meta.entraine_le)}`
                  : "matrice des biais (méta-apprenant absent)"}
                aide="Une seule correction de contexte à l'inférence : le méta-apprenant s'il a passé son test d'utilité, la matrice des biais sinon."
                badge={meta?.actif ? <Pastille ton="vert">méta-apprenant</Pastille> : <Pastille ton="bleu">matrice des biais</Pastille>}
              />
            </div>
          )}
        </div>
      </div>

      {/* Pronostic servi contre le marché */}
      <ServiContreMarche svm={learning?.servi_vs_marche} />

      {/* Poids appris par profil */}
      {learning?.profil_weights?.profils && (
        <Section
          title="Poids appris par profil"
          desc="Multiplicateur appliqué à chaque type de pari selon ce que le profil a réellement encaissé. En dessous de 10 conseils réglés, le poids reste neutre (×1,00) — jamais inventé. ×0 = type coupé."
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {(["conservateur", "equilibre", "agressif"] as const).map((pk) => {
              const p = learning.profil_weights.profils[pk];
              if (!p) return null;
              const labels: Record<string, string> = { conservateur: "Prudent", equilibre: "Modéré", agressif: "Risqué" };
              const detail: Record<string, { n?: number; roi?: number }> = p.type_detail ?? {};
              // Les plus joués d'abord : un poids sur 2 conseils n'informe de rien.
              const types = Object.entries(p.type_weights || {})
                .map(([t, w]) => ({ t, w: w as number, n: detail[t]?.n ?? 0, roi: detail[t]?.roi }))
                .sort((a, b) => b.n - a.n)
                .slice(0, 7);
              return (
                <div key={pk} className="bt-verre rounded-xl p-3 shadow-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-bold text-foreground">{labels[pk]}</span>
                    <span className="text-[11px] text-muted-foreground">{num(p.n_runs)} conseils réglés</span>
                  </div>
                  {p.roi_global != null && (
                    <div className={`mt-0.5 text-lg font-bold tabular-nums ${tone(p.roi_global)}`}>
                      ROI {signedPct(p.roi_global)}
                    </div>
                  )}
                  <div className="mt-2 space-y-1">
                    {types.map(({ t, w, n, roi }) => (
                      <div key={t} className="flex items-center gap-2 text-[11px]" title={`${num(n)} conseils · ROI ${signedPct(roi)}`}>
                        <span className="w-24 shrink-0 truncate text-muted-foreground">{t}</span>
                        <div className="relative h-1.5 flex-1 rounded-full bg-muted">
                          <div className="absolute inset-y-0 left-1/2 w-px bg-border" />
                          <div
                            className="absolute inset-y-0 rounded-full"
                            style={{
                              left: w >= 1 ? "50%" : `${50 - Math.min(Math.abs(w - 1) * 50, 50)}%`,
                              width: `${Math.min(Math.abs(w - 1) * 50, 50)}%`,
                              background: w >= 1 ? DIVERGING_POS : DIVERGING_NEG,
                            }}
                          />
                        </div>
                        <span className="w-9 shrink-0 text-right tabular-nums text-muted-foreground">{num(n)}</span>
                        <span className={`w-11 shrink-0 text-right font-mono font-semibold tabular-nums ${w === 0 ? "text-red-700" : w > 1 ? "text-emerald-700" : w < 1 ? "text-red-700" : "text-muted-foreground"}`}>
                          {w === 0 ? "coupé" : `×${w.toFixed(2)}`}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </Section>
      )}

      {/* ROI par signal */}
      {(learning?.signaux?.length ?? 0) > 0 && (
        <Section
          title="Rendement réel par signal qualitatif"
          desc={
            <>
              Chaque signal détecté par l&apos;analyse confronté au résultat encaissé (mise plate en simple
              gagnant, 30 cas minimum). Le prélèvement rend presque tout négatif : la barre mesure
              l&apos;écart à la moyenne de tous les signaux
              {learning?.signaux_reference != null && <> (<b>{signedPct(learning.signaux_reference * 100)}</b>)</>},
              et c&apos;est ce multiplicateur qui pondère les pronostics.
            </>
          }
        >
          <div className="mb-2 hidden text-[11px] uppercase tracking-wide text-muted-foreground sm:flex sm:gap-3">
            <span className="w-40 shrink-0">Signal</span>
            <span className="flex-1 text-center">Écart à la moyenne</span>
            <span className="w-14 shrink-0 text-right">Poids</span>
            <span className="w-36 shrink-0 text-right">ROI · gagne · cas</span>
          </div>
          {/* Le nom du signal passe AU-DESSUS de sa barre sous 640 px. */}
          <div className="space-y-3 sm:space-y-1.5">
            {learning!.signaux
              .slice()
              .sort((a: any, b: any) => (b.multiplier ?? 1) - (a.multiplier ?? 1))
              .map((s: { signal: string; n: number; win_rate: number; roi: number; multiplier?: number }) => {
                const m = s.multiplier ?? 1;
                const ecart = m - 1;
                return (
                  <div key={s.signal} className="text-[11px] sm:flex sm:items-center sm:gap-3">
                    <span className="block font-medium text-foreground sm:w-40 sm:shrink-0 sm:truncate">
                      {s.signal.replace(/_/g, " ")}
                    </span>
                    <div className="mt-1 flex items-center gap-2 sm:mt-0 sm:flex-1 sm:gap-3">
                      <div className="relative h-2 flex-1 rounded-full bg-muted">
                        <div className="absolute inset-y-0 left-1/2 w-px bg-border" />
                        <div
                          className="absolute inset-y-0 rounded-full"
                          style={{
                            left: ecart >= 0 ? "50%" : `${50 - Math.min(Math.abs(ecart) * 100, 50)}%`,
                            width: `${Math.min(Math.abs(ecart) * 100, 50)}%`,
                            background: ecart >= 0 ? DIVERGING_POS : DIVERGING_NEG,
                          }}
                        />
                      </div>
                      <span className={`w-12 shrink-0 text-right font-mono font-bold tabular-nums sm:w-14 ${tone(ecart)}`}>
                        ×{m.toFixed(2)}
                      </span>
                      <span className="w-28 shrink-0 whitespace-nowrap text-right tabular-nums text-muted-foreground sm:w-36">
                        {signedPct(s.roi * 100, 0)} · {pct(s.win_rate * 100, 0)} · {num(s.n)}
                      </span>
                    </div>
                  </div>
                );
              })}
          </div>
        </Section>
      )}

      {/* Brier course par course + poids features */}
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <Section
          title="Erreur course par course"
          desc="Brier de la proba top 3 (plus bas = mieux), comparé au marché sur les mêmes partants. Points rouges : courses « surprise »."
          right={
            <div className="flex gap-1">
              {[15, 30, 50].map((n) => (
                <button
                  key={n}
                  onClick={() => setHistLimit(n)}
                  className={`inline-flex min-h-[2.25rem] min-w-[2.25rem] items-center justify-center rounded-lg px-2 text-[11px] font-semibold transition-colors ${histLimit === n ? "bg-foreground text-background" : "text-muted-foreground hover:bg-muted hover:text-foreground"}`}
                >
                  {n}
                </button>
              ))}
            </div>
          }
        >
          {loadingHistory || histPoints.length === 0 ? (
            <Empty>{loadingHistory ? "Chargement…" : "Aucune course analysée."}</Empty>
          ) : (
            <>
              {moyServi != null && moyMarche != null && (
                <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
                  <span>Moyenne servie <b className={`font-mono ${moyServi < moyMarche ? "text-emerald-700" : "text-red-700"}`}>{moyServi.toFixed(4)}</b></span>
                  <span>marché <b className="font-mono text-foreground">{moyMarche.toFixed(4)}</b></span>
                  <span>meilleur que le marché sur <b className="text-foreground">{nMieux}/{paires.length}</b> courses</span>
                </div>
              )}
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={histPoints} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid {...GRID} />
                  <XAxis dataKey="date" hide />
                  <YAxis domain={[0, "auto"]} tick={axisTick} axisLine={axisLine} tickLine={tickLine} width={40} tickFormatter={(v) => v.toFixed(2)} />
                  <Tooltip
                    content={
                      <ChartTooltip
                        valueFormatter={(v) => v.toFixed(4)}
                        labelFormatter={(l) => {
                          const p = histPoints.find((x) => x.date === l);
                          return p?.lieu ? `${l} · ${p.lieu}` : String(l);
                        }}
                      />
                    }
                  />
                  <Legend wrapperStyle={{ fontSize: 11 }} iconType="plainline" />
                  {moyMarche != null && <ReferenceLine y={moyMarche} stroke="#9CA3AF" strokeDasharray="2 3" />}
                  <Line
                    type="monotone" dataKey="marche" name="Marché" stroke="#9CA3AF" strokeWidth={1.25}
                    strokeDasharray="5 4" dot={false} isAnimationActive={false} connectNulls
                  />
                  <Line
                    type="monotone" dataKey="brier" name="Pronostic" stroke="#3B82F6" strokeWidth={1.75}
                    isAnimationActive={false}
                    dot={(props: any) => {
                      const { cx, cy, payload, index } = props;
                      if (cx == null || cy == null || !payload) return <g key={index} />;
                      return (
                        <circle
                          key={index} cx={cx} cy={cy} r={payload.surprise ? 4 : 2}
                          fill={payload.surprise ? "#EF4444" : "#3B82F6"} stroke="#fff" strokeWidth={payload.surprise ? 1 : 0}
                        />
                      );
                    }}
                  />
                </LineChart>
              </ResponsiveContainer>
              <Note>
                Le marché est traduit en proba top 3 depuis les cotes de victoire (modèle de Harville),
                avec la cote figée au moment du pronostic. Pointillé horizontal : moyenne du marché.
              </Note>
            </>
          )}
        </Section>

        <Section
          title="Dérive des poids de features"
          desc="Écart entre le poids appris en ligne et le poids par défaut du groupe. Vert = renforcé, rouge = atténué. Zéro = le moteur n'a rien changé."
        >
          {drifts.length === 0 ? (
            <Empty>Aucune dérive enregistrée — le tilt attend son volume minimal de courses.</Empty>
          ) : (
            <>
              <ResponsiveContainer width="100%" height={Math.max(190, drifts.length * 34)}>
                <BarChart data={drifts} layout="vertical" margin={{ left: 4, right: 44, top: 4, bottom: 4 }}>
                  <CartesianGrid {...GRID} horizontal={false} vertical />
                  <XAxis
                    type="number" tick={axisTick} axisLine={axisLine} tickLine={tickLine}
                    tickFormatter={(v) => (v > 0 ? "+" : "") + v.toFixed(1)}
                  />
                  <YAxis
                    type="category" dataKey="groupe" width={116} interval={0}
                    tick={{ fontSize: 10, fill: "#6B7280" }} axisLine={axisLine} tickLine={tickLine}
                  />
                  <ReferenceLine x={0} stroke="#4B5563" strokeWidth={1} />
                  <Tooltip
                    cursor={{ fill: "rgba(148,163,184,0.08)" }}
                    content={<ChartTooltip valueFormatter={(v) => `${v > 0 ? "+" : ""}${v.toFixed(3)}`} />}
                  />
                  <Bar dataKey="drift" name="Dérive vs défaut" radius={[0, 3, 3, 0]} barSize={14} isAnimationActive={false}>
                    {drifts.map((f, i) => (
                      <Cell key={i} fill={f.drift >= 0 ? DIVERGING_POS : DIVERGING_NEG} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
              <div className="mt-2 space-y-0.5">
                {drifts.map((f) => (
                  <div key={f.groupe} className="flex items-center gap-2 text-[11px] text-muted-foreground">
                    <span className="w-28 shrink-0 truncate">{f.groupe}</span>
                    <span className="tabular-nums">
                      poids <b className="text-foreground">{f.poids_actuel.toFixed(3)}</b> · défaut {f.poids_défaut.toFixed(2)}
                      {f.poids_actuel >= 1.9 && <span className="ml-1 text-amber-700">· proche du plafond 2,00</span>}
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
          <Note>
            La règle d&apos;apprentissage ne fait que MONTER un poids (quand le gagnant raté portait le
            signal), puis le ramène de 2 % par course vers son défaut. Elle n&apos;a jamais été validée
            par un test avec / sans : un poids élevé dit « souvent présent chez les gagnants ratés »,
            pas « utile ». Plafond 2,00.
          </Note>
        </Section>
      </div>

      {/* Biais contextuels */}
      <Section
        title="Biais contextuels détectés"
        desc={biaisMetaActif
          ? "Contextes (hippodrome, discipline, terrain) anormalement surprenants. Le méta-apprenant étant actif, cette matrice n'est PAS appliquée aux pronostics : elle sert de diagnostic."
          : "Contextes (hippodrome, discipline, terrain) où le modèle se trompe systématiquement. La correction est appliquée à l'inférence."}
        right={
          (biasMatrix?.length ?? 0) > 12 ? (
            <button
              onClick={() => setShowBiasAll((v) => !v)}
              className="inline-flex min-h-[2.25rem] items-center gap-1 rounded-lg px-2 text-[11px] font-semibold text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              {showBiasAll ? <><ChevronUp className="h-3 w-3" />Réduire</> : <><ChevronDown className="h-3 w-3" />Tout voir ({num(biasMatrix?.length)})</>}
            </button>
          ) : undefined
        }
      >
        {!biasMatrix ? (
          <Empty>Chargement…</Empty>
        ) : biasRows.length === 0 ? (
          <Empty>Aucun biais détecté — il en faut au moins 5 courses par contexte.</Empty>
        ) : (
          <div role="region" tabIndex={0} aria-label="Tableau de données, défilement horizontal" className="-mx-4 overflow-x-auto overscroll-x-contain px-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring sm:-mx-5 sm:px-5">
            <table className="w-full min-w-[640px] text-xs">
              <thead>
                <tr className="border-b border-border/70 text-[11px] uppercase tracking-wide text-muted-foreground">
                  <th className="py-2 pr-3 text-left font-semibold">Contexte</th>
                  <th className="px-2 py-2 text-left font-semibold">Discipline</th>
                  <th className="px-2 py-2 text-left font-semibold">Terrain</th>
                  <th className="px-2 py-2 text-right font-semibold">Courses</th>
                  <th className="px-2 py-2 text-right font-semibold">Surprises</th>
                  <th className="px-2 py-2 text-right font-semibold">Mis à jour</th>
                  <th className="py-2 pl-2 text-left font-semibold">Correction</th>
                </tr>
              </thead>
              <tbody>
                {biasRows.map((row, i) => {
                  const perime = row.updated_at ? new Date(row.updated_at).getTime() < ilYa30j : false;
                  const suspect = row.nb_courses >= 20 && row.taux_surprise >= 0.99;
                  return (
                    <tr key={i} className={`border-b border-border/50 ${perime ? "opacity-60" : ""}`}>
                      <td className="max-w-[200px] truncate py-2 pr-3 font-medium text-foreground" title={row.contexte}>
                        {lieu(row.hippodrome ?? row.contexte)}
                      </td>
                      <td className="px-2 py-2 capitalize text-muted-foreground">{row.discipline ?? "—"}</td>
                      <td className="px-2 py-2 text-muted-foreground">{row.terrain ?? "—"}</td>
                      <td className="px-2 py-2 text-right tabular-nums text-muted-foreground">{num(row.nb_courses)}</td>
                      <td className="px-2 py-2 text-right tabular-nums text-amber-700">
                        {pct((row.taux_surprise ?? 0) * 100)}
                        {suspect && (
                          <span className="ml-1 text-red-700" title="100 % de surprises sur autant de courses : comptage douteux (données de juin, avant les correctifs de l'analyse post-course)">⚠</span>
                        )}
                      </td>
                      <td className={`px-2 py-2 text-right tabular-nums ${perime ? "text-amber-700" : "text-muted-foreground"}`} title={perime ? "Contexte plus alimenté depuis plus de 30 jours" : undefined}>
                        {dateFr(row.updated_at)}
                      </td>
                      <td className="py-2 pl-2">
                        {!row.correction_factor ? (
                          <span className="text-[11px] text-muted-foreground">aucune</span>
                        ) : row.correction_appliquee ? (
                          <Pastille ton="bleu" title="Confiance réduite de 0,05 sur ce contexte, appliquée à chaque pronostic">confiance −0,05</Pastille>
                        ) : row.meta_actif ? (
                          <Pastille ton="gris" title="Le méta-apprenant est actif : la matrice des biais n'est lue que s'il est absent">non appliquée</Pastille>
                        ) : (
                          <Pastille ton="gris" title={`Lue à l'inférence seulement à partir de ${row.seuil_courses ?? 8} courses`}>
                            en attente ({row.nb_courses}/{row.seuil_courses ?? 8})
                          </Pastille>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <Note>
          Correction binaire, jamais graduée : −0,05 de confiance dès qu&apos;un contexte dépasse 55 %
          de surprises sur au moins 8 courses, rien sinon — et seulement quand le méta-apprenant est
          absent. Lignes grisées : contexte plus alimenté depuis 30 jours (souvent un ancien libellé
          d&apos;hippodrome).
        </Note>
      </Section>

      {/* Journal */}
      <Section
        title={<span className="flex items-center gap-2"><Zap className="h-4 w-4 text-emerald-700" />Journal d&apos;apprentissage</span>}
        desc="Les dernières courses digérées par le moteur. Brier vert = meilleur que le marché sur la même course."
      >
        {loadingHistory ? (
          <Empty>Chargement…</Empty>
        ) : !history?.length ? (
          <Empty>Aucune course analysée.</Empty>
        ) : (
          <div role="region" tabIndex={0} aria-label="Tableau de données, défilement" className="-mx-4 max-h-[26rem] overflow-auto overscroll-contain px-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring sm:-mx-5 sm:px-5">
            <table className="w-full min-w-[700px] text-xs">
              <thead className="sticky top-0 bg-card">
                <tr className="border-b border-border/70 text-[11px] uppercase tracking-wide text-muted-foreground">
                  <th className="py-2 pr-3 text-left font-semibold">Date</th>
                  <th className="px-2 py-2 text-left font-semibold">Hippodrome</th>
                  <th className="px-2 py-2 text-left font-semibold">Discipline</th>
                  <th className="px-2 py-2 text-right font-semibold">Brier</th>
                  <th className="px-2 py-2 text-right font-semibold">Marché</th>
                  <th className="px-2 py-2 text-right font-semibold">Partants</th>
                  <th className="px-2 py-2 text-right font-semibold" title="Proba d'être dans les 3 premiers donnée au cheval qui a gagné">Proba top 3 du gagnant</th>
                  <th className="px-2 py-2 text-right font-semibold">Gagnant réel</th>
                </tr>
              </thead>
              <tbody>
                {history.map((h, i) => {
                  const b = h.brier_score;
                  const m = h.brier_marche;
                  const cls = b == null || m == null ? "text-foreground" : b < m ? "text-emerald-700" : b > m ? "text-red-700" : "text-foreground";
                  return (
                    <tr key={h.log_id ?? i} className={`border-b border-border/50 ${h.was_surprise ? "bg-red-50/40" : ""}`}>
                      <td className="py-2 pr-3 font-mono text-muted-foreground">
                        {h.analyzed_at ? format(new Date(h.analyzed_at), "dd/MM HH:mm") : "—"}
                      </td>
                      <td className="px-2 py-2 font-medium text-foreground">{lieu(h.hippodrome)}</td>
                      <td className="px-2 py-2 text-muted-foreground">{h.discipline ?? "—"}</td>
                      <td className={`px-2 py-2 text-right font-mono font-semibold tabular-nums ${cls}`}>{b?.toFixed(4) ?? "—"}</td>
                      <td className="px-2 py-2 text-right font-mono tabular-nums text-muted-foreground">{m?.toFixed(4) ?? "—"}</td>
                      <td className="px-2 py-2 text-right tabular-nums text-muted-foreground">{h.nb_partants ?? "—"}</td>
                      <td className="px-2 py-2 text-right font-mono tabular-nums text-muted-foreground">
                        {h.gagnant_proba_ia != null ? pct(h.gagnant_proba_ia * 100) : "—"}
                      </td>
                      <td className="px-2 py-2 text-right">
                        {h.gagnant_rang_predit == null ? "—" : hors3(h) ? (
                          <span className="text-muted-foreground" title="Le gagnant réel n'était pas dans les 3 premiers du classement prédit">
                            hors top 3
                          </span>
                        ) : (
                          <span className={`font-bold ${h.gagnant_rang_predit === 1 ? "text-emerald-700" : "text-amber-700"}`}>
                            {h.gagnant_rang_predit}<sup>{h.gagnant_rang_predit === 1 ? "er" : "e"}</sup> prédit
                          </span>
                        )}
                        {h.was_surprise && <span className="ml-1 text-red-700" title="Course classée surprise">⚡</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  );
}
