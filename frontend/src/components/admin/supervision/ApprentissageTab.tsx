"use client";

/**
 * Onglet « Apprentissage » — ce que le système corrige tout seul, et sur quoi.
 *
 * Température de calibration, détecteur de dérive, poids de features, poids
 * appris par profil, ROI par signal, biais contextuels, journal course par
 * course. Tout provient d'états réellement persistés : un module qui n'a pas
 * encore assez de données affiche « en attente », jamais une valeur neutre
 * déguisée en mesure.
 */

import { useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronUp, Thermometer, Zap } from "lucide-react";
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
  log_id: string; hippodrome?: string; discipline?: string;
  brier_score?: number; was_surprise?: boolean;
  gagnant_proba_ia?: number; gagnant_rang_predit?: number;
  hors_top3?: boolean; nb_partants?: number; analyzed_at: string;
}
interface BiasRow {
  contexte: string; discipline?: string; terrain?: string; hippodrome?: string;
  nb_courses: number; taux_surprise: number; brier_moyen?: number;
  correction_factor: number; correction_appliquee?: boolean; seuil_courses?: number;
  favori_win_rate?: number;
}

const SEVERITY: Record<string, { label: string; cls: string; aide: string }> = {
  critical: {
    label: "Dérive critique",
    cls: "border-red-200 bg-red-50 text-red-700",
    aide: "ADWIN et/ou Page-Hinkley ont détecté une rupture nette de la qualité des probabilités.",
  },
  warning: {
    label: "Avertissement",
    cls: "border-amber-200 bg-amber-50 text-amber-700",
    aide: "Signal de dérive naissant — à surveiller, pas encore une rupture.",
  },
  none: {
    label: "Stable",
    cls: "border-emerald-200 bg-emerald-50 text-emerald-700",
    aide: "Aucune rupture détectée sur la fenêtre glissante.",
  },
};

/** 99 = sentinelle « gagnant hors du top-3 prédit » posée par post_race_analyzer,
 *  pas une 99e place. L'afficher tel quel serait un chiffre inventé. */
function hors3(h: HistoryEntry): boolean {
  return h.hors_top3 === true || h.gagnant_rang_predit === 99 || (h.gagnant_rang_predit ?? 0) > 3;
}

