"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import {
  Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import {
  Trophy, Star, Receipt, Coins, ArrowRight, ShieldCheck, BadgeCheck,
  Clock3, Database, ExternalLink, LockKeyhole, BarChart3, RefreshCw,
  CheckCircle2, CalendarDays, Target, Crown, ChevronDown, TrendingUp,
  Dices, LineChart, Gauge, Sparkles, Users, Bell, Wallet, Brain, Minus,
} from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { DisciplineImg } from "@/components/ui/DisciplineIcon";
import { axisTick, GRID, ChartTooltip } from "@/components/charts/chart-kit";
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
    // Sous-ensemble strictement rejouable (snapshots immuables). Toujours ≤
    // nb_courses_analysees : sert la mention « vérifiable », pas les taux.
    nb_courses_rejouables?: number;
    // Date de la plus ancienne course mesurée (ISO) — la cohorte publiée retient
    // toute course dont le pronostic était figé AVANT le départ.
    mesure_depuis?: string | null;
    nb_surprises: number;
    // Repères « hasard » calculés sur le champ réel de chaque course.
    hasard_top3?: number | null;
    hasard_top1?: number | null;
    nb_partants_moyen?: number | null;
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
  // Série longue (30 j) — les jours sans course mesurée sont ABSENTS du tableau.
  tendance_30j?: Array<{
    date: string;
    jour: string;
    nb_predictions: number;
    accuracy_top3: number;
    accuracy_top1: number;
  }>;
  by_discipline: Array<{
    discipline: string;
    nb_courses: number;
    accuracy_top3: number;
    accuracy_top1?: number;
    brier_moyen?: number | null;
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

const nf = (n: number, d = 0) =>
  n.toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d });
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

function CountUp({ value, decimals = 0, suffix = "", prefix = "", className }: {
  value: number; decimals?: number; suffix?: string; prefix?: string; className?: string;
}) {
  const { val, ref } = useCountUp(value);
  return <span ref={ref} className={className}>{prefix}{nf(val, decimals)}{suffix}</span>;
}

function CountUpEuro({ value, className, decimals = 0, prefix = "" }: { value: number; className?: string; decimals?: number; prefix?: string }) {
  return <CountUp value={value} decimals={decimals} prefix={prefix} suffix="€" className={className} />;
}

function SectionHeading({ eyebrow, title, description, icon: Icon, align = "left" }: {
  eyebrow: string;
  title: string;
  description: string;
  icon: typeof Trophy;
  align?: "left" | "center";
}) {
  return (
    <div className={cn("flex items-start gap-3 sm:gap-4", align === "center" && "flex-col items-center text-center")}>
      <span className="mt-0.5 inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-amber-200 bg-amber-50 text-amber-800">
        <Icon className="h-5 w-5" aria-hidden="true" />
      </span>
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-amber-800">{eyebrow}</p>
        <h2 className="mt-1 font-display text-xl font-bold tracking-tight text-foreground sm:text-2xl">{title}</h2>
        <p className={cn("mt-1.5 max-w-2xl text-sm leading-6 text-muted-foreground", align === "center" && "mx-auto")}>{description}</p>
      </div>
    </div>
  );
}

// ─── Tuile de chiffre clé ─────────────────────────────────────
function KpiTile({ icon: Icon, label, value, sub, accent = false, footer }: {
  icon: typeof Target;
  label: string;
  value: React.ReactNode;
  sub?: string;
  accent?: boolean;
  footer?: React.ReactNode;
}) {
  return (
    <div className={cn(
      "flex h-full flex-col rounded-2xl border p-5 transition-shadow sm:p-6",
      accent
        ? "border-amber-200 bg-gradient-to-b from-amber-50/80 to-white shadow-[0_18px_45px_-40px_rgba(180,83,9,.7)]"
        : "border-stone-200 bg-white shadow-[0_18px_45px_-42px_rgba(15,23,42,.55)]",
    )}>
      <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
        <Icon className={cn("h-3.5 w-3.5", accent ? "text-amber-700" : "text-stone-400")} aria-hidden="true" />
        {label}
      </div>
      <div className={cn("mt-3 font-display text-3xl font-bold tabular-nums sm:text-4xl", accent ? "text-amber-800" : "text-slate-900")}>
        {value}
      </div>
      {sub && <p className="mt-2 text-xs leading-5 text-muted-foreground">{sub}</p>}
      {footer && <div className="mt-auto pt-4">{footer}</div>}
    </div>
  );
}

// ─── Courbe de tendance (30 jours) ────────────────────────────
type PointTendance = { jour: string; top3: number | null; nb: number };

