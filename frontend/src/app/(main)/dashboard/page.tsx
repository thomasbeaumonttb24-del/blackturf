"use client";

/**
 * Mon espace — tableau de bord de l'abonné, dans la veine du palmarès et de
 * l'accueil : un en-tête sombre en relief (sol en perspective, orbites, carte du
 * pari du jour en lévitation), des cartes qui s'inclinent vers le pointeur et des
 * chiffres qui s'animent à leur arrivée.
 *
 * Les effets viennent des briques partagées (`track-record/effets`, `espace/kit`)
 * et des classes de `globals.css` : tous se coupent avec « réduire les animations ».
 */

import Link from "next/link";
import useSWR from "swr";
import {
  ArrowRight, BarChart3, Calendar, CheckCircle2, ChevronRight, Clock, Cpu, Crosshair,
  LineChart, LockKeyhole, Radio, Sparkles, Star, Target, Ticket, TrendingDown, TrendingUp,
  Trophy, Wallet, Zap,
} from "lucide-react";
import { format } from "date-fns";
import { fr } from "date-fns/locale";
import { Button } from "@/components/ui/button";
import { IdentiteCheval } from "@/components/courses/identite-cheval";
import { Reveal, Tilt, useReveal } from "@/components/track-record/effets";
import { Anneau, Compteur, CourbeCapital, SectionTitre, nf } from "@/components/espace/kit";
import { useRequireAuth } from "@/hooks/useAuth";
import { bankrollApi, predictionsApi, coursesApi, statsApi } from "@/lib/api";
import { RUBRIQUES } from "@/lib/navigation";
import { cn, planLabel } from "@/lib/utils";

// ─── Types ──────────────────────────────────────────────────────
interface Reunion {
  hippodrome_nom?: string;
  discipline?: string;
  courses?: Array<{
    course_id: string;
    nom?: string;
    heure?: string;
    nb_partants?: number;
    statut?: string;
    est_quinte?: boolean;
  }>;
}

type CourseJour = NonNullable<Reunion["courses"]>[number] & { hippodrome?: string; discipline?: string };

interface PariDuJour {
  course_id: string;
  code: string;
  hippodrome: string;
  numero: number;
  nom_cheval: string;
  ev?: number;
  edge_valide?: boolean;
  niveau: number;
  raison?: string;
  proba_top1?: number;
  cote_pmu?: number | null;
}

interface PariProfil {
  profil: string;
  profil_label: string;
  course_id: string;
  code: string;
  hippodrome: string;
  type_pari: string;
  chevaux: Array<{ numero: number; nom: string }>;
  mise: number;
  probabilite: number;
  ev: number;
  raisons: string[];
}

interface ValueBet {
  nom_cheval: string;
  numero?: number | null;
  hippodrome: string;
  discipline?: string;
  heure?: string;
  ev: number;
  niveau: number;
  cote?: number;
  course_id: string;
}

interface Entree {
  date: string;
  gain_perte: number | null;
  resultat: string | null;
}

// ─── Petites briques ────────────────────────────────────────────
function Etoiles({ n, clair }: { n: number; clair?: boolean }) {
  return (
    <span className="flex gap-0.5" aria-label={`${n} étoile${n > 1 ? "s" : ""} sur 4`}>
      {Array.from({ length: 4 }).map((_, i) => (
        <Star
          key={i}
          aria-hidden="true"
          className={cn(
            "h-3 w-3",
            i < n ? "fill-amber-400 text-amber-500" : clair ? "text-white/25" : "text-stone-300",
          )}
        />
      ))}
    </span>
  );
}

/** Carte chiffre de l'en-tête : verre dépoli, inclinable, en entrée décalée. */
function CarteChiffre({ i, icone: Icone, libelle, children, note, teinte }: {
  i: number;
  icone: typeof Wallet;
  libelle: string;
  children: React.ReactNode;
  note?: React.ReactNode;
  teinte: string;
}) {
  return (
    <Tilt
      max={10}
      className="tr-rise rounded-2xl bg-gradient-to-b from-white/[0.14] to-white/[0.04] p-3.5 ring-1 ring-white/15 shadow-[0_24px_48px_-28px_rgba(0,0,0,.9)] backdrop-blur-md sm:p-5"
      style={{ animationDelay: `${300 + i * 110}ms` }}
    >
      <span className="absolute inset-x-4 top-0 h-px bg-gradient-to-r from-transparent via-amber-200/70 to-transparent" aria-hidden="true" />
      <div className="tr-pop">
        <div className="flex items-center justify-between gap-2">
          <span className={cn("flex h-8 w-8 items-center justify-center rounded-xl ring-1 ring-white/10 sm:h-9 sm:w-9", teinte)}>
            <Icone className="h-4 w-4" aria-hidden="true" />
          </span>
          {note}
        </div>
        <div className="mt-3 whitespace-nowrap font-display text-[1.45rem] font-black leading-none text-white sm:text-3xl">
          {children}
        </div>
        <div className="mt-1.5 text-[11px] font-medium text-white/65 sm:text-xs">{libelle}</div>
      </div>
    </Tilt>
  );
}

