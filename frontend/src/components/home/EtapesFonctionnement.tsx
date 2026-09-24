"use client";

/**
 * « Comment ça marche » (accueil) : trois étapes, chacune avec un petit écran
 * qui montre le geste — le classement d'une course, la répartition d'un
 * budget, le règlement d'un pari.
 *
 * Les écrans sont des ILLUSTRATIONS : chiffres d'exemple, marqués comme tels,
 * jamais une course réelle. Même règle que le palmarès : l'état servi est
 * l'état final ; les barres ne se remplissent à l'écran que si le bloc était
 * encore sous la ligne de flottaison quand le script a démarré.
 */

import Link from "next/link";
import { ArrowRight, Check, ChevronRight, Coins, ListOrdered, Receipt } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Tilt, useReveal } from "@/components/track-record/effets";

// ─── Écran commun ───────────────────────────────────────────────
function Ecran({ titre, badge, children }: { titre: string; badge: ReactNode; children: ReactNode }) {
  return (
    <div className="relative isolate flex flex-col overflow-hidden rounded-2xl bg-slate-950 p-3.5 text-white md:min-h-[12.5rem] ring-1 ring-slate-900 shadow-[inset_0_1px_0_rgba(255,255,255,.08),0_18px_36px_-22px_rgba(15,23,42,.8)]">
      <div
        className="pointer-events-none absolute inset-0 -z-10 opacity-70"
        style={{
          backgroundImage: "linear-gradient(rgba(255,255,255,.04) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.04) 1px, transparent 1px)",
          backgroundSize: "18px 18px",
        }}
        aria-hidden="true"
      />
      <span className="etape-scan pointer-events-none absolute inset-x-0 -z-10 h-16" aria-hidden="true" />
      <div className="mb-3 flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-rose-400/70" />
          <span className="h-1.5 w-1.5 rounded-full bg-amber-300/70" />
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-400/70" />
          <span className="ml-1.5 font-mono text-[9px] uppercase tracking-[0.14em] text-white/55">{titre}</span>
        </span>
        {badge}
      </div>
      {/* Même hauteur pour les trois écrans : les titres dessous restent alignés. */}
      <div className="flex flex-1 flex-col justify-between">{children}</div>
    </div>
  );
}

const Exemple = () => (
  <span className="rounded bg-white/5 px-1.5 py-0.5 font-mono text-[8px] uppercase tracking-[0.14em] text-white/40 ring-1 ring-white/10">exemple</span>
);

// ─── 01 · Le classement d'une course ────────────────────────────
function EcranClassement({ hidden }: { hidden: boolean }) {
  const lignes = [
    { n: 7, p: 34, c: "from-amber-300 to-amber-500" },
    { n: 3, p: 21, c: "from-amber-200/90 to-amber-400/90" },
    { n: 11, p: 14, c: "from-amber-100/80 to-amber-300/80" },
    { n: 5, p: 9, c: "from-white/40 to-white/25" },
  ];
  return (
    <Ecran titre="R1 · C4 · classement" badge={<Exemple />}>
      <div className="space-y-2">
        {lignes.map((l, i) => (
          <div key={l.n} className="flex items-center gap-2">
            <span className="w-3 font-mono text-[9px] text-white/40">{i + 1}</span>
            <span className={cn(
              "inline-flex h-5 w-6 items-center justify-center rounded font-mono text-[10px] font-bold",
              i === 0 ? "bg-amber-400 text-slate-950" : "bg-white/10 text-white/85",
            )}>{l.n}</span>
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[.06]">
              <div
                className={cn("tr-bar h-full rounded-full bg-gradient-to-r", l.c)}
                style={{ width: hidden ? 0 : `${(l.p / 40) * 100}%`, transitionDelay: `${i * 120}ms` }}
              />
            </div>
            <span className="w-8 text-right font-mono text-[10px] tabular-nums text-white/75">{l.p} %</span>
          </div>
        ))}
      </div>
      <div className="mt-3 flex items-center justify-between border-t border-white/10 pt-2.5 font-mono text-[9px] uppercase tracking-[0.12em] text-white/50">
        <span>Confiance</span>
        <span className="flex gap-1" aria-hidden="true">
          {[0, 1, 2, 3, 4].map((k) => (
            <span key={k} className={cn("h-1.5 w-3.5 rounded-sm", k < 4 ? "bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,.7)]" : "bg-white/10")} />
          ))}
        </span>
      </div>
    </Ecran>
  );
}

