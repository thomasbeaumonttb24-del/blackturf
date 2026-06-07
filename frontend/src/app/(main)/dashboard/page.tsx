"use client";

import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Area, AreaChart,
} from "recharts";
import {
  TrendingUp, TrendingDown, Zap, Calendar, Activity, Star,
  ArrowRight, ChevronRight, AlertTriangle, CheckCircle, Clock,
  BarChart3, Wallet, Trophy, Cpu,
} from "lucide-react";
import { format } from "date-fns";
import { fr } from "date-fns/locale";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useRequireAuth } from "@/hooks/useAuth";
import { bankrollApi, predictionsApi, coursesApi, statsApi } from "@/lib/api";

// ─── helpers ────────────────────────────────────────────────
const NIVEAU_LABELS: Record<number, string> = {
  1: "Intéressant", 2: "Bon", 3: "Fort", 4: "Exceptionnel",
};
const NIVEAU_COLORS: Record<number, string> = {
  1: "text-zinc-400", 2: "text-blue-400", 3: "text-amber-400", 4: "text-emerald-400",
};

function StarRating({ n }: { n: number }) {
  return (
    <span className="flex gap-0.5">
      {Array.from({ length: 4 }).map((_, i) => (
        <Star
          key={i}
          className={`w-3 h-3 ${i < n ? "fill-amber-400 text-amber-400" : "text-zinc-600"}`}
        />
      ))}
    </span>
  );
}

function DriftBadge({ severity }: { severity: string }) {
  if (severity === "critical")
    return <Badge className="bg-red-500/20 text-red-400 border-red-500/30 gap-1"><AlertTriangle className="w-3 h-3" />Dérive critique</Badge>;
  if (severity === "warning")
    return <Badge className="bg-amber-500/20 text-amber-400 border-amber-500/30 gap-1"><AlertTriangle className="w-3 h-3" />Avertissement</Badge>;
  return <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30 gap-1"><CheckCircle className="w-3 h-3" />Stable</Badge>;
}

interface Reunion {
  hippodrome_nom?: string;
  discipline?: string;
  courses?: Array<{
    course_id: string;
    nom?: string;
    heure?: string;
    nb_partants?: number;
    statut?: string;
  }>;
}