// ─── En-tête ────────────────────────────────────────────────────
function PariDuJourCarte({ p }: { p: PariDuJour }) {
  const proba = Math.round((p.proba_top1 ?? 0) * 100);
  const ev = Math.round((p.ev ?? 0) * 100);
  return (
    <Link href={`/courses/${p.course_id}`} className="group block" aria-label={`Pari du jour : ${p.nom_cheval}, ${p.code} à ${p.hippodrome}`}>
      <Tilt max={9} className="esp-lisere rounded-[1.6rem]">
        <div className="relative overflow-hidden rounded-[1.6rem] bg-gradient-to-br from-stone-900/95 via-stone-900/90 to-amber-950/80 p-5 ring-1 ring-white/10 shadow-[0_40px_80px_-30px_rgba(0,0,0,.9),0_0_60px_-20px_rgba(245,158,11,.45)] backdrop-blur-xl sm:p-6">
          <span className="tr-shine" aria-hidden="true" />
          <div className="pointer-events-none absolute -right-16 -top-16 h-44 w-44 rounded-full bg-amber-400/20 blur-3xl" aria-hidden="true" />

          <div className="tr-pop relative">
            <div className="flex items-center justify-between gap-3">
              <span className="vb-glow inline-flex items-center gap-1.5 rounded-full bg-amber-400/15 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.18em] text-amber-300 ring-1 ring-amber-400/30">
                <Crosshair className="h-3 w-3" aria-hidden="true" /> Pari du jour
              </span>
              <span className="truncate text-[11px] font-medium text-white/55">{p.code} · {p.hippodrome}</span>
            </div>

            <div className="mt-5 flex items-center gap-4 sm:gap-5">
              <Anneau pct={proba} taille={104} epaisseur={9} couleur={["#FCD34D", "#D97706"]}>
                <span className="font-display text-2xl font-black leading-none text-white">{proba}<span className="text-sm">%</span></span>
                <span className="mt-1 text-[9px] font-semibold uppercase tracking-wider text-white/50">gagnant</span>
              </Anneau>
              <div className="min-w-0 flex-1">
                <div className="text-lg font-bold text-white">
                  <IdentiteCheval numero={p.numero} nom={p.nom_cheval} courseId={p.course_id} />
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  {ev > 0 && (
                    <span className="rounded-full bg-emerald-400/15 px-2 py-0.5 text-[11px] font-bold text-emerald-300 ring-1 ring-emerald-400/30">
                      EV +{ev}%
                    </span>
                  )}
                  {p.cote_pmu && (
                    <span className="rounded-full bg-white/10 px-2 py-0.5 text-[11px] font-semibold text-white/80 ring-1 ring-white/10">
                      Cote {p.cote_pmu}
                    </span>
                  )}
                  <Etoiles n={Math.max(1, p.niveau)} clair />
                </div>
                {p.edge_valide && (
                  <span
                    className="mt-2 inline-flex items-center gap-1 text-[11px] font-semibold text-amber-200"
                    title="Signaux historiquement gagnants confirmés hors échantillon (taux de gain 3 à 4 fois le marché sur le passé). Pas une garantie."
                  >
                    <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" /> Edge validé
                  </span>
                )}
              </div>
            </div>

            {p.raison && <p className="mt-4 line-clamp-2 text-xs leading-relaxed text-white/60">{p.raison}</p>}

            <div className="mt-5 flex items-center justify-between border-t border-white/10 pt-4 text-sm font-semibold text-amber-300">
              Voir l&apos;analyse de la course
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" aria-hidden="true" />
            </div>
          </div>
        </div>
      </Tilt>
    </Link>
  );
}

/** Sans pari du jour (tôt le matin, jour sans course) : une carte vers le programme. */
function PariDuJourAttente() {
  return (
    <Link href={RUBRIQUES.coursesDuJour.href} className="group block">
      <Tilt max={9} className="rounded-[1.6rem]">
        <div className="relative overflow-hidden rounded-[1.6rem] bg-white/[0.06] p-6 ring-1 ring-white/10 backdrop-blur-xl">
          <div className="tr-pop">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-white/10 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.18em] text-white/70">
              <Sparkles className="h-3 w-3" aria-hidden="true" /> Pari du jour
            </span>
            <p className="mt-4 font-display text-xl font-bold text-white">L&apos;IA analyse encore le programme.</p>
            <p className="mt-2 text-sm leading-relaxed text-white/60">
              Le pari du jour apparaît ici dès qu&apos;une course présente un écart net entre sa chance réelle et sa cote.
            </p>
            <span className="mt-5 inline-flex items-center gap-1.5 text-sm font-semibold text-amber-300">
              {RUBRIQUES.coursesDuJour.label} <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" aria-hidden="true" />
            </span>
          </div>
        </div>
      </Tilt>
    </Link>
  );
}

const PARTICULES = [
  { l: "8%", t: "22%", d: 7, s: 3 }, { l: "22%", t: "70%", d: 9, s: 2 }, { l: "46%", t: "14%", d: 8, s: 2 },
  { l: "63%", t: "78%", d: 11, s: 3 }, { l: "82%", t: "30%", d: 6, s: 2 }, { l: "92%", t: "64%", d: 10, s: 3 },
];

