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
 *   public/img/disciplines/attele-v9.png
 *   public/img/disciplines/plat-v9.png
 *   public/img/disciplines/monte-v9.png
 *   public/img/disciplines/obstacle-v9.png
 * (fournis dans ce même paquet, sous /public)
 */

import { useEffect, useLayoutEffect, useState, useMemo, useCallback, useRef } from "react";
import { format, addDays, differenceInMinutes, differenceInSeconds } from "date-fns";
import { fr } from "date-fns/locale";
import {
  ChevronRight, Trophy, Loader2, Zap, Search, X, Radio, Filter,
} from "lucide-react";
import Link from "next/link";
import { TrendingUp as IconeMarcheDirect } from "lucide-react";
import { CheckoutButton } from "@/components/billing/CheckoutButton";
import { CompteGratuitCta } from "@/components/billing/CompteGratuitCta";
import { peutDemarrerEssai } from "@/lib/auth";
import useSWR from "swr";
import { coursesApi, predictionsApi } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import { formatTime, cn } from "@/lib/utils";
import { jourParis } from "@/lib/seo";
import { CARTE_CLS, Pastille, PastilleDirect, SG } from "@/components/courses/course-ui";

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
// `color` sert aussi de couleur de TEXTE au nom de la discipline sur la carte de course.
// #6B7280 y donnait 4,38:1 sur le fond creme #F5F4EF — le dernier echec de contraste du
// site. #4B5563 passe a 6,86:1. Les cinq disciplines connues etaient deja assez foncees ;
// seul ce repli, servi quand la discipline n'est pas reconnue, echouait.
const DISC_FALLBACK: DiscMeta = { color: "#4B5563", bg: "#F3F4F6", ring: "#E5E7EB", mask: "plat-v9.png" };

function discMeta(discipline: string): DiscMeta {
  const d = (discipline || "").toLowerCase();
  if (d.includes("attel")) return { color: "#0E7C66", bg: "#ECFDF5", ring: "#B7E4D3", mask: "attele-v9.png" };
  if (d.includes("plat")) return { color: "#B45309", bg: "#FEF6E7", ring: "#F5DCA8", mask: "plat-v9.png" };
  if (d.includes("mont")) return { color: "#2A5BD7", bg: "#EEF3FF", ring: "#C5D6FB", mask: "monte-v9.png" };
  // « Obstacle » est la valeur renvoyée telle quelle par l'API (au même titre que
  // « Haies ») : sans ce cas, ces courses tombaient sur le repli et s'affichaient
  // avec le cheval de plat en gris, sans la barrière — alors que la fiche course,
  // elle, avait bien son entrée « Obstacle ».
  // Prune et non rouge-orangé : à 10° de teinte du plat (#B45309), l'obstacle était
  // indistinguable de lui dans la rangée de filtres, où les deux pastilles se
  // touchent. La prune est à 91° du plat, 72° du monté et 127° de l'attelé.
  // Contraste 7,48:1 sur le crème #F5F4EF — c'est ce fond-là, et non du blanc, qui
  // fait référence : `color` sert aussi de couleur de TEXTE au nom de la discipline
  // sur la carte de course (fonds réels : #FFFFFF à venir, #F5F4EF terminée,
  // #F0FDF8 en direct). Toute nouvelle teinte se vérifie contre les trois.
  if (d.includes("obstacle") || d.includes("haie")) return { color: "#86198F", bg: "#FAF2FC", ring: "#E9C7EE", mask: "obstacle-v9.png" };
  if (d.includes("steeple") || d.includes("cross")) return { color: "#A32C3E", bg: "#FCEEF0", ring: "#F0C9CF", mask: "obstacle-v9.png" };
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

/* ─── Compteur animé ──────────────────────────────────────
 * Le HTML serveur porte la vraie valeur (robots, visiteurs sans JavaScript). Côté
 * navigateur, on repart de 0 avant la première peinture puis on monte jusqu'à elle —
 * sauf si le visiteur a demandé moins d'animations. */
const useIsoLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;
function useCompteur(cible: number, dureeMs = 900): number {
  const [v, setV] = useState(cible);
  const deja = useRef(false);
  useIsoLayoutEffect(() => {
    if (deja.current) { setV(cible); return; }
    deja.current = true;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches || cible <= 0) { setV(cible); return; }
    let raf = 0;
    const t0 = performance.now();
    setV(0);
    const pas = (t: number) => {
      const k = Math.min(1, (t - t0) / dureeMs);
      setV(Math.round(cible * (1 - Math.pow(1 - k, 3))));
      if (k < 1) raf = requestAnimationFrame(pas);
    };
    raf = requestAnimationFrame(pas);
    return () => cancelAnimationFrame(raf);
  }, [cible, dureeMs]);
  return v;
}

function TuileCompteur({ n, libelle, ton }: { n: number; libelle: string; ton?: string }) {
  const v = useCompteur(n);
  return (
    <div className="bt-pop rounded-2xl bg-white/85 px-2.5 py-2.5 ring-1 ring-[#E6DCC6] shadow-[inset_0_1px_0_#fff,0_1px_2px_rgba(17,24,39,.05),0_10px_22px_-18px_rgba(146,64,14,.5)] backdrop-blur sm:px-4 sm:py-3">
      <div className={cn("text-[22px] font-bold leading-none tabular-nums text-stone-900 sm:text-[28px]", ton)} style={SG}>{v}</div>
      <div className="mt-1 text-[11px] font-medium text-stone-500 sm:text-xs">{libelle}</div>
    </div>
  );
}

/* Minutes avant le départ (null au-delà d'une heure ou course partie) — sert à
 * l'anneau qui se vide autour de l'heure de départ. */
