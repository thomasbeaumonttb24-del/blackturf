"use client";

/**
 * Paris de valeur — même registre sobre que « Mon espace » : fond ivoire,
 * panneaux blancs aux ombres étagées, relief discret (`Plan3D`, `Tilt`).
 *
 * Chaque carte affiche tout ce que sert `/value-bets` (cf. `services/valuebets_lecture`
 * côté API) : casaque, jockey, entraîneur, musique, code course, chance calculée et
 * sa fourchette, chance selon la cote, cote juste, meilleure cote et son opérateur,
 * mouvement depuis l'ouverture, accord des modèles, afflux d'argent.
 */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import {
  ArrowRight, ArrowUpDown, Clock, LayoutGrid, List, Lock, RefreshCw, TrendingDown, TrendingUp, X, Zap,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { IdentiteCheval } from "@/components/courses/identite-cheval";
import { Reveal, Tilt } from "@/components/track-record/effets";
import { Compteur, Etoiles, Plan3D, SectionTitre, nf } from "@/components/espace/kit";
import { useAuth } from "@/hooks/useAuth";
import { useValueBetsStream } from "@/hooks/useWebSocket";
import { predictionsApi } from "@/lib/api";
import { RUBRIQUES } from "@/lib/navigation";
import { disciplineLabel, heureParis, titleCase } from "@/lib/seo";
import { cn } from "@/lib/utils";

// ─── Types ──────────────────────────────────────────────────────
type VB = {
  vb_id: string;
  course_id: string;
  nom_cheval: string;
  numero?: number | null;
  casaque_image_url?: string | null;
  jockey?: string | null;
  entraineur?: string | null;
  musique?: string | null;
  hippodrome_nom: string;
  date_heure: string;
  code?: string | null;
  nom_course?: string | null;
  discipline?: string | null;
  distance?: number | null;
  nb_partants?: number | null;
  est_quinte?: boolean;
  statut_course?: string | null;
  ev_max: number;
  niveau: number;
  meilleure_source?: string | null;
  detecte_a?: string | null;
  spi_detected: boolean;
  spi_score: number | null;
  proba_top1?: number | null;
  proba_top1_low?: number | null;
  proba_top1_high?: number | null;
  proba_top3?: number | null;
  rang_predit?: number | null;
  confiance?: number | null;
  cote_juste?: number | null;
  cote_pmu: number | null;
  cote_reference?: number | null;
  cote_betfair_exchange?: number | null;
  cote_max?: number | null;
  cote_max_source?: string | null;
  nb_sources?: number;
  /** Positif = la cote a BAISSÉ depuis l'ouverture (l'argent arrive dessus). */
  mouvement_cote_pct?: number | null;
};

const NIVEAU_LABEL: Record<number, string> = { 1: "Intéressant", 2: "Bon signal", 3: "Fort signal", 4: "Exceptionnel" };
const OPERATEUR: Record<string, string> = {
  pmu: "PMU", winamax: "Winamax", betclic: "Betclic", unibet: "Unibet",
  bet365: "Bet365", ladbrokes: "Ladbrokes", betfair: "Betfair", geny: "Geny", bzh: "BZH",
};
const TRIS = [
  { v: "ev", l: "Espérance" },
  { v: "proba", l: "Chance" },
  { v: "heure", l: "Heure" },
  { v: "cote", l: "Cote" },
  { v: "niveau", l: "Niveau" },
] as const;
type Tri = (typeof TRIS)[number]["v"];

// Tableau vide STABLE : `useValueBetsStream` renvoie un `[]` neuf à chaque rendu
// tant que le flux n'a rien dit, et un effet qui en dépendait bouclait sans fin
// (« Maximum update depth exceeded »).
const AUCUN: VB[] = [];

const pct = (x?: number | null, d = 0) => (x == null ? "—" : `${nf(x * 100, d)} %`);
const cote = (x?: number | null) => (x == null ? "—" : nf(x, 1));

// ─── Briques ────────────────────────────────────────────────────
function Niveau({ n, avecLibelle }: { n: number; avecLibelle?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap" title={NIVEAU_LABEL[n]}>
      <Etoiles n={n} />
      {avecLibelle && <span className="text-[11px] font-medium text-stone-600">{NIVEAU_LABEL[n]}</span>}
    </span>
  );
}

/** Chance calculée face à la chance que la cote suppose : l'écart EST le pari de valeur. */
function Ecart({ vb }: { vb: VB }) {
  const p = vb.proba_top1;
  const implicite = vb.cote_pmu && vb.cote_pmu > 1 ? 1 / vb.cote_pmu : null;
  if (p == null && implicite == null) return null;
  const max = Math.max(p ?? 0, implicite ?? 0, 0.01);
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2 text-[11px]">
        <span className="w-24 shrink-0 text-stone-500">Chance calculée</span>
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-stone-100">
          <div className="h-full rounded-full bg-emerald-600" style={{ width: `${((p ?? 0) / max) * 100}%` }} />
        </div>
        <span className="w-12 shrink-0 text-right font-semibold tabular-nums text-stone-900">{pct(p)}</span>
      </div>
      <div className="flex items-center gap-2 text-[11px]">
        <span className="w-24 shrink-0 text-stone-500">Selon la cote</span>
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-stone-100">
          <div className="h-full rounded-full bg-stone-400" style={{ width: `${((implicite ?? 0) / max) * 100}%` }} />
        </div>
        <span className="w-12 shrink-0 text-right tabular-nums text-stone-600">{pct(implicite)}</span>
      </div>
    </div>
  );
}

