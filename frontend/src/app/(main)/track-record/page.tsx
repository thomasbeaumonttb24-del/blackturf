"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import {
  Trophy, Star, Receipt, Coins, ArrowRight, ShieldCheck, Database,
  ExternalLink, LockKeyhole, BarChart3, RefreshCw, CheckCircle2, XCircle,
  CalendarDays, Target, Crown, ChevronDown, Dices,
  LineChart, Gauge, Sparkles, Users, Bell, Wallet, Brain,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { DisciplineImg } from "@/components/ui/DisciplineIcon";
import dynamic from "next/dynamic";
import type { PointTendance } from "@/components/track-record/TendanceChart";
import { Reveal, Tilt, useReveal } from "@/components/track-record/effets";
import { TicketsGrid, Podium, PROFIL_LABELS, ecartVise, type WinningBet } from "@/components/track-record/BetsShowcase";
import { JaugeHasard, JaugeBrier } from "@/components/track-record/Jauges";
import { statsApi } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
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
    // `null` quand notre favori n'a pas de place à l'arrivée : disqualifié, tombé
    // ou distancé. Le pari est perdu, la course reste comptée.
    favori_position: number | null;
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

const nf = (n: number, d = 0) =>
  n.toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d });
// ─── Compteur animé (count-up) — déclenché quand l'élément entre à l'écran ───
/**
 * Compteur animé (count-up) déclenché à l'entrée dans le viewport.
 *
 * L'état initial est la VRAIE valeur, jamais 0 : l'animation est un bonus, pas la
 * source de vérité. Un rendu serveur, un IntersectionObserver absent, un onglet en
 * arrière-plan ou une capture automatisée doivent afficher « 3 630 courses
 * analysées », jamais « 0 courses analysées » — un titre à zéro détruirait la
 * crédibilité de la page. Un filet de sécurité repose la valeur exacte si
 * l'animation n'a pas abouti dans le temps imparti.
 */
function useCountUp(target: number, duration = 1400) {
  const [val, setVal] = useState(target);
  const ref = useRef<HTMLSpanElement>(null);
  const started = useRef(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined"
        || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setVal(target);
      return;
    }
    let raf = 0;
    let garde: ReturnType<typeof setTimeout> | undefined;
    let fini = false;
    const run = () => {
      if (started.current) return;
      started.current = true;
      const t0 = performance.now();
      setVal(0);
      const tick = (now: number) => {
        const p = Math.min((now - t0) / duration, 1);
        const eased = 1 - Math.pow(1 - p, 3); // easeOutCubic
        setVal(target * eased);
        if (p < 1) raf = requestAnimationFrame(tick);
        else { fini = true; setVal(target); }
      };
      raf = requestAnimationFrame(tick);
      garde = setTimeout(() => { if (!fini) { cancelAnimationFrame(raf); setVal(target); } }, duration + 800);
    };
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => e.isIntersecting && run()),
      { threshold: 0.3 },
    );
    io.observe(el);
    return () => {
      io.disconnect();
      cancelAnimationFrame(raf);
      if (garde) clearTimeout(garde);
    };
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

function SectionHeading({ eyebrow, title, description, icon: Icon, tone = "clair", aside }: {
  eyebrow: string;
  title: string;
  description: string;
  icon: typeof Trophy;
  tone?: "clair" | "sombre";
  aside?: React.ReactNode;
}) {
  const sombre = tone === "sombre";
  return (
    <Reveal className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="max-w-3xl">
        <span className={cn(
          "inline-flex items-center gap-2 rounded-full px-3 py-1 text-[11px] font-bold uppercase tracking-[0.16em] ring-1",
          sombre ? "bg-amber-400/10 text-amber-300 ring-amber-400/25" : "bg-amber-100/70 text-amber-900 ring-amber-200",
        )}>
          <Icon className="h-3.5 w-3.5" aria-hidden="true" /> {eyebrow}
        </span>
        <h2 className={cn(
          "mt-3 font-display text-[1.65rem] font-extrabold leading-[1.15] tracking-tight sm:text-4xl",
          sombre ? "text-white" : "text-slate-900",
        )}>
          {title}
        </h2>
        <p className={cn("mt-2 text-[15px] leading-7", sombre ? "text-white/65" : "text-muted-foreground")}>{description}</p>
      </div>
      {aside && <div className="shrink-0">{aside}</div>}
    </Reveal>
  );
}

/** Pastille « en direct » : le point respire, le texte reste sobre. */
function PastilleDirect({ children, sombre }: { children: React.ReactNode; sombre?: boolean }) {
  return (
    <span className={cn(
      "inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium ring-1",
      sombre ? "bg-white/5 text-white/80 ring-white/10" : "bg-white text-emerald-800 ring-emerald-200 shadow-sm",
    )}>
      <span className="live-dot h-2 w-2 rounded-full bg-emerald-500" aria-hidden="true" />
      {children}
    </span>
  );
}

/** Boutons « voir plus / réduire » partagés par les deux listes de paris. */
function VoirPlus({ reste, pas, etendu, onPlus, onReduire, libelle, sombre }: {
  reste: number; pas: number; etendu: boolean; onPlus: () => void; onReduire: () => void; libelle: string; sombre?: boolean;
}) {
  if (reste <= 0 && !etendu) return null;
  return (
    <div className="mt-8 flex flex-wrap justify-center gap-3">
      {reste > 0 && (
        <Button
          onClick={onPlus}
          variant="outline"
          className={cn(
            "press min-h-12 rounded-full px-6 font-semibold shadow-sm",
            sombre ? "border-amber-300/40 bg-amber-300/10 text-amber-200 hover:bg-amber-300/20 hover:text-amber-100" : "border-amber-300 bg-white text-amber-900 hover:bg-amber-50",
          )}
        >
          {libelle} <span className={sombre ? "text-amber-200/60" : "text-amber-700/70"}>(+{Math.min(pas, reste)})</span>
          <ChevronDown className="h-4 w-4" />
        </Button>
      )}
      {etendu && (
        <Button onClick={onReduire} variant="ghost" className={cn("min-h-12 rounded-full", sombre ? "text-white/60 hover:bg-white/5 hover:text-white" : "text-muted-foreground")}>
          Réduire <ChevronDown className="h-4 w-4 rotate-180" />
        </Button>
      )}
    </div>
  );
}

// ─── Carte discipline ─────────────────────────────────────────
function DisciplineCard({ d, maxCourses, hasard }: {
  d: TrackRecord["by_discipline"][number];
  maxCourses: number;
  hasard: number | null;
}) {
  const { ref, hidden } = useReveal<HTMLDivElement>(0.4);
  const partVolume = maxCourses > 0 ? Math.round((d.nb_courses / maxCourses) * 100) : 0;
  const ton = d.accuracy_top3 >= 55 ? "text-emerald-700" : d.accuracy_top3 >= 40 ? "text-amber-700" : "text-slate-600";
  return (
    <Tilt max={7} className="h-full rounded-3xl bg-white p-5 ring-1 ring-stone-200/80 shadow-[0_24px_50px_-36px_rgba(17,24,39,.5)] hover:ring-amber-300 sm:p-6">
      <div ref={ref}>
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="tr-pop inline-flex h-12 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-amber-50 to-stone-100 shadow-[inset_0_1px_0_#fff,0_8px_16px_-10px_rgba(0,0,0,.35)] ring-1 ring-stone-200">
              <DisciplineImg discipline={d.discipline} className="h-7 w-11" />
            </span>
            <div>
              <span className="block font-display text-base font-bold capitalize text-foreground">{d.discipline}</span>
              <span className="mt-0.5 block text-xs tabular-nums text-muted-foreground">
                {nf(d.nb_courses)} course{d.nb_courses > 1 ? "s" : ""} analysée{d.nb_courses > 1 ? "s" : ""}
              </span>
            </div>
          </div>
          <div className="text-right">
            <span className={cn("tr-pop block whitespace-nowrap font-display text-3xl font-black tabular-nums", ton)}>
              {nf(d.accuracy_top3, 1)}<span className="text-base"> %</span>
            </span>
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Top-3</span>
          </div>
        </div>

        {/* Barre Top-3 + repère hasard */}
        <div className="relative mt-6 h-3 overflow-hidden rounded-full bg-stone-100 shadow-[inset_0_1px_2px_rgba(0,0,0,.08)]" role="img"
          aria-label={`${d.discipline} : ${nf(d.accuracy_top3, 1)} % de présence du gagnant dans le Top-3, sur ${nf(d.nb_courses)} courses`}>
          <div className="tr-bar h-full rounded-full bg-gradient-to-r from-amber-300 via-amber-500 to-amber-700 shadow-[inset_0_1px_0_rgba(255,255,255,.5)]"
            style={{ width: hidden ? "0%" : `${Math.min(d.accuracy_top3, 100)}%` }} />
          {hasard != null && (
            <span className="absolute inset-y-0 w-0.5 bg-slate-700/70" style={{ left: `${Math.min(hasard, 100)}%` }} aria-hidden="true" />
          )}
        </div>
        {hasard != null && (
          <div className="relative h-4">
            <span className="absolute top-0.5 -translate-x-1/2 whitespace-nowrap text-[10px] font-medium text-slate-600"
              style={{ left: `${Math.min(hasard, 100)}%` }}>▲ hasard {nf(hasard, 0)} %</span>
          </div>
        )}

        <dl className="mt-4 grid grid-cols-3 gap-2 rounded-2xl bg-stone-50 p-3 text-center ring-1 ring-stone-100">
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
    </Tilt>
  );
}

