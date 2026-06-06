"use client";

import { useEffect, useState, useMemo, useCallback } from "react";
import { format, addDays, subDays, differenceInMinutes, differenceInSeconds } from "date-fns";
import { fr } from "date-fns/locale";
import {
  ChevronLeft, ChevronRight, Clock, MapPin, Trophy, Loader2, Zap,
  Search, X, Radio, ChevronDown, ChevronUp, Filter,
} from "lucide-react";
import Link from "next/link";
import useSWR from "swr";
import { coursesApi, predictionsApi } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { disciplineIcon, formatTime, cn } from "@/lib/utils";

/* ─── Types ─────────────────────────────────────────────── */
interface CourseSummary {
  course_id: string;
  nom: string | null;
  numero: number;
  date_heure: string;
  hippodrome_nom: string;
  discipline: string;
  distance: number;
  nb_partants: number;
  statut: string;
  est_quinte: boolean;
  est_quarte: boolean;
  est_tierce: boolean;
  penetrometre_coef: number | null;
  penetrometre_desc: string | null;
  pool_total_eur: number | null;
}
interface Reunion {
  reunion_id: string;
  hippodrome: string;
  numero: number;
  courses: CourseSummary[];
}

/* ─── Discipline chips config ───────────────────────────── */
const DISCIPLINES = ["Tous", "Plat", "Attelé", "Monté", "Haies", "Steeple", "Cross"] as const;
type DisciplineFilter = (typeof DISCIPLINES)[number];

/* ─── Countdown hook ────────────────────────────────────── */
function useCountdown(targetDate: string, statut: string) {
  const [text, setText] = useState<string | null>(null);

  useEffect(() => {
    if (statut !== "programme" && statut !== "a_venir") return;
    const tick = () => {
      const now = new Date();
      const target = new Date(targetDate);
      const diffSec = differenceInSeconds(target, now);
      if (diffSec <= 0) { setText(null); return; }
      const mins = differenceInMinutes(target, now);
      if (mins >= 60) { setText(null); return; }
      if (mins >= 1) setText(`dans ${mins} min`);
      else setText(`dans ${diffSec}s`);
    };
    tick();
    const id = setInterval(tick, 10000);
    return () => clearInterval(id);
  }, [targetDate, statut]);

  return text;
}

/* ─── StatutBadge ───────────────────────────────────────── */
function StatutBadge({ statut }: { statut: string }) {
  if (statut === "en_cours")
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-emerald-600 ring-1 ring-emerald-200">
        <Radio className="h-2.5 w-2.5 animate-pulse" />
        En direct
      </span>
    );
  if (statut === "termine")
    return (
      <span className="inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-[10px] text-gray-500">
        Terminée
      </span>
    );
  if (statut === "annule")
    return (
      <span className="inline-flex items-center rounded-full bg-red-50 px-2 py-0.5 text-[10px] text-red-500 ring-1 ring-red-200">
        Annulée
      </span>
    );
  return null;
}