function Mouvement({ m, compact }: { m?: number | null; compact?: boolean }) {
  if (m == null || Math.abs(m) < 1) return compact ? null : <span className="text-stone-400">stable</span>;
  const baisse = m > 0;
  return (
    <span className={cn("inline-flex items-center gap-0.5 font-medium tabular-nums", baisse ? "text-emerald-700" : "text-rose-700")}
      title={baisse ? "La cote a baissé depuis l'ouverture : l'argent arrive sur ce cheval" : "La cote a monté depuis l'ouverture : le cheval est délaissé"}>
      {baisse ? <TrendingDown className="h-3 w-3" aria-hidden="true" /> : <TrendingUp className="h-3 w-3" aria-hidden="true" />}
      {nf(Math.abs(m), 0)}&nbsp;%
    </span>
  );
}

function EnTeteCourse({ vb }: { vb: VB }) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[11px] text-stone-500">
      {vb.code && <span className="shrink-0 font-semibold text-stone-700">{vb.code}</span>}
      <span className="min-w-0 break-words">{titleCase(vb.hippodrome_nom)}</span>
      <span aria-hidden="true">·</span>
      <span className="inline-flex shrink-0 items-center gap-0.5"><Clock className="h-3 w-3" aria-hidden="true" />{heureParis(vb.date_heure)}</span>
      {vb.est_quinte && <span className="shrink-0 rounded border border-amber-300 px-1 text-[9px] font-semibold uppercase tracking-wide text-amber-800">Quinté+</span>}
    </div>
  );
}

function DetailCourse({ vb }: { vb: VB }) {
  const bits = [
    vb.discipline && disciplineLabel(vb.discipline),
    vb.distance ? `${nf(vb.distance)} m` : null,
    vb.nb_partants ? `${vb.nb_partants} partants` : null,
  ].filter(Boolean);
  return bits.length ? <div className="break-words text-[11px] text-stone-500">{bits.join(" · ")}</div> : null;
}

function Equipe({ vb }: { vb: VB }) {
  if (!vb.jockey && !vb.entraineur && !vb.musique) return null;
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[11px]">
      {vb.jockey && (<><dt className="text-stone-500">Jockey</dt><dd className="min-w-0 break-words text-stone-800">{titleCase(vb.jockey)}</dd></>)}
      {vb.entraineur && (<><dt className="text-stone-500">Entraîneur</dt><dd className="min-w-0 break-words text-stone-800">{titleCase(vb.entraineur)}</dd></>)}
      {vb.musique && (<><dt className="text-stone-500">Musique</dt><dd className="min-w-0 break-all font-mono text-stone-800">{vb.musique}</dd></>)}
    </dl>
  );
}