// ─── Page ───────────────────────────────────────────────────────
export default function DashboardPage() {
  const { user } = useRequireAuth();
  const plan = user?.plan ?? "free";
  const isPaid = !!user && !["free", "decouverte"].includes(plan);

  const { data: bankrollStats } = useSWR("bankroll-stats", () => bankrollApi.stats().then((r) => r.data), { refreshInterval: 60_000 });
  const { data: summary } = useSWR("dashboard-summary", () => statsApi.dashboardSummary().then((r) => r.data), { refreshInterval: 120_000 });
  const { data: programme } = useSWR("programme-today", () => coursesApi.programme().then((r) => r.data), { refreshInterval: 180_000 });
  const { data: pariDuJour } = useSWR<PariDuJour | null>("pari-du-jour", () => predictionsApi.pariDuJour().then((r) => r.data), { refreshInterval: 120_000 });
  const { data: parisProfils } = useSWR<{ profils?: PariProfil[] }>("pari-du-jour-profils", () => predictionsApi.pariDuJourProfils().then((r) => r.data), { refreshInterval: 120_000 });
  // Même clé et même requête que la page « Suivi du capital » : le cache est partagé.
  const { data: entrees } = useSWR<Entree[]>("/bankroll/entries", () => bankrollApi.entries().then((r) => r.data));

  // Prochaines courses : à venir / en cours d'abord, triées par heure.
  // Si tout est terminé (soirée), on retombe sur les dernières courses.
  const reunions: Reunion[] = programme?.reunions ?? [];
  const toutes: CourseJour[] = reunions.flatMap((r) =>
    (r.courses ?? []).map((c) => ({ ...c, hippodrome: r.hippodrome_nom, discipline: r.discipline })),
  );
  const aVenir = toutes
    .filter((c) => c.statut === "a_venir" || c.statut === "en_cours")
    .sort((a, b) => (a.heure ?? "").localeCompare(b.heure ?? ""));
  const courses = (aVenir.length > 0 ? aVenir : toutes.slice(-6)).slice(0, 6);
  const aDesProchaines = aVenir.length > 0;

  const topVbs: ValueBet[] = summary?.top_vbs ?? [];
  const profils = parisProfils?.profils ?? [];

  const capital: number | null = bankrollStats
    ? (bankrollStats.bankroll_initiale ?? 0) + (bankrollStats.gains_totaux ?? 0) - (bankrollStats.pertes_totales ?? 0)
    : null;
  const roi: number = bankrollStats?.roi_global ?? 0;
  const roiAlgo: number | null = bankrollStats ? bankrollStats.roi_ia_only ?? 0 : null;

  // Courbe : capital après chacun des derniers paris réglés. L'API renvoie les 50
  // plus récents ; on part du capital actuel et on remonte le temps pour que le
  // dernier point tombe exactement sur le chiffre affiché.
  const regles = (entrees ?? [])
    .filter((e) => e.gain_perte != null && e.resultat && e.resultat !== "en_attente")
    .sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime());
  let courbe: number[] = [];
  if (capital != null && regles.length >= 2) {
    const somme = regles.reduce((s, e) => s + (e.gain_perte ?? 0), 0);
    let c = capital - somme;
    courbe = [c, ...regles.map((e) => (c += e.gain_perte ?? 0))];
  }
  const variationCourbe = courbe.length ? courbe[courbe.length - 1] - courbe[0] : 0;

  const ligneDuJour = [
    summary?.nb_courses_jour != null && `${summary.nb_courses_jour} course${summary.nb_courses_jour > 1 ? "s" : ""} au programme`,
    summary?.nb_vbs_actifs ? `${summary.nb_vbs_actifs} pari${summary.nb_vbs_actifs > 1 ? "s" : ""} de valeur actif${summary.nb_vbs_actifs > 1 ? "s" : ""}` : null,
    summary?.nb_en_cours ? `${summary.nb_en_cours} en direct` : null,
  ].filter(Boolean) as string[];

  return (
    <div className="min-h-screen bg-background [--tr-notch-bg:hsl(var(--background))]">
      {/* ══ En-tête : cockpit sombre en relief ══════════════════════════ */}
      <header className="relative isolate overflow-hidden bg-[#0b0d12] text-white">
        <div className="mesh-anim absolute inset-0 opacity-70" aria-hidden="true" />
        <div className="tr-floor opacity-60" aria-hidden="true" />
        <div className="tr-glow pointer-events-none absolute -left-24 top-10 h-80 w-80 rounded-full bg-amber-500/20 blur-[100px]" aria-hidden="true" />
        <div className="tr-glow pointer-events-none absolute right-0 top-1/3 h-96 w-96 rounded-full bg-orange-600/15 blur-[110px] [animation-delay:2s]" aria-hidden="true" />
        {PARTICULES.map((p, i) => (
          <span
            key={i}
            className="particle pointer-events-none absolute rounded-full bg-amber-300"
            style={{ left: p.l, top: p.t, width: p.s, height: p.s, animationDuration: `${p.d}s`, animationDelay: `${i * 0.7}s`, boxShadow: "0 0 10px 2px rgba(252,211,77,.6)" }}
            aria-hidden="true"
          />
        ))}
        <div className="absolute inset-x-0 bottom-0 h-24 bg-gradient-to-b from-transparent to-[#0b0d12]/60" aria-hidden="true" />

        <div className="relative mx-auto max-w-7xl px-4 pb-8 pt-8 sm:px-6 sm:pb-12 sm:pt-12 lg:px-8">
          <div className="grid items-center gap-8 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:gap-12">
            {/* Salutation */}
            <div className="tr-rise">
              <div className="flex flex-wrap items-center gap-2">
                <span className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.24em] text-amber-300 sm:text-[11px]">
                  <span className="h-px w-6 bg-amber-400/70" aria-hidden="true" />
                  {RUBRIQUES.monEspace.label}
                </span>
                <span className={cn(
                  "rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider ring-1",
                  isPaid ? "bg-amber-400/15 text-amber-200 ring-amber-400/40" : "bg-white/10 text-white/70 ring-white/15",
                )}>
                  {planLabel(plan)}
                </span>
              </div>

              <h1 className="mt-4 font-display text-[2.1rem] font-extrabold leading-[1.05] tracking-tight [text-shadow:0_2px_24px_rgba(0,0,0,0.5)] sm:text-6xl">
                Bonjour{user?.prenom ? "," : ""}{" "}
                <span className="text-gradient-animated">{user?.prenom ?? "et bienvenue"}</span>
              </h1>
              <p className="mt-3 text-sm capitalize text-white/55 sm:text-base">
                {format(new Date(), "EEEE d MMMM yyyy", { locale: fr })}
              </p>

              {ligneDuJour.length > 0 && (
                <p className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm text-white/80 sm:text-[15px]">
                  {summary?.nb_en_cours ? <span className="live-dot h-2 w-2 rounded-full bg-emerald-400" aria-hidden="true" /> : null}
                  {ligneDuJour.map((t, i) => (
                    <span key={t} className="inline-flex items-center gap-3">
                      {i > 0 && <span className="text-white/25" aria-hidden="true">·</span>}
                      {t}
                    </span>
                  ))}
                </p>
              )}

              <div className="mt-6 flex flex-wrap gap-3">
                <Button asChild size="lg" className="press btn-shimmer h-12 rounded-xl bg-brand-gold px-6 font-bold text-brand-dark shadow-lg shadow-amber-500/30 hover:bg-brand-gold-deep">
                  <Link href={RUBRIQUES.coursesDuJour.href}>
                    <Calendar className="mr-2 h-4 w-4" aria-hidden="true" /> {RUBRIQUES.coursesDuJour.label}
                  </Link>
                </Button>
                <Button asChild size="lg" variant="outline" className="press h-12 rounded-xl border-white/20 bg-white/5 px-6 font-semibold text-white backdrop-blur hover:bg-white/10 hover:text-white">
                  <Link href={RUBRIQUES.quinte.href}>
                    <Trophy className="mr-2 h-4 w-4 text-amber-300" aria-hidden="true" /> {RUBRIQUES.quinte.label}
                  </Link>
                </Button>
              </div>
            </div>

            {/* Pari du jour en lévitation, sur ses orbites */}
            <div className="relative mx-auto w-full max-w-md lg:max-w-none">
              <div className="esp-orbite pointer-events-none absolute left-1/2 top-1/2 h-[130%] w-[130%] -translate-x-1/2 -translate-y-1/2" aria-hidden="true">
                <span /><span />
              </div>
              <div className="tr-rise relative" style={{ animationDelay: "180ms" }}>
                <div className="esp-flotte">
                  {pariDuJour ? <PariDuJourCarte p={pariDuJour} /> : <PariDuJourAttente />}
                </div>
              </div>
              <div className="pointer-events-none absolute inset-x-[15%] -bottom-6 h-8 rounded-[100%] bg-black/60 blur-2xl" aria-hidden="true" />
            </div>
          </div>

          {/* Chiffres clés */}
          <div className="mt-10 grid grid-cols-2 gap-2.5 sm:gap-4 lg:grid-cols-4">
            <CarteChiffre
              i={0} icone={Wallet} libelle="Capital total" teinte="bg-amber-400/15 text-amber-300"
              note={bankrollStats && (
                <span className={cn("inline-flex items-center gap-1 text-[11px] font-bold", roi >= 0 ? "text-emerald-300" : "text-rose-300")}>
                  {roi >= 0 ? <TrendingUp className="h-3 w-3" aria-hidden="true" /> : <TrendingDown className="h-3 w-3" aria-hidden="true" />}
                  {roi > 0 ? "+" : ""}{nf(roi, 1)}%
                </span>
              )}
            >
              <Compteur valeur={capital} suffixe={" €"} />
            </CarteChiffre>
            <CarteChiffre
              i={1} icone={BarChart3} libelle="Rendement algo" teinte="bg-sky-400/15 text-sky-300"
              note={<span className="text-[11px] text-white/50">{bankrollStats?.nb_paris ?? 0} paris</span>}
            >
              <Compteur
                valeur={roiAlgo} decimales={1} suffixe="%" signe
                className={roiAlgo == null ? undefined : roiAlgo >= 0 ? "text-emerald-300" : "text-rose-300"}
              />
            </CarteChiffre>
            <CarteChiffre
              i={2} icone={Zap} libelle={RUBRIQUES.parisDeValeur.label} teinte="bg-emerald-400/15 text-emerald-300"
              note={(summary?.nb_vbs_premium ?? 0) > 0 && (
                <span className="rounded-full bg-amber-400/15 px-1.5 py-0.5 text-[10px] font-bold text-amber-200">{summary.nb_vbs_premium} ★★★+</span>
              )}
            >
              <Compteur valeur={summary?.nb_vbs_actifs} />
            </CarteChiffre>
            <CarteChiffre
              i={3} icone={Trophy} libelle="Courses aujourd'hui" teinte="bg-violet-400/15 text-violet-300"
              note={(summary?.nb_en_cours ?? 0) > 0 && (
                <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-300">
                  <span className="live-dot h-1.5 w-1.5 rounded-full bg-emerald-400" aria-hidden="true" /> En cours
                </span>
              )}
            >
              <Compteur valeur={summary?.nb_courses_jour} />
            </CarteChiffre>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-7xl space-y-12 px-4 py-10 sm:space-y-16 sm:px-6 sm:py-14 lg:px-8">
        {/* ══ Le pari du jour par profil ══════════════════════════════ */}
        {profils.length > 0 && (
          <section>
            <SectionTitre sur="Par profil" titre="Trois façons de jouer aujourd'hui" icone={Ticket} />
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3 sm:gap-5 [perspective:1400px]">
              {profils.map((p, i) => <TicketProfil key={p.profil} p={p} i={i} />)}
            </div>
          </section>
        )}

        {/* ══ Capital + accès rapide ══════════════════════════════════ */}
        <section className="grid grid-cols-1 gap-6 lg:grid-cols-5">
          <Reveal className="lg:col-span-3">
            <PanneauCapital
              capital={capital}
              courbe={courbe}
              variation={variationCourbe}
              stats={bankrollStats}
            />
          </Reveal>
          <Reveal className="lg:col-span-2" delay={120}>
            <AccesRapide />
          </Reveal>
        </section>

        {/* ══ Paris de valeur + prochaines courses ═════════════════════ */}
        <section className="grid grid-cols-1 gap-6 lg:grid-cols-5">
          <div className="lg:col-span-3">
            <SectionTitre
              sur="En direct du modèle"
              titre="Meilleurs paris de valeur"
              icone={Zap}
              aside={
                <Link href={RUBRIQUES.parisDeValeur.href} className="group inline-flex items-center gap-1 text-sm font-semibold text-amber-800 hover:text-amber-950">
                  Voir tous <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
                </Link>
              }
            />
            <ParisDeValeur vbs={topVbs} isPaid={isPaid} />
          </div>
          <div className="lg:col-span-2">
            <SectionTitre
              sur="Programme"
              titre={aDesProchaines ? "Prochaines courses" : "Courses du jour"}
              icone={Calendar}
              aside={
                <Link href={RUBRIQUES.coursesDuJour.href} className="group inline-flex items-center gap-1 text-sm font-semibold text-amber-800 hover:text-amber-950">
                  Tout voir <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
                </Link>
              }
            />
            <FriseProgramme courses={courses} />
          </div>
        </section>
      </div>
    </div>
  );
}

