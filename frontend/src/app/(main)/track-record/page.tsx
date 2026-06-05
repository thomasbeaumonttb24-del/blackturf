"use client";

import useSWR from "swr";
import Link from "next/link";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import {
  TrendingUp, Brain, Zap, Trophy, CheckCircle2, XCircle,
  ChevronRight, Star, Activity,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { statsApi } from "@/lib/api";
import { cn } from "@/lib/utils";

// ─── Types ───────────────────────────────────────────────────
interface TrackRecord {
  global: {
    accuracy_top1: number;
    accuracy_top3: number;
    brier_moyen: number;
    nb_courses_analysees: number;
    nb_surprises: number;
  };
  by_month: Array<{
    mois: string;
    accuracy_top3: number;
    nb_predictions: number;
    nb_surprises: number;
  }>;
  by_discipline: Array<{
    discipline: string;
    nb_courses: number;
    accuracy_top3: number;
  }>;
  best_pronostics: Array<{
    course_id: string;
    hippodrome: string;
    discipline: string;
    date: string | null;
    cheval_predit: string;
    cote: number | null;
    proba_top1: number;
    gagnant_reel: string | null;
    correct: boolean | null;
  }>;
  vb_performance: Array<{
    niveau: number;
    nb_vbs: number;
    win_rate: number;
    roi: number;
  }>;
  adaptive_learning: {
    temperature?: number;
    n_races?: number;
    brier_ema?: number;
  };
}

const NIVEAU_LABELS: Record<number, string> = {
  1: "1 étoile", 2: "2 étoiles", 3: "3 étoiles", 4: "4 étoiles",
};
const NIVEAU_COLORS: Record<number, string> = {
  1: "text-zinc-400", 2: "text-blue-400", 3: "text-amber-400", 4: "text-emerald-400",
};

function StarRating({ n }: { n: number }) {
  return (
    <span className="flex gap-0.5">
      {Array.from({ length: 4 }).map((_, i) => (
        <Star key={i} className={cn("w-3 h-3", i < n ? "fill-amber-400 text-amber-400" : "text-zinc-600")} />
      ))}
    </span>
  );
}

function AccuracyTooltip({ active, payload, label }: {
  active?: boolean; payload?: Array<{ value: number; name: string }>; label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2 text-xs shadow-lg">
      <div className="font-medium text-foreground mb-1">{label}</div>
      {payload.map((p) => (
        <div key={p.name} className="text-amber-400 font-bold">{p.value}% précision top-3</div>
      ))}
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────
export default function TrackRecordPage() {
  const { data, isLoading } = useSWR<TrackRecord>(
    "track-record",
    () => statsApi.trackRecord().then((r) => r.data),
    { refreshInterval: 3_600_000 }  // matches server cache
  );

  if (isLoading || !data) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="text-muted-foreground text-sm animate-pulse">Chargement du track-record…</div>
      </div>
    );
  }

  const g = data.global;

  return (
    <div className="min-h-screen bg-background">

      {/* ── Hero ──────────────────────────────────────────── */}
      <div className="relative overflow-hidden border-b border-border/40 bg-gradient-to-br from-background via-background to-amber-950/10">
        <div className="max-w-7xl mx-auto px-4 py-14 sm:py-20">
          <div className="text-center max-w-2xl mx-auto">
            <Badge className="mb-4 bg-amber-500/20 text-amber-400 border-amber-500/30 px-3 py-1">
              Track-record IA — Données réelles
            </Badge>
            <h1 className="text-3xl sm:text-4xl font-extrabold text-foreground mb-4 leading-tight">
              L&apos;IA BlackTurf prouve ses résultats
            </h1>
            <p className="text-lg text-muted-foreground mb-8">
              Chaque prédiction est archivée et vérifiable.
            </p>

            {/* Hero stats */}
            <div className="flex flex-wrap justify-center gap-6 sm:gap-10">
              <div className="text-center">
                <div className="text-4xl font-black text-amber-400 tabular-nums">
                  {g.accuracy_top3}%
                </div>
                <div className="text-xs text-muted-foreground mt-1">Précision Top-3</div>
              </div>
              <div className="text-center">
                <div className="text-4xl font-black text-foreground tabular-nums">
                  {g.nb_courses_analysees.toLocaleString("fr-FR")}
                </div>
                <div className="text-xs text-muted-foreground mt-1">Courses analysées</div>
              </div>
              <div className="text-center">
                <div className="text-4xl font-black text-blue-400 tabular-nums">
                  {g.brier_moyen.toFixed(3)}
                </div>
                <div className="text-xs text-muted-foreground mt-1">Score Brier moyen</div>
              </div>
              <div className="text-center">
                <div className="text-4xl font-black text-foreground tabular-nums">
                  {g.accuracy_top1}%
                </div>
                <div className="text-xs text-muted-foreground mt-1">Précision Top-1</div>
              </div>
            </div>

            <div className="mt-8 flex justify-center gap-3">
              <Button asChild variant="brand" size="lg">
                <Link href="/inscription">Essayer gratuitement</Link>
              </Button>
              <Button asChild variant="outline" size="lg">
                <Link href="/tarifs">Voir les offres</Link>
              </Button>
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 py-10 space-y-10">

        {/* ── Monthly accuracy chart ─────────────── */}
        <Card className="border-border/60">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-amber-400" />
              Précision Top-3 par mois (6 derniers mois)
            </CardTitle>
          </CardHeader>
          <CardContent>
            {data.by_month.every((m) => m.nb_predictions === 0) ? (
              <div className="h-48 flex items-center justify-center text-sm text-muted-foreground">
                Pas encore de données mensuelles
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={data.by_month} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.4} />
                  <XAxis
                    dataKey="mois"
                    tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                    axisLine={false}
                    tickLine={false}
                    domain={[0, 100]}
                    tickFormatter={(v) => `${v}%`}
                  />
                  <Tooltip content={<AccuracyTooltip />} />
                  <Line
                    type="monotone"
                    dataKey="accuracy_top3"
                    stroke="#f59e0b"
                    strokeWidth={2.5}
                    dot={{ r: 4, fill: "#f59e0b", strokeWidth: 0 }}
                    activeDot={{ r: 6, fill: "#f59e0b" }}
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        {/* ── VB performance + Discipline ───────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

          {/* VB Performance by niveau */}
          <Card className="border-border/60">
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Zap className="w-4 h-4 text-amber-400" />
                Performance Value Bets par niveau
              </CardTitle>
            </CardHeader>
            <CardContent>
              {data.vb_performance.every((v) => v.nb_vbs === 0) ? (
                <div className="py-6 text-center text-sm text-muted-foreground">
                  Pas encore de value bets résolus
                </div>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/40">
                      <th className="text-left py-2 text-xs font-medium text-muted-foreground">Niveau</th>
                      <th className="text-right py-2 text-xs font-medium text-muted-foreground">VBs</th>
                      <th className="text-right py-2 text-xs font-medium text-muted-foreground">Win rate</th>
                      <th className="text-right py-2 text-xs font-medium text-muted-foreground">ROI</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/30">
                    {data.vb_performance.map((v) => (
                      <tr key={v.niveau} className="hover:bg-accent/20 transition-colors">
                        <td className="py-3">
                          <div className="flex items-center gap-2">
                            <StarRating n={v.niveau} />
                            <span className={cn("text-xs font-medium", NIVEAU_COLORS[v.niveau])}>
                              {NIVEAU_LABELS[v.niveau]}
                            </span>
                          </div>
                        </td>
                        <td className="text-right py-3 tabular-nums text-foreground font-medium">
                          {v.nb_vbs}
                        </td>
                        <td className="text-right py-3 tabular-nums">
                          <span className={cn("font-medium",
                            v.win_rate >= 30 ? "text-emerald-400" : "text-muted-foreground"
                          )}>
                            {v.win_rate}%
                          </span>
                        </td>
                        <td className="text-right py-3 tabular-nums">
                          <span className={cn("font-bold",
                            v.roi >= 0 ? "text-emerald-400" : "text-red-400"
                          )}>
                            {v.roi >= 0 ? "+" : ""}{v.roi}%
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </CardContent>
          </Card>

          {/* By discipline */}
          <Card className="border-border/60">
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Trophy className="w-4 h-4 text-purple-400" />
                Précision par discipline
              </CardTitle>
            </CardHeader>
            <CardContent>
              {data.by_discipline.length === 0 ? (
                <div className="py-6 text-center text-sm text-muted-foreground">
                  Pas encore de données
                </div>
              ) : (
                <div className="space-y-4">
                  {data.by_discipline.map((d) => (
                    <div key={d.discipline}>
                      <div className="flex items-center justify-between mb-1.5">
                        <div>
                          <span className="text-sm font-medium text-foreground">{d.discipline}</span>
                          <span className="text-xs text-muted-foreground ml-2">{d.nb_courses} courses</span>
                        </div>
                        <span className={cn("text-sm font-bold tabular-nums",
                          d.accuracy_top3 >= 50 ? "text-emerald-400" :
                          d.accuracy_top3 >= 35 ? "text-amber-400" : "text-muted-foreground"
                        )}>
                          {d.accuracy_top3}%
                        </span>
                      </div>
                      <div className="h-2 rounded-full bg-muted overflow-hidden">
                        <div
                          className="h-full rounded-full bg-amber-400 transition-all"
                          style={{ width: `${Math.min(d.accuracy_top3, 100)}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* ── Best predictions ──────────────────── */}
        <Card className="border-border/60">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base flex items-center gap-2">
                <Star className="w-4 h-4 text-amber-400" />
                Les meilleurs pronostics
              </CardTitle>
              <span className="text-xs text-muted-foreground">
                Gagnant prédit rang 1, cote &gt; 5.0
              </span>
            </div>
          </CardHeader>
          <CardContent>
            {data.best_pronostics.length === 0 ? (
              <div className="py-8 text-center text-sm text-muted-foreground">
                Pas encore de pronostics haute cote archivés
              </div>
            ) : (
              <div className="space-y-2">
                {data.best_pronostics.map((p, i) => (
                  <Link
                    key={p.course_id + i}
                    href={`/courses/${p.course_id}`}
                    className="flex items-center justify-between p-3 rounded-lg border border-border/40 hover:border-brand-gold/40 hover:bg-accent/30 transition-all group"
                  >
                    <div className="flex items-center gap-3 min-w-0 flex-1">
                      <div className="text-lg font-black text-muted-foreground w-6 text-center shrink-0">
                        #{i + 1}
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-foreground text-sm">{p.cheval_predit}</span>
                          <Badge variant="outline" className="text-xs px-1.5 py-0 h-4 shrink-0">
                            {p.discipline}
                          </Badge>
                        </div>
                        <div className="text-xs text-muted-foreground mt-0.5">
                          {p.hippodrome} · {p.date}
                          {p.gagnant_reel && (
                            <span className="ml-2">
                              → Vainqueur réel: <span className="text-foreground font-medium">{p.gagnant_reel}</span>
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-4 shrink-0 ml-3">
                      <div className="text-right">
                        <div className="text-sm font-bold text-foreground">
                          {p.proba_top1}% proba
                        </div>
                        {p.cote && (
                          <div className="text-xs text-muted-foreground">Cote {p.cote}</div>
                        )}
                      </div>
                      {p.correct === true && (
                        <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
                      )}
                      {p.correct === false && (
                        <XCircle className="w-5 h-5 text-red-400 shrink-0" />
                      )}
                      <ChevronRight className="w-4 h-4 text-muted-foreground group-hover:text-foreground transition-colors" />
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* ── Adaptive learning card ────────────── */}
        {data.adaptive_learning.n_races !== undefined && (
          <Card className="border-border/60 border-blue-500/20 bg-blue-950/10">
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Brain className="w-4 h-4 text-blue-400" />
                L&apos;IA s&apos;améliore en continu
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
                <div className="text-center">
                  <div className="text-2xl font-bold text-blue-400 tabular-nums">
                    {data.adaptive_learning.n_races?.toLocaleString("fr-FR") ?? "—"}
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">Courses apprises</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold text-amber-400 tabular-nums">
                    {data.adaptive_learning.temperature?.toFixed(3) ?? "—"}
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">
                    Température (calibration)
                  </div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold text-foreground tabular-nums">
                    {data.adaptive_learning.brier_ema?.toFixed(4) ?? "—"}
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">Brier EMA (tendance)</div>
                </div>
              </div>
              <p className="text-xs text-muted-foreground mt-4 text-center max-w-lg mx-auto">
                Le modèle apprend de chaque course terminée. La température s&apos;ajuste automatiquement
                pour rester calibré sur les nouvelles conditions de terrain.
              </p>
              <div className="mt-4 flex justify-center">
                <div className="flex items-center gap-1.5 text-xs text-emerald-400">
                  <Activity className="w-3.5 h-3.5" />
                  Apprentissage adaptatif actif
                </div>
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
