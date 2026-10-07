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
  ChevronRight, Trophy, Loader2, Zap, Search, X, Radio, Filter, Timer, CalendarClock,
  Sparkles, Users, Calculator, ArrowLeftRight,
} from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { TrendingUp as IconeMarcheDirect } from "lucide-react";
import { CompteGratuitCta } from "@/components/billing/CompteGratuitCta";
import { peutDebloquer } from "@/lib/auth";
import useSWR from "swr";
import { coursesApi, predictionsApi } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import { formatTime, cn } from "@/lib/utils";
import { jourParis } from "@/lib/seo";
import { BandeauOnglet, IconeTuile, Pastille, PastilleDirect, SG } from "@/components/courses/course-ui";

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
      const k = Math.min(1, Math.max(0, (t - t0) / dureeMs));
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
    // Tuile de verre sur le bandeau noir : reflet en haut, ombre douce en bas —
    // elle se lit comme un bloc posé, pas comme un aplat.
    <div className="bt-pop bt-tuile relative overflow-hidden rounded-2xl bg-gradient-to-b from-white/[.10] to-white/[.03] px-2.5 py-2.5 ring-1 ring-inset ring-white/10 shadow-[inset_0_1px_0_rgba(255,255,255,.14),0_1px_0_rgba(0,0,0,.55),0_16px_26px_-16px_rgba(0,0,0,.9)] backdrop-blur sm:px-4 sm:py-3">
      <span aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-amber-200/50 to-transparent" />
      <div className={cn("text-[22px] font-bold leading-none tabular-nums text-white sm:text-[28px]", ton)} style={SG}>{v}</div>
      <div className="mt-1 text-[11px] font-medium text-stone-400 sm:text-xs">{libelle}</div>
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

/* Secondes avant le départ, rafraîchies chaque seconde (null une fois parti ou
 * pour une course qui n'est plus à venir). Null au premier rendu : l'heure du
 * serveur et celle du navigateur ne doivent pas diverger à l'hydratation. */