// ─── Tickets par profil ─────────────────────────────────────────
const PROFIL_STYLE: Record<string, { bande: string; texte: string; barre: string; halo: string }> = {
  conservateur: { bande: "from-emerald-500 to-teal-400", texte: "text-emerald-700", barre: "from-emerald-500 to-teal-400", halo: "shadow-emerald-500/20" },
  equilibre: { bande: "from-sky-500 to-indigo-400", texte: "text-sky-700", barre: "from-sky-500 to-indigo-400", halo: "shadow-sky-500/20" },
  agressif: { bande: "from-rose-500 to-orange-400", texte: "text-rose-700", barre: "from-rose-500 to-orange-400", halo: "shadow-rose-500/20" },
};

function TicketProfil({ p, i }: { p: PariProfil; i: number }) {
  const s = PROFIL_STYLE[p.profil] ?? PROFIL_STYLE.equilibre;
  const proba = Math.round((p.probabilite ?? 0) * 100);
  const { ref, hidden } = useReveal<HTMLDivElement>(0.3);
  return (
    <Reveal delay={i * 120}>
      <Link href={`/courses/${p.course_id}`} className="block">
        <Tilt max={8} className={cn("rounded-2xl shadow-xl", s.halo)}>
          <div ref={ref} className="relative overflow-hidden rounded-2xl bg-white ring-1 ring-stone-200/80">
            <div className={cn("h-1.5 bg-gradient-to-r", s.bande)} />
            <span className="tr-shine" aria-hidden="true" />
            <div className="tr-pop p-4 sm:p-5">
              <div className="flex items-center justify-between gap-2">
                <span className={cn("text-[11px] font-black uppercase tracking-[0.16em]", s.texte)}>{p.profil_label}</span>
                <span className="rounded-md bg-stone-100 px-1.5 py-0.5 text-[10px] font-semibold text-stone-600">{p.code}</span>
              </div>
              <div className="mt-3 font-display text-lg font-bold text-stone-900">{p.type_pari}</div>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {(p.chevaux ?? []).map((c) => (
                  <span key={c.numero} className="inline-flex h-7 min-w-[2rem] items-center justify-center rounded-lg bg-[#172033] px-1.5 text-xs font-extrabold tabular-nums text-white shadow-[0_4px_10px_-4px_rgba(23,32,51,.7)]" title={c.nom}>
                    {c.numero}
                  </span>
                ))}
              </div>
            </div>

            {/* Ligne de découpe du ticket */}
            <div className="relative mx-0 border-t-2 border-dashed border-stone-200">
              <span className="absolute -left-2.5 -top-2.5 h-5 w-5 rounded-full bg-background ring-1 ring-stone-200/80 [clip-path:inset(0_0_0_50%)]" aria-hidden="true" />
              <span className="absolute -right-2.5 -top-2.5 h-5 w-5 rounded-full bg-background ring-1 ring-stone-200/80 [clip-path:inset(0_50%_0_0)]" aria-hidden="true" />
            </div>

            <div className="p-4 sm:p-5">
              <div className="flex items-baseline justify-between">
                <span className="font-display text-3xl font-black tabular-nums text-stone-900">{proba}<span className="text-lg">%</span></span>
                {p.ev > 0 && <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-bold text-emerald-700 ring-1 ring-emerald-200">EV +{Math.round(p.ev * 100)}%</span>}
              </div>
              <div className="text-[11px] text-stone-500">de chances de toucher</div>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-stone-100">
                <div className={cn("tr-bar h-full rounded-full bg-gradient-to-r", s.barre)} style={{ width: hidden ? "0%" : `${Math.max(3, proba)}%` }} />
              </div>
              {p.raisons?.[0] && <p className="mt-3 line-clamp-2 text-xs leading-relaxed text-stone-500">{p.raisons[0]}</p>}
              <div className="mt-3 truncate text-[11px] font-medium text-stone-400">{p.hippodrome}</div>
            </div>
          </div>
        </Tilt>
      </Link>
    </Reveal>
  );
}

// ─── Capital ────────────────────────────────────────────────────
function PanneauCapital({ capital, courbe, variation, stats }: {
  capital: number | null;
  courbe: number[];
  variation: number;
  stats?: { nb_paris?: number; nb_gagnants?: number; nb_perdants?: number; taux_reussite?: number; mise_totale?: number };
}) {
  const taux = stats?.taux_reussite ?? 0;
  return (
    <div className="bento-feature relative h-full overflow-hidden rounded-3xl p-5 ring-1 ring-stone-200/80 shadow-[0_30px_60px_-40px_rgba(28,25,23,.45)] sm:p-7">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-100/70 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.16em] text-amber-900 ring-1 ring-amber-200">
            <LineChart className="h-3 w-3" aria-hidden="true" /> {RUBRIQUES.suiviCapital.label}
          </span>
          <div className="mt-3 font-display text-4xl font-black tracking-tight text-stone-900 sm:text-5xl">
            <Compteur valeur={capital} suffixe={" €"} />
          </div>
          {courbe.length > 0 && (
            <div className={cn("mt-1 inline-flex items-center gap-1 text-sm font-semibold", variation >= 0 ? "text-emerald-700" : "text-rose-700")}>
              {variation >= 0 ? <TrendingUp className="h-4 w-4" aria-hidden="true" /> : <TrendingDown className="h-4 w-4" aria-hidden="true" />}
              {variation >= 0 ? "+" : ""}{nf(variation, 2)} € sur vos {courbe.length - 1} derniers paris
            </div>
          )}
        </div>

        <Anneau pct={taux} taille={92} epaisseur={8} couleur={["#10B981", "#059669"]} fond="rgba(120,113,108,.12)">
          <span className="font-display text-xl font-black leading-none text-stone-900">{nf(taux, 0)}%</span>
          <span className="mt-0.5 text-[9px] font-semibold uppercase tracking-wider text-stone-500">réussite</span>
        </Anneau>
      </div>

      <div className="mt-6">
        {courbe.length > 0 ? (
          <CourbeCapital points={courbe} hauteur={150} />
        ) : (
          <div className="flex h-[150px] flex-col items-center justify-center rounded-2xl border border-dashed border-stone-300 bg-white/60 text-center">
            <LineChart className="h-7 w-7 text-amber-600" aria-hidden="true" />
            <p className="mt-2 text-sm font-medium text-stone-700">Votre courbe apparaîtra ici</p>
            <p className="mt-0.5 text-xs text-stone-500">Enregistrez au moins deux paris réglés pour la tracer.</p>
          </div>
        )}
      </div>

      <div className="mt-5 grid grid-cols-3 gap-2 text-center">
        {[
          { l: "Paris", v: stats?.nb_paris, c: "text-stone-900" },
          { l: "Gagnés", v: stats?.nb_gagnants, c: "text-emerald-700" },
          { l: "Perdus", v: stats?.nb_perdants, c: "text-rose-700" },
        ].map((k) => (
          <div key={k.l} className="rounded-xl bg-white/80 py-2.5 ring-1 ring-stone-200/70">
            <div className={cn("font-display text-lg font-black", k.c)}><Compteur valeur={k.v} /></div>
            <div className="text-[11px] text-stone-500">{k.l}</div>
          </div>
        ))}
      </div>

      <Link href={RUBRIQUES.suiviCapital.href} className="group mt-5 inline-flex items-center gap-1.5 text-sm font-semibold text-amber-800 hover:text-amber-950">
        Ouvrir le suivi du capital <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" aria-hidden="true" />
      </Link>
    </div>
  );
}