// ─── FAQ ──────────────────────────────────────────────────────
function Faq({ q, children }: { q: string; children: React.ReactNode }) {
  return (
    <details className="group rounded-2xl bg-white px-5 py-4 ring-1 ring-stone-200 transition-shadow hover:shadow-[0_16px_36px_-28px_rgba(17,24,39,.5)] open:bg-amber-50/40 open:ring-amber-200">
      <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-4 text-[15px] font-semibold text-foreground marker:content-none">
        {q}
        <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-amber-50 ring-1 ring-amber-200 transition-transform group-open:rotate-180">
          <ChevronDown className="h-4 w-4 text-amber-700" aria-hidden="true" />
        </span>
      </summary>
      <div className="mt-3 text-sm leading-7 text-muted-foreground">{children}</div>
    </details>
  );
}

// ─── Carte de chiffre du hero (verre dépoli) ───
function HeroStatCard({ value, label, note, cls, i }: {
  value: React.ReactNode; label: string; note?: string; cls?: string; i: number;
}) {
  return (
    <Tilt
      max={10}
      className="tr-rise rounded-2xl bg-gradient-to-b from-white/[0.16] to-white/[0.05] px-3 py-2.5 text-left ring-1 ring-white/20 shadow-[0_20px_40px_-24px_rgba(0,0,0,.8)] backdrop-blur-md sm:px-5 sm:py-5 sm:text-center"
      style={{ animationDelay: `${250 + i * 110}ms` }}
    >
      <span className="absolute inset-x-4 top-0 h-px bg-gradient-to-r from-transparent via-amber-200/70 to-transparent" aria-hidden="true" />
      <div className={cn("tr-pop font-display text-[1.45rem] font-black leading-tight tabular-nums sm:text-[2.1rem]", cls ?? "text-white")}>{value}</div>
      <div className="mt-0.5 text-[11px] font-medium leading-tight text-white/80 sm:mt-1.5 sm:text-xs">{label}</div>
      {note && <div className="mt-0.5 text-[10px] leading-tight text-white/55 sm:mt-1">{note}</div>}
    </Tilt>
  );
}

// ─── En-tête ──────────────────────────────────────────────────
/**
 * En-tête du palmarès — rendu dans les TROIS états de la page (chargement,
 * erreur, données).
 *
 * `/track-record` est un composant client intégral : pendant le chargement, le
 * HTML servi ne contenait qu'un squelette, SANS le moindre `<h1>`. Sortir
 * l'en-tête du garde de chargement règle le référencement : son texte ne dépend
 * d'aucune donnée, seuls le compteur et les quatre chiffres en dépendent.
 *
 * Hauteur : l'en-tête occupe EXACTEMENT l'écran visible sous la barre de
 * navigation (64 px) — et, sur téléphone connecté, au-dessus de la barre d'onglets
 * du bas (68 px, affichée aux seuls utilisateurs connectés). L'ancienne version (88vh + 112 px de marge haute) débordait sur
 * mobile : il fallait faire défiler pour atteindre le bouton et les chiffres.
 * Tout est désormais resserré sur petit écran (titre, chapeau raccourci,
 * cartes compactes) pour que titre, bouton et chiffres tiennent dans le
 * premier écran, centrés.
 */
