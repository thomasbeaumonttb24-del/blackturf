"use client";

/**
 * Programme — refonte visuelle (vue chronologique).
 *
 * Drop-in : remplace src/app/(main)/programme/page.tsx
 * Conserve toute la logique de données existante (coursesApi.programme, value bets SWR,
 * useAuth, countdown, filtres). Seule la présentation change.
 *
 * ⚠ ASSETS À COPIER dans le dossier /public :
 *   public/img/logo-horse.png
 *   public/img/disciplines/attele-v7.png
 *   public/img/disciplines/plat-v7.png
 *   public/img/disciplines/monte-v7.png
 *   public/img/disciplines/obstacle-v7.png
 * (fournis dans ce même paquet, sous /public)
 */

import { useEffect, useState, useMemo, useCallback, useRef } from "react";
import { format, addDays, differenceInMinutes, differenceInSeconds } from "date-fns";
import { fr } from "date-fns/locale";
import {
  ChevronRight, Trophy, Loader2, Zap, Search, X, Radio, Filter,
} from "lucide-react";
import Link from "next/link";
import useSWR from "swr";
import { coursesApi, predictionsApi } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import { formatTime, cn } from "@/lib/utils";
import { jourParis } from "@/lib/seo";

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

/* ─── Helpers ───────────────────────────────────────────── */
const titleCase = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() : s);

const cap = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

const enjeux = (v: number | null) => {
  if (v == null || v <= 0) return null;
  return v >= 1_000_000 ? `${(v / 1_000_000).toFixed(1)}M€` : `${Math.round(v / 1_000)}k€`;
};

/* ─── Palette des disciplines (couleur + silhouette détourée) ── */
type DiscMeta = { color: string; bg: string; ring: string; mask: string };
const DISC_FALLBACK: DiscMeta = { color: "#6B7280", bg: "#F3F4F6", ring: "#E5E7EB", mask: "plat-v7.png" };

function discMeta(discipline: string): DiscMeta {
  const d = (discipline || "").toLowerCase();
  if (d.includes("attel")) return { color: "#0E7C66", bg: "#ECFDF5", ring: "#B7E4D3", mask: "attele-v7.png" };
  if (d.includes("plat")) return { color: "#B45309", bg: "#FEF6E7", ring: "#F5DCA8", mask: "plat-v7.png" };
  if (d.includes("mont")) return { color: "#2A5BD7", bg: "#EEF3FF", ring: "#C5D6FB", mask: "monte-v7.png" };
  if (d.includes("haie")) return { color: "#C1502A", bg: "#FDF1EA", ring: "#F3CDB8", mask: "obstacle-v7.png" };
  if (d.includes("steeple") || d.includes("cross")) return { color: "#A32C3E", bg: "#FCEEF0", ring: "#F0C9CF", mask: "obstacle-v7.png" };
  return DISC_FALLBACK;
}

/* Icône discipline : silhouette détourée, teintée (fond transparent) */
function DiscIcon({ discipline, w = 46, h = 30, color }: { discipline: string; w?: number; h?: number; color?: string }) {
  const m = discMeta(discipline);
  const url = `/img/disciplines/${m.mask}`;
  return (
    <span
      aria-hidden
      style={{
        display: "inline-block",
        width: w,
        height: h,
        background: color ?? m.color,
        WebkitMaskImage: `url(${url})`,
        maskImage: `url(${url})`,
        WebkitMaskRepeat: "no-repeat",
        maskRepeat: "no-repeat",
        WebkitMaskPosition: "center",
        maskPosition: "center",
        WebkitMaskSize: "contain",
        maskSize: "contain",
      }}
    />
  );
}

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
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-emerald-700 ring-1 ring-emerald-200 whitespace-nowrap">
        <Radio className="h-2.5 w-2.5 animate-pulse" /> En direct
      </span>
    );
  if (statut === "termine")
    return <span className="inline-flex items-center rounded-full bg-white px-2 py-0.5 text-[10px] font-semibold text-gray-600 ring-1 ring-gray-200">Terminée</span>;
  if (statut === "annule")
    return <span className="inline-flex items-center rounded-full bg-red-50 px-2 py-0.5 text-[10px] text-red-700 ring-1 ring-red-200">Annulée</span>;
  return null;
}

/* ─── Sélecteur de jour ─────────────────────────────────── */
const HIDE_SCROLLBAR = "[scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden";

