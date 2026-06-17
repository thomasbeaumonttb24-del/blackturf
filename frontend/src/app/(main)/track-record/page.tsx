"use client";

import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import {
  Trophy, Star, Receipt, Coins, Sparkles, ArrowRight, ShieldCheck,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { HeroStats } from "@/components/home/HeroStats";
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

// ─── Compteur animé (count-up) — déclenché quand l'élément entre à l'écran ───
function useCountUp(target: number, duration = 1400) {
  const [val, setVal] = useState(0);
  const ref = useRef<HTMLSpanElement>(null);
  const started = useRef(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const run = () => {
      if (started.current) return;
      started.current = true;
      if (typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        setVal(target);
        return;
      }
      const t0 = performance.now();
      const tick = (now: number) => {
        const p = Math.min((now - t0) / duration, 1);
        const eased = 1 - Math.pow(1 - p, 3); // easeOutCubic
        setVal(target * eased);
        if (p < 1) requestAnimationFrame(tick);
        else setVal(target);
      };
      requestAnimationFrame(tick);
    };
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => e.isIntersecting && run()),
      { threshold: 0.3 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [target, duration]);
  return { val, ref };
}

function CountUpEuro({ value, className, decimals = 0, prefix = "" }: { value: number; className?: string; decimals?: number; prefix?: string }) {
  const { val, ref } = useCountUp(value);
  return (
    <span ref={ref} className={className}>
      {prefix}{val.toLocaleString("fr-FR", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}€
    </span>
  );
}

// ─── Table de paris gagnés (réutilisée : 50 derniers + 30 meilleurs) ───
function BetsTable({ bets, ranked = false }: { bets: WinningBet[]; ranked?: boolean }) {
  return (
    <>
      {/* Mobile : liste de cartes empilées (pas de scroll horizontal) */}
      <div className="sm:hidden divide-y divide-border/30">
        {bets.map((b, i) => {
          const pm = PROFIL_LABELS[b.profil] ?? { label: b.profil, cls: "bg-muted text-muted-foreground ring-border" };
          return (
            <div key={i} className={cn("py-3 flex items-start gap-3", ranked && i < 3 && "bg-brand-gold/[0.04] -mx-3 px-3 rounded-lg")}>
              {ranked && <span className="font-black text-muted-foreground tabular-nums text-sm pt-0.5 w-5 shrink-0">{i + 1}</span>}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <Link href={`/courses/${b.course_id}`} className="font-semibold text-sm hover:text-brand-gold transition-colors">{b.code ?? "—"}</Link>
                  <span className="text-[11px] text-muted-foreground tabular-nums">
                    {b.date ? new Date(b.date).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit", year: "2-digit" }) : "—"}
                  </span>
                  <span className={cn("ml-auto inline-flex rounded-full px-1.5 py-0.5 text-[9px] font-semibold ring-1 shrink-0", pm.cls)}>{pm.label}</span>
                </div>
                <div className="text-[11px] text-muted-foreground mt-0.5">{b.type_pari}</div>
              </div>
              <div className="text-right shrink-0">
                <span className="inline-flex items-center rounded-full px-2 py-0.5 text-[9px] font-semibold bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200">Gagné</span>
                <div className="text-sm font-bold text-emerald-600 tabular-nums mt-0.5">+{b.benefice.toFixed(2)}€</div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Desktop : tableau complet */}
      <div className="hidden sm:block overflow-x-auto">
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
    </>
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

      {/* ── Hero — image plein cadre + dynamisme ──────────────────────── */}
      <div className="relative overflow-hidden border-b border-border/40 min-h-[60vh] sm:min-h-[70vh] flex items-center">
        {/* Image de course plein cadre + Ken Burns */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/img/showcase.jpg"
          alt="Peloton de chevaux en pleine course"
          className="absolute inset-0 h-full w-full object-cover object-[60%_center] ken-burns"
        />
        {/* Dégradés lisibilité (foncé bas + gauche) */}
        <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/55 to-black/35" />
        <div className="absolute inset-0 bg-gradient-to-r from-black/60 via-transparent to-transparent" />

        <div className="relative max-w-7xl mx-auto w-full px-4 py-16 sm:py-28">
          <div className="text-center max-w-2xl mx-auto">
            <h1 className="text-2xl sm:text-5xl font-extrabold text-white mb-3 sm:mb-4 leading-[1.1] [text-shadow:0_2px_24px_rgba(0,0,0,0.5)]">
              L&apos;algorithme BlackTurf{" "}
              <span className="text-gradient-animated">prouve ses gains</span>
            </h1>
            <p className="text-sm sm:text-lg text-white/80 mb-6 sm:mb-9 max-w-xl mx-auto">
              Chaque pronostic archivé, réglé aux rapports PMU officiels.
            </p>

            {/* Hero stats — cartes verre + count-up (live, mêmes chiffres que l'accueil) */}
            <HeroStats
              fallback={{
                accuracy_top3: g.accuracy_top3,
                favori_place_rate: g.favori_place_rate,
                courses_analysees: g.nb_courses_analysees,
              }}
            />

            <div className="mt-6 sm:mt-9 flex flex-col sm:flex-row justify-center gap-3">
              <Button asChild variant="brand" size="lg" className="press btn-shimmer shadow-lg shadow-amber-500/30">
                <Link href="/inscription">Essayer gratuitement <ArrowRight className="h-4 w-4 ml-1" /></Link>
              </Button>
              <Button asChild variant="outline" size="lg" className="press bg-white/10 backdrop-blur-sm border-white/25 text-white hover:bg-white/20 hover:text-white">
                <Link href="/tarifs">Voir les offres</Link>
              </Button>
            </div>
            {data.updated_at && (
              <p className="mt-5 text-[11px] text-white/55">
                Dernière mise à jour : {new Date(data.updated_at).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })} · recalculé à chaque fin de course
              </p>
            )}
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-3 sm:px-4 py-6 sm:py-10 space-y-6 sm:space-y-10">

        {/* ── TOTAL DES GAINS générés par l'algorithme, par profil ───────────── */}
        <Card className="relative overflow-hidden border-emerald-500/30 bg-gradient-to-br from-emerald-50/70 via-background to-amber-50/40">
          {/* Voile décoratif (cheval) en filigrane */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/img/duel.jpg"
            alt=""
            aria-hidden
            className="pointer-events-none absolute -right-10 -top-10 w-72 h-72 object-cover rounded-full opacity-[0.07] blur-[1px] ken-burns"
          />
          <CardHeader className="p-4 sm:p-6 pb-3 sm:pb-3 relative">
            <CardTitle className="text-sm sm:text-base flex items-center gap-2">
              <Coins className="w-4 h-4 text-emerald-500" />
              Total des gains générés par l&apos;algorithme
            </CardTitle>
            <p className="text-[11px] text-muted-foreground mt-1 max-w-2xl">
              Gains réels encaissés, réglés aux rapports PMU, par profil.
            </p>
          </CardHeader>
          <CardContent className="p-4 sm:p-6 pt-0 relative">
            {gagnantsError ? (
              <div className="py-8 text-center text-sm text-muted-foreground">Indisponible pour le moment.</div>
            ) : !gagnantsData ? (
              <div className="py-8 text-center text-sm text-muted-foreground animate-pulse">Chargement…</div>
            ) : (
              <>
                {/* Grand total encaissé (count-up) */}
                <div className="rounded-2xl border border-emerald-500/30 bg-white/70 backdrop-blur-sm p-4 sm:p-6 mb-5 sm:mb-6 text-center sm:text-left">
                  <div className="flex flex-col sm:flex-row items-center sm:items-end justify-between gap-4">
                    <div>
                      <div className="text-[11px] uppercase tracking-wider text-emerald-700/80 flex items-center gap-1.5 justify-center sm:justify-start">
                        <Sparkles className="w-3.5 h-3.5" /> Total encaissé par les pronostics
                      </div>
                      <CountUpEuro
                        value={gagnantsData.total_gain ?? 0}
                        prefix="+"
                        className="block text-4xl sm:text-6xl font-black tabular-nums leading-none mt-2 text-emerald-600 [text-shadow:0_2px_18px_rgba(16,185,129,0.18)]"
                      />
                    </div>
                    <div className="text-center">
                      <div className="text-2xl font-black tabular-nums text-foreground">{gagnantsData.n.toLocaleString("fr-FR")}</div>
                      <div className="text-[10px] uppercase tracking-wider text-muted-foreground mt-0.5">Paris gagnés</div>
                    </div>
                  </div>
                </div>

                {/* Graphe : gains encaissés par profil */}
                {gagnantsData.profils && gagnantsData.profils.length > 0 && (() => {
                  const PROFIL_BAR: Record<string, { from: string; to: string; dot: string }> = {
                    conservateur: { from: "from-emerald-400", to: "to-emerald-600", dot: "bg-emerald-500" },
                    equilibre: { from: "from-blue-400", to: "to-blue-600", dot: "bg-blue-500" },
                    agressif: { from: "from-rose-400", to: "to-rose-600", dot: "bg-rose-500" },
                  };
                  const maxGain = Math.max(1, ...gagnantsData.profils!.map((p) => p.gain_total ?? 0));
                  return (
                    <>
                      {/* Barres horizontales animées */}
                      <div className="space-y-5">
                        {gagnantsData.profils!.map((p) => {
                          const pm = PROFIL_LABELS[p.profil] ?? { label: p.label, cls: "bg-muted text-muted-foreground ring-border" };
                          const bar = PROFIL_BAR[p.profil] ?? { from: "from-amber-400", to: "to-amber-600", dot: "bg-amber-500" };
                          const gain = p.gain_total ?? 0;
                          const pct = Math.round((gain / maxGain) * 100);
                          return (
                            <div key={p.profil}>
                              <div className="flex items-center justify-between mb-1.5">
                                <span className="flex items-center gap-2 text-sm font-medium">
                                  <span className={cn("inline-block h-2.5 w-2.5 rounded-full", bar.dot)} />
                                  {pm.label}
                                  <span className="text-[11px] text-muted-foreground font-normal">· {p.paris_gagnes} paris gagnés</span>
                                </span>
                                <CountUpEuro value={gain} prefix="+" className="text-sm font-black tabular-nums text-emerald-600" />
                              </div>
                              <div className="h-3.5 rounded-full bg-muted/70 overflow-hidden ring-1 ring-border/40">
                                <div
                                  className={cn("h-full rounded-full bg-gradient-to-r bar-grow", bar.from, bar.to)}
                                  style={{ ["--bar-pct" as string]: `${pct}%` }}
                                />
                              </div>
                            </div>
                          );
                        })}
                      </div>

                      {/* Cartes récap par profil */}
                      <div className="mt-6 sm:mt-7 grid grid-cols-1 sm:grid-cols-3 gap-3">
                        {gagnantsData.profils!.map((p) => {
                          const pm = PROFIL_LABELS[p.profil] ?? { label: p.label, cls: "bg-muted text-muted-foreground ring-border" };
                          return (
                            <div key={p.profil} className="rounded-xl border border-border/60 bg-white/80 backdrop-blur-sm p-3 sm:p-4 tilt-card">
                              <div className="flex items-center justify-between">
                                <span className={cn("inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1", pm.cls)}>{pm.label}</span>
                                <span className="text-[10px] uppercase tracking-wider text-muted-foreground">{p.nb_courses} courses</span>
                              </div>
                              <CountUpEuro
                                value={p.gain_total ?? 0}
                                prefix="+"
                                className="block mt-3 text-2xl font-black tabular-nums leading-none text-emerald-600"
                              />
                              <div className="text-[11px] text-muted-foreground mt-0.5">de gains encaissés</div>
                              <div className="mt-3 flex items-center justify-between text-[11px]">
                                <span className="text-muted-foreground">Paris gagnés</span>
                                <span className="font-semibold tabular-nums">{p.paris_gagnes}</span>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </>
                  );
                })()}

                <p className="mt-5 flex items-center gap-1.5 text-[11px] text-muted-foreground/70">
                  <ShieldCheck className="w-3.5 h-3.5 text-emerald-500 flex-shrink-0" />
                  Gains réels, figés avant le départ et réglés aux rapports PMU officiels. Performances passées — aucune garantie de gain futur.
                </p>
              </>
            )}
          </CardContent>
        </Card>

        {/* ── 50 derniers paris gagnés (tous profils) ───────────────────────── */}
        <Card className="border-border/60">
          <CardHeader className="p-4 sm:p-6 pb-3 sm:pb-3">
            <CardTitle className="text-sm sm:text-base flex items-center gap-2">
              <Receipt className="w-4 h-4 text-emerald-500" />
              Les 50 derniers paris gagnés
            </CardTitle>
            <p className="text-[11px] text-muted-foreground mt-1">
              Tous profils, les plus récents — figés avant le départ, réglés au rapport PMU réel.
            </p>
          </CardHeader>
          <CardContent className="p-4 sm:p-6 pt-0">
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
            <CardHeader className="p-4 sm:p-6 pb-3 sm:pb-3">
              <CardTitle className="text-sm sm:text-base flex items-center gap-2">
                <Star className="w-4 h-4 text-brand-gold fill-brand-gold" />
                Les 30 plus gros gains
              </CardTitle>
              <p className="text-[11px] text-muted-foreground mt-1">
                Les 30 plus gros bénéfices nets — réglés aux rapports PMU.
              </p>
            </CardHeader>
            <CardContent className="p-4 sm:p-6 pt-0">
              <BetsTable bets={gagnantsData.top_gains} ranked />
            </CardContent>
          </Card>
        )}

        {/* ── Précision par discipline (donnée simple, lisible) ───────────── */}
        <div className="grid grid-cols-1 gap-6">

          {/* By discipline */}
          <Card className="border-border/60">
            <CardHeader className="p-4 sm:p-6 pb-3 sm:pb-3">
              <CardTitle className="text-sm sm:text-base flex items-center gap-2">
                <Trophy className="w-4 h-4 text-purple-600" />
                Précision par discipline
              </CardTitle>
            </CardHeader>
            <CardContent className="p-4 sm:p-6 pt-0">
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