// ─── Carte (grille) ─────────────────────────────────────────────
function CarteVB({ vb, isExpert }: { vb: VB; isExpert: boolean }) {
  const ev = Math.round(vb.ev_max * 100);
  return (
    <Link href={`/courses/${vb.course_id}`} className="group block h-full">
      <Tilt max={3} className="h-full rounded-2xl">
        <article className="esp-panneau relative flex h-full flex-col overflow-hidden rounded-2xl">
          {vb.niveau >= 4 && <span className="absolute inset-x-0 top-0 h-[3px] bg-gradient-to-r from-amber-700 via-amber-500 to-amber-300" aria-hidden="true" />}
          <div className="p-4 sm:p-5">
            <div className="flex items-center justify-between gap-2">
              <EnTeteCourse vb={vb} />
              <Niveau n={vb.niveau} />
            </div>

            <div className="mt-4 flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-base font-semibold text-stone-900">
                  <IdentiteCheval numero={vb.numero} nom={titleCase(vb.nom_cheval)} courseId={vb.course_id} imgUrl={vb.casaque_image_url} />
                </div>
                <div className="mt-1"><DetailCourse vb={vb} /></div>
              </div>
              <div className="shrink-0 text-right">
                <div className={cn("font-display text-2xl font-medium tabular-nums", ev > 0 ? "text-emerald-700" : "text-rose-700")}>
                  {ev > 0 ? "+" : ""}{ev}&nbsp;%
                </div>
                <div className="text-[10px] uppercase tracking-wider text-stone-400">Espérance</div>
              </div>
            </div>

            <div className="mt-4"><Ecart vb={vb} /></div>
            {vb.proba_top1_low != null && vb.proba_top1_high != null && (
              <div className="mt-1 text-right text-[10px] text-stone-400">
                fourchette {pct(vb.proba_top1_low)} – {pct(vb.proba_top1_high)}
              </div>
            )}
          </div>

          <dl className="grid grid-cols-3 border-y border-stone-100 bg-stone-50/60 text-center">
            <div className="px-2 py-2.5">
              <dt className="text-[10px] text-stone-500">Cote PMU</dt>
              <dd className="mt-0.5 font-display text-base font-medium tabular-nums text-stone-900">{cote(vb.cote_pmu)}</dd>
              {vb.cote_reference != null && <dd className="text-[10px] tabular-nums text-stone-400">ouv. {cote(vb.cote_reference)}</dd>}
            </div>
            <div className="border-x border-stone-100 px-2 py-2.5">
              <dt className="text-[10px] text-stone-500">Cote juste</dt>
              <dd className="mt-0.5 font-display text-base font-medium tabular-nums text-stone-900">{cote(vb.cote_juste)}</dd>
              <dd className="text-[10px] text-stone-400"><Mouvement m={vb.mouvement_cote_pct} /></dd>
            </div>
            <div className="px-2 py-2.5">
              <dt className="text-[10px] text-stone-500">Meilleure cote</dt>
              <dd className="mt-0.5 font-display text-base font-medium tabular-nums text-stone-900">{cote(vb.cote_max)}</dd>
              <dd className="text-[10px] text-stone-400">
                {vb.cote_max_source ? OPERATEUR[vb.cote_max_source] ?? vb.cote_max_source : "—"}
                {vb.nb_sources ? ` · ${vb.nb_sources} op.` : ""}
              </dd>
            </div>
          </dl>

          <div className="flex flex-1 flex-col gap-3 p-4 sm:p-5">
            <Equipe vb={vb} />
            <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-stone-500">
              {vb.confiance != null && <span>Accord des modèles <span className="font-semibold text-stone-800">{nf(vb.confiance)}&nbsp;%</span></span>}
              {vb.rang_predit != null && <span>{vb.rang_predit === 1 ? "1er" : `${vb.rang_predit}e`} du classement</span>}
              {vb.proba_top3 != null && <span>Podium {pct(vb.proba_top3)}</span>}
              {isExpert && vb.spi_detected && (
                <span className="inline-flex items-center gap-1 font-medium text-amber-800" title="Chute rapide de la cote : de l'argent arrive sur ce cheval">
                  <Zap className="h-3 w-3" aria-hidden="true" /> Afflux d&apos;argent
                </span>
              )}
            </div>
            <div className="flex items-center justify-between border-t border-stone-100 pt-3 text-xs">
              <span className="text-stone-400">{vb.detecte_a ? `Repéré à ${heureParis(vb.detecte_a)}` : ""}</span>
              <span className="inline-flex items-center gap-1 font-medium text-stone-700 group-hover:text-stone-900">
                Voir la course <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
              </span>
            </div>
          </div>
        </article>
      </Tilt>
    </Link>
  );
}

