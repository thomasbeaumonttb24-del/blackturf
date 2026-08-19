"use client";

import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import {
  Trophy, Star, Receipt, Coins, ArrowRight, ShieldCheck, BadgeCheck,
  Clock3, Database, ExternalLink, LockKeyhole, BarChart3, RefreshCw,
  CheckCircle2, CalendarDays, Target, Crown, ChevronDown,
} from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { statsApi } from "@/lib/api";
import { EchantillonNotice } from "@/components/stats/EchantillonNotice";
import { cn } from "@/lib/utils";

// ─── Types ───────────────────────────────────────────────────
interface TrackRecord {
  global: {
    accuracy_top1: number;
    accuracy_top3: number;
    brier_moyen: number;
    nb_courses_analysees: number;
    // Date de la plus ancienne course mesurée (ISO) — le read-model ne retient que
    // la cohorte rejouable, donc les taux ne portent que sur cette période.
    mesure_depuis?: string | null;
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

function SectionHeading({ eyebrow, title, description, icon: Icon }: {
  eyebrow: string;
  title: string;
  description: string;
  icon: typeof Trophy;
}) {
  return (
    <div className="flex items-start gap-3 sm:gap-4">
      <span className="mt-0.5 inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-amber-200 bg-amber-50 text-amber-800">
        <Icon className="h-5 w-5" aria-hidden="true" />
      </span>
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-amber-800">{eyebrow}</p>
        <h2 className="mt-1 font-display text-xl font-bold tracking-tight text-foreground sm:text-2xl">{title}</h2>
        <p className="mt-1.5 max-w-2xl text-sm leading-6 text-muted-foreground">{description}</p>
      </div>
    </div>
  );
}

// ─── Table de paris gagnés (réutilisée : 50 derniers + 30 meilleurs) ───
function BetsTable({ bets, ranked = false }: { bets: WinningBet[]; ranked?: boolean }) {
  return (
    <>
      {/* Mobile : liste de cartes empilées (pas de scroll horizontal) */}
      <div className="space-y-3 sm:hidden">
        {bets.map((b, i) => {
          const pm = PROFIL_LABELS[b.profil] ?? { label: b.profil, cls: "bg-muted text-muted-foreground ring-border" };
          return (
            <article key={i} className={cn("rounded-2xl border border-border/70 bg-white p-4 shadow-[0_8px_24px_-24px_rgba(17,24,39,.55)]", ranked && i < 3 && "border-amber-300 bg-amber-50/40")}>
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-2.5">
                  {ranked && <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-amber-100 text-xs font-black tabular-nums text-amber-900">{i + 1}</span>}
                  <div>
                    <Link href={`/courses/${b.course_id}`} className="inline-flex min-h-11 items-center gap-1 font-semibold text-foreground underline-offset-4 transition-colors hover:text-amber-800 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500">
                      {b.code ?? "Course"}<ExternalLink className="h-3 w-3" aria-hidden="true" />
                    </Link>
                    <p className="-mt-2 text-xs text-muted-foreground">{b.hippodrome}</p>
                  </div>
                </div>
                <div className="text-right">
                  <p className="text-base font-bold tabular-nums text-emerald-700">+{b.benefice.toFixed(2)}€</p>
                  <p className="text-[11px] text-muted-foreground">gain net</p>
                </div>
              </div>
              <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 border-t border-border/60 pt-3 text-xs">
                <div><span className="block text-muted-foreground">Pari</span><span className="mt-0.5 block font-medium">{b.type_pari} · {b.chevaux.map((n) => `N°${n}`).join(" + ")}</span></div>
                <div className="text-right"><span className="block text-muted-foreground">Mise / rapport</span><span className="mt-0.5 block font-medium tabular-nums">{b.mise.toFixed(0)}€{b.rapport ? ` · ×${b.rapport.toFixed(1)}` : ""}</span></div>
                <div className="flex items-center gap-1.5 text-muted-foreground"><CalendarDays className="h-3.5 w-3.5" aria-hidden="true" />{b.date ? new Date(b.date).toLocaleDateString("fr-FR") : "Date indisponible"}</div>
                <div className="flex justify-end"><span className={cn("inline-flex items-center rounded-full px-2 py-1 text-[10px] font-semibold ring-1", pm.cls)}>{pm.label}</span></div>
              </div>
              {b.fige_avant_course && <p className="mt-3 flex items-center gap-1.5 text-[10px] font-medium text-emerald-700"><LockKeyhole className="h-3 w-3" aria-hidden="true" /> Pronostic figé avant le départ</p>}
            </article>
          );
        })}
      </div>

      {/* Desktop : tableau complet */}
      <div className="hidden sm:block overflow-x-auto">
      <table className="w-full min-w-[820px] text-sm">
        <caption className="sr-only">Liste des paris gagnants réglés aux rapports PMU officiels</caption>
        <thead>
          <tr className="border-b border-border bg-stone-50 text-[11px] uppercase tracking-[0.1em] text-muted-foreground">
            {ranked && <th scope="col" className="w-10 rounded-l-xl px-3 py-3 text-left font-semibold">#</th>}
            <th scope="col" className={cn("px-3 py-3 text-left font-semibold", !ranked && "rounded-l-xl")}>Date</th>
            <th scope="col" className="px-3 py-3 text-left font-semibold">Course</th>
            <th scope="col" className="px-3 py-3 text-left font-semibold">Pari</th>
            <th scope="col" className="px-3 py-3 text-right font-semibold">Mise</th>
            <th scope="col" className="px-3 py-3 text-right font-semibold">Rapport</th>
            <th scope="col" className="px-3 py-3 text-left font-semibold">Profil</th>
            <th scope="col" className="rounded-r-xl px-3 py-3 text-right font-semibold">Gain net</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/30">
          {bets.map((b, i) => {
            const pm = PROFIL_LABELS[b.profil] ?? { label: b.profil, cls: "bg-muted text-muted-foreground ring-border" };
            return (
              <tr key={i} className={cn("transition-colors hover:bg-stone-50/80", ranked && i < 3 && "bg-amber-50/45")}>
                {ranked && <td className="px-3 py-4 font-black text-amber-900 tabular-nums">{i + 1}</td>}
                <td className="whitespace-nowrap px-3 py-4 text-xs text-muted-foreground tabular-nums">
                  {b.date ? new Date(b.date).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit", year: "2-digit" }) : "—"}
                </td>
                <td className="px-3 py-4">
                  <Link href={`/courses/${b.course_id}`} className="inline-flex items-center gap-1 font-semibold underline-offset-4 transition-colors hover:text-amber-800 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500">{b.code ?? "—"}<ExternalLink className="h-3 w-3" aria-hidden="true" /></Link>
                  <span className="block max-w-[150px] truncate text-[11px] text-muted-foreground">{b.hippodrome}</span>
                </td>
                <td className="px-3 py-4"><span className="font-medium">{b.type_pari}</span><span className="block text-[11px] text-muted-foreground">{b.chevaux.map((n) => `N°${n}`).join(" + ")}</span></td>
                <td className="px-3 py-4 text-right font-mono tabular-nums text-muted-foreground">{b.mise.toFixed(0)}€</td>
                <td className="px-3 py-4 text-right font-mono tabular-nums">{b.rapport ? `×${b.rapport.toFixed(1)}` : "—"}</td>
                <td className="px-3 py-4">
                  <span className={cn("inline-flex justify-center items-center w-[68px] rounded-full py-0.5 text-[10px] font-semibold ring-1", pm.cls)}>{pm.label}</span>
                </td>
                <td className="whitespace-nowrap px-3 py-4 text-right">
                  <span className="font-bold tabular-nums text-emerald-700">+{b.benefice.toFixed(2)}€</span>
                  {b.fige_avant_course && <span className="mt-1 flex items-center justify-end gap-1 text-[10px] text-emerald-700"><LockKeyhole className="h-3 w-3" aria-hidden="true" /> vérifié</span>}
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
  const [recentLimit, setRecentLimit] = useState(10);
  const [recordsLimit, setRecordsLimit] = useState(10);
  const { data, isLoading, error, mutate } = useSWR<TrackRecord>(
    "track-record",
    () => statsApi.trackRecord().then((r) => r.data),
    { refreshInterval: 60_000, revalidateOnFocus: true, shouldRetryOnError: false }  // recalcul ~ à chaque fin de course
  );

  // Paris RÉELLEMENT gagnés par l'algorithme, par profil (pronos émis réglés)
  const { data: gagnantsData, error: gagnantsError, mutate: mutateGagnants } = useSWR<{
    gagnants: WinningBet[]; top_gains?: WinningBet[]; n: number; n_courses?: number; total_gain?: number; total_benefice?: number;
    profils?: Array<{ profil: string; label: string; nb_courses: number; mise_totale?: number; gain_total?: number; gain_net: number; roi: number | null; paris_gagnes: number; taux_courses_beneficiaires: number | null }>;
    updated_at?: string;
  }>(
    "palmares-gagnants",
    // `palmaresGagnants` est gardé par require_admin → 401 pour un visiteur, et cette
    // page est PUBLIQUE : sans repli, tout prospect voyait un palmarès vide. On tente
    // d'abord la version admin (agrégats ROI/profil en plus), et on retombe sur la
    // version publique sinon. Les blocs ROI se masquent d'eux-mêmes quand `profils`
    // est absent — le ROI reste donc admin-only, conformément à la règle produit.
    async () => {
      try {
        return (await statsApi.palmaresGagnants()).data;
      } catch {
        const pub = (await statsApi.palmaresPublic()).data;
        return {
          gagnants: pub.gagnants ?? [],
          top_gains: pub.top_gains ?? [],
          n: pub.nb_paris_gagnes ?? 0,
          n_courses: pub.nb_courses_reglees ?? 0,
          updated_at: pub.updated_at,
        };
      }
    },
    { refreshInterval: 60_000, revalidateOnFocus: true, shouldRetryOnError: false },
  );

  if (isLoading) {
    return (
      <div className="min-h-screen bg-[#FCFBF8] px-4 py-16" aria-busy="true" aria-label="Chargement du palmarès">
        <div className="mx-auto max-w-6xl animate-pulse space-y-8">
          <div className="h-5 w-36 rounded-full bg-stone-200" />
          <div className="h-12 max-w-2xl rounded-2xl bg-stone-200" />
          <div className="h-5 max-w-xl rounded-full bg-stone-100" />
          <div className="grid gap-4 sm:grid-cols-3"><div className="h-28 rounded-2xl bg-white" /><div className="h-28 rounded-2xl bg-white" /><div className="h-28 rounded-2xl bg-white" /></div>
          <div className="h-80 rounded-3xl bg-white" />
        </div>
      </div>
    );
  }

  // Erreur API → message clair au lieu d'un spinner infini.
  if (error || !data) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#FCFBF8] px-4">
        <div role="alert" className="w-full max-w-md rounded-3xl border border-border bg-white p-8 text-center shadow-sm">
          <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-amber-50 text-amber-800"><BarChart3 className="h-5 w-5" aria-hidden="true" /></span>
          <h1 className="mt-4 font-display text-xl font-bold text-foreground">Palmarès temporairement indisponible</h1>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">Les données n&apos;ont pas pu être chargées. Aucun résultat en cache n&apos;est affiché.</p>
          <Button onClick={() => mutate()} variant="brand" className="mt-6 min-h-11"><RefreshCw className="h-4 w-4" /> Réessayer</Button>
        </div>
      </div>
    );
  }

  const g = data.global;

  return (
    <div className="min-h-screen bg-[#FCFBF8]">

      {/* ── Hero éditorial : preuve avant promesse ─────────────────────── */}
      <header className="border-b border-stone-200/80 bg-white">
        <div className="mx-auto grid max-w-7xl items-center gap-10 px-4 py-12 sm:px-6 sm:py-16 lg:grid-cols-[1.05fr_.95fr] lg:py-20">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-emerald-800">
              <BadgeCheck className="h-3.5 w-3.5" aria-hidden="true" /> Palmarès vérifié
            </div>
            <h1 className="mt-6 max-w-3xl font-display text-4xl font-bold leading-[1.04] tracking-[-0.035em] text-slate-950 sm:text-5xl lg:text-6xl">
              Les résultats parlent.<br /><span className="text-amber-800">Chaque gain est consultable.</span>
            </h1>
            <p className="mt-5 max-w-xl text-base leading-7 text-slate-600 sm:text-lg">
              Les pronostics sont figés avant le départ, puis réglés avec les rapports PMU officiels. Ici, vous voyez les résultats — pas une promesse.
            </p>
            <div className="mt-7 flex flex-col gap-3 sm:flex-row">
              <Button asChild variant="brand" size="lg" className="min-h-12 rounded-xl px-6 shadow-none">
                <Link href="/tarifs">Découvrir l&apos;offre Pro <ArrowRight className="ml-1 h-4 w-4" /></Link>
              </Button>
              <Button asChild variant="outline" size="lg" className="min-h-12 rounded-xl border-stone-300 bg-white px-6">
                <a href="#preuves">Voir les résultats</a>
              </Button>
            </div>
            <div className="mt-7 flex flex-wrap gap-x-5 gap-y-2 text-xs text-slate-500">
              <span className="inline-flex items-center gap-1.5"><LockKeyhole className="h-3.5 w-3.5 text-emerald-700" aria-hidden="true" /> Pronostics horodatés</span>
              <span className="inline-flex items-center gap-1.5"><Database className="h-3.5 w-3.5 text-emerald-700" aria-hidden="true" /> Rapports officiels</span>
              <span className="inline-flex items-center gap-1.5"><Clock3 className="h-3.5 w-3.5 text-emerald-700" aria-hidden="true" /> Mise à jour continue</span>
            </div>
          </div>

          <div className="relative overflow-hidden rounded-[2rem] bg-slate-950 p-6 text-white shadow-[0_24px_70px_-38px_rgba(15,23,42,.75)] sm:p-8">
            <div className="absolute inset-0 opacity-15 [background-image:radial-gradient(circle_at_1px_1px,white_1px,transparent_0)] [background-size:24px_24px]" aria-hidden="true" />
            <div className="relative">
              <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-amber-300">Preuve en chiffres</p>
              <div className="mt-6 grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-white/10 bg-white/10">
                <div className="bg-slate-950/90 p-5 sm:p-6">
                  <p className="text-3xl font-bold tabular-nums sm:text-4xl">{g.accuracy_top3.toLocaleString("fr-FR", { maximumFractionDigits: 1 })}%</p>
                  <p className="mt-2 text-xs leading-5 text-slate-400">Précision Top-3</p>
                </div>
                <div className="bg-slate-950/90 p-5 sm:p-6">
                  <p className="text-3xl font-bold tabular-nums sm:text-4xl">{g.nb_courses_analysees.toLocaleString("fr-FR")}</p>
                  <p className="mt-2 text-xs leading-5 text-slate-400">Courses analysées</p>
                </div>
                <div className="col-span-2 bg-slate-950/90 p-5 sm:p-6">
                  <div className="flex items-end justify-between gap-4">
                    <div><p className="text-3xl font-bold tabular-nums text-emerald-300 sm:text-5xl">{gagnantsData ? `+${(gagnantsData.total_gain ?? 0).toLocaleString("fr-FR", { maximumFractionDigits: 0 })}€` : "—"}</p><p className="mt-2 text-xs text-slate-400">Gains encaissés documentés</p></div>
                    <div className="text-right"><p className="text-xl font-bold tabular-nums">{gagnantsData?.n.toLocaleString("fr-FR") ?? "—"}</p><p className="mt-1 text-[11px] text-slate-400">paris gagnés</p></div>
                  </div>
                </div>
              </div>
              <EchantillonNotice
                nbCourses={g.nb_courses_analysees}
                mesureDepuis={g.mesure_depuis}
                variante="sombre"
              />
              {data.updated_at && <p className="mt-5 flex items-center gap-2 text-[11px] text-slate-400"><RefreshCw className="h-3.5 w-3.5" aria-hidden="true" /> Actualisé le {new Date(data.updated_at).toLocaleDateString("fr-FR")} à {new Date(data.updated_at).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}</p>}
            </div>
          </div>
        </div>
      </header>

      <main id="preuves" className="mx-auto max-w-7xl space-y-16 px-4 py-12 sm:px-6 sm:py-16 lg:space-y-20">

        {/* ── TOTAL DES GAINS générés par l'algorithme, par profil ───────────── */}
        <section aria-label="Gains vérifiés" className="space-y-6">
          <SectionHeading eyebrow="Vue d'ensemble" title="Les gains vérifiés" description="Une lecture consolidée des gains encaissés et de leur répartition par profil de risque." icon={Coins} />
        <Card className="overflow-hidden rounded-3xl border-stone-200 bg-white shadow-[0_18px_55px_-45px_rgba(15,23,42,.5)]">
          <CardContent className="p-5 sm:p-8">
            {gagnantsError ? (
              <div role="alert" className="py-10 text-center text-sm text-muted-foreground"><p>Les gains détaillés sont indisponibles pour le moment.</p><Button onClick={() => mutateGagnants()} variant="outline" className="mt-4 min-h-11"><RefreshCw className="h-4 w-4" /> Réessayer</Button></div>
            ) : !gagnantsData ? (
              <div className="py-8 text-center text-sm text-muted-foreground animate-pulse">Chargement…</div>
            ) : (
              <>
                {/* Grand total encaissé (count-up) */}
                <div className="rounded-2xl border border-emerald-200 bg-emerald-50/55 p-5 sm:p-7">
                  <div className="flex flex-col sm:flex-row items-center sm:items-end justify-between gap-4">
                    <div>
                      <div className="flex items-center justify-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-emerald-800 sm:justify-start">
                        <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" /> Total réglé aux rapports officiels
                      </div>
                      <CountUpEuro
                        value={gagnantsData.total_gain ?? 0}
                        prefix="+"
                        className="mt-3 block text-4xl font-bold leading-none tabular-nums text-emerald-800 sm:text-6xl"
                      />
                    </div>
                    <div className="grid grid-cols-2 gap-6 text-center sm:text-right">
                      <div><div className="text-2xl font-bold tabular-nums text-foreground">{gagnantsData.n.toLocaleString("fr-FR")}</div><div className="mt-1 text-[10px] uppercase tracking-wider text-muted-foreground">Paris gagnés</div></div>
                      <div><div className="text-2xl font-bold tabular-nums text-foreground">{(gagnantsData.n_courses ?? 0).toLocaleString("fr-FR")}</div><div className="mt-1 text-[10px] uppercase tracking-wider text-muted-foreground">Courses réglées</div></div>
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
                      <div className="mt-8 space-y-5" aria-label="Répartition des gains encaissés par profil">
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
                              <div className="h-2.5 overflow-hidden rounded-full bg-stone-100">
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
                      <div className="mt-8 grid grid-cols-1 gap-3 sm:grid-cols-3">
                        {gagnantsData.profils!.map((p) => {
                          const pm = PROFIL_LABELS[p.profil] ?? { label: p.label, cls: "bg-muted text-muted-foreground ring-border" };
                          return (
                            <div key={p.profil} className="rounded-2xl border border-stone-200 bg-stone-50/60 p-4 sm:p-5">
                              <div className="flex items-center justify-between">
                                <span className={cn("inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1", pm.cls)}>{pm.label}</span>
                                <span className="text-[10px] uppercase tracking-wider text-muted-foreground">{p.nb_courses} courses</span>
                              </div>
                              <CountUpEuro
                                value={p.gain_total ?? 0}
                                prefix="+"
                                className="mt-4 block text-2xl font-bold leading-none tabular-nums text-emerald-800"
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

                <p className="mt-6 flex items-start gap-2 rounded-xl bg-stone-50 px-3 py-2.5 text-[11px] leading-5 text-muted-foreground">
                  <ShieldCheck className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-emerald-700" />
                  Gains réels, figés avant le départ et réglés aux rapports PMU officiels. Performances passées — aucune garantie de gain futur.
                </p>
              </>
            )}
          </CardContent>
        </Card>
        </section>

        {/* ── Méthode de vérification ─────────────────────────────────────── */}
        <section aria-label="Méthode de vérification" className="rounded-3xl border border-stone-200 bg-white p-6 sm:p-8">
          <div className="grid gap-6 md:grid-cols-[.8fr_2.2fr] md:items-center">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-amber-800">Traçabilité</p>
              <h2 className="mt-2 font-display text-2xl font-bold tracking-tight">Comment un gain devient une preuve</h2>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">Trois étapes simples, consultables course par course.</p>
            </div>
            <ol className="grid gap-3 sm:grid-cols-3">
              {[
                { icon: LockKeyhole, n: "01", title: "Pronostic figé", text: "La sélection est horodatée avant le départ." },
                { icon: Database, n: "02", title: "Rapport officiel", text: "Le résultat est réglé avec les données PMU." },
                { icon: ExternalLink, n: "03", title: "Preuve consultable", text: "Chaque ligne renvoie vers la course concernée." },
              ].map((step) => (
                <li key={step.n} className="rounded-2xl bg-stone-50 p-4">
                  <div className="flex items-center justify-between"><step.icon className="h-4 w-4 text-amber-800" aria-hidden="true" /><span className="font-display text-[10px] font-bold tracking-widest text-stone-400">{step.n}</span></div>
                  <h3 className="mt-4 text-sm font-semibold">{step.title}</h3>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">{step.text}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* ── 50 derniers paris gagnés (tous profils) ───────────────────────── */}
        <section aria-label="Derniers paris gagnés" className="space-y-6">
          <SectionHeading eyebrow="Historique en direct" title="Les derniers paris gagnés" description="Les 50 résultats les plus récents, tous profils confondus. Ouvrez une course pour contrôler le détail." icon={Receipt} />
        <Card className="overflow-hidden rounded-3xl border-stone-200 bg-white shadow-none">
          <CardHeader className="flex-row items-center justify-between space-y-0 border-b border-stone-100 p-4 sm:px-6">
            <p className="inline-flex items-center gap-2 text-xs font-medium text-emerald-800"><span className="h-2 w-2 rounded-full bg-emerald-500" /> Données actualisées</p>
            <p className="text-xs text-muted-foreground">Mise de référence : 10€ / course</p>
          </CardHeader>
          <CardContent className="p-4 sm:p-6">
            {!gagnantsData ? (
              <div className="py-8 text-center text-sm text-muted-foreground animate-pulse">Chargement…</div>
            ) : gagnantsData.gagnants.length === 0 ? (
              <div className="py-8 text-center text-sm text-muted-foreground">
                Les paris gagnants apparaîtront ici dès les prochaines arrivées (l&apos;historique se construit en temps réel).
              </div>
            ) : (
              <>
                <BetsTable bets={gagnantsData.gagnants.slice(0, recentLimit)} />
                {recentLimit < Math.min(50, gagnantsData.gagnants.length) && (
                  <div className="mt-5 flex justify-center">
                    <Button onClick={() => setRecentLimit((n) => Math.min(n + 10, 50))} variant="outline" className="min-h-11 rounded-xl border-stone-300 bg-white">
                      Afficher 10 résultats supplémentaires <ChevronDown className="h-4 w-4" />
                    </Button>
                  </div>
                )}
                <p className="mt-5 border-t border-stone-100 pt-4 text-[11px] text-muted-foreground">
                  {gagnantsData.n} pari{gagnantsData.n > 1 ? "s" : ""} gagnant{gagnantsData.n > 1 ? "s" : ""} au total ·
                  {Math.min(recentLimit, gagnantsData.gagnants.length)} résultat{Math.min(recentLimit, gagnantsData.gagnants.length) > 1 ? "s" : ""} affiché{Math.min(recentLimit, gagnantsData.gagnants.length) > 1 ? "s" : ""}.
                </p>
              </>
            )}
          </CardContent>
        </Card>
        </section>

        {/* ── 30 meilleurs gains ────────────────────────────────────────────── */}
        {gagnantsData?.top_gains && gagnantsData.top_gains.length > 0 && (
          <section aria-label="Plus gros gains" className="space-y-6">
            <SectionHeading eyebrow="Records" title="Les plus gros gains" description="Les 30 meilleures performances nettes enregistrées et réglées aux rapports officiels." icon={Star} />
          <Card className="overflow-hidden rounded-3xl border-amber-200 bg-white shadow-none">
            <CardContent className="p-4 sm:p-6">
              <BetsTable bets={gagnantsData.top_gains.slice(0, recordsLimit)} ranked />
              {recordsLimit < gagnantsData.top_gains.length && (
                <div className="mt-5 flex justify-center">
                  <Button onClick={() => setRecordsLimit((n) => Math.min(n + 10, 30))} variant="outline" className="min-h-11 rounded-xl border-stone-300 bg-white">Afficher plus de records <ChevronDown className="h-4 w-4" /></Button>
                </div>
              )}
            </CardContent>
          </Card>
          </section>
        )}

        {/* ── Conversion après démonstration de valeur ────────────────────── */}
        <section className="relative overflow-hidden rounded-[2rem] bg-slate-950 px-6 py-10 text-white sm:px-10 sm:py-12" aria-labelledby="cta-pro-title">
          <div className="absolute -right-20 -top-20 h-64 w-64 rounded-full bg-amber-500/10 blur-3xl" aria-hidden="true" />
          <div className="relative grid gap-8 lg:grid-cols-[1fr_auto] lg:items-end">
            <div>
              <div className="inline-flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-amber-300"><Crown className="h-3.5 w-3.5" aria-hidden="true" /> BlackTurf Pro</div>
              <h2 id="cta-pro-title" className="mt-4 max-w-2xl font-display text-3xl font-bold tracking-tight sm:text-4xl">Passez des résultats aux décisions.</h2>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300 sm:text-base">Retrouvez les analyses complètes, les probabilités et les plans de mise qui ont produit ce palmarès. Les performances passées ne garantissent pas les résultats futurs.</p>
              <ul className="mt-6 grid gap-2 text-sm text-slate-200 sm:grid-cols-3">
                <li className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-emerald-300" aria-hidden="true" /> Pronostics complets</li>
                <li className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-emerald-300" aria-hidden="true" /> Plans de mise</li>
                <li className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-emerald-300" aria-hidden="true" /> Cotes en direct</li>
              </ul>
            </div>
            <Button asChild variant="brand" size="lg" className="min-h-12 rounded-xl px-7 shadow-none">
              <Link href="/tarifs">Voir les offres Pro <ArrowRight className="ml-1 h-4 w-4" /></Link>
            </Button>
          </div>
        </section>

        {/* ── Précision par discipline (donnée simple, lisible) ───────────── */}
        <section aria-label="Précision par discipline" className="space-y-6">
          <SectionHeading eyebrow="Qualité du modèle" title="La précision par discipline" description="Une vue simple du taux de présence dans le Top-3, rapportée au volume de courses analysées." icon={Target} />

          {/* By discipline */}
          <Card className="rounded-3xl border-stone-200 bg-white shadow-none">
            <CardContent className="p-5 sm:p-8">
              {data.by_discipline.length === 0 ? (
                <div className="py-6 text-center text-sm text-muted-foreground">
                  Aucune donnée pour le moment
                </div>
              ) : (
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {data.by_discipline.map((d) => (
                    <div key={d.discipline} className="rounded-2xl border border-stone-200 bg-stone-50/60 p-4">
                      <div className="mb-4 flex items-start justify-between gap-3">
                        <div>
                          <span className="block text-sm font-semibold text-foreground">{d.discipline}</span>
                          <span className="mt-1 block text-xs text-muted-foreground">{d.nb_courses} courses analysées</span>
                        </div>
                        <span className={cn("text-lg font-bold tabular-nums",
                          d.accuracy_top3 >= 50 ? "text-emerald-600" :
                          d.accuracy_top3 >= 35 ? "text-amber-600" : "text-muted-foreground"
                        )}>
                          {d.accuracy_top3}%
                        </span>
                      </div>
                      <div className="h-2 overflow-hidden rounded-full bg-stone-200" role="img" aria-label={`${d.discipline} : ${d.accuracy_top3}% de précision Top-3`}>
                        <div
                          className="h-full rounded-full bg-amber-600 transition-all"
                          style={{ width: `${Math.min(d.accuracy_top3, 100)}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </section>

        {/* Détails techniques (Brier, calibration, apprentissage) déplacés dans
            l'espace admin — le palmarès public reste sur des résultats simples. */}
        <p className="mx-auto max-w-3xl border-t border-stone-200 pt-6 text-center text-[11px] leading-5 text-muted-foreground">
          Résultats réels, recalculés à chaque fin de course. Aucune donnée simulée hors des
          backtests explicitement étiquetés.
        </p>
      </main>
    </div>
  );
}