function TemperatureGauge({ temp }: { temp?: number | null }) {
  const t = typeof temp === "number" && isFinite(temp) ? temp : 1.0;
  const pctPos = Math.min(Math.max(((t - 0.5) / 1.5) * 100, 0), 100);
  const color = t < 0.85 ? "#3B82F6" : t > 1.2 ? "#EF4444" : "#10B981";
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-[11px] text-muted-foreground">
        <span>0,5 — probas plus tranchées</span>
        <span className="font-mono text-sm font-bold" style={{ color }}>{t.toFixed(4)}</span>
        <span>2,0 — probas plus prudentes</span>
      </div>
      <div className="relative h-2.5 overflow-hidden rounded-full bg-muted">
        <div className="absolute inset-y-0 left-1/3 w-px bg-border" />
        <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pctPos}%`, backgroundColor: color }} />
      </div>
    </div>
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
  const drifts: FeatureDrift[] = alState?.top_feature_drifts ?? [];
  const sev = SEVERITY[dd.severity ?? "none"] ?? SEVERITY.none;
  const calibration = alState?.calibration;

  const histPoints = (history ?? []).slice().reverse().map((h) => ({
    date: h.analyzed_at ? format(new Date(h.analyzed_at), "dd/MM HH:mm") : "",
    brier: h.brier_score ?? null,
    surprise: !!h.was_surprise,
  }));

  const biasRows = (biasMatrix ?? []).slice(0, showBiasAll ? 100 : 12);

  return (
    <div className="space-y-5">
      {/* État du moteur */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        <div className={`rounded-xl border p-4 ${sev.cls}`} title={sev.aide}>
          <div className="flex items-center gap-2">
            {dd.severity === "none" || !dd.severity ? (
              <CheckCircle2 className="h-5 w-5" />
            ) : (
              <AlertTriangle className="h-5 w-5" />
            )}
            <div>
              <div className="text-sm font-bold">{sev.label}</div>
              <div className="text-[11px] opacity-80">Détecteur de dérive ADWIN + Page-Hinkley</div>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] opacity-90">
            <span>Brier moyen {dd.brier_mean?.toFixed(4) ?? "—"}</span>
            <span>Surprises {dd.surprise_rate != null ? pct(dd.surprise_rate * 100) : "—"}</span>
            {dd.adwin_triggered && <span className="font-semibold">ADWIN déclenché</span>}
            {dd.ph_triggered && <span className="font-semibold">Page-Hinkley déclenché</span>}
          </div>
        </div>

        <div className="rounded-xl border border-border/70 bg-card p-4 shadow-sm">
          <div className="mb-3 flex items-center gap-2">
            <Thermometer className="h-4 w-4 text-amber-700" />
            <span className="text-sm font-bold text-foreground">Température de calibration</span>
          </div>
          <TemperatureGauge temp={temperature ?? 1.0} />
          <div className="mt-2 flex justify-between text-[11px] text-muted-foreground">
            <span>{num(nRaces)} courses analysées</span>
            <span>Brier EMA {typeof brierEma === "number" ? brierEma.toFixed(3) : "—"}</span>
          </div>
        </div>

        <div className="rounded-xl border border-border/70 bg-card p-4 shadow-sm">
          <div className="mb-3 text-sm font-bold text-foreground">Corrections appliquées à l&apos;inférence</div>
          {!calibration ? (
            <p className="text-[11px] text-muted-foreground">État de calibration indisponible.</p>
          ) : (
            <div className="space-y-2 text-[11px]">
              {[
                { k: "Calibration isotonique", actif: calibration.isotonique?.actif, detail: `${num(calibration.isotonique?.n_points)} points · ${num(calibration.isotonique?.n_obs)} obs` },
                { k: "Calibration longshots", actif: calibration.longshots?.actif, detail: `${num(calibration.longshots?.n_obs)} obs` },
                { k: "Tilt des poids de features", actif: calibration.feature_weight_tilt?.actif, detail: `${num(calibration.feature_weight_tilt?.courses_apprises)} / ${num(calibration.feature_weight_tilt?.courses_requises)} courses` },
              ].map((c) => (
                <div key={c.k} className="flex items-center justify-between gap-2">
                  <span className="truncate text-muted-foreground">{c.k}</span>
                  <span className="flex shrink-0 items-center gap-2">
                    <span className="text-[11px] text-muted-foreground">{c.detail}</span>
                    <span className={`rounded-full border px-1.5 py-0.5 text-[11px] font-semibold ${c.actif ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-border bg-muted/40 text-muted-foreground"}`}>
                      {c.actif ? "active" : "en attente"}
                    </span>
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Edge hors-échantillon */}
      {learning?.edge && (
        <Section
          title="Le filtre de conviction bat-il le marché ?"
          desc="Mesuré sur des courses jamais vues à l'entraînement : taux de réussite des paris à forte conviction contre le taux obtenu en jouant tout."
          right={
            <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${learning.edge.edge_ok ? "border-emerald-200 bg-emerald-50 text-emerald-700" : learning.edge.enough_filt === false ? "border-amber-200 bg-amber-50 text-amber-700" : "border-red-200 bg-red-50 text-red-700"}`}>
              {learning.edge.edge_ok ? "avantage confirmé" : learning.edge.enough_filt === false ? "échantillon insuffisant" : "avantage à surveiller"}
            </span>
          }
        >
          {(() => {
            // Sous seuil, ces chiffres restent affichés mais en gris : les
            // colorer en vert ferait passer pour un résultat ce que la ligne
            // d'avertissement juste dessous qualifie de bruit.
            const solide = learning.edge.enough_filt !== false;
            const gris = "text-muted-foreground";
            return (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <StatTile label="Réussite filtrée" value={pct((learning.edge.win_filtre ?? 0) * 100)}
                  sub={`${num(learning.edge.n_filt)} paris retenus`}
                  valueClass={solide ? "text-emerald-700" : gris} />
                <StatTile label="Réussite sans filtre" value={pct((learning.edge.win_baseline ?? 0) * 100)} sub="en jouant tout" />
                <StatTile label="ROI plafonné" value={signedPct(learning.edge.roi_plafonne)}
                  valueClass={solide ? tone(learning.edge.roi_plafonne) : gris}
                  sub={solide ? "gains extrêmes bornés" : "non concluant à ce volume"} />
                <StatTile label="Courses de test" value={num(learning.edge.n_test)}
                  sub={learning.edge.mesure_le ? `mesuré le ${new Date(learning.edge.mesure_le).toLocaleDateString("fr-FR", { timeZone: "Europe/Paris" })}` : "—"} />
              </div>
            );
          })()}
          {learning.edge.enough_filt === false && (
            <div className="mt-3 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-2.5 text-[11px] text-amber-800">
              <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" />
              <span>
                Échantillon filtré trop petit ({num(learning.edge.n_filt)} paris) : ces chiffres sont
                dominés par la variance, pas par un avantage établi.
              </span>
            </div>
          )}
        </Section>
      )}

      {/* Poids appris par profil */}
      {learning?.profil_weights?.profils && (
        <Section
          title="Poids appris par profil"
          desc="Multiplicateur appliqué à chaque type de pari selon ce que le profil a réellement encaissé. En dessous de 10 conseils réglés, le poids reste neutre — jamais inventé."
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {(["conservateur", "equilibre", "agressif"] as const).map((pk) => {
              const p = learning.profil_weights.profils[pk];
              if (!p) return null;
              const labels: Record<string, string> = { conservateur: "Prudent", equilibre: "Modéré", agressif: "Risqué" };
              return (
                <div key={pk} className="rounded-xl border border-border/70 bg-card p-3 shadow-sm">
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
                    {Object.entries(p.type_weights || {}).slice(0, 6).map(([t, w]) => (
                      <div key={t} className="flex items-center gap-2 text-[11px]">
                        <span className="w-24 shrink-0 truncate text-muted-foreground">{t}</span>
                        <div className="relative h-1.5 flex-1 rounded-full bg-muted">
                          <div className="absolute inset-y-0 left-1/2 w-px bg-border" />
                          <div
                            className="absolute inset-y-0 rounded-full"
                            style={{
                              left: (w as number) >= 1 ? "50%" : `${50 - Math.min(Math.abs((w as number) - 1) * 100, 50)}%`,
                              width: `${Math.min(Math.abs((w as number) - 1) * 100, 50)}%`,
                              background: (w as number) >= 1 ? DIVERGING_POS : DIVERGING_NEG,
                            }}
                          />
                        </div>
                        <span className={`w-10 shrink-0 text-right font-mono font-semibold tabular-nums ${(w as number) >= 1 ? "text-emerald-700" : "text-red-700"}`}>
                          ×{(w as number).toFixed(2)}
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
          desc="Chaque signal détecté par l'analyse (forme, driver, terrain…) confronté au résultat encaissé. Seuls les signaux à 30 conseils minimum sont affichés."
        >
          {/* Le nom du signal passe AU-DESSUS de sa barre sous 640 px. En une
              seule ligne, « Driver en réussite hippodrome » dans 160 px fixes,
              plus la barre, plus deux colonnes de chiffres, débordaient de
              l'écran : la mesure sortait du cadre. */}
          <div className="space-y-3 sm:space-y-1.5">
            {learning!.signaux.map((s: { signal: string; n: number; win_rate: number; roi: number }) => (
              <div key={s.signal} className="text-[11px] sm:flex sm:items-center sm:gap-3">
                <span className="block font-medium text-foreground sm:w-40 sm:shrink-0 sm:truncate">
                  {s.signal}
                </span>
                <div className="mt-1 flex items-center gap-2 sm:mt-0 sm:flex-1 sm:gap-3">
                  <div className="relative h-2 flex-1 rounded-full bg-muted">
                    <div className="absolute inset-y-0 left-1/2 w-px bg-border" />
                    <div
                      className="absolute inset-y-0 rounded-full"
                      style={{
                        left: s.roi >= 0 ? "50%" : `${50 - Math.min(Math.abs(s.roi) * 100, 50)}%`,
                        width: `${Math.min(Math.abs(s.roi) * 100, 50)}%`,
                        background: s.roi >= 0 ? DIVERGING_POS : DIVERGING_NEG,
                      }}
                    />
                  </div>
                  <span className={`w-12 shrink-0 text-right font-mono font-bold tabular-nums sm:w-14 ${tone(s.roi)}`}>
                    {signedPct(s.roi * 100, 0)}
                  </span>
                  <span className="w-20 shrink-0 text-right tabular-nums text-muted-foreground sm:w-24">
                    {pct(s.win_rate * 100, 0)} · {num(s.n)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* Brier course par course + poids features */}
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <Section
          title="Erreur course par course"
          desc="Brier de chaque course analysée, de la plus ancienne à la plus récente. Les points rouges sont les courses classées « surprise »."
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
            <ResponsiveContainer width="100%" height={210}>
              <LineChart data={histPoints} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid {...GRID} />
                <XAxis dataKey="date" hide />
                <YAxis domain={[0, 0.5]} tick={axisTick} axisLine={axisLine} tickLine={tickLine} width={40} tickFormatter={(v) => v.toFixed(2)} />
                <ReferenceLine y={0.25} stroke="#EF4444" strokeDasharray="4 4" label={{ value: "seuil critique 0,25", fontSize: 10, fill: "#EF4444", position: "insideTopLeft" }} />
                <ReferenceLine y={0.18} stroke="#10B981" strokeDasharray="4 4" label={{ value: "cible 0,18", fontSize: 10, fill: "#10B981", position: "insideBottomLeft" }} />
                <Tooltip content={<ChartTooltip valueFormatter={(v) => v.toFixed(4)} />} />
                <Line
                  type="monotone" dataKey="brier" name="Brier" stroke="#3B82F6" strokeWidth={1.5}
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
          )}
        </Section>

        <Section
          title="Dérive des poids de features"
          desc="Écart entre le poids appris en ligne et le poids par défaut du groupe. Vert = le groupe a été renforcé par l'apprentissage, rouge = atténué. Zéro = le moteur n'a rien changé."
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
                      {f.poids_actuel >= 1.98 && <span className="ml-1 text-amber-700">· plafond 2,00 atteint</span>}
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
          <Note>
            Chaque groupe a son propre poids par défaut (cotes 1,20 · elo 1,00 · équipement 0,60) :
            c&apos;est l&apos;écart à CE défaut qui est tracé, pas le poids brut. Le moteur borne les
            poids à 2,00.
          </Note>
        </Section>
      </div>

      {/* Biais contextuels */}
      <Section
        title="Biais contextuels détectés"
        desc="Contextes (hippodrome, discipline, terrain) où le modèle se trompe systématiquement dans le même sens. La correction est appliquée à l'inférence."
        right={
          biasRows.length > 0 ? (
            <button
              onClick={() => setShowBiasAll((v) => !v)}
              className="inline-flex min-h-[2.25rem] items-center gap-1 rounded-lg px-2 text-[11px] font-semibold text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              {showBiasAll ? <><ChevronUp className="h-3 w-3" />Réduire</> : <><ChevronDown className="h-3 w-3" />Tout voir</>}
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
            <table className="w-full min-w-[620px] text-xs">
              <thead>
                <tr className="border-b border-border/70 text-[11px] uppercase tracking-wide text-muted-foreground">
                  <th className="py-2 pr-3 text-left font-semibold">Contexte</th>
                  <th className="px-2 py-2 text-left font-semibold">Discipline</th>
                  <th className="px-2 py-2 text-left font-semibold">Terrain</th>
                  <th className="px-2 py-2 text-right font-semibold">Courses</th>
                  <th className="px-2 py-2 text-right font-semibold">Surprises</th>
                  <th className="px-2 py-2 text-right font-semibold">Brier moyen</th>
                  <th className="py-2 pl-2 text-left font-semibold">Correction</th>
                </tr>
              </thead>
              <tbody>
                {biasRows.map((row, i) => (
                  <tr key={i} className="border-b border-border/50">
                    <td className="max-w-[180px] truncate py-2 pr-3 font-medium text-foreground" title={row.contexte}>
                      {row.hippodrome ?? row.contexte}
                    </td>
                    <td className="px-2 py-2 text-muted-foreground">{row.discipline ?? "—"}</td>
                    <td className="px-2 py-2 text-muted-foreground">{row.terrain ?? "—"}</td>
                    <td className="px-2 py-2 text-right tabular-nums text-muted-foreground">{num(row.nb_courses)}</td>
                    <td className="px-2 py-2 text-right tabular-nums text-amber-700">{pct((row.taux_surprise ?? 0) * 100)}</td>
                    <td className="px-2 py-2 text-right font-mono tabular-nums text-muted-foreground">{row.brier_moyen?.toFixed(4) ?? "—"}</td>
                    <td className="py-2 pl-2">
                      {!row.correction_factor ? (
                        <span className="text-[11px] text-muted-foreground">aucune</span>
                      ) : row.correction_appliquee ?? row.nb_courses >= (row.seuil_courses ?? 8) ? (
                        <span className="whitespace-nowrap rounded-full border border-blue-200 bg-blue-50 px-2 py-0.5 text-[11px] font-semibold text-blue-700"
                          title="Confiance réduite de 0,05 sur ce contexte, appliquée à chaque pronostic">
                          confiance −0,05
                        </span>
                      ) : (
                        <span className="whitespace-nowrap rounded-full border border-border bg-muted/40 px-2 py-0.5 text-[11px] font-semibold text-muted-foreground"
                          title={`Détectée, mais lue à l'inférence seulement à partir de ${row.seuil_courses ?? 8} courses`}>
                          en attente ({row.nb_courses}/{row.seuil_courses ?? 8})
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Note>
          La correction est binaire, jamais graduée : −0,05 de confiance dès qu&apos;un contexte
          dépasse 55 % de surprises sur au moins 8 courses, rien sinon. Elle n&apos;est jamais
          positive — un contexte où le favori tient mieux que la moyenne n&apos;est pas récompensé,
          seulement les contextes anormalement surprenants sont pénalisés.
        </Note>
      </Section>

      {/* Journal */}
      <Section
        title={<span className="flex items-center gap-2"><Zap className="h-4 w-4 text-emerald-700" />Journal d&apos;apprentissage</span>}
        desc="Les dernières courses digérées par le moteur, avec l'ajustement de température qu'elles ont provoqué."
      >
        {loadingHistory ? (
          <Empty>Chargement…</Empty>
        ) : !history?.length ? (
          <Empty>Aucune course analysée.</Empty>
        ) : (
          <div role="region" tabIndex={0} aria-label="Tableau de données, défilement" className="-mx-4 max-h-[26rem] overflow-auto overscroll-contain px-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring sm:-mx-5 sm:px-5">
            <table className="w-full min-w-[620px] text-xs">
              <thead className="sticky top-0 bg-card">
                <tr className="border-b border-border/70 text-[11px] uppercase tracking-wide text-muted-foreground">
                  <th className="py-2 pr-3 text-left font-semibold">Date</th>
                  <th className="px-2 py-2 text-left font-semibold">Hippodrome</th>
                  <th className="px-2 py-2 text-left font-semibold">Discipline</th>
                  <th className="px-2 py-2 text-right font-semibold">Brier</th>
                  <th className="px-2 py-2 text-right font-semibold">Partants</th>
                  <th className="px-2 py-2 text-right font-semibold">Proba du gagnant</th>
                  <th className="px-2 py-2 text-right font-semibold">Gagnant réel</th>
                </tr>
              </thead>
              <tbody>
                {history.map((h, i) => (
                  <tr key={h.log_id ?? i} className={`border-b border-border/50 ${h.was_surprise ? "bg-red-50/40" : ""}`}>
                    <td className="py-2 pr-3 font-mono text-muted-foreground">
                      {h.analyzed_at ? format(new Date(h.analyzed_at), "dd/MM HH:mm") : "—"}
                    </td>
                    <td className="px-2 py-2 font-medium text-foreground">{h.hippodrome ?? "—"}</td>
                    <td className="px-2 py-2 text-muted-foreground">{h.discipline ?? "—"}</td>
                    <td className={`px-2 py-2 text-right font-mono tabular-nums ${(h.brier_score ?? 0) > 0.25 ? "text-red-700" : (h.brier_score ?? 0) < 0.18 ? "text-emerald-700" : "text-foreground"}`}>
                      {h.brier_score?.toFixed(4) ?? "—"}
                    </td>
                    <td className="px-2 py-2 text-right tabular-nums text-muted-foreground">
                      {h.nb_partants ?? "—"}
                    </td>
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
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  );
}