function useMinutesAvant(targetDate: string, statut: string): number | null {
  const [m, setM] = useState<number | null>(null);
  useEffect(() => {
    if (statut !== "programme" && statut !== "a_venir") { setM(null); return; }
    const tick = () => {
      const s = differenceInSeconds(new Date(targetDate), new Date());
      setM(s > 0 && s < 3600 ? s / 60 : null);
    };
    tick();
    const id = setInterval(tick, 5000);
    return () => clearInterval(id);
  }, [targetDate, statut]);
  return m;
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

/* ─── Horloge partagée ──────────────────────────────────────
 * Ni le jour ni l'heure ne peuvent être figés au rendu. Cette page est servie depuis
 * un cache (ISR côté serveur, et cache HTTP côté navigateur, qui a le droit de rendre
 * un HTML de la veille) puis reste ouverte des heures. Sans horloge qui bat,
 * `jourParis()` garde la valeur qu'il avait à la GÉNÉRATION du HTML : d'où un
 * « Programme du jour » qui ouvre sur hier, et une « prochaine course » restée à 11h
 * alors qu'il est 14h.
 *
 * Le premier rendu — SSR puis hydratation — renvoie `null` : il ne dépend d'aucune
 * horloge, donc aucun mismatch d'hydratation possible. L'heure réelle arrive à
 * l'effet, juste après, et tout ce qui en dépend se recalcule.
 */
function useHorloge(periodeMs = 30000): Date | null {
  const [maintenant, setMaintenant] = useState<Date | null>(null);
  useEffect(() => {
    const tick = () => setMaintenant(new Date());
    tick();
    const id = setInterval(tick, periodeMs);
    // Un onglet en arrière-plan voit ses timers étranglés par le navigateur, et un
    // portable qui sort de veille a pu sauter la nuit entière : au retour au premier
    // plan on resynchronise tout de suite, sans attendre le prochain battement.
    const auRetour = () => { if (document.visibilityState === "visible") tick(); };
    document.addEventListener("visibilitychange", auRetour);
    window.addEventListener("focus", tick);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", auRetour);
      window.removeEventListener("focus", tick);
    };
  }, [periodeMs]);
  return maintenant;
}

/* Seau horaire de la timeline, lu à Paris. `new Date(...).getHours()` lisait le fuseau
 * de la MACHINE : le conteneur tourne en UTC, le HTML prérendu sortait donc avec un
 * en-tête de groupe « 9h » posé au-dessus de courses affichées à 11:03 — faux pour le
 * visiteur sans JavaScript comme pour un robot d'indexation, et mismatch d'hydratation
 * pour les autres. `formatToParts` plutôt que `format` : selon la version d'ICU,
 * `format` en fr-FR rend « 09 h » et non « 09 ». */
