"use client";

import useSWR from "swr";
import Link from "next/link";
import {
  TrendingUp, Trophy, CheckCircle2, XCircle, ArrowUpRight, Minus,
  ChevronRight, Star, Activity, Receipt,
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
  fige_avant_course?: boolean;   // prono figé avant le départ (preuve d'intégrité)
  fige_le?: string | null;       // horodatage du gel pré-course
  regle_le?: string | null;      // horodatage du règlement post-arrivée
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

// ─── Table de paris gagnés (réutilisée : 50 derniers + 30 meilleurs) ───
function BetsTable({ bets, ranked = false }: { bets: WinningBet[]; ranked?: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm min-w-[760px]">
        <thead>
          <tr className="border-b border-border/40 text-[11px] uppercase tracking-wide text-muted-foreground">
            {ranked && <th className="text-left py-2 font-medium w-8">#</th>}
            <th className="text-left py-2 font-medium">Date</th>
            <th className="text-left py-2 font-medium">Course</th>
            <th className="text-right py-2 font-medium">Cote</th>
            <th className="text-right py-2 font-medium">Mise</th>
            <th className="text-right py-2 font-medium">Gain</th>
            <th className="text-left py-2 font-medium pl-3">Profil</th>
            <th className="text-left py-2 font-medium">Type</th>
            <th className="text-right py-2 font-medium">Résultat</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/30">
          {bets.map((b, i) => {
            const pm = PROFIL_LABELS[b.profil] ?? { label: b.profil, cls: "bg-muted text-muted-foreground ring-border" };
            return (
              <tr key={i} className={cn("hover:bg-accent/20 transition-colors", ranked && i < 3 && "bg-brand-gold/[0.04]")}>
                {ranked && <td className="py-2.5 font-black text-muted-foreground tabular-nums">{i + 1}</td>}
                <td className="py-2.5 text-xs text-muted-foreground tabular-nums whitespace-nowrap">
                  {b.date ? new Date(b.date).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit", year: "2-digit" }) : "—"}
                </td>
                <td className="py-2.5">
                  <Link href={`/courses/${b.course_id}`} className="font-medium hover:text-brand-gold transition-colors">{b.code ?? "—"}</Link>
                  <span className="block text-[10px] text-muted-foreground truncate max-w-[130px]">{b.hippodrome}</span>
                </td>
                <td className="py-2.5 text-right font-mono tabular-nums">{b.rapport ? `×${b.rapport.toFixed(1)}` : "—"}</td>
                <td className="py-2.5 text-right font-mono tabular-nums text-muted-foreground">{b.mise.toFixed(0)}€</td>
                <td className="py-2.5 text-right font-mono tabular-nums font-semibold">{b.gain.toFixed(2)}€</td>
                <td className="py-2.5 pl-3">
                  <span className={cn("inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1", pm.cls)}>{pm.label}</span>
                </td>
                <td className="py-2.5">
                  <span className="font-medium">{b.type_pari}</span>
                  <span className="block text-[10px] text-muted-foreground">{b.chevaux.map((n) => `N°${n}`).join(" + ")}</span>
                </td>
                <td className="py-2.5 text-right whitespace-nowrap">
                  <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200">Gagné</span>
                  <span className="block text-[11px] font-bold text-emerald-600 tabular-nums mt-0.5">+{b.benefice.toFixed(2)}€</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────
export default function TrackRecordPage() {
  const { data, isLoading, error } = useSWR<TrackRecord>(
    "track-record",
    () => statsApi.trackRecord().then((r) => r.data),
    { refreshInterval: 60_000, revalidateOnFocus: true, shouldRetryOnError: false }  // recalcul ~ à chaque fin de course
  );

  // Paris RÉELLEMENT gagnés par l'algorithme, par profil (pronos émis réglés)
  const { data: gagnantsData, error: gagnantsError } = useSWR<{
    gagnants: WinningBet[]; top_gains?: WinningBet[]; n: number; n_courses?: number; total_gain?: number; total_benefice?: number;
    profils?: Array<{ profil: string; label: string; nb_courses: number; mise_totale?: number; gain_total?: number; gain_net: number; roi: number | null; paris_gagnes: number; taux_courses_beneficiaires: number | null }>;
    updated_at?: string;
  }>(
    "palmares-gagnants",
    () => statsApi.palmaresGagnants().then((r) => r.data),
    { refreshInterval: 60_000, revalidateOnFocus: true, shouldRetryOnError: false },
  );

  if (isLoading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="text-muted-foreground text-sm animate-pulse">Chargement du palmarès…</div>
      </div>
    );
  }

  // Erreur API → message clair au lieu d'un spinner infini.
  if (error || !data) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center px-4">
        <div className="text-center space-y-2">
          <p className="text-foreground font-semibold">Palmarès indisponible</p>
          <p className="text-muted-foreground text-sm">Réessaie dans un instant.</p>
        </div>
      </div>
    );
  }

  const g = data.global;

  return (
    <div className="min-h-screen bg-background">

      {/* ── Hero ──────────────────────────────────────────── */}
      <div className="relative overflow-hidden border-b border-border/40 bg-gradient-to-br from-background via-background to-amber-50">
        <div className="max-w-7xl mx-auto px-4 py-14 sm:py-20">
          <div className="text-center max-w-2xl mx-auto">
            <Badge className="mb-4 inline-flex items-center gap-1.5 bg-emerald-500/15 text-emerald-600 border-emerald-500/30 px-3 py-1">
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500 opacity-75" />
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
                <div className="text-4xl font-black text-amber-600 tabular-nums">
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
                <div className="text-4xl font-black text-emerald-600 tabular-nums">
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

        {/* ── BILAN RÉEL : l'algo joue les 3 profils sur chaque course ───────── */}
        <Card className="border-emerald-500/30">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Trophy className="w-4 h-4 text-emerald-500" />
              Bilan réel — 10€ par profil sur chaque course
            </CardTitle>
            <p className="text-[11px] text-muted-foreground mt-1">
              Sur chaque course analysée, l&apos;algorithme joue le pronostic <strong>figé avant le départ</strong> des
              3 profils de risque (10€ chacun, soit 30€/course), réglé aux <strong>vrais rapports PMU</strong> à l&apos;arrivée.
              Cumul réel ci-dessous — aucune donnée inventée.
            </p>
          </CardHeader>
          <CardContent>
            {gagnantsError ? (
              <div className="py-8 text-center text-sm text-muted-foreground">Indisponible pour le moment.</div>
            ) : !gagnantsData ? (
              <div className="py-8 text-center text-sm text-muted-foreground animate-pulse">Chargement…</div>
            ) : (
              <>
                {(() => {
                  const tg = gagnantsData.total_gain ?? 0;
                  const tb = gagnantsData.total_benefice ?? 0;
                  const tm = Math.round((tg - tb) * 100) / 100;   // misé = gagné − bénéfice
                  return (
                    <div className="rounded-2xl border border-emerald-500/30 bg-emerald-50/40 p-5 mb-5">
                      <div className="flex flex-wrap items-end justify-between gap-4">
                        <div>
                          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Bénéfice net total</div>
                          <div className={cn("text-4xl font-black tabular-nums leading-none mt-1", tb >= 0 ? "text-emerald-600" : "text-rose-500")}>
                            {tb >= 0 ? "+" : ""}{tb.toFixed(2)}€
                          </div>
                        </div>
                        <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
                          <div><div className="text-muted-foreground text-xs">Total misé</div><div className="font-bold tabular-nums">{tm.toFixed(0)}€</div></div>
                          <div><div className="text-muted-foreground text-xs">Total gagné</div><div className="font-bold tabular-nums text-emerald-600">{tg.toFixed(0)}€</div></div>
                          <div><div className="text-muted-foreground text-xs">Paris gagnés</div><div className="font-bold tabular-nums">{gagnantsData.n}</div></div>
                          <div><div className="text-muted-foreground text-xs">Courses</div><div className="font-bold tabular-nums">{gagnantsData.n_courses ?? 0}</div></div>
                        </div>
                      </div>
                    </div>
                  );
                })()}
                {gagnantsData.profils && gagnantsData.profils.length > 0 && (
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    {gagnantsData.profils.map((p) => {
                      const pm = PROFIL_LABELS[p.profil] ?? { label: p.label, cls: "bg-muted text-muted-foreground ring-border" };
                      return (
                        <div key={p.profil} className="rounded-xl border border-border/60 bg-white p-4">
                          <div className="flex items-center justify-between">
                            <span className={cn("inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1", pm.cls)}>{pm.label}</span>
                            <span className="text-[10px] uppercase tracking-wider text-muted-foreground">{p.nb_courses} courses</span>
                          </div>
                          <div className={cn("mt-3 text-2xl font-black tabular-nums leading-none", p.gain_net >= 0 ? "text-emerald-600" : "text-rose-500")}>
                            {p.gain_net >= 0 ? "+" : ""}{p.gain_net.toFixed(0)}€
                          </div>
                          <div className="text-[11px] text-muted-foreground mt-0.5">bénéfice net · ROI {p.roi != null ? `${p.roi >= 0 ? "+" : ""}${p.roi}%` : "—"}</div>
                          <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
                            <span className="text-muted-foreground">Misé</span><span className="text-right font-medium tabular-nums">{(p.mise_totale ?? 0).toFixed(0)}€</span>
                            <span className="text-muted-foreground">Gagné</span><span className="text-right font-medium tabular-nums text-emerald-600">{(p.gain_total ?? 0).toFixed(0)}€</span>
                            <span className="text-muted-foreground">Paris gagnés</span><span className="text-right font-medium tabular-nums">{p.paris_gagnes}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </>
            )}
          </CardContent>
        </Card>

        {/* ── 50 derniers paris gagnés (tous profils) ───────────────────────── */}
        <Card className="border-border/60">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Receipt className="w-4 h-4 text-emerald-500" />
              Les 50 derniers paris gagnés
            </CardTitle>
            <p className="text-[11px] text-muted-foreground mt-1">
              Tous profils confondus, les plus récents. Chaque pari a été <strong>figé avant le départ</strong> et réglé
              au <strong>rapport PMU réel</strong> à l&apos;arrivée.
            </p>
          </CardHeader>
          <CardContent>
            {!gagnantsData ? (
              <div className="py-8 text-center text-sm text-muted-foreground animate-pulse">Chargement…</div>
            ) : gagnantsData.gagnants.length === 0 ? (
              <div className="py-8 text-center text-sm text-muted-foreground">
                Les paris gagnants apparaîtront ici dès les prochaines arrivées (l&apos;historique se construit en temps réel).
              </div>
            ) : (
              <>
                <BetsTable bets={gagnantsData.gagnants.slice(0, 50)} />
                <p className="mt-3 text-[11px] text-muted-foreground/70">
                  {gagnantsData.n} pari{gagnantsData.n > 1 ? "s" : ""} gagnant{gagnantsData.n > 1 ? "s" : ""} au total ·
                  les 50 plus récents affichés · mise de référence 10€/course.
                </p>
              </>
            )}
          </CardContent>
        </Card>

        {/* ── 30 meilleurs gains ────────────────────────────────────────────── */}
        {gagnantsData?.top_gains && gagnantsData.top_gains.length > 0 && (
          <Card className="border-brand-gold/30">
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Star className="w-4 h-4 text-brand-gold fill-brand-gold" />
                Les 30 plus gros gains
              </CardTitle>
              <p className="text-[11px] text-muted-foreground mt-1">
                Les 30 paris au plus gros bénéfice net — réels, figés avant le départ, réglés aux rapports PMU.
              </p>
            </CardHeader>
            <CardContent>
              <BetsTable bets={gagnantsData.top_gains} ranked />
            </CardContent>
          </Card>
        )}

        {/* ── Précision par discipline (donnée simple, lisible) ───────────── */}
        <div className="grid grid-cols-1 gap-6">

          {/* By discipline */}
          <Card className="border-border/60">
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Trophy className="w-4 h-4 text-purple-600" />
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
                          d.accuracy_top3 >= 50 ? "text-emerald-600" :
                          d.accuracy_top3 >= 35 ? "text-amber-600" : "text-muted-foreground"
                        )}>
                          {d.accuracy_top3}%
                        </span>
                      </div>
                      <div className="h-2 rounded-full bg-muted overflow-hidden">
                        <div
                          className="h-full rounded-full bg-amber-500 transition-all"
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
