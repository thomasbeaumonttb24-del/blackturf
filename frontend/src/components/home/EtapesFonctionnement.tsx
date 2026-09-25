"use client";

/**
 * « Comment ça marche » (accueil) : trois étapes, chacune montrée avec le VRAI
 * composant du site, posé sur un plan en relief qui se redresse au défilement.
 *
 *  1. le classement d'une course  → `ClassementAlgo` (table des abonnés) ;
 *  2. le plan de mise              → `PlanMiseDisplay` (page course) ;
 *  3. le règlement                 → `BetTicket` (palmarès), alimenté par les
 *     derniers paris réellement réglés. Sans palmarès, un ticket d'exemple.
 *
 * Les étapes 1 et 2 tournent sur une course d'EXEMPLE, marquée comme telle :
 * aucun cheval réel, aucune cote réelle. L'état servi est l'état FINAL (plan à
 * plat, tout visible) : l'inclinaison n'est jouée que si le script tourne et que
 * l'utilisateur n'a pas demandé à réduire les animations.
 */

import Link from "next/link";
import useSWR from "swr";
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { ArrowRight, CheckCircle2, LockKeyhole, Sparkles } from "lucide-react";
import { statsApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ClassementAlgo, type ClassementPrediction, type ClassementSignal } from "@/components/courses/classement";
import { PlanMiseDisplay, type MisePlan } from "@/components/courses/plan-mise";
import { BetTicket, type WinningBet } from "@/components/track-record/BetsShowcase";

// ─── Course d'exemple ───────────────────────────────────────────
const pred = (numero: number, nom: string, rang: number, p1: number, p3: number, cote: number, conf: number): ClassementPrediction => ({
  prediction_id: `exemple-${numero}`, numero, nom_cheval: nom, rang_predit: rang,
  proba_top1: p1, proba_top3: p3, proba_top1_low: null, proba_top1_high: null,
  confidence_score: conf, cote_pmu: cote, cote_juste: Math.round((1 / p1) * 100) / 100, value_bet: null,
});

const EXEMPLE_CLASSEMENT: ClassementPrediction[] = [
  pred(7, "Horizon Doré", 1, 0.34, 0.71, 3.8, 0.78),
  pred(3, "Belle de Mai", 2, 0.21, 0.55, 4.6, 0.7),
  pred(11, "Quartz du Val", 3, 0.14, 0.41, 9.5, 0.62),
  pred(5, "Nuit Blanche", 4, 0.09, 0.3, 8.2, 0.55),
  pred(1, "Cap Ferret", 5, 0.07, 0.24, 14, 0.5),
];

const sig = (label: string, detail: string, sens: ClassementSignal["sens"]): ClassementSignal => ({ label, detail, sens, score: 1 });
const EXEMPLE_SIGNAUX: Record<number, ClassementSignal[]> = {
  7: [sig("Forme récente", "3 podiums sur ses 4 dernières sorties", "positif"), sig("Terrain favorable", "Déjà gagnant sur terrain souple", "positif")],
  3: [sig("Jockey en forme", "22 % de réussite sur 30 jours", "positif")],
  11: [sig("Retour de repos", "Pas couru depuis 70 jours", "negatif")],
};

const pari = (type: string, nums: number[], mise: number, gain: number, probabilite: number) => ({
  type, mise, gain_potentiel: gain, probabilite, description: "",
  chevaux: nums.map((numero) => ({ numero, nom: "" })),
});

const EXEMPLE_PLAN: MisePlan = {
  montant_total: 20, montant_joue: 20, montant_reserve: 0, ev_global: 0, kelly_warning: false,
  profil: "equilibre",
  resume_ia: "Le n°7 domine le classement : il porte la ligne sécurité. Le n°3 et le n°11 complètent les combinaisons.",
  avertissement: "Exemple illustratif — sur une vraie course, le plan est calculé sur les cotes du moment.",
  niveaux: [
    { niveau: "securite", label: "Sécurité", emoji: "", couleur: "", montant: 10, pct: 50, paris: [pari("Simple Placé", [7], 10, 18, 0.71)] },
    { niveau: "rendement", label: "Rendement", emoji: "", couleur: "", montant: 6, pct: 30, paris: [pari("Couplé Placé", [7, 3], 6, 33, 0.29)] },
    { niveau: "coup", label: "Coup à tenter", emoji: "", couleur: "", montant: 4, pct: 20, paris: [pari("Trio", [7, 3, 11], 4, 92, 0.06)] },
  ],
};

