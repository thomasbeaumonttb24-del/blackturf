"use client";

import { useState } from "react";
import useSWR from "swr";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
  LineChart, Line, ReferenceLine, Cell,
} from "recharts";
import { axisTick, axisLine, tickLine, GRID } from "@/components/charts/chart-kit";
import {
  AlertTriangle, CheckCircle, Activity, Thermometer, Brain,
  BarChart3, RefreshCw, ChevronDown, ChevronUp, Clock, Cpu,
  TrendingUp, TrendingDown, Zap,
} from "lucide-react";
import { format } from "date-fns";
import { fr } from "date-fns/locale";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { adminApi, statsApi } from "@/lib/api";

// ─── types ───────────────────────────────────────────────────
interface Feature { name: string; weight: number }
interface HistoryEntry {
  log_id: string; hippodrome?: string; discipline?: string;
  brier_score?: number; was_surprise?: boolean;
  gagnant_proba_ia?: number; gagnant_rang_predit?: number;
  temperature_update?: number; analyzed_at: string;
}
interface BiasRow {
  contexte: string; discipline?: string; terrain?: string; hippodrome?: string;
  nb_courses: number; taux_surprise: number; brier_moyen?: number;
  correction_factor: number; favori_win_rate?: number;
}

// ─── helpers ─────────────────────────────────────────────────
function SeverityCard({ severity }: { severity: string }) {
  const cfg: Record<string, { label: string; color: string; bg: string; icon: React.ReactNode }> = {
    critical: { label: "Dérive critique", color: "text-red-400", bg: "bg-red-500/10 border-red-500/30", icon: <AlertTriangle className="w-5 h-5 text-red-400" /> },
    warning: { label: "Avertissement", color: "text-amber-400", bg: "bg-amber-500/10 border-amber-500/30", icon: <AlertTriangle className="w-5 h-5 text-amber-400" /> },
    none: { label: "Stable", color: "text-emerald-400", bg: "bg-emerald-500/10 border-emerald-500/30", icon: <CheckCircle className="w-5 h-5 text-emerald-400" /> },
  };
  const c = cfg[severity] ?? cfg.none;
  return (
    <div className={`rounded-xl border p-4 flex items-center gap-3 ${c.bg}`}>
      {c.icon}
      <div>
        <div className={`font-semibold ${c.color}`}>{c.label}</div>
        <div className="text-xs text-muted-foreground">Drift detector (ADWIN + Page-Hinkley)</div>
      </div>
    </div>
  );
}

function TemperatureGauge({ temp }: { temp?: number | null }) {
  const t = typeof temp === "number" && isFinite(temp) ? temp : 1.0;
  const pct = Math.min(Math.max(((t - 0.5) / 1.5) * 100, 0), 100);
  const color = t < 0.85 ? "#3b82f6" : t > 1.2 ? "#ef4444" : "#10b981";
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground">Froide (sharpens)</span>
        <span className="font-mono font-bold" style={{ color }}>{t.toFixed(4)}</span>
        <span className="text-muted-foreground">Chaude (flattens)</span>
      </div>
      <div className="h-3 rounded-full bg-muted/50 overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
      <div className="flex justify-between text-[10px] text-muted-foreground">
        <span>0.5</span><span>1.0</span><span>2.0</span>
      </div>
    </div>
  );
}