/* ─── CourseRow ─────────────────────────────────────────── */
function CourseRow({ course, vbCount }: { course: CourseSummary; vbCount?: number }) {
  const isLive = course.statut === "en_cours";
  const isDone = course.statut === "termine" || course.statut === "annule";
  const countdown = useCountdown(course.date_heure, course.statut);

  return (
    <Link href={`/courses/${course.course_id}`} className="block group">
      <div
        className={cn(
          "relative flex items-center gap-3 px-4 py-3 transition-all duration-150",
          "hover:bg-gray-50/80 border-b border-gray-100 last:border-b-0",
          isLive && "bg-emerald-50/50 hover:bg-emerald-50",
          isDone && "opacity-60",
        )}
      >
        {/* Live pulse bar */}
        {isLive && (
          <span className="absolute left-0 top-1/2 -translate-y-1/2 h-8 w-0.5 rounded-full bg-emerald-500" />
        )}

        {/* Course number circle */}
        <div
          className={cn(
            "h-8 w-8 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 ring-1",
            course.est_quinte
              ? "bg-amber-50 text-amber-600 ring-amber-200"
              : isLive
              ? "bg-emerald-50 text-emerald-600 ring-emerald-200"
              : "bg-gray-100 text-gray-600 ring-gray-200",
          )}
        >
          {course.numero}
        </div>

        {/* Main info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span
              className={cn(
                "text-sm font-semibold truncate max-w-[200px] group-hover:text-gray-900",
                isDone ? "text-gray-400" : "text-gray-800",
              )}
            >
              {course.nom || `Course ${course.numero}`}
            </span>
            {course.est_quinte && (
              <span className="inline-flex items-center rounded-full bg-amber-50 px-1.5 py-0 text-[9px] font-bold text-amber-600 ring-1 ring-amber-200 uppercase tracking-wide">
                Quinté+
              </span>
            )}
            {course.est_quarte && !course.est_quinte && (
              <span className="inline-flex items-center rounded-full bg-amber-50 px-1.5 py-0 text-[9px] font-bold text-amber-600 ring-1 ring-amber-200 uppercase tracking-wide">
                Quarté+
              </span>
            )}
            {course.est_tierce && !course.est_quarte && (
              <span className="inline-flex items-center rounded-full bg-yellow-50 px-1.5 py-0 text-[9px] font-semibold text-yellow-600 ring-1 ring-yellow-200 uppercase tracking-wide">
                Tiercé
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 text-xs text-gray-400 mt-0.5 flex-wrap">
            <span>{disciplineIcon(course.discipline)} {course.discipline}</span>
            <span className="text-gray-200">·</span>
            <span>{course.distance}m</span>
            <span className="text-gray-200">·</span>
            <span>{course.nb_partants} partants</span>
            {course.penetrometre_coef != null && course.penetrometre_desc && (
              <>
                <span className="text-gray-200">·</span>
                <span className={cn(
                  "font-medium",
                  course.penetrometre_coef < 3.0 ? "text-amber-600" :
                  course.penetrometre_coef < 5.0 ? "text-green-600" :
                  course.penetrometre_coef < 7.0 ? "text-blue-600" : "text-indigo-600"
                )}>
                  🌿 {course.penetrometre_desc} {course.penetrometre_coef.toFixed(1)}
                </span>
              </>
            )}
            {course.pool_total_eur != null && course.pool_total_eur > 0 && (
              <>
                <span className="text-gray-200">·</span>
                <span className="text-violet-600 font-medium tabular-nums">
                  Cagnotte {course.pool_total_eur >= 1_000_000
                    ? `${(course.pool_total_eur / 1_000_000).toFixed(1)}M€`
                    : `${Math.round(course.pool_total_eur / 1_000)}k€`}
                </span>
              </>
            )}
          </div>
        </div>

        {/* Right: time + status + VB */}
        <div className="flex flex-col items-end gap-1 flex-shrink-0">
          <div className="flex items-center gap-1.5">
            {countdown && (
              <span className="text-[10px] font-medium text-amber-600 bg-amber-50 rounded-full px-1.5 py-0.5">
                {countdown}
              </span>
            )}
            <span className={cn("text-sm font-semibold tabular-nums", isLive ? "text-emerald-600" : "text-gray-700")}>
              {formatTime(course.date_heure)}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            {vbCount !== undefined && vbCount > 0 && (
              <span className="inline-flex items-center gap-0.5 rounded-full bg-amber-50 px-1.5 py-0.5 text-[10px] font-bold text-amber-600 ring-1 ring-amber-200">
                <Zap className="h-2.5 w-2.5" />
                {vbCount} <span className="hidden sm:inline">de valeur</span>
              </span>
            )}
            <StatutBadge statut={course.statut} />
          </div>
        </div>

        {/* Hover arrow */}
        <ChevronRight className="h-3.5 w-3.5 text-gray-300 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0" />
      </div>
    </Link>
  );
}