// ─── Ligne (liste) ──────────────────────────────────────────────
function LigneVB({ vb, isExpert }: { vb: VB; isExpert: boolean }) {
  const ev = Math.round(vb.ev_max * 100);
  return (
    <Link href={`/courses/${vb.course_id}`} className="group grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1 px-4 py-3.5 transition-colors hover:bg-stone-50/80 sm:grid-cols-[minmax(0,2.2fr)_repeat(4,minmax(0,1fr))_auto] sm:px-5">
      <div className="min-w-0">
        <EnTeteCourse vb={vb} />
        <div className="mt-1 flex min-w-0 items-center gap-2 text-sm font-medium text-stone-900">
          <IdentiteCheval numero={vb.numero} nom={titleCase(vb.nom_cheval)} courseId={vb.course_id} imgUrl={vb.casaque_image_url} />
          {isExpert && vb.spi_detected && <Zap className="h-3.5 w-3.5 shrink-0 text-amber-700" aria-label="Afflux d'argent" />}
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[11px] text-stone-500">
          <Niveau n={vb.niveau} />
          {vb.jockey && <span className="min-w-0 break-words">{titleCase(vb.jockey)}</span>}
        </div>
      </div>
      <div className="hidden text-right sm:block">
        <div className="text-[10px] text-stone-500">Chance</div>
        <div className="text-sm font-semibold tabular-nums text-stone-900">{pct(vb.proba_top1)}</div>
      </div>
      <div className="hidden text-right sm:block">
        <div className="text-[10px] text-stone-500">Cote / juste</div>
        <div className="text-sm tabular-nums text-stone-900">{cote(vb.cote_pmu)} <span className="text-stone-400">/ {cote(vb.cote_juste)}</span></div>
      </div>
      <div className="hidden text-right sm:block">
        <div className="text-[10px] text-stone-500">Meilleure</div>
        <div className="text-sm tabular-nums text-stone-900">{cote(vb.cote_max)} <span className="text-[10px] text-stone-400">{vb.cote_max_source ? OPERATEUR[vb.cote_max_source] ?? "" : ""}</span></div>
      </div>
      <div className="hidden text-right text-xs sm:block">
        <div className="text-[10px] text-stone-500">Mouvement</div>
        <Mouvement m={vb.mouvement_cote_pct} />
      </div>
      <div className="text-right">
        <div className={cn("font-display text-lg font-medium tabular-nums", ev > 0 ? "text-emerald-700" : "text-rose-700")}>{ev > 0 ? "+" : ""}{ev}&nbsp;%</div>
        <div className="text-[10px] text-stone-400 sm:hidden">{pct(vb.proba_top1)} · cote {cote(vb.cote_pmu)}</div>
      </div>
    </Link>
  );
}