function DayStrip({ selected, onSelect }: { selected: Date; onSelect: (d: Date) => void }) {
  // Jour de Paris, identique au serveur et au navigateur → pas de mismatch d’hydratation
  const today = new Date(`${jourParis()}T12:00:00`);
  const days = Array.from({ length: 10 }, (_, i) => addDays(today, i - 9));
  const selKey = format(selected, "yyyy-MM-dd");
  const todayKey = format(today, "yyyy-MM-dd");
  const yesterdayKey = format(addDays(today, -1), "yyyy-MM-dd");
  const scrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollLeft = el.scrollWidth;
  }, []);
  return (
    <div ref={scrollRef} className={cn("flex gap-2 overflow-x-auto -mx-4 px-4 sm:mx-0 sm:px-0 pb-0.5", HIDE_SCROLLBAR)}>
      {days.map((d) => {
        const key = format(d, "yyyy-MM-dd");
        const isSel = key === selKey;
        const isToday = key === todayKey;
        const topLabel = isToday ? "Auj." : key === yesterdayKey ? "Hier" : format(d, "EEE", { locale: fr });
        return (
          <button
            key={key}
            onClick={() => onSelect(d)}
            className={cn(
              "group flex flex-col items-center justify-center rounded-2xl px-3.5 py-2.5 min-w-[58px] shrink-0 border transition-all hover:-translate-y-0.5",
              isSel
                ? "bg-gray-900 text-white border-gray-900 shadow-md shadow-gray-900/10"
                : isToday
                ? "bg-white text-gray-800 border-amber-300 ring-1 ring-amber-200 hover:border-amber-400"
                : "bg-white text-gray-700 border-gray-200 hover:border-gray-300 hover:bg-gray-50",
            )}
          >
            <span className={cn("text-[10px] font-bold uppercase tracking-wide leading-none", isSel ? "text-white/70" : isToday ? "text-amber-700" : "text-gray-600")}>
              {topLabel}
            </span>
            <span className="text-xl font-extrabold tabular-nums leading-none mt-1.5" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>{format(d, "d")}</span>
            <span className={cn("text-[9px] uppercase tracking-wide leading-none mt-1", isSel ? "text-white/50" : "text-gray-600")}>
              {format(d, "MMM", { locale: fr })}
            </span>
          </button>
        );
      })}
    </div>
  );
}

/* ─── Bandeau "Prochaine course" ────────────────────────── */
function NextRaceBanner({ item }: { item: { course: CourseSummary; reunionNum: number } }) {
  const { course, reunionNum } = item;
  const m = discMeta(course.discipline);
  const isLive = course.statut === "en_cours";
  const countdown = useCountdown(course.date_heure, course.statut);
  const url = `/img/disciplines/${m.mask}`;
  return (
    <div
      className="relative overflow-hidden rounded-[22px] animate-[fadeUp_.5s_cubic-bezier(.16,1,.3,1)_both]"
      style={{ border: "1px solid rgba(255,255,255,.08)", background: "linear-gradient(135deg,#0F1520 0%,#1A2230 100%)", boxShadow: "0 18px 40px -24px rgba(15,21,32,.7)" }}
    >
      <span className="absolute left-0 top-0 h-full w-[3px]" style={{ background: "linear-gradient(180deg,#F59E0B,#D97706)" }} />
      <span
        aria-hidden
        className="pointer-events-none absolute max-[767px]:hidden"
        style={{
          // la silhouette reste entièrement dans la carte : aucun sabot rogné par l'overflow
          right: 200, bottom: 10, width: 300, height: 132, background: "rgba(255,255,255,.07)",
          WebkitMaskImage: `url(${url})`, maskImage: `url(${url})`,
          WebkitMaskRepeat: "no-repeat", maskRepeat: "no-repeat",
          WebkitMaskPosition: "center", maskPosition: "center",
          WebkitMaskSize: "contain", maskSize: "contain",
        }}
      />
      <div className="relative flex flex-wrap items-center gap-4 px-4 py-4 sm:gap-5 sm:px-6 sm:py-5">
        <div className="flex-1 min-w-[230px]">
          <div className="flex items-center gap-2.5 mb-3">
            <span className="text-[10.5px] font-bold uppercase tracking-[.16em] text-slate-600">Prochaine course</span>
            <span className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide" style={{ color: "#FCD34D", background: "rgba(245,158,11,.12)", border: "1px solid rgba(245,158,11,.28)" }}>
              <span className="h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse" />
              {isLive ? "En piste" : "À venir"}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-2.5">
            <span className="rounded-md px-2 py-0.5 text-[12px] font-bold tabular-nums" style={{ fontFamily: "'Space Grotesk', sans-serif", color: "#0F1520", background: "#E2E8F0" }}>
              R{reunionNum}C{course.numero}
            </span>
            <span className="text-lg sm:text-[22px] font-bold text-white tracking-tight" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>{course.hippodrome_nom}</span>
          </div>
          {course.nom && <div className="mt-1.5 text-sm font-medium text-slate-300">{course.nom}</div>}
          <div className="mt-4 flex flex-wrap gap-2">
            {[titleCase(course.discipline), `${course.distance} m`, `${course.nb_partants} partants`].map((t) => (
              <span key={t} className="inline-flex items-center rounded-lg px-3 py-1.5 text-[12px] font-semibold text-slate-200" style={{ background: "rgba(255,255,255,.06)", border: "1px solid rgba(255,255,255,.1)" }}>{t}</span>
            ))}
          </div>
        </div>
        <div className="flex w-full flex-row items-end justify-between gap-3.5 border-t border-white/10 pt-4 sm:w-auto sm:flex-col sm:items-end sm:border-t-0 sm:border-l sm:border-white/10 sm:pt-0 sm:pl-6">
          <div className="text-left sm:text-right">
            <div className="text-[10px] font-bold uppercase tracking-[.16em] text-slate-600">Départ</div>
            <div className="mt-1 text-[26px] sm:text-[30px] font-bold leading-none tracking-tight text-white tabular-nums" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>{formatTime(course.date_heure)}</div>
            {countdown && (
              <div className="mt-2 inline-block rounded-full px-2.5 py-0.5 text-[11px] font-bold" style={{ color: "#FCD34D", background: "rgba(245,158,11,.12)", border: "1px solid rgba(245,158,11,.28)" }}>{countdown}</div>
            )}
          </div>
          <Link
            href={`/courses/${course.course_id}`}
            className="inline-flex items-center gap-1.5 rounded-xl px-4 py-2.5 text-[13px] font-bold transition-transform hover:-translate-y-0.5"
            style={{ background: "linear-gradient(135deg,#F59E0B,#D97706)", color: "#0F1520", boxShadow: "0 8px 22px -10px rgba(245,158,11,.6)" }}
          >
            Voir la course <ChevronRight className="h-4 w-4" />
          </Link>
        </div>
      </div>
    </div>
  );
}

