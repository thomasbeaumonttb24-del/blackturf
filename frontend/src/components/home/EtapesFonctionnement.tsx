"use client";

/**
 * « Comment ça marche » (accueil) : trois étapes, chacune avec une petite
 * illustration épurée — le classement d'une course, la répartition d'un
 * budget, le règlement d'un pari.
 *
 * Les illustrations sont des EXEMPLES : chiffres fictifs, marqués comme tels,
 * jamais une course réelle. L'état servi est l'état final ; les barres ne se
 * remplissent à l'écran que si le bloc était encore sous la ligne de
 * flottaison quand le script a démarré.
 */

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";
import { cn } from "@/lib/utils";
import { useReveal } from "@/components/track-record/effets";

// ─── Illustration commune ───────────────────────────────────────
function Apercu({ titre, children }: { titre: string; children: ReactNode }) {
  return (
    <div className="flex flex-col rounded-2xl bg-stone-50 p-5 md:h-[13rem]">
      <div className="mb-4 flex items-center justify-between gap-2 text-xs text-stone-500">
        <span>{titre}</span>
        <span className="italic text-stone-400">exemple</span>
      </div>
      <div className="flex flex-1 flex-col justify-between">{children}</div>
    </div>
  );
}

// ─── 01 · Le classement d'une course ────────────────────────────
function ApercuClassement({ hidden }: { hidden: boolean }) {
  const lignes = [
    { n: 7, p: 34 },
    { n: 3, p: 21 },
    { n: 11, p: 14 },
    { n: 5, p: 9 },
  ];
  return (
    <Apercu titre="R1 · C4">
      <div className="space-y-3">
        {lignes.map((l, i) => (
          <div key={l.n} className="flex items-center gap-3 text-sm">
            <span className={cn("w-5 tabular-nums", i === 0 ? "font-medium text-stone-900" : "text-stone-500")}>{l.n}</span>
            <div className="h-1 flex-1 rounded-full bg-stone-200/70">
              <div
                className={cn("tr-bar h-full rounded-full", i === 0 ? "bg-amber-600" : "bg-stone-400")}
                style={{ width: hidden ? 0 : `${(l.p / 40) * 100}%`, transitionDelay: `${i * 100}ms` }}
              />
            </div>
            <span className="w-10 whitespace-nowrap text-right tabular-nums text-stone-500">{l.p} %</span>
          </div>
        ))}
      </div>
    </Apercu>
  );
}

// ─── 02 · La répartition d'un budget ────────────────────────────
function ApercuBudget() {
  const lignes = [
    { l: "Sécurité", m: 10 },
    { l: "Rendement", m: 6 },
    { l: "Coup", m: 4 },
  ];
  return (
    <Apercu titre="Plan de mise">
      <div className="flex items-baseline justify-between border-b border-stone-200 pb-3">
        <span className="text-sm text-stone-500">Budget</span>
        <span className="font-display text-2xl font-medium tabular-nums text-stone-900">20 €</span>
      </div>
      <div className="mt-3 space-y-2">
        {lignes.map((x) => (
          <div key={x.l} className="flex items-center justify-between text-sm">
            <span className="text-stone-600">{x.l}</span>
            <span className="tabular-nums text-stone-900">{x.m} €</span>
          </div>
        ))}
      </div>
    </Apercu>
  );
}

// ─── 03 · Le règlement au rapport officiel ──────────────────────
function ApercuReglement() {
  return (
    <Apercu titre="Arrivée officielle">
      <div className="flex items-center gap-4 text-sm">
        {[7, 3, 11].map((n, i) => (
          <span key={n} className="text-stone-500">
            {i + 1}<sup>{i ? "e" : "er"}</sup>{" "}
            <span className="font-medium tabular-nums text-stone-900">{n}</span>
          </span>
        ))}
      </div>
      <div className="mt-4 flex items-baseline justify-between border-t border-stone-200 pt-3">
        <span className="text-sm text-stone-500">Réglé au rapport PMU</span>
        <span className="font-display text-2xl font-medium tabular-nums text-emerald-700">+12,40 €</span>
      </div>
    </Apercu>
  );
}

// ─── Étape ──────────────────────────────────────────────────────
const ETAPES = [
  {
    step: "01", titre: "Ouvrez la course",
    desc: "Tout le programme PMU du jour est déjà analysé : classement des partants, probabilité de chacun, score de confiance de la course.",
    Apercu: ApercuClassement,
  },
  {
    step: "02", titre: "Donnez votre budget",
    desc: "Vous entrez un montant, nous répartissons : une ligne sécurité, une ligne rendement, une ligne coup — selon votre profil de risque.",
    Apercu: ApercuBudget,
  },
  {
    step: "03", titre: "Pariez où vous voulez",
    desc: "Vous jouez chez votre opérateur. À l'arrivée, chaque pari est réglé au rapport officiel et votre capital est mis à jour.",
    Apercu: ApercuReglement,
  },
] as const;

function Etape({ e, index }: { e: (typeof ETAPES)[number]; index: number }) {
  const { ref, hidden } = useReveal<HTMLDivElement>(0.3);
  return (
    <div
      ref={ref}
      className={cn("tr-reveal flex h-full flex-col", hidden && "tr-armed")}
      style={{ "--tr-delay": `${index * 100}ms` } as CSSProperties}
    >
      <e.Apercu hidden={hidden} />
      <div className="mt-6 border-t border-stone-200 pt-5">
        <span className="text-sm tabular-nums text-stone-400">{e.step}</span>
        <h3 className="mt-2 font-display text-lg font-medium text-stone-900">{e.titre}</h3>
        <p className="mt-2 text-sm leading-relaxed text-stone-500">{e.desc}</p>
      </div>
    </div>
  );
}

export function EtapesFonctionnement() {
  return (
    <>
      <ol className="grid gap-12 md:grid-cols-3 md:gap-10">
        {ETAPES.map((e, i) => (
          <li key={e.step}><Etape e={e} index={i} /></li>
        ))}
      </ol>

      {/* La page pilier de la méthode n'était atteignable que depuis le pied de page :
          un lien de bas de site ne dit à personne, moteur compris, qu'elle porte le
          sujet principal du site. Elle est citée ici, là où la question se pose. */}
      <Link
        href="/pronostics-ia"
        className="group mx-auto mt-14 flex max-w-3xl items-center gap-4 border-y border-stone-200 py-5 text-left transition-colors hover:border-stone-400"
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