/**
 * Complète la série renvoyée par l'API avec les jours SANS course mesurée.
 * L'API ne renvoie que les jours peuplés : sans ce remplissage, un trou de
 * collecte (ex. 12→15/08) se lirait comme une continuité — la courbe raconterait
 * une régularité que les données n'ont pas. On insère `null` (trou visible) au
 * lieu de 0 %, qui se lirait comme un échec du modèle.
 */
function completerJours(
  serie: Array<{ date: string; jour: string; accuracy_top3: number; nb_predictions: number }>,
  jours = 30,
): PointTendance[] {
  if (serie.length === 0) return [];
  const parDate = new Map(serie.map((p) => [p.date, p]));
  const fin = new Date(`${serie[serie.length - 1].date}T12:00:00Z`);
  const out: PointTendance[] = [];
  for (let i = jours - 1; i >= 0; i--) {
    const d = new Date(fin);
    d.setUTCDate(d.getUTCDate() - i);
    const iso = d.toISOString().slice(0, 10);
    const p = parDate.get(iso);
    out.push({
      jour: `${iso.slice(8, 10)}/${iso.slice(5, 7)}`,
      top3: p ? p.accuracy_top3 : null,
      nb: p ? p.nb_predictions : 0,
    });
  }
  return out;
}

function TendanceChart({ data, moyenne, hasard }: { data: PointTendance[]; moyenne: number; hasard: number | null }) {
  return (
    <div className="h-[260px] w-full sm:h-[300px]">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 12, right: 8, bottom: 0, left: -18 }}>
          <defs>
            <linearGradient id="tendanceFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#F59E0B" stopOpacity={0.35} />
              <stop offset="100%" stopColor="#F59E0B" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid {...GRID} />
          <XAxis
            dataKey="jour"
            tick={axisTick}
            axisLine={false}
            tickLine={false}
            interval="preserveStartEnd"
            minTickGap={28}
          />
          <YAxis
            domain={[0, 100]}
            ticks={[0, 25, 50, 75, 100]}
            tick={axisTick}
            axisLine={false}
            tickLine={false}
            width={44}
            tickFormatter={(v: number) => `${v}%`}
          />
          {hasard != null && (
            <ReferenceLine
              y={hasard}
              stroke="#94A3B8"
              strokeDasharray="4 4"
              label={{ value: `hasard ${nf(hasard, 0)} %`, position: "insideBottomRight", fontSize: 10, fill: "#94A3B8" }}
            />
          )}
          <ReferenceLine
            y={moyenne}
            stroke="#059669"
            strokeDasharray="5 3"
            label={{ value: `moyenne ${nf(moyenne, 1)} %`, position: "insideTopRight", fontSize: 10, fill: "#059669" }}
          />
          <Tooltip
            content={
              <ChartTooltip
                labelMap={{ top3: "Top-3" }}
                valueFormatter={(v) => `${nf(v, 1)} %`}
              />
            }
          />
          <Area
            type="monotone"
            dataKey="top3"
            name="Top-3"
            stroke="#B45309"
            strokeWidth={2}
            fill="url(#tendanceFill)"
            connectNulls={false}
            dot={false}
            activeDot={{ r: 4, strokeWidth: 2, stroke: "#fff" }}
          />
        </AreaChart>
      </ResponsiveContainer>
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