/* ─── Bandeau value bets actifs (funnel Free, décision 2026-08-16) ─────────
   Compteur AGRÉGÉ honnête (vrai COUNT(*) côté backend, endpoint public/léger
   /value-bets/compteur) — jamais le détail (cheval/course/cote) d'un value bet
   à un compte non abonné. Visible tant que l'utilisateur n'est pas déjà payant
   (free/decouverte ou visiteur non connecté) : donne un signal de ce qui se
   joue EN CE MOMENT sans casser le paywall. */
function ValueBetsCompteurBanner({ initial }: { initial?: { count: number; niveau_min: number } | null }) {
  const { data } = useSWR(
    "/value-bets-compteur-banner",
    () => predictionsApi.valueBetsCompteur(3).then((r) => r.data as { count: number; niveau_min: number }),
    // `fallbackData` : le compteur est désormais résolu côté serveur et arrive dans le
    // HTML. Sans lui, le bandeau restait absent jusqu'à l'aller-retour réseau, s'insérait
    // en haut de page et devenait l'élément LCP — mesuré à 4,0 s sur mobile pour un
    // premier rendu à 1,2 s. SWR le rafraîchit ensuite toutes les minutes.
    { refreshInterval: 60000, fallbackData: initial ?? undefined },
  );
  if (!data || !data.count) return null;
  return (
    <Link
      href="/tarifs"
      className="relative flex flex-wrap items-center justify-between gap-3 overflow-hidden rounded-2xl px-4 py-3.5 transition-transform hover:-translate-y-0.5 sm:px-5 sm:py-4"
      style={{ border: "1px solid rgba(16,185,129,.28)", background: "linear-gradient(135deg,rgba(16,185,129,.08),rgba(255,255,255,.92))" }}
    >
      <div className="flex items-center gap-2.5">
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
        </span>
        <p className="text-[13.5px] font-semibold text-gray-800">
          <span className="tabular-nums text-[15px] font-bold text-emerald-700">{data.count}</span>{" "}
          {data.count > 1 ? "paris de valeur" : "pari de valeur"} ★★★+ actif{data.count > 1 ? "s" : ""} maintenant
        </p>
      </div>
      <span
        className="inline-flex flex-shrink-0 items-center gap-1 rounded-lg px-3 py-1.5 text-[12.5px] font-bold text-white shadow-sm"
        style={{ background: "linear-gradient(135deg,#10B981,#059669)" }}
      >
        Visibles dès Standard <ChevronRight className="h-3.5 w-3.5" />
      </span>
    </Link>
  );
}

/* ─── Ligne de course (timeline) ────────────────────────── */
interface ApercuCourse {
  analysee: boolean;
  nb_notes: number;
  nb_ecartes: number;
  confiance: number | null;
  accord_marche: boolean | null;
}

