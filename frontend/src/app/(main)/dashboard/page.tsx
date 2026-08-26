"use client";

import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
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
  1: "text-zinc-600", 2: "text-blue-700", 3: "text-amber-700", 4: "text-emerald-700",
};

function StarRating({ n }: { n: number }) {
  return (
    <span className="flex gap-0.5">
      {Array.from({ length: 4 }).map((_, i) => (
        <Star
          key={i}
          className={`w-3 h-3 ${i < n ? "fill-amber-500 text-amber-700" : "text-zinc-600"}`}
        />
      ))}
    </span>
  );
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

  const isPaid = user && !["free", "decouverte"].includes(user.plan ?? "free");

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
  const { data: pariDuJour } = useSWR(
    "pari-du-jour",
    () => predictionsApi.pariDuJour().then((r) => r.data),
    { refreshInterval: 120_000 }
  );
  const { data: parisProfils } = useSWR(
    "pari-du-jour-profils",
    () => predictionsApi.pariDuJourProfils().then((r) => r.data),
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

  const roi = bankrollStats?.roi_global ?? 0;
  const roiPositive = roi >= 0;

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-7xl mx-auto px-4 py-6 sm:py-8 space-y-6 sm:space-y-8">

        {/* ── Header ─────────────────────────────── */}
        <div className="flex flex-row items-center justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-xl sm:text-2xl font-bold text-foreground truncate">
              Bonjour{user?.prenom ? `, ${user.prenom}` : ""} 👋
            </h1>
            <p className="text-sm text-muted-foreground mt-0.5">
              {format(new Date(), "EEEE d MMMM", { locale: fr })}
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Badge variant={user?.plan === "expert" ? "expert" : "secondary"} className="text-xs px-3 py-1">
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
              <CardContent className="p-4 sm:p-5">
                <div className="flex flex-col sm:flex-row sm:items-center gap-3 sm:gap-4">
                  <div className="flex items-center gap-2 sm:flex-col sm:items-start sm:gap-0.5 shrink-0">
                    <span className="text-[11px] font-semibold uppercase tracking-wide text-brand-gold-dark">🎯 Pari du jour</span>
                    <span className="text-[11px] text-muted-foreground">{pariDuJour.code} · {pariDuJour.hippodrome}</span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-bold text-foreground">N°{pariDuJour.numero} {pariDuJour.nom_cheval}</span>
                      <span className="text-xs rounded-full px-2 py-0.5 bg-emerald-500/15 text-emerald-700 font-semibold">
                        EV +{((pariDuJour.ev ?? 0) * 100).toFixed(0)}%
                      </span>
                      {pariDuJour.edge_valide && (
                        <span
                          className="text-xs rounded-full px-2 py-0.5 bg-amber-50 text-amber-700 font-semibold ring-1 ring-amber-200"
                          title="Signaux historiquement gagnants confirmés — edge validé hors-échantillon (taux de gain 3-4× le marché sur le passé). Pas une garantie."
                        >
                          ✓ Edge validé
                        </span>
                      )}
                      {"⭐".repeat(Math.max(1, pariDuJour.niveau))}
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">{pariDuJour.raison}</p>
                  </div>
                  <div className="flex items-center gap-4 shrink-0">
                    <div className="text-right">
                      <div className="text-lg font-bold tabular-nums">{((pariDuJour.proba_top1 ?? 0) * 100).toFixed(0)}%</div>
                      <div className="text-[10px] text-muted-foreground">gagnant{pariDuJour.cote_pmu ? ` · cote ${pariDuJour.cote_pmu}` : ""}</div>
                    </div>
                    <ChevronRight className="w-5 h-5 text-muted-foreground group-hover:text-brand-gold-dark transition-colors" />
                  </div>
                </div>
              </CardContent>
            </Card>
          </Link>
        )}

        {/* ── Le pari du jour PAR PROFIL ──────────── */}
        {parisProfils?.profils?.length > 0 && (
          <div>
            <div className="flex items-center gap-2 mb-2 px-0.5">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-brand-gold-dark">Le pari du jour, par profil</span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {parisProfils.profils.map((p: {
                profil: string; profil_label: string; course_id: string; code: string; hippodrome: string;
                type_pari: string; chevaux: Array<{ numero: number; nom: string }>; mise: number;
                probabilite: number; ev: number; raisons: string[];
              }) => {
                const col = p.profil === "conservateur" ? "border-emerald-300 bg-emerald-50/40"
                  : p.profil === "equilibre" ? "border-blue-300 bg-blue-50/40" : "border-rose-300 bg-rose-50/40";
                return (
                  <Link key={p.profil} href={`/courses/${p.course_id}`}
                    className={`block rounded-xl border p-3 hover:shadow-md transition-shadow ${col}`}>
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold uppercase tracking-wide">{p.profil_label}</span>
                      <span className="text-[10px] text-muted-foreground">{p.code}</span>
                    </div>
                    <div className="mt-1.5 text-sm font-semibold">{p.type_pari}</div>
                    <div className="text-xs text-muted-foreground">{(p.chevaux ?? []).map((c) => `N°${c.numero}`).join(" + ")}</div>
                    <div className="mt-1.5 flex items-baseline gap-2">
                      <span className="text-lg font-bold tabular-nums">{Math.round((p.probabilite ?? 0) * 100)}%</span>
                      <span className="text-[10px] text-muted-foreground">de toucher</span>
                      {p.ev > 0 && <span className="text-[10px] font-bold text-emerald-700">EV +{Math.round(p.ev * 100)}%</span>}
                    </div>
                    {p.raisons?.[0] && <p className="mt-1 text-[10px] text-muted-foreground leading-snug line-clamp-2">{p.raisons[0]}</p>}
                    <div className="mt-1 text-[10px] text-muted-foreground truncate">{p.hippodrome}</div>
                  </Link>
                );
              })}
            </div>
          </div>
        )}

        {/* ── KPI cards ──────────────────────────── */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
          {/* Bankroll */}
          <Card className="border-border/60 hover:border-brand-gold/40 transition-colors">
            <CardContent className="p-4 sm:p-5">
              <div className="flex items-start justify-between mb-3">
                <div className="p-2 rounded-lg bg-amber-50">
                  <Wallet className="w-4 h-4 text-amber-700" />
                </div>
                <span className={`text-xs font-medium flex items-center gap-1 ${roiPositive ? "text-emerald-700" : "text-red-700"}`}>
                  {roiPositive ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                  {roi > 0 ? "+" : ""}{roi}%
                </span>
              </div>
              <div className="text-xl sm:text-2xl font-bold text-foreground tabular-nums">
                {bankrollStats
                  ? `€${((bankrollStats.bankroll_initiale ?? 0) + (bankrollStats.gains_totaux ?? 0) - (bankrollStats.pertes_totales ?? 0)).toFixed(0)}`
                  : "—"}
              </div>
              <div className="text-xs text-muted-foreground mt-1">Capital total</div>
            </CardContent>
          </Card>

          {/* ROI */}
          <Card className="border-border/60 hover:border-brand-gold/40 transition-colors">
            <CardContent className="p-4 sm:p-5">
              <div className="flex items-start justify-between mb-3">
                <div className="p-2 rounded-lg bg-blue-50">
                  <BarChart3 className="w-4 h-4 text-blue-700" />
                </div>
                <span className="text-xs text-muted-foreground">{bankrollStats?.nb_paris ?? 0} paris</span>
              </div>
              <div className={`text-xl sm:text-2xl font-bold tabular-nums ${(bankrollStats?.roi_ia_only ?? 0) >= 0 ? "text-emerald-700" : "text-red-700"}`}>
                {bankrollStats ? `${bankrollStats.roi_ia_only > 0 ? "+" : ""}${bankrollStats.roi_ia_only}%` : "—"}
              </div>
              <div className="text-xs text-muted-foreground mt-1">Rendement algo</div>
            </CardContent>
          </Card>

          {/* Value Bets */}
          <Card className="border-border/60 hover:border-brand-gold/40 transition-colors">
            <CardContent className="p-4 sm:p-5">
              <div className="flex items-start justify-between mb-3">
                <div className="p-2 rounded-lg bg-emerald-50">
                  <Zap className="w-4 h-4 text-emerald-700" />
                </div>
                {(summary?.nb_vbs_premium ?? 0) > 0 && (
                  <Badge className="bg-amber-50 text-amber-700 border-0 text-xs">
                    {summary.nb_vbs_premium} ★★★+
                  </Badge>
                )}
              </div>
              <div className="text-xl sm:text-2xl font-bold text-foreground tabular-nums">
                {summary?.nb_vbs_actifs ?? "—"}
              </div>
              <div className="text-xs text-muted-foreground mt-1">Paris de valeur</div>
            </CardContent>
          </Card>

          {/* Courses du jour */}
          <Card className="border-border/60 hover:border-brand-gold/40 transition-colors">
            <CardContent className="p-4 sm:p-5">
              <div className="flex items-start justify-between mb-3">
                <div className="p-2 rounded-lg bg-purple-50">
                  <Trophy className="w-4 h-4 text-purple-700" />
                </div>
                {(summary?.nb_en_cours ?? 0) > 0 && (
                  <span className="flex items-center gap-1 text-xs text-emerald-700">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                    En cours
                  </span>
                )}
              </div>
              <div className="text-xl sm:text-2xl font-bold text-foreground tabular-nums">
                {summary?.nb_courses_jour ?? "—"}
              </div>
              <div className="text-xs text-muted-foreground mt-1">Courses aujourd&apos;hui</div>
            </CardContent>
          </Card>
        </div>

        {/* ── Main grid ──────────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-4 sm:gap-6">

          {/* Left col (3/5) */}
          <div className="lg:col-span-3 space-y-4 sm:space-y-6">

            {/* Top Value Bets */}
            <Card className="border-border/60">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base flex items-center gap-2">
                    <Zap className="w-4 h-4 text-amber-700" />
                    Meilleurs paris de valeur
                  </CardTitle>
                  <Button asChild variant="ghost" size="sm" className="text-xs text-muted-foreground hover:text-foreground shrink-0">
                    <Link href="/value-bets">
                      Voir tous <ArrowRight className="w-3 h-3 ml-1" />
                    </Link>
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {!isPaid ? (
                  <div className="rounded-lg border border-dashed border-border/60 p-6 text-center">
                    <Star className="w-8 h-8 text-amber-700 mx-auto mb-2" />
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
                      className="flex items-center justify-between gap-2 p-3 rounded-lg border border-border/40 hover:border-brand-gold/40 hover:bg-accent/30 transition-all group"
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="text-lg font-bold text-muted-foreground w-6 text-center shrink-0">
                          #{i + 1}
                        </div>
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="font-semibold text-foreground text-sm truncate">{vb.nom_cheval}</span>
                            <StarRating n={vb.niveau} />
                          </div>
                          <div className="flex items-center gap-2 mt-0.5 flex-wrap">
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
                      <div className="flex items-center gap-2 shrink-0">
                        <div className="text-right">
                          <div className={`text-sm font-bold tabular-nums ${vb.ev > 0 ? "text-emerald-700" : "text-red-700"}`}>
                            {vb.ev > 0 ? "+" : ""}{(vb.ev * 100).toFixed(0)}%
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
                    <Calendar className="w-4 h-4 text-blue-700" />
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
                          <span className="flex h-9 w-12 flex-shrink-0 flex-col items-center justify-center rounded-md bg-muted/50 font-mono text-xs font-bold text-amber-700 tabular-nums">
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
                          <span className="flex shrink-0 items-center gap-1 text-xs font-medium text-emerald-700">
                            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />En direct
                          </span>
                        ) : c.statut === "termine" ? (
                          <span className="shrink-0 text-xs text-muted-foreground">Terminée</span>
                        ) : (
                          <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground group-hover:text-brand-gold-dark transition-colors" />
                        )}
                      </Link>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Right col (2/5) */}
          <div className="lg:col-span-2 space-y-4 sm:space-y-6">

            {/* Quick links */}
            <Card className="border-border/60">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm text-muted-foreground font-medium">Accès rapide</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {[
                  { href: "/bankroll", label: "Suivi du capital", icon: Wallet },
                  { href: "/strategies", label: "Mes stratégies", icon: BarChart3 },
                  { href: "/assistant", label: "Assistant algorithme", icon: Cpu },
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
