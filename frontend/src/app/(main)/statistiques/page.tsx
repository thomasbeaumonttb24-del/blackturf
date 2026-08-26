"use client";

import useSWR from "swr";
import Link from "next/link";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  Cell, CartesianGrid,
} from "recharts";
import {
  TrendingUp, TrendingDown, Wallet, Target, Trophy,
  BarChart3, ChevronRight, Flame, Zap, Brain,
  CheckCircle2, XCircle, Minus,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useRequireAuth } from "@/hooks/useAuth";
import { statsApi } from "@/lib/api";
import { cn } from "@/lib/utils";

// ─── Types ───────────────────────────────────────────────────
interface PerfData {
  nb_paris: number;
  mise_totale: number;
  win_rate: number;
  cote_moyenne: number;
  roi: number;
  gain_net: number;
  roi_par_discipline: Array<{ discipline: string; nb_paris: number; roi: number; win_rate: number }>;
  monthly_pnl: Array<{ mois: string; gain_perte: number; nb_paris: number }>;
  best_bets: BetRow[];
  worst_bets: BetRow[];
  suivi_ia: {
    pct_suivi: number;
    nb_ia: number;
    nb_non_ia: number;
    roi_ia: number;
    roi_non_ia: number;
    win_rate_ia: number;
    win_rate_non_ia: number;
  };
  streak: { type: "win" | "loss" | "none"; count: number };
}

interface BetRow {
  entry_id: string;
  date: string | null;
  type_pari: string;
  chevaux: string | null;
  mise: number;
  cote: number | null;
  resultat: string | null;
  gain_perte: number | null;
  course_id: string | null;
}