// ─── main ─────────────────────────────────────────────────────
export default function AlgorithmeMonitoringPage() {
  const { user } = useAuth();
  const [histLimit, setHistLimit] = useState(30);
  const [showBiasAll, setShowBiasAll] = useState(false);

  // ⚠️ Tous les hooks DOIVENT être appelés inconditionnellement (Rules of Hooks).
  // Les clés SWR sont gatées sur is_admin : null = pas de fetch tant que non-admin.
  const isAdmin = !!user?.is_admin;
  const { data: alState, mutate: refreshState, isLoading: loadingState } = useSWR(
    isAdmin ? "admin-al-state" : null,
    () => adminApi.alState().then((r) => r.data),
    { refreshInterval: 30_000 }
  );
  const { data: calib } = useSWR(
    isAdmin ? "admin-calibration-quality" : null,
    () => adminApi.calibrationQuality().then((r) => r.data),
    { refreshInterval: 120_000 }
  );
  const { data: history, isLoading: loadingHistory } = useSWR(
    isAdmin ? ["admin-al-history", histLimit] : null,
    () => adminApi.alHistory(histLimit).then((r) => r.data),
    { refreshInterval: 60_000 }
  );
  const { data: biasMatrix } = useSWR(
    isAdmin ? "admin-bias-matrix" : null,
    () => adminApi.biasMatrix().then((r) => r.data),
    { refreshInterval: 300_000 }
  );
  const { data: mlStatus } = useSWR(
    isAdmin ? "ml-status" : null,
    () => statsApi.mlStatus().then((r) => r.data),
    { refreshInterval: 30_000 }
  );
  // Santé de l'apprentissage : poids par profil + ROI par signal + edge (live 30s)
  const { data: learning } = useSWR(
    isAdmin ? "admin-learning-signals" : null,
    () => adminApi.learningSignals().then((r) => r.data),
    { refreshInterval: 30_000 }
  );
  // Convergence : preuve d'amélioration dans le temps (précision/Brier/edge/gains)
  const { data: converge } = useSWR(
    isAdmin ? "admin-learning-convergence" : null,
    () => adminApi.learningConvergence().then((r) => r.data),
    { refreshInterval: 60_000 }
  );

  // Garde d'accès APRÈS tous les hooks.
  if (!isAdmin) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <AlertTriangle className="w-12 h-12 text-amber-400 mx-auto mb-4" />
          <h2 className="text-xl font-bold mb-2">Accès refusé</h2>
          <p className="text-muted-foreground">Réservé aux administrateurs.</p>
        </div>
      </div>
    );
  }

  const al = alState?.adaptive_learning ?? mlStatus?.adaptive_learning ?? {};
  const dd = alState?.drift_detector ?? mlStatus?.drift_detector ?? {};
  const model = mlStatus?.model ?? {};
  const topFeatures: Feature[] = al.top_features ?? [];

  const histPoints: Array<{ date: string; brier: number; surprise: boolean; rang: number }> =
    (history ?? []).slice().reverse().map((h: HistoryEntry) => ({
      date: h.analyzed_at ? format(new Date(h.analyzed_at), "dd/MM HH:mm", { locale: fr }) : "",
      brier: h.brier_score ?? 0,
      surprise: h.was_surprise ?? false,
      rang: h.gagnant_rang_predit ?? 0,
    }));

  const biasRows: BiasRow[] = (biasMatrix ?? []).slice(0, showBiasAll ? 100 : 15);

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-7xl mx-auto px-4 py-8 space-y-8">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
              <Brain className="w-6 h-6 text-blue-400" />
              Monitoring Algorithme
            </h1>
            <p className="text-sm text-muted-foreground mt-0.5">
              Adaptive learning · Drift detection · Meta-learner · Biais contextuels
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => refreshState()}
            disabled={loadingState}
            className="gap-2"
          >
            <RefreshCw className={`w-4 h-4 ${loadingState ? "animate-spin" : ""}`} />
            Actualiser
          </Button>
        </div>

        {/* Status row */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Drift */}
          <SeverityCard severity={dd.severity ?? "none"} />

          {/* Temperature */}
          <Card className="border-border/60">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 mb-3">
                <Thermometer className="w-4 h-4 text-amber-400" />
                <span className="text-sm font-medium">Température calibration</span>
              </div>
              <TemperatureGauge temp={al.temperature ?? 1.0} />
              <div className="flex justify-between text-xs text-muted-foreground mt-2">
                <span>{al.n_races ?? 0} courses analysées</span>
                <span>EMA Brier: {al.brier_ema?.toFixed(3) ?? "—"}</span>
              </div>
            </CardContent>
          </Card>

          {/* Model */}
          <Card className="border-border/60">
            <CardContent className="p-4 space-y-2">
              <div className="flex items-center gap-2 mb-1">
                <Cpu className="w-4 h-4 text-blue-400" />
                <span className="text-sm font-medium">
                  Modèle v{model.version ?? "—"}
                  {mlStatus?.meta_learner?.is_trained && (
                    <Badge className="ml-2 bg-emerald-500/20 text-emerald-400 border-emerald-500/30 text-xs">
                      Meta-learner ✓
                    </Badge>
                  )}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="rounded bg-muted/40 p-2">
                  <span className="text-muted-foreground" title="Capacité à classer un gagnant devant un perdant. 0.5 = hasard, 1 = parfait. ~0.70-0.78 = bon pour le turf.">AUC-ROC ⓘ</span>
                  <div className="font-bold mt-0.5">{model.auc_roc ?? "—"}</div>
                </div>
                <div className="rounded bg-muted/40 p-2">
                  <span className="text-muted-foreground" title="Écart entre proba annoncée et réalité. Plus BAS = mieux calibré. ~0.17 = bon.">Brier ⓘ</span>
                  <div className="font-bold mt-0.5">{model.brier_score ?? "—"}</div>
                </div>
                <div className="rounded bg-muted/40 p-2">
                  <span className="text-muted-foreground" title="% de fois où le gagnant réel est dans les 3 chevaux prédits en tête.">Top-3 ⓘ</span>
                  <div className="font-bold mt-0.5">{model.precision_top3 ? `${(model.precision_top3 * 100).toFixed(1)}%` : "—"}</div>
                </div>
                <div className="rounded bg-muted/40 p-2">
                  <span className="text-muted-foreground" title="ROI simulé d'un backtest 10€ flat sur les value bets — indicatif, forte variance.">ROI sim. ⓘ</span>
                  <div className={`font-bold mt-0.5 ${(model.roi_simule ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                    {model.roi_simule != null ? `${model.roi_simule > 0 ? "+" : ""}${model.roi_simule}%` : "—"}
                  </div>
                </div>
              </div>
              <p className="text-[10px] text-muted-foreground/70">
                En clair : <b>AUC</b> = à quel point l&apos;algo trie bien les chevaux · <b>Brier</b> = ses probas sont-elles justes · <b>Top-3</b> = il vise juste · <b>ROI</b> = rentabilité simulée.
              </p>
              {model.trained_at && (
                <div className="text-[10px] text-muted-foreground flex items-center gap-1">
                  <Clock className="w-3 h-3" />
                  Entraîné le {format(new Date(model.trained_at), "d MMM yyyy à HH:mm", { locale: fr })}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Calibrations & apprentissage réellement appliqués à l'inférence */}
        {alState?.calibration && (
          <Card className="border-border/60">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 mb-3">
                <Cpu className="w-4 h-4 text-emerald-400" />
                <span className="text-sm font-medium">Calibrations appliquées à l&apos;inférence</span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
                <div className="rounded bg-muted/40 p-3">
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Calibration isotonique</span>
                    <Badge className={`text-[10px] ${alState.calibration.isotonique?.actif ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30" : "bg-muted text-muted-foreground"}`}>
                      {alState.calibration.isotonique?.actif ? "active" : "en attente"}
                    </Badge>
                  </div>
                  <div className="mt-1 text-muted-foreground">
                    {alState.calibration.isotonique?.n_points ?? 0} points · {alState.calibration.isotonique?.n_obs ?? 0} obs
                  </div>
                </div>
                <div className="rounded bg-muted/40 p-3">
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Calibration longshots</span>
                    <Badge className={`text-[10px] ${alState.calibration.longshots?.actif ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30" : "bg-muted text-muted-foreground"}`}>
                      {alState.calibration.longshots?.actif ? "active" : "en attente"}
                    </Badge>
                  </div>
                  <div className="mt-1 text-muted-foreground">
                    {alState.calibration.longshots?.n_obs ?? 0} obs
                  </div>
                </div>
                <div className="rounded bg-muted/40 p-3">
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Tilt poids features</span>
                    <Badge className={`text-[10px] ${alState.calibration.feature_weight_tilt?.actif ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30" : "bg-muted text-muted-foreground"}`}>
                      {alState.calibration.feature_weight_tilt?.actif ? "actif" : "en attente"}
                    </Badge>
                  </div>
                  <div className="mt-1 text-muted-foreground">
                    {alState.calibration.feature_weight_tilt?.courses_apprises ?? 0}/{alState.calibration.feature_weight_tilt?.courses_requises ?? 0} courses
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Qualité de calibration (reliability + ECE) */}
        {calib?.reliable && (
          <Card className="border-border/60">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 mb-3">
                <Cpu className="w-4 h-4 text-violet-400" />
                <span className="text-sm font-medium">Qualité de calibration — proba de victoire</span>
                <Badge className="ml-auto text-[10px] bg-violet-500/20 text-violet-300 border-violet-500/30">
                  {calib.verdict} · {calib.n_obs} obs
                </Badge>
              </div>
              <div className="grid grid-cols-3 gap-3 text-xs mb-3">
                <div className="rounded bg-muted/40 p-2">
                  <span className="text-muted-foreground">ECE</span>
                  <div className="font-bold mt-0.5">{(calib.ece * 100).toFixed(1)}%</div>
                </div>
                <div className="rounded bg-muted/40 p-2">
                  <span className="text-muted-foreground">Brier (victoire)</span>
                  <div className="font-bold mt-0.5">{calib.brier.toFixed(4)}</div>
                </div>
                <div className="rounded bg-muted/40 p-2">
                  <span className="text-muted-foreground">Taux victoire moyen</span>
                  <div className="font-bold mt-0.5">{(calib.base_rate * 100).toFixed(1)}%</div>
                </div>
              </div>
              {/* Reliability : proba prédite vs fréquence réelle par bin */}
              <div className="space-y-1">
                {calib.bins.filter((b: { n: number }) => b.n > 0).map((b: { lo: number; hi: number; n: number; proba_moy: number; freq_reelle: number }, i: number) => (
                  <div key={i} className="flex items-center gap-2 text-[10px]">
                    <span className="text-muted-foreground w-16 tabular-nums">{Math.round(b.lo * 100)}–{Math.round(b.hi * 100)}%</span>
                    <span className="tabular-nums text-muted-foreground">prédit {(b.proba_moy * 100).toFixed(0)}%</span>
                    <span className="tabular-nums font-semibold">→ réel {(b.freq_reelle * 100).toFixed(0)}%</span>
                    <span className="text-muted-foreground/60">({b.n})</span>
                  </div>
                ))}
              </div>
              <p className="text-[10px] text-muted-foreground mt-2">ECE bas = probas fiables (un cheval à 30% gagne ~30% du temps). Mesuré sur résultats réels.</p>
            </CardContent>
          </Card>
        )}

        {/* Santé de l'apprentissage : poids par profil + ROI par signal + edge */}
        {learning && (
          <Card className="border-border/60">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 mb-3">
                <Cpu className="w-4 h-4 text-emerald-400" />
                <span className="text-sm font-medium">Santé de l&apos;apprentissage — preuve live</span>
                {learning.edge && (
                  <Badge className={`ml-auto text-[10px] ${learning.edge.edge_ok ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/30" : "bg-rose-500/20 text-rose-300 border-rose-500/30"}`}>
                    edge {learning.edge.edge_ok ? "OK" : "à surveiller"}
                  </Badge>
                )}
              </div>

              {/* Edge hors-échantillon */}
              {learning.edge && (
                <div className="grid grid-cols-3 gap-3 text-xs mb-4">
                  <div className="rounded bg-muted/40 p-2">
                    <span className="text-muted-foreground">Win filtré</span>
                    <div className="font-bold mt-0.5 text-emerald-400">{(learning.edge.win_filtre * 100).toFixed(1)}%</div>
                  </div>
                  <div className="rounded bg-muted/40 p-2">
                    <span className="text-muted-foreground">Win baseline</span>
                    <div className="font-bold mt-0.5">{(learning.edge.win_baseline * 100).toFixed(1)}%</div>
                  </div>
                  <div className="rounded bg-muted/40 p-2">
                    <span className="text-muted-foreground">ROI plafonné</span>
                    <div className={`font-bold mt-0.5 ${learning.edge.roi_plafonne >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                      {learning.edge.roi_plafonne >= 0 ? "+" : ""}{learning.edge.roi_plafonne}%
                    </div>
                  </div>
                </div>
              )}

              {/* Poids appris par profil */}
              {learning.profil_weights?.profils && (
                <div className="mb-4">
                  <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1.5">Poids appris par profil (pronos émis réglés)</p>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                    {(["conservateur", "equilibre", "agressif"] as const).map((pk) => {
                      const p = learning.profil_weights.profils[pk];
                      if (!p) return null;
                      return (
                        <div key={pk} className="rounded bg-muted/30 p-2 text-xs">
                          <div className="flex items-center justify-between">
                            <span className="font-semibold capitalize">{pk}</span>
                            <span className="text-muted-foreground">{p.n_runs} runs</span>
                          </div>
                          {p.roi_global != null && (
                            <div className={`text-sm font-bold ${p.roi_global >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                              ROI {p.roi_global >= 0 ? "+" : ""}{p.roi_global}%
                            </div>
                          )}
                          <div className="mt-1 space-y-0.5">
                            {Object.entries(p.type_weights || {}).slice(0, 4).map(([t, w]) => (
                              <div key={t} className="flex justify-between text-[10px]">
                                <span className="text-muted-foreground truncate">{t}</span>
                                <span className={`font-mono ${(w as number) >= 1 ? "text-emerald-400" : "text-rose-400"}`}>×{(w as number).toFixed(2)}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  <p className="text-[10px] text-muted-foreground/60 mt-1">Actif dès 10 runs réglés/profil. En-dessous = neutre (jamais inventé).</p>
                </div>
              )}

              {/* ROI par signal */}
              {learning.signaux?.length > 0 && (
                <div>
                  <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1.5">ROI réel par signal (gagnants ↑ / pièges ↓)</p>
                  <div className="space-y-1">
                    {learning.signaux.map((s: { signal: string; n: number; win_rate: number; roi: number }) => (
                      <div key={s.signal} className="flex items-center gap-2 text-[11px]">
                        <span className="w-40 shrink-0 truncate font-medium">{s.signal}</span>
                        <span className={`w-16 text-right font-mono font-bold ${s.roi >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                          {s.roi >= 0 ? "+" : ""}{Math.round(s.roi)}%
                        </span>
                        <span className="text-muted-foreground tabular-nums">win {Math.round(s.win_rate)}% · {s.n}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              <p className="text-[10px] text-muted-foreground mt-3">Recalculé à chaque fin de course + chaque nuit. 100% mesuré sur résultats réels.</p>
            </CardContent>
          </Card>
        )}

        {/* Convergence de l'apprentissage — preuve VISUELLE que l'algo s'améliore */}
        {converge && (
          <Card className="border-border/60">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 mb-1">
                <TrendingUp className="w-4 h-4 text-emerald-400" />
                <span className="text-sm font-medium">L&apos;algorithme s&apos;améliore-t-il ? — convergence</span>
              </div>
              <p className="text-[11px] text-muted-foreground mb-4">
                Tout est mesuré sur les vraies courses terminées. Si l&apos;algorithme apprend bien :
                la <b className="text-amber-500">précision monte</b>, l&apos;<b className="text-blue-400">erreur Brier baisse</b>,
                et les <b className="text-emerald-400">gains cumulés montent</b>.
              </p>

              {/* Précision top-3 (↑) + erreur Brier (↓) par semaine */}
              {converge.par_semaine?.length > 1 && (
                <div className="mb-5">
                  <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1">
                    Précision &amp; erreur, semaine par semaine
                  </p>
                  <ResponsiveContainer width="100%" height={180}>
                    <LineChart data={converge.par_semaine} margin={{ top: 6, right: 6, bottom: 0, left: -10 }}>
                      <CartesianGrid {...GRID} />
                      <XAxis dataKey="semaine" tick={axisTick} axisLine={axisLine} tickLine={tickLine} />
                      <YAxis yAxisId="p" domain={[0, 100]} tick={axisTick} axisLine={axisLine} tickLine={tickLine} tickFormatter={(v) => `${v}%`} />
                      <YAxis yAxisId="b" orientation="right" domain={[0, 0.4]} tick={axisTick} axisLine={axisLine} tickLine={tickLine} />
                      <Tooltip contentStyle={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: 10, fontSize: 12 }}
                        formatter={(v: number, n: string) => n.includes("Brier") ? [v?.toFixed?.(3) ?? v, "Erreur Brier"] : [`${v}%`, n]} />
                      <Line yAxisId="p" type="monotone" name="Précision top-3" dataKey="precision_top3" stroke="#F59E0B" strokeWidth={2.5} dot={{ r: 3 }} />
                      <Line yAxisId="b" type="monotone" name="Erreur Brier" dataKey="brier" stroke="#3B82F6" strokeWidth={2} strokeDasharray="5 3" connectNulls dot={{ r: 2 }} />
                    </LineChart>
                  </ResponsiveContainer>
                  <p className="text-[10px] text-muted-foreground/60 mt-1">
                    <span className="text-amber-500">▲ Précision top-3</span> = le gagnant finit dans les 3 premiers prédits.
                    <span className="text-blue-400 ml-2">▼ Brier</span> = écart proba/réalité (plus bas = mieux calibré).
                  </p>
                </div>
              )}

              {/* Gain net cumulé par profil (doit monter) */}
              {converge.profil_cumul && Object.keys(converge.profil_cumul).length > 0 && (() => {
                const COLORS: Record<string, string> = { Prudent: "#10B981", Modéré: "#3B82F6", Risqué: "#EF4444" };
                // Fusionne les 3 séries par jour
                const jours: string[] = [];
                Object.values(converge.profil_cumul as Record<string, Array<{ jour: string; cumul: number }>>).forEach((s) =>
                  s.forEach((p) => { if (!jours.includes(p.jour)) jours.push(p.jour); }));
                const data = jours.map((j) => {
                  const row: Record<string, number | string> = { jour: j };
                  Object.entries(converge.profil_cumul as Record<string, Array<{ jour: string; cumul: number }>>).forEach(([k, s]) => {
                    const pt = s.find((p) => p.jour === j); if (pt) row[k] = pt.cumul;
                  });
                  return row;
                });
                return (
                  <div>
                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1">
                      Gain net cumulé par profil (10€/course, rapports PMU réels)
                    </p>
                    <ResponsiveContainer width="100%" height={180}>
                      <LineChart data={data} margin={{ top: 6, right: 6, bottom: 0, left: -6 }}>
                        <CartesianGrid {...GRID} />
                        <XAxis dataKey="jour" tick={axisTick} axisLine={axisLine} tickLine={tickLine} />
                        <YAxis tick={axisTick} axisLine={axisLine} tickLine={tickLine} tickFormatter={(v) => `${v}€`} />
                        <ReferenceLine y={0} stroke="#9CA3AF" strokeDasharray="2 2" />
                        <Tooltip contentStyle={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: 10, fontSize: 12 }}
                          formatter={(v: number, n: string) => [`${v >= 0 ? "+" : ""}${v}€`, n]} />
                        {Object.keys(converge.profil_cumul).map((k) => (
                          <Line key={k} type="monotone" dataKey={k} name={k} stroke={COLORS[k] || "#6B7280"} strokeWidth={2} dot={false} connectNulls />
                        ))}
                      </LineChart>
                    </ResponsiveContainer>
                    <p className="text-[10px] text-muted-foreground/60 mt-1">
                      Chaque courbe = capital cumulé d&apos;un profil en jouant 10€/course sur l&apos;historique réglé. Monte = profil rentable.
                    </p>
                  </div>
                );
              })()}

              {/* Edge hors-échantillon : le filtre bat-il le marché ? */}
              {converge.edge_histo?.length > 0 && (
                <div className="mt-4 rounded bg-muted/30 p-2.5">
                  <p className="text-[11px] font-medium mb-1">Edge hors-échantillon (dernière mesure)</p>
                  {(() => {
                    const last = converge.edge_histo[converge.edge_histo.length - 1];
                    return (
                      <p className="text-[11px] text-muted-foreground">
                        Sur des courses jamais apprises, les paris à forte conviction gagnent{" "}
                        <b className={last.win_filtre >= (last.win_baseline || 0) ? "text-emerald-400" : "text-rose-400"}>{last.win_filtre}%</b>{" "}
                        contre <b>{last.win_baseline}%</b> en jouant tout — ROI plafonné{" "}
                        <b className={last.roi >= 0 ? "text-emerald-400" : "text-rose-400"}>{last.roi >= 0 ? "+" : ""}{last.roi}%</b>.{" "}
                        {last.edge_ok ? "L'avantage tient ✓" : "Avantage à surveiller"}.
                      </p>
                    );
                  })()}
                </div>
              )}

              {/* Dernières victoires de l'algorithme — concret, parlant */}
              {converge.victoires?.length > 0 && (
                <div className="mt-5">
                  <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1.5">
                    Dernières victoires de l&apos;algorithme (plan profil net positif)
                  </p>
                  <div className="space-y-1">
                    {converge.victoires.map((v: { course_id: string; code: string | null; hippodrome: string; date: string | null; profil: string; net: number }, i: number) => (
                      <a key={i} href={`/courses/${v.course_id}`}
                        className="flex items-center gap-2 text-[11px] rounded px-2 py-1.5 hover:bg-accent/30 transition-colors">
                        <span className="text-muted-foreground tabular-nums w-12 shrink-0">
                          {v.date ? new Date(v.date).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" }) : "—"}
                        </span>
                        <span className="font-medium w-14 shrink-0">{v.code ?? "—"}</span>
                        <span className="text-muted-foreground truncate flex-1">{v.hippodrome}</span>
                        <span className="text-[10px] text-muted-foreground shrink-0">{v.profil}</span>
                        <span className="font-mono font-bold text-emerald-500 w-16 text-right shrink-0">+{v.net.toFixed(2)}€</span>
                      </a>
                    ))}
                  </div>
                  <p className="text-[10px] text-muted-foreground/60 mt-1">
                    Meilleur profil gagnant par course · gain net réel (rapports PMU) · cliquable.
                  </p>
                </div>
              )}

              <p className="text-[10px] text-muted-foreground/60 mt-3">
                Recalculé à chaque fin de course + chaque nuit. Aucune donnée inventée.
              </p>
            </CardContent>
          </Card>
        )}

        {/* Drift signals */}
        {(dd.adwin_triggered || dd.ph_triggered) && (
          <Card className="border-amber-500/40 bg-amber-500/5">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 mb-2">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
                <span className="text-sm font-semibold text-amber-400">Signaux de dérive actifs</span>
              </div>
              <div className="flex gap-3 text-xs">
                {dd.adwin_triggered && (
                  <Badge className="bg-red-500/20 text-red-400 border-red-500/30">ADWIN déclenché</Badge>
                )}
                {dd.ph_triggered && (
                  <Badge className="bg-orange-500/20 text-orange-400 border-orange-500/30">Page-Hinkley déclenché</Badge>
                )}
                <span className="text-muted-foreground">
                  Brier moyen : {dd.brier_mean?.toFixed(4) ?? "—"} ·
                  Taux surprise : {dd.surprise_rate != null ? `${(dd.surprise_rate * 100).toFixed(1)}%` : "—"}
                </span>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Charts row */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

          {/* Brier history */}
          <Card className="border-border/60">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base flex items-center gap-2">
                  <Activity className="w-4 h-4 text-blue-400" />
                  Historique Brier score
                </CardTitle>
                <div className="flex gap-1">
                  {[15, 30, 50].map((n) => (
                    <button
                      key={n}
                      onClick={() => setHistLimit(n)}
                      className={`text-xs px-2 py-0.5 rounded ${histLimit === n ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground"}`}
                    >
                      {n}
                    </button>
                  ))}
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {loadingHistory || histPoints.length === 0 ? (
                <div className="h-48 flex items-center justify-center text-sm text-muted-foreground">
                  {loadingHistory ? "Chargement…" : "Aucune donnée"}
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart data={histPoints} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid {...GRID} />
                    <XAxis dataKey="date" hide />
                    <YAxis domain={[0, 0.5]} tick={axisTick} axisLine={axisLine} tickLine={tickLine} width={40} tickFormatter={(v) => v.toFixed(2)} />
                    <Tooltip
                      contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 11 }}
                      formatter={(v: number) => [v.toFixed(4), "Brier"]}
                    />
                    <ReferenceLine y={0.25} stroke="#ef4444" strokeDasharray="4 4" strokeWidth={1} label={{ value: "0.25", fontSize: 10, fill: "#ef4444" }} />
                    <ReferenceLine y={0.18} stroke="#10b981" strokeDasharray="4 4" strokeWidth={1} label={{ value: "0.18", fontSize: 10, fill: "#10b981" }} />
                    <Line
                      type="monotone"
                      dataKey="brier"
                      stroke="#3b82f6"
                      strokeWidth={1.5}
                      dot={(props) => {
                        const { cx, cy, payload, index } = props;
                        if (cx == null || cy == null || !payload) return <g key={index} />;
                        const surprise = !!payload.surprise;
                        return (
                          <circle
                            key={index}
                            cx={cx}
                            cy={cy}
                            r={surprise ? 4 : 2}
                            fill={surprise ? "#ef4444" : "#3b82f6"}
                            stroke="none"
                          />
                        );
                      }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              )}
              <p className="text-[10px] text-muted-foreground mt-2">
                <span className="inline-block w-2 h-2 rounded-full bg-red-500 mr-1" />Surprise
                <span className="inline-block w-2 h-2 rounded-full bg-blue-500 mr-1 ml-3" />Normal
                · Vert = cible ≤0.18, Rouge = seuil critique ≥0.25
              </p>
            </CardContent>
          </Card>

          {/* Feature weights */}
          <Card className="border-border/60">
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <BarChart3 className="w-4 h-4 text-amber-400" />
                Poids features adaptatifs
              </CardTitle>
            </CardHeader>
            <CardContent>
              {topFeatures.length === 0 ? (
                <div className="h-48 flex items-center justify-center text-sm text-muted-foreground">
                  Poids non disponibles (modèle en cours d&apos;apprentissage)
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={topFeatures} layout="vertical" margin={{ left: 0, right: 8 }}>
                    <CartesianGrid {...GRID} horizontal={false} vertical />
                    <XAxis type="number" tick={axisTick} axisLine={axisLine} tickLine={tickLine} tickFormatter={(v) => v.toFixed(2)} />
                    <YAxis type="category" dataKey="name" tick={{ fontSize: 9, fill: "#9CA3AF" }} axisLine={axisLine} tickLine={tickLine} width={100} />
                    <Tooltip
                      contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 11 }}
                      formatter={(v: number) => [v.toFixed(4), "Poids adaptatif"]}
                    />
                    <Bar dataKey="weight" radius={[0, 4, 4, 0]}>
                      {topFeatures.map((f, i) => (
                        <Cell
                          key={i}
                          fill={f.weight > 0 ? "#10b981" : "#ef4444"}
                          fillOpacity={0.7 + 0.3 * (1 - i / topFeatures.length)}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Learning history table */}
        <Card className="border-border/60">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Zap className="w-4 h-4 text-emerald-400" />
              Journal d&apos;apprentissage récent
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {loadingHistory ? (
              <div className="p-8 text-center text-sm text-muted-foreground">Chargement…</div>
            ) : !history?.length ? (
              <div className="p-8 text-center text-sm text-muted-foreground">Aucune donnée disponible</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border/60">
                      <th className="text-left px-4 py-2.5 text-muted-foreground font-medium">Date</th>
                      <th className="text-left px-4 py-2.5 text-muted-foreground font-medium">Hippodrome</th>
                      <th className="text-left px-4 py-2.5 text-muted-foreground font-medium">Discipline</th>
                      <th className="text-right px-4 py-2.5 text-muted-foreground font-medium">Brier</th>
                      <th className="text-right px-4 py-2.5 text-muted-foreground font-medium">Proba IA</th>
                      <th className="text-right px-4 py-2.5 text-muted-foreground font-medium">Rang prédit</th>
                      <th className="text-center px-4 py-2.5 text-muted-foreground font-medium">Surprise</th>
                      <th className="text-right px-4 py-2.5 text-muted-foreground font-medium">ΔT°</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(history as HistoryEntry[]).map((h, i) => (
                      <tr
                        key={h.log_id ?? i}
                        className={`border-b border-border/30 hover:bg-muted/20 transition-colors ${h.was_surprise ? "bg-red-500/5" : ""}`}
                      >
                        <td className="px-4 py-2 text-muted-foreground font-mono">
                          {h.analyzed_at ? format(new Date(h.analyzed_at), "dd/MM HH:mm") : "—"}
                        </td>
                        <td className="px-4 py-2 font-medium">{h.hippodrome ?? "—"}</td>
                        <td className="px-4 py-2 text-muted-foreground">{h.discipline ?? "—"}</td>
                        <td className={`px-4 py-2 text-right font-mono ${(h.brier_score ?? 0) > 0.25 ? "text-red-400" : (h.brier_score ?? 0) < 0.18 ? "text-emerald-400" : "text-foreground"}`}>
                          {h.brier_score?.toFixed(4) ?? "—"}
                        </td>
                        <td className="px-4 py-2 text-right font-mono">
                          {h.gagnant_proba_ia != null ? `${(h.gagnant_proba_ia * 100).toFixed(1)}%` : "—"}
                        </td>
                        <td className="px-4 py-2 text-right">
                          {h.gagnant_rang_predit != null ? (
                            <span className={`font-bold ${h.gagnant_rang_predit === 1 ? "text-emerald-400" : h.gagnant_rang_predit <= 3 ? "text-amber-400" : "text-muted-foreground"}`}>
                              #{h.gagnant_rang_predit}
                            </span>
                          ) : "—"}
                        </td>
                        <td className="px-4 py-2 text-center">
                          {h.was_surprise ? (
                            <span className="text-red-400 font-bold">⚡</span>
                          ) : (
                            <span className="text-muted-foreground">·</span>
                          )}
                        </td>
                        <td className="px-4 py-2 text-right font-mono">
                          {h.temperature_update != null ? (
                            <span className={`text-xs ${h.temperature_update > 0 ? "text-red-400" : "text-emerald-400"} flex items-center justify-end gap-0.5`}>
                              {h.temperature_update > 0 ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                              {h.temperature_update > 0 ? "+" : ""}{h.temperature_update.toFixed(4)}
                            </span>
                          ) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Bias matrix */}
        <Card className="border-border/60">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base flex items-center gap-2">
                <Brain className="w-4 h-4 text-purple-400" />
                Matrice de biais contextuels
              </CardTitle>
              {biasRows.length > 0 && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-xs gap-1"
                  onClick={() => setShowBiasAll((v) => !v)}
                >
                  {showBiasAll ? <><ChevronUp className="w-3 h-3" />Réduire</> : <><ChevronDown className="w-3 h-3" />Tout voir</>}
                </Button>
              )}
            </div>
          </CardHeader>
          <CardContent className="p-0">
            {!biasMatrix ? (
              <div className="p-8 text-center text-sm text-muted-foreground">Chargement…</div>
            ) : biasRows.length === 0 ? (
              <div className="p-8 text-center text-sm text-muted-foreground">
                Pas encore de biais détectés (nécessite ≥5 courses par contexte)
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border/60">
                      <th className="text-left px-4 py-2.5 text-muted-foreground font-medium">Contexte</th>
                      <th className="text-left px-4 py-2.5 text-muted-foreground font-medium">Discipline</th>
                      <th className="text-left px-4 py-2.5 text-muted-foreground font-medium">Terrain</th>
                      <th className="text-right px-4 py-2.5 text-muted-foreground font-medium">Courses</th>
                      <th className="text-right px-4 py-2.5 text-muted-foreground font-medium">Surprises</th>
                      <th className="text-right px-4 py-2.5 text-muted-foreground font-medium">Brier moy.</th>
                      <th className="text-right px-4 py-2.5 text-muted-foreground font-medium">Correction</th>
                    </tr>
                  </thead>
                  <tbody>
                    {biasRows.map((row, i) => (
                      <tr key={i} className="border-b border-border/30 hover:bg-muted/20 transition-colors">
                        <td className="px-4 py-2 font-mono text-[10px] text-muted-foreground max-w-[140px] truncate" title={row.contexte}>
                          {row.hippodrome ?? row.contexte}
                        </td>
                        <td className="px-4 py-2">
                          {row.discipline ? (
                            <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4">{row.discipline}</Badge>
                          ) : "—"}
                        </td>
                        <td className="px-4 py-2 text-muted-foreground">{row.terrain ?? "—"}</td>
                        <td className="px-4 py-2 text-right">{row.nb_courses}</td>
                        <td className="px-4 py-2 text-right text-amber-400">
                          {(((row.taux_surprise ?? 0) * 100)).toFixed(1)}%
                        </td>
                        <td className="px-4 py-2 text-right font-mono">
                          {row.brier_moyen?.toFixed(4) ?? "—"}
                        </td>
                        <td className="px-4 py-2 text-right">
                          <span
                            className={`font-bold font-mono ${Math.abs(row.correction_factor ?? 0) > 0.08 ? ((row.correction_factor ?? 0) > 0 ? "text-red-400" : "text-blue-400") : "text-muted-foreground"}`}
                          >
                            {(row.correction_factor ?? 0) > 0 ? "+" : ""}{(row.correction_factor ?? 0).toFixed(4)}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>

      </div>
    </div>
  );
}