// ─── main component ─────────────────────────────────────────
export default function DashboardPage() {
  const { user } = useRequireAuth();
  const [equityHover, setEquityHover] = useState<number | null>(null);
  const [eqProfil, setEqProfil] = useState<"conservateur" | "equilibre" | "agressif">("equilibre");

  const isPaid = user && !["free", "decouverte"].includes(user.plan ?? "free");
  const isExpert = user?.plan === "expert";

  // Parallel data fetches
  const { data: bankrollStats } = useSWR(
    "bankroll-stats",
    () => bankrollApi.stats().then((r) => r.data),
    { refreshInterval: 60_000 }
  );
  const { data: summary } = useSWR(
    "dashboard-summary",
    () => statsApi.dashboardSummary().then((r) => r.data),
    { refreshInterval: 120_000 }
  );
  const { data: programme } = useSWR(
    "programme-today",
    () => coursesApi.programme().then((r) => r.data),
    { refreshInterval: 180_000 }
  );
  const { data: equity } = useSWR(
    "equity-curve",
    () => statsApi.equityCurve().then((r) => r.data)
  );
  const { data: pariDuJour } = useSWR(
    "pari-du-jour",
    () => predictionsApi.pariDuJour().then((r) => r.data),
    { refreshInterval: 120_000 }
  );

  // flatten today's courses from programme reunions
  const reunions: Reunion[] = programme?.reunions ?? [];
  const allCourses = reunions.flatMap((r: Reunion) =>
    (r.courses ?? []).map((c) => ({ ...c, hippodrome: r.hippodrome_nom, discipline: r.discipline }))
  );
  // Prochaines courses : à venir / en cours d'abord, triées par heure.
  // Si tout est terminé (soirée), on retombe sur les dernières courses.
  const upcoming = allCourses
    .filter((c) => c.statut === "a_venir" || c.statut === "en_cours")
    .sort((a, b) => (a.heure ?? "").localeCompare(b.heure ?? ""));
  const todayCourses = (upcoming.length > 0 ? upcoming : allCourses.slice(-6)).slice(0, 6);
  const aDesProchaines = upcoming.length > 0;

  const topVbs = summary?.top_vbs ?? [];
  // Source = nos plans de mise 10€ PAR PROFIL (equity.profils) ; repli sur points.
  const eqProfilsSeries: Record<string, Array<{ date: string; bankroll: number }>> | undefined = equity?.profils;
  const planBased = !!(eqProfilsSeries && Object.keys(eqProfilsSeries).length);
  const eqResume: Record<string, { mise_totale: number; gain_total: number; gain_net: number; roi: number | null; roi_typique: number | null; nb_courses: number }> | undefined = equity?.profils_resume;
  const curResume = planBased ? eqResume?.[eqProfil] : undefined;
  const equityPoints: Array<{ date: string; bankroll: number }> =
    (planBased ? eqProfilsSeries[eqProfil] : equity?.points) ?? equity?.points ?? [];
  const lastEquity = equityPoints.at(-1)?.bankroll ?? 0;
  const firstEquity = equityPoints[0]?.bankroll ?? 0;
  // P&L cumulé réel : la courbe part de 0 → dernier point = net réel.
  const equityGain = curResume ? curResume.gain_net : (equityPoints.length > 1 ? lastEquity - firstEquity : 0);

  const roi = bankrollStats?.roi_global ?? 0;
  const roiPositive = roi >= 0;

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-7xl mx-auto px-4 py-8 space-y-8">

        {/* ── Header ─────────────────────────────── */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-foreground">
              Bonjour{user?.prenom ? `, ${user.prenom}` : ""} 👋
            </h1>
            <p className="text-sm text-muted-foreground mt-0.5">
              {format(new Date(), "EEEE d MMMM yyyy", { locale: fr })}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Badge variant={user?.plan === "expert" ? "expert" : user?.plan === "pro" ? "pro" : "secondary"} className="text-xs px-3 py-1">
              {(user?.plan ?? "free").toUpperCase()}
            </Badge>
            <Button asChild variant="brand" size="sm">
              <Link href="/programme">
                <Calendar className="w-4 h-4 mr-2" />
                Programme
              </Link>
            </Button>
          </div>
        </div>

        {/* ── Pari du jour ───────────────────────── */}
        {pariDuJour && (
          <Link href={`/courses/${pariDuJour.course_id}`} className="block group">
            <Card className="border-brand-gold/40 bg-gradient-to-r from-amber-500/10 via-amber-500/5 to-transparent hover:border-brand-gold/70 transition-colors">
              <CardContent className="p-5">
                <div className="flex flex-col sm:flex-row sm:items-center gap-4">
                  <div className="flex items-center gap-2 sm:flex-col sm:items-start sm:gap-0.5 shrink-0">
                    <span className="text-[11px] font-semibold uppercase tracking-wide text-brand-gold">🎯 Pari du jour</span>
                    <span className="text-[11px] text-muted-foreground">{pariDuJour.code} · {pariDuJour.hippodrome}</span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-bold text-foreground">N°{pariDuJour.numero} {pariDuJour.nom_cheval}</span>
                      <span className="text-xs rounded-full px-2 py-0.5 bg-emerald-500/15 text-emerald-500 font-semibold">
                        EV +{(pariDuJour.ev * 100).toFixed(0)}%
                      </span>
                      {"⭐".repeat(Math.max(1, pariDuJour.niveau))}
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">{pariDuJour.raison}</p>
                  </div>
                  <div className="flex items-center gap-4 shrink-0">
                    <div className="text-right">
                      <div className="text-lg font-bold tabular-nums">{(pariDuJour.proba_top1 * 100).toFixed(0)}%</div>
                      <div className="text-[10px] text-muted-foreground">gagnant{pariDuJour.cote_pmu ? ` · cote ${pariDuJour.cote_pmu}` : ""}</div>
                    </div>
                    <ChevronRight className="w-5 h-5 text-muted-foreground group-hover:text-brand-gold transition-colors" />
                  </div>
                </div>
              </CardContent>
            </Card>
          </Link>
        )}

        {/* ── KPI cards ──────────────────────────── */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Bankroll */}
          <Card className="border-border/60 hover:border-brand-gold/40 transition-colors">
            <CardContent className="p-5">
              <div className="flex items-start justify-between mb-3">
                <div className="p-2 rounded-lg bg-amber-500/10">
                  <Wallet className="w-4 h-4 text-amber-400" />
                </div>
                <span className={`text-xs font-medium flex items-center gap-1 ${roiPositive ? "text-emerald-400" : "text-red-400"}`}>
                  {roiPositive ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                  {roi > 0 ? "+" : ""}{roi}%
                </span>
              </div>
              <div className="text-2xl font-bold text-foreground tabular-nums">
                {bankrollStats
                  ? `€${((bankrollStats.bankroll_initiale ?? 0) + (bankrollStats.gains_totaux ?? 0) - (bankrollStats.pertes_totales ?? 0)).toFixed(0)}`
                  : "—"}
              </div>
              <div className="text-xs text-muted-foreground mt-1">Capital total</div>
            </CardContent>
          </Card>

          {/* ROI */}
          <Card className="border-border/60 hover:border-brand-gold/40 transition-colors">
            <CardContent className="p-5">
              <div className="flex items-start justify-between mb-3">
                <div className="p-2 rounded-lg bg-blue-500/10">
                  <BarChart3 className="w-4 h-4 text-blue-400" />
                </div>
                <span className="text-xs text-muted-foreground">{bankrollStats?.nb_paris ?? 0} paris</span>
              </div>
              <div className={`text-2xl font-bold tabular-nums ${(bankrollStats?.roi_ia_only ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                {bankrollStats ? `${bankrollStats.roi_ia_only > 0 ? "+" : ""}${bankrollStats.roi_ia_only}%` : "—"}
              </div>
              <div className="text-xs text-muted-foreground mt-1">Rendement paris IA</div>
            </CardContent>
          </Card>

          {/* Value Bets */}
          <Card className="border-border/60 hover:border-brand-gold/40 transition-colors">
            <CardContent className="p-5">
              <div className="flex items-start justify-between mb-3">
                <div className="p-2 rounded-lg bg-emerald-500/10">
                  <Zap className="w-4 h-4 text-emerald-400" />
                </div>
                {(summary?.nb_vbs_premium ?? 0) > 0 && (
                  <Badge className="bg-amber-500/20 text-amber-400 border-0 text-xs">
                    {summary.nb_vbs_premium} ★★★+
                  </Badge>
                )}
              </div>
              <div className="text-2xl font-bold text-foreground tabular-nums">
                {summary?.nb_vbs_actifs ?? "—"}
              </div>
              <div className="text-xs text-muted-foreground mt-1">Paris de valeur actifs</div>
            </CardContent>
          </Card>

          {/* Courses du jour */}
          <Card className="border-border/60 hover:border-brand-gold/40 transition-colors">
            <CardContent className="p-5">
              <div className="flex items-start justify-between mb-3">
                <div className="p-2 rounded-lg bg-purple-500/10">
                  <Trophy className="w-4 h-4 text-purple-400" />
                </div>
                {(summary?.nb_en_cours ?? 0) > 0 && (
                  <span className="flex items-center gap-1 text-xs text-emerald-400">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                    En cours
                  </span>
                )}
              </div>
              <div className="text-2xl font-bold text-foreground tabular-nums">
                {summary?.nb_courses_jour ?? "—"}
              </div>
              <div className="text-xs text-muted-foreground mt-1">Courses aujourd&apos;hui</div>
            </CardContent>
          </Card>
        </div>

        {/* ── Main grid ──────────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">

          {/* Left col (3/5) */}
          <div className="lg:col-span-3 space-y-6">

            {/* Top Value Bets */}
            <Card className="border-border/60">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base flex items-center gap-2">
                    <Zap className="w-4 h-4 text-amber-400" />
                    Meilleurs paris de valeur du moment
                  </CardTitle>
                  <Button asChild variant="ghost" size="sm" className="text-xs text-muted-foreground hover:text-foreground">
                    <Link href="/value-bets">
                      Voir tous <ArrowRight className="w-3 h-3 ml-1" />
                    </Link>
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {!isPaid ? (
                  <div className="rounded-lg border border-dashed border-border/60 p-6 text-center">
                    <Star className="w-8 h-8 text-amber-400 mx-auto mb-2" />
                    <p className="text-sm font-medium text-foreground mb-1">Fonctionnalité Premium</p>
                    <p className="text-xs text-muted-foreground mb-3">
                      Accédez aux paris de valeur en temps réel à partir de Standard.
                    </p>
                    <Button asChild variant="brand" size="sm">
                      <Link href="/tarifs">Passer Premium</Link>
                    </Button>
                  </div>
                ) : topVbs.length === 0 ? (
                  <div className="text-center py-6 text-muted-foreground text-sm">
                    Aucun pari de valeur actif pour le moment
                  </div>
                ) : (
                  topVbs.map((vb: {
                    nom_cheval: string; hippodrome: string; discipline?: string;
                    heure?: string; ev: number; niveau: number; cote?: number; course_id: string;
                  }, i: number) => (
                    <Link
                      key={i}
                      href={`/courses/${vb.course_id}`}
                      className="flex items-center justify-between p-3 rounded-lg border border-border/40 hover:border-brand-gold/40 hover:bg-accent/30 transition-all group"
                    >
                      <div className="flex items-center gap-3">
                        <div className="text-lg font-bold text-muted-foreground w-6 text-center">
                          #{i + 1}
                        </div>
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="font-semibold text-foreground text-sm">{vb.nom_cheval}</span>
                            <StarRating n={vb.niveau} />
                          </div>
                          <div className="flex items-center gap-2 mt-0.5">
                            <span className="text-xs text-muted-foreground">{vb.hippodrome}</span>
                            {vb.heure && (
                              <span className="text-xs text-muted-foreground flex items-center gap-0.5">
                                <Clock className="w-3 h-3" />{vb.heure}
                              </span>
                            )}
                            {vb.discipline && (
                              <Badge variant="outline" className="text-xs px-1.5 py-0 h-4">{vb.discipline}</Badge>
                            )}
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        <div className="text-right">
                          <div className={`text-sm font-bold tabular-nums ${vb.ev > 0 ? "text-emerald-400" : "text-red-400"}`}>
                            Espérance {vb.ev > 0 ? "+" : ""}{(vb.ev * 100).toFixed(0)}%
                          </div>
                          {vb.cote && (
                            <div className="text-xs text-muted-foreground">Cote {vb.cote}</div>
                          )}
                        </div>
                        <ChevronRight className="w-4 h-4 text-muted-foreground group-hover:text-foreground transition-colors" />
                      </div>
                    </Link>
                  ))
                )}
              </CardContent>
            </Card>

            {/* Programme du jour */}
            <Card className="border-border/60">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base flex items-center gap-2">
                    <Calendar className="w-4 h-4 text-blue-400" />
                    {aDesProchaines ? "Prochaines courses" : "Programme du jour"}
                  </CardTitle>
                  <Button asChild variant="ghost" size="sm" className="text-xs text-muted-foreground hover:text-foreground">
                    <Link href="/programme">
                      Programme complet <ArrowRight className="w-3 h-3 ml-1" />
                    </Link>
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                {todayCourses.length === 0 ? (
                  <p className="text-sm text-muted-foreground text-center py-4">
                    Aucune donnée pour le moment
                  </p>
                ) : (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {todayCourses.map((c: {
                      course_id: string; nom?: string; heure?: string;
                      nb_partants?: number; statut?: string; est_quinte?: boolean;
                      hippodrome?: string; discipline?: string;
                    }) => (
                      <Link
                        key={c.course_id}
                        href={`/courses/${c.course_id}`}
                        className="flex items-center gap-3 p-3 rounded-lg border border-border/40 hover:border-brand-gold/40 hover:bg-accent/30 transition-all group"
                      >
                        {c.heure && (
                          <span className="flex h-9 w-12 flex-shrink-0 flex-col items-center justify-center rounded-md bg-muted/50 font-mono text-xs font-bold text-amber-500 tabular-nums">
                            {c.heure}
                          </span>
                        )}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-1.5">
                            <span className="truncate text-xs font-medium text-foreground">
                              {c.hippodrome ?? c.nom ?? "—"}
                            </span>
                            {c.est_quinte && (
                              <span className="shrink-0 rounded bg-amber-100 px-1 text-[9px] font-bold text-amber-700">Quinté+</span>
                            )}
                          </div>
                          <div className="mt-0.5 flex items-center gap-1.5">
                            {c.discipline && (
                              <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4">{c.discipline}</Badge>
                            )}
                            {c.nb_partants && (
                              <span className="text-[10px] text-muted-foreground">{c.nb_partants} partants</span>
                            )}
                          </div>
                        </div>
                        {c.statut === "en_cours" ? (
                          <span className="flex shrink-0 items-center gap-1 text-xs font-medium text-emerald-500">
                            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />En direct
                          </span>
                        ) : c.statut === "termine" ? (
                          <span className="shrink-0 text-xs text-muted-foreground">Terminée</span>
                        ) : (
                          <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground/40 group-hover:text-brand-gold transition-colors" />
                        )}
                      </Link>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Right col (2/5) */}
          <div className="lg:col-span-2 space-y-6">

            {/* Equity curve */}
            <Card className="border-border/60">
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base flex items-center gap-2">
                    <TrendingUp className="w-4 h-4 text-emerald-400" />
                    Performance IA — backtest
                  </CardTitle>
                  {equity?.is_real ? (
                    <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30 text-xs">Réel</Badge>
                  ) : (
                    <Badge variant="secondary" className="text-xs">En construction</Badge>
                  )}
                </div>
                <p className="text-[11px] text-muted-foreground mt-0.5">
                  {planBased
                    ? "P&L RÉEL — plan de mise 10€/course par profil, réglé aux vrais rapports PMU"
                    : "Simulation 10€/pari de valeur ★★★+ sur l’historique — distinct de votre capital"}
                </p>
                {/* Sélecteur de profil (chaque profil = sa propre courbe) */}
                {planBased && (
                  <div className="mt-2 inline-flex gap-1">
                    {([
                      ["conservateur", "🛡️ Prudent"],
                      ["equilibre", "⚖️ Modéré"],
                      ["agressif", "🔥 Risqué"],
                    ] as const).map(([k, lbl]) => (
                      <button key={k} onClick={() => setEqProfil(k)}
                        className={`rounded-md px-2 py-0.5 text-[10px] font-semibold border transition-colors ${
                          eqProfil === k ? "border-emerald-500 bg-emerald-500/10 text-emerald-500"
                          : "border-border text-muted-foreground hover:border-emerald-500/40"}`}>
                        {lbl}
                      </button>
                    ))}
                  </div>
                )}
                {equityPoints.length > 1 && (
                  <div className="mt-1">
                    <span className={`text-lg font-bold tabular-nums ${equityGain >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                      {equityGain >= 0 ? "+" : ""}€{equityGain.toFixed(0)}
                    </span>
                    <span className="text-xs font-normal text-muted-foreground ml-2">net réel · forte variance</span>
                    {curResume && (
                      <div className="text-[11px] text-muted-foreground mt-0.5 tabular-nums">
                        Misé <span className="font-semibold text-foreground">{curResume.mise_totale}€</span>
                        {" · "}Gagné <span className="font-semibold text-foreground">{curResume.gain_total}€</span>
                        {" · "}ROI <span className={`font-semibold ${(curResume.roi ?? 0) >= 0 ? "text-emerald-500" : "text-red-500"}`}>
                          {(curResume.roi ?? 0) >= 0 ? "+" : ""}{curResume.roi}%</span>
                        {curResume.roi_typique != null && (
                          <span className="text-muted-foreground/70"> (typique {curResume.roi_typique >= 0 ? "+" : ""}{curResume.roi_typique}%)</span>
                        )}
                        {curResume.nb_courses != null && <span className="text-muted-foreground/60"> · {curResume.nb_courses} courses</span>}
                      </div>
                    )}
                  </div>
                )}
              </CardHeader>
              <CardContent className="pt-0">
                {equityPoints.length < 2 ? (
                  <div className="h-32 flex items-center justify-center text-sm text-muted-foreground">
                    Aucune donnée pour le moment
                  </div>
                ) : (
                  <ResponsiveContainer width="100%" height={130}>
                    <AreaChart data={equityPoints} onMouseLeave={() => setEquityHover(null)}>
                      <defs>
                        <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#059669" stopOpacity={0.25} />
                          <stop offset="95%" stopColor="#059669" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <XAxis dataKey="date" hide />
                      <YAxis hide domain={["auto", "auto"]} />
                      <Tooltip
                        cursor={{ stroke: "#E5E7EB", strokeWidth: 1 }}
                        contentStyle={{ background: "#ffffff", border: "1px solid #E5E7EB", borderRadius: 12, fontSize: 12, boxShadow: "0 4px 12px rgba(0,0,0,0.06)" }}
                        formatter={(v: number) => [`${v >= 0 ? "+" : ""}€${v.toFixed(0)}`, planBased ? "P&L cumulé" : "Capital simulé"]}
                        labelFormatter={(l) => l}
                      />
                      <Area
                        type="monotone"
                        dataKey="bankroll"
                        stroke="#059669"
                        strokeWidth={2.5}
                        fill="url(#equityGrad)"
                        dot={false}
                        activeDot={{ r: 4, fill: "#059669", stroke: "#fff", strokeWidth: 2 }}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>

            {/* Model health */}
            <Card className="border-border/60">
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <Cpu className="w-4 h-4 text-blue-400" />
                  Santé du modèle IA
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {/* Drift status */}
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">Dérive statistique</span>
                  <DriftBadge severity={summary?.drift_severity ?? "none"} />
                </div>

                {/* Quick stats */}
                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-lg bg-muted/40 p-3">
                    <div className="text-xs text-muted-foreground mb-1">AUC-ROC</div>
                    <div className="text-base font-bold text-foreground tabular-nums">
                      {summary?.model_auc != null ? summary.model_auc.toFixed(3) : "—"}
                    </div>
                  </div>
                  <div className="rounded-lg bg-muted/40 p-3">
                    <div className="text-xs text-muted-foreground mb-1">
                      Précision Top-3{summary?.nb_courses_evaluees ? ` (${summary.nb_courses_evaluees} courses)` : ""}
                    </div>
                    <div className="text-base font-bold text-foreground tabular-nums">
                      {summary?.precision_top3 != null ? `${Math.round(summary.precision_top3 * 100)}%` : "—"}
                    </div>
                  </div>
                </div>

                {isExpert && (
                  <Button asChild variant="outline" size="sm" className="w-full text-xs">
                    <Link href="/admin/algorithme">
                      <Activity className="w-3 h-3 mr-2" />
                      Monitoring détaillé
                    </Link>
                  </Button>
                )}
              </CardContent>
            </Card>

            {/* Quick links */}
            <Card className="border-border/60">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm text-muted-foreground font-medium">Accès rapide</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {[
                  { href: "/bankroll", label: "Suivi du capital", icon: Wallet },
                  { href: "/strategies", label: "Mes stratégies", icon: BarChart3 },
                  { href: "/assistant", label: "Assistant IA", icon: Cpu },
                ].map(({ href, label, icon: Icon }) => (
                  <Link
                    key={href}
                    href={href}
                    className="flex items-center justify-between p-2.5 rounded-lg hover:bg-accent/40 transition-colors group"
                  >
                    <div className="flex items-center gap-2.5 text-sm text-foreground">
                      <Icon className="w-4 h-4 text-muted-foreground group-hover:text-foreground transition-colors" />
                      {label}
                    </div>
                    <ChevronRight className="w-4 h-4 text-muted-foreground" />
                  </Link>
                ))}
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}