function TimelineRow({ course, reunionNum, vbCount, apercu, delay, targetId }: { course: CourseSummary; reunionNum: number; vbCount?: number; apercu?: ApercuCourse; delay: number; targetId?: string }) {
  const m = discMeta(course.discipline);
  const isLive = course.statut === "en_cours";
  const isDone = course.statut === "termine" || course.statut === "annule";
  const countdown = useCountdown(course.date_heure, course.statut);
  const codeCls = isDone
    ? "text-gray-600 bg-gray-100/70 ring-gray-200"
    : course.est_quinte
    ? "text-amber-700 bg-amber-50 ring-amber-200"
    : isLive ? "text-emerald-700 bg-emerald-50 ring-emerald-200" : "text-gray-700 bg-gray-100 ring-gray-200";
  return (
    <Link
      href={`/courses/${course.course_id}`}
      id={targetId}
      className={cn(
        "group relative flex scroll-mt-28 items-center gap-2.5 rounded-2xl border px-3 py-2.5 no-underline transition-all duration-200 sm:gap-3 sm:px-4 sm:py-3",
        isDone
          ? "border-[#E9E6DC] hover:border-gray-300"
          : "border-[#ECE7DC] shadow-[0_1px_2px_rgba(0,0,0,.03)] hover:-translate-y-0.5 hover:border-amber-300 hover:shadow-[0_16px_32px_-14px_rgba(180,83,9,.28)]",
      )}
      style={{ background: isLive ? "#F0FDF8" : isDone ? "#F5F4EF" : "#FFFFFF", animation: `fadeUp .5s cubic-bezier(.16,1,.3,1) ${delay}s both` }}
    >
      <span className="absolute left-0 top-0 bottom-0 w-[3px] rounded-l-2xl" style={{ background: isLive ? "#10B981" : !isDone && course.est_quinte ? "#F59E0B" : "transparent" }} />
      <div className="flex w-10 flex-shrink-0 flex-col items-center sm:w-11">
        <span className={cn("text-base font-bold leading-none tabular-nums", isLive ? "text-emerald-700" : isDone ? "text-gray-600 line-through decoration-gray-300" : "text-gray-900")} style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
          {formatTime(course.date_heure)}
        </span>
        {countdown && <span className="mt-1 text-center text-[9px] font-bold leading-tight text-amber-700">{countdown}</span>}
      </div>
      {/* La pastille garde la couleur de la discipline même course finie : en gris
          délavé (1,8:1 de contraste) jambes et driver se noyaient dans le fond et
          le cheval paraissait amputé. L'heure barrée et le badge « Terminée »
          suffisent à marquer le passé. */}
      <span className="hidden h-[42px] w-[50px] flex-shrink-0 items-center justify-center rounded-xl min-[400px]:flex" style={{ background: m.bg, border: `1px solid ${m.ring}` }}>
        <DiscIcon discipline={course.discipline} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className={cn("inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-bold tabular-nums ring-1", codeCls)} style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
            R{reunionNum}C{course.numero}
          </span>
          <span className={cn("max-w-full truncate text-sm font-semibold sm:max-w-[230px]", isDone ? "text-gray-600" : "text-gray-800")}>
            <span className="text-gray-600">{course.hippodrome_nom}</span>
            <span className="text-gray-300"> · </span>
            {course.nom || `Course ${course.numero}`}
          </span>
          {course.est_quinte ? (
            <span className="rounded-full border border-amber-200 bg-amber-50 px-1.5 text-[9px] font-bold uppercase tracking-wide text-amber-700">Quinté+</span>
          ) : course.est_quarte ? (
            <span className="rounded-full border border-amber-200 bg-amber-50 px-1.5 text-[9px] font-bold uppercase tracking-wide text-amber-700">Quarté+</span>
          ) : course.est_tierce ? (
            <span className="rounded-full border border-yellow-200 bg-yellow-50 px-1.5 text-[9px] font-bold uppercase tracking-wide text-yellow-700">Tiercé</span>
          ) : null}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-gray-600">
          <span className="font-semibold" style={{ color: m.color }}>{titleCase(course.discipline)}</span>
          <span className="text-gray-300">·</span><span>{course.distance} m</span>
          <span className="text-gray-300">·</span><span>{course.nb_partants} partants</span>
          {enjeux(course.pool_total_eur) && (<><span className="text-gray-300">·</span><span className="font-medium text-gray-600 tabular-nums">Enjeux {enjeux(course.pool_total_eur)}</span></>)}
        </div>
        {/* Ce que le modèle dit de CETTE course. Rien d'identifiant : une
            confiance, et le fait qu'il suive ou non le favori des parieurs.
            Pas de pastille « Analysée » : toutes les courses le sont, elle
            n'apprenait rien et volait la place des deux chiffres qui varient. */}
        {apercu?.analysee && (
          <div className="mt-1.5 hidden flex-wrap items-center gap-1.5 sm:flex">
            {apercu.confiance != null && (
              <span className="rounded-full border border-gray-200 bg-white px-2 py-0.5 text-[10px] font-semibold text-gray-600 tabular-nums">
                confiance {apercu.confiance}/100
              </span>
            )}
            {apercu.accord_marche === false && (
              <span
                title="Le n°1 du modèle n'est pas le favori des parieurs sur cette course"
                className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700"
              >
                ne suit pas le marché
              </span>
            )}
          </div>
        )}
      </div>
      <div className="flex flex-shrink-0 items-center gap-1.5">
        {vbCount !== undefined && vbCount > 0 && (
          <span className="inline-flex items-center gap-0.5 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-bold text-amber-700 tabular-nums">
            <Zap className="h-2.5 w-2.5" />{vbCount}
          </span>
        )}
        <StatutBadge statut={course.statut} />
        <ChevronRight className="hidden h-3.5 w-3.5 flex-shrink-0 text-gray-300 sm:block" />
      </div>
    </Link>
  );
}