function HeroPalmares({ courses, depuis, stats, barreBas = false }: {
  courses: number | null;
  depuis: string | null;
  /** Vrai quand la barre d'onglets mobile est affichée (utilisateur connecté). */
  barreBas?: boolean;
  stats?: Array<{ value: React.ReactNode; label: string; note?: string; cls?: string }>;
}) {
  // Sans données (chargement, erreur), les cartes gardent leur place et leur
  // libellé : un tiret est honnête, une carte absente ferait sauter la mise en page.
  const cartes = stats ?? [
    { label: "Gagnant dans le Top-3", value: "—", cls: "text-amber-300" },
    { label: "Favori qui gagne", value: "—", cls: "text-emerald-300" },
    { label: "Courses analysées", value: "—" },
    { label: "Paris gagnés", value: "—" },
  ];

  return (
    <header className={cn(
      "relative isolate flex flex-col overflow-hidden md:min-h-[calc(100svh_-_4rem)]",
      barreBas ? "min-h-[calc(100svh_-_4rem_-_68px_-_env(safe-area-inset-bottom))]" : "min-h-[calc(100svh_-_4rem)]",
    )}>
      <picture>
        {/* Sur mobile, la boite du hero fait environ 432 x 972 px CSS : forcer une
            image 16:9 a la couvrir revient a l agrandir 4,3 fois, et le peloton
            devenait une bouillie. Un cadrage PORTRAIT 1:2 de la meme photo couvre la
            meme boite avec 1,5x d agrandissement seulement, pour 34 ko au lieu de 25.
            `sizes` vaut 320px et non 100vw : ce qui compte n est pas la largeur du
            viewport mais la largeur REELLEMENT couverte, que object-cover deduit de la
            hauteur. */}
        <source
          media="(max-width: 767px)"
          type="image/avif"
          srcSet="/img/palmares-hero-p420.avif 420w, /img/palmares-hero-p640.avif 640w, /img/palmares-hero-p900.avif 900w"
          sizes="320px"
        />
        <source
          media="(max-width: 767px)"
          type="image/webp"
          srcSet="/img/palmares-hero-p420.webp 420w, /img/palmares-hero-p640.webp 640w, /img/palmares-hero-p900.webp 900w"
          sizes="320px"
        />
        <source
          type="image/avif"
          srcSet="/img/palmares-hero-w480.avif 480w, /img/palmares-hero-w640.avif 640w, /img/palmares-hero-w800.avif 800w, /img/palmares-hero-w1024.avif 1024w, /img/palmares-hero-w1600.avif 1600w"
          sizes="100vw"
        />
        {/* `no-img-element` ne se declenche pas dans un <picture> : la directive
            de desactivation devenait inutile, et une directive inutile est une erreur. */}
        <img
          src="/img/palmares-hero-w1600.webp"
          srcSet="/img/palmares-hero-w480.webp 480w, /img/palmares-hero-w640.webp 640w, /img/palmares-hero-w800.webp 800w, /img/palmares-hero-w1024.webp 1024w, /img/palmares-hero-w1600.webp 1600w"
          sizes="100vw"
          width={1620}
          height={911}
          alt="Peloton de galopeurs de face dans la ligne droite, casaques rouge, or, violette et orange."
          fetchPriority="high"
          decoding="async"
          className="ken-burns absolute inset-0 h-full w-full object-cover object-[52%_center]"
        />
      </picture>
      {/* Voiles : vertical pour la lisibilité du texte blanc, horizontal léger
          pour asseoir le bord gauche, halo or pour la profondeur. */}
      <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/60 to-black/40" aria-hidden="true" />
      <div className="absolute inset-0 bg-gradient-to-r from-black/55 via-transparent to-transparent" aria-hidden="true" />
      <div className="tr-glow pointer-events-none absolute left-1/2 top-1/3 h-[420px] w-[420px] -translate-x-1/2 rounded-full bg-amber-500/15 blur-[90px]" aria-hidden="true" />

      <div className="relative mx-auto flex w-full max-w-5xl flex-1 flex-col justify-center px-4 py-5 text-center sm:px-6 sm:py-16 lg:px-8">
        <p className="flex items-center justify-center gap-3 text-[10px] font-semibold uppercase tracking-[0.24em] text-amber-300 sm:text-[11px]">
          <span className="h-px w-6 bg-amber-400/70 sm:w-7" aria-hidden="true" />
          Nos performances
          <span className="h-px w-6 bg-amber-400/70 sm:w-7" aria-hidden="true" />
        </p>

        <h1 className="mt-3 font-display text-[1.95rem] font-extrabold leading-[1.08] tracking-tight text-white [text-shadow:0_2px_24px_rgba(0,0,0,0.55)] sm:mt-6 sm:text-[4.25rem] sm:leading-[1.02]">
          Chaque pronostic IA,{" "}
          <span className="text-gradient-animated block">noté à l&apos;arrivée.</span>
        </h1>

        {/* Sur mobile, le chapeau garde l'essentiel (le compteur, l'horodatage, le
            PMU) ; la date de départ est déjà sur la carte « Courses analysées ». */}
        <p className="mx-auto mt-3 max-w-2xl text-sm leading-relaxed text-white/85 sm:mt-6 sm:text-lg">
          {courses !== null && (
            <>
              <span className="font-semibold tabular-nums text-white">{nf(courses)} courses</span>
              {" "}analysées<span className="hidden sm:inline">{depuis ? ` depuis le ${depuis}` : ""}</span>.{" "}
            </>
          )}
          Chaque prévision est horodatée avant le départ, puis confrontée aux{" "}
          <span className="font-semibold text-white">rapports PMU officiels</span>
          <span className="hidden sm:inline"> — les réussites comme les échecs</span>.
        </p>

        <div className="mt-5 flex justify-center sm:mt-8">
          <Button size="xl" asChild
            className="press btn-shimmer h-12 w-full max-w-sm rounded-xl bg-brand-gold px-6 text-base font-bold text-brand-dark shadow-lg shadow-amber-500/30 hover:bg-brand-gold-deep sm:h-14 sm:w-auto sm:px-10">
            <Link href="/tarifs">Essayer 7 jours gratuitement <ArrowRight className="ml-1 h-5 w-5" /></Link>
          </Button>
        </div>

        <p className="mt-3 flex flex-wrap items-center justify-center gap-x-2.5 gap-y-1 text-[11px] text-white/65 sm:mt-5">
          <span className="inline-flex items-center gap-1.5"><LockKeyhole className="h-3.5 w-3.5 text-emerald-300" aria-hidden="true" /> Horodaté avant le départ</span>
          <span aria-hidden="true">·</span>
          <span className="inline-flex items-center gap-1.5"><Database className="h-3.5 w-3.5 text-emerald-300" aria-hidden="true" /> Rapports PMU officiels</span>
          <span className="hidden sm:inline" aria-hidden="true">·</span>
          <span className="hidden items-center gap-1.5 sm:inline-flex"><CheckCircle2 className="h-3.5 w-3.5 text-emerald-300" aria-hidden="true" /> Aucun prélèvement pendant l&apos;essai</span>
        </p>

        <div className="mx-auto mt-5 grid w-full max-w-3xl grid-cols-2 gap-2 sm:mt-10 sm:grid-cols-4 sm:gap-4">
          {cartes.map((c, i) => <HeroStatCard key={c.label} i={i} {...c} />)}
        </div>
      </div>

      <a
        href="#preuves"
        className="relative mx-auto mb-5 hidden flex-col items-center gap-1 text-[11px] font-medium uppercase tracking-[0.2em] text-white/60 transition-colors hover:text-amber-300 md:flex"
      >
        Voir les preuves
        <ChevronDown className="h-5 w-5 animate-bounce" aria-hidden="true" />
      </a>
    </header>
  );
}

// ─── Courbe de tendance (30 jours) ────────────────────────────

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

// Recharts (~100 ko) ne servait qu ici, tout en bas de page, mais son import au
// niveau du module le faisait entrer dans le lot d hydratation initial et retardait
// la peinture du hero. Charge a la demande, avec un substitut de meme hauteur pour
// garder le CLS a zero.
const TendanceChart = dynamic(() => import("@/components/track-record/TendanceChart"), {
  ssr: false,
  loading: () => <div className="h-[260px] w-full animate-pulse rounded-2xl bg-stone-100 sm:h-[300px]" aria-hidden="true" />,
});