// ─── Sub-components ──────────────────────────────────────────
function KpiCard({
  label, value, sub, positive, icon: Icon, iconBg,
}: {
  label: string; value: string; sub?: string;
  positive?: boolean;
  icon: React.ElementType; iconBg: string;
}) {
  return (
    <Card className="border-border/60 hover:border-brand-gold/40 transition-colors">
      <CardContent className="p-4 sm:p-5">
        <div className="flex items-start justify-between mb-3">
          <div className={cn("p-2 rounded-lg", iconBg)}>
            <Icon className="w-4 h-4" />
          </div>
          {positive !== undefined && (
            <span className={cn("flex items-center gap-1 text-xs font-medium",
              positive ? "text-emerald-700" : "text-red-700"
            )}>
              {positive ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
            </span>
          )}
        </div>
        <div className={cn("text-xl sm:text-2xl font-bold tabular-nums",
          positive === true ? "text-emerald-700" : positive === false ? "text-red-700" : "text-foreground"
        )}>
          {value}
        </div>
        <div className="text-xs text-muted-foreground mt-1">{label}</div>
        {sub && <div className="text-[11px] text-muted-foreground mt-0.5">{sub}</div>}
      </CardContent>
    </Card>
  );
}

function ResultBadge({ r }: { r: string | null }) {
  if (r === "gagne") return (
    <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700 bg-emerald-50 border border-emerald-100 px-2 py-0.5 rounded-full">
      <CheckCircle2 className="w-3 h-3" />Gagné
    </span>
  );
  if (r === "perd") return (
    <span className="inline-flex items-center gap-1 text-xs font-medium text-red-700 bg-red-50 border border-red-100 px-2 py-0.5 rounded-full">
      <XCircle className="w-3 h-3" />Perdu
    </span>
  );
  return (
    <span className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground bg-muted px-2 py-0.5 rounded-full">
      <Minus className="w-3 h-3" />—
    </span>
  );
}

function BetTable({ bets, title, color }: { bets: BetRow[]; title: string; color: "green" | "red" }) {
  if (bets.length === 0) return null;
  return (
    <div>
      <h3 className={cn("text-sm font-semibold mb-3",
        color === "green" ? "text-emerald-700" : "text-red-700"
      )}>{title}</h3>
      <div className="space-y-2">
        {bets.map((b) => (
          <div key={b.entry_id}
            className="flex items-center justify-between p-3 rounded-lg border border-border/40 bg-card/50 text-sm"
          >
            <div className="flex-1 min-w-0">
              <div className="font-medium text-foreground truncate">
                {b.chevaux || b.type_pari}
              </div>
              <div className="flex items-center gap-2 mt-0.5">
                <ResultBadge r={b.resultat} />
                {b.cote && (
                  <span className="text-xs text-muted-foreground">Cote {b.cote}</span>
                )}
                <span className="text-xs text-muted-foreground">Mise {b.mise}€</span>
              </div>
            </div>
            <div className={cn("font-bold tabular-nums shrink-0 ml-4",
              (b.gain_perte ?? 0) >= 0 ? "text-emerald-700" : "text-red-700"
            )}>
              {(b.gain_perte ?? 0) >= 0 ? "+" : ""}{(b.gain_perte ?? 0).toFixed(2)}€
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Custom tooltip for monthly P&L ──────────────────────────
function PnlTooltip({ active, payload, label }: {
  active?: boolean; payload?: Array<{ value: number }>; label?: string;
}) {
  if (!active || !payload?.length) return null;
  const val = payload[0].value;
  return (
    <div className="rounded-xl bg-white ring-1 ring-border px-3 py-2 text-xs shadow-md">
      <div className="font-medium text-foreground mb-1">{label}</div>
      <div className={cn("font-bold tabular-nums", val >= 0 ? "text-emerald-700" : "text-red-700")}>
        {val >= 0 ? "+" : ""}{val.toFixed(2)}€
      </div>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────
export default function StatistiquesPage() {
  useRequireAuth();

  const { data, isLoading, error } = useSWR<PerfData>(
    "perf-personnelle",
    () => statsApi.perfPersonnelle().then((r) => r.data),
    { refreshInterval: 120_000, shouldRetryOnError: false }
  );

  if (isLoading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="text-muted-foreground text-sm animate-pulse">Chargement des statistiques…</div>
      </div>
    );
  }

  // État d'erreur/vide explicite : sans ça, une erreur API (ex. 404 utilisateur sans
  // paris) laissait `data` undefined → spinner infini.
  if (error || !data) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center px-4">
        <div className="text-center space-y-2">
          <p className="text-foreground font-semibold">Statistiques indisponibles</p>
          <p className="text-muted-foreground text-sm">
            Aucune donnée à afficher pour le moment. Place des paris pour suivre tes performances.
          </p>
        </div>
      </div>
    );
  }

  const roiPositive = data.roi >= 0;
  const gainPositive = data.gain_net >= 0;

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-7xl mx-auto px-4 py-6 sm:py-8 space-y-6 sm:space-y-8">

        {/* ── Header ────────────────────────────── */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 sm:gap-4">
          <div>
            <h1 className="text-xl sm:text-2xl font-bold text-foreground flex items-center gap-2">
              <BarChart3 className="w-5 h-5 sm:w-6 sm:h-6 text-amber-700" />
              Mes Statistiques
            </h1>
            <p className="text-sm text-muted-foreground mt-0.5">
              {data.nb_paris} paris
            </p>
          </div>
          {data.streak.type !== "none" && data.streak.count > 1 && (
            <Badge className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 text-sm",
              data.streak.type === "win"
                ? "bg-emerald-50 text-emerald-700 border-emerald-500/30"
                : "bg-red-50 text-red-700 border-red-500/30"
            )}>
              <Flame className="w-4 h-4" />
              Série de {data.streak.count} {data.streak.type === "win" ? "victoires" : "défaites"}
            </Badge>
          )}
        </div>

        {/* ── KPIs ──────────────────────────────── */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
          <KpiCard
            label="Total misé"
            value={`${data.mise_totale.toFixed(0)}€`}
            sub={`${data.nb_paris} paris`}
            icon={Wallet}
            iconBg="bg-amber-50"
          />
          <KpiCard
            label="Rendement global"
            value={`${roiPositive ? "+" : ""}${data.roi}%`}
            positive={roiPositive}
            icon={BarChart3}
            iconBg="bg-blue-50"
          />
          <KpiCard
            label="Taux de réussite"
            value={`${data.win_rate}%`}
            sub={`Cote moy. ${data.cote_moyenne}`}
            positive={data.win_rate >= 20}
            icon={Target}
            iconBg="bg-purple-50"
          />
          <KpiCard
            label="Gain net"
            value={`${gainPositive ? "+" : ""}${data.gain_net.toFixed(2)}€`}
            positive={gainPositive}
            icon={Trophy}
            iconBg="bg-emerald-50"
          />
        </div>

        {/* ── Charts ────────────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 sm:gap-6">

          {/* Monthly P&L */}
          <Card className="lg:col-span-2 border-border/60">
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <TrendingUp className="w-4 h-4 text-amber-700" />
                Gains et pertes / mois
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={data.monthly_pnl} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#EEF1F6" vertical={false} />
                  <XAxis
                    dataKey="mois"
                    tick={{ fontSize: 10, fill: "#4B5563" }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fontSize: 10, fill: "#4B5563" }}
                    axisLine={false}
                    tickLine={false}
                    tickFormatter={(v) => `${v}€`}
                  />
                  <Tooltip content={<PnlTooltip />} cursor={{ fill: "#F59E0B", fillOpacity: 0.06 }} />
                  <Bar dataKey="gain_perte" radius={[6, 6, 0, 0]} maxBarSize={36}>
                    {data.monthly_pnl.map((entry, i) => (
                      <Cell
                        key={i}
                        fill={entry.gain_perte >= 0 ? "#059669" : "#EF4444"}
                        opacity={0.9}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          {/* ROI par discipline */}
          <Card className="border-border/60">
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <BarChart3 className="w-4 h-4 text-blue-700" />
                Rendement par discipline
              </CardTitle>
            </CardHeader>
            <CardContent>
              {data.roi_par_discipline.length === 0 ? (
                <div className="h-32 flex items-center justify-center text-sm text-muted-foreground">
                  Aucune donnée pour le moment
                </div>
              ) : (
                <div className="space-y-3">
                  {data.roi_par_discipline.map((d) => {
                    const isPos = d.roi >= 0;
                    const barW = Math.min(Math.abs(d.roi) / 30 * 100, 100);
                    return (
                      <div key={d.discipline}>
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-xs text-foreground font-medium">{d.discipline}</span>
                          <span className={cn("text-xs font-bold tabular-nums",
                            isPos ? "text-emerald-700" : "text-red-700"
                          )}>
                            {isPos ? "+" : ""}{d.roi}%
                          </span>
                        </div>
                        <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                          <div
                            className={cn("h-full rounded-full transition-all",
                              isPos ? "bg-emerald-500" : "bg-red-500"
                            )}
                            style={{ width: `${barW}%` }}
                          />
                        </div>
                        <div className="text-[10px] text-muted-foreground mt-0.5">
                          {d.nb_paris} paris · {d.win_rate}% de réussite
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* ── Best / Worst bets ─────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-6">
          <Card className="border-border/60">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Meilleurs paris</CardTitle>
            </CardHeader>
            <CardContent>
              {data.best_bets.length === 0 ? (
                <p className="text-sm text-muted-foreground">Aucun pari gagné pour l&apos;instant</p>
              ) : (
                <BetTable bets={data.best_bets} title="" color="green" />
              )}
            </CardContent>
          </Card>

          <Card className="border-border/60">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Pires paris</CardTitle>
            </CardHeader>
            <CardContent>
              {data.worst_bets.length === 0 ? (
                <p className="text-sm text-muted-foreground">Aucun pari perdu pour l&apos;instant</p>
              ) : (
                <BetTable bets={data.worst_bets} title="" color="red" />
              )}
            </CardContent>
          </Card>
        </div>

        {/* ── Suivi IA ──────────────────────────── */}
        <Card className="border-border/60">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Brain className="w-4 h-4 text-blue-700" />
              Suivi des recommandations IA
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-6">

              {/* % suivi */}
              <div className="flex flex-col items-center justify-center p-4 rounded-xl bg-muted/40 text-center">
                <div className="text-3xl font-bold text-foreground mb-1">
                  {data.suivi_ia.pct_suivi}%
                </div>
                <div className="text-xs text-muted-foreground">des recommandations suivies</div>
                <div className="text-[11px] text-muted-foreground mt-1">
                  {data.suivi_ia.nb_ia} IA · {data.suivi_ia.nb_non_ia} libres
                </div>
              </div>

              {/* Paris IA */}
              <div className="p-4 rounded-xl bg-blue-50 border border-blue-500/20">
                <div className="flex items-center gap-1.5 mb-2">
                  <Zap className="w-4 h-4 text-blue-700" />
                  <span className="text-sm font-semibold text-foreground">Avec IA</span>
                </div>
                <div className={cn("text-xl font-bold tabular-nums",
                  data.suivi_ia.roi_ia >= 0 ? "text-emerald-700" : "text-red-700"
                )}>
                  Rendement {data.suivi_ia.roi_ia >= 0 ? "+" : ""}{data.suivi_ia.roi_ia}%
                </div>
                <div className="text-xs text-muted-foreground mt-1">
                  {data.suivi_ia.win_rate_ia}% de réussite
                </div>
              </div>

              {/* Paris libres */}
              <div className="p-4 rounded-xl bg-muted/40 border border-border/40">
                <div className="flex items-center gap-1.5 mb-2">
                  <Target className="w-4 h-4 text-muted-foreground" />
                  <span className="text-sm font-semibold text-foreground">Sans IA</span>
                </div>
                <div className={cn("text-xl font-bold tabular-nums",
                  data.suivi_ia.roi_non_ia >= 0 ? "text-emerald-700" : "text-red-700"
                )}>
                  Rendement {data.suivi_ia.roi_non_ia >= 0 ? "+" : ""}{data.suivi_ia.roi_non_ia}%
                </div>
                <div className="text-xs text-muted-foreground mt-1">
                  {data.suivi_ia.win_rate_non_ia}% de réussite
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* ── Quick links ───────────────────────── */}
        <div className="flex gap-3 flex-wrap">
          <Link
            href="/bankroll"
            className="flex items-center gap-2 px-4 py-2 rounded-lg border border-border/60 text-sm text-muted-foreground hover:text-foreground hover:border-brand-gold/40 transition-all"
          >
            <Wallet className="w-4 h-4" />
            Gérer mon capital
            <ChevronRight className="w-3 h-3" />
          </Link>
          <Link
            href="/track-record"
            className="flex items-center gap-2 px-4 py-2 rounded-lg border border-border/60 text-sm text-muted-foreground hover:text-foreground hover:border-brand-gold/40 transition-all"
          >
            <TrendingUp className="w-4 h-4" />
            Palmarès de l&apos;IA
            <ChevronRight className="w-3 h-3" />
          </Link>
        </div>
      </div>
    </div>
  );
}