/* ─── Page ──────────────────────────────────────────────── */
/**
 * `initialProgramme` / `initialJour` viennent du composant serveur (page.tsx) : ils
 * permettent au premier rendu — celui que voit le robot d'indexation — de contenir déjà
 * le programme complet. Sans eux, le programme n'arrivait qu'après un useEffect côté
 * navigateur : Googlebot ne recevait qu'un squelette vide et la page ne pouvait ranker
 * sur aucune requête « programme PMU / courses du jour ».
 */
export default function ProgrammeClient({
  initialProgramme = null,
  initialJour,
  initialCompteurVB = null,
}: {
  initialProgramme?: { reunions: Reunion[]; nb_courses: number } | null;
  initialJour: string; // "YYYY-MM-DD", jour de Paris calculé côté serveur
  initialCompteurVB?: { count: number; niveau_min: number } | null;
} ) {
  const { user } = useAuth();
  const [selectedDate, setSelectedDate] = useState(() => new Date(`${initialJour}T12:00:00`));
  const [programme, setProgramme] = useState<{ reunions: Reunion[]; nb_courses: number } | null>(initialProgramme);
  // Jour auquel correspond `programme` (ref, pas état : lu dans l'effet de chargement,
  // une valeur figée dans la fermeture donnerait un mauvais verdict). Sert à ne pas
  // laisser les courses d'hier sous la date d'aujourd'hui quand un appel échoue.
  const programmeJour = useRef<string | null>(initialProgramme ? initialJour : null);
  const [erreurReseau, setErreurReseau] = useState(false);
  const [loading, setLoading] = useState(!initialProgramme);
  const [discFilter, setDiscFilter] = useState<string>("Tous");
  const [reunionFilter, setReunionFilter] = useState<number | "all">("all");
  const [hippoSearch, setHippoSearch] = useState("");
  const [showSearch, setShowSearch] = useState(false);
  const [vbOnly, setVbOnly] = useState(false);

  const isToday = format(selectedDate, "yyyy-MM-dd") === jourParis();
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

  /* Aperçu public de l'analyse, une requête pour toute la journée. Public :
     c'est justement au visiteur SANS compte qu'il doit s'adresser. */
  const { data: apercuJour } = useSWR(
    `/programme-apercu/${format(selectedDate, "yyyy-MM-dd")}`,
    () => coursesApi.programmeApercu(format(selectedDate, "yyyy-MM-dd")).then((r) => r.data),
    { refreshInterval: 300000, revalidateOnFocus: false },
  );
  const apercuByCourse = (apercuJour as { courses?: Record<string, ApercuCourse> } | undefined)?.courses ?? {};

  /* Fetch programme */
  useEffect(() => {
    let cancelled = false;
    const dateStr = format(selectedDate, "yyyy-MM-dd");
    const load = (initial: boolean) => {
      if (initial) setLoading(true);
      coursesApi
        .programme(dateStr)
        .then((res) => {
          if (cancelled) return;
          setProgramme(res.data);
          programmeJour.current = dateStr;
          setErreurReseau(false);
        })
        // Un appel qui échoue (429, coupure, 5xx) ne doit PAS effacer un programme
        // déjà affiché : on vidait l'état, la page annonçait « Aucune course
        // programmée » et se lisait comme « le PMU n'a rien prévu aujourd'hui »
        // alors que les 42 courses étaient là, envoyées par le rendu serveur.
        .catch(() => {
          if (cancelled) return;
          setErreurReseau(true);
          if (programmeJour.current !== dateStr) setProgramme(null);
        })
        .finally(() => { if (!cancelled && initial) setLoading(false); });
    };
    // Le rendu serveur a déjà fourni ce jour-là : pas de requête au montage. C'était
    // un appel API par visite pour redemander ce qu'on venait de recevoir.
    if (programmeJour.current === dateStr) setLoading(false);
    else load(true);
    const iv = isToday ? setInterval(() => load(false), 60000) : null;
    return () => { cancelled = true; if (iv) clearInterval(iv); };
  }, [selectedDate, isToday]);

  const selectDate = useCallback((d: Date) => {
    setDiscFilter("Tous");
    setReunionFilter("all");
    setHippoSearch("");
    setVbOnly(false);
    setSelectedDate(d);
  }, []);

  /* Derived */
  const allCourses = useMemo(() => programme?.reunions.flatMap((r) => r.courses) ?? [], [programme]);

  const discCounts = useMemo(
    () => allCourses.reduce((acc, c) => { acc[c.discipline] = (acc[c.discipline] || 0) + 1; return acc; }, {} as Record<string, number>),
    [allCourses],
  );

  /* Réunions (pour le filtre par réunion) */
  const reunionOptions = useMemo(
    () => (programme?.reunions ?? []).map((r) => ({ numero: r.numero, hippodrome: r.hippodrome })).sort((a, b) => a.numero - b.numero),
    [programme],
  );

  /* Prochaine course (toutes réunions, hors terminées/annulées) */
  const nextRace = useMemo(() => {
    if (!programme || !isToday) return null;
    const cands: Array<{ course: CourseSummary; reunionNum: number }> = [];
    for (const r of programme.reunions) for (const c of r.courses) {
      if (c.statut !== "termine" && c.statut !== "annule") cands.push({ course: c, reunionNum: r.numero });
    }
    cands.sort((a, b) => new Date(a.course.date_heure).getTime() - new Date(b.course.date_heure).getTime());
    return cands[0] ?? null;
  }, [programme, isToday]);

  /* Aplatir + filtrer + trier par heure */
  const flat = useMemo(() => {
    if (!programme) return [] as Array<{ course: CourseSummary; reunionNum: number }>;
    const items: Array<{ course: CourseSummary; reunionNum: number }> = [];
    for (const r of programme.reunions) {
      if (reunionFilter !== "all" && r.numero !== reunionFilter) continue;
      if (hippoSearch && !r.hippodrome.toLowerCase().includes(hippoSearch.toLowerCase())) continue;
      for (const c of r.courses) {
        if (discFilter !== "Tous" && c.discipline !== discFilter) continue;
        if (vbOnly && isPaid && (vbByCourse[c.course_id] || 0) <= 0) continue;
        items.push({ course: c, reunionNum: r.numero });
      }
    }
    items.sort((a, b) => new Date(a.course.date_heure).getTime() - new Date(b.course.date_heure).getTime());
    return items;
  }, [programme, reunionFilter, hippoSearch, discFilter, vbOnly, isPaid, vbByCourse]);

  /* Groupes horaires */
  const groups = useMemo(() => {
    const map = new Map<string, typeof flat>();
    for (const it of flat) {
      const key = `${new Date(it.course.date_heure).getHours()}h`;
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(it);
    }
    return Array.from(map.entries());
  }, [flat]);

  const dayName = cap(format(selectedDate, "EEEE", { locale: fr }));
  const restDate = format(selectedDate, "d MMMM yyyy", { locale: fr });

  const resetFilters = () => { setDiscFilter("Tous"); setReunionFilter("all"); setHippoSearch(""); setVbOnly(false); };

  return (
    <div
      className="min-h-screen"
      style={{
        background:
          "radial-gradient(ellipse at 20% 0%,rgba(245,158,11,.06) 0%,transparent 48%),radial-gradient(ellipse at 85% 8%,rgba(217,119,6,.04) 0%,transparent 42%),linear-gradient(180deg,#FFFDF6 0%,#FAFAF8 40%)",
      }}
    >
      {/* @keyframes local (fadeUp) */}
      <style>{`@keyframes fadeUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:none}}@media (prefers-reduced-motion:reduce){*{animation:none!important}}`}</style>

      <div className="mx-auto max-w-4xl space-y-5 px-4 py-6 sm:space-y-6 sm:px-6 sm:py-8 lg:px-8">

        {/* ── HERO ── */}
        <div
          className="relative overflow-hidden rounded-[28px] px-5 pb-5 pt-6 sm:px-7 sm:pb-6 sm:pt-7 animate-[fadeUp_.5s_cubic-bezier(.16,1,.3,1)_both]"
          style={{ border: "1px solid rgba(245,158,11,.18)", background: "linear-gradient(180deg,#FFFBF0 0%,#FFFFFF 100%)", boxShadow: "0 1px 3px rgba(0,0,0,.04),0 16px 44px -20px rgba(180,83,9,.18)" }}
        >
          <div className="pointer-events-none absolute inset-0" style={{ background: "radial-gradient(60% 60% at 12% 8%,rgba(245,158,11,.10),transparent 62%),radial-gradient(55% 55% at 94% 20%,rgba(217,119,6,.07),transparent 60%)" }} />
          <span
            aria-hidden
            className="pointer-events-none absolute max-[479px]:hidden"
            style={{
              right: 30, top: 16, width: 172, height: 104, opacity: 0.11, background: "linear-gradient(120deg,#D97706,#92400E)",
              WebkitMaskImage: "url(/img/logo-horse.png)", maskImage: "url(/img/logo-horse.png)",
              WebkitMaskRepeat: "no-repeat", maskRepeat: "no-repeat",
              WebkitMaskPosition: "center", maskPosition: "center",
              WebkitMaskSize: "contain", maskSize: "contain",
            }}
          />
          <div className="relative">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div className="inline-flex items-center gap-2 text-[11px] font-bold uppercase tracking-[.16em] text-amber-700">
                <span className="h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse" />
                Programme du jour
              </div>
              {!isToday && (
                <button
                  onClick={() => selectDate(new Date())}
                  className="shrink-0 rounded-xl px-4 py-2 text-sm font-semibold text-white shadow-sm transition-colors"
                  style={{ background: "linear-gradient(135deg,#F59E0B,#D97706)" }}
                >
                  Aujourd&apos;hui
                </button>
              )}
            </div>
            <h1 className="text-[27px] sm:text-[38px] font-bold leading-[1.08] sm:leading-[1.04] tracking-tight" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
              <span style={{ background: "linear-gradient(135deg,#92400E 0%,#D97706 55%,#F59E0B 100%)", WebkitBackgroundClip: "text", backgroundClip: "text", WebkitTextFillColor: "transparent" }}>{dayName}</span>
              <span className="text-gray-800"> {restDate}</span>
            </h1>

            {programme && programme.nb_courses > 0 && (
              <div className="mt-5 flex flex-wrap gap-2.5">
                {[{ n: programme.nb_courses, l: "Courses" }, { n: programme.reunions.length, l: "Réunions" }].map((s) => (
                  <div key={s.l} className="min-w-[118px] flex-1 rounded-2xl px-4 py-3.5" style={{ background: "rgba(255,255,255,.72)", backdropFilter: "blur(4px)", border: "1px solid rgba(0,0,0,.06)" }}>
                    <div className="text-[29px] font-bold leading-none text-gray-900 tabular-nums" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>{s.n}</div>
                    <div className="mt-1.5 text-xs font-medium text-gray-600">{s.l}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* ── Sélecteur de jour ── */}
        <DayStrip selected={selectedDate} onSelect={selectDate} />

        {/* ── Prochaine course ── */}
        {nextRace && <NextRaceBanner item={nextRace} />}

        {/* ── Bandeau value bets actifs (Free/Découverte + visiteurs non connectés) ── */}
        {!isPaid && <ValueBetsCompteurBanner initial={initialCompteurVB} />}

        {/* ── Contrôles ── */}
        {programme && programme.nb_courses > 0 && (
          <div className="space-y-3">
            {/* Recherche + valeur */}
            <div className="flex flex-wrap items-center gap-2.5">
              {isPaid && isToday && (
                <button
                  onClick={() => setVbOnly((v) => !v)}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-full px-3.5 py-2 text-[13px] font-semibold transition-all",
                    vbOnly ? "bg-amber-500 text-brand-dark shadow-sm shadow-amber-200" : "border border-amber-200 bg-amber-50 text-amber-700 hover:bg-amber-100",
                  )}
                >
                  <Zap className="h-3.5 w-3.5" /> Valeur
                </button>
              )}
              <div className="relative min-w-[190px] flex-1">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-600" />
                <input
                  value={hippoSearch}
                  onChange={(e) => setHippoSearch(e.target.value)}
                  placeholder="Rechercher un hippodrome…"
                  className="w-full rounded-xl border border-gray-200 bg-white py-2.5 pl-9 pr-8 text-[13px] outline-none transition-all focus:border-amber-400 focus:ring-2 focus:ring-amber-100"
                />
                {hippoSearch && (
                  <button onClick={() => setHippoSearch("")} className="absolute right-3 top-1/2 -translate-y-1/2">
                    <X className="h-3.5 w-3.5 text-gray-600" />
                  </button>
                )}
              </div>
            </div>

            {/* Filtre par réunion */}
            {reunionOptions.length > 1 && (
              <div className={cn("flex gap-2 overflow-x-auto pb-1.5", HIDE_SCROLLBAR)}>
                <button
                  onClick={() => setReunionFilter("all")}
                  className={cn("inline-flex flex-shrink-0 items-center gap-1.5 rounded-xl border px-3.5 py-2 text-[13px] font-semibold transition-all hover:-translate-y-0.5",
                    reunionFilter === "all" ? "border-gray-900 bg-gray-900 text-white" : "border-gray-200 bg-white text-gray-600 hover:border-gray-300")}
                  style={{ fontFamily: "'Space Grotesk', sans-serif" }}
                >
                  Toutes
                </button>
                {reunionOptions.map((r) => {
                  const active = reunionFilter === r.numero;
                  return (
                    <button
                      key={r.numero}
                      onClick={() => setReunionFilter(r.numero)}
                      className={cn("inline-flex flex-shrink-0 items-center gap-1.5 rounded-xl border px-3.5 py-2 text-[13px] font-semibold transition-all hover:-translate-y-0.5",
                        active ? "border-gray-900 bg-gray-900 text-white" : "border-gray-200 bg-white text-gray-600 hover:border-gray-300")}
                    >
                      <span style={{ fontFamily: "'Space Grotesk', sans-serif", fontWeight: 700 }}>R{r.numero}</span>
                      <span className="opacity-75 whitespace-nowrap font-medium">{r.hippodrome}</span>
                    </button>
                  );
                })}
              </div>
            )}

            {/* Filtre par discipline */}
            <div className={cn("flex gap-2 overflow-x-auto pb-1.5", HIDE_SCROLLBAR)}>
              {["Tous", ...Object.keys(discCounts).sort((a, b) => discCounts[b] - discCounts[a])].map((d) => {
                const count = d === "Tous" ? allCourses.length : (discCounts[d] ?? 0);
                if (d !== "Tous" && count === 0) return null;
                const active = discFilter === d;
                return (
                  <button
                    key={d}
                    onClick={() => setDiscFilter(d)}
                    className={cn("inline-flex flex-shrink-0 items-center gap-1.5 rounded-full border px-3.5 py-2 text-[13px] font-semibold transition-all hover:-translate-y-0.5",
                      active ? "border-gray-900 bg-gray-900 text-white" : "border-gray-200 bg-white text-gray-600 hover:border-gray-300 hover:text-gray-900")}
                  >
                    {d !== "Tous" && <DiscIcon discipline={d} w={34} h={24} color={active ? "#FFFFFF" : discMeta(d).color} />}
                    {titleCase(d)}
                    <span className={cn("rounded-full px-1.5 text-[11px] font-bold tabular-nums", active ? "bg-white/20 text-white" : "bg-gray-100 text-gray-600")}>{count}</span>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* ── Contenu ── */}
        {loading ? (
          <div className="flex flex-col items-center justify-center gap-3 py-24">
            <Loader2 className="h-8 w-8 animate-spin text-gray-300" />
            <p className="text-sm text-gray-600">Chargement du programme…</p>
          </div>
        ) : !programme && erreurReseau ? (
          /* Panne de lecture, pas journée vide : le distinguer évite d'annoncer
             « aucune course » quand c'est l'API qui n'a pas répondu. */
          <div className="flex flex-col items-center justify-center gap-3 py-24">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-amber-50"><Radio className="h-7 w-7 text-amber-600" /></div>
            <p className="font-semibold text-gray-700">Programme momentanément indisponible</p>
            <p className="text-sm text-gray-600">La connexion au service a échoué. Nouvelle tentative automatique dans une minute.</p>
            <button onClick={() => window.location.reload()} className="mt-1 text-sm font-medium text-amber-700 hover:underline">Réessayer maintenant</button>
          </div>
        ) : !programme || programme.nb_courses === 0 ? (
          <div className="flex flex-col items-center justify-center gap-3 py-24">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-gray-100"><Trophy className="h-7 w-7 text-gray-300" /></div>
            <p className="font-semibold text-gray-600">Aucune course programmée</p>
            <p className="text-sm text-gray-600">Essayez une autre date</p>
            <button onClick={() => setSelectedDate(new Date())} className="mt-1 text-sm font-medium text-amber-700 hover:underline">Revenir à aujourd&apos;hui</button>
          </div>
        ) : groups.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 py-16">
            <Filter className="h-8 w-8 text-gray-300" />
            <p className="text-sm text-gray-600">Aucune course ne correspond aux filtres</p>
            <button onClick={resetFilters} className="text-sm font-medium text-amber-700 hover:underline">Effacer les filtres</button>
          </div>
        ) : (
          /* ── TIMELINE ── */
          <div className="relative">
            <div className="absolute left-[19px] sm:left-[22px] top-4 bottom-4 w-0.5 rounded hidden sm:block" style={{ background: "linear-gradient(180deg,#FCD34D,#F59E0B,#D97706)", opacity: 0.35 }} />
            <div className="space-y-7">
              {groups.map(([hour, items]) => (
                <div key={hour} className="relative">
                  <div className="mb-3.5 flex items-center gap-3.5">
                    <div
                      className="relative z-[2] flex h-10 w-10 items-center justify-center rounded-xl text-[13px] font-bold text-white sm:h-[46px] sm:w-[46px] sm:rounded-2xl sm:text-[15px]"
                      style={{ fontFamily: "'Space Grotesk', sans-serif", background: "linear-gradient(135deg,#F59E0B,#D97706)", boxShadow: "0 4px 12px -4px rgba(217,119,6,.4)" }}
                    >
                      {hour}
                    </div>
                    <span className="text-xs font-semibold text-gray-600">{items.length} course{items.length > 1 ? "s" : ""}</span>
                  </div>
                  <div className="ml-0 sm:ml-[62px] flex flex-col gap-2.5">
                    {items.map(({ course, reunionNum }, i) => (
                      <TimelineRow
                        key={course.course_id}
                        course={course}
                        reunionNum={reunionNum}
                        vbCount={isPaid ? vbByCourse[course.course_id] : undefined}
                        apercu={apercuByCourse[course.course_id]}
                        delay={Math.min(i, 8) * 0.05}
                        targetId={course.course_id === nextRace?.course.course_id ? "next-race-row" : undefined}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Upsell (utilisateurs gratuits) ── */}
        {!isPaid && isToday && programme && programme.nb_courses > 0 && (
          <div className="flex flex-wrap items-center justify-between gap-3.5 rounded-[20px] px-5 py-4" style={{ border: "1px solid rgba(245,158,11,.28)", background: "linear-gradient(135deg,#FFFBF0,#FEF3E2)" }}>
            <div className="min-w-[200px]">
              <p className="text-sm font-bold text-amber-900">Paris de valeur verrouillés</p>
              <p className="mt-1 text-xs text-amber-700">Passez Standard pour les voir détectés par l&apos;IA sur chaque course.</p>
            </div>
            <Link href="/tarifs" className="flex-shrink-0 rounded-xl px-5 py-2.5 text-sm font-bold text-white transition-transform hover:-translate-y-0.5" style={{ background: "linear-gradient(135deg,#F59E0B,#D97706)", boxShadow: "0 8px 22px -8px rgba(245,158,11,.55)" }}>
              Voir les offres
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}