export default function TrackRecordPage() {
  // Sert uniquement à savoir S'IL FAUT tenter la version admin du palmarès :
  // pour un visiteur, l'appeler ne rapporte rien et coûte un 401 dans la console.
  const { user, loading: authEnCours } = useAuth();
  const estAdmin = !!user?.is_admin;
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
    // Tant que l'auth n'a pas tranché, on n'appelle rien : la clé `null` suspend SWR.
    // Pour un visiteur anonyme, `hasSessionHint()` répond sans aller au réseau, donc
    // l'attente est nulle en pratique.
    authEnCours ? null : estAdmin ? "palmares-gagnants-admin" : "palmares-gagnants-public",
    // `palmaresGagnants` est gardé par require_admin → 401 pour un visiteur, et cette
    // page est PUBLIQUE : sans repli, tout prospect voyait un palmarès vide. Les blocs
    // ROI se masquent d'eux-mêmes quand `profils` est absent — le ROI reste donc
    // admin-only, conformément à la règle produit.
    //
    // On ne tente PLUS la version admin d'abord : le 401 était rattrapé côté code mais
    // le navigateur le journalise quand même, et Lighthouse le compte en « erreurs de
    // console » (−4 points de bonnes pratiques sur une page vue par des prospects).
    // Le repli est conservé : un admin dont l'appel échoue voit la version publique
    // plutôt qu'un palmarès vide.
    async () => {
      const publique = async () => {
        const pub = (await statsApi.palmaresPublic()).data;
        return {
          gagnants: pub.gagnants ?? [],
          top_gains: pub.top_gains ?? [],
          n: pub.nb_paris_gagnes ?? 0,
          n_courses: pub.nb_courses_reglees ?? 0,
          updated_at: pub.updated_at,
        };
      };
      if (!estAdmin) return publique();
      try {
        return (await statsApi.palmaresGagnants()).data;
      } catch {
        return publique();
      }
    },
    { refreshInterval: 60_000, revalidateOnFocus: true, shouldRetryOnError: false },
  );

  // Arrivée par `/track-record#records` (lien « Voir les 30 records » de l'accueil) :
  // la section n'existe qu'une fois le palmarès chargé par SWR, bien après la
  // tentative de défilement du navigateur — l'ancre seule tombait dans le vide et
  // laissait le visiteur en haut de page. On déplie donc les 30 records et on
  // défile nous-mêmes, une seule fois, dès que la section est rendue.
  const ancreRecordsFaite = useRef(false);
  const recordsPrets = !!data && !!gagnantsData?.top_gains?.length;
  useEffect(() => {
    if (ancreRecordsFaite.current || window.location.hash !== "#records") return;
    setRecordsLimit(30);
    if (!recordsPrets) return;
    ancreRecordsFaite.current = true;
    // Deux images : la grille dépliée doit être peinte avant de mesurer.
    requestAnimationFrame(() => requestAnimationFrame(() => {
      document.getElementById("records")?.scrollIntoView({ block: "start" });
    }));
  }, [recordsPrets]);

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

  // C'EST CET ÉTAT QUI EST SERVI EN HTML. Il ne portait qu'un squelette gris,
  // donc aucun `<h1>` : la page de preuve du site était sa page la moins bien
  // référencée. L'en-tête, dont le texte ne dépend d'aucune donnée, y figure
  // désormais tel quel ; seuls les chiffres restent en attente.
  if (isLoading) {
    return (
      <div className="min-h-screen bg-[#FCFBF8]">
        <HeroPalmares courses={null} depuis={null} barreBas={!!user} />
        <div className="mx-auto max-w-6xl animate-pulse space-y-8 px-4 py-16 sm:px-6" aria-busy="true" aria-label="Chargement de nos performances">
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
          <h1 className="mt-4 font-display text-xl font-bold text-foreground">Nos performances sont temporairement indisponibles</h1>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">Les données n&apos;ont pas pu être chargées. Aucun résultat en cache n&apos;est affiché.</p>
          <Button onClick={() => mutate()} variant="brand" className="mt-6 min-h-11"><RefreshCw className="h-4 w-4" /> Réessayer</Button>
        </div>
      </div>
    );
  }

  const g = data.global;
  // `total_gain` n'existe que sur la version admin du palmarès (règle produit :
  // les montants agrégés ne sont pas publics). Sans ce garde-fou, un visiteur lisait
  // « Total réglé aux rapports officiels : +0 € ».
  const gainConnu = typeof gagnantsData?.total_gain === "number" && (gagnantsData?.total_gain ?? 0) > 0;
  const nbGagnants = gagnantsData?.n ?? 0;
  const nbCoursesReglees = gagnantsData?.n_courses ?? 0;
  const hasard3 = g.hasard_top3 ?? null;
  const hasard1 = g.hasard_top1 ?? null;
  const facteur3 = hasard3 && hasard3 > 0 ? g.accuracy_top3 / hasard3 : null;
  // « Notre favori gagne » = `favori_win_rate` PARTOUT sur le site (ce hero, la barre
  // de comparaison plus bas, la carte de l'accueil). `accuracy_top1` mesure exactement
  // le même évènement sur une autre table (`race_learning_log`) : publier les deux,
  // c'était afficher deux pourcentages différents pour une seule et même phrase.
  // `hasard_top1` reste le bon repère des deux côtés — c'est une espérance calculée
  // par course (1/nb_partants), pas une propriété de la cohorte.
  const favoriGagne = g.favori_win_rate;
  const facteur1 = hasard1 && hasard1 > 0 ? favoriGagne / hasard1 : null;
  const depuis = g.mesure_depuis
    ? new Date(g.mesure_depuis).toLocaleDateString("fr-FR", { timeZone: "Europe/Paris", day: "numeric", month: "long", year: "numeric" })
    : null;
  const maxCourses = Math.max(1, ...data.by_discipline.map((d) => d.nb_courses));
  const clv = data.clv;

  // Tendance : repères lisibles au-dessus de la courbe.
  const joursMesures = (data.tendance_30j ?? []).filter((p) => p.nb_predictions > 0);
  const joursAuDessus = hasard3 != null ? joursMesures.filter((p) => p.accuracy_top3 > hasard3).length : null;
  // Meilleur jour : seulement parmi les journées d'au moins 5 courses — un 100 %
  // sur 2 courses serait un record creux.
  const meilleurJour = joursMesures
    .filter((p) => p.nb_predictions >= 5)
    .reduce<(typeof joursMesures)[number] | null>((m, p) => (!m || p.accuracy_top3 > m.accuracy_top3 ? p : m), null);

  return (
    <div className="relative min-h-screen overflow-x-clip bg-[#FCFBF8]">

      <HeroPalmares
        barreBas={!!user}
        courses={g.nb_courses_analysees}
        depuis={depuis}
        stats={[
          {
            value: <CountUp value={g.accuracy_top3} decimals={1} suffix=" %" />,
            label: "Gagnant dans le Top-3",
            note: hasard3 != null ? `Hasard : ${nf(hasard3, 0)} %` : undefined,
            cls: "text-amber-300",
          },
          {
            value: <CountUp value={favoriGagne} decimals={1} suffix=" %" />,
            label: "Favori qui gagne",
            note: hasard1 != null ? `Hasard : ${nf(hasard1, 1)} %` : undefined,
            cls: "text-emerald-300",
          },
          {
            value: <CountUp value={g.nb_courses_analysees} />,
            label: "Courses analysées",
            note: depuis ? `Depuis le ${depuis}` : undefined,
          },
          {
            value: !gagnantsData ? "—" : gainConnu
              ? <CountUpEuro value={gagnantsData.total_gain ?? 0} prefix="+" />
              : <CountUp value={nbGagnants} />,
            label: gainConnu ? "Gains encaissés" : "Paris gagnés",
            note: gainConnu ? `${nf(nbGagnants)} paris gagnés` : `Sur ${nf(nbCoursesReglees)} courses réglées`,
          },
        ]}
      />

      {/* Sous l'image : ce qui qualifie la mesure. */}
      <div className="mx-auto max-w-7xl px-4 pt-6 sm:px-6 sm:pt-8">
        <div className="flex flex-col gap-2 rounded-2xl bg-white/80 px-4 py-3 text-xs text-slate-600 ring-1 ring-stone-200 backdrop-blur sm:flex-row sm:items-center sm:justify-between">
          <span className="inline-flex items-start gap-2">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" aria-hidden="true" />
            <span>
              Cohorte mesurée : toute course dont le pronostic existait avant le départ
              {g.nb_courses_rejouables ? `, dont ${nf(g.nb_courses_rejouables)} rejouables à l'identique` : ""}.
            </span>
          </span>
          {data.updated_at && (
            <span className="inline-flex shrink-0 items-center gap-1.5 font-medium text-slate-700">
              <RefreshCw className="h-3.5 w-3.5 text-amber-600" aria-hidden="true" />
              Actualisé à {new Date(data.updated_at).toLocaleTimeString("fr-FR", { timeZone: "Europe/Paris", hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
        </div>
        <EchantillonNotice nbCourses={g.nb_courses_analysees} mesureDepuis={g.mesure_depuis} />
      </div>

      <main id="preuves" className="mx-auto max-w-7xl scroll-mt-20 space-y-20 px-4 py-12 sm:px-6 sm:py-16 lg:space-y-28">

        {/* ── 50 derniers paris gagnés (tous profils) ───────────────────────── */}
        <section aria-label="Derniers paris gagnés" className="space-y-8">
          <SectionHeading
            eyebrow="En direct"
            title="Les derniers paris gagnés"
            description="Les 50 plus récents, tous profils confondus, avec le jour et l'heure de départ de la course. Touchez une course : vous voyez le pari, la mise et le rapport officiel."
            icon={Receipt}
            aside={<PastilleDirect>Mise de référence : 10 € / course</PastilleDirect>}
          />
          {!gagnantsData ? (
            <div className="grid gap-4 lg:grid-cols-2" aria-busy="true">
              {[0, 1, 2, 3].map((k) => <div key={k} className="h-40 animate-pulse rounded-2xl bg-white ring-1 ring-stone-200" />)}
            </div>
          ) : gagnantsData.gagnants.length === 0 ? (
            <div className="rounded-3xl bg-white py-12 text-center text-sm text-muted-foreground ring-1 ring-stone-200">
              Les paris gagnants apparaîtront ici dès les prochaines arrivées (l&apos;historique se construit en temps réel).
            </div>
          ) : (
            <div>
              <TicketsGrid bets={gagnantsData.gagnants.slice(0, recentLimit)} />
              <VoirPlus
                reste={Math.min(50, gagnantsData.gagnants.length) - recentLimit}
                pas={10}
                etendu={recentLimit > 10}
                onPlus={() => setRecentLimit((n) => Math.min(n + 10, 50))}
                onReduire={() => setRecentLimit(10)}
                libelle="Voir plus de paris"
              />
              <p className="mt-5 text-center text-xs text-muted-foreground">
                <strong className="font-semibold text-slate-800">{nf(gagnantsData.n)}</strong> pari{gagnantsData.n > 1 ? "s" : ""} gagnant{gagnantsData.n > 1 ? "s" : ""} au total ·{" "}
                {Math.min(recentLimit, gagnantsData.gagnants.length)} affiché{Math.min(recentLimit, gagnantsData.gagnants.length) > 1 ? "s" : ""}
              </p>
              {gagnantsData.gagnants.slice(0, recentLimit).some(ecartVise) && <NoteRapportVise />}
            </div>
          )}
        </section>

        {/* ── 30 meilleurs gains : scène sombre + podium ─────────────────────── */}
        {gagnantsData?.top_gains && gagnantsData.top_gains.length > 0 && (
          <section
            id="records"
            aria-label="Plus gros gains"
            className="relative isolate -mx-4 scroll-mt-20 overflow-hidden bg-[#0b1020] px-4 py-12 sm:mx-0 sm:rounded-[2rem] sm:px-8 sm:py-16 lg:px-12"
          >
            <div className="pointer-events-none absolute inset-0 -z-10" aria-hidden="true">
              <span className="tr-glow absolute -left-24 top-10 h-80 w-80 rounded-full bg-amber-500/20 blur-[100px]" />
              <span className="tr-glow absolute -right-24 top-1/3 h-96 w-96 rounded-full bg-indigo-500/15 blur-[110px]" style={{ animationDelay: "2s" }} />
              <span className="tr-floor" />
            </div>
            <SectionHeading
              tone="sombre"
              eyebrow="Records"
              title="Les plus gros gains"
              description="Nos 30 meilleurs coups, réglés aux rapports officiels. Chacun était figé avant le départ de la course."
              icon={Star}
              aside={<PastilleDirect sombre>Réglés aux rapports PMU</PastilleDirect>}
            />
            <div className="mt-10 lg:mt-14">
              <Podium bets={gagnantsData.top_gains} />
            </div>
            {gagnantsData.top_gains.length > 3 && (
              <div className="mt-12">
                <p className="mb-4 flex items-center gap-3 text-[11px] font-bold uppercase tracking-[0.18em] text-white/50">
                  <span className="h-px flex-1 bg-white/10" aria-hidden="true" /> La suite du classement <span className="h-px flex-1 bg-white/10" aria-hidden="true" />
                </p>
                <TicketsGrid bets={gagnantsData.top_gains.slice(3, recordsLimit)} rankOffset={3} dark />
                <VoirPlus
                  reste={Math.min(30, gagnantsData.top_gains.length) - recordsLimit}
                  pas={10}
                  etendu={recordsLimit > 10}
                  onPlus={() => setRecordsLimit((n) => Math.min(n + 10, 30))}
                  onReduire={() => setRecordsLimit(10)}
                  libelle="Voir plus de records"
                  sombre
                />
              </div>
            )}
            <p className="mt-6 text-center text-xs text-white/50">
              {Math.min(recordsLimit, gagnantsData.top_gains.length)} record{Math.min(recordsLimit, gagnantsData.top_gains.length) > 1 ? "s" : ""} affiché{Math.min(recordsLimit, gagnantsData.top_gains.length) > 1 ? "s" : ""} sur {Math.min(30, gagnantsData.top_gains.length)}
            </p>
          </section>
        )}

        {/* ── Les paris qui sont passés : total + profils ─────────────────── */}
        <section aria-label="Gains vérifiés" className="space-y-8">
          <SectionHeading
            eyebrow="Vue d'ensemble"
            title="Les paris qui sont passés"
            description={gainConnu
              ? "Les gains encaissés, profil par profil, avec le nombre de courses réglées en face."
              : "Le total des paris gagnés — et, juste à côté, le nombre de courses réglées. Sans ce second chiffre, n'afficher que les gagnants serait malhonnête."}
            icon={Coins}
          />
          {gagnantsError ? (
            <div role="alert" className="rounded-3xl bg-white py-10 text-center text-sm text-muted-foreground ring-1 ring-stone-200">
              <p>Les gains détaillés sont indisponibles pour le moment.</p>
              <Button onClick={() => mutateGagnants()} variant="outline" className="mt-4 min-h-11"><RefreshCw className="h-4 w-4" /> Réessayer</Button>
            </div>
          ) : !gagnantsData ? (
            <div className="h-56 animate-pulse rounded-3xl bg-white ring-1 ring-stone-200" aria-busy="true" />
          ) : (
            <>
              <div className="grid gap-4 lg:grid-cols-[1.35fr_1fr]">
                {/* Grand total (count-up) */}
                <Reveal>
                  <Tilt max={5} className="h-full overflow-hidden rounded-3xl bg-gradient-to-br from-emerald-600 via-emerald-700 to-emerald-900 p-6 text-white shadow-[0_40px_80px_-40px_rgba(4,120,87,.8)] sm:p-9">
                    <span className="tr-shine" aria-hidden="true" />
                    <span className="tr-glow pointer-events-none absolute -right-10 -top-10 h-56 w-56 rounded-full bg-emerald-300/30 blur-3xl" aria-hidden="true" />
                    <Trophy className="pointer-events-none absolute -bottom-6 -right-4 h-40 w-40 rotate-12 text-white/[0.07]" aria-hidden="true" />
                    <div className="relative">
                      <p className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.16em] text-emerald-100">
                        <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                        {gainConnu ? "Total réglé aux rapports officiels" : "Paris gagnants réglés aux rapports officiels"}
                      </p>
                      {gainConnu ? (
                        <CountUpEuro
                          value={gagnantsData.total_gain ?? 0}
                          prefix="+"
                          className="tr-pop mt-4 block font-display text-5xl font-black leading-none tabular-nums sm:text-7xl"
                        />
                      ) : (
                        <CountUp value={nbGagnants} className="tr-pop mt-4 block font-display text-6xl font-black leading-none tabular-nums sm:text-8xl" />
                      )}
                      <p className="mt-4 max-w-md text-sm leading-6 text-emerald-50/85">
                        {gainConnu
                          ? `${nf(nbGagnants)} paris gagnés, sur ${nf(nbCoursesReglees)} courses réglées.`
                          : `paris gagnés, tous profils confondus, sur ${nf(nbCoursesReglees)} courses réglées. Chacun est consultable sur sa course.`}
                      </p>
                    </div>
                  </Tilt>
                </Reveal>

                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-1">
                  {[
                    // Version publique : le grand bloc porte déjà le nombre de paris
                    // gagnés — le répéter juste à côté n'apprendrait rien.
                    gainConnu
                      ? { icon: Trophy, v: nbGagnants, l: "Paris gagnés", t: "Réglés au rapport PMU officiel, un par un.", cls: "from-amber-400 to-amber-600" }
                      : { icon: Trophy, v: Object.keys(PROFIL_LABELS).length, l: "Profils de jeu", t: "Prudent, Modéré et Risqué : chaque pari gagné indique son profil.", cls: "from-amber-400 to-amber-600" },
                    { icon: Target, v: nbCoursesReglees, l: "Courses réglées", t: "Le dénominateur : toutes les courses jouées, gagnantes ou non.", cls: "from-slate-600 to-slate-900" },
                  ].map((k, i) => (
                    <Reveal key={k.l} delay={120 + i * 100}>
                      <Tilt max={7} className="flex h-full items-center gap-4 rounded-3xl bg-white p-5 ring-1 ring-stone-200/80 shadow-[0_24px_50px_-36px_rgba(17,24,39,.5)] sm:p-6">
                        <span className={cn("tr-pop inline-flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br text-white shadow-[inset_0_1px_0_rgba(255,255,255,.35),0_12px_22px_-10px_rgba(0,0,0,.5)]", k.cls)}>
                          <k.icon className="h-6 w-6" aria-hidden="true" />
                        </span>
                        <div>
                          <CountUp value={k.v} className="block font-display text-3xl font-black leading-none tabular-nums text-slate-900" />
                          <p className="mt-1 text-sm font-semibold text-slate-800">{k.l}</p>
                          <p className="mt-0.5 text-xs leading-5 text-muted-foreground">{k.t}</p>
                        </div>
                      </Tilt>
                    </Reveal>
                  ))}
                </div>
              </div>

              {/* Gains encaissés par profil (version admin uniquement) */}
              {gagnantsData.profils && gagnantsData.profils.length > 0 && (() => {
                const PROFIL_BAR: Record<string, { grad: string; dot: string }> = {
                  conservateur: { grad: "from-emerald-300 via-emerald-500 to-emerald-700", dot: "bg-emerald-500" },
                  equilibre: { grad: "from-sky-300 via-blue-500 to-blue-700", dot: "bg-blue-500" },
                  agressif: { grad: "from-rose-300 via-rose-500 to-rose-700", dot: "bg-rose-500" },
                };
                const maxGain = Math.max(1, ...gagnantsData.profils!.map((p) => p.gain_total ?? 0));
                return (
                  <div className="grid gap-4 sm:grid-cols-3" aria-label="Répartition des gains encaissés par profil">
                    {gagnantsData.profils!.map((p, i) => {
                      const pm = PROFIL_LABELS[p.profil] ?? { label: p.label, cls: "bg-muted text-muted-foreground ring-border" };
                      const bar = PROFIL_BAR[p.profil] ?? { grad: "from-amber-300 to-amber-600", dot: "bg-amber-500" };
                      const gain = p.gain_total ?? 0;
                      return (
                        <Reveal key={p.profil} delay={i * 100}>
                          <Tilt max={7} className="h-full rounded-3xl bg-white p-5 ring-1 ring-stone-200/80 shadow-[0_24px_50px_-36px_rgba(17,24,39,.5)] sm:p-6">
                            <div className="flex items-center justify-between">
                              <span className={cn("inline-flex rounded-full px-2.5 py-0.5 text-[11px] font-semibold ring-1", pm.cls)}>{pm.label}</span>
                              <span className="text-[11px] uppercase tracking-wider text-muted-foreground">{nf(p.nb_courses)} courses</span>
                            </div>
                            <CountUpEuro value={gain} prefix="+" className="tr-pop mt-5 block font-display text-3xl font-black leading-none tabular-nums text-emerald-700" />
                            <p className="mt-1 text-xs text-muted-foreground">de gains encaissés</p>
                            <div className="mt-4 h-2.5 overflow-hidden rounded-full bg-stone-100">
                              <div className={cn("h-full rounded-full bg-gradient-to-r bar-grow", bar.grad)} style={{ ["--bar-pct" as string]: `${Math.round((gain / maxGain) * 100)}%` }} />
                            </div>
                            <p className="mt-3 flex items-center justify-between text-xs">
                              <span className="flex items-center gap-1.5 text-muted-foreground"><span className={cn("h-2 w-2 rounded-full", bar.dot)} /> Paris gagnés</span>
                              <span className="font-bold tabular-nums">{nf(p.paris_gagnes)}</span>
                            </p>
                          </Tilt>
                        </Reveal>
                      );
                    })}
                  </div>
                );
              })()}

              <p className="flex items-start gap-2 rounded-2xl bg-white px-4 py-3 text-xs leading-5 text-muted-foreground ring-1 ring-stone-200">
                <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" aria-hidden="true" />
                Gains réels, figés avant le départ et réglés aux rapports PMU officiels. Performances passées — aucune garantie de gain futur.
              </p>
            </>
          )}
        </section>

        {/* ── Méthode de vérification ─────────────────────────────────────── */}
        <section aria-label="Méthode de vérification" className="space-y-10">
          <SectionHeading
            eyebrow="Traçabilité"
            title="Comment un pronostic devient une preuve"
            description="Trois étapes, vérifiables course par course — c'est ce qui sépare un palmarès d'une capture d'écran."
            icon={LockKeyhole}
          />
          <ol className="relative grid gap-4 md:grid-cols-3 md:gap-6">
            <span className="pointer-events-none absolute left-[10%] right-[10%] top-9 hidden h-0.5 bg-gradient-to-r from-amber-200 via-amber-400 to-emerald-300 md:block" aria-hidden="true" />
            {[
              { icon: LockKeyhole, n: "01", title: "Figé avant le départ", text: "La sélection, les cotes retenues et le plan de mise sont enregistrés et horodatés pendant que la course est encore à venir." },
              { icon: Database, n: "02", title: "Réglé au rapport officiel", text: "À l'arrivée, le pari est réglé au rapport PMU publié — jamais à une cote choisie après coup." },
              { icon: ExternalLink, n: "03", title: "Consultable une par une", text: "Chaque ligne renvoie vers sa course : partants, cotes, arrivée. Rien ne repose sur notre parole." },
            ].map((step, i) => (
              <Reveal as="li" key={step.n} delay={i * 130} className="relative">
                <Tilt max={7} className="h-full rounded-3xl bg-white p-6 text-center ring-1 ring-stone-200/80 shadow-[0_24px_50px_-36px_rgba(17,24,39,.5)]">
                  <span className="tr-pop relative mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-slate-800 to-slate-950 text-amber-300 shadow-[inset_0_1px_0_rgba(255,255,255,.2),0_14px_24px_-10px_rgba(15,23,42,.7)]">
                    <step.icon className="h-6 w-6" aria-hidden="true" />
                    <span className="absolute -right-2 -top-2 rounded-full bg-amber-400 px-1.5 py-0.5 font-display text-[10px] font-black text-slate-950 ring-2 ring-white">{step.n}</span>
                  </span>
                  <h3 className="mt-5 font-display text-base font-bold">{step.title}</h3>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">{step.text}</p>
                </Tilt>
              </Reveal>
            ))}
          </ol>
        </section>

        {/* ── Nos résultats comparés au hasard ──────────────────────────── */}
        <section aria-label="Nos résultats comparés au hasard" className="space-y-8">
          <SectionHeading
            eyebrow="Qualité du modèle"
            title="Ce que valent vraiment ces pourcentages"
            description="Un pourcentage seul ne veut rien dire. On le compare donc à ce que ferait un tirage au sort sur les mêmes courses : l'anneau coloré, c'est nous ; l'anneau gris, le hasard."
            icon={Gauge}
          />
          <div className="grid gap-4 sm:grid-cols-2 sm:gap-6">
            <Reveal>
              <JaugeHasard
                label="Le gagnant figure dans notre Top-3"
                aide={`Sur ${nf(g.nb_courses_analysees)} courses réglées, champ moyen de ${g.nb_partants_moyen ? nf(g.nb_partants_moyen, 1) : "11"} partants.`}
                nous={g.accuracy_top3}
                hasard={hasard3}
                facteur={facteur3}
              />
            </Reveal>
            <Reveal delay={140}>
              <JaugeHasard
                label="Notre favori gagne la course"
                aide="Le cheval classé numéro 1 par l'algorithme franchit la ligne en tête."
                nous={favoriGagne}
                hasard={hasard1}
                facteur={facteur1}
                teinte="emeraude"
              />
            </Reveal>
          </div>

          <div className="grid gap-4 lg:grid-cols-2 lg:gap-6">
            <Reveal><JaugeBrier value={g.brier_moyen} /></Reveal>
            <Reveal delay={140}>
              <div className="h-full rounded-3xl bg-white p-6 ring-1 ring-stone-200/80 sm:p-7">
                <h3 className="flex items-center gap-2 font-display text-lg font-bold text-foreground">
                  <ShieldCheck className="h-5 w-5 text-amber-600" aria-hidden="true" /> Ce que ces chiffres ne disent pas
                </h3>
                <ul className="mt-4 space-y-3 text-sm leading-6 text-muted-foreground">
                  <li className="flex gap-3 rounded-2xl bg-stone-50 p-3">
                    <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-rose-500" aria-hidden="true" />
                    <span>Ce n&apos;est pas un taux de paris gagnants : un cheval bien classé ne fait pas gagner un
                    Simple Gagnant, et le prélèvement PMU s&apos;applique à chaque mise.</span>
                  </li>
                  <li className="flex gap-3 rounded-2xl bg-stone-50 p-3">
                    <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-rose-500" aria-hidden="true" />
                    <span>Ce n&apos;est pas une promesse : les performances passées ne préjugent pas des suivantes,
                    et jouer comporte un risque de perte.</span>
                  </li>
                  <li className="flex gap-3 rounded-2xl bg-emerald-50 p-3 ring-1 ring-emerald-100">
                    <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" aria-hidden="true" />
                    <span>C&apos;est en revanche vérifiable course par course : chaque ligne de ce bilan renvoie
                    vers la course concernée et son rapport officiel.</span>
                  </li>
                </ul>
              </div>
            </Reveal>
          </div>
        </section>

        {/* ── Tendance 30 jours ─────────────────────────────────────────── */}
        {tendance.points.length > 0 && (
          <section aria-label="Tendance sur 30 jours" className="space-y-8">
            <SectionHeading
              eyebrow="Régularité"
              title="Jour après jour, sur 30 jours"
              description="Une bonne journée ne prouve rien. Ce qui compte, c'est que la courbe dorée reste au-dessus de la ligne grise du hasard, jour après jour."
              icon={LineChart}
            />
            <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
              {[
                { l: "Moyenne pondérée", v: `${nf(tendance.moyenne, 1)} %`, s: "gagnant dans le Top-3", cls: "text-amber-700" },
                { l: "Jours au-dessus du hasard", v: joursAuDessus != null ? `${joursAuDessus} / ${joursMesures.length}` : "—", s: hasard3 != null ? `hasard : ${nf(hasard3, 0)} %` : "", cls: "text-emerald-700" },
                { l: "Meilleur jour", v: meilleurJour ? `${nf(meilleurJour.accuracy_top3, 0)} %` : "—", s: meilleurJour ? `le ${meilleurJour.jour} · ${meilleurJour.nb_predictions} courses` : "au moins 5 courses", cls: "text-slate-900" },
                { l: "Courses mesurées", v: nf(tendance.totalCourses), s: `sur ${tendance.jours} jours`, cls: "text-slate-900" },
              ].map((k, i) => (
                <Reveal key={k.l} delay={i * 80}>
                  <Tilt max={8} className="h-full rounded-2xl bg-white p-4 ring-1 ring-stone-200/80 shadow-[0_20px_40px_-32px_rgba(17,24,39,.5)] sm:p-5">
                    <p className="text-[11px] font-semibold uppercase leading-tight tracking-wider text-muted-foreground">{k.l}</p>
                    <p className={cn("tr-pop mt-2 font-display text-2xl font-black tabular-nums sm:text-3xl", k.cls)}>{k.v}</p>
                    {k.s && <p className="mt-1 text-[11px] leading-tight text-muted-foreground">{k.s}</p>}
                  </Tilt>
                </Reveal>
              ))}
            </div>
            <Reveal>
              <div className="overflow-hidden rounded-3xl bg-white ring-1 ring-stone-200/80 shadow-[0_40px_80px_-50px_rgba(180,83,9,.5)]">
                <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-stone-100 px-4 py-3 text-[11px] font-medium text-slate-600 sm:px-6">
                  <span className="inline-flex items-center gap-1.5"><span className="h-1 w-5 rounded-full bg-gradient-to-r from-amber-300 to-amber-700" /> Top-3 du jour</span>
                  <span className="inline-flex items-center gap-1.5"><span className="h-0 w-5 border-t-2 border-dashed border-emerald-600" /> Moyenne</span>
                  {hasard3 != null && <span className="inline-flex items-center gap-1.5"><span className="h-0 w-5 border-t-2 border-dashed border-slate-400" /> Hasard</span>}
                </div>
                <div className="p-2 sm:p-6">
                  <TendanceChart data={tendance.points} moyenne={tendance.moyenne} hasard={hasard3} />
                </div>
                <p className="border-t border-stone-100 px-4 py-3 text-[11px] leading-5 text-muted-foreground sm:px-6">
                  Les journées sans course mesurée (interruption de collecte) apparaissent en trou plutôt qu&apos;à
                  zéro : afficher 0 % laisserait croire à un échec du modèle là où il n&apos;y a simplement pas de donnée.
                </p>
              </div>
            </Reveal>
          </section>
        )}

        {/* ── Précision par discipline ──────────────────────────────────── */}
        <section aria-label="Précision par discipline" className="space-y-8">
          <SectionHeading
            eyebrow="Par spécialité"
            title="La précision, discipline par discipline"
            description="Le trot et le galop ne se lisent pas pareil. Voici, sans tri, ce que l'algorithme donne sur chacun."
            icon={Sparkles}
          />
          {data.by_discipline.length === 0 ? (
            <div className="rounded-3xl bg-white py-10 text-center text-sm text-muted-foreground ring-1 ring-stone-200">Aucune donnée pour le moment</div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {data.by_discipline.map((d, i) => (
                <Reveal key={d.discipline} delay={i * 90}>
                  <DisciplineCard d={d} maxCourses={maxCourses} hasard={hasard3} />
                </Reveal>
              ))}
            </div>
          )}
        </section>

        {/* ── Le favori IA face au marché ───────────────────────────────── */}
        <section aria-label="Le favori de l'algorithme face au marché" className="space-y-8">
          <SectionHeading
            eyebrow="Face au marché"
            title="Notre favori contre la cote des parieurs"
            description="Recopier la cote, tout le monde sait faire. La vraie question : nos favoris tiennent-ils à l'arrivée, et le marché nous suit-il ?"
            icon={Users}
          />
          <div className="grid gap-4 lg:grid-cols-[.9fr_1.1fr] lg:gap-6">
            <Reveal>
              <div className="group relative h-full min-h-[260px] overflow-hidden rounded-3xl bg-slate-900">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src="/img/palmares-duel.webp"
                  alt="Trois chevaux au coude à coude dans la ligne droite"
                  className="absolute inset-0 h-full w-full object-cover transition-transform duration-[1.5s] group-hover:scale-110"
                  loading="lazy"
                />
                <div className="absolute inset-0 bg-gradient-to-t from-slate-950 via-slate-950/40 to-transparent" aria-hidden="true" />
                <div className="absolute inset-x-0 bottom-0 p-6">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-amber-300">Closing line value</p>
                  <p className="mt-2 max-w-sm text-sm leading-6 text-slate-200">
                    Quand la cote d&apos;un cheval baisse entre notre pronostic et le départ, c&apos;est le marché
                    qui vient nous rejoindre. De tous les signaux, c&apos;est le plus difficile à maquiller.
                  </p>
                </div>
              </div>
            </Reveal>

            <div className="grid gap-4 sm:grid-cols-2">
              <Reveal delay={80}>
                <Tilt max={7} className="h-full rounded-3xl bg-white p-6 ring-1 ring-stone-200/80 shadow-[0_24px_50px_-36px_rgba(17,24,39,.5)]">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Favori placé</p>
                  <p className="tr-pop mt-3 font-display text-4xl font-black tabular-nums text-emerald-700">
                    <CountUp value={g.favori_place_rate} decimals={1} suffix=" %" />
                  </p>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">
                    Notre cheval numéro 1 termine dans les 3 premiers, sur {nf(g.nb_favoris_evalues)} courses
                    confrontées à l&apos;arrivée officielle.
                  </p>
                </Tilt>
              </Reveal>
              <Reveal delay={160}>
                <Tilt max={7} className="h-full rounded-3xl bg-white p-6 ring-1 ring-stone-200/80 shadow-[0_24px_50px_-36px_rgba(17,24,39,.5)]">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Favori gagnant</p>
                  <p className="tr-pop mt-3 font-display text-4xl font-black tabular-nums text-slate-900">
                    <CountUp value={g.favori_win_rate} decimals={1} suffix=" %" />
                  </p>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">
                    Il gagne franchement la course, contre {hasard1 != null ? `${nf(hasard1, 1)} %` : "—"} pour un
                    choix au hasard sur le même champ.
                  </p>
                </Tilt>
              </Reveal>
              <Reveal delay={240} className="sm:col-span-2">
                <Tilt max={4} className={cn("h-full rounded-3xl p-6 ring-1", clv ? "bg-gradient-to-br from-amber-50 via-white to-white ring-amber-200 shadow-[0_24px_50px_-36px_rgba(180,83,9,.6)]" : "bg-white ring-stone-200")}>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-amber-800">Le marché se déplace vers nous</p>
                  {clv ? (
                    <div className="mt-3 flex flex-wrap items-end gap-x-6 gap-y-2">
                      <p className="tr-pop font-display text-4xl font-black tabular-nums text-amber-700">
                        <CountUp value={clv.pct_beat_line} decimals={1} suffix=" %" />
                      </p>
                      <p className="max-w-md text-sm leading-6 text-muted-foreground">
                        de nos favoris voient leur cote <strong className="font-semibold text-foreground">baisser</strong> entre
                        notre pronostic et le départ, sur {nf(clv.n)} courses mesurées.
                      </p>
                    </div>
                  ) : (
                    <p className="mt-3 text-sm leading-6 text-muted-foreground">
                      Indicateur en cours de constitution : il exige l&apos;historique complet des cotes, de notre
                      pronostic jusqu&apos;au départ.
                    </p>
                  )}
                </Tilt>
              </Reveal>
            </div>
          </div>
        </section>

        {/* ── Ce que débloque l'abonnement ──────────────────────────────── */}
        <section aria-label="Ce que débloque l'abonnement" className="space-y-8">
          <SectionHeading
            eyebrow="Passer à l'action"
            title="Nos performances sont publiques. Les pronostics du jour ne le sont pas."
            description="Ici, vous voyez ce qui s'est déjà joué. L'abonnement donne les pronostics des courses de tout à l'heure."
            icon={Crown}
          />
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {[
              { icon: Brain, title: "Les pronostics complets", text: "Le classement complet de chaque course, les probabilités par cheval et les intervalles de confiance — pas seulement les 3 premiers.", pro: true },
              { icon: Dices, title: "Les paris de valeur", text: "Les chevaux dont la cote du marché est supérieure à notre probabilité, notés de ★ à ★★★★, mis à jour en continu.", pro: true },
              { icon: Wallet, title: "Le plan de mise", text: "Combien miser, sur quel type de pari, selon votre profil de risque et votre bankroll — figé avant le départ.", pro: true },
              { icon: Bell, title: "Les alertes en direct", text: "Notification dès qu'un pari de valeur apparaît ou qu'une cote décroche sur une course qui vous intéresse.", pro: true },
              { icon: LineChart, title: "Le suivi de vos résultats", text: "Votre capital, vos paris et votre ROI suivis course après course, avec le même degré d'honnêteté que cette page.", pro: true },
              { icon: CalendarDays, title: "Le programme et les cotes", text: "Le programme du jour, les partants et les cotes en direct restent accessibles gratuitement, sans carte bancaire.", pro: false },
            ].map((f, i) => (
              <Reveal key={f.title} delay={(i % 3) * 90}>
                <Tilt max={7} className={cn("h-full rounded-3xl p-6 ring-1 shadow-[0_24px_50px_-40px_rgba(17,24,39,.5)]", f.pro ? "bg-white ring-amber-200/80 hover:ring-amber-300" : "bg-stone-50 ring-stone-200")}>
                  <div className="flex items-center justify-between">
                    <span className={cn(
                      "tr-pop inline-flex h-12 w-12 items-center justify-center rounded-2xl shadow-[inset_0_1px_0_rgba(255,255,255,.4),0_12px_22px_-12px_rgba(0,0,0,.5)]",
                      f.pro ? "bg-gradient-to-br from-amber-300 to-amber-600 text-slate-950" : "bg-white text-slate-600 ring-1 ring-stone-200",
                    )}>
                      <f.icon className="h-5 w-5" aria-hidden="true" />
                    </span>
                    <span className={cn("rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider", f.pro ? "bg-amber-100 text-amber-900" : "bg-stone-200/70 text-slate-600")}>
                      {f.pro ? "Abonnés" : "Gratuit"}
                    </span>
                  </div>
                  <h3 className="mt-5 font-display text-base font-bold text-foreground">{f.title}</h3>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">{f.text}</p>
                </Tilt>
              </Reveal>
            ))}
          </div>
        </section>

        {/* ── Conversion après démonstration de valeur ────────────────────── */}
        <Reveal>
        <section className="relative isolate overflow-hidden rounded-[2rem] bg-slate-950 px-6 py-10 text-white sm:px-10 sm:py-14" aria-labelledby="cta-pro-title">
          <div
            className="pointer-events-none absolute inset-0 -z-10 bg-cover bg-center opacity-20"
            style={{ backgroundImage: "url(/img/palmares-gagnant.webp)" }}
            aria-hidden="true"
          />
          <div className="pointer-events-none absolute inset-0 -z-10 bg-gradient-to-r from-slate-950 via-slate-950/95 to-slate-950/70" aria-hidden="true" />
          <span className="tr-glow pointer-events-none absolute -right-20 -top-20 -z-10 h-72 w-72 rounded-full bg-amber-500/20 blur-3xl" aria-hidden="true" />
          <span className="tr-floor -z-10 opacity-60" aria-hidden="true" />
          <div className="relative grid gap-8 lg:grid-cols-[1fr_auto] lg:items-end">
            <div>
              <div className="inline-flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-amber-300"><Crown className="h-3.5 w-3.5" aria-hidden="true" /> BlackTurf Pro</div>
              <h2 id="cta-pro-title" className="mt-4 max-w-2xl font-display text-3xl font-extrabold tracking-tight sm:text-5xl">
                Passez des résultats <span className="text-gradient-animated">aux décisions.</span>
              </h2>
              <p className="mt-4 max-w-2xl text-sm leading-6 text-slate-300 sm:text-base">
                Retrouvez les analyses complètes, les probabilités et les plans de mise qui ont produit ces performances.
                7 jours d&apos;essai : carte requise, aucun prélèvement avant la fin de l&apos;essai, annulable à tout moment. Les performances passées ne garantissent pas les résultats futurs.
              </p>
              <ul className="mt-6 grid gap-2 text-sm text-slate-200 sm:grid-cols-3">
                <li className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-emerald-300" aria-hidden="true" /> Pronostics complets</li>
                <li className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-emerald-300" aria-hidden="true" /> Plans de mise</li>
                <li className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-emerald-300" aria-hidden="true" /> Cotes en direct</li>
              </ul>
            </div>
            <div className="flex flex-col gap-3">
              <Button asChild variant="brand" size="lg" className="press btn-shimmer min-h-14 rounded-xl px-8 text-base font-bold shadow-lg shadow-amber-500/25">
                <Link href="/tarifs">Démarrer l&apos;essai gratuit <ArrowRight className="ml-1 h-4 w-4" /></Link>
              </Button>
              <p className="text-center text-[11px] text-slate-400">Standard 12€/mois · Expert 19€/mois · sans engagement</p>
            </div>
          </div>
        </section>
        </Reveal>

        {/* ── FAQ ──────────────────────────────────────────────────────── */}
        <section aria-label="Questions fréquentes" className="space-y-8">
          <SectionHeading
            eyebrow="Transparence"
            title="Les questions qu'on nous pose"
            description="Les réponses gênantes en premier — c'est à ça qu'on reconnaît un palmarès honnête."
            icon={ShieldCheck}
          />
          <div className="grid items-start gap-3 lg:grid-cols-2">
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
            <Faq q="« Gagnant dans le Top-3 », qu'est-ce que ça veut dire exactement ?">
              La part des courses où le cheval qui a gagné figurait parmi nos trois premiers choix.
              {hasard3 != null && ` Sur ces mêmes courses — ${g.nb_partants_moyen ? `${nf(g.nb_partants_moyen, 1)} partants en moyenne` : "champ réel"} — un tirage au sort atteindrait ${nf(hasard3, 0)} %.`}
              {" "}Ce n&apos;est pas un taux de paris gagnants : un cheval placé ne fait pas gagner un pari Simple Gagnant.
            </Faq>
            <Faq q="À quelle fréquence cette page est-elle mise à jour ?">
              À chaque arrivée. Dès qu&apos;une course est réglée, son résultat entre dans les taux ci-dessus et
              la course apparaît, gagnante ou perdante, dans l&apos;historique. Rien n&apos;est saisi à la main :
              c&apos;est la même chaîne qui produit les pronostics et qui les note.
            </Faq>
            <Faq q="Pourquoi montrer des taux moyens plutôt que vos plus beaux coups ?">
              Parce que n&apos;importe qui peut publier une capture d&apos;écran d&apos;un Trio à 450 contre 1 — nous en
              avons, ils sont plus bas dans la page. Un gros gain isolé ne prouve rien sur la méthode ;
              {" "}{nf(g.nb_courses_analysees)} courses mesurées, avec leur dénominateur et leurs échecs, si.
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

/** Explication de l'écart « rapport payé / rapport visé », sous la liste. */
function NoteRapportVise() {
  return (
    <p className="mx-auto mt-4 max-w-3xl rounded-2xl bg-white px-4 py-3 text-[11px] leading-relaxed text-muted-foreground ring-1 ring-stone-200">
      <span className="font-medium text-foreground">Payé</span> = le rapport PMU officiel
      à l&apos;arrivée. <span className="font-medium text-foreground">Visé</span> = celui annoncé par
      le plan au moment où il a été figé, avant le départ. Les deux diffèrent quand l&apos;argent
      entre dans les enjeux après le figeage — surtout sur les réunions étrangères, où les paris
      se clôturent après notre pronostic.
    </p>
  );
}