function useSecondesAvant(targetDate: string, statut: string): number | null {
  const [s, setS] = useState<number | null>(null);
  useEffect(() => {
    if (statut !== "programme" && statut !== "a_venir") { setS(null); return; }
    const tick = () => {
      const d = differenceInSeconds(new Date(targetDate), new Date());
      setS(d > 0 ? d : null);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [targetDate, statut]);
  return s;
}

/* « 07:42 » sous une heure, « 1 h 12 » au-delà. */
function formatRebours(sec: number): string {
  if (sec >= 3600) {
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
    return `${h} h ${String(m).padStart(2, "0")}`;
  }
  const m = Math.floor(sec / 60), r = sec % 60;
  return `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
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
              // Jours en léger relief : un liseré sous chaque jour, qui s'efface quand
              // on appuie. Le jour choisi est noir, liseré doré.
              "group mb-1 flex min-w-[58px] shrink-0 flex-col items-center justify-center rounded-2xl px-3.5 py-2.5 ring-1 transition-all duration-150 hover:-translate-y-0.5 active:translate-y-px",
              isSel
                ? "bg-gradient-to-b from-stone-800 to-stone-950 text-white ring-stone-900 shadow-[inset_0_1px_0_rgba(255,255,255,.14),0_1px_0_#B45309,0_12px_20px_-10px_rgba(17,24,39,.8)] active:shadow-[inset_0_1px_0_rgba(255,255,255,.14),0_1px_0_#B45309]"
                : isToday
                ? "bg-gradient-to-b from-white to-[#FBF8F1] text-gray-800 ring-amber-300 shadow-[inset_0_1px_0_#fff,0_1px_0_#F5D48A,0_10px_18px_-12px_rgba(146,64,14,.5)] active:shadow-[inset_0_1px_0_#fff,0_1px_0_#F5D48A]"
                : "bg-gradient-to-b from-white to-[#FBF8F1] text-gray-700 ring-[#ECE7DC] shadow-[inset_0_1px_0_#fff,0_1px_0_#E6DFD0,0_10px_18px_-12px_rgba(17,24,39,.35)] hover:ring-stone-300 active:shadow-[inset_0_1px_0_#fff,0_1px_0_#E6DFD0]",
            )}
          >
            <span className={cn("text-[10px] font-bold uppercase tracking-wide leading-none", isSel ? "text-amber-300" : isToday ? "text-amber-700" : "text-gray-600")}>
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
/* Partants RÉELS : `nb_partants` du programme compte les déclarés, non-partants
 * compris. L'aperçu du jour, lui, compte les chevaux notés par le modèle parmi ceux
 * qui courent (`non_partant = false`, une prédiction par partant) : c'est le chiffre
 * de la fiche course. Repli sur les déclarés tant que l'aperçu n'est pas arrivé. */
function partantsReels(course: CourseSummary, apercu?: ApercuCourse): number {
  const notes = apercu?.analysee ? apercu.nb_notes : 0;
  return notes > 0 ? Math.min(notes, course.nb_partants || notes) : course.nb_partants;
}

function NextRaceBanner({ item, apercu }: { item: { course: CourseSummary; reunionNum: number }; apercu?: ApercuCourse }) {
  const { course, reunionNum } = item;
  const m = discMeta(course.discipline);
  const isLive = course.statut === "en_cours";
  const fiche = `/courses/${course.course_id}`;
  const minutes = useMinutesAvant(course.date_heure, course.statut);
  const secondes = useSecondesAvant(course.date_heure, course.statut);
  // Anneau : plein à une heure du départ, vide au départ.
  const R = 44, C = 2 * Math.PI * R;
  const part = minutes == null ? (isLive ? 1 : 0) : Math.max(0.02, Math.min(1, minutes / 60));
  const ACCES: Array<[string, string, string, typeof Timer]> = [
    ["synthese", "Pronostic", "le classement de l'IA", Sparkles],
    ["partants", "Partants", "la fiche de chaque cheval", Users],
    ["plan", "Plan de mise", "vos paris selon le budget", Calculator],
  ];
  return (
    // Cercle doré : un dégradé conique tourne derrière la carte et n'apparaît que
    // sur 2 px de bord. Toutes ses teintes sont dorées — le tour reste doré et
    // d'épaisseur égale partout, seul le reflet clair se déplace.
    <div className="bt-lisere relative rounded-[18px] p-[2px] shadow-[0_22px_44px_-26px_rgba(146,64,14,.6)]">
    <section aria-label="Prochaine course" className="overflow-hidden rounded-[16px] bg-white">
      {/* Bandeau noir : il porte l'identité de la course et l'action principale. Noir
          et or plutôt que l'aplat jaune d'avant, trop criard en haut de page. */}
      <div className="relative isolate flex flex-wrap items-center gap-x-3 gap-y-2.5 overflow-hidden bg-[radial-gradient(120%_140%_at_100%_0%,rgba(245,158,11,.22)_0%,transparent_55%),linear-gradient(160deg,#241D14_0%,#0E0C09_70%)] px-4 py-3 sm:px-5">
        <IconeTuile icone={Timer} className="from-amber-300 to-amber-500 text-stone-900 ring-amber-200/60 shadow-[inset_0_1px_0_rgba(255,255,255,.6),0_2px_0_#92400E,0_8px_14px_-6px_rgba(245,158,11,.6)]" />
        <div className="min-w-0 flex-1">
          <p className="m-0 flex items-center gap-2 text-[10.5px] font-bold uppercase tracking-[.14em] text-amber-300">
            Prochaine course
            {isLive && <PastilleDirect libelle="En piste" />}
          </p>
          <h2 className="m-0 mt-0.5 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[17px] font-bold leading-tight text-white sm:text-[19px]" style={SG}>
            <span className="rounded-md bg-gradient-to-b from-amber-300 to-amber-500 px-1.5 py-0.5 text-[11.5px] font-bold tabular-nums text-stone-900 shadow-[inset_0_1px_0_rgba(255,255,255,.55),0_2px_0_#92400E]">R{reunionNum}C{course.numero}</span>
            <span className="min-w-0 break-words">{joliNom(course.hippodrome_nom)}</span>
          </h2>
        </div>
        <Link
          href={fiche}
          className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-xl bg-gradient-to-b from-amber-300 via-amber-400 to-amber-600 px-3.5 py-2.5 text-[13px] font-bold text-stone-900 shadow-[inset_0_1px_0_rgba(255,255,255,.55),0_1px_0_#92400E,0_12px_22px_-10px_rgba(245,158,11,.75)] transition-all hover:-translate-y-0.5 active:translate-y-px active:shadow-[inset_0_1px_0_rgba(255,255,255,.55),0_1px_0_#92400E] max-[479px]:w-full max-[479px]:justify-center"
        >
          Voir la course <ChevronRight className="h-4 w-4" />
        </Link>
      </div>

      {/* Corps : compte à rebours · la course · accès directs */}
      <div className="grid gap-4 p-4 sm:p-5 md:grid-cols-[auto_minmax(0,1fr)_minmax(0,15rem)] md:items-center md:gap-6">
        <div className="flex items-center gap-4 md:contents">
          {/* Compte à rebours : l'anneau se vide sur la dernière heure, le chiffre
              défile à la seconde. */}
          <div
            className="relative flex h-[112px] w-[112px] shrink-0 items-center justify-center md:h-[124px] md:w-[124px]"
            role="timer"
            aria-live="off"
            aria-label={secondes != null ? `Départ dans ${formatRebours(secondes)}` : isLive ? "Course en piste" : `Départ à ${formatTime(course.date_heure)}`}
          >
            {/* Socle : l'anneau est posé sur un disque en relief qui projette son ombre */}
            <span aria-hidden className="absolute inset-[3%] rounded-full bg-gradient-to-b from-white to-[#EFE9DC] shadow-[inset_0_2px_0_#fff,inset_0_-6px_12px_rgba(146,64,14,.12),0_14px_24px_-12px_rgba(17,24,39,.45)]" />
            <span aria-hidden className="absolute -bottom-2 left-1/2 h-3 w-[70%] -translate-x-1/2 rounded-[50%] bg-stone-900/20 blur-md" />
            <svg viewBox="0 0 104 104" className="absolute inset-0 h-full w-full -rotate-90 drop-shadow-[0_0_6px_rgba(245,158,11,.45)]" aria-hidden>
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
            <div className="relative flex h-[76%] w-[76%] flex-col items-center justify-center rounded-full bg-gradient-to-b from-white via-white to-stone-100 shadow-[inset_0_1px_0_#fff,inset_0_-3px_6px_rgba(17,24,39,.06),0_2px_0_#E4DCCB,0_10px_18px_-8px_rgba(17,24,39,.45)]">
              {secondes != null ? (
                <>
                  <span className="text-[10.5px] font-semibold text-stone-500">départ dans</span>
                  <span className={cn("font-bold leading-none tracking-tight tabular-nums", secondes < 300 ? "text-amber-700" : "text-stone-900", secondes >= 3600 ? "text-[18px]" : "text-[23px]")} style={SG}>
                    {formatRebours(secondes)}
                  </span>
                  <span className="mt-1 text-[10px] font-semibold tabular-nums text-stone-500">à {formatTime(course.date_heure)}</span>
                </>
              ) : (
                <>
                  <span className="text-[10.5px] font-semibold text-stone-500">{isLive ? "en piste" : "départ"}</span>
                  <span className="text-[22px] font-bold leading-none tracking-tight text-stone-900 tabular-nums" style={SG}>{formatTime(course.date_heure)}</span>
                </>
              )}
            </div>
          </div>

          {/* La course */}
          <div className="min-w-0">
            {course.nom && <p className="m-0 text-[15px] font-semibold leading-snug text-stone-800" style={SG}>{joliNom(course.nom)}</p>}
            <div className="mt-2 flex flex-wrap gap-1.5">
              <span className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-[12px] font-semibold" style={{ color: m.color, background: m.bg, boxShadow: `inset 0 0 0 1px ${m.ring}` }}>
                <DiscIcon discipline={course.discipline} w={26} h={18} />{titleCase(course.discipline)}
              </span>
              {[`${course.distance} m`, `${partantsReels(course, apercu)} partants`].map((t) => (
                <span key={t} className="inline-flex items-center rounded-lg bg-gradient-to-b from-white to-[#FAF7F0] px-2.5 py-1 text-[12px] font-semibold tabular-nums text-stone-700 ring-1 ring-inset ring-[#ECE7DC] shadow-[0_2px_0_#ECE5D6]">{t}</span>
              ))}
              {course.est_quinte && <Pastille className="bg-amber-50 text-amber-800 ring-amber-200">Quinté+</Pastille>}
            </div>
          </div>
        </div>

        {/* Accès directs aux onglets de la fiche */}
        <nav aria-label="Accès rapide à la course" className="grid grid-cols-3 gap-2 md:grid-cols-1">
          {ACCES.map(([cle, lib, desc, Icone]) => (
            <Link
              key={cle}
              href={`${fiche}#${cle}`}
              className="group flex flex-col items-center gap-1 rounded-xl bg-gradient-to-b from-[#FFFBF2] to-amber-50 px-2 py-2.5 text-center ring-1 ring-inset ring-amber-200 shadow-[inset_0_1px_0_#fff,0_1px_0_#F3D9A4,0_10px_16px_-12px_rgba(146,64,14,.45)] transition-all duration-150 hover:-translate-y-0.5 hover:bg-amber-50 active:translate-y-px active:shadow-[inset_0_1px_0_#fff,0_1px_0_#F3D9A4] md:flex-row md:gap-2.5 md:px-3 md:py-2 md:text-left"
            >
              <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-gradient-to-b from-stone-800 to-stone-950 shadow-[inset_0_1px_0_rgba(255,255,255,.15),0_2px_0_#B45309]">
                <Icone className="h-3.5 w-3.5 text-amber-300" aria-hidden />
              </span>
              <span className="min-w-0 md:flex-1">
                <span className="block text-[12.5px] font-bold text-amber-900">{lib}</span>
                <span className="hidden text-[11px] leading-tight text-stone-500 md:block">{desc}</span>
              </span>
              <ChevronRight className="hidden h-3.5 w-3.5 shrink-0 text-amber-600 transition-transform group-hover:translate-x-0.5 md:block" aria-hidden />
            </Link>
          ))}
        </nav>
      </div>
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
  /* Nombre de chevaux payés au moins 8 % au-dessus de leur chance (cote PMU ÷
     cote juste du modèle − 1) : la tuile « Écarts de prix » de la fiche course. */
  nb_ecarts_prix?: number;
}