// ─── Accès rapide ───────────────────────────────────────────────
const RACCOURCIS = [
  { r: RUBRIQUES.assistant, icone: Cpu, fond: "from-violet-500 to-fuchsia-500" },
  { r: RUBRIQUES.strategies, icone: Target, fond: "from-sky-500 to-cyan-400" },
  { r: RUBRIQUES.statistiques, icone: BarChart3, fond: "from-emerald-500 to-teal-400" },
  { r: RUBRIQUES.resultats, icone: Radio, fond: "from-amber-500 to-orange-500" },
];

function AccesRapide() {
  return (
    <div className="h-full rounded-3xl bg-white p-5 ring-1 ring-stone-200/80 shadow-[0_30px_60px_-40px_rgba(28,25,23,.45)] sm:p-7">
      <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-100/70 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.16em] text-amber-900 ring-1 ring-amber-200">
        <Sparkles className="h-3 w-3" aria-hidden="true" /> Accès rapide
      </span>
      <h2 className="mt-3 font-display text-xl font-extrabold tracking-tight text-slate-900 sm:text-2xl">Vos outils</h2>
      <div className="mt-5 grid grid-cols-2 gap-3 [perspective:900px]">
        {RACCOURCIS.map(({ r, icone: Icone, fond }) => (
          <Link key={r.href} href={r.href} className="block">
            <Tilt max={12} className="esp-tuile h-full rounded-2xl bg-stone-50 ring-1 ring-stone-200/80 transition-colors hover:bg-white">
              <div className="p-3.5 sm:p-4">
                <span className={cn("esp-icone flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br text-white shadow-md", fond)}>
                  <Icone className="h-5 w-5" aria-hidden="true" />
                </span>
                <div className="mt-3 text-sm font-bold leading-tight text-stone-900">{r.label}</div>
                <div className="mt-0.5 line-clamp-2 text-[11px] leading-snug text-stone-500">{r.description}</div>
              </div>
            </Tilt>
          </Link>
        ))}
      </div>
    </div>
  );
}