// ─── Pari le plus fort, en relief ──────────────────────────────
function PariVedette({ vb }: { vb: VB }) {
  const ev = Math.round(vb.ev_max * 100);
  return (
    <Link href={`/courses/${vb.course_id}`} className="group block" aria-label={`Plus forte espérance : ${vb.nom_cheval}`}>
      <div className="esp-panneau relative overflow-hidden rounded-[1.4rem]">
        <div className="h-1 bg-gradient-to-r from-amber-700 via-amber-500 to-amber-300" aria-hidden="true" />
        <div className="p-5 sm:p-7">
          <div className="flex items-center justify-between gap-3">
            <span className="text-[11px] font-medium uppercase tracking-[0.2em] text-amber-800">Plus forte espérance</span>
            <Niveau n={vb.niveau} avecLibelle />
          </div>
          <div className="mt-2"><EnTeteCourse vb={vb} /></div>
          <div className="mt-5 flex items-end justify-between gap-4">
            <div className="min-w-0">
              <div className="text-lg font-semibold text-stone-900">
                <IdentiteCheval numero={vb.numero} nom={titleCase(vb.nom_cheval)} courseId={vb.course_id} imgUrl={vb.casaque_image_url} />
              </div>
              <div className="mt-1"><DetailCourse vb={vb} /></div>
            </div>
            <div className="shrink-0 text-right">
              <div className="font-display text-4xl font-medium tabular-nums text-emerald-700">+{ev}<span className="text-xl"> %</span></div>
              <div className="text-[10px] uppercase tracking-wider text-stone-400">Espérance</div>
            </div>
          </div>
          <div className="mt-5"><Ecart vb={vb} /></div>
          <dl className="mt-5 grid grid-cols-3 gap-2 border-t border-stone-100 pt-4 text-center">
            <div><dt className="text-[10px] text-stone-500">Cote PMU</dt><dd className="font-display text-lg font-medium tabular-nums">{cote(vb.cote_pmu)}</dd></div>
            <div><dt className="text-[10px] text-stone-500">Cote juste</dt><dd className="font-display text-lg font-medium tabular-nums">{cote(vb.cote_juste)}</dd></div>
            <div><dt className="text-[10px] text-stone-500">Accord modèles</dt><dd className="font-display text-lg font-medium tabular-nums">{vb.confiance != null ? `${nf(vb.confiance)} %` : "—"}</dd></div>
          </dl>
        </div>
      </div>
    </Link>
  );
}