/* Tuile discipline : la silhouette propre à chaque discipline (plat, attelé, monté,
 * obstacle), posée sur un galet teinté. Reflet en haut, ombre portée sous le cheval
 * et léger pivot 3D au survol de la ligne : du volume, sans bibliothèque. */
function TuileDiscipline({ discipline, className }: { discipline: string; className?: string }) {
  const m = discMeta(discipline);
  return (
    <span
      aria-hidden
      className={cn("relative h-11 w-11 flex-shrink-0 items-center justify-center overflow-hidden rounded-2xl [perspective:420px] sm:h-14 sm:w-14", className)}
      style={{
        background: `radial-gradient(120% 95% at 30% 0%,#FFFFFF 0%,${m.bg} 55%,${m.ring} 135%)`,
        boxShadow: `inset 0 0 0 1px ${m.ring}, inset 0 1px 0 #fff, inset 0 -8px 14px -8px ${m.ring}, 0 10px 20px -12px ${m.color}80`,
      }}
    >
      {/* reflet de verre sur le haut du galet, sous le cheval */}
      <span className="pointer-events-none absolute inset-x-1 top-0.5 h-2/5 rounded-t-[14px] bg-gradient-to-b from-white/60 to-transparent" />
      {/* sol : une ombre douce sous les sabots */}
      <span className="absolute bottom-[7px] left-1/2 h-1.5 w-8 -translate-x-1/2 rounded-[50%] bg-stone-900/15 blur-[2px]" />
      <span className="relative block transition-transform duration-500 ease-out [transform-style:preserve-3d] group-hover:[transform:rotateY(-16deg)_translateZ(10px)_scale(1.08)]">
        <span className="absolute inset-0 translate-x-[2px] translate-y-[3px] opacity-[.16] blur-[2px]">
          <DiscIcon discipline={discipline} w={38} h={28} color="#1C1917" />
        </span>
        <span className="relative block drop-shadow-[0_1px_0_rgba(255,255,255,.8)]">
          <DiscIcon discipline={discipline} w={38} h={28} />
        </span>
      </span>
    </span>
  );
}

/* Noms lisibles : le PMU envoie hippodromes et courses EN CAPITALES. Sur une liste de
 * quarante lignes, ces capitales criaient et se lisaient mal. Un nom déjà en casse
 * mixte est laissé tel quel ; les sigles connus restent en capitales. */
const PETITS_MOTS = new Set(["de", "du", "des", "la", "le", "les", "et", "sur", "en", "au", "aux", "d", "l"]);
const SIGLES = new Set(["PMU", "PDV", "PX", "GNT", "II", "III", "IV", "UK", "USA"]);
function joliNom(s: string | null | undefined): string {
  if (!s) return "";
  if (s !== s.toUpperCase()) return s;
  let premier = true;
  return s.toLowerCase().replace(/[a-zà-öø-ÿ0-9]+/g, (mot) => {
    const debut = premier;
    premier = false;
    if (SIGLES.has(mot.toUpperCase())) return mot.toUpperCase();
    if (!debut && PETITS_MOTS.has(mot)) return mot;
    return mot.charAt(0).toUpperCase() + mot.slice(1);
  });
}
/* « HIPPODROME DE SAINT MALO » → « Saint Malo » : dans une liste, le mot
 * « hippodrome » répété sur chaque ligne n'apprend rien. */