// ─── 02 · La répartition d'un budget ────────────────────────────
function EcranBudget({ hidden }: { hidden: boolean }) {
  const lignes = [
    { l: "Sécurité", m: 10, c: "bg-emerald-400", t: "text-emerald-300" },
    { l: "Rendement", m: 6, c: "bg-amber-400", t: "text-amber-300" },
    { l: "Coup", m: 4, c: "bg-rose-400", t: "text-rose-300" },
  ];
  return (
    <Ecran titre="Plan de mise" badge={<Exemple />}>
      <div className="flex items-center justify-between rounded-lg bg-white/[.05] px-2.5 py-1.5 ring-1 ring-amber-300/30">
        <span className="font-mono text-[9px] uppercase tracking-[0.12em] text-white/50">Budget</span>
        <span className="font-display text-base font-black tabular-nums text-white">
          20 €<span className="etape-caret ml-0.5 inline-block h-3.5 w-px translate-y-0.5 bg-amber-300" aria-hidden="true" />
        </span>
      </div>
      {/* Barre empilée : les trois lignes se partagent le budget. */}
      <div className="mt-3 flex h-2 gap-0.5 overflow-hidden rounded-full bg-white/[.06]" aria-hidden="true">
        {lignes.map((x, i) => (
          <span
            key={x.l}
            className={cn("tr-bar h-full first:rounded-l-full last:rounded-r-full", x.c)}
            style={{ width: hidden ? 0 : `${(x.m / 20) * 100}%`, transitionDelay: `${i * 160}ms` }}
          />
        ))}
      </div>
      <div className="mt-2.5 space-y-1.5">
        {lignes.map((x) => (
          <div key={x.l} className="flex items-center justify-between font-mono text-[10px]">
            <span className="inline-flex items-center gap-1.5 text-white/70">
              <span className={cn("h-1.5 w-1.5 rounded-full", x.c)} /> {x.l}
            </span>
            <span className={cn("tabular-nums font-bold", x.t)}>{x.m} €</span>
          </div>
        ))}
      </div>
    </Ecran>
  );
}

// ─── 03 · Le règlement au rapport officiel ──────────────────────
function EcranReglement({ hidden }: { hidden: boolean }) {
  return (
    <Ecran titre="Arrivée officielle" badge={<Exemple />}>
      <div className="flex items-center gap-1.5">
        {[7, 3, 11].map((n, i) => (
          <span key={n} className="inline-flex items-center gap-1 rounded-md bg-white/[.06] px-1.5 py-1 ring-1 ring-white/10">
            <span className="font-mono text-[8px] text-white/40">{i + 1}<sup>{i ? "e" : "er"}</sup></span>
            <span className="font-mono text-[11px] font-bold text-white">{n}</span>
          </span>
        ))}
      </div>
      <div className="mt-3 flex items-center justify-between rounded-lg bg-emerald-400/10 px-2.5 py-1.5 ring-1 ring-emerald-400/30">
        <span className="inline-flex items-center gap-1.5 font-mono text-[9px] uppercase tracking-[0.12em] text-emerald-200">
          <Check className="h-3 w-3" aria-hidden="true" /> Réglé au rapport PMU
        </span>
        <span className="font-mono text-[10px] font-bold tabular-nums text-emerald-300">+ 12,40 €</span>
      </div>
      {/* Courbe de capital : se trace quand le bloc entre à l'écran. */}
      <svg viewBox="0 0 200 44" className="mt-2.5 h-11 w-full" aria-hidden="true">
        <defs>
          <linearGradient id="etape-capital" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#34D399" stopOpacity=".35" />
            <stop offset="100%" stopColor="#34D399" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d="M0 34 L28 30 L52 36 L80 26 L108 28 L136 18 L164 20 L200 8 L200 44 L0 44 Z" fill="url(#etape-capital)"
          style={{ opacity: hidden ? 0 : 1, transition: "opacity .8s ease .6s" }} />
        <path d="M0 34 L28 30 L52 36 L80 26 L108 28 L136 18 L164 20 L200 8" fill="none" stroke="#34D399" strokeWidth="2"
          strokeLinecap="round" strokeLinejoin="round" pathLength={1} strokeDasharray="1"
          style={{ strokeDashoffset: hidden ? 1 : 0, transition: "stroke-dashoffset 1.4s cubic-bezier(0.16,1,0.3,1)" }} />
        <circle cx="200" cy="8" r="3" fill="#fff" style={{ opacity: hidden ? 0 : 1, transition: "opacity .4s ease 1.2s" }} />
      </svg>
    </Ecran>
  );
}

// ─── Carte d'étape ──────────────────────────────────────────────
const ETAPES = [
  {
    step: "01", icon: ListOrdered, titre: "Ouvrez la course",
    desc: "Tout le programme PMU du jour est déjà analysé : classement des partants, probabilité de chacun, score de confiance de la course.",
    Ecran: EcranClassement,
  },
  {
    step: "02", icon: Coins, titre: "Donnez votre budget",
    desc: "Vous entrez un montant, nous répartissons : une ligne sécurité, une ligne rendement, une ligne coup — selon votre profil de risque.",
    Ecran: EcranBudget,
  },
  {
    step: "03", icon: Receipt, titre: "Pariez où vous voulez",
    desc: "Vous jouez chez votre opérateur. À l'arrivée, chaque pari est réglé au rapport officiel et votre capital est mis à jour.",
    Ecran: EcranReglement,
  },
] as const;