// ─── Paris de valeur ────────────────────────────────────────────
function ParisDeValeur({ vbs, isPaid }: { vbs: ValueBet[]; isPaid: boolean }) {
  const { ref, hidden } = useReveal<HTMLDivElement>(0.25);

  if (!isPaid) {
    return (
      <Reveal>
        <div className="relative overflow-hidden rounded-3xl bg-white p-5 ring-1 ring-stone-200/80 sm:p-6">
          {/* Silhouette floutée de la liste : des barres, aucun cheval ni cote inventés. */}
          <div className="space-y-3 blur-[3px]" aria-hidden="true">
            {[78, 64, 52].map((w) => (
              <div key={w} className="flex items-center gap-3 rounded-2xl border border-stone-100 p-3">
                <div className="h-9 w-9 rounded-xl bg-amber-100" />
                <div className="flex-1 space-y-2">
                  <div className="h-3 rounded bg-stone-200" style={{ width: `${w}%` }} />
                  <div className="h-2 w-1/3 rounded bg-stone-100" />
                </div>
                <div className="h-5 w-12 rounded bg-emerald-100" />
              </div>
            ))}
          </div>
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-gradient-to-b from-white/40 via-white/85 to-white px-6 text-center">
            <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-gold text-white shadow-lg shadow-amber-500/30">
              <LockKeyhole className="h-5 w-5" aria-hidden="true" />
            </span>
            <p className="mt-3 font-display text-base font-bold text-stone-900">Réservé aux abonnés</p>
            <p className="mt-1 max-w-xs text-xs text-stone-500">Les paris de valeur en temps réel sont inclus dès l&apos;abonnement Standard.</p>
            <Button asChild size="sm" className="press btn-shimmer mt-4 rounded-xl bg-brand-gold font-bold text-brand-dark hover:bg-brand-gold-deep">
              <Link href={RUBRIQUES.tarifs.href}>Voir les abonnements</Link>
            </Button>
          </div>
        </div>
      </Reveal>
    );
  }

  if (vbs.length === 0) {
    return (
      <Reveal>
        <div className="flex flex-col items-center justify-center rounded-3xl border border-dashed border-stone-300 bg-white/70 px-6 py-12 text-center">
          <Zap className="h-7 w-7 text-amber-600" aria-hidden="true" />
          <p className="mt-2 text-sm font-medium text-stone-700">Aucun pari de valeur actif pour le moment</p>
          <p className="mt-0.5 text-xs text-stone-500">Le modèle en signale dès qu&apos;une cote dépasse la chance réelle d&apos;un cheval.</p>
        </div>
      </Reveal>
    );
  }

  const evMax = Math.max(...vbs.map((v) => v.ev), 0.01);
  const medailles = ["from-amber-300 to-amber-600", "from-stone-200 to-stone-400", "from-orange-300 to-orange-600"];

  return (
    <div ref={ref} className="space-y-3">
      {vbs.map((vb, i) => (
        <Link key={`${vb.course_id}-${i}`} href={`/courses/${vb.course_id}`} className="block">
          <Tilt max={4} className="rounded-2xl">
            <div
              className={cn(
                "group relative flex items-center gap-3 overflow-hidden rounded-2xl bg-white p-3.5 ring-1 ring-stone-200/80 transition-shadow hover:shadow-[0_20px_40px_-24px_rgba(180,83,9,.45)] hover:ring-amber-300 sm:gap-4 sm:p-4",
                !hidden && "esp-ligne",
              )}
              style={{ animationDelay: `${i * 110}ms` }}
            >
              <span className={cn("tr-pop flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br font-display text-base font-black text-white shadow-md", medailles[i] ?? medailles[2])}>
                {i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex min-w-0 items-center gap-2 text-sm font-semibold text-stone-900">
                  <IdentiteCheval numero={vb.numero} nom={vb.nom_cheval} courseId={vb.course_id} />
                  <span className="hidden sm:inline"><Etoiles n={vb.niveau} /></span>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-stone-500">
                  <span className="truncate">{vb.hippodrome}</span>
                  {vb.heure && <span className="inline-flex items-center gap-0.5"><Clock className="h-3 w-3" aria-hidden="true" />{vb.heure}</span>}
                  {vb.discipline && <span className="rounded bg-stone-100 px-1.5 py-px font-medium capitalize text-stone-600">{vb.discipline}</span>}
                </div>
                <div className="mt-2 h-1 overflow-hidden rounded-full bg-stone-100">
                  <div className="tr-bar h-full rounded-full bg-gradient-to-r from-emerald-500 to-teal-400" style={{ width: hidden ? "0%" : `${Math.max(6, (vb.ev / evMax) * 100)}%` }} />
                </div>
              </div>
              <div className="shrink-0 text-right">
                <div className={cn("font-display text-lg font-black tabular-nums", vb.ev > 0 ? "text-emerald-700" : "text-rose-700")}>
                  {vb.ev > 0 ? "+" : ""}{Math.round(vb.ev * 100)}%
                </div>
                {vb.cote && <div className="text-[11px] text-stone-500">cote {vb.cote}</div>}
              </div>
              <ChevronRight className="hidden h-4 w-4 shrink-0 text-stone-300 transition-transform group-hover:translate-x-0.5 group-hover:text-amber-700 sm:block" aria-hidden="true" />
            </div>
          </Tilt>
        </Link>
      ))}
    </div>
  );
}

// ─── Frise des prochaines courses ──────────────────────────────
function FriseProgramme({ courses }: { courses: CourseJour[] }) {
  const { ref, hidden } = useReveal<HTMLOListElement>(0.2);

  if (courses.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-3xl border border-dashed border-stone-300 bg-white/70 px-6 py-12 text-center">
        <Calendar className="h-7 w-7 text-amber-600" aria-hidden="true" />
        <p className="mt-2 text-sm font-medium text-stone-700">Aucune course pour le moment</p>
      </div>
    );
  }

  return (
    <ol ref={ref} className="relative space-y-2.5 rounded-3xl bg-white p-3 ring-1 ring-stone-200/80 shadow-[0_30px_60px_-40px_rgba(28,25,23,.45)] sm:p-4">
      {/* Rail doré qui relie les horaires */}
      <span className="pointer-events-none absolute bottom-8 left-[2.35rem] top-8 w-px bg-gradient-to-b from-amber-400 via-amber-200 to-transparent sm:left-[2.6rem]" aria-hidden="true" />
      {courses.map((c, i) => {
        const direct = c.statut === "en_cours";
        const finie = c.statut === "termine";
        return (
          <li key={c.course_id} className={cn(!hidden && "esp-ligne")} style={{ animationDelay: `${i * 90}ms` }}>
            <Link
              href={`/courses/${c.course_id}`}
              className="group relative flex items-center gap-3 rounded-2xl p-2 transition-colors hover:bg-amber-50/70"
            >
              <span className={cn(
                "relative z-10 flex h-11 w-14 shrink-0 flex-col items-center justify-center rounded-xl font-display text-sm font-black tabular-nums ring-1",
                direct ? "bg-emerald-600 text-white ring-emerald-500 shadow-[0_8px_20px_-8px_rgba(5,150,105,.8)]"
                  : finie ? "bg-stone-100 text-stone-400 ring-stone-200"
                  : "bg-[#0b0d12] text-amber-300 ring-stone-800 shadow-[0_8px_18px_-10px_rgba(11,13,18,.9)]",
              )}>
                {c.heure ?? "—"}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className={cn("truncate text-sm font-semibold", finie ? "text-stone-400" : "text-stone-900")}>
                    {c.hippodrome ?? c.nom ?? "—"}
                  </span>
                  {c.est_quinte && (
                    <span className="shrink-0 rounded-md bg-gradient-gold px-1.5 py-px text-[9px] font-black uppercase text-white">Quinté+</span>
                  )}
                </div>
                <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-stone-500">
                  {c.discipline && <span className="capitalize">{c.discipline.toLowerCase()}</span>}
                  {c.discipline && c.nb_partants ? <span aria-hidden="true">·</span> : null}
                  {c.nb_partants ? <span>{c.nb_partants} partants</span> : null}
                </div>
              </div>
              {direct ? (
                <span className="flex shrink-0 items-center gap-1.5 text-[11px] font-bold text-emerald-700">
                  <span className="live-dot h-2 w-2 rounded-full bg-emerald-500" aria-hidden="true" /> En direct
                </span>
              ) : finie ? (
                <span className="shrink-0 text-[11px] text-stone-400">Terminée</span>
              ) : (
                <ArrowRight className="h-4 w-4 shrink-0 text-stone-300 transition-all group-hover:translate-x-0.5 group-hover:text-amber-700" aria-hidden="true" />
              )}
            </Link>
          </li>
        );
      })}
    </ol>
  );
}
