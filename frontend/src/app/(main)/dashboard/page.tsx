"use client";

/**
 * Mon espace — tableau de bord de l'abonné.
 *
 * Registre sobre, celui de « Comment ça marche » sur l'accueil : fond ivoire,
 * panneaux blancs aux ombres étagées, pierre et or employé avec parcimonie. Le
 * relief passe par des plans légèrement inclinés qui suivent le pointeur
 * (`Plan3D`, `Tilt`) plutôt que par des effets lumineux.
 */

import Link from "next/link";
import useSWR from "swr";
import {
  Activity, ArrowRight, ArrowUpRight, Medal, Calendar, CheckCircle2, Clock, Cpu, LockKeyhole,
  Radio, Target, TrendingDown, TrendingUp, Trophy,
} from "lucide-react";
import { format } from "date-fns";
import { fr } from "date-fns/locale";
import { Button } from "@/components/ui/button";
import { CasaqueNumero, IdentiteCheval } from "@/components/courses/identite-cheval";
import { Reveal, Tilt, useReveal } from "@/components/track-record/effets";
import { Anneau, Compteur, Etoiles, Plan3D, SectionTitre, nf } from "@/components/espace/kit";
import { useRequireAuth } from "@/hooks/useAuth";
import { defiApi, predictionsApi, coursesApi, statsApi, type DefiMoi } from "@/lib/api";
import { BOUTON_OR, CompteRebours, DEFI_CARTE, DefiEntete, ResultatPari, formatPts, moisLabel } from "@/components/defi/kit";
import { DefiClassementLive } from "@/components/defi/DefiClassementLive";
import { RUBRIQUES } from "@/lib/navigation";
import { cn, planLabel } from "@/lib/utils";
import { disciplineLabel, heureParis, titleCase } from "@/lib/seo";

// ─── Types ──────────────────────────────────────────────────────
/** Forme réelle de `/programme` (cf. `CourseSummary` côté API) : l'heure vient de
 *  `date_heure` et l'hippodrome de la COURSE, jamais de la réunion. */
interface CourseJour {
  course_id: string;
  nom?: string | null;
  numero: number;
  numero_reunion?: number | null;
  date_heure: string;
  hippodrome_nom: string;
  discipline: string;
  distance?: number;
  nb_partants?: number;
  statut?: string;
  est_quinte?: boolean;
  est_quarte?: boolean;
  est_tierce?: boolean;
  penetrometre_desc?: string | null;
  pool_total_eur?: number | null;
}

interface Reunion {
  numero?: number;
  hippodrome?: string;
  courses?: CourseJour[];
}

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
  proba_top1_low?: number | null;
  proba_top1_high?: number | null;
  /** Accord des modèles, 0-100. */
  confidence?: number;
  cote_pmu?: number | null;
  date_heure?: string;
  discipline?: string;
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
  gain_potentiel?: number | null;
  probabilite: number;
  ev: number;
  raisons: string[];
  date_heure?: string | null;
  discipline?: string | null;
}

interface ValueBet {
  nom_cheval: string;
  numero?: number | null;
  hippodrome: string;
  discipline?: string;
  heure?: string;
  date_heure?: string | null;
  code?: string | null;
  ev: number;
  niveau: number;
  cote?: number;
  course_id: string;
}

const euros = (n?: number | null, d = 0) => (n == null ? "—" : `${nf(n, d)}\u00a0€`);
const pct = (x?: number | null) => (x == null ? "—" : `${Math.round(x * 100)}\u00a0%`);
const heureDe = (iso?: string | null, repli?: string | null) => (iso ? heureParis(iso) : repli ?? null);

const lienDiscret = "group inline-flex items-center gap-1 text-sm font-medium text-stone-600 transition-colors hover:text-stone-900";