function CarteEtape({ e, index }: { e: (typeof ETAPES)[number]; index: number }) {
  const { ref, hidden } = useReveal<HTMLDivElement>(0.3);
  const Icone = e.icon;
  return (
    <div
      ref={ref}
      className={cn("tr-reveal relative h-full", hidden && "tr-armed")}
      style={{ "--tr-delay": `${index * 110}ms` } as CSSProperties}
    >
      <Tilt max={6} className="group h-full overflow-hidden rounded-3xl bg-white p-3 ring-1 ring-stone-200/80 shadow-[0_30px_60px_-40px_rgba(17,24,39,.45)] transition-shadow hover:ring-amber-300/60">
        <div className="tr-pop">
          <e.Ecran hidden={hidden} />
        </div>
        <div className="relative px-3 pb-3 pt-5">
          {/* Numéro en filigrane, en contour doré. */}
          <span
            className="pointer-events-none absolute right-3 top-2 select-none font-display text-6xl font-black leading-none text-transparent"
            style={{ WebkitTextStroke: "1.5px rgba(217,119,6,.28)" }}
            aria-hidden="true"
          >
            {e.step}
          </span>
          <span className="inline-flex items-center gap-2 rounded-full bg-amber-50 px-2.5 py-1 font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-amber-800 ring-1 ring-amber-200">
            <Icone className="h-3.5 w-3.5" aria-hidden="true" /> Étape {e.step}
          </span>
          <h3 className="mt-3 font-display text-lg font-bold text-gray-900">{e.titre}</h3>
          <p className="mt-1.5 text-sm leading-relaxed text-gray-600">{e.desc}</p>
        </div>
      </Tilt>

      {/* Liaison vers l'étape suivante (bureau uniquement). */}
      {index < ETAPES.length - 1 && (
        <span
          className="absolute -right-[22px] top-[5.5rem] z-20 hidden h-9 w-9 items-center justify-center rounded-full bg-white text-amber-600 ring-1 ring-amber-200 shadow-[0_8px_20px_-8px_rgba(180,83,9,.5)] md:inline-flex"
          aria-hidden="true"
        >
          <ChevronRight className="etape-fleche h-4 w-4" />
        </span>
      )}
    </div>
  );
}

export function EtapesFonctionnement() {
  return (
    <>
      <div className="relative">
        {/* Rail qui relie les trois écrans, avec une impulsion qui le parcourt. */}
        <div className="pointer-events-none absolute left-[8%] right-[8%] top-[6.6rem] hidden h-px bg-gradient-to-r from-amber-200/0 via-amber-300/70 to-amber-200/0 md:block" aria-hidden="true">
          <span className="etape-impulsion absolute -top-[3px] h-[7px] w-16 rounded-full bg-gradient-to-r from-transparent via-amber-400 to-transparent blur-[1px]" />
        </div>
        <ol className="relative grid gap-5 md:grid-cols-3 md:gap-8">
          {ETAPES.map((e, i) => (
            <li key={e.step}><CarteEtape e={e} index={i} /></li>
          ))}
        </ol>
      </div>

      {/* La page pilier de la méthode n'était atteignable que depuis le pied de page :
          un lien de bas de site ne dit à personne, moteur compris, qu'elle porte le
          sujet principal du site. Elle est citée ici, là où la question se pose. */}
      <Link
        href="/pronostics-ia"
        className="group mx-auto mt-10 flex max-w-3xl flex-col items-start gap-3 rounded-2xl bg-slate-950 p-4 text-left ring-1 ring-slate-900 transition hover:ring-amber-400/50 sm:flex-row sm:items-center sm:gap-4 sm:p-5"
      >
        <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-amber-300 to-amber-600 text-slate-950 shadow-[inset_0_1px_0_rgba(255,255,255,.4)]">
          <ListOrdered className="h-5 w-5" aria-hidden="true" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block font-display text-sm font-bold text-white sm:text-base">
            Comment l&apos;IA calcule une probabilité par cheval
          </span>
          <span className="mt-0.5 block text-xs leading-relaxed text-white/60 sm:text-sm">
            Les données sur lesquelles le modèle apprend, son réentraînement quotidien, et la
            façon dont sa justesse est vérifiée.
          </span>
        </span>
        <ArrowRight className="h-5 w-5 shrink-0 text-amber-300 transition-transform group-hover:translate-x-1" aria-hidden="true" />
      </Link>
    </>
  );
}