const EXEMPLE_TICKETS: WinningBet[] = [
  { profil: "equilibre", course_id: "", code: "R1 · C4", hippodrome: "Course d'exemple", date: "2026-09-20T13:50:00Z", type_pari: "Couplé Placé", chevaux: [7, 3], mise: 6, gain: 33.6, benefice: 27.6, rapport: 5.6, fige_avant_course: true },
  { profil: "conservateur", course_id: "", code: "R1 · C4", hippodrome: "Course d'exemple", date: "2026-09-20T13:50:00Z", type_pari: "Simple Placé", chevaux: [7], mise: 10, gain: 18, benefice: 8, rapport: 1.8, fige_avant_course: true },
];

const rien = () => {};

// ─── Scène en relief ────────────────────────────────────────────
function mouvementReduit() {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * Le plan part incliné et se redresse à mesure que la scène monte dans l'écran
 * (`--p` de 0 à 1), puis suit légèrement le pointeur. Tout passe par des
 * variables CSS : aucun rendu React pendant le défilement.
 */
function Scene({ children, sens, halo, puces, label }: {
  children: ReactNode;
  sens: 1 | -1;
  halo: string;
  puces?: ReactNode;
  label: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || mouvementReduit()) return;
    let raf = 0;
    const maj = () => {
      raf = 0;
      const r = el.getBoundingClientRect();
      const vh = window.innerHeight;
      const p = Math.max(0, Math.min(1, (vh - r.top) / (vh * 0.8)));
      el.style.setProperty("--p", p.toFixed(3));
    };
    const demande = () => { if (!raf) raf = requestAnimationFrame(maj); };
    maj();
    window.addEventListener("scroll", demande, { passive: true });
    window.addEventListener("resize", demande);
    return () => {
      window.removeEventListener("scroll", demande);
      window.removeEventListener("resize", demande);
      cancelAnimationFrame(raf);
    };
  }, []);

  const onMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.pointerType !== "mouse" || mouvementReduit()) return;
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    el.style.setProperty("--px", (((e.clientX - r.left) / r.width - 0.5) * 2).toFixed(3));
    el.style.setProperty("--py", (((e.clientY - r.top) / r.height - 0.5) * 2).toFixed(3));
  };
  const onLeave = () => {
    ref.current?.style.setProperty("--px", "0");
    ref.current?.style.setProperty("--py", "0");
  };

  return (
    <div
      ref={ref}
      onPointerMove={onMove}
      onPointerLeave={onLeave}
      className="scene3d relative"
      style={{ "--sens": sens } as CSSProperties}
      role="img"
      aria-label={label}
    >
      {/* Ambiance : une lueur douce derrière l'écran, et son ombre portée au sol. */}
      <div className={cn("scene3d-halo pointer-events-none absolute -inset-10 -z-10 rounded-full blur-3xl", halo)} aria-hidden="true" />
      <div className="scene3d-plan">
        <div className="relative overflow-hidden rounded-[1.4rem] bg-white shadow-[0_2px_0_rgba(255,255,255,.9)_inset,0_50px_90px_-40px_rgba(28,25,23,.45),0_18px_36px_-24px_rgba(28,25,23,.25)] ring-1 ring-stone-200/80">
          <div inert className="pointer-events-none select-none">{children}</div>
          <div className="scene3d-reflet pointer-events-none absolute inset-0" aria-hidden="true" />
        </div>
        {puces}
      </div>
      <div className="scene3d-sol pointer-events-none absolute inset-x-[12%] -bottom-8 -z-10 h-10 rounded-[100%] bg-stone-900/20 blur-2xl" aria-hidden="true" />
    </div>
  );
}