// ─── En-tête ────────────────────────────────────────────────────
function PariDuJourCarte({ p }: { p: PariDuJour }) {
  const proba = Math.round((p.proba_top1 ?? 0) * 100);
  const ev = Math.round((p.ev ?? 0) * 100);
  return (
    <Link href={`/courses/${p.course_id}`} className="group block" aria-label={`Pari du jour : ${p.nom_cheval}, ${p.code} à ${p.hippodrome}`}>
      <div className="esp-panneau relative overflow-hidden rounded-[1.4rem]">
        <div className="h-1 bg-gradient-to-r from-amber-700 via-amber-500 to-amber-300" aria-hidden="true" />
        <div className="p-5 sm:p-7">
          <div className="flex items-center justify-between gap-3 text-[11px]">
            <span className="font-medium uppercase tracking-[0.2em] text-amber-800">Pari du jour</span>
            <span className="truncate text-stone-500">
              {[p.code, titleCase(p.hippodrome), p.date_heure && heureParis(p.date_heure)].filter(Boolean).join(" · ")}
            </span>
          </div>

          <div className="mt-6 flex items-center gap-5">
            <Anneau pct={proba} taille={96} epaisseur={5} couleur={["#B45309", "#F59E0B"]} fond="rgba(120,113,108,.14)">
              <span className="font-display text-2xl font-medium leading-none text-stone-900">{proba}<span className="text-sm text-stone-500"> %</span></span>
              <span className="mt-1 text-[9px] font-medium uppercase tracking-wider text-stone-500">victoire</span>
            </Anneau>
            <div className="min-w-0 flex-1">
              <div className="text-lg font-semibold text-stone-900">
                <IdentiteCheval numero={p.numero} nom={p.nom_cheval} courseId={p.course_id} />
              </div>
              {p.discipline && <div className="mt-1 text-xs text-stone-500">{disciplineLabel(p.discipline)}</div>}
              <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
                {p.cote_pmu ? (<><dt className="text-stone-500">Cote PMU</dt><dd className="text-right font-semibold tabular-nums text-stone-900">{p.cote_pmu}</dd></>) : null}
                {p.cote_pmu ? (<><dt className="text-stone-500">Cote juste</dt><dd className="text-right font-semibold tabular-nums text-stone-900">{p.proba_top1 ? nf(1 / p.proba_top1, 1) : "—"}</dd></>) : null}
                <dt className="text-stone-500">EV</dt>
                <dd className={cn("text-right font-semibold tabular-nums", ev > 0 ? "text-emerald-700" : "text-stone-900")}>{ev > 0 ? "+" : ""}{ev} %</dd>
                {p.proba_top1_low != null && p.proba_top1_high != null && (<><dt className="text-stone-500">Fourchette</dt><dd className="text-right tabular-nums text-stone-700">{Math.round(p.proba_top1_low * 100)} – {Math.round(p.proba_top1_high * 100)} %</dd></>)}
                {p.confidence != null && (<><dt className="text-stone-500">Accord des modèles</dt><dd className="text-right tabular-nums text-stone-700">{p.confidence} %</dd></>)}
                <dt className="text-stone-500">Niveau</dt>
                <dd className="text-right"><Niveau n={p.niveau} /></dd>
              </dl>
              {p.edge_valide && (
                <span
                  className="mt-3 inline-flex items-center gap-1 text-[11px] font-medium text-stone-600"
                  title="Signaux historiquement gagnants confirmés hors échantillon (taux de gain 3 à 4 fois le marché sur le passé). Pas une garantie."
                >
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" aria-hidden="true" /> Signal validé sur l&apos;historique
                </span>
              )}
            </div>
          </div>

          {p.raison && <p className="mt-5 line-clamp-2 border-l-2 border-amber-200 pl-3 text-[13px] leading-relaxed text-stone-600">{p.raison}</p>}

          <div className="mt-6 flex items-center justify-between border-t border-stone-100 pt-4 text-sm font-medium text-stone-900">
            Voir l&apos;analyse de la course
            <ArrowRight className="h-4 w-4 text-stone-400 transition-all group-hover:translate-x-1 group-hover:text-stone-900" aria-hidden="true" />
          </div>
        </div>
      </div>
    </Link>
  );
}

/** Niveau d'un pari de valeur, de 1 à 4 étoiles. */
function Niveau({ n }: { n: number }) {
  return <Etoiles n={n} taille="h-3 w-3" />;
}

/** Sans pari du jour (tôt le matin, jour sans course) : une carte vers le programme. */
function PariDuJourAttente() {
  return (
    <Link href={RUBRIQUES.coursesDuJour.href} className="group block">
      <div className="esp-panneau rounded-[1.4rem] p-6 sm:p-7">
        <span className="text-[11px] font-medium uppercase tracking-[0.2em] text-stone-500">Pari du jour</span>
        <p className="mt-4 font-display text-xl font-medium text-stone-900">Pas encore de sélection.</p>
        <p className="mt-2 text-sm leading-relaxed text-stone-500">
          Le pari du jour est publié dès qu&apos;une course présente un écart net entre la chance d&apos;un cheval et sa cote.
        </p>
        <span className="mt-5 inline-flex items-center gap-1.5 text-sm font-medium text-stone-900">
          {RUBRIQUES.coursesDuJour.label} <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" aria-hidden="true" />
        </span>
      </div>
    </Link>
  );
}

/** Une colonne du relevé de chiffres clés. */
function Chiffre({ libelle, children, note }: { libelle: string; children: React.ReactNode; note?: React.ReactNode }) {
  return (
    <div className="px-4 py-4 sm:px-6 sm:py-5">
      <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-stone-500">{libelle}</div>
      <div className="mt-2 whitespace-nowrap font-display text-2xl font-medium tracking-tight text-stone-900 sm:text-[1.9rem]">{children}</div>
      <div className="mt-1 min-h-[1rem] text-xs text-stone-500">{note}</div>
    </div>
  );
}