// ─── Page ───────────────────────────────────────────────────────
export default function ValueBetsPage() {
  const { user } = useAuth();
  // ★ n'est plus servi par le serveur (−18 % mesuré sur 60 jours) : le filtre
  // démarre à ★★ et ne propose plus le niveau 1.
  const [niveauMin, setNiveauMin] = useState(2);
  const [discipline, setDiscipline] = useState<string | null>(null);
  const [tri, setTri] = useState<Tri>("ev");
  const [vue, setVue] = useState<"grille" | "liste">("grille");
  const [lastSync, setLastSync] = useState<Date | null>(null);

  const isPro = !!user && !["free", "decouverte"].includes(user.plan ?? "free");
  const isExpert = user?.plan === "expert";

  const { valueBets: flux, connected } = useValueBetsStream(isPro);
  const streamBets = flux.length > 0 ? (flux as VB[]) : AUCUN;
  const { data: apiBets, isLoading } = useSWR(
    isPro ? ["/value-bets", niveauMin] : null,
    () => predictionsApi.valueBets(niveauMin, 100).then((r) => r.data),
    { refreshInterval: 60_000 },
  );

  // Le flux WS ne connaît pas le filtre de niveau : il remplace la liste REST dès
  // qu'il a parlé. Même filtre appliqué ici, quelle que soit la source.
  const tous = useMemo(
    () => (streamBets.length > 0 ? streamBets : ((apiBets ?? AUCUN) as VB[])).filter((v) => (v.niveau ?? 0) >= niveauMin),
    [streamBets, apiBets, niveauMin],
  );

  useEffect(() => {
    if (streamBets.length > 0 || apiBets) setLastSync(new Date());
  }, [apiBets, streamBets]);

  // Disciplines réellement présentes (valeurs de l'API : PLAT, ATTELE, MONTE…).
  const disciplines = useMemo(() => {
    const m = new Map<string, number>();
    for (const v of tous) if (v.discipline) m.set(v.discipline.toUpperCase(), (m.get(v.discipline.toUpperCase()) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [tous]);

  const paris = useMemo(() => {
    const r = discipline ? tous.filter((v) => v.discipline?.toUpperCase() === discipline) : [...tous];
    const t = (d: string) => new Date(d).getTime();
    switch (tri) {
      case "ev": r.sort((a, b) => b.ev_max - a.ev_max); break;
      case "proba": r.sort((a, b) => (b.proba_top1 ?? 0) - (a.proba_top1 ?? 0)); break;
      case "heure": r.sort((a, b) => t(a.date_heure) - t(b.date_heure)); break;
      case "cote": r.sort((a, b) => (b.cote_pmu ?? 0) - (a.cote_pmu ?? 0)); break;
      case "niveau": r.sort((a, b) => b.niveau - a.niveau || b.ev_max - a.ev_max); break;
    }
    return r;
  }, [tous, discipline, tri]);

  const vedette = useMemo(() => [...tous].sort((a, b) => b.ev_max - a.ev_max)[0], [tous]);
  const nbFort = tous.filter((v) => v.niveau >= 3).length;
  const evMoy = tous.length ? tous.reduce((s, v) => s + v.ev_max, 0) / tous.length : null;
  const nbCourses = new Set(tous.map((v) => v.course_id)).size;
  const prochain = [...tous].filter((v) => new Date(v.date_heure).getTime() > Date.now()).sort((a, b) => a.date_heure.localeCompare(b.date_heure))[0];

  // ── Visiteur non connecté / compte gratuit ──
  if (!user || !isPro) {
    return (
      <div className="min-h-screen bg-background">
        <div className="mx-auto max-w-3xl px-4 py-16 sm:py-24">
          <Reveal>
            <div className="esp-panneau rounded-3xl p-8 text-center sm:p-12">
              <Lock className="mx-auto h-6 w-6 text-stone-700" aria-hidden="true" />
              <span className="mt-5 flex items-center justify-center gap-2 text-[11px] font-medium uppercase tracking-[0.2em] text-stone-500">
                <span className="h-px w-6 bg-amber-600/70" aria-hidden="true" /> {RUBRIQUES.parisDeValeur.label}
              </span>
              <h1 className="mt-3 font-display text-3xl font-medium tracking-tight text-stone-900 sm:text-4xl">Les chevaux mieux cotés que leur chance réelle</h1>
              <p className="mx-auto mt-4 max-w-lg text-[15px] leading-relaxed text-stone-600">
                Chaque pari affiche la chance calculée du cheval, celle que suppose sa cote, la cote juste et la meilleure cote du marché. Inclus dès l&apos;abonnement Standard.
              </p>
              <div className="mt-8 flex flex-wrap justify-center gap-3">
                {!user ? (
                  <>
                    <Button asChild size="lg" className="press h-12 rounded-xl bg-stone-900 px-6 font-medium text-white hover:bg-stone-800">
                      <Link href="/inscription?plan=standard&suite=%2Fvalue-bets">Créer mon compte gratuit</Link>
                    </Button>
                    <Button asChild size="lg" variant="outline" className="press h-12 rounded-xl border-stone-300 bg-white px-6 font-medium text-stone-900">
                      <Link href="/login?redirect=/value-bets">Se connecter</Link>
                    </Button>
                  </>
                ) : (
                  <Button asChild size="lg" className="press h-12 rounded-xl bg-stone-900 px-6 font-medium text-white hover:bg-stone-800">
                    <Link href={RUBRIQUES.tarifs.href}>Voir les abonnements</Link>
                  </Button>
                )}
              </div>
            </div>
          </Reveal>
        </div>
      </div>
    );
  }

  const puce = (actif: boolean) => cn(
    "rounded-full border px-3 py-1.5 text-xs transition-colors",
    actif ? "border-stone-900 bg-stone-900 text-white" : "border-stone-200 bg-white text-stone-600 hover:border-stone-400 hover:text-stone-900",
  );

  return (
    <div className="min-h-screen bg-background">
      {/* ══ En-tête ═════════════════════════════════════════════════ */}
      <header className="relative isolate overflow-hidden border-b border-stone-200/70 bg-gradient-to-b from-[#FBF8F2] to-background">
        <div className="pointer-events-none absolute -right-40 -top-40 -z-10 h-[32rem] w-[32rem] rounded-full bg-amber-100/60 blur-3xl" aria-hidden="true" />
        <div className="mx-auto max-w-7xl px-4 pb-10 pt-8 sm:px-6 sm:pb-14 sm:pt-14 lg:px-8">
          <div className="grid items-center gap-10 lg:grid-cols-[minmax(0,6fr)_minmax(0,5fr)] lg:gap-16">
            <Reveal>
              <div className="flex flex-wrap items-center gap-3 text-[11px] font-medium uppercase tracking-[0.2em] text-stone-500">
                <span className="flex items-center gap-2"><span className="h-px w-6 bg-amber-600/70" aria-hidden="true" />{RUBRIQUES.parisDeValeur.label}</span>
                {connected ? (
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 px-2 py-0.5 text-[10px] tracking-[0.14em] text-emerald-700">
                    <span className="live-dot h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden="true" /> En direct
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-stone-300 px-2 py-0.5 text-[10px] tracking-[0.14em] text-stone-600">
                    <RefreshCw className="h-3 w-3" aria-hidden="true" /> Toutes les 60 s
                  </span>
                )}
              </div>
              <h1 className="mt-5 font-display text-[2.2rem] font-medium leading-[1.05] tracking-tight text-stone-900 sm:text-[3.4rem]">
                Paris de valeur du jour
              </h1>
              <p className="mt-4 max-w-lg text-[15px] leading-relaxed text-stone-600">
                Les chevaux dont la chance calculée dépasse ce que dit leur cote, course par course.
                {lastSync && <span className="text-stone-500"> Actualisé à {lastSync.toLocaleTimeString("fr-FR", { timeZone: "Europe/Paris", hour: "2-digit", minute: "2-digit" })}.</span>}
              </p>
            </Reveal>
            <Reveal delay={120}>
              {vedette ? (
                <Plan3D className="mx-auto w-full max-w-md lg:max-w-none"><PariVedette vb={vedette} /></Plan3D>
              ) : (
                <div className="esp-panneau rounded-[1.4rem] p-7 text-sm text-stone-500">
                  {isLoading ? "Chargement des paris…" : "Aucun pari de valeur pour le moment. Ils apparaissent dès qu'une cote dépasse la chance réelle d'un cheval."}
                </div>
              )}
            </Reveal>
          </div>

          <Reveal delay={200}>
            <div className="esp-panneau mt-12 grid grid-cols-2 overflow-hidden rounded-2xl lg:grid-cols-4 [&>*]:border-stone-100 [&>*:nth-child(odd)]:border-r [&>*:nth-child(-n+2)]:border-b lg:[&>*:nth-child(-n+2)]:border-b-0 lg:[&>*:nth-child(-n+3)]:border-r">
              {[
                { l: "Paris actifs", v: <Compteur valeur={tous.length} />, n: `sur ${nbCourses} course${nbCourses > 1 ? "s" : ""}` },
                { l: "Niveau 3 et plus", v: <Compteur valeur={nbFort} />, n: "fort signal ou exceptionnel" },
                { l: "Espérance moyenne", v: evMoy != null ? <Compteur valeur={evMoy * 100} decimales={1} suffixe={" %"} signe className="text-emerald-800" /> : "—", n: "gain moyen attendu par euro misé" },
                { l: "Prochain départ", v: prochain ? heureParis(prochain.date_heure) : "—", n: prochain ? `${prochain.code ?? ""} ${titleCase(prochain.hippodrome_nom)}`.trim() : null },
              ].map((k) => (
                <div key={k.l} className="px-4 py-4 sm:px-6 sm:py-5">
                  <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-stone-500">{k.l}</div>
                  <div className="mt-2 whitespace-nowrap font-display text-2xl font-medium tracking-tight text-stone-900 sm:text-[1.9rem]">{k.v}</div>
                  <div className="mt-1 min-h-[1rem] break-words text-xs text-stone-500">{k.n}</div>
                </div>
              ))}
            </div>
          </Reveal>
        </div>
      </header>

      <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 sm:py-16 lg:px-8">
        <SectionTitre
          sur={`${paris.length} pari${paris.length > 1 ? "s" : ""}`}
          titre="Toute la sélection"
          aside={
            <div className="flex rounded-lg border border-stone-200 bg-white p-0.5">
              {([["grille", LayoutGrid, "Vue en grille"], ["liste", List, "Vue en liste"]] as const).map(([v, Icone, l]) => (
                <button key={v} onClick={() => setVue(v)} aria-label={l} aria-pressed={vue === v}
                  className={cn("rounded-md p-1.5 transition-colors", vue === v ? "bg-stone-900 text-white" : "text-stone-500 hover:text-stone-900")}>
                  <Icone className="h-4 w-4" aria-hidden="true" />
                </button>
              ))}
            </div>
          }
        />

        {/* Filtres, toujours visibles */}
        <div className="mb-6 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-[11px] font-medium uppercase tracking-[0.14em] text-stone-500">Niveau</span>
            {[2, 3, 4].map((n) => (
              <button key={n} onClick={() => setNiveauMin(n)} aria-pressed={niveauMin === n} className={cn(puce(niveauMin === n), "inline-flex items-center gap-1.5")}>
                <Etoiles n={n} taille="h-3 w-3" vides={false} />{n < 4 && <span>et +</span>}
              </button>
            ))}
            <span className="mx-2 hidden h-5 w-px bg-stone-200 sm:block" aria-hidden="true" />
            <button onClick={() => setDiscipline(null)} aria-pressed={!discipline} className={puce(!discipline)}>
              Toutes <span className="opacity-60">{tous.length}</span>
            </button>
            {disciplines.map(([d, n]) => (
              <button key={d} onClick={() => setDiscipline(d)} aria-pressed={discipline === d} className={puce(discipline === d)}>
                {disciplineLabel(d)} <span className="opacity-60">{n}</span>
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <ArrowUpDown className="h-3.5 w-3.5 text-stone-400" aria-hidden="true" />
            <span className="mr-1 text-[11px] font-medium uppercase tracking-[0.14em] text-stone-500">Trier</span>
            {TRIS.map((t) => (
              <button key={t.v} onClick={() => setTri(t.v)} aria-pressed={tri === t.v} className={puce(tri === t.v)}>{t.l}</button>
            ))}
          </div>
        </div>

        {isLoading && tous.length === 0 ? (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3" aria-busy="true" aria-label="Chargement des paris de valeur">
            {Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-[26rem] animate-pulse rounded-2xl bg-white ring-1 ring-stone-200" />)}
          </div>
        ) : paris.length === 0 ? (
          <div className="rounded-3xl border border-dashed border-stone-200 px-6 py-14 text-center">
            <p className="text-sm font-medium text-stone-700">
              Aucun pari de valeur{discipline ? ` en ${disciplineLabel(discipline).toLowerCase()}` : ""} pour le moment.
            </p>
            <p className="mt-1 text-xs text-stone-500">Une sélection apparaît dès qu&apos;une cote dépasse la chance réelle d&apos;un cheval.</p>
            {(discipline || niveauMin > 2) && (
              <button onClick={() => { setDiscipline(null); setNiveauMin(2); }} className="mx-auto mt-4 inline-flex items-center gap-1 text-xs font-medium text-stone-700 hover:text-stone-900">
                <X className="h-3 w-3" aria-hidden="true" /> Réinitialiser les filtres
              </button>
            )}
          </div>
        ) : vue === "grille" ? (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {paris.map((vb, i) => (
              <Reveal key={vb.vb_id} delay={Math.min(i, 8) * 60} className="h-full">
                <CarteVB vb={vb} isExpert={isExpert} />
              </Reveal>
            ))}
          </div>
        ) : (
          <Reveal>
            <div className="esp-panneau divide-y divide-stone-100 overflow-hidden rounded-3xl">
              {paris.map((vb) => <LigneVB key={vb.vb_id} vb={vb} isExpert={isExpert} />)}
            </div>
          </Reveal>
        )}

        <p className="mx-auto mt-12 max-w-2xl text-center text-xs leading-relaxed text-stone-500">
          <span className="font-medium text-stone-700">Espérance = cote × chance calculée − 1.</span>{" "}
          Une espérance positive se vérifie sur la durée, jamais sur un pari isolé. La cote juste est
          la cote qui correspondrait exactement à la chance calculée. Pariez de façon responsable.
        </p>
      </div>
    </div>
  );
}
