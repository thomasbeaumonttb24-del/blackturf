"use client";

import useSWR from "swr";
import Link from "next/link";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import {
  TrendingUp, Brain, Zap, Trophy, CheckCircle2, XCircle, ArrowUpRight, Minus,
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
    favori_win_rate: number;
    favori_place_rate: number;
    nb_favoris_evalues: number;
    favori_roi: number;
    favori_mise_totale: number;
    favori_gain_total: number;
    favori_net: number;
  };
  clv?: { n: number; pct_beat_line: number; clv_implied: number; clv_median: number } | null;
  updated_at?: string;
  by_day: Array<{
    jour: string;
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
  derniers_pronostics: Array<{
    course_id: string;
    hippodrome: string;
    discipline: string;
    date: string | null;
    favori_nom: string;
    favori_numero: number;
    proba_top1: number;
    cote: number | null;
    favori_position: number;
    gagnant_nom: string | null;
    rang_ia_gagnant: number | null;
    verdict: "gagnant" | "place" | "top3" | "manque";
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

interface ProfilsBacktest {
  profils: Array<{
    profil: string;
    label: string;
    nb_courses: number;
    mise_totale: number;
    gain_total: number;
    gain_net: number;
    roi: number | null;
    roi_winsorise: number | null;
    taux_courses_beneficiaires: number | null;
  }>;
  nb_courses: number;
  mise_par_course: number;
  updated_at?: string;
  type_perf?: Record<string, { n: number; win_rate: number; roi_winsorise: number; poids_appris: number }>;
}

const NIVEAU_LABELS: Record<number, string> = {
  1: "1 étoile", 2: "2 étoiles", 3: "3 étoiles", 4: "4 étoiles",
};
const NIVEAU_COLORS: Record<number, string> = {
  1: "text-zinc-400", 2: "text-blue-400", 3: "text-amber-400", 4: "text-emerald-400",
};

const VERDICTS: Record<string, { emoji: string; label: string; cls: string }> = {
  gagnant: { emoji: "🎯", label: "Gagnant", cls: "border-emerald-300 bg-emerald-50 text-emerald-700" },
  place: { emoji: "✅", label: "Placé", cls: "border-amber-300 bg-amber-50 text-amber-700" },
  top3: { emoji: "➕", label: "Vainqueur top-3 IA", cls: "border-blue-300 bg-blue-50 text-blue-700" },
  manque: { emoji: "❌", label: "Manqué", cls: "border-rose-300 bg-rose-50 text-rose-700" },
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
    <div className="rounded-xl bg-white ring-1 ring-border px-3 py-2 text-xs shadow-md">
      <div className="font-medium text-foreground mb-1">{label}</div>
      {payload.map((p) => (
        <div key={p.name} className="font-bold tabular-nums" style={{ color: "#F59E0B" }}>{p.value}% de précision Top-3</div>
      ))}
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────
export default function TrackRecordPage() {
  const { data, isLoading } = useSWR<TrackRecord>(
    "track-record",
    () => statsApi.trackRecord().then((r) => r.data),
    { refreshInterval: 60_000, revalidateOnFocus: true }  // recalcul ~ à chaque fin de course
  );

  // Backtest par profil — calcul lourd côté API (cache 6h), pas de refresh agressif
  const { data: profilsData } = useSWR<ProfilsBacktest>(
    "stats-profils",
    () => statsApi.profils().then((r) => r.data),
    { refreshInterval: 300_000, revalidateOnFocus: true },  // maj ~ à chaque fin de course
  );

  if (isLoading || !data) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="text-muted-foreground text-sm animate-pulse">Chargement du palmarès…</div>
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
            <Badge className="mb-4 inline-flex items-center gap-1.5 bg-emerald-500/15 text-emerald-600 border-emerald-500/30 px-3 py-1">
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
              </span>
              Données réelles — mises à jour à chaque fin de course
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
              <div className="text-center">
                <div className="text-4xl font-black text-emerald-400 tabular-nums">
                  {g.favori_place_rate}%
                </div>
                <div className="text-xs text-muted-foreground mt-1">Favori IA placé (top-3)</div>
              </div>
              <div className="text-center">
                <div className={cn("text-4xl font-black tabular-nums", g.favori_roi >= 0 ? "text-emerald-500" : "text-rose-500")}>
                  {g.favori_roi >= 0 ? "+" : ""}{g.favori_roi}%
                </div>
                <div className="text-xs text-muted-foreground mt-1">
                  ROI réel — 1€ sur le favori
                  <span className="block text-[10px] text-muted-foreground/60">
                    {g.favori_net >= 0 ? "+" : ""}{g.favori_net}€ sur {g.favori_mise_totale} paris
                  </span>
                </div>
              </div>
            </div>
            <p className="mt-3 text-[11px] text-muted-foreground/60 max-w-xl mx-auto">
              ROI = backtest réel (1€ Simple Gagnant sur le favori IA, réglé sur l&apos;arrivée
              officielle et la cote PMU réelle). Échantillon limité, forte variance —
              les performances passées ne préjugent pas des résultats futurs.
            </p>
            {data.updated_at && (
              <p className="mt-2 text-[11px] text-muted-foreground/70">
                Dernière mise à jour : {new Date(data.updated_at).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })} · recalculé automatiquement à chaque fin de course
              </p>
            )}

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

        {/* ── CLV : l'IA bat-elle la ligne de clôture ? ─────────────── */}
        {data.clv && data.clv.n >= 10 && (
          <Card className="border-emerald-500/30 bg-gradient-to-br from-emerald-50/60 to-transparent">
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <TrendingUp className="w-4 h-4 text-emerald-500" />
                Closing Line Value — l&apos;IA anticipe le marché
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
                <div className="text-center">
                  <div className="text-3xl font-black tabular-nums text-emerald-600">{data.clv.pct_beat_line}%</div>
                  <div className="mt-1 text-xs text-muted-foreground">Picks battant la ligne de clôture</div>
                </div>
                <div className="text-center">
                  <div className="text-3xl font-black tabular-nums text-emerald-600">+{data.clv.clv_median}%</div>
                  <div className="mt-1 text-xs text-muted-foreground">CLV médian (cote prise vs clôture)</div>
                </div>
                <div className="text-center">
                  <div className="text-3xl font-black tabular-nums text-blue-500">+{data.clv.clv_implied}%</div>
                  <div className="mt-1 text-xs text-muted-foreground">Gain de proba implicite moyen</div>
                </div>
              </div>
              <p className="mt-4 text-[11px] leading-relaxed text-muted-foreground/80">
                Sur {data.clv.n} courses, la cote du favori IA <strong>baisse {data.clv.pct_beat_line}% du temps</strong> entre
                l&apos;ouverture et le départ : le marché bouge <strong>vers</strong> le pronostic de l&apos;IA. C&apos;est la
                métrique de référence des pros — battre la ligne de clôture prouve un avantage réel, indépendamment de la chance
                sur un résultat isolé. Calculé sur les cotes PMU réelles (ouverture vs clôture).
              </p>
            </CardContent>
          </Card>
        )}

        {/* ── Monthly accuracy chart ─────────────── */}
        <Card className="border-border/60">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-amber-400" />
              Précision Top-3 par jour (7 derniers jours)
            </CardTitle>
          </CardHeader>
          <CardContent>
            {(data.by_day ?? []).every((d) => d.nb_predictions === 0) ? (
              <div className="h-48 flex items-center justify-center text-sm text-muted-foreground">
                Aucune donnée journalière pour le moment
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={data.by_day ?? []} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#EEF1F6" vertical={false} />
                  <XAxis
                    dataKey="jour"
                    tick={{ fontSize: 11, fill: "#9CA3AF" }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fontSize: 11, fill: "#9CA3AF" }}
                    axisLine={false}
                    tickLine={false}
                    domain={[0, 100]}
                    tickFormatter={(v) => `${v}%`}
                  />
                  <Tooltip content={<AccuracyTooltip />} cursor={{ stroke: "#E5E7EB", strokeWidth: 1 }} />
                  <Line
                    type="monotone"
                    dataKey="accuracy_top3"
                    stroke="#F59E0B"
                    strokeWidth={3}
                    dot={{ r: 4, fill: "#F59E0B", stroke: "#fff", strokeWidth: 2 }}
                    activeDot={{ r: 6, fill: "#F59E0B", stroke: "#fff", strokeWidth: 2 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        {/* ── Performance par profil de risque (backtest simulé) ───────── */}
        <Card className="border-border/60">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-amber-400" />
              Performance par profil de risque
            </CardTitle>
          </CardHeader>
          <CardContent>
            {!profilsData ? (
              <div className="py-8 text-center text-sm text-muted-foreground animate-pulse">
                Calcul du backtest par profil…
              </div>
            ) : profilsData.nb_courses === 0 ? (
              <div className="py-8 text-center text-sm text-muted-foreground">
                Pas encore assez d&apos;historique pour le backtest par profil.
              </div>
            ) : (
              <>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  {profilsData.profils.map((p) => {
                    const accent =
                      p.profil === "conservateur" ? "#059669"
                      : p.profil === "equilibre" ? "#2563EB"
                      : "#D97706";
                    const tcb = p.taux_courses_beneficiaires;
                    // ROI typique = winsorisé (gros rapports plafonnés) pour ne pas
                    // afficher un chiffre gonflé par la variance (jeu responsable).
                    const roiT = p.roi_winsorise;
                    const roiPos = (roiT ?? 0) >= 0;
                    return (
                      <div key={p.profil} className="rounded-2xl border border-border/60 bg-white p-5">
                        <div className="flex items-center justify-between mb-3">
                          <span className="text-sm font-semibold" style={{ color: accent }}>{p.label}</span>
                          <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
                            {p.nb_courses} courses
                          </span>
                        </div>
                        {/* Métrique PRINCIPALE : % de courses où le profil gagne (robuste, intuitif) */}
                        <div className="text-3xl font-black tabular-nums" style={{ color: accent }}>
                          {tcb == null ? "—" : `${tcb}%`}
                        </div>
                        <div className="text-xs text-muted-foreground mt-0.5">
                          courses gagnantes (mise {profilsData.mise_par_course}€/course)
                        </div>
                        <div className="mt-4 space-y-1.5 text-xs">
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">ROI typique</span>
                            <span className="font-semibold tabular-nums" style={{ color: roiT == null ? "#9CA3AF" : roiPos ? "#059669" : "#DC2626" }}>
                              {roiT == null ? "—" : `${roiPos ? "+" : ""}${roiT}%`}
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Gain net (brut)</span>
                            <span className="font-medium tabular-nums" style={{ color: p.gain_net >= 0 ? "#059669" : "#DC2626" }}>
                              {p.gain_net >= 0 ? "+" : ""}{p.gain_net}€
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Misé total</span>
                            <span className="font-medium tabular-nums">{p.mise_totale}€</span>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
                <p className="mt-4 text-[11px] leading-relaxed text-muted-foreground/80">
                  Backtest sur les {profilsData.nb_courses} dernières courses réglables : le plan de mise de chaque profil est
                  figé <strong>avant la course</strong> (mêmes prédictions que celles servies), réglé sur l&apos;arrivée
                  officielle <strong>et les rapports PMU RÉELS</strong> (Simple Gagnant, Couplé, Trio, 2sur4). Mis à jour à
                  chaque fin de course. <strong>Courses gagnantes</strong> = part des courses où le profil finit bénéficiaire
                  (le Prudent gagne souvent peu, le Risqué rarement mais gros). Le <strong>ROI typique</strong> plafonne les
                  très gros rapports (×30) pour refléter le rendement courant ; le <strong>gain net brut</strong> les inclut,
                  d&apos;où sa forte variance. Les courses dont un pari gagnant n&apos;a pas de rapport publié sont exclues
                  (jamais estimées). <strong>Simulation — résultats passés, aucune garantie de gain futur.</strong>
                </p>
              </>
            )}
          </CardContent>
        </Card>

        {/* ── Ce que l'IA a APPRIS (poids par type, auto-amélioration) ───── */}
        {profilsData?.type_perf && Object.keys(profilsData.type_perf).length > 0 && (
          <Card className="border-border/60">
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Brain className="w-4 h-4 text-violet-400" />
                Ce que l&apos;IA a appris — pondération par type de pari
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {Object.entries(profilsData.type_perf)
                  .sort((a, b) => b[1].poids_appris - a[1].poids_appris)
                  .map(([type, p]) => {
                    const boost = p.poids_appris >= 1.0;
                    // barre : 0.5 -> 0%, 1.3 -> 100%
                    const pct = Math.max(0, Math.min(100, ((p.poids_appris - 0.5) / 0.8) * 100));
                    return (
                      <div key={type} className="flex items-center gap-3 text-xs">
                        <span className="w-32 shrink-0 font-medium truncate">{type}</span>
                        <div className="flex-1 h-2 rounded-full bg-muted/40 overflow-hidden">
                          <div className="h-full rounded-full transition-all"
                            style={{ width: `${pct}%`, background: boost ? "#059669" : "#DC2626" }} />
                        </div>
                        <span className="w-12 text-right font-mono font-bold tabular-nums"
                          style={{ color: boost ? "#059669" : "#DC2626" }}>
                          ×{p.poids_appris.toFixed(2)}
                        </span>
                        <span className="w-36 text-right text-muted-foreground tabular-nums hidden sm:block">
                          win {p.win_rate}% · ROI {p.roi_winsorise >= 0 ? "+" : ""}{p.roi_winsorise}% · {p.n} paris
                        </span>
                      </div>
                    );
                  })}
              </div>
              <p className="mt-4 text-[11px] leading-relaxed text-muted-foreground/80">
                L&apos;IA mesure le ROI RÉEL de chaque type de pari sur l&apos;historique réglé et en déduit un
                <strong> poids de conviction</strong> (×0.5 à ×1.3) appliqué à la sélection future :
                un type qui perd (ex. Simple Gagnant) est <strong>dé-pondéré</strong>, un type qui rapporte
                (placé à valeur, couplé) est <strong>privilégié</strong>. Recalculé à chaque fin de course —
                si un type se remet à gagner, son poids remonte. <strong>L&apos;algorithme s&apos;auto-corrige.</strong>
              </p>
            </CardContent>
          </Card>
        )}

        {/* ── VB performance + Discipline ───────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

          {/* VB Performance by niveau */}
          <Card className="border-border/60">
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Zap className="w-4 h-4 text-amber-400" />
                Performance des paris de valeur par niveau
              </CardTitle>
            </CardHeader>
            <CardContent>
              {data.vb_performance.every((v) => v.nb_vbs === 0) ? (
                <div className="py-6 text-center text-sm text-muted-foreground">
                  Aucun pari de valeur résolu pour le moment
                </div>
              ) : (
                <div className="overflow-x-auto">
                <table className="w-full text-sm min-w-[360px]">
                  <thead>
                    <tr className="border-b border-border/40">
                      <th className="text-left py-2 text-xs font-medium text-muted-foreground">Niveau</th>
                      <th className="text-right py-2 text-xs font-medium text-muted-foreground">Paris</th>
                      <th className="text-right py-2 text-xs font-medium text-muted-foreground">Réussite</th>
                      <th className="text-right py-2 text-xs font-medium text-muted-foreground">Rendement</th>
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
                </div>
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
                  Aucune donnée pour le moment
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
                Aucun pronostic à haute cote archivé pour le moment
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
                        <div className="text-sm font-bold text-foreground tabular-nums">
                          {p.proba_top1}% de probabilité
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

        {/* ── Derniers pronostics (favori IA vs arrivée) ─────── */}
        <Card className="border-border/60">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base flex items-center gap-2">
                <Activity className="w-4 h-4 text-brand-blue" />
                Historique des courses — favori IA
              </CardTitle>
              {g.nb_favoris_evalues > 0 && (
                <span className="text-xs text-muted-foreground">
                  Favori IA gagnant {g.favori_win_rate}% · placé {g.favori_place_rate}% sur {g.nb_favoris_evalues.toLocaleString("fr-FR")} courses
                </span>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {data.derniers_pronostics.length === 0 ? (
              <div className="py-8 text-center text-sm text-muted-foreground">
                Aucune course terminée avec pronostic archivé pour le moment
              </div>
            ) : (
              <>
              <div className="divide-y divide-border/40">
                {data.derniers_pronostics.map((p, i) => {
                  // Mise fictive 1€ Gagnant sur le favori IA.
                  const pos = p.favori_position;
                  const won = pos === 1;
                  const placed = pos != null && pos > 1 && pos <= 3;
                  const gain = won && p.cote ? p.cote : 0;      // 1€ Gagnant -> cote
                  const tier = won ? "gain" : placed ? "place" : "loss";
                  const posLabel = pos === 1 ? "1ᵉʳ" : pos != null ? `${pos}ᵉ` : "NP";
                  const posCircle =
                    won ? "bg-emerald-100 text-emerald-700"
                    : placed ? "bg-amber-100 text-amber-700"
                    : "bg-rose-100 text-rose-600";
                  return (
                    <Link
                      key={p.course_id + i}
                      href={`/courses/${p.course_id}`}
                      className="flex items-center gap-3 py-2.5 px-1 hover:bg-accent/30 transition-colors group rounded-md"
                    >
                      {/* Position */}
                      <span className={cn("flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg text-xs font-bold tabular-nums", posCircle)}>
                        {posLabel}
                      </span>
                      {/* Cheval + meta */}
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="truncate text-sm font-semibold text-foreground">N°{p.favori_numero} {p.favori_nom}</span>
                          <Badge variant="outline" className="hidden sm:inline-flex text-[10px] px-1.5 py-0 h-4 shrink-0">{p.discipline}</Badge>
                        </div>
                        <div className="mt-0.5 truncate text-xs text-muted-foreground">
                          {p.hippodrome} · {p.date}
                          {p.cote ? ` · cote ${p.cote}` : ""}
                          {!won && p.gagnant_nom && <span> · vainqueur {p.gagnant_nom}</span>}
                        </div>
                      </div>
                      {/* Résultat */}
                      <div className="flex flex-shrink-0 items-center gap-2">
                        {tier === "gain" ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-1 text-xs font-bold text-emerald-700 ring-1 ring-emerald-200">
                            <ArrowUpRight className="h-3.5 w-3.5" />+{gain.toFixed(2)}€
                          </span>
                        ) : tier === "place" ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-1 text-xs font-bold text-amber-700 ring-1 ring-amber-200">
                            <Minus className="h-3.5 w-3.5" />Placé
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 rounded-full bg-rose-50 px-2 py-1 text-xs font-bold text-rose-600 ring-1 ring-rose-200">
                            <XCircle className="h-3.5 w-3.5" />Perdu
                          </span>
                        )}
                        <ChevronRight className="h-4 w-4 text-muted-foreground/50 group-hover:text-foreground transition-colors" />
                      </div>
                    </Link>
                  );
                })}
              </div>
              <p className="mt-3 text-[10px] text-muted-foreground/70">
                Résultat = 1€ Gagnant sur le favori IA, réglé à la cote réelle.
                <span className="text-emerald-600 font-medium"> ↗ vert</span> = gain &gt; mise ·
                <span className="text-amber-600 font-medium"> Placé orange</span> = top 3 sans gain ·
                <span className="text-rose-600 font-medium"> Perdu rouge</span> = hors top 3.
              </p>
              </>
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