// ─── Page ───────────────────────────────────────────────────────
export default function DashboardPage() {
  const { user } = useRequireAuth();
  const plan = user?.plan ?? "free";
  const isPaid = !!user && !["free", "decouverte"].includes(plan);

  const { data: defi } = useSWR<DefiMoi>(user ? ["/defi/moi", user.user_id] : null, () => defiApi.moi().then((r) => r.data), { refreshInterval: 60_000 });
  const { data: summary } = useSWR("dashboard-summary", () => statsApi.dashboardSummary().then((r) => r.data), { refreshInterval: 120_000 });
  const { data: programme } = useSWR("programme-today", () => coursesApi.programme().then((r) => r.data), { refreshInterval: 180_000 });
  const { data: pariDuJour } = useSWR<PariDuJour | null>("pari-du-jour", () => predictionsApi.pariDuJour().then((r) => r.data), { refreshInterval: 120_000 });
  const { data: parisProfils } = useSWR<{ profils?: PariProfil[] }>("pari-du-jour-profils", () => predictionsApi.pariDuJourProfils().then((r) => r.data), { refreshInterval: 120_000 });

  // Prochaines courses : à venir / en cours d'abord, triées par heure.
  // Si tout est terminé (soirée), on retombe sur les dernières courses.
  const reunions: Reunion[] = programme?.reunions ?? [];
  const toutes: CourseJour[] = reunions
    .flatMap((r) => (r.courses ?? []).map((c) => ({ ...c, hippodrome_nom: c.hippodrome_nom || r.hippodrome || "" })))
    .sort((a, b) => a.date_heure.localeCompare(b.date_heure));
  const aVenir = toutes.filter((c) => c.statut === "a_venir" || c.statut === "en_cours");
  const courses = (aVenir.length > 0 ? aVenir : toutes.slice(-6)).slice(0, 6);
  const aDesProchaines = aVenir.length > 0;

  const topVbs: ValueBet[] = summary?.top_vbs ?? [];
  const profils = parisProfils?.profils ?? [];

  const roiDefi: number | null = defi?.roi ?? null;

  return (
    <div className="min-h-screen bg-background">
      {/* ══ En-tête ═════════════════════════════════════════════════ */}
      <header className="relative isolate overflow-hidden border-b border-stone-200/70 bg-gradient-to-b from-[#FBF8F2] to-background">
        <div className="pointer-events-none absolute -right-40 -top-40 -z-10 h-[32rem] w-[32rem] rounded-full bg-amber-100/60 blur-3xl" aria-hidden="true" />

        <div className="mx-auto max-w-7xl px-4 pb-10 pt-8 sm:px-6 sm:pb-14 sm:pt-14 lg:px-8">
          <div className="grid items-center gap-10 lg:grid-cols-[minmax(0,6fr)_minmax(0,5fr)] lg:gap-16">
            <Reveal>
              <div className="flex flex-wrap items-center gap-3 text-[11px] font-medium uppercase tracking-[0.2em] text-stone-500">
                <span className="flex items-center gap-2">
                  <span className="h-px w-6 bg-amber-600/70" aria-hidden="true" />
                  {RUBRIQUES.monEspace.label}
                </span>
                <span className="rounded-full border border-stone-300 px-2 py-0.5 text-[10px] tracking-[0.14em] text-stone-600">
                  {planLabel(plan)}
                </span>
              </div>

              <h1 className="mt-5 font-display text-[2.2rem] font-medium leading-[1.05] tracking-tight text-stone-900 sm:text-[3.4rem]">
                Bonjour{user?.prenom ? `, ${user.prenom}` : ""}.
              </h1>
              <p className="mt-3 text-base capitalize text-stone-500">
                {format(new Date(), "EEEE d MMMM yyyy", { locale: fr })}
              </p>

              {summary && (
                <p className="mt-6 max-w-lg text-[15px] leading-relaxed text-stone-600">
                  {summary.nb_courses_jour} course{summary.nb_courses_jour > 1 ? "s" : ""} au programme aujourd&apos;hui
                  {summary.nb_vbs_actifs ? <>, dont <span className="font-semibold text-stone-900">{summary.nb_vbs_actifs} pari{summary.nb_vbs_actifs > 1 ? "s" : ""} de valeur</span> en cours</> : null}.
                  {summary.nb_en_cours ? (
                    <span className="ml-2 inline-flex items-center gap-1.5 whitespace-nowrap text-sm text-emerald-700">
                      <span className="live-dot h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden="true" />
                      {summary.nb_en_cours} en direct
                    </span>
                  ) : null}
                </p>
              )}

              <div className="mt-7 flex flex-wrap gap-3">
                <Button asChild size="lg" className="press h-12 rounded-xl bg-stone-900 px-6 font-medium text-white shadow-[0_12px_24px_-12px_rgba(28,25,23,.6)] hover:bg-stone-800">
                  <Link href={RUBRIQUES.coursesDuJour.href}>
                    <Calendar className="mr-2 h-4 w-4" aria-hidden="true" /> {RUBRIQUES.coursesDuJour.label}
                  </Link>
                </Button>
                <Button asChild size="lg" variant="outline" className="press h-12 rounded-xl border-stone-300 bg-white px-6 font-medium text-stone-900 hover:bg-stone-50">
                  <Link href={RUBRIQUES.quinte.href}>
                    <Trophy className="mr-2 h-4 w-4 text-amber-700" aria-hidden="true" /> {RUBRIQUES.quinte.label}
                  </Link>
                </Button>
              </div>
            </Reveal>

            <Reveal delay={120}>
              <Plan3D className="mx-auto w-full max-w-md lg:max-w-none">
                {pariDuJour ? <PariDuJourCarte p={pariDuJour} /> : <PariDuJourAttente />}
              </Plan3D>
            </Reveal>
          </div>

          {/* Relevé des chiffres clés : un seul panneau, quatre colonnes. */}
          <Reveal delay={200}>
            <div className="esp-panneau mt-12 grid grid-cols-2 overflow-hidden rounded-2xl lg:grid-cols-4 [&>*]:border-stone-100 [&>*:nth-child(odd)]:border-r [&>*:nth-child(-n+2)]:border-b lg:[&>*:nth-child(-n+2)]:border-b-0 lg:[&>*:nth-child(-n+3)]:border-r">
              <Chiffre
                libelle="Solde du défi"
                note={defi && (defi.rang != null
                  ? <span className="font-medium text-amber-800">{defi.rang}{defi.rang === 1 ? "er" : "e"} sur {defi.nb_classes}</span>
                  : `encore ${Math.max(0, 10 - defi.nb_paris)} paris pour être classé`)}
              >
                <Compteur valeur={defi?.solde ?? null} suffixe={" pts"} />
              </Chiffre>
              <Chiffre libelle="Paris du défi" note={defi && roiDefi != null && (
                <span className={cn("inline-flex items-center gap-1 font-medium", roiDefi >= 0 ? "text-emerald-700" : "text-rose-700")}>
                  {roiDefi >= 0 ? <TrendingUp className="h-3 w-3" aria-hidden="true" /> : <TrendingDown className="h-3 w-3" aria-hidden="true" />}
                  {roiDefi > 0 ? "+" : ""}{nf(roiDefi, 1)} % de rendement
                </span>
              )}>
                <Compteur valeur={defi?.nb_paris ?? null} />
              </Chiffre>
              <Chiffre libelle={RUBRIQUES.parisDeValeur.label} note={(summary?.nb_vbs_premium ?? 0) > 0 ? `dont ${summary.nb_vbs_premium} de niveau 3 ou plus` : null}>
                <Compteur valeur={summary?.nb_vbs_actifs} />
              </Chiffre>
              <Chiffre libelle="Courses du jour" note={(summary?.nb_en_cours ?? 0) > 0 ? `${summary.nb_en_cours} en cours` : null}>
                <Compteur valeur={summary?.nb_courses_jour} />
              </Chiffre>
            </div>
          </Reveal>
        </div>
      </header>

      <div className="mx-auto max-w-7xl space-y-14 px-4 py-12 sm:space-y-20 sm:px-6 sm:py-16 lg:px-8">
        {/* ══ Le pari du jour par profil ══════════════════════════════ */}
        {profils.length > 0 && (
          <section>
            <SectionTitre sur="Selon votre profil" titre="Trois façons de jouer aujourd'hui" />
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3 sm:gap-5">
              {profils.map((p, i) => <CarteProfil key={p.profil} p={p} i={i} />)}
            </div>
          </section>
        )}

        {/* ══ Défi du mois + outils ═════════════════════════════════════ */}
        <section className="grid grid-cols-1 gap-6 lg:grid-cols-5">
          <Reveal className="lg:col-span-3">
            <PanneauDefi defi={defi} />
          </Reveal>
          <Reveal className="lg:col-span-2" delay={120}>
            <Outils modele={summary} />
          </Reveal>
        </section>

        {/* ══ Paris de valeur + prochaines courses ═════════════════════ */}
        <section className="grid grid-cols-1 gap-10 lg:grid-cols-5 lg:gap-6">
          <div className="lg:col-span-3">
            <SectionTitre
              sur="Sélection du moment"
              titre="Meilleurs paris de valeur"
              aside={<Link href={RUBRIQUES.parisDeValeur.href} className={lienDiscret}>Voir tous <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" aria-hidden="true" /></Link>}
            />
            <ParisDeValeur vbs={topVbs} isPaid={isPaid} />
          </div>
          <div className="lg:col-span-2">
            <SectionTitre
              sur="Programme"
              titre={aDesProchaines ? "Prochaines courses" : "Courses du jour"}
              aside={<Link href={RUBRIQUES.coursesDuJour.href} className={lienDiscret}>Tout voir <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" aria-hidden="true" /></Link>}
            />
            <ProchainesCourses courses={courses} />
          </div>
        </section>
      </div>
    </div>
  );
}

// ─── Cartes par profil ──────────────────────────────────────────
const PROFIL_TEINTE: Record<string, { filet: string; texte: string; barre: string }> = {
  conservateur: { filet: "bg-emerald-700", texte: "text-emerald-800", barre: "bg-emerald-700" },
  equilibre: { filet: "bg-stone-800", texte: "text-stone-800", barre: "bg-stone-800" },
  agressif: { filet: "bg-amber-700", texte: "text-amber-800", barre: "bg-amber-700" },
};

function CarteProfil({ p, i }: { p: PariProfil; i: number }) {
  const t = PROFIL_TEINTE[p.profil] ?? PROFIL_TEINTE.equilibre;
  const proba = Math.round((p.probabilite ?? 0) * 100);
  const { ref, hidden } = useReveal<HTMLDivElement>(0.3);
  return (
    <Reveal delay={i * 110}>
      <Link href={`/courses/${p.course_id}`} className="group block h-full">
        <Tilt max={4} className="h-full rounded-2xl">
          <div ref={ref} className="esp-panneau relative flex h-full flex-col overflow-hidden rounded-2xl p-5 sm:p-6">
            <span className={cn("absolute inset-x-0 top-0 h-[3px]", t.filet)} aria-hidden="true" />
            <div className="flex items-center justify-between gap-2">
              <span className={cn("text-[11px] font-semibold uppercase tracking-[0.16em]", t.texte)}>{p.profil_label}</span>
              <span className="truncate text-[11px] text-stone-400">
                {[p.code, titleCase(p.hippodrome), heureDe(p.date_heure)].filter(Boolean).join(" · ")}
              </span>
            </div>
            <div className="mt-4 font-display text-lg font-medium text-stone-900">{p.type_pari}</div>
            {p.discipline && <div className="text-[11px] text-stone-500">{disciplineLabel(p.discipline)}</div>}
            {/* Casaque + dossard + nom de chaque cheval joué. */}
            <ul className="mt-3 space-y-1.5">
              {(p.chevaux ?? []).map((c) => (
                <li key={c.numero} className="flex min-w-0 items-center gap-2 text-sm text-stone-800">
                  {c.nom
                    ? <IdentiteCheval numero={c.numero} nom={titleCase(c.nom)} courseId={p.course_id} />
                    : <CasaqueNumero numero={c.numero} courseId={p.course_id} />}
                </li>
              ))}
            </ul>

            <dl className="mt-4 grid grid-cols-2 gap-3 rounded-xl bg-stone-50 px-3 py-2.5 text-xs ring-1 ring-stone-100">
              <div>
                <dt className="text-stone-500">Mise conseillée</dt>
                <dd className="mt-0.5 font-display text-base font-medium tabular-nums text-stone-900">{euros(p.mise, 2)}</dd>
              </div>
              <div className="text-right">
                <dt className="text-stone-500">Gain possible</dt>
                <dd className="mt-0.5 font-display text-base font-medium tabular-nums text-stone-900">{euros(p.gain_potentiel, 2)}</dd>
              </div>
            </dl>

            <div className="mt-6 flex items-baseline justify-between border-t border-stone-100 pt-4">
              <span className="text-xs text-stone-500">Chance de toucher</span>
              <span className="font-display text-2xl font-medium tabular-nums text-stone-900">{proba}<span className="text-sm text-stone-500"> %</span></span>
            </div>
            <div className="mt-2 h-1 overflow-hidden rounded-full bg-stone-100">
              <div className={cn("tr-bar h-full rounded-full", t.barre)} style={{ width: hidden ? "0%" : `${Math.max(2, proba)}%` }} />
            </div>
            <div className={cn("mt-2 text-right text-[11px] font-medium", p.ev > 0 ? "text-emerald-700" : "text-stone-500")}>
              EV {p.ev > 0 ? "+" : ""}{Math.round((p.ev ?? 0) * 100)} %
            </div>
            {p.raisons?.[0] && <p className="mt-3 line-clamp-2 text-xs leading-relaxed text-stone-500">{p.raisons[0]}</p>}
          </div>
        </Tilt>
      </Link>
    </Reveal>
  );
}

// ─── Défi du mois ───────────────────────────────────────────────
function PanneauDefi({ defi }: { defi?: DefiMoi }) {
  const derniers = (defi?.paris ?? []).slice(0, 4);
  return (
    <div className={cn(DEFI_CARTE, "h-full")}>
      <DefiEntete
        surtitre={defi ? `Défi du mois · ${moisLabel(defi.mois)}` : "Défi du mois"}
        titre="Ma saison"
        sousTitre={!defi ? undefined : defi.rang != null
          ? <><b className="text-amber-800">{defi.rang}{defi.rang === 1 ? "er" : "e"}</b> sur {defi.nb_classes} joueurs classés</>
          : defi.nb_paris === 0 ? "Vos points du mois vous attendent : engagez votre premier pari."
          : `Encore ${Math.max(0, 10 - defi.nb_paris)} paris pour entrer au classement.`}
        droite={defi && <CompteRebours mois={defi.mois} />}
      >
        <div className="mt-4 flex flex-wrap items-end justify-between gap-3">
          <div className="font-display text-4xl font-bold tracking-tight text-slate-900 sm:text-5xl">
            <Compteur valeur={defi?.solde ?? null} suffixe={" pts"} />
          </div>
          <Link href={RUBRIQUES.coursesDuJour.href}
            className={cn(BOUTON_OR, "press h-11 text-sm")}>
            <Medal className="h-4 w-4" aria-hidden="true" /> Parier mes points
          </Link>
        </div>
      </DefiEntete>

      <div className="p-5 sm:p-6">
        {defi && defi.nb_paris > 0 && (
          <div className="mb-5 grid grid-cols-2 gap-3">
            {([["Plan de mise", defi.plan], ["Mes choix perso", defi.perso]] as const).map(([l, st]) => (
              <div key={l} className="rounded-2xl bg-stone-50 p-4 ring-1 ring-stone-100">
                <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-stone-500">{l}</div>
                <div className={cn("mt-1 font-display text-xl font-bold tabular-nums", st.points_nets >= 0 ? "text-emerald-700" : "text-rose-700")}>
                  {formatPts(st.points_nets, true)}
                </div>
                <div className="text-xs text-stone-500">{st.nb_paris} pari{st.nb_paris > 1 ? "s" : ""}</div>
              </div>
            ))}
          </div>
        )}

        <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-stone-500">Derniers paris</div>
        {derniers.length === 0 ? (
          <p className="mt-2 text-sm text-stone-500">
            Aucun pari ce mois-ci. Sur chaque course, l&apos;onglet « Défi du mois » permet de jouer vos chevaux ou ceux du plan de mise.
          </p>
        ) : (
          <ul className="mt-2 divide-y divide-stone-100">
            {derniers.map((p) => (
              <li key={p.pari_id} className="flex items-center justify-between gap-3 py-2.5">
                <Link href={`/courses/${p.course_id}#defi`} className="min-w-0 text-sm text-stone-800 hover:underline">
                  <span className="font-medium">{p.type_pari}</span> {p.chevaux.map((n) => `n°${n}`).join(" + ")}
                  <span className="block truncate text-xs text-stone-500">{p.course_label}</span>
                </Link>
                <ResultatPari p={p} />
              </li>
            ))}
          </ul>
        )}
        <Link href={RUBRIQUES.defi.href} className={cn(lienDiscret, "mt-3")}>
          Classement et règlement <ArrowUpRight className="h-4 w-4 transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" aria-hidden="true" />
        </Link>
      </div>
    </div>
  );
}

// ─── Outils ─────────────────────────────────────────────────────
const OUTILS = [
  { r: RUBRIQUES.assistant, icone: Cpu },
  { r: RUBRIQUES.strategies, icone: Target },
  { r: RUBRIQUES.resultats, icone: Radio },
];

interface EtatModele {
  precision_top3?: number | null;
  model_auc?: number | null;
  nb_courses_evaluees?: number;
  drift_severity?: string;
}

function Outils({ modele }: { modele?: EtatModele }) {
  const derive = modele?.drift_severity && modele.drift_severity !== "none";
  return (
    <div className="esp-panneau h-full rounded-3xl p-5 sm:p-8">
      <span className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.2em] text-stone-500">
        <span className="h-px w-5 bg-amber-600/70" aria-hidden="true" /> Accès rapide
      </span>
      <h2 className="mt-3 font-display text-xl font-medium tracking-tight text-stone-900 sm:text-[1.65rem]">Vos outils</h2>
      <DefiClassementLive top={3} className="mt-5" />
      <ul className="mt-5 divide-y divide-stone-100">
        {OUTILS.map(({ r, icone: Icone }) => (
          <li key={r.href}>
            <Link href={r.href} className="group flex items-center gap-4 py-3.5">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-b from-white to-stone-100 text-stone-700 shadow-[0_1px_0_#fff_inset,0_0_0_1px_rgba(28,25,23,.08),0_6px_12px_-8px_rgba(28,25,23,.35)] transition-transform duration-300 group-hover:-translate-y-0.5">
                <Icone className="h-[18px] w-[18px]" aria-hidden="true" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium text-stone-900">{r.label}</span>
                <span className="block truncate text-xs text-stone-500">{r.description}</span>
              </span>
              <ArrowRight className="h-4 w-4 shrink-0 text-stone-300 transition-all group-hover:translate-x-0.5 group-hover:text-stone-900" aria-hidden="true" />
            </Link>
          </li>
        ))}
      </ul>

      {/* État du modèle, tel que publié par /stats/dashboard-summary. Les chiffres
          absents (modèle non crédible, trop peu de courses) restent des tirets. */}
      {modele && (
        <div className="mt-5 rounded-2xl bg-stone-50 p-4 ring-1 ring-stone-100">
          <div className="flex items-center justify-between gap-2">
            <span className="inline-flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.16em] text-stone-500">
              <Activity className="h-3.5 w-3.5" aria-hidden="true" /> Le modèle
            </span>
            <span className={cn("inline-flex items-center gap-1.5 text-[11px] font-medium", derive ? "text-amber-700" : "text-emerald-700")}>
              <span className={cn("h-1.5 w-1.5 rounded-full", derive ? "bg-amber-500" : "bg-emerald-500")} aria-hidden="true" />
              {derive ? "Recalibrage en cours" : "Stable"}
            </span>
          </div>
          <dl className="mt-3 grid grid-cols-3 gap-2 text-center">
            <div>
              <dd className="font-display text-lg font-medium tabular-nums text-stone-900">{pct(modele.precision_top3)}</dd>
              <dt className="text-[10px] leading-tight text-stone-500">gagnant dans notre top 3</dt>
            </div>
            <div>
              <dd className="font-display text-lg font-medium tabular-nums text-stone-900">{modele.model_auc != null ? nf(modele.model_auc, 2) : "—"}</dd>
              <dt className="text-[10px] leading-tight text-stone-500">AUC</dt>
            </div>
            <div>
              <dd className="font-display text-lg font-medium tabular-nums text-stone-900">{modele.nb_courses_evaluees != null ? nf(modele.nb_courses_evaluees) : "—"}</dd>
              <dt className="text-[10px] leading-tight text-stone-500">courses évaluées</dt>
            </div>
          </dl>
          <Link href={RUBRIQUES.performances.href} className={cn(lienDiscret, "mt-3 text-xs")}>
            {RUBRIQUES.performances.label} <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
          </Link>
        </div>
      )}
    </div>
  );
}

// ─── Paris de valeur ────────────────────────────────────────────
function ParisDeValeur({ vbs, isPaid }: { vbs: ValueBet[]; isPaid: boolean }) {
  const { ref, hidden } = useReveal<HTMLDivElement>(0.25);

  if (!isPaid) {
    return (
      <Reveal>
        <div className="esp-panneau relative overflow-hidden rounded-3xl p-5 sm:p-6">
          {/* Silhouette floutée de la liste : des barres, aucun cheval ni cote inventés. */}
          <div className="space-y-4 blur-[3px]" aria-hidden="true">
            {[78, 64, 52].map((w) => (
              <div key={w} className="flex items-center gap-4 py-2">
                <div className="h-6 w-6 rounded bg-stone-100" />
                <div className="flex-1 space-y-2">
                  <div className="h-3 rounded bg-stone-200" style={{ width: `${w}%` }} />
                  <div className="h-2 w-1/3 rounded bg-stone-100" />
                </div>
                <div className="h-5 w-12 rounded bg-stone-100" />
              </div>
            ))}
          </div>
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-gradient-to-b from-white/50 via-white/90 to-white px-6 text-center">
            <LockKeyhole className="h-5 w-5 text-stone-700" aria-hidden="true" />
            <p className="mt-3 font-display text-base font-medium text-stone-900">Réservé aux abonnés</p>
            <p className="mt-1 max-w-xs text-xs text-stone-500">Les paris de valeur en temps réel sont inclus dès l&apos;abonnement Standard.</p>
            <Button asChild size="sm" className="press mt-4 rounded-lg bg-stone-900 font-medium text-white hover:bg-stone-800">
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
        <div className="rounded-3xl border border-dashed border-stone-200 px-6 py-12 text-center">
          <p className="text-sm font-medium text-stone-700">Aucun pari de valeur pour le moment</p>
          <p className="mt-1 text-xs text-stone-500">Une sélection apparaît dès qu&apos;une cote dépasse la chance réelle d&apos;un cheval.</p>
        </div>
      </Reveal>
    );
  }

  const evMax = Math.max(...vbs.map((v) => v.ev), 0.01);

  return (
    <div ref={ref} className="esp-panneau divide-y divide-stone-100 overflow-hidden rounded-3xl">
      {vbs.map((vb, i) => (
        <Link
          key={`${vb.course_id}-${i}`}
          href={`/courses/${vb.course_id}`}
          className={cn("group flex items-center gap-4 px-4 py-4 transition-colors hover:bg-stone-50/80 sm:px-6", !hidden && "esp-ligne")}
          style={{ animationDelay: `${i * 90}ms` }}
        >
          <span className="w-5 shrink-0 font-display text-lg font-medium tabular-nums text-stone-400">{i + 1}</span>
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-center gap-2 text-sm font-medium text-stone-900">
              <IdentiteCheval numero={vb.numero} nom={vb.nom_cheval} courseId={vb.course_id} />
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-stone-500">
              {vb.code && <span className="font-medium text-stone-600">{vb.code}</span>}
              <span className="truncate">{titleCase(vb.hippodrome)}</span>
              {heureDe(vb.date_heure, vb.heure) && <span className="inline-flex items-center gap-0.5"><Clock className="h-3 w-3" aria-hidden="true" />{heureDe(vb.date_heure, vb.heure)}</span>}
              {vb.discipline && <span>{disciplineLabel(vb.discipline)}</span>}
              <Niveau n={vb.niveau} />
            </div>
            <div className="mt-2.5 h-[3px] max-w-xs overflow-hidden rounded-full bg-stone-100">
              <div className="tr-bar h-full rounded-full bg-emerald-600/80" style={{ width: hidden ? "0%" : `${Math.max(6, (vb.ev / evMax) * 100)}%` }} />
            </div>
          </div>
          <div className="shrink-0 text-right">
            <div className={cn("font-display text-lg font-medium tabular-nums", vb.ev > 0 ? "text-emerald-700" : "text-rose-700")}>
              {vb.ev > 0 ? "+" : ""}{Math.round(vb.ev * 100)} %
            </div>
            <div className="text-[10px] uppercase tracking-wider text-stone-400">EV</div>
            {vb.cote && <div className="text-[11px] text-stone-500">cote {vb.cote}</div>}
          </div>
          <ArrowRight className="hidden h-4 w-4 shrink-0 text-stone-300 transition-all group-hover:translate-x-0.5 group-hover:text-stone-900 sm:block" aria-hidden="true" />
        </Link>
      ))}
    </div>
  );
}

// ─── Prochaines courses ─────────────────────────────────────────
function ProchainesCourses({ courses }: { courses: CourseJour[] }) {
  const { ref, hidden } = useReveal<HTMLOListElement>(0.2);

  if (courses.length === 0) {
    return (
      <div className="rounded-3xl border border-dashed border-stone-200 px-6 py-12 text-center">
        <p className="text-sm font-medium text-stone-700">Aucune course pour le moment</p>
      </div>
    );
  }

  return (
    <ol ref={ref} className="esp-panneau divide-y divide-stone-100 overflow-hidden rounded-3xl">
      {courses.map((c, i) => {
        const direct = c.statut === "en_cours";
        const finie = c.statut === "termine";
        return (
          <li key={c.course_id} className={cn(!hidden && "esp-ligne")} style={{ animationDelay: `${i * 80}ms` }}>
            <Link href={`/courses/${c.course_id}`} className="group flex items-center gap-4 px-4 py-3.5 transition-colors hover:bg-stone-50/80 sm:px-5">
              <span className={cn(
                "w-12 shrink-0 font-display text-base font-medium tabular-nums",
                direct ? "text-emerald-700" : finie ? "text-stone-300" : "text-stone-900",
              )}>
                {heureParis(c.date_heure)}
              </span>
              <span className={cn("h-8 w-px shrink-0", direct ? "bg-emerald-500" : "bg-stone-200")} aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  {c.numero_reunion ? <span className="shrink-0 text-[11px] font-medium text-stone-500">R{c.numero_reunion}C{c.numero}</span> : null}
                  <span className={cn("truncate text-sm font-medium", finie ? "text-stone-400" : "text-stone-900")}>
                    {titleCase(c.hippodrome_nom) || titleCase(c.nom) || "—"}
                  </span>
                  {(c.est_quinte || c.est_quarte || c.est_tierce) && (
                    <span className="shrink-0 rounded border border-amber-300 px-1 text-[9px] font-semibold uppercase tracking-wide text-amber-800">
                      {c.est_quinte ? "Quinté+" : c.est_quarte ? "Quarté+" : "Tiercé"}
                    </span>
                  )}
                </div>
                {c.nom && <div className="truncate text-[11px] text-stone-600">{titleCase(c.nom)}</div>}
                <div className="mt-0.5 truncate text-[11px] text-stone-500">
                  {[
                    disciplineLabel(c.discipline),
                    c.distance ? `${nf(c.distance)} m` : null,
                    c.nb_partants ? `${c.nb_partants} partants` : null,
                    c.penetrometre_desc ? titleCase(c.penetrometre_desc) : null,
                    c.pool_total_eur ? `${nf(c.pool_total_eur)} € d'enjeux` : null,
                  ].filter(Boolean).join(" · ")}
                </div>
              </div>
              {direct ? (
                <span className="flex shrink-0 items-center gap-1.5 text-[11px] font-medium text-emerald-700">
                  <span className="live-dot h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden="true" /> En direct
                </span>
              ) : finie ? (
                <span className="shrink-0 text-[11px] text-stone-400">Terminée</span>
              ) : (
                <ArrowRight className="h-4 w-4 shrink-0 text-stone-300 transition-all group-hover:translate-x-0.5 group-hover:text-stone-900" aria-hidden="true" />
              )}
            </Link>
          </li>
        );
      })}
    </ol>
  );
}