/* ─── ReunionCard ───────────────────────────────────────── */
function ReunionCard({
  reunion,
  vbByCourse,
  isPaid,
  disciplineFilter,
}: {
  reunion: Reunion;
  vbByCourse: Record<string, number>;
  isPaid: boolean;
  disciplineFilter: DisciplineFilter;
}) {
  const [collapsed, setCollapsed] = useState(false);

  const filteredCourses = useMemo(
    () =>
      disciplineFilter === "Tous"
        ? reunion.courses
        : reunion.courses.filter((c) => c.discipline === disciplineFilter),
    [reunion.courses, disciplineFilter],
  );

  if (filteredCourses.length === 0) return null;

  const hasQuinte = filteredCourses.some((c) => c.est_quinte);
  const reunionVbs = filteredCourses.reduce((sum, c) => sum + (vbByCourse[c.course_id] || 0), 0);
  const liveCount = filteredCourses.filter((c) => c.statut === "en_cours").length;
  const firstTime = filteredCourses[0]?.date_heure;
  const lastTime = filteredCourses[filteredCourses.length - 1]?.date_heure;

  // Pénétromètre de la réunion (même valeur pour toutes les courses)
  const penetro = filteredCourses.find((c) => c.penetrometre_coef != null);
  const penetroCoef = penetro?.penetrometre_coef ?? null;
  const penetroDesc = penetro?.penetrometre_desc ?? null;

  // Discipline breakdown for this reunion
  const discBreakdown = filteredCourses.reduce((acc, c) => {
    acc[c.discipline] = (acc[c.discipline] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);

  return (
    <div
      className={cn(
        "rounded-2xl border bg-white shadow-sm overflow-hidden",
        hasQuinte ? "border-amber-200" : "border-gray-200",
      )}
    >
      {/* Header */}
      <button
        onClick={() => setCollapsed((v) => !v)}
        className={cn(
          "w-full flex items-center gap-3 px-5 py-4 text-left transition-colors",
          hasQuinte ? "bg-gradient-to-r from-amber-50/80 to-white hover:from-amber-100/60" : "hover:bg-gray-50/70",
        )}
      >
        {/* Gold accent for Quinté reunion */}
        {hasQuinte && (
          <span className="h-full absolute left-0 top-0 bottom-0 w-1 rounded-l-2xl bg-gradient-to-b from-amber-400 to-amber-500" />
        )}

        {/* Hippodrome icon */}
        <div
          className={cn(
            "h-9 w-9 rounded-xl flex items-center justify-center flex-shrink-0 text-base",
            hasQuinte ? "bg-amber-100 text-amber-600" : "bg-gray-100 text-gray-500",
          )}
        >
          <MapPin className="h-4 w-4" />
        </div>

        {/* Info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h2 className="font-bold text-gray-900 text-sm">{reunion.hippodrome}</h2>
            {hasQuinte && (
              <span className="inline-flex items-center rounded-full bg-amber-100 px-1.5 py-0 text-[9px] font-bold text-amber-700 uppercase tracking-wide">
                Quinté+
              </span>
            )}
            {liveCount > 0 && (
              <span className="inline-flex items-center gap-0.5 rounded-full bg-emerald-100 px-1.5 py-0 text-[9px] font-bold uppercase tracking-wide text-emerald-700">
                <Radio className="h-2 w-2 animate-pulse" />
                En direct
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 text-xs text-gray-400 mt-0.5 flex-wrap">
            <span>R{reunion.numero}</span>
            <span className="text-gray-200">·</span>
            <span>{filteredCourses.length} courses</span>
            {firstTime && (
              <>
                <span className="text-gray-200">·</span>
                <span className="flex items-center gap-0.5">
                  <Clock className="h-2.5 w-2.5" />
                  {formatTime(firstTime)}
                  {lastTime !== firstTime && ` → ${formatTime(lastTime)}`}
                </span>
              </>
            )}
            {Object.entries(discBreakdown).map(([disc, n]) => (
              <span key={disc} className="hidden sm:inline text-gray-300">
                · {disciplineIcon(disc)} {n}
              </span>
            ))}
            {/* Pénétromètre de la réunion */}
            {penetroCoef != null && penetroDesc && (
              <span className={cn(
                "font-semibold",
                penetroCoef < 3.0 ? "text-amber-600" :
                penetroCoef < 5.0 ? "text-green-600" :
                penetroCoef < 7.0 ? "text-blue-600" : "text-indigo-600"
              )}>
                · 🌿 {penetroDesc} ({penetroCoef.toFixed(1)})
              </span>
            )}
          </div>
        </div>

        {/* VB count */}
        {isPaid && reunionVbs > 0 && (
          <span className="inline-flex items-center gap-0.5 text-xs font-bold text-amber-600 bg-amber-50 rounded-full px-2 py-1 ring-1 ring-amber-200 flex-shrink-0">
            <Zap className="h-3 w-3" />
            {reunionVbs}
          </span>
        )}

        {collapsed ? (
          <ChevronDown className="h-4 w-4 text-gray-400 flex-shrink-0" />
        ) : (
          <ChevronUp className="h-4 w-4 text-gray-400 flex-shrink-0" />
        )}
      </button>

      {/* Courses list */}
      {!collapsed && (
        <div className="divide-y divide-gray-50">
          {filteredCourses.map((course) => (
            <CourseRow
              key={course.course_id}
              course={course}
              vbCount={isPaid ? vbByCourse[course.course_id] : undefined}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/* ─── Page ──────────────────────────────────────────────── */
export default function ProgrammePage() {
  const { user } = useAuth();
  const [selectedDate, setSelectedDate] = useState(new Date());
  const [programme, setProgramme] = useState<{ reunions: Reunion[]; nb_courses: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [discFilter, setDiscFilter] = useState<DisciplineFilter>("Tous");
  const [hippoSearch, setHippoSearch] = useState("");
  const [showSearch, setShowSearch] = useState(false);
  const [vbOnly, setVbOnly] = useState(false);

  const isToday = format(selectedDate, "yyyy-MM-dd") === format(new Date(), "yyyy-MM-dd");
  const isPaid = user && !["free", "decouverte"].includes(user.plan);

  /* Value bets */
  const { data: valueBets } = useSWR(
    isPaid && isToday ? "/value-bets-programme" : null,
    () => predictionsApi.valueBets(1).then((r) => r.data),
    { refreshInterval: 120000 },
  );

  const vbByCourse = useMemo(() => {
    if (!valueBets) return {} as Record<string, number>;
    return (valueBets as Array<{ course_id: string }>).reduce((acc, vb) => {
      acc[vb.course_id] = (acc[vb.course_id] || 0) + 1;
      return acc;
    }, {} as Record<string, number>);
  }, [valueBets]);

  /* Fetch programme */
  useEffect(() => {
    setLoading(true);
    const dateStr = format(selectedDate, "yyyy-MM-dd");
    coursesApi
      .programme(dateStr)
      .then((res) => setProgramme(res.data))
      .catch(() => setProgramme({ reunions: [], nb_courses: 0 }))
      .finally(() => setLoading(false));
  }, [selectedDate]);

  /* Navigate date */
  const goDate = useCallback(
    (d: number) => {
      setDiscFilter("Tous");
      setHippoSearch("");
      setVbOnly(false);
      setSelectedDate(d > 0 ? addDays(selectedDate, d) : subDays(selectedDate, -d));
    },
    [selectedDate],
  );

  /* Derived stats */
  const allCourses = useMemo(() => programme?.reunions.flatMap((r) => r.courses) ?? [], [programme]);
  const totalVbs = Object.values(vbByCourse).reduce((a, b) => a + b, 0);
  const liveCount = allCourses.filter((c) => c.statut === "en_cours").length;

  const discCounts = useMemo(
    () =>
      allCourses.reduce((acc, c) => {
        acc[c.discipline] = (acc[c.discipline] || 0) + 1;
        return acc;
      }, {} as Record<string, number>),
    [allCourses],
  );

  /* Filter reunions */
  const filteredReunions = useMemo(() => {
    if (!programme) return [];
    return programme.reunions.filter((r) => {
      if (hippoSearch && !r.hippodrome.toLowerCase().includes(hippoSearch.toLowerCase())) return false;
      if (discFilter !== "Tous" && !r.courses.some((c) => c.discipline === discFilter)) return false;
      // VB-only: garder uniquement les réunions avec au moins 1 value bet
      if (vbOnly && isPaid && !r.courses.some((c) => (vbByCourse[c.course_id] || 0) > 0)) return false;
      return true;
    });
  }, [programme, hippoSearch, discFilter, vbOnly, isPaid, vbByCourse]);

  const dateLabel = format(selectedDate, "EEEE d MMMM yyyy", { locale: fr });

  return (
    <div className="mx-auto max-w-4xl px-4 sm:px-6 lg:px-8 py-8 space-y-6">

      {/* ── Header ── */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">Programme</h1>
          <p className="text-sm text-gray-500 capitalize mt-0.5">{dateLabel}</p>
        </div>

        {/* Date nav */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => goDate(-1)}
            className="h-9 w-9 rounded-xl border border-gray-200 flex items-center justify-center text-gray-500 hover:bg-gray-50 hover:border-gray-300 transition-all"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <button
            onClick={() => { setSelectedDate(new Date()); setDiscFilter("Tous"); setHippoSearch(""); }}
            className={cn(
              "h-9 px-4 rounded-xl text-sm font-semibold transition-all",
              isToday
                ? "bg-amber-500 text-white shadow-sm shadow-amber-200"
                : "border border-gray-200 text-gray-600 hover:bg-gray-50",
            )}
          >
            Aujourd&apos;hui
          </button>
          <button
            onClick={() => goDate(1)}
            className="h-9 w-9 rounded-xl border border-gray-200 flex items-center justify-center text-gray-500 hover:bg-gray-50 hover:border-gray-300 transition-all"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* ── Stats bar ── */}
      {programme && programme.nb_courses > 0 && (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-3 rounded-2xl bg-gray-50 border border-gray-200 text-sm">
          <span className="font-semibold text-gray-700">{programme.nb_courses} courses</span>
          <span className="text-gray-300">|</span>
          <span className="text-gray-500">{programme.reunions.length} réunions</span>

          {liveCount > 0 && (
            <>
              <span className="text-gray-300">|</span>
              <span className="flex items-center gap-1 font-semibold text-emerald-600">
                <Radio className="h-3 w-3 animate-pulse" />
                {liveCount} en cours
              </span>
            </>
          )}

          {Object.entries(discCounts).map(([disc, n]) => (
            <span key={disc} className="text-gray-400 text-xs">
              {disciplineIcon(disc)} {n} {disc}
            </span>
          ))}

          {isPaid && totalVbs > 0 ? (
            <span className="ml-auto flex items-center gap-1 text-xs font-bold text-amber-600 tabular-nums">
              <Zap className="h-3 w-3" />
              {totalVbs} pari{totalVbs > 1 ? "s" : ""} de valeur
            </span>
          ) : !isPaid && isToday ? (
            <Link
              href="/tarifs"
              className="ml-auto flex items-center gap-1 text-xs font-semibold text-amber-600 hover:underline"
            >
              <Zap className="h-3 w-3" /> Débloquer les paris de valeur
            </Link>
          ) : null}
        </div>
      )}

      {/* ── Filters ── */}
      {programme && programme.nb_courses > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          {/* Discipline chips */}
          <div className="flex items-center gap-1 flex-wrap flex-1">
            {DISCIPLINES.map((d) => {
              const count = d === "Tous" ? allCourses.length : (discCounts[d] ?? 0);
              if (d !== "Tous" && count === 0) return null;
              return (
                <button
                  key={d}
                  onClick={() => setDiscFilter(d)}
                  className={cn(
                    "inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium transition-all",
                    discFilter === d
                      ? "bg-gray-900 text-white shadow-sm"
                      : "bg-gray-100 text-gray-600 hover:bg-gray-200",
                  )}
                >
                  {d !== "Tous" && disciplineIcon(d)}
                  {d}
                  {count > 0 && (
                    <span
                      className={cn(
                        "rounded-full px-1 text-[10px] font-bold",
                        discFilter === d ? "bg-white/20 text-white" : "bg-gray-200 text-gray-500",
                      )}
                    >
                      {count}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {/* VB only toggle — paid users + today only */}
          {isPaid && isToday && totalVbs > 0 && (
            <button
              onClick={() => setVbOnly((v) => !v)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold transition-all",
                vbOnly
                  ? "bg-amber-500 text-white shadow-sm shadow-amber-200"
                  : "bg-amber-50 text-amber-700 border border-amber-200 hover:bg-amber-100",
              )}
            >
              <Zap className="h-3 w-3" />
              Paris de valeur
            </button>
          )}

          {/* Search toggle */}
          <button
            onClick={() => { setShowSearch((v) => !v); if (showSearch) setHippoSearch(""); }}
            className={cn(
              "h-8 w-8 rounded-full flex items-center justify-center transition-all",
              showSearch || hippoSearch
                ? "bg-gray-900 text-white"
                : "bg-gray-100 text-gray-500 hover:bg-gray-200",
            )}
          >
            {hippoSearch ? <X className="h-3.5 w-3.5" /> : <Search className="h-3.5 w-3.5" />}
          </button>
        </div>
      )}

      {/* Search input */}
      {showSearch && (
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <input
            autoFocus
            value={hippoSearch}
            onChange={(e) => setHippoSearch(e.target.value)}
            placeholder="Rechercher un hippodrome..."
            className="w-full rounded-xl border border-gray-200 bg-white pl-9 pr-4 py-2.5 text-sm outline-none focus:border-amber-400 focus:ring-2 focus:ring-amber-100 transition-all"
          />
          {hippoSearch && (
            <button onClick={() => setHippoSearch("")} className="absolute right-3 top-1/2 -translate-y-1/2">
              <X className="h-3.5 w-3.5 text-gray-400" />
            </button>
          )}
        </div>
      )}

      {/* ── Content ── */}
      {loading ? (
        <div className="flex flex-col items-center justify-center py-24 gap-3">
          <Loader2 className="h-8 w-8 animate-spin text-gray-300" />
          <p className="text-sm text-gray-400">Chargement du programme…</p>
        </div>
      ) : !programme || programme.nb_courses === 0 ? (
        <div className="flex flex-col items-center justify-center py-24 gap-3">
          <div className="h-16 w-16 rounded-2xl bg-gray-100 flex items-center justify-center">
            <Trophy className="h-7 w-7 text-gray-300" />
          </div>
          <p className="font-semibold text-gray-600">Aucune course programmée</p>
          <p className="text-sm text-gray-400">Essayez une autre date</p>
          <button
            onClick={() => setSelectedDate(new Date())}
            className="mt-1 text-sm text-amber-600 font-medium hover:underline"
          >
            Revenir à aujourd&apos;hui
          </button>
        </div>
      ) : filteredReunions.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 gap-2">
          <Filter className="h-8 w-8 text-gray-300" />
          <p className="text-sm text-gray-500">Aucune réunion ne correspond aux filtres</p>
          <button
            onClick={() => { setDiscFilter("Tous"); setHippoSearch(""); }}
            className="text-sm text-amber-600 font-medium hover:underline"
          >
            Effacer les filtres
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {filteredReunions.map((reunion) => (
            <ReunionCard
              key={reunion.reunion_id}
              reunion={reunion}
              vbByCourse={vbByCourse}
              isPaid={!!isPaid}
              disciplineFilter={discFilter}
            />
          ))}
        </div>
      )}

      {/* ── Upsell strip for free users ── */}
      {!isPaid && isToday && programme && programme.nb_courses > 0 && (
        <div className="flex items-center justify-between gap-4 rounded-2xl bg-gradient-to-r from-amber-50 to-orange-50 border border-amber-200 px-5 py-4">
          <div>
            <p className="text-sm font-semibold text-amber-800">🔐 Paris de valeur non accessibles</p>
            <p className="text-xs text-amber-600 mt-0.5">
              Passez Standard pour voir les opportunités détectées par l&apos;IA sur chaque course.
            </p>
          </div>
          <Link
            href="/tarifs"
            className="flex-shrink-0 rounded-xl bg-amber-500 hover:bg-amber-600 text-white text-sm font-semibold px-4 py-2 transition-colors shadow-sm shadow-amber-200"
          >
            Voir les offres
          </Link>
        </div>
      )}
    </div>
  );
}