const HEURE_PARIS_H = new Intl.DateTimeFormat("fr-FR", {
  timeZone: "Europe/Paris",
  hour: "2-digit",
  hour12: false,
});
function heureBucket(iso: string): string {
  const h = HEURE_PARIS_H.formatToParts(new Date(iso)).find((p) => p.type === "hour")?.value ?? "0";
  return `${Number(h)}h`;
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

function DayStrip({ selected, jourCourant, onSelect }: { selected: Date; jourCourant: string; onSelect: (d: Date) => void }) {
  // Le jour vient du parent, il n'est plus relu ici. Un `jourParis()` appelé au rendu
  // donnait le jour de GÉNÉRATION du HTML côté serveur et le vrai jour côté navigateur :
  // sur un HTML servi depuis le cache après minuit, la pastille « Auj. » se posait sur
  // hier — et le texte différait entre les deux rendus (mismatch d'hydratation).
  const today = new Date(`${jourCourant}T12:00:00`);
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
    <div ref={scrollRef} className={cn("-mx-4 flex gap-2 overflow-x-auto px-4 pb-2 pt-0.5 sm:mx-0 sm:px-0", HIDE_SCROLLBAR)}>
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
              "group flex min-w-[58px] shrink-0 flex-col items-center justify-center rounded-2xl px-3.5 py-2.5 ring-1 transition-all hover:-translate-y-0.5 active:scale-[.97]",
              isSel
                ? "bg-stone-900 text-white ring-stone-900 shadow-[0_8px_18px_-10px_rgba(17,24,39,.7)]"
                : isToday
                ? "bg-white text-gray-800 ring-amber-300 shadow-[inset_0_1px_0_#fff,0_1px_2px_rgba(17,24,39,.05),0_8px_18px_-14px_rgba(146,64,14,.5)]"
                : "bg-white text-gray-700 ring-[#ECE7DC] shadow-[inset_0_1px_0_#fff,0_1px_2px_rgba(17,24,39,.05),0_8px_18px_-14px_rgba(17,24,39,.4)] hover:ring-stone-300",
            )}
          >
            <span className={cn("text-[10px] font-bold uppercase tracking-wide leading-none", isSel ? "text-white/70" : isToday ? "text-amber-700" : "text-gray-600")}>
              {topLabel}
            </span>
            <span className="text-xl font-extrabold tabular-nums leading-none mt-1.5" style={{ fontFamily: "var(--font-space-grotesk), sans-serif" }}>{format(d, "d")}</span>
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
  const fiche = `/courses/${course.course_id}`;
  const minutes = useMinutesAvant(course.date_heure, course.statut);
  // Anneau : plein à une heure du départ, vide au départ.
  const R = 44, C = 2 * Math.PI * R;
  const part = minutes == null ? (isLive ? 1 : 0) : Math.max(0.02, Math.min(1, minutes / 60));
  return (
    // Liseré doré animé : un dégradé conique qui tourne DERRIÈRE la carte, masqué
    // partout sauf sur 1,5 px de bord.
    <div className="bt-lisere relative rounded-[18px] p-[1.5px] shadow-[0_22px_44px_-26px_rgba(146,64,14,.55)]">
    <section aria-label="Prochaine course" className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-amber-50 via-white to-white">
      <span aria-hidden className="absolute inset-y-4 left-0 w-1 rounded-r-full bg-gradient-to-b from-amber-300 via-amber-500 to-amber-700" />
      <span
        aria-hidden
        className="pointer-events-none absolute max-[767px]:hidden"
        style={{
          // la silhouette reste entièrement dans la carte : aucun sabot rogné par l'overflow
          right: 210, bottom: 12, width: 280, height: 124, background: m.color, opacity: 0.07,
          WebkitMaskImage: `url(${url})`, maskImage: `url(${url})`,
          WebkitMaskRepeat: "no-repeat", maskRepeat: "no-repeat",
          WebkitMaskPosition: "center", maskPosition: "center",
          WebkitMaskSize: "contain", maskSize: "contain",
        }}
      />
      <div className="relative flex flex-wrap items-center gap-4 px-4 py-4 sm:gap-6 sm:px-6 sm:py-5">
        <div className="min-w-[230px] flex-1">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <span className="bt-brillance bg-clip-text text-[10.5px] font-bold uppercase tracking-[.16em] text-transparent">Prochaine course</span>
            {isLive ? <PastilleDirect libelle="En piste" /> : countdown ? (
              <Pastille className="bg-amber-50 text-amber-800 ring-amber-200">{countdown}</Pastille>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-2.5">
            <span className="rounded-md bg-stone-900 px-2 py-0.5 text-[12px] font-bold tabular-nums text-white" style={SG}>
              R{reunionNum}C{course.numero}
            </span>
            <span className="text-lg font-bold tracking-tight text-stone-900 sm:text-[22px]" style={SG}>{course.hippodrome_nom}</span>
          </div>
          {course.nom && <div className="mt-1 text-sm font-medium text-stone-600">{course.nom}</div>}
          <div className="mt-3 flex flex-wrap gap-1.5">
            <span className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-[12px] font-semibold ring-1 ring-inset" style={{ color: m.color, background: m.bg, boxShadow: `inset 0 0 0 1px ${m.ring}` }}>
              <DiscIcon discipline={course.discipline} w={26} h={18} />{titleCase(course.discipline)}
            </span>
            {[`${course.distance} m`, `${course.nb_partants} partants`].map((t) => (
              <span key={t} className="inline-flex items-center rounded-lg bg-white px-2.5 py-1 text-[12px] font-semibold text-stone-700 ring-1 ring-inset ring-[#ECE7DC]">{t}</span>
            ))}
            {course.est_quinte && <Pastille className="bg-amber-50 text-amber-800 ring-amber-200">Quinté+</Pastille>}
          </div>
        </div>
        <div className="flex w-full flex-row items-end justify-between gap-3.5 border-t border-[#EFE8D8] pt-4 sm:w-auto sm:flex-col sm:items-end sm:border-l sm:border-t-0 sm:pl-6 sm:pt-0">
          <div className="relative flex h-[104px] w-[104px] shrink-0 items-center justify-center" title={minutes != null ? `Départ dans ${Math.ceil(minutes)} min` : undefined}>
            <svg width="104" height="104" viewBox="0 0 104 104" className="absolute inset-0 -rotate-90" aria-hidden>
              <defs>
                <linearGradient id="bt-anneau" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" stopColor={isLive ? "#34D399" : "#FCD34D"} />
                  <stop offset="100%" stopColor={isLive ? "#059669" : "#D97706"} />
                </linearGradient>
              </defs>
              <circle cx="52" cy="52" r={R} fill="none" stroke="#F1EEE6" strokeWidth="6" />
              <circle cx="52" cy="52" r={R} fill="none" stroke="url(#bt-anneau)" strokeWidth="6" strokeLinecap="round"
                strokeDasharray={`${part * C} ${C}`} className="transition-[stroke-dasharray] duration-1000 ease-out" />
            </svg>
            <div className="relative flex h-[80px] w-[80px] flex-col items-center justify-center rounded-full bg-gradient-to-b from-white to-stone-50 shadow-[inset_0_1px_0_#fff,0_6px_14px_-8px_rgba(17,24,39,.35)]">
              <span className="text-[9.5px] font-bold uppercase tracking-[.14em] text-stone-500">{isLive ? "En piste" : "Départ"}</span>
              <span className="text-[21px] font-bold leading-none tracking-tight text-stone-900 tabular-nums" style={SG}>{formatTime(course.date_heure)}</span>
            </div>
          </div>
          <Link
            href={fiche}
            className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-xl bg-gradient-to-b from-amber-400 to-amber-600 px-3.5 py-2.5 text-[13px] font-bold sm:px-4 text-stone-900 shadow-[inset_0_1px_0_rgba(255,255,255,.45),0_8px_18px_-8px_rgba(217,119,6,.65)] transition-transform hover:-translate-y-0.5 active:scale-[.98]"
          >
            Voir la course <ChevronRight className="h-4 w-4" />
          </Link>
        </div>
      </div>
      {/* Accès directs aux onglets de la fiche : le pronostic, les partants, le plan. */}
      <nav aria-label="Accès rapide à la course" className="relative flex flex-wrap gap-2 border-t border-[#EFE8D8] bg-white/60 px-4 py-2.5 sm:px-6">
        {[["synthese", "Pronostic"], ["partants", "Partants"], ["plan", "Plan de mise"]].map(([cle, lib]) => (
          <Link
            key={cle}
            href={`${fiche}#${cle}`}
            className="inline-flex shrink-0 items-center gap-1 rounded-lg bg-white px-3 py-1.5 text-[12.5px] font-semibold text-amber-800 ring-1 ring-inset ring-amber-200 shadow-[inset_0_1px_0_#fff,0_1px_2px_rgba(146,64,14,.12)] transition-colors hover:bg-amber-50"
          >
            {lib}<span aria-hidden>›</span>
          </Link>
        ))}
      </nav>
    </section>
    </div>
  );
}

/* ─── Bandeau value bets actifs (funnel Free, décision 2026-08-16) ─────────
   Compteur AGRÉGÉ honnête (vrai COUNT(*) côté backend, endpoint public/léger
   /value-bets/compteur) — jamais le détail (cheval/course/cote) d'un value bet
   à un compte non abonné. Visible tant que l'utilisateur n'est pas déjà payant
   (free/decouverte ou visiteur non connecté) : donne un signal de ce qui se
   joue EN CE MOMENT sans casser le paywall. */
function ValueBetsCompteurBanner({ initial, href = "/tarifs", libelle = "Visibles dès Standard" }: { initial?: { count: number; niveau_min: number } | null; href?: string; libelle?: string }) {
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
      href={href}
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
        {libelle} <ChevronRight className="h-3.5 w-3.5" />
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

function TimelineRow({ course, reunionNum, vbCount, apercu, delay, onOuvrir }: { course: CourseSummary; reunionNum: number; vbCount?: number; apercu?: ApercuCourse; delay: number; onOuvrir?: () => void }) {
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
      /* Identifiant stable de la ligne : c'est lui qui permet de ramener le lecteur
         exactement là où il était quand il revient d'une fiche course. */
      id={`course-${course.course_id}`}
      onClick={onOuvrir}
      className={cn(
        "bt-apparition group relative flex scroll-mt-28 items-center gap-2.5 overflow-hidden rounded-2xl px-3 py-3 no-underline ring-1 transition-all duration-200 active:scale-[.99] sm:gap-3 sm:px-4",
        isDone
          ? "ring-[#E9E6DC] hover:ring-stone-300"
          : "ring-[#ECE7DC] shadow-[inset_0_1px_0_#fff,0_1px_2px_rgba(17,24,39,.05),0_12px_28px_-22px_rgba(17,24,39,.45)] hover:-translate-y-0.5 hover:ring-amber-300 hover:shadow-[inset_0_1px_0_#fff,0_2px_4px_rgba(17,24,39,.05),0_22px_40px_-24px_rgba(146,64,14,.45)]",
      )}
      style={{ background: isLive ? "#F0FDF8" : isDone ? "#F5F4EF" : "#FFFFFF", ["--bt-delai" as string]: `${delay}s` }}
    >
      <span className="absolute inset-y-3 left-0 w-1 rounded-r-full" style={{ background: isLive ? "linear-gradient(180deg,#34D399,#059669)" : !isDone && course.est_quinte ? "linear-gradient(180deg,#FCD34D,#D97706)" : "transparent" }} />
      <div className="flex w-10 flex-shrink-0 flex-col items-center sm:w-11">
        <span className={cn("text-base font-bold leading-none tabular-nums", isLive ? "text-emerald-700" : isDone ? "text-gray-600 line-through decoration-gray-300" : "text-gray-900")} style={{ fontFamily: "var(--font-space-grotesk), sans-serif" }}>
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
          <span className={cn("inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-bold tabular-nums ring-1", codeCls)} style={{ fontFamily: "var(--font-space-grotesk), sans-serif" }}>
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
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {apercu.confiance != null && (
              <span
                className="rounded-full border border-gray-200 bg-white px-2 py-0.5 text-[10px] font-semibold text-gray-600 tabular-nums"
                title="Accord des 3 modèles (entre eux et avec le marché) sur le n°1 de cette course. Ce n'est pas sa chance de gagner."
              >
                <span className="sm:hidden">accord {apercu.confiance}/100</span>
                <span className="hidden sm:inline">accord des modèles {apercu.confiance}/100</span>
              </span>
            )}
            {apercu.accord_marche === false && (
              <span
                title="Le n°1 du modèle n'est pas le favori des parieurs sur cette course"
                className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700"
              >
                <span className="sm:hidden">≠ marché</span>
                <span className="hidden sm:inline">ne suit pas le marché</span>
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

/* ─── Groupement par heure ──────────────────────────────── */
type ItemCourse = { course: CourseSummary; reunionNum: number };

function grouperParHeure(items: ItemCourse[]): Array<[string, ItemCourse[]]> {
  const map = new Map<string, ItemCourse[]>();
  for (const it of items) {
    const key = heureBucket(it.course.date_heure);
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(it);
  }
  return Array.from(map.entries());
}

const estPassee = (c: CourseSummary) => c.statut === "termine" || c.statut === "annule";

/* ─── Mémoire de position (retour depuis une fiche course) ──
 * Le retour arrière rouvrait le programme TOUT EN HAUT : `DefilementHaut` remet la
 * page à zéro à chaque changement de chemin, et `history.scrollRestoration` est
 * volontairement en « manual » (une position restaurée par le navigateur n'a aucun
 * rapport avec une page dont le contenu arrive après le premier rendu). Le lecteur
 * devait donc refaire défiler les 40 courses déjà courues pour retrouver la suivante.
 *
 * On mémorise donc nous-mêmes, au clic, la course ouverte et la position — puis on y
 * revient une fois la liste posée. Deux `requestAnimationFrame` : le premier laisse
 * React rendre la liste, le second laisse le navigateur en calculer la hauteur ; c'est
 * aussi ce qui fait passer ce saut APRÈS la remise à zéro de `DefilementHaut`.
 * `sessionStorage` et non l'état React : le composant est démonté entre les deux pages.
 */
const CLE_RETOUR = "programme:retour";
type RetourProgramme = { jour: string; courseId: string; y: number; termines: boolean };

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
  const { user, loading: authLoading } = useAuth();
  const maintenant = useHorloge(15000);
  /* Jour de Paris VIVANT. Il part de `initialJour` — la valeur exacte contenue dans le
     HTML servi, donc zéro mismatch d'hydratation — puis se corrige au premier battement
     d'horloge. C'est ce qui rattrape un HTML sorti du cache (ISR ou cache navigateur :
     Next annonce `stale-while-revalidate` sur cette page) ainsi qu'un onglet resté
     ouvert par-dessus minuit. */
  const [jourCourant, setJourCourant] = useState(initialJour);
  useEffect(() => {
    if (!maintenant) return;
    const j = jourParis(0, maintenant);
    setJourCourant((prec) => (prec === j ? prec : j));
  }, [maintenant]);

  const [selectedDate, setSelectedDate] = useState(() => new Date(`${initialJour}T12:00:00`));
  /* Tant que le visiteur n'a pas choisi une journée lui-même, la page suit le jour
     courant. Sans cela, `selectedDate` restait sur le jour figé dans le HTML : la page
     ouvrait sur hier, `isToday` valait faux, et avec lui tombaient le rafraîchissement
     toutes les minutes, les value bets et le bandeau « prochaine course ». */
  const jourChoisiALaMain = useRef(false);
  useEffect(() => {
    if (jourChoisiALaMain.current) return;
    setSelectedDate((prec) =>
      format(prec, "yyyy-MM-dd") === jourCourant ? prec : new Date(`${jourCourant}T12:00:00`),
    );
  }, [jourCourant]);
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
  /* Bloc « déjà courues » : replié par défaut. Valeur fixe au premier rendu (pas de
     lecture de `sessionStorage` ici) — l'état initial doit être identique côté serveur
     et côté navigateur, sinon l'hydratation diverge. */
  const [terminesOuverts, setTerminesOuverts] = useState(false);
  /* Jour actuellement affiché, lisible depuis un effet de montage sans le prendre en
     dépendance. */
  const jourAffiche = useRef(initialJour);
  // Mise à jour dans un effet, jamais pendant le rendu : cet effet-ci est déclaré avant
  // celui de restauration, donc la valeur est déjà à jour quand il la lit au montage.
  useEffect(() => { jourAffiche.current = format(selectedDate, "yyyy-MM-dd"); }, [selectedDate]);

  const isToday = format(selectedDate, "yyyy-MM-dd") === jourCourant;
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
    // Le navigateur étrangle les timers d'un onglet en arrière-plan : après une heure
    // masquée, l'intervalle d'une minute n'a pas tourné une minute sur deux et la page
    // se rouvrait sur des statuts périmés. Un retour au premier plan force la relecture.
    const auRetour = () => { if (isToday && document.visibilityState === "visible") load(false); };
    document.addEventListener("visibilitychange", auRetour);
    return () => {
      cancelled = true;
      if (iv) clearInterval(iv);
      document.removeEventListener("visibilitychange", auRetour);
    };
  }, [selectedDate, isToday]);

  const selectDate = useCallback((d: Date) => {
    setDiscFilter("Tous");
    setReunionFilter("all");
    setHippoSearch("");
    setVbOnly(false);
    setTerminesOuverts(false);
    // Revenir sur aujourd'hui rend la main au suivi automatique du jour ; choisir une
    // autre journée le suspend, sinon le passage de minuit arracherait le visiteur de
    // la journée qu'il consulte.
    jourChoisiALaMain.current = format(d, "yyyy-MM-dd") !== jourCourant;
    setSelectedDate(d);
  }, [jourCourant]);

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

  /* Prochaine course (toutes réunions)
   *
   * Le bandeau ne bascule plus à l'ARRIVÉE de la course précédente, mais à son DÉPART :
   * c'est le seul moment qui intéresse le lecteur, et le résultat met plusieurs minutes
   * à remonter (statut, puis rapports). Deux tolérances traînaient là : 20 min après
   * l'heure annoncée pour une course « à venir », 60 min pour une course « en cours ».
   * En fin de journée elles cumulaient et le bandeau annonçait une course déjà courue
   * pendant que trois autres partaient.
   *
   * Règle : est « prochaine » la première course dont le départ n'est PAS passé. Le
   * statut ne sert plus qu'à écarter les courses finies ou annulées — il n'est jamais
   * lu seul, il se croise avec `date_heure` (même règle que côté serveur).
   *
   * Seule marge conservée : 30 s, l'imprécision de l'horloge du navigateur. Et si plus
   * aucune course n'est à venir (dernière de la journée), on retombe sur celle qui est
   * réellement en piste — au plus 30 min après son départ, au-delà c'est une donnée
   * bloquée, pas une course.
   */
  const nextRace = useMemo(() => {
    if (!programme || !isToday) return null;
    const t = maintenant ? maintenant.getTime() : null;
    const MARGE_HORLOGE_MS = 30 * 1000;
    const TOLERANCE_EN_COURS_MS = 30 * 60 * 1000;
    const aVenir: ItemCourse[] = [];
    const enPiste: ItemCourse[] = [];
    for (const r of programme.reunions) for (const c of r.courses) {
      if (estPassee(c)) continue;
      const item = { course: c, reunionNum: r.numero };
      if (t === null) { aVenir.push(item); continue; }
      const depart = new Date(c.date_heure).getTime();
      if (depart + MARGE_HORLOGE_MS >= t) aVenir.push(item);
      else if (c.statut === "en_cours" && depart + TOLERANCE_EN_COURS_MS >= t) enPiste.push(item);
    }
    const parHeure = (a: ItemCourse, b: ItemCourse) =>
      new Date(a.course.date_heure).getTime() - new Date(b.course.date_heure).getTime();
    aVenir.sort(parHeure);
    enPiste.sort(parHeure);
    return aVenir[0] ?? enPiste[enPiste.length - 1] ?? null;
  }, [programme, isToday, maintenant]);

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

  /* Une journée compte jusqu'à 45 courses, et à 17 h les trois quarts sont courues.
     Dépliées, elles occupaient tout le haut de la liste : pour atteindre la prochaine
     course il fallait faire défiler tout ce qui était joué — le reproche n°1 sur mobile.
     Elles vivent donc dans un bloc REPLIÉ, placé en HAUT de la timeline : replié il ne
     coûte qu'une ligne avant les courses à venir, et l'accès aux arrivées ne demande
     plus de descendre toute la fin de journée.

     Repliées, pas retirées : le HTML garde les liens vers les fiches course, seul
     chemin d'exploration vers elles (les ~17 000 archives n'ont pas d'autre entrée).
     Et sur une journée entièrement courue — une date passée — il n'y a rien à replier,
     sinon la page s'ouvrirait vide. */
  const flatAVenir = useMemo(() => flat.filter((it) => !estPassee(it.course)), [flat]);
  const flatTermines = useMemo(() => flat.filter((it) => estPassee(it.course)), [flat]);
  const replierTermines = flatAVenir.length > 0 && flatTermines.length > 0;

  /* Groupes horaires */
  const groupesAVenir = useMemo(
    () => grouperParHeure(replierTermines ? flatAVenir : flat),
    [replierTermines, flatAVenir, flat],
  );
  const groupesTermines = useMemo(
    () => (replierTermines ? grouperParHeure(flatTermines) : []),
    [replierTermines, flatTermines],
  );

  /* Au clic sur une course : on note où on était, et si le bloc des courses courues
     était ouvert. Écriture protégée — en navigation privée `sessionStorage` peut
     lever, et on ne casse pas une page pour un confort de défilement. */
  const memoriserRetour = useCallback((courseId: string) => {
    try {
      sessionStorage.setItem(
        CLE_RETOUR,
        JSON.stringify({
          jour: format(selectedDate, "yyyy-MM-dd"),
          courseId,
          y: window.scrollY,
          termines: terminesOuverts,
        } as RetourProgramme),
      );
    } catch { /* position non mémorisée : la page s'ouvrira en haut, comme avant */ }
  }, [selectedDate, terminesOuverts]);

  /* Retour effectif à la ligne quittée.
   *
   * Effet de MONTAGE, sans dépendances : c'est ce qui l'a fait marcher. Piloté par les
   * données (`loading`, `flat.length`, `selectedDate`), il se relançait — et son
   * nettoyage annulait la boucle de saut avant même son premier essai, de sorte que le
   * saut n'avait jamais lieu (mesuré : « nettoyage 0 »). Il n'a de toute façon besoin
   * d'aucun état : il cherche une ligne dans le DOM, et le DOM sait quand elle arrive.
   *
   * Trois autres pièges, tous mesurés ici :
   *  · une référence d'élément prise dans l'effet ne survit pas à l'hydratation (React
   *    remplace les nœuds) — la ligne est donc RELUE à chaque essai ;
   *  · pendant le streaming, le HTML existe EN DOUBLE, une copie encore dans le
   *    conteneur masqué de React. `getElementById` renvoyait cette copie-là et rien ne
   *    bougeait : on cherche l'instance VISIBLE ;
   *  · `requestAnimationFrame` ne bat pas dans un onglet en arrière-plan — la boucle
   *    tourne donc sur une minuterie.
   *
   * Elle s'arrête dès que le lecteur touche à la molette ou au clavier : on ne se bat
   * jamais contre son défilement à lui.
   */
  useEffect(() => {
    let pos: RetourProgramme | null = null;
    try {
      const brut = sessionStorage.getItem(CLE_RETOUR);
      // Consommée tout de suite : un retour, une restauration. Sans cela un
      // rechargement ultérieur rejouerait le même saut.
      sessionStorage.removeItem(CLE_RETOUR);
      if (brut) {
        const lu = JSON.parse(brut) as RetourProgramme;
        if (lu?.courseId && lu?.jour) pos = lu;
      }
    } catch { /* stockage indisponible ou valeur illisible : la page s'ouvre en haut */ }
    if (!pos) return;
    if (pos.jour !== jourAffiche.current) return;
    if (pos.termines) setTerminesOuverts(true);

    const { courseId, y } = pos;
    let annule = false;
    let essais = 0;
    let atteint = false;
    let minuterie: ReturnType<typeof setTimeout> | null = null;
    const abandonner = () => { annule = true; if (minuterie) clearTimeout(minuterie); };
    window.addEventListener("wheel", abandonner, { passive: true, once: true });
    window.addEventListener("touchstart", abandonner, { passive: true, once: true });
    window.addEventListener("keydown", abandonner, { once: true });

    const tenter = () => {
      if (annule) return;
      const instances = document.querySelectorAll<HTMLElement>(`[id="course-${CSS.escape(courseId)}"]`);
      // `offsetParent` nul = ligne masquée : soit la copie de streaming, soit une course
      // terminée pendant la visite, passée dans le bloc replié.
      const cible = Array.from(instances).find((el) => el.offsetParent);
      if (cible) {
        const rect = cible.getBoundingClientRect();
        const vise = Math.max(0, rect.top + window.scrollY - window.innerHeight / 2 + rect.height / 2);
        if (Math.abs(window.scrollY - vise) > 8) {
          window.scrollTo({ top: vise, behavior: "instant" as ScrollBehavior });
        }
        atteint = true;
      }
      // ~1,5 s de tentatives : le temps que l'hydratation finisse, que le programme
      // arrive si le rendu serveur ne l'avait pas fourni, et que les hauteurs se posent.
      if (++essais < 30) { minuterie = setTimeout(tenter, 50); return; }
      // Budget épuisé sans jamais voir la ligne : soit elle est repliée (course terminée
      // entre-temps) et rester en haut, sur les courses à venir, est exactement ce qu'on
      // venait chercher ; soit la liste a changé et les pixels restent le seul repère.
      if (!atteint && instances.length === 0 && y > 0) {
        window.scrollTo({ top: y, behavior: "instant" as ScrollBehavior });
      }
    };
    minuterie = setTimeout(tenter, 0);

    // Pas de nettoyage qui annule la boucle : en développement React monte, démonte et
    // remonte chaque composant, et ce nettoyage-là tuait la restauration. La boucle
    // s'éteint d'elle-même en 1,5 s, et elle ne déplace la page que si elle retrouve
    // CETTE ligne-là, visible — sur une autre page, elle ne trouve rien.
    return () => {
      window.removeEventListener("wheel", abandonner);
      window.removeEventListener("touchstart", abandonner);
      window.removeEventListener("keydown", abandonner);
    };
  }, []);

  const dayName = cap(format(selectedDate, "EEEE", { locale: fr }));
  const restDate = format(selectedDate, "d MMMM yyyy", { locale: fr });

  const resetFilters = () => { setDiscFilter("Tous"); setReunionFilter("all"); setHippoSearch(""); setVbOnly(false); };

  /* Un seul rendu de groupes, servi deux fois : la liste du haut et le bloc replié.
     `anime` est coupé pour le bloc replié — l'animation d'entrée se rejouerait à
     chaque ouverture, sur des dizaines de lignes d'un coup. */
  const rendreGroupes = (groupes: Array<[string, ItemCourse[]]>, anime: boolean) => (
    <div className="space-y-7">
      {groupes.map(([hour, items]) => (
        <div key={hour} className="relative">
          <div className="mb-3.5 flex items-center gap-3.5">
            <div
              className="relative z-[2] flex h-10 w-10 items-center justify-center rounded-xl text-[13px] font-bold text-white sm:h-[46px] sm:w-[46px] sm:rounded-2xl sm:text-[15px]"
              style={{ fontFamily: "var(--font-space-grotesk), sans-serif", background: "linear-gradient(180deg,#FBBF24,#D97706)", boxShadow: "inset 0 1px 0 rgba(255,255,255,.45), 0 6px 14px -6px rgba(217,119,6,.6)" }}
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
                delay={anime ? Math.min(i, 8) * 0.05 : 0}
                onOuvrir={() => memoriserRetour(course.course_id)}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );

  return (
    <div
      className="min-h-screen"
      style={{
        background:
          "radial-gradient(ellipse at 20% 0%,rgba(245,158,11,.06) 0%,transparent 48%),radial-gradient(ellipse at 85% 8%,rgba(217,119,6,.04) 0%,transparent 42%),linear-gradient(180deg,#FFFDF6 0%,#FAFAF8 40%)",
      }}
    >
      {/* @keyframes local (fadeUp) */}
      <style>{`
@keyframes fadeUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:none}}
@keyframes btDerive1{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(40px,18px) scale(1.12)}}
@keyframes btDerive2{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(-36px,-14px) scale(1.08)}}
@keyframes btDerive3{0%,100%{transform:translate(0,0)}50%{transform:translate(24px,-20px)}}
@keyframes btTour{to{transform:rotate(360deg)}}
@keyframes btBrille{0%{background-position:0% 50%}100%{background-position:200% 50%}}
@keyframes btPop{from{opacity:0;transform:translateY(10px) scale(.96)}to{opacity:1;transform:none}}
@keyframes btPouls{0%{box-shadow:0 0 0 0 rgba(217,119,6,.45)}70%{box-shadow:0 0 0 10px rgba(217,119,6,0)}100%{box-shadow:0 0 0 0 rgba(217,119,6,0)}}
.bt-halo-a{animation:btDerive1 14s ease-in-out infinite}
.bt-halo-b{animation:btDerive2 17s ease-in-out infinite}
.bt-halo-c{animation:btDerive3 12s ease-in-out infinite}
.bt-brillance{background-image:linear-gradient(90deg,#92400E 0%,#D97706 25%,#F59E0B 50%,#D97706 75%,#92400E 100%);background-size:200% 100%;animation:btBrille 6s linear infinite}
.bt-pop{animation:btPop .6s cubic-bezier(.16,1,.3,1) both}
.bt-pop:nth-child(2){animation-delay:.07s}.bt-pop:nth-child(3){animation-delay:.14s}.bt-pop:nth-child(4){animation-delay:.21s}
.bt-lisere{isolation:isolate;overflow:hidden}
.bt-lisere::before{content:"";position:absolute;inset:-60%;z-index:-1;background:conic-gradient(from 0deg,#F59E0B,#FDE68A,#ECE7DC 30%,#ECE7DC 55%,#D97706 75%,#F59E0B);animation:btTour 7s linear infinite}
.bt-maintenant-point{animation:btPouls 2s ease-out infinite}
.bt-apparition{animation:fadeUp .5s cubic-bezier(.16,1,.3,1) var(--bt-delai,0s) both}
@supports (animation-timeline: view()){
  .bt-apparition{animation:fadeUp linear both;animation-timeline:view();animation-range:entry 0% entry 55%}
}
@media (prefers-reduced-motion:reduce){*{animation:none!important}.bt-lisere::before{background:#ECE7DC}}
`}</style>

      <div className="mx-auto max-w-4xl space-y-5 px-4 py-6 sm:space-y-6 sm:px-6 sm:py-8 lg:px-8">

        {/* ── EN-TÊTE : panneau teinté et plat, comme les bandeaux de la fiche course ── */}
        <header className="relative isolate overflow-hidden rounded-[22px] bg-[#F3EDE0] px-4 pb-4 pt-5 ring-1 ring-inset ring-[#E6DCC6] sm:px-6 sm:pb-5 sm:pt-6">
          {/* Halos dorés qui dérivent lentement : de la vie, sans fond sombre. */}
          <span aria-hidden className="bt-halo-a pointer-events-none absolute -left-16 -top-20 -z-10 h-56 w-56 rounded-full bg-amber-300/45 blur-3xl" />
          <span aria-hidden className="bt-halo-b pointer-events-none absolute -bottom-24 right-10 -z-10 h-60 w-60 rounded-full bg-orange-200/60 blur-3xl" />
          <span aria-hidden className="bt-halo-c pointer-events-none absolute left-1/3 top-6 -z-10 h-40 w-40 rounded-full bg-yellow-200/50 blur-3xl" />
          <span
            aria-hidden
            className="pointer-events-none absolute max-[479px]:hidden"
            style={{
              right: 26, top: 14, width: 150, height: 92, opacity: 0.1, background: "#92400E",
              WebkitMaskImage: "url(/img/logo-horse.png)", maskImage: "url(/img/logo-horse.png)",
              WebkitMaskRepeat: "no-repeat", maskRepeat: "no-repeat",
              WebkitMaskPosition: "center", maskPosition: "center",
              WebkitMaskSize: "contain", maskSize: "contain",
            }}
          />
          <div className="relative">
            <div className="mb-2.5 flex items-center justify-between gap-3">
              <div className="inline-flex items-center gap-2 text-[11px] font-bold uppercase tracking-[.16em] text-amber-700">
                <span className="h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse" />
                Programme du jour
              </div>
              {!isToday && (
                <button
                  onClick={() => selectDate(new Date(`${jourCourant}T12:00:00`))}
                  className="shrink-0 rounded-xl bg-gradient-to-b from-amber-400 to-amber-600 px-4 py-2 text-sm font-bold text-stone-900 shadow-[inset_0_1px_0_rgba(255,255,255,.45),0_6px_14px_-6px_rgba(217,119,6,.6)]"
                >
                  Aujourd&apos;hui
                </button>
              )}
            </div>

            {/* Une journée passée consultée depuis le sélecteur n'a pas d'adresse à elle :
                l'URL reste /programme. Sa page permanente, c'est celle de ses arrivées —
                elle porte les mêmes courses, plus les rapports, et elle est indexable. */}
            {format(selectedDate, "yyyy-MM-dd") < jourCourant && (
              <a
                href={`/resultats/${format(selectedDate, "yyyy-MM-dd")}`}
                className="mb-3 inline-flex items-center gap-1.5 rounded-lg bg-white px-3 py-1.5 text-[12.5px] font-semibold text-amber-800 ring-1 ring-inset ring-amber-200 transition-colors hover:bg-amber-50"
              >
                Arrivées et rapports du {format(selectedDate, "d MMMM yyyy", { locale: fr })} →
              </a>
            )}

            {/* Le `h1` nomme le contenu (« Programme PMU ») et porte la date : c'est le
                titre que lisent un lecteur arrivé par un lien et un moteur de recherche. */}
            <h1 className="text-[26px] font-bold leading-[1.08] tracking-tight sm:text-[34px] sm:leading-[1.04]" style={SG}>
              <span className="bt-brillance bg-clip-text text-transparent">Programme PMU</span>
              <span className="text-stone-800"> — {dayName.toLowerCase()} {restDate}</span>
            </h1>

            {programme && programme.nb_courses > 0 && (() => {
              const enDirect = allCourses.filter((c) => c.statut === "en_cours").length;
              const aVenir = allCourses.filter((c) => !estPassee(c) && c.statut !== "en_cours").length;
              const tuiles: Array<{ n: number; l: string; ton?: string }> = [
                { n: programme.nb_courses, l: "Courses" },
                { n: programme.reunions.length, l: "Réunions" },
                ...(isToday ? [
                  { n: enDirect, l: "En direct", ton: enDirect > 0 ? "text-emerald-700" : undefined },
                  { n: aVenir, l: "À venir", ton: "text-amber-700" },
                ] : []),
              ];
              return (
                <div className={cn("mt-4 grid gap-2", tuiles.length === 4 ? "grid-cols-2 min-[360px]:grid-cols-4" : "grid-cols-2")}>
                  {tuiles.map((t) => <TuileCompteur key={t.l} n={t.n} libelle={t.l} ton={t.ton} />)}
                </div>
              );
            })()}
          </div>
        </header>

        {/* ── Sélecteur de jour ── */}
        <DayStrip selected={selectedDate} jourCourant={jourCourant} onSelect={selectDate} />

        {/* ── Prochaine course ── */}
        {nextRace && <NextRaceBanner item={nextRace} />}

        {/* ── Bandeau value bets actifs (Free/Découverte + visiteurs non connectés) ── */}
        {!isPaid && (
          <ValueBetsCompteurBanner
            initial={initialCompteurVB}
            // Anonyme : l'étape d'avant l'abonnement, c'est le compte gratuit (et son
            // essai). Compte gratuit avec essai à prendre : il est offert, pas « dès 12 € ».
            href={user ? "/tarifs" : "/inscription?plan=standard&suite=%2Fprogramme"}
            libelle={!user ? "Créer un compte gratuit" : peutDemarrerEssai(user) ? "Essai 7 jours offert" : "Visibles dès Standard"}
          />
        )}

        {/* ── Contrôles ── */}
        {programme && programme.nb_courses > 0 && (
          <div className={cn(CARTE_CLS, "space-y-3 p-3.5 sm:p-4")}>
            <div className="flex items-center justify-between gap-2">
              <p className="m-0 inline-flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-[.1em] text-stone-500">
                <Filter className="h-3.5 w-3.5" aria-hidden /> Filtrer les courses
              </p>
              {(discFilter !== "Tous" || reunionFilter !== "all" || hippoSearch || vbOnly) && (
                <button onClick={resetFilters} className="text-[12px] font-semibold text-amber-700 hover:underline">Tout effacer</button>
              )}
            </div>
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
                  className="w-full rounded-xl border border-[#E6DCC6] bg-[#FCFAF5] py-2.5 pl-9 pr-8 text-[13px] outline-none transition-all focus:border-amber-400 focus:bg-white focus:ring-2 focus:ring-amber-100"
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
                  style={{ fontFamily: "var(--font-space-grotesk), sans-serif" }}
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
                      <span style={{ fontFamily: "var(--font-space-grotesk), sans-serif", fontWeight: 700 }}>R{r.numero}</span>
                      {/* Pas d'`opacity-75` ici : le gris du bouton passé à 75 % donne
                          #78808A sur blanc, soit 3,99:1 — dernier échec de contraste du
                          site. La hiérarchie visuelle tient déjà sans lui : « R1 » est en
                          graisse 700, le nom de l'hippodrome en `font-medium`. */}
                      <span className="whitespace-nowrap font-medium">{r.hippodrome}</span>
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
            <button onClick={() => selectDate(new Date(`${jourCourant}T12:00:00`))} className="mt-1 text-sm font-medium text-amber-700 hover:underline">Revenir à aujourd&apos;hui</button>
          </div>
        ) : flat.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 py-16">
            <Filter className="h-8 w-8 text-gray-300" />
            <p className="text-sm text-gray-600">Aucune course ne correspond aux filtres</p>
            <button onClick={resetFilters} className="text-sm font-medium text-amber-700 hover:underline">Effacer les filtres</button>
          </div>
        ) : (
          /* ── TIMELINE ── */
          <div className="relative">
            <div className="absolute left-[19px] sm:left-[22px] top-4 bottom-4 w-0.5 rounded hidden sm:block" style={{ background: "linear-gradient(180deg,#FCD34D,#F59E0B,#D97706)", opacity: 0.35 }} />
            {/* Courses déjà courues — au-DESSUS de la timeline, repliées. Elles étaient
                en bas jusqu'au 2026-09-08 : y accéder demandait de faire défiler toute
                la fin de journée à venir, alors qu'on les consulte pour l'arrivée et le
                bilan, juste après la course. En haut, elles sont à un clic.

                Repliées, pas retirées : le HTML garde les liens vers les fiches course,
                seul chemin d'exploration vers elles (les ~17 000 archives n'ont pas
                d'autre entrée). Un bouton et une classe `hidden`, et non un `details`
                natif : le repli d'un `details` fermé dépend de la feuille de style du
                navigateur (vérifié : dans un moteur où elle manque, les 14 lignes
                restaient visibles et le repli ne servait à rien). Ici c'est notre CSS
                qui décide, partout pareil. */}
            {replierTermines && (
              <div className="mb-7">
                <button
                  type="button"
                  onClick={() => setTerminesOuverts((v) => !v)}
                  aria-expanded={terminesOuverts}
                  aria-controls="courses-terminees"
                  className={cn(CARTE_CLS, "flex w-full items-center justify-between gap-3 px-4 py-3 text-left text-[13px] font-semibold text-gray-700 transition-transform active:scale-[.99]")}
                >
                  <span>
                    {flatTermines.length} course{flatTermines.length > 1 ? "s" : ""} déjà courue{flatTermines.length > 1 ? "s" : ""}
                  </span>
                  <span className="inline-flex items-center gap-1 text-[12px] font-medium text-amber-700">
                    {terminesOuverts ? "Masquer" : "Afficher"}
                    <ChevronRight className={cn("h-3.5 w-3.5 transition-transform", terminesOuverts && "rotate-90")} />
                  </span>
                </button>
                <div id="courses-terminees" className={cn("mt-5", !terminesOuverts && "hidden")}>
                  {rendreGroupes(groupesTermines, false)}
                </div>
              </div>
            )}

            {isToday && replierTermines && maintenant && (
              <div className="relative z-[2] mb-5 flex items-center gap-3" aria-label="Heure actuelle">
                <span className="bt-maintenant-point flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white ring-2 ring-amber-400 sm:h-[46px] sm:w-[46px] sm:rounded-2xl">
                  <span className="h-2.5 w-2.5 rounded-full bg-amber-500" />
                </span>
                <span className="text-[12px] font-bold uppercase tracking-[.12em] text-amber-800">
                  Maintenant · <span className="tabular-nums" style={SG}>{format(maintenant, "HH:mm")}</span>
                </span>
                <span className="h-px flex-1 bg-gradient-to-r from-amber-400 to-transparent" />
              </div>
            )}
            {rendreGroupes(groupesAVenir, true)}
          </div>
        )}

        {/* ── Visiteur anonyme : ce qu'un compte gratuit ouvre sur ces courses ── */}
        {!authLoading && !user && programme && programme.nb_courses > 0 && (
          <CompteGratuitCta
            icone={IconeMarcheDirect}
            titre="Suivez le marché des cotes en direct sur ces courses"
            texte="Créez votre compte gratuit en 30 secondes : l'évolution des cotes minute par minute, le classement de l'algorithme sur une course par jour et votre plan de mise."
            suite="/programme"
          />
        )}

        {/* ── Compte gratuit : l'essai de 7 jours, en un clic ── */}
        {!isPaid && user && peutDemarrerEssai(user) && isToday && programme && programme.nb_courses > 0 && (
          <div className="flex flex-wrap items-center justify-between gap-3.5 rounded-[20px] px-5 py-4" style={{ border: "1px solid rgba(16,185,129,.28)", background: "linear-gradient(135deg,#ECFDF5,#FFFBF0)" }}>
            <div className="min-w-[200px] flex-1">
              <p className="text-sm font-bold text-emerald-900">Paris de valeur de ce soir : 7 jours offerts</p>
              <p className="mt-1 text-xs text-emerald-800">Essai Standard gratuit — carte demandée, 0 € prélevé avant la fin de l&apos;essai.</p>
            </div>
            <CheckoutButton plan="standard" periodicite="monthly" label="Démarrer mon essai" size="default" className="flex-shrink-0" />
          </div>
        )}

        {/* ── Upsell (utilisateurs gratuits ayant déjà pris l'essai) ── */}
        {!isPaid && user && !peutDemarrerEssai(user) && isToday && programme && programme.nb_courses > 0 && (
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