function hippodromeCourt(s: string | null | undefined): string {
  const nom = (s ?? "").replace(/^\s*hippodrome\s+(de\s+la\s+|de\s+l['’]\s*|du\s+|des\s+|de\s+|d['’]\s*)?/i, "");
  return joliNom(nom || s);
}

function TimelineRow({ course, reunionNum, vbCount, apercu, delay, onOuvrir }: { course: CourseSummary; reunionNum: number; vbCount?: number; apercu?: ApercuCourse; delay: number; onOuvrir?: () => void }) {
  const m = discMeta(course.discipline);
  const isLive = course.statut === "en_cours";
  const isDone = course.statut === "termine" || course.statut === "annule";
  const countdown = useCountdown(course.date_heure, course.statut);
  const pari = course.est_quinte ? "Quinté+" : course.est_quarte ? "Quarté+" : course.est_tierce ? "Tiercé" : null;
  const nbEcarts = apercu?.nb_ecarts_prix ?? 0;
  const signaux = apercu?.analysee || (vbCount !== undefined && vbCount > 0) || nbEcarts > 0;
  return (
    <Link
      href={`/courses/${course.course_id}`}
      /* Identifiant stable de la ligne : c'est lui qui permet de ramener le lecteur
         exactement là où il était quand il revient d'une fiche course. */
      id={`course-${course.course_id}`}
      onClick={onOuvrir}
      className={cn(
        "bt-apparition group relative flex scroll-mt-28 items-center gap-3 overflow-hidden rounded-[20px] py-3.5 pl-4 pr-3.5 no-underline transition-[transform,box-shadow,background-color] duration-300 ease-out active:scale-[.995] sm:gap-4 sm:py-4 sm:pl-6 sm:pr-5",
        isDone
          ? "bg-[#F7F5F0] ring-1 ring-inset ring-stone-200 hover:bg-white"
          : isLive
          ? "bg-gradient-to-r from-emerald-50 via-white to-white ring-1 ring-inset ring-emerald-300 shadow-[0_1px_2px_rgba(28,25,23,.06),0_12px_28px_-16px_rgba(5,150,105,.45)]"
          : "bg-white ring-1 ring-inset ring-stone-200 shadow-[0_1px_2px_rgba(28,25,23,.06),0_12px_28px_-18px_rgba(28,25,23,.28)] hover:-translate-y-0.5 hover:ring-amber-300 hover:shadow-[0_2px_4px_rgba(28,25,23,.06),0_22px_40px_-20px_rgba(146,64,14,.4)]",
      )}
      style={{ ["--bt-delai" as string]: `${delay}s` }}
    >
      {/* Liseré à la couleur de la discipline : on repère d'un coup d'œil plat, attelé,
          obstacle en descendant la liste. Vert pour une course en piste. */}
      <span
        aria-hidden
        className="absolute inset-y-0 left-0 w-1 sm:w-[5px]"
        style={{ background: isLive ? "linear-gradient(180deg,#34D399,#059669)" : isDone ? "#D6D3CD" : `linear-gradient(180deg,${m.color}B3,${m.color})` }}
      />
      {/* Heure de départ, et le temps restant quand il approche */}
      <div className="flex w-[48px] flex-shrink-0 flex-col items-center gap-1 sm:w-[56px]">
        <span className={cn("text-[17px] font-bold leading-none tracking-tight tabular-nums sm:text-[19px]", isLive ? "text-emerald-700" : isDone ? "text-stone-400 line-through decoration-stone-300" : "text-stone-900")} style={SG}>
          {formatTime(course.date_heure)}
        </span>
        {countdown && (
          <span className="whitespace-nowrap rounded-full bg-amber-50 px-1.5 py-px text-[9.5px] font-bold leading-tight text-amber-800 tabular-nums ring-1 ring-inset ring-amber-200">{countdown.replace(/^dans /, "")}</span>
        )}
      </div>
      {/* La pastille garde la couleur de la discipline même course finie : en gris
          délavé (1,8:1 de contraste) jambes et driver se noyaient dans le fond et
          le cheval paraissait amputé. L'heure barrée et le badge « Terminée »
          suffisent à marquer le passé. */}
      <TuileDiscipline discipline={course.discipline} className={cn("hidden min-[360px]:flex", isDone && "opacity-70 saturate-[.8]")} />
      <div className="min-w-0 flex-1">
        {/* Ligne 1 : le numéro de course, bien lisible — c'est lui qu'on cherche et
            qu'on joue au guichet — puis l'hippodrome. */}
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          <span
            className={cn(
              "inline-flex flex-shrink-0 items-center rounded-lg px-2 py-[3px] text-[13px] font-bold leading-none tracking-tight tabular-nums shadow-[inset_0_1px_0_rgba(255,255,255,.14),0_4px_10px_-6px_rgba(28,25,23,.6)] sm:text-[14px]",
              isLive ? "bg-emerald-700 text-white" : isDone ? "bg-stone-400 text-white" : "bg-stone-900 text-white",
            )}
            style={SG}
          >
            R{reunionNum}<span className={cn("ml-px", isLive || isDone ? "text-white/80" : "text-amber-300")}>C{course.numero}</span>
          </span>
          <span className={cn("min-w-0 break-words text-[13px] font-semibold", isDone ? "text-stone-500" : "text-stone-700")}>{hippodromeCourt(course.hippodrome_nom)}</span>
          {pari && (
            <span className="inline-flex flex-shrink-0 items-center rounded-full bg-gradient-to-r from-amber-100 to-amber-50 px-2 py-px text-[10px] font-bold uppercase tracking-wide text-amber-800 ring-1 ring-inset ring-amber-300">{pari}</span>
          )}
          {/* Sur téléphone, le statut monte ici : dans une colonne à droite il volait
              la largeur du titre, qui passait sur quatre lignes. */}
          {(isLive || isDone) && (
            <span className="ml-auto flex flex-shrink-0 items-center pl-1 sm:hidden">
              {isLive ? (
                // La ligne est déjà verte : un point qui bat suffit, le mot reste lu à l'écran.
                <span className="relative flex h-2 w-2" title="En direct">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-70" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
                  <span className="sr-only">En direct</span>
                </span>
              ) : (
                <StatutBadge statut={course.statut} />
              )}
            </span>
          )}
        </div>
        {/* Ligne 2 : le nom de la course */}
        <p className={cn("m-0 mt-1.5 break-words text-[14.5px] font-semibold leading-snug sm:text-[15px]", isDone ? "text-stone-500" : "text-stone-900")}>
          {joliNom(course.nom) || `Course ${course.numero}`}
        </p>
        {/* Ligne 3 : discipline, distance, partants */}
        <div className="mt-1 flex flex-wrap items-center gap-x-2 text-[12.5px] text-stone-600">
          <span className="font-semibold" style={{ color: m.color }}>{titleCase(course.discipline)}</span>
          <span aria-hidden className="text-stone-300">·</span>
          <span className="tabular-nums">{course.distance.toLocaleString("fr-FR")} m</span>
          <span aria-hidden className="text-stone-300">·</span>
          <span className="tabular-nums">{partantsReels(course, apercu)} partants</span>
        </div>
        {/* Ligne 4 : ce que l'analyse dit de CETTE course. Rien d'identifiant : une
            confiance, l'avis du marché, des comptes — jamais un cheval.
            Pas de pastille « Analysée » : toutes les courses le sont, elle
            n'apprenait rien et volait la place des chiffres qui varient. */}
        {signaux && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {vbCount !== undefined && vbCount > 0 && (
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-800 ring-1 ring-inset ring-emerald-200">
                <Zap className="h-3 w-3" aria-hidden />
                <b className="font-bold tabular-nums">{vbCount}</b>
                <span className="hidden sm:inline">pari{vbCount > 1 ? "s" : ""} de valeur</span>
                <span className="sm:hidden">valeur</span>
              </span>
            )}
            {nbEcarts > 0 && (
              <span
                title={`${nbEcarts} cheva${nbEcarts > 1 ? "ux payés" : "l payé"} au moins 8 % au-dessus de ${nbEcarts > 1 ? "leur" : "sa"} chance selon le modèle — même lecture que la fiche course`}
                className="inline-flex items-center gap-1 rounded-full bg-sky-50 px-2 py-0.5 text-[11px] font-semibold text-sky-800 ring-1 ring-inset ring-sky-200"
              >
                <ArrowLeftRight className="h-3 w-3" aria-hidden />
                <b className="font-bold tabular-nums">{nbEcarts}</b> écart{nbEcarts > 1 ? "s" : ""} de prix
              </span>
            )}
            {apercu?.analysee && apercu.confiance != null && (
              <span
                className="inline-flex items-center gap-1.5 rounded-full bg-stone-50 py-0.5 pl-2 pr-2.5 text-[11px] font-medium text-stone-700 ring-1 ring-inset ring-stone-200"
                title="Accord des 3 modèles (entre eux et avec le marché) sur le n°1 de cette course. Ce n'est pas sa chance de gagner."
              >
                <span className="sm:hidden">Accord</span>
                <span className="hidden sm:inline">Accord des modèles</span>
                <span aria-hidden className="h-1 w-8 overflow-hidden rounded-full bg-stone-200">
                  <span className="block h-full rounded-full bg-gradient-to-r from-amber-400 to-emerald-500" style={{ width: `${Math.max(0, Math.min(100, apercu.confiance))}%` }} />
                </span>
                <b className="font-semibold tabular-nums text-stone-800">{apercu.confiance}</b>
              </span>
            )}
            {apercu?.analysee && apercu.accord_marche === false && (
              <span
                title="Le n°1 du modèle n'est pas le favori des parieurs sur cette course"
                className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-800 ring-1 ring-inset ring-amber-200"
              >
                <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-amber-500" />
                <span className="sm:hidden">≠ marché</span>
                <span className="hidden sm:inline">Ne suit pas le marché</span>
              </span>
            )}
          </div>
        )}
      </div>
      <div className="hidden flex-shrink-0 items-center gap-2 sm:flex">
        <StatutBadge statut={course.statut} />
        <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-stone-100 text-stone-500 ring-1 ring-inset ring-stone-200 transition-colors duration-300 group-hover:bg-amber-50 group-hover:text-amber-600">
          <ChevronRight className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-0.5" />
        </span>
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
    { refreshInterval: 60000 },
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
    // Chaque minute le jour même : les écarts de prix suivent les cotes, un aperçu
    // de cinq minutes contredisait la fiche course ouverte au même moment.
    { refreshInterval: isToday ? 60000 : 0, revalidateOnFocus: isToday },
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
    <div className="space-y-6">
      {groupes.map(([hour, items]) => (
        <div key={hour} className="relative">
          {/* Repère horaire : une pastille légère et un filet qui s'efface, plutôt
              qu'un gros jeton — la liste respire et l'œil va aux courses. */}
          <div className="mb-3 flex items-center gap-3">
            <span className="inline-flex items-center rounded-full bg-gradient-to-b from-stone-800 to-stone-950 px-3.5 py-1 text-[13px] font-bold tabular-nums text-amber-300 shadow-[inset_0_1px_0_rgba(255,255,255,.12),0_6px_14px_-8px_rgba(28,25,23,.7)]" style={SG}>
              {hour}
            </span>
            <span className="text-[12px] font-semibold text-stone-600">{items.length} course{items.length > 1 ? "s" : ""}</span>
            <span aria-hidden className="h-px flex-1 bg-gradient-to-r from-stone-300 to-transparent" />
          </div>
          <div className="flex flex-col gap-2.5">
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
/* translate et non transform : avec un remplissage « both », une animation de transform écraserait la bascule au survol de .bt-relief. */
@keyframes fadeUp{from{opacity:0;translate:0 20px}to{opacity:1;translate:none}}
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
.bt-brillance-nuit{background-image:linear-gradient(90deg,#D97706 0%,#FBBF24 25%,#FEF3C7 50%,#FBBF24 75%,#D97706 100%);background-size:200% 100%;animation:btBrille 6s linear infinite}
/* Relief des lignes : légère bascule en perspective au survol (souris uniquement). */
.bt-relief{transition:transform .25s cubic-bezier(.16,1,.3,1),box-shadow .25s ease}
@media (hover:hover){.bt-relief:hover{transform:perspective(900px) rotateX(3deg) translateY(-3px)}}
.bt-pop{animation:btPop .6s cubic-bezier(.16,1,.3,1) both}
.bt-lisere{isolation:isolate;overflow:hidden}
.bt-lisere::before{content:"";position:absolute;left:50%;top:50%;width:200vmax;height:200vmax;margin:-100vmax 0 0 -100vmax;z-index:-1;background:conic-gradient(from 0deg,#FDE68A,#F59E0B 18%,#D97706 30%,#FBBF24 45%,#FFF7D6 50%,#FBBF24 55%,#D97706 70%,#F59E0B 82%,#FDE68A);animation:btTour 6s linear infinite}
.bt-pop:nth-child(2){animation-delay:.07s}.bt-pop:nth-child(3){animation-delay:.14s}.bt-pop:nth-child(4){animation-delay:.21s}
.bt-apparition{animation:fadeUp .5s cubic-bezier(.16,1,.3,1) var(--bt-delai,0s) both}
@supports (animation-timeline: view()){
  .bt-apparition{animation:fadeUp linear both;animation-timeline:view();animation-range:entry 0% entry 55%}
}
@media (prefers-reduced-motion:reduce){*{animation:none!important}.bt-lisere::before{background:#F59E0B}}
`}</style>

      <div className="mx-auto max-w-4xl space-y-5 px-4 py-6 sm:space-y-6 sm:px-6 sm:py-8 lg:px-8">

        {/* ── EN-TÊTE : bandeau noir et or ── */}
        <header className="relative isolate overflow-hidden rounded-[22px] bg-[linear-gradient(160deg,#261F16_0%,#12100C_55%,#0B0907_100%)] px-4 pb-4 pt-5 ring-1 ring-inset ring-amber-500/25 shadow-[inset_0_1px_0_rgba(255,255,255,.08),0_26px_48px_-28px_rgba(17,12,5,.85)] sm:px-6 sm:pb-5 sm:pt-6">
          {/* Halos dorés qui dérivent lentement, atténués sur le noir. */}
          <span aria-hidden className="bt-halo-a pointer-events-none absolute -left-16 -top-20 -z-10 h-56 w-56 rounded-full bg-amber-500/20 blur-3xl" />
          <span aria-hidden className="bt-halo-b pointer-events-none absolute -bottom-24 right-10 -z-10 h-60 w-60 rounded-full bg-orange-600/20 blur-3xl" />
          <span aria-hidden className="bt-halo-c pointer-events-none absolute left-1/3 top-6 -z-10 h-40 w-40 rounded-full bg-yellow-400/10 blur-3xl" />
          <span
            aria-hidden
            className="pointer-events-none absolute max-[479px]:hidden"
            style={{
              right: 26, top: 14, width: 150, height: 92, opacity: 0.14, background: "#FBBF24",
              WebkitMaskImage: "url(/img/logo-horse.png)", maskImage: "url(/img/logo-horse.png)",
              WebkitMaskRepeat: "no-repeat", maskRepeat: "no-repeat",
              WebkitMaskPosition: "center", maskPosition: "center",
              WebkitMaskSize: "contain", maskSize: "contain",
            }}
          />
          <div className="relative">
            <div className="mb-2.5 flex items-center justify-between gap-3">
              <div className="inline-flex items-center gap-2 text-[11px] font-bold uppercase tracking-[.16em] text-amber-300">
                <span className="h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse" />
                Programme PMU
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
                className="mb-3 inline-flex items-center gap-1.5 rounded-lg bg-white/10 px-3 py-1.5 text-[12.5px] font-semibold text-amber-200 ring-1 ring-inset ring-amber-300/30 transition-colors hover:bg-white/15"
              >
                Arrivées et rapports du {format(selectedDate, "d MMMM yyyy", { locale: fr })} →
              </a>
            )}

            {/* « Courses du jour » : le nom de la rubrique dans toutes les barres de
                navigation (`@/lib/navigation`). « Programme PMU », le terme que tapent
                les internautes, reste dans le `<title>` et le sur-titre juste au-dessus.
                Un autre jour que celui-ci devient « Courses du mardi 23 septembre ». */}
            <h1 className="text-[26px] font-bold leading-[1.08] tracking-tight sm:text-[34px] sm:leading-[1.04]" style={SG}>
              <span className="bt-brillance-nuit bg-clip-text text-transparent">{isToday ? "Courses du jour" : "Courses"}</span>
              <span className="text-stone-100">{isToday ? " — " : " du "}{dayName.toLowerCase()} {restDate}</span>
            </h1>

            {programme && programme.nb_courses > 0 && (() => {
              const enDirect = allCourses.filter((c) => c.statut === "en_cours").length;
              const aVenir = allCourses.filter((c) => !estPassee(c) && c.statut !== "en_cours").length;
              const tuiles: Array<{ n: number; l: string; ton?: string }> = [
                { n: programme.nb_courses, l: "Courses" },
                { n: programme.reunions.length, l: "Réunions" },
                ...(isToday ? [
                  { n: enDirect, l: "En direct", ton: enDirect > 0 ? "text-emerald-400" : undefined },
                  { n: aVenir, l: "À venir", ton: "text-amber-400" },
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
        {nextRace && <NextRaceBanner item={nextRace} apercu={apercuByCourse[nextRace.course.course_id]} />}

        {/* ── Bandeau value bets actifs (Free/Découverte + visiteurs non connectés) ── */}
        {!isPaid && (
          <ValueBetsCompteurBanner
            initial={initialCompteurVB}
            // Anonyme : l'étape d'avant, c'est le compte gratuit. Compte gratuit : le
            // prix d'entrée est le Pass Jour (5 €, sans abonnement), pas « dès 12 € ».
            href={user ? "/tarifs#passes" : "/inscription?plan=standard&suite=%2Fprogramme"}
            libelle={!user ? "Créer un compte gratuit" : "Débloquer dès 5 €"}
          />
        )}

        {/* ── Contrôles ── */}
        {programme && programme.nb_courses > 0 && (
          <div className="space-y-4 rounded-[24px] bg-white p-4 ring-1 ring-inset ring-stone-200 shadow-[0_1px_2px_rgba(28,25,23,.06),0_18px_40px_-24px_rgba(28,25,23,.3)] sm:p-5">
            <div className="-mx-4 -mt-4 flex items-center justify-between gap-2 rounded-t-[24px] border-b border-stone-200 bg-gradient-to-b from-[#FFFBF2] to-white px-4 py-3 sm:-mx-5 sm:-mt-5 sm:px-5">
              <div className="flex items-center gap-2.5">
                <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-b from-stone-800 to-stone-950 text-amber-300 shadow-[inset_0_1px_0_rgba(255,255,255,.12)]">
                  <Filter className="h-4 w-4" aria-hidden />
                </span>
                <h2 className="m-0 text-[15px] font-bold text-stone-900" style={SG}>Filtrer les courses</h2>
              </div>
              {(discFilter !== "Tous" || reunionFilter !== "all" || hippoSearch || vbOnly) && (
                <button onClick={resetFilters} className="rounded-full px-2.5 py-1 text-[12px] font-semibold text-amber-700 transition-colors hover:bg-amber-50">Tout effacer</button>
              )}
            </div>
            {/* Recherche + valeur */}
            <div className="flex flex-wrap items-center gap-2.5">
              {isPaid && isToday && (
                <button
                  onClick={() => setVbOnly((v) => !v)}
                  aria-pressed={vbOnly}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-full px-4 py-2.5 text-[13px] font-semibold transition-all duration-200",
                    vbOnly ? "bg-gradient-to-b from-amber-400 to-amber-500 text-stone-900 shadow-[0_6px_16px_-8px_rgba(217,119,6,.7)]" : "bg-amber-50 text-amber-800 ring-1 ring-inset ring-amber-200 hover:bg-amber-100",
                  )}
                >
                  <Zap className="h-3.5 w-3.5" /> Valeur
                </button>
              )}
              <div className="relative min-w-[190px] flex-1">
                <Search className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-stone-500" />
                <input
                  value={hippoSearch}
                  onChange={(e) => setHippoSearch(e.target.value)}
                  placeholder="Rechercher un hippodrome…"
                  aria-label="Rechercher un hippodrome"
                  className={cn("w-full rounded-full border-0 bg-stone-50 py-2.5 pl-10 text-[13.5px] text-stone-800 outline-none ring-1 ring-inset ring-stone-200 transition-all placeholder:text-stone-500 focus:bg-white focus:ring-amber-300 focus:shadow-[0_0_0_4px_rgba(251,191,36,.15)]", hippoSearch ? "pr-9" : "pr-4")}
                />
                {hippoSearch && (
                  <button onClick={() => setHippoSearch("")} aria-label="Effacer la recherche" className="absolute right-3 top-1/2 -translate-y-1/2 rounded-full p-0.5 hover:bg-stone-200/60">
                    <X className="h-3.5 w-3.5 text-stone-500" />
                  </button>
                )}
              </div>
            </div>

            {/* Filtre par réunion. Nom court (« Paris-Vincennes ») : les capitales
                « HIPPODROME DE … » répétées sur douze boutons remplissaient la carte.
                Sur ordinateur les réunions passent à la ligne ; sur mobile elles
                défilent, avec un fondu à droite qui signale la suite. */}
            {reunionOptions.length > 1 && (
              <div className="space-y-2">
                <p className="m-0 text-[10.5px] font-bold uppercase tracking-[.14em] text-stone-500">Réunions</p>
                <div className={cn("-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1 pr-8 [mask-image:linear-gradient(to_right,#000_calc(100%-2rem),transparent)] sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0 sm:pr-0 sm:[mask-image:none]", HIDE_SCROLLBAR)}>
                  {[{ numero: "all" as const, hippodrome: "Toutes" }, ...reunionOptions].map((r) => {
                    const active = reunionFilter === r.numero;
                    const tout = r.numero === "all";
                    return (
                      <button
                        key={String(r.numero)}
                        onClick={() => setReunionFilter(r.numero)}
                        aria-pressed={active}
                        className={cn(
                          "inline-flex flex-shrink-0 items-center gap-1.5 rounded-full px-3.5 py-2 text-[13px] transition-all duration-200",
                          active
                            ? "bg-stone-900 text-white shadow-[0_6px_14px_-8px_rgba(28,25,23,.7)]"
                            : "bg-white text-stone-700 ring-1 ring-inset ring-stone-200 hover:ring-stone-300 hover:text-stone-900",
                        )}
                      >
                        {!tout && (
                          <span className={cn("text-[11.5px] font-bold tabular-nums", active ? "text-amber-300" : "text-amber-700")} style={SG}>R{r.numero}</span>
                        )}
                        {/* Pas d'`opacity-75` ici : un gris passé à 75 % tombait sous 4,5:1. */}
                        <span className={cn("whitespace-nowrap", tout ? "font-semibold" : "font-medium")}>{tout ? r.hippodrome : hippodromeCourt(r.hippodrome)}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Filtre par discipline : la silhouette de chaque discipline, sur un galet */}
            <div className="space-y-2">
              <p className="m-0 text-[10.5px] font-bold uppercase tracking-[.14em] text-stone-500">Disciplines</p>
              <div className={cn("-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0", HIDE_SCROLLBAR)}>
                {["Tous", ...Object.keys(discCounts).sort((a, b) => discCounts[b] - discCounts[a])].map((d) => {
                  const count = d === "Tous" ? allCourses.length : (discCounts[d] ?? 0);
                  if (d !== "Tous" && count === 0) return null;
                  const active = discFilter === d;
                  const dm = discMeta(d);
                  return (
                    <button
                      key={d}
                      onClick={() => setDiscFilter(d)}
                      aria-pressed={active}
                      className={cn(
                        "group inline-flex flex-shrink-0 items-center gap-2 rounded-full py-1.5 pr-3 text-[13px] font-semibold transition-all duration-200",
                        d === "Tous" ? "pl-3.5" : "pl-1.5",
                        active
                          ? "bg-stone-900 text-white shadow-[0_6px_14px_-8px_rgba(28,25,23,.7)]"
                          : "bg-white text-stone-700 ring-1 ring-inset ring-stone-200 hover:-translate-y-px hover:ring-stone-300 hover:shadow-[0_8px_16px_-12px_rgba(28,25,23,.35)]",
                      )}
                    >
                      {d !== "Tous" && (
                        <span
                          aria-hidden
                          className="flex h-8 w-10 items-center justify-center rounded-full transition-transform duration-300 group-hover:scale-105"
                          style={{
                            background: active ? "rgba(255,255,255,.12)" : `radial-gradient(120% 100% at 30% 0%,#FFFFFF 0%,${dm.bg} 60%,${dm.ring} 140%)`,
                            boxShadow: active ? "inset 0 1px 0 rgba(255,255,255,.15)" : `inset 0 1px 0 #fff, 0 4px 10px -6px ${dm.color}80`,
                          }}
                        >
                          <DiscIcon discipline={d} w={30} h={21} color={active ? "#FFFFFF" : dm.color} />
                        </span>
                      )}
                      {titleCase(d)}
                      <span className={cn("rounded-full px-1.5 text-[11px] font-bold tabular-nums", active ? "bg-white/15 text-white" : "bg-stone-100 text-stone-700")}>{count}</span>
                    </button>
                  );
                })}
              </div>
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
            <p className="font-semibold text-gray-700">Courses momentanément indisponibles</p>
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
            <BandeauOnglet
              icone={CalendarClock}
              titre="Courses du jour"
              className="mb-5"
              sousTitre={
                <>
                  <b className="font-semibold text-stone-900">{flatAVenir.length}</b> à venir
                  {flatTermines.length > 0 && <> · <b className="font-semibold text-stone-700">{flatTermines.length}</b> déjà courue{flatTermines.length > 1 ? "s" : ""}</>}
                </>
              }
              droite={isToday && maintenant ? (
                <Pastille className="bg-white text-amber-800 ring-amber-200">
                  <span className="relative flex h-1.5 w-1.5">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-60 motion-reduce:animate-none" />
                    <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-amber-500" />
                  </span>
                  Maintenant · <span className="tabular-nums">{format(maintenant, "HH:mm")}</span>
                </Pastille>
              ) : undefined}
            />
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
                  className="flex w-full items-center justify-between gap-3 rounded-[18px] bg-white px-4 py-3 text-left text-[13px] font-semibold text-stone-800 ring-1 ring-inset ring-stone-200 shadow-[0_1px_2px_rgba(28,25,23,.05)] transition-colors hover:ring-amber-300 active:scale-[.995]"
                >
                  <span className="inline-flex items-center gap-2.5">
                    <span aria-hidden className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-50 text-[10px] font-bold text-emerald-700 ring-1 ring-inset ring-emerald-200">✓</span>
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

            {rendreGroupes(groupesAVenir, true)}
          </div>
        )}

        {/* ── Visiteur anonyme : ce qu'un compte gratuit ouvre sur ces courses ── */}
        {!authLoading && !user && programme && programme.nb_courses > 0 && (
          <CompteGratuitCta
            icone={IconeMarcheDirect}
            titre="Suivez le marché des cotes en direct sur ces courses"
            texte="Créez votre compte gratuit en 30 secondes : l'évolution des cotes minute par minute, le classement complet de l'algorithme sur une course par jour, avec son plan de mise."
            suite="/programme"
          />
        )}

        {/* ── Compte gratuit confirmé : les pass sans abonnement, en un clic ── */}
        {!isPaid && user && peutDebloquer(user) && isToday && programme && programme.nb_courses > 0 && (
          <div className="flex flex-wrap items-center justify-between gap-3.5 rounded-[20px] px-5 py-4" style={{ border: "1px solid rgba(16,185,129,.28)", background: "linear-gradient(135deg,#ECFDF5,#FFFBF0)" }}>
            <div className="min-w-[200px] flex-1">
              <p className="text-sm font-bold text-emerald-900">Paris de valeur de ce soir : dès 5 €</p>
              <p className="mt-1 text-xs text-emerald-800">Pass Jour : tout Expert pendant 24 h, paiement unique, sans abonnement.</p>
            </div>
            <Button variant="brand" size="default" className="flex-shrink-0" asChild><Link href="/tarifs#formules">Voir les formules</Link></Button>
          </div>
        )}

        {/* ── Upsell (autres comptes gratuits : adresse non confirmée, paiement en attente…) ── */}
        {!isPaid && user && !peutDebloquer(user) && isToday && programme && programme.nb_courses > 0 && (
          <div className="flex flex-wrap items-center justify-between gap-3.5 rounded-[20px] px-5 py-4" style={{ border: "1px solid rgba(245,158,11,.28)", background: "linear-gradient(135deg,#FFFBF0,#FEF3E2)" }}>
            <div className="min-w-[200px]">
              <p className="text-sm font-bold text-amber-900">Paris de valeur verrouillés</p>
              <p className="mt-1 text-xs text-amber-700">Dès 5 € avec un pass, ou avec Standard : détectés par l&apos;IA sur chaque course.</p>
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
