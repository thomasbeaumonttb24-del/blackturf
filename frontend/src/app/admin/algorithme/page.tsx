"use client";

import { useState } from "react";
import useSWR from "swr";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, ReferenceLine, Cell,
} from "recharts";
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

function TemperatureGauge({ temp }: { temp: number }) {
  const pct = Math.min(Math.max(((temp - 0.5) / 1.5) * 100, 0), 100);
  const color = temp < 0.85 ? "#3b82f6" : temp > 1.2 ? "#ef4444" : "#10b981";
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground">Froide (sharpens)</span>
        <span className="font-mono font-bold" style={{ color }}>{temp.toFixed(4)}</span>
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

  if (!user?.is_admin) {
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

  const { data: alState, mutate: refreshState, isLoading: loadingState } = useSWR(
    "admin-al-state",
    () => adminApi.alState().then((r) => r.data),
    { refreshInterval: 30_000 }
  );
  const { data: history, isLoading: loadingHistory } = useSWR(
    ["admin-al-history", histLimit],
    () => adminApi.alHistory(histLimit).then((r) => r.data),
    { refreshInterval: 60_000 }
  );
  const { data: biasMatrix } = useSWR(
    "admin-bias-matrix",
    () => adminApi.biasMatrix().then((r) => r.data),
    { refreshInterval: 300_000 }
  );
  const { data: mlStatus } = useSWR(
    "ml-status",
    () => statsApi.mlStatus().then((r) => r.data),
    { refreshInterval: 30_000 }
  );

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
                  <span className="text-muted-foreground">AUC-ROC</span>
                  <div className="font-bold mt-0.5">{model.auc_roc ?? "—"}</div>
                </div>
                <div className="rounded bg-muted/40 p-2">
                  <span className="text-muted-foreground">Brier</span>
                  <div className="font-bold mt-0.5">{model.brier_score ?? "—"}</div>
                </div>
                <div className="rounded bg-muted/40 p-2">
                  <span className="text-muted-foreground">Top-3</span>
                  <div className="font-bold mt-0.5">{model.precision_top3 ? `${(model.precision_top3 * 100).toFixed(1)}%` : "—"}</div>
                </div>
                <div className="rounded bg-muted/40 p-2">
                  <span className="text-muted-foreground">ROI sim.</span>
                  <div className={`font-bold mt-0.5 ${(model.roi_simule ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                    {model.roi_simule != null ? `${model.roi_simule > 0 ? "+" : ""}${model.roi_simule}%` : "—"}
                  </div>
                </div>
              </div>
              {model.trained_at && (
                <div className="text-[10px] text-muted-foreground flex items-center gap-1">
                  <Clock className="w-3 h-3" />
                  Entraîné le {format(new Date(model.trained_at), "d MMM yyyy à HH:mm", { locale: fr })}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

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
                  <LineChart data={histPoints}>
                    <XAxis dataKey="date" hide />
                    <YAxis domain={[0, 0.5]} tick={{ fontSize: 10 }} tickFormatter={(v) => v.toFixed(2)} />
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
                        const { cx, cy, payload } = props;
                        return payload.surprise
                          ? <circle key={props.key} cx={cx} cy={cy} r={4} fill="#ef4444" stroke="none" />
                          : <circle key={props.key} cx={cx} cy={cy} r={2} fill="#3b82f6" stroke="none" />;
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
                    <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={(v) => v.toFixed(2)} />
                    <YAxis type="category" dataKey="name" tick={{ fontSize: 9 }} width={100} />
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
                          {(row.taux_surprise * 100).toFixed(1)}%
                        </td>
                        <td className="px-4 py-2 text-right font-mono">
                          {row.brier_moyen?.toFixed(4) ?? "—"}
                        </td>
                        <td className="px-4 py-2 text-right">
                          <span
                            className={`font-bold font-mono ${Math.abs(row.correction_factor) > 0.08 ? (row.correction_factor > 0 ? "text-red-400" : "text-blue-400") : "text-muted-foreground"}`}
                          >
                            {row.correction_factor > 0 ? "+" : ""}{row.correction_factor.toFixed(4)}
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