/** Pastille qui flotte au-dessus du plan (profondeur `z`, en px). */
function Puce({ children, className, z = 70, delai = 0 }: { children: ReactNode; className?: string; z?: number; delai?: number }) {
  return (
    <div
      className={cn("scene3d-puce absolute z-10 hidden sm:block", className)}
      style={{ "--z": `${z}px`, animationDelay: `${delai}ms` } as CSSProperties}
      aria-hidden="true"
    >
      <div className="flex items-center gap-2 rounded-2xl bg-white/90 px-3.5 py-2.5 text-sm text-stone-700 shadow-[0_24px_48px_-20px_rgba(28,25,23,.45)] ring-1 ring-stone-200/80 backdrop-blur">
        {children}
      </div>
    </div>
  );
}

/** Coupe les longs composants en « écran » avec un fondu en bas. */
function Fenetre({ children, hauteur }: { children: ReactNode; hauteur: string }) {
  return (
    <div className="relative overflow-hidden" style={{ maxHeight: hauteur }}>
      {children}
      <div className="absolute inset-x-0 bottom-0 h-24 bg-gradient-to-t from-white to-transparent" />
    </div>
  );
}

/**
 * Rend un composant à sa largeur de bureau (`largeur`) puis le réduit pour
 * tenir dans le cadre — comme une capture du vrai écran. Sous 640 px de
 * fenêtre, le composant garde sa mise en page mobile, sans réduction.
 */
function Echelle({ children, largeur, hauteur }: { children: ReactNode; largeur: number; hauteur: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [k, setK] = useState<number | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const maj = () => setK(window.innerWidth >= 640 ? Math.min(1, el.clientWidth / largeur) : null);
    maj();
    const ro = new ResizeObserver(maj);
    ro.observe(el);
    return () => ro.disconnect();
  }, [largeur]);
  return (
    <div ref={ref} className="relative overflow-hidden" style={{ height: k ? hauteur * k : undefined, maxHeight: k ? undefined : "34rem" }}>
      <div style={k ? { width: largeur, transform: `scale(${k})`, transformOrigin: "top left" } : undefined}>{children}</div>
      <div className="absolute inset-x-0 bottom-0 h-20 bg-gradient-to-t from-white to-transparent" />
    </div>
  );
}

// ─── Étapes ─────────────────────────────────────────────────────
function useDerniersTickets() {
  const { data } = useSWR<{ gagnants: WinningBet[] }>(
    "palmares-public",
    () => statsApi.palmaresPublic().then((r) => r.data),
    { revalidateOnFocus: false },
  );
  const reels = (data?.gagnants ?? []).slice(0, 2);
  return { tickets: reels.length ? reels : EXEMPLE_TICKETS, reels: reels.length > 0 };
}

function Etape({ n, titre, desc, points, inverse, children }: {
  n: number; titre: string; desc: string; points: string[]; inverse?: boolean; children: ReactNode;
}) {
  return (
    <li className={cn("grid items-center gap-12 lg:gap-20", inverse ? "lg:grid-cols-[minmax(0,6fr)_minmax(0,5fr)]" : "lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]")}>
      <div className={cn("max-w-md", inverse && "lg:order-2")}>
        <span className="inline-flex h-11 w-11 items-center justify-center rounded-full bg-stone-900 font-display text-base font-medium text-white shadow-[0_12px_24px_-12px_rgba(28,25,23,.6)]">
          {n}
        </span>
        <h3 className="mt-6 font-display text-2xl font-medium tracking-tight text-stone-900 sm:text-[2rem] sm:leading-tight">{titre}</h3>
        <p className="mt-4 text-base leading-relaxed text-stone-500">{desc}</p>
        <ul className="mt-6 space-y-2.5">
          {points.map((p) => (
            <li key={p} className="flex items-start gap-2.5 text-sm text-stone-600">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" aria-hidden="true" /> {p}
            </li>
          ))}
        </ul>
      </div>
      <div className={cn(inverse && "lg:order-1")}>{children}</div>
    </li>
  );
}