// ─── Carte discipline ─────────────────────────────────────────
function DisciplineCard({ d, maxCourses, hasard }: {
  d: TrackRecord["by_discipline"][number];
  maxCourses: number;
  hasard: number | null;
}) {
  const partVolume = maxCourses > 0 ? Math.round((d.nb_courses / maxCourses) * 100) : 0;
  return (
    <div className="group relative overflow-hidden rounded-2xl border border-stone-200 bg-white p-5 transition-all hover:border-amber-200 hover:shadow-[0_20px_45px_-38px_rgba(180,83,9,.75)]">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="inline-flex h-11 w-11 items-center justify-center rounded-xl bg-stone-50 ring-1 ring-stone-200">
            <DisciplineImg discipline={d.discipline} className="h-7 w-8" />
          </span>
          <div>
            <span className="block text-sm font-semibold capitalize text-foreground">{d.discipline}</span>
            <span className="mt-0.5 block text-xs tabular-nums text-muted-foreground">
              {nf(d.nb_courses)} course{d.nb_courses > 1 ? "s" : ""} analysée{d.nb_courses > 1 ? "s" : ""}
            </span>
          </div>
        </div>
        <div className="text-right">
          <span className={cn("block font-display text-2xl font-bold tabular-nums",
            d.accuracy_top3 >= 55 ? "text-emerald-700" : d.accuracy_top3 >= 40 ? "text-amber-700" : "text-slate-600")}>
            {nf(d.accuracy_top3, 1)} %
          </span>
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground">Top-3</span>
        </div>
      </div>

      {/* Barre Top-3 + repère hasard */}
      <div className="relative mt-5 h-2.5 overflow-hidden rounded-full bg-stone-100" role="img"
        aria-label={`${d.discipline} : ${nf(d.accuracy_top3, 1)} % de présence du gagnant dans le Top-3, sur ${nf(d.nb_courses)} courses`}>
        <div className="h-full rounded-full bg-gradient-to-r from-amber-400 to-amber-600 transition-all duration-700"
          style={{ width: `${Math.min(d.accuracy_top3, 100)}%` }} />
      </div>
      {hasard != null && (
        <div className="relative h-3">
          <span className="absolute top-0 -translate-x-1/2 text-[9px] font-medium text-slate-400"
            style={{ left: `${Math.min(hasard, 100)}%` }}>▲ hasard</span>
        </div>
      )}

      <dl className="mt-4 grid grid-cols-3 gap-2 border-t border-stone-100 pt-3 text-center">
        <div>
          <dt className="text-[10px] uppercase tracking-wider text-muted-foreground">Top-1</dt>
          <dd className="mt-0.5 text-sm font-bold tabular-nums text-slate-900">
            {d.accuracy_top1 != null ? `${nf(d.accuracy_top1, 1)} %` : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-[10px] uppercase tracking-wider text-muted-foreground">Brier</dt>
          <dd className="mt-0.5 text-sm font-bold tabular-nums text-slate-900">
            {d.brier_moyen != null ? nf(d.brier_moyen, 3) : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-[10px] uppercase tracking-wider text-muted-foreground">Volume</dt>
          <dd className="mt-0.5 text-sm font-bold tabular-nums text-slate-900">{partVolume} %</dd>
        </div>
      </dl>
    </div>
  );
}

// ─── FAQ ──────────────────────────────────────────────────────
function Faq({ q, children }: { q: string; children: React.ReactNode }) {
  return (
    <details className="group rounded-2xl border border-stone-200 bg-white px-5 py-4 open:border-amber-200 open:bg-amber-50/30">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-4 text-sm font-semibold text-foreground marker:content-none">
        {q}
        <ChevronDown className="h-4 w-4 shrink-0 text-amber-700 transition-transform group-open:rotate-180" aria-hidden="true" />
      </summary>
      <div className="mt-3 text-sm leading-6 text-muted-foreground">{children}</div>
    </details>
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

  // Série 30 j complétée + moyenne pondérée par le volume de courses du jour
  // (une moyenne simple donnerait autant de poids à un jour de 3 courses qu'à un
  // jour de 60 → une journée creuse déformerait la ligne de référence).
  const tendance = useMemo(() => {
    const brute = data?.tendance_30j ?? [];
    const points = completerJours(brute);
    const total = brute.reduce((s, p) => s + p.nb_predictions, 0);
    const moyenne = total > 0
      ? brute.reduce((s, p) => s + p.accuracy_top3 * p.nb_predictions, 0) / total
      : 0;
    return { points, moyenne, totalCourses: total, jours: brute.length };
  }, [data?.tendance_30j]);

  if (isLoading) {
    return (
      <div className="min-h-screen bg-[#FCFBF8] px-4 py-16" aria-busy="true" aria-label="Chargement du palmarès">
        <div className="mx-auto max-w-6xl animate-pulse space-y-8">
          <div className="h-5 w-36 rounded-full bg-stone-200" />
          <div className="h-12 max-w-2xl rounded-2xl bg-stone-200" />
          <div className="h-5 max-w-xl rounded-full bg-stone-100" />
          <div className="grid gap-4 sm:grid-cols-4"><div className="h-32 rounded-2xl bg-white" /><div className="h-32 rounded-2xl bg-white" /><div className="h-32 rounded-2xl bg-white" /><div className="h-32 rounded-2xl bg-white" /></div>
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
  const hasard3 = g.hasard_top3 ?? null;
  const hasard1 = g.hasard_top1 ?? null;
  const facteur3 = hasard3 && hasard3 > 0 ? g.accuracy_top3 / hasard3 : null;
  const facteur1 = hasard1 && hasard1 > 0 ? g.accuracy_top1 / hasard1 : null;
  const depuis = g.mesure_depuis
    ? new Date(g.mesure_depuis).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" })
    : null;
  const maxCourses = Math.max(1, ...data.by_discipline.map((d) => d.nb_courses));
  const clv = data.clv;

  return (
    <div className="min-h-screen bg-[#FCFBF8]">

      {/* ── Hero éditorial : preuve avant promesse ─────────────────────── */}
      <header className="relative overflow-hidden border-b border-stone-200/80 bg-white">
        {/* Photo d'ambiance très en retrait : elle habille, elle ne parle pas à la
            place des chiffres (contraste du texte préservé sur mobile). */}
        <div
          className="pointer-events-none absolute inset-0 bg-cover bg-center opacity-[0.07]"
          style={{ backgroundImage: "url(/img/hero.webp)" }}
          aria-hidden="true"
        />
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-white via-white/85 to-white" aria-hidden="true" />

        <div className="relative mx-auto grid max-w-7xl items-center gap-10 px-4 py-12 sm:px-6 sm:py-16 lg:grid-cols-[1.05fr_.95fr] lg:py-20">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-emerald-800">
              <BadgeCheck className="h-3.5 w-3.5" aria-hidden="true" /> Palmarès vérifié
            </div>
            <h1 className="mt-6 max-w-3xl font-display text-4xl font-bold leading-[1.04] tracking-[-0.035em] text-slate-950 sm:text-5xl lg:text-6xl">
              <CountUp value={g.nb_courses_analysees} /> courses analysées.<br />
              <span className="text-amber-800">Chaque pronostic horodaté.</span>
            </h1>
            <p className="mt-5 max-w-xl text-base leading-7 text-slate-600 sm:text-lg">
              Les pronostics sont figés avant le départ, puis réglés avec les rapports PMU officiels.
              {depuis ? ` Tout ce que vous voyez ici est mesuré depuis le ${depuis}.` : ""} Des résultats, pas une promesse.
            </p>
            <div className="mt-7 flex flex-col gap-3 sm:flex-row">
              <Button asChild variant="brand" size="lg" className="min-h-12 rounded-xl px-6 shadow-none">
                <Link href="/tarifs">Essayer 7 jours gratuitement <ArrowRight className="ml-1 h-4 w-4" /></Link>
              </Button>
              <Button asChild variant="outline" size="lg" className="min-h-12 rounded-xl border-stone-300 bg-white px-6">
                <a href="#preuves">Voir la méthode et les preuves</a>
              </Button>
            </div>
            <div className="mt-7 flex flex-wrap gap-x-5 gap-y-2 text-xs text-slate-500">
              <span className="inline-flex items-center gap-1.5"><LockKeyhole className="h-3.5 w-3.5 text-emerald-700" aria-hidden="true" /> Pronostics horodatés</span>
              <span className="inline-flex items-center gap-1.5"><Database className="h-3.5 w-3.5 text-emerald-700" aria-hidden="true" /> Rapports officiels</span>
              <span className="inline-flex items-center gap-1.5"><Clock3 className="h-3.5 w-3.5 text-emerald-700" aria-hidden="true" /> Mise à jour continue</span>
              <span className="inline-flex items-center gap-1.5"><CheckCircle2 className="h-3.5 w-3.5 text-emerald-700" aria-hidden="true" /> Sans carte bancaire</span>
            </div>
          </div>

          <div className="relative overflow-hidden rounded-[2rem] bg-slate-950 p-6 text-white shadow-[0_24px_70px_-38px_rgba(15,23,42,.75)] sm:p-8">
            <div className="absolute inset-0 opacity-15 [background-image:radial-gradient(circle_at_1px_1px,white_1px,transparent_0)] [background-size:24px_24px]" aria-hidden="true" />
            <div className="absolute -right-16 -top-16 h-56 w-56 rounded-full bg-amber-500/20 blur-3xl" aria-hidden="true" />
            <div className="relative">
              <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-amber-300">Preuve en chiffres</p>
              <div className="mt-6 grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-white/10 bg-white/10">
                <div className="bg-slate-950/90 p-5 sm:p-6">
                  <p className="text-3xl font-bold tabular-nums sm:text-4xl"><CountUp value={g.accuracy_top3} decimals={1} suffix=" %" /></p>
                  <p className="mt-2 text-xs leading-5 text-slate-400">
                    Gagnant dans notre Top-3
                    {hasard3 != null && <span className="mt-0.5 block text-slate-500">hasard : {nf(hasard3, 0)} %</span>}
                  </p>
                </div>
                <div className="bg-slate-950/90 p-5 sm:p-6">
                  <p className="text-3xl font-bold tabular-nums sm:text-4xl"><CountUp value={g.nb_courses_analysees} /></p>
                  <p className="mt-2 text-xs leading-5 text-slate-400">
                    Courses analysées
                    {depuis && <span className="mt-0.5 block text-slate-500">depuis le {depuis}</span>}
                  </p>
                </div>
                <div className="col-span-2 bg-slate-950/90 p-5 sm:p-6">
                  <div className="flex items-end justify-between gap-4">
                    <div>
                      <p className="text-3xl font-bold tabular-nums text-emerald-300 sm:text-5xl">
                        {gagnantsData ? <CountUpEuro value={gagnantsData.total_gain ?? 0} prefix="+" /> : "—"}
                      </p>
                      <p className="mt-2 text-xs text-slate-400">Gains encaissés documentés</p>
                    </div>
                    <div className="text-right">
                      <p className="text-xl font-bold tabular-nums">{gagnantsData?.n.toLocaleString("fr-FR") ?? "—"}</p>
                      <p className="mt-1 text-[11px] text-slate-400">paris gagnés</p>
                    </div>
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

      <main id="preuves" className="mx-auto max-w-7xl space-y-16 px-4 py-12 sm:px-6 sm:py-16 lg:space-y-24">

        {/* ── Chiffres clés ─────────────────────────────────────────────── */}
        <section aria-label="Chiffres clés" className="space-y-6">
          <SectionHeading
            eyebrow="Qualité du modèle"
            title="Ce que l'algorithme fait, chiffré"
            description="Quatre indicateurs mesurés sur toutes les courses pronostiquées avant le départ. Aucun n'est une promesse de gain : ils décrivent la qualité de l'analyse."
            icon={Gauge}
          />
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <KpiTile
              icon={Target}
              label="Précision Top-3"
              accent
              value={<CountUp value={g.accuracy_top3} decimals={1} suffix=" %" />}
              sub={hasard3 != null
                ? `Le gagnant est dans nos 3 favoris. Un tirage au sort ferait ${nf(hasard3, 0)} % sur les mêmes courses.`
                : "Le gagnant réel figure dans nos 3 favoris."}
              footer={facteur3 ? (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-100/70 px-2.5 py-1 text-[11px] font-semibold text-amber-900">
                  <TrendingUp className="h-3 w-3" aria-hidden="true" /> ×{nf(facteur3, 1)} le hasard
                </span>
              ) : undefined}
            />
            <KpiTile
              icon={Trophy}
              label="Précision Top-1"
              value={<CountUp value={g.accuracy_top1} decimals={1} suffix=" %" />}
              sub={hasard1 != null
                ? `Notre favori gagne la course. Au hasard : ${nf(hasard1, 1)} %.`
                : "Notre favori numéro 1 gagne la course."}
              footer={facteur1 ? (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-stone-100 px-2.5 py-1 text-[11px] font-semibold text-slate-700">
                  <TrendingUp className="h-3 w-3" aria-hidden="true" /> ×{nf(facteur1, 1)} le hasard
                </span>
              ) : undefined}
            />
            <KpiTile
              icon={Database}
              label="Courses analysées"
              value={<CountUp value={g.nb_courses_analysees} />}
              sub={depuis ? `Toutes disciplines, depuis le ${depuis}. Champ moyen : ${g.nb_partants_moyen ? nf(g.nb_partants_moyen, 1) : "—"} partants.` : "Toutes disciplines confondues."}
              footer={g.nb_courses_rejouables ? (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-semibold text-emerald-800 ring-1 ring-emerald-200">
                  <LockKeyhole className="h-3 w-3" aria-hidden="true" /> dont {nf(g.nb_courses_rejouables)} rejouables à l&apos;identique
                </span>
              ) : undefined}
            />
            <KpiTile
              icon={Brain}
              label="Score de Brier"
              value={<CountUp value={g.brier_moyen} decimals={3} />}
              sub="Écart moyen entre nos probabilités et la réalité. Plus il est bas, mieux les probabilités sont calibrées."
              footer={
                <span className="inline-flex items-center gap-1.5 rounded-full bg-stone-100 px-2.5 py-1 text-[11px] font-semibold text-slate-700">
                  <Minus className="h-3 w-3" aria-hidden="true" /> 0 = parfait · 0,25 = pile ou face
                </span>
              }
            />
          </div>
          <p className="flex items-start gap-2 rounded-2xl border border-stone-200 bg-white px-4 py-3 text-[11px] leading-5 text-muted-foreground">
            <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-700" aria-hidden="true" />
            La précision d&apos;analyse mesure la qualité du classement des chevaux. Ce n&apos;est ni un taux de gain,
            ni une garantie de profit : jouer comporte un risque de perte.
          </p>
        </section>

        {/* ── Tendance 30 jours ─────────────────────────────────────────── */}
        {tendance.points.length > 0 && (
          <section aria-label="Tendance sur 30 jours" className="space-y-6">
            <SectionHeading
              eyebrow="Régularité"
              title="Jour après jour, sur 30 jours"
              description="La performance d'un jour ne prouve rien. Celle de trente jours consécutifs, si. Chaque point est la précision Top-3 mesurée sur les courses réglées ce jour-là."
              icon={LineChart}
            />
            <Card className="overflow-hidden rounded-3xl border-stone-200 bg-white shadow-[0_18px_55px_-45px_rgba(15,23,42,.5)]">
              <CardHeader className="flex-row flex-wrap items-center justify-between gap-3 space-y-0 border-b border-stone-100 p-4 sm:px-6">
                <p className="inline-flex items-center gap-2 text-xs font-medium text-emerald-800">
                  <span className="h-2 w-2 rounded-full bg-emerald-500" /> {nf(tendance.totalCourses)} courses sur {tendance.jours} jours mesurés
                </p>
                <p className="text-xs text-muted-foreground">Moyenne pondérée : <span className="font-bold tabular-nums text-foreground">{nf(tendance.moyenne, 1)} %</span></p>
              </CardHeader>
              <CardContent className="p-3 sm:p-6">
                <TendanceChart data={tendance.points} moyenne={tendance.moyenne} hasard={hasard3} />
                <p className="mt-4 border-t border-stone-100 pt-4 text-[11px] leading-5 text-muted-foreground">
                  Les journées sans course mesurée (interruption de collecte) apparaissent en trou plutôt qu&apos;à
                  zéro : afficher 0 % laisserait croire à un échec du modèle là où il n&apos;y a simplement pas de donnée.
                </p>
              </CardContent>
            </Card>
          </section>
        )}

        {/* ── Précision par discipline ──────────────────────────────────── */}
        <section aria-label="Précision par discipline" className="space-y-6">
          <SectionHeading
            eyebrow="Par spécialité"
            title="La précision, discipline par discipline"
            description="Le trot attelé, le plat, le monté et l'obstacle ne se jouent pas de la même façon. Voici le volume réellement analysé et la précision atteinte sur chacun."
            icon={Sparkles}
          />
          {data.by_discipline.length === 0 ? (
            <Card className="rounded-3xl border-stone-200 bg-white shadow-none">
              <CardContent className="py-10 text-center text-sm text-muted-foreground">Aucune donnée pour le moment</CardContent>
            </Card>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {data.by_discipline.map((d) => (
                <DisciplineCard key={d.discipline} d={d} maxCourses={maxCourses} hasard={hasard3} />
              ))}
            </div>
          )}
        </section>

        {/* ── Le favori IA face au marché ───────────────────────────────── */}
        <section aria-label="Le favori de l'algorithme face au marché" className="space-y-6">
          <SectionHeading
            eyebrow="Face au marché"
            title="Notre favori contre la cote des parieurs"
            description="Un bon pronostic ne se contente pas de recopier la cote : il doit voir avant le marché. Ces trois mesures confrontent nos favoris à la réalité de l'arrivée et au mouvement des cotes."
            icon={Users}
          />
          <div className="grid gap-4 lg:grid-cols-3">
            <div className="rounded-3xl border border-stone-200 bg-white p-6">
              <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Favori placé</p>
              <p className="mt-3 font-display text-4xl font-bold tabular-nums text-emerald-700">
                <CountUp value={g.favori_place_rate} decimals={1} suffix=" %" />
              </p>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                Notre cheval numéro 1 termine dans les 3 premiers, sur {nf(g.nb_favoris_evalues)} courses confrontées à l&apos;arrivée officielle.
              </p>
            </div>
            <div className="rounded-3xl border border-stone-200 bg-white p-6">
              <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Favori gagnant</p>
              <p className="mt-3 font-display text-4xl font-bold tabular-nums text-slate-900">
                <CountUp value={g.favori_win_rate} decimals={1} suffix=" %" />
              </p>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                Il gagne franchement la course. À comparer aux {hasard1 != null ? `${nf(hasard1, 1)} %` : "—"} d&apos;un choix au hasard sur le même champ.
              </p>
            </div>
            <div className={cn("rounded-3xl border p-6", clv ? "border-amber-200 bg-gradient-to-b from-amber-50/80 to-white" : "border-stone-200 bg-white")}>
              <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-amber-800">Le marché nous suit</p>
              {clv ? (
                <>
                  <p className="mt-3 font-display text-4xl font-bold tabular-nums text-amber-800">
                    <CountUp value={clv.pct_beat_line} decimals={1} suffix=" %" />
                  </p>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">
                    Part de nos favoris dont la cote <strong className="font-semibold text-foreground">baisse</strong> entre notre pronostic
                    et le départ : le marché se déplace vers notre pick. Mesuré sur {nf(clv.n)} courses.
                  </p>
                </>
              ) : (
                <p className="mt-3 text-sm leading-6 text-muted-foreground">
                  Indicateur en cours de constitution : il demande un historique complet de cotes, de notre pronostic jusqu&apos;au départ.
                </p>
              )}
            </div>
          </div>
        </section>

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
                          const part = Math.round((gain / maxGain) * 100);
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
                                  style={{ ["--bar-pct" as string]: `${part}%` }}
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

        {/* ── Ce que débloque l'abonnement ──────────────────────────────── */}
        <section aria-label="Ce que débloque l'abonnement" className="space-y-6">
          <SectionHeading
            eyebrow="Passer à l'action"
            title="Le palmarès est public. Les pronostics du jour ne le sont pas."
            description="Cette page montre ce que l'algorithme a fait hier. L'abonnement donne accès à ce qu'il annonce pour les courses de tout à l'heure."
            icon={Crown}
          />
          <div className="grid gap-4 lg:grid-cols-3">
            {[
              { icon: Brain, title: "Les pronostics complets", text: "Le classement complet de chaque course, les probabilités par cheval et les intervalles de confiance — pas seulement les 3 premiers.", pro: true },
              { icon: Dices, title: "Les paris de valeur", text: "Les chevaux dont la cote du marché est supérieure à notre probabilité, notés de ★ à ★★★★, mis à jour en continu.", pro: true },
              { icon: Wallet, title: "Le plan de mise", text: "Combien miser, sur quel type de pari, selon votre profil de risque et votre bankroll — figé avant le départ.", pro: true },
              { icon: Bell, title: "Les alertes en direct", text: "Notification dès qu'un pari de valeur apparaît ou qu'une cote décroche sur une course qui vous intéresse.", pro: true },
              { icon: LineChart, title: "Le suivi de vos résultats", text: "Votre capital, vos paris et votre ROI suivis course après course, avec le même degré d'honnêteté que cette page.", pro: true },
              { icon: CalendarDays, title: "Le programme et les cotes", text: "Le programme du jour, les partants et les cotes en direct restent accessibles gratuitement, sans carte bancaire.", pro: false },
            ].map((f) => (
              <div key={f.title} className={cn("rounded-2xl border p-5", f.pro ? "border-amber-200 bg-white" : "border-stone-200 bg-stone-50/60")}>
                <div className="flex items-center justify-between">
                  <span className={cn("inline-flex h-9 w-9 items-center justify-center rounded-xl", f.pro ? "bg-amber-50 text-amber-800 ring-1 ring-amber-200" : "bg-white text-slate-500 ring-1 ring-stone-200")}>
                    <f.icon className="h-4 w-4" aria-hidden="true" />
                  </span>
                  <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider", f.pro ? "bg-amber-100 text-amber-900" : "bg-stone-200/70 text-slate-600")}>
                    {f.pro ? "Abonnés" : "Gratuit"}
                  </span>
                </div>
                <h3 className="mt-4 text-sm font-semibold text-foreground">{f.title}</h3>
                <p className="mt-1.5 text-xs leading-5 text-muted-foreground">{f.text}</p>
              </div>
            ))}
          </div>
        </section>

        {/* ── Conversion après démonstration de valeur ────────────────────── */}
        <section className="relative overflow-hidden rounded-[2rem] bg-slate-950 px-6 py-10 text-white sm:px-10 sm:py-14" aria-labelledby="cta-pro-title">
          <div
            className="pointer-events-none absolute inset-0 bg-cover bg-center opacity-20"
            style={{ backgroundImage: "url(/img/cta.webp)" }}
            aria-hidden="true"
          />
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-r from-slate-950 via-slate-950/95 to-slate-950/70" aria-hidden="true" />
          <div className="absolute -right-20 -top-20 h-64 w-64 rounded-full bg-amber-500/10 blur-3xl" aria-hidden="true" />
          <div className="relative grid gap-8 lg:grid-cols-[1fr_auto] lg:items-end">
            <div>
              <div className="inline-flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-amber-300"><Crown className="h-3.5 w-3.5" aria-hidden="true" /> BlackTurf Pro</div>
              <h2 id="cta-pro-title" className="mt-4 max-w-2xl font-display text-3xl font-bold tracking-tight sm:text-4xl">Passez des résultats aux décisions.</h2>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300 sm:text-base">
                Retrouvez les analyses complètes, les probabilités et les plans de mise qui ont produit ce palmarès.
                7 jours d&apos;essai, sans carte bancaire. Les performances passées ne garantissent pas les résultats futurs.
              </p>
              <ul className="mt-6 grid gap-2 text-sm text-slate-200 sm:grid-cols-3">
                <li className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-emerald-300" aria-hidden="true" /> Pronostics complets</li>
                <li className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-emerald-300" aria-hidden="true" /> Plans de mise</li>
                <li className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-emerald-300" aria-hidden="true" /> Cotes en direct</li>
              </ul>
            </div>
            <div className="flex flex-col gap-3">
              <Button asChild variant="brand" size="lg" className="min-h-12 rounded-xl px-7 shadow-none">
                <Link href="/tarifs">Démarrer l&apos;essai gratuit <ArrowRight className="ml-1 h-4 w-4" /></Link>
              </Button>
              <p className="text-center text-[11px] text-slate-400">Standard 12€/mois · Expert 19€/mois · sans engagement</p>
            </div>
          </div>
        </section>

        {/* ── FAQ ──────────────────────────────────────────────────────── */}
        <section aria-label="Questions fréquentes" className="space-y-6">
          <SectionHeading
            eyebrow="Transparence"
            title="Les questions qu'on nous pose"
            description="Les réponses gênantes en premier — c'est à ça qu'on reconnaît un palmarès honnête."
            icon={ShieldCheck}
          />
          <div className="grid gap-3 lg:grid-cols-2">
            <Faq q="Est-ce que je vais gagner de l'argent ?">
              Personne ne peut vous le garantir, et nous ne le ferons pas. Cette page mesure la <strong>qualité de l&apos;analyse</strong> :
              à quelle fréquence le gagnant figure dans nos favoris, et à quel point nos probabilités sont calibrées.
              Le pari hippique reste soumis au prélèvement de l&apos;opérateur et au hasard : le risque de perte est réel.
            </Faq>
            <Faq q="Comment sont calculés ces chiffres ?">
              Chaque course pronostiquée est journalisée au moment de l&apos;analyse, <strong>avant le départ</strong>, puis confrontée à
              l&apos;arrivée officielle PMU. Une course n&apos;entre dans les statistiques que si son pronostic existait avant le départ —
              cela exclut mécaniquement toute reconstruction a posteriori.
              {g.nb_courses_rejouables ? ` Sur les ${nf(g.nb_courses_analysees)} courses mesurées, ${nf(g.nb_courses_rejouables)} sont en plus rejouables à l'identique (les données d'entrée sont figées et archivées).` : ""}
            </Faq>
            <Faq q="Pourquoi ne montrez-vous pas un ROI global ?">
              Parce qu&apos;un ROI dépend entièrement de la mise, du type de pari et du profil de risque : un chiffre unique
              n&apos;aurait aucun sens et servirait surtout à vendre. Nous affichons ce qui est vérifiable : les gains réellement
              encaissés, pari par pari, chacun consultable sur sa course.
            </Faq>
            <Faq q="« Précision Top-3 », qu'est-ce que ça veut dire exactement ?">
              La part des courses où le cheval qui a gagné figurait parmi nos trois premiers choix.
              {hasard3 != null && ` Sur ces mêmes courses — ${g.nb_partants_moyen ? `${nf(g.nb_partants_moyen, 1)} partants en moyenne` : "champ réel"} — un tirage au sort atteindrait ${nf(hasard3, 0)} %.`}
              {" "}Ce n&apos;est pas un taux de paris gagnants : un cheval placé ne fait pas gagner un pari Simple Gagnant.
            </Faq>
          </div>
        </section>

        <p className="mx-auto max-w-3xl border-t border-stone-200 pt-6 text-center text-[11px] leading-5 text-muted-foreground">
          Résultats réels, recalculés à chaque fin de course. Aucune donnée simulée hors des
          backtests explicitement étiquetés. Jouer comporte des risques : endettement, isolement, dépendance.
          Interdit aux mineurs. Appelez le 09 74 75 13 13 (appel non surtaxé).
        </p>
      </main>
    </div>
  );
}
