"use client";

import useSWR from "swr";
import Link from "next/link";
import {
  TrendingUp, Trophy, CheckCircle2, XCircle, ArrowUpRight, Minus,
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
    brier_moyen: number | null;
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

interface WinningBet {
  profil: string;
  course_id: string;
  code: string | null;
  hippodrome: string;
  date: string | null;
  type_pari: string;
  chevaux: number[];
  mise: number;
  gain: number;
  benefice: number;
  rapport: number | null;
}

const PROFIL_LABELS: Record<string, { label: string; cls: string }> = {
  conservateur: { label: "Prudent", cls: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
  equilibre: { label: "Modéré", cls: "bg-blue-50 text-blue-700 ring-blue-200" },
  agressif: { label: "Risqué", cls: "bg-rose-50 text-rose-700 ring-rose-200" },
};

const VERDICTS: Record<string, { emoji: string; label: string; cls: string }> = {
  gagnant: { emoji: "🎯", label: "Gagnant", cls: "border-emerald-300 bg-emerald-50 text-emerald-700" },
  place: { emoji: "✅", label: "Placé", cls: "border-amber-300 bg-amber-50 text-amber-700" },
  top3: { emoji: "➕", label: "Pronostic top-3", cls: "border-blue-300 bg-blue-50 text-blue-700" },
  manque: { emoji: "❌", label: "Manqué", cls: "border-rose-300 bg-rose-50 text-rose-700" },
};

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

  // Paris RÉELLEMENT gagnés par l'algorithme, par profil (pronos émis réglés)
  const { data: gagnantsData } = useSWR<{
    gagnants: WinningBet[]; n: number; n_courses?: number; total_gain?: number; total_benefice?: number;
    profils?: Array<{ profil: string; label: string; nb_courses: number; gain_net: number; roi: number | null; paris_gagnes: number; taux_courses_beneficiaires: number | null }>;
    updated_at?: string;
  }>(
    "palmares-gagnants",
    () => statsApi.palmaresGagnants().then((r) => r.data),
    { refreshInterval: 60_000, revalidateOnFocus: true },
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
              L&apos;algorithme BlackTurf prouve ses résultats
            </h1>
            <p className="text-lg text-muted-foreground mb-8">
              Chaque pronostic est archivé et vérifiable — résultats réels, par profil de jeu.
            </p>

            {/* Hero stats */}
            <div className="flex flex-wrap justify-center gap-6 sm:gap-10">
              <div className="text-center">
                <div className="text-4xl font-black text-amber-400 tabular-nums">
                  {g.accuracy_top3}%
                </div>
                <div className="text-xs text-muted-foreground mt-1">Fiabilité Top-3</div>
              </div>
              <div className="text-center">
                <div className="text-4xl font-black text-foreground tabular-nums">
                  {g.nb_courses_analysees.toLocaleString("fr-FR")}
                </div>
                <div className="text-xs text-muted-foreground mt-1">Courses analysées</div>
              </div>
              <div className="text-center">
                <div className="text-4xl font-black text-emerald-400 tabular-nums">
                  {g.favori_place_rate}%
                </div>
                <div className="text-xs text-muted-foreground mt-1">Favori placé (top-3)</div>
              </div>
            </div>
            <p className="mt-3 text-[11px] text-muted-foreground/60 max-w-xl mx-auto">
              Les gains ci-dessous proviennent des paris RÉELLEMENT générés par l&apos;algorithme
              (par profil), réglés aux rapports PMU officiels sur toutes les courses analysées.
              Performances passées — aucune garantie de gain futur.
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
                Closing Line Value — l&apos;algorithme anticipe le marché
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
                Sur {data.clv.n} courses, la cote du favori <strong>baisse {data.clv.pct_beat_line}% du temps</strong> entre
                l&apos;ouverture et le départ : le marché bouge <strong>vers</strong> le pronostic de l&apos;algorithme. C&apos;est la
                métrique de référence des pros — battre la ligne de clôture prouve un avantage réel, indépendamment de la chance
                sur un résultat isolé. Calculé sur les cotes PMU réelles (ouverture vs clôture).
              </p>
            </CardContent>
          </Card>
        )}

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

        {/* ── Paris GAGNÉS par l'algorithme (réels, par profil) ───────────── */}
        <Card className="border-emerald-500/30">
          <CardHeader className="pb-3">
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <CardTitle className="text-base flex items-center gap-2">
                <Trophy className="w-4 h-4 text-emerald-500" />
                Paris gagnés générés par l&apos;algorithme
              </CardTitle>
              {gagnantsData && gagnantsData.total_benefice != null && (
                <div className="text-right">
                  <div className={cn("text-2xl font-black tabular-nums leading-none", gagnantsData.total_benefice >= 0 ? "text-emerald-500" : "text-rose-500")}>
                    {gagnantsData.total_benefice >= 0 ? "+" : ""}{gagnantsData.total_benefice.toFixed(2)}€
                  </div>
                  <div className="text-[10px] text-muted-foreground mt-0.5">
                    bénéfice net · {gagnantsData.n} paris gagnés sur {gagnantsData.n_courses ?? 0} courses
                  </div>
                </div>
              )}
            </div>
            <p className="text-[11px] text-muted-foreground mt-1">
              Chaque ligne = un pari réellement émis avant la course par un profil, réglé au
              rapport PMU officiel. Toutes les courses analysées. Mis à jour à chaque arrivée. Aucune donnée inventée.
            </p>
          </CardHeader>
          <CardContent>
            {/* Résumé par profil — vrai nombre de courses + gain net réel */}
            {gagnantsData?.profils && gagnantsData.profils.length > 0 && (
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-5">
                {gagnantsData.profils.map((p) => {
                  const pm = PROFIL_LABELS[p.profil] ?? { label: p.label, cls: "bg-muted text-muted-foreground ring-border" };
                  return (
                    <div key={p.profil} className="rounded-xl border border-border/60 bg-muted/20 p-3">
                      <span className={cn("inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1", pm.cls)}>{pm.label}</span>
                      <div className={cn("mt-2 text-2xl font-black tabular-nums leading-none", p.gain_net >= 0 ? "text-emerald-500" : "text-rose-500")}>
                        {p.gain_net >= 0 ? "+" : ""}{p.gain_net.toFixed(0)}€
                      </div>
                      <div className="text-[11px] text-muted-foreground mt-1">
                        gain net · ROI {p.roi != null ? `${p.roi >= 0 ? "+" : ""}${p.roi}%` : "—"}
                      </div>
                      <div className="text-[10px] text-muted-foreground/70 mt-1.5">
                        {p.nb_courses} courses · {p.paris_gagnes} paris gagnés
                        {p.taux_courses_beneficiaires != null ? ` · ${p.taux_courses_beneficiaires}% bénéf.` : ""}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
            {!gagnantsData ? (
              <div className="py-8 text-center text-sm text-muted-foreground animate-pulse">Chargement…</div>
            ) : gagnantsData.gagnants.length === 0 ? (
              <div className="py-8 text-center text-sm text-muted-foreground">
                Les paris gagnants apparaîtront ici dès les prochaines arrivées (l&apos;historique se
                construit course après course, en temps réel).
              </div>
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm min-w-[560px]">
                    <thead>
                      <tr className="border-b border-border/40 text-[11px] uppercase tracking-wide text-muted-foreground">
                        <th className="text-left py-2 font-medium">Profil</th>
                        <th className="text-left py-2 font-medium">Course</th>
                        <th className="text-left py-2 font-medium">Pari</th>
                        <th className="text-right py-2 font-medium">Mise</th>
                        <th className="text-right py-2 font-medium">Gain</th>
                        <th className="text-right py-2 font-medium">Bénéfice</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border/30">
                      {gagnantsData.gagnants.map((b, i) => {
                        const pm = PROFIL_LABELS[b.profil] ?? { label: b.profil, cls: "bg-muted text-muted-foreground ring-border" };
                        return (
                          <tr key={i} className="hover:bg-accent/20 transition-colors">
                            <td className="py-2.5">
                              <span className={cn("inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1", pm.cls)}>{pm.label}</span>
                            </td>
                            <td className="py-2.5">
                              <Link href={`/courses/${b.course_id}`} className="font-medium hover:text-brand-gold transition-colors">
                                {b.code ?? "—"}
                              </Link>
                              <span className="block text-[10px] text-muted-foreground truncate max-w-[140px]">{b.hippodrome}</span>
                            </td>
                            <td className="py-2.5">
                              <span className="font-medium">{b.type_pari}</span>
                              <span className="block text-[10px] text-muted-foreground">{b.chevaux.map((n) => `N°${n}`).join(" + ")}</span>
                            </td>
                            <td className="py-2.5 text-right font-mono tabular-nums text-muted-foreground">{b.mise.toFixed(0)}€</td>
                            <td className="py-2.5 text-right font-mono tabular-nums font-semibold">{b.gain.toFixed(2)}€</td>
                            <td className="py-2.5 text-right font-mono tabular-nums font-bold text-emerald-600">
                              +{b.benefice.toFixed(2)}€{b.rapport ? <span className="block text-[10px] font-normal text-muted-foreground">×{b.rapport.toFixed(1)}</span> : null}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <p className="mt-3 text-[11px] text-muted-foreground/70">
                  {gagnantsData.n} pari{gagnantsData.n > 1 ? "s" : ""} gagnant{gagnantsData.n > 1 ? "s" : ""} au total ·
                  mise de référence 10€/course · réglé aux rapports PMU réels.
                </p>
              </>
            )}
          </CardContent>
        </Card>

        {/* ── Précision par discipline (donnée simple, lisible) ───────────── */}
        <div className="grid grid-cols-1 gap-6">

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

        {/* Détails techniques (Brier, calibration, apprentissage) déplacés dans
            l'espace admin — le palmarès public reste sur des résultats simples. */}
        <p className="text-center text-[11px] text-muted-foreground/60">
          Résultats réels, recalculés à chaque fin de course. Aucune donnée simulée hors des
          backtests explicitement étiquetés.
        </p>
      </div>
    </div>
  );
}