export function EtapesFonctionnement() {
  const { tickets, reels } = useDerniersTickets();

  return (
    <>
      <ol className="space-y-28 sm:space-y-36">
        <Etape
          n={1}
          titre="Ouvrez la course"
          desc="Tout le programme PMU du jour est déjà analysé. Chaque partant reçoit une probabilité de victoire et une cote juste, et les chevaux sont classés du plus probable au moins probable."
          points={["Probabilité de victoire et de podium", "Cote juste face à la cote du marché", "Signaux qui expliquent le classement"]}
        >
          <Scene
            sens={1}
            halo="bg-amber-200/50"
            label="Exemple du classement de l'algorithme sur une course fictive"
            puces={
              <>
                <Puce className="-left-10 -bottom-6" z={90}>
                  <span className="font-display text-lg font-medium text-stone-900">34 %</span> de chances pour le n°7
                </Puce>
                <Puce className="-right-6 -top-5" z={60} delai={900}>
                  <Sparkles className="h-4 w-4 text-amber-600" /> Recalculé à chaque mouvement de cote
                </Puce>
              </>
            }
          >
            <Echelle largeur={860} hauteur={720}>
              <ClassementAlgo predictions={EXEMPLE_CLASSEMENT} signauxParNumero={EXEMPLE_SIGNAUX} onLegende={rien} />
            </Echelle>
          </Scene>
        </Etape>

        <Etape
          n={2}
          inverse
          titre="Donnez votre budget"
          desc="Vous entrez un montant et choisissez votre profil. Le moteur répartit la mise sur trois lignes, sécurité, rendement et coup à tenter, en ne gardant que les paris au bon prix."
          points={["Trois profils : prudent, modéré, risqué", "Mise et gain possible pour chaque ticket", "Les paris écartés, avec la raison"]}
        >
          <Scene
            sens={-1}
            halo="bg-emerald-200/50"
            label="Exemple d'un plan de mise de 20 euros sur une course fictive"
            puces={
              <Puce className="-right-10 bottom-28" z={90}>
                <span className="font-display text-lg font-medium text-stone-900">20 €</span> répartis en 3 lignes
              </Puce>
            }
          >
            <Fenetre hauteur="31rem">
              <div className="mx-auto max-w-[27rem] p-4 sm:p-5">
                <PlanMiseDisplay
                  plan={EXEMPLE_PLAN}
                  profil="equilibre"
                  switching={false}
                  onChangeProfil={rien}
                  onClose={rien}
                />
              </div>
            </Fenetre>
          </Scene>
        </Etape>

        <Etape
          n={3}
          titre="Pariez où vous voulez"
          desc="Vous jouez chez votre opérateur habituel, et vous enregistrez vos paris au Défi du mois : réglés au rapport PMU officiel, ils vous rapportent des points et vous font grimper au classement."
          points={["Pronostic figé avant le départ", "Règlement au rapport officiel", "Classement du Défi du mois"]}
        >
          <Scene
            sens={1}
            halo="bg-sky-200/40"
            label={reels ? "Les derniers paris réellement réglés par BlackTurf" : "Exemple de paris réglés"}
            puces={
              <Puce className="-left-8 -top-5" z={80}>
                <LockKeyhole className="h-4 w-4 text-emerald-600" />
                {reels ? "Derniers paris réellement réglés" : "Exemple de règlement"}
              </Puce>
            }
          >
            <div className="space-y-3 bg-stone-50/70 p-4 sm:p-6">
              {tickets.map((b, i) => (
                <div key={`${b.course_id}-${b.type_pari}-${i}`} className="scene3d-ticket" style={{ "--i": i } as CSSProperties}>
                  <BetTicket b={b} />
                </div>
              ))}
            </div>
          </Scene>
        </Etape>
      </ol>

      {/* La page pilier de la méthode n'était atteignable que depuis le pied de page :
          un lien de bas de site ne dit à personne, moteur compris, qu'elle porte le
          sujet principal du site. Elle est citée ici, là où la question se pose. */}
      <Link
        href="/pronostics-ia"
        className="group mx-auto mt-28 flex max-w-3xl items-center gap-4 border-y border-stone-200 py-5 text-left transition-colors hover:border-stone-400"
      >
        <span className="min-w-0 flex-1">
          <span className="block font-display text-base font-medium text-stone-900">
            Comment l&apos;IA calcule une probabilité par cheval
          </span>
          <span className="mt-1 block text-sm leading-relaxed text-stone-500">
            Les données sur lesquelles le modèle apprend, son réentraînement quotidien, et la
            façon dont sa justesse est vérifiée.
          </span>
        </span>
        <ArrowRight className="h-5 w-5 shrink-0 text-stone-400 transition-transform group-hover:translate-x-1 group-hover:text-stone-900" aria-hidden="true" />
      </Link>
    </>
  );
}
