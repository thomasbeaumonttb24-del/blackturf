"use client";

import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { statsApi } from "@/lib/api";
import { cn } from "@/lib/utils";

// Valeurs initiales (rendu serveur) pour un premier paint instantané + SEO.
// Ensuite le composant rafraîchit en LIVE (SWR) → mêmes chiffres sur toutes
// les pages, toujours à jour.
export interface HeroStatsFallback {
  accuracy_top3?: number | null;
  favori_place_rate?: number | null;
  courses_analysees?: number | null;
}

function numOf(x: unknown): number | null {
  const n = typeof x === "string" ? parseFloat(x) : (x as number);
  return Number.isFinite(n) ? n : null;
}

// Compteur animé (count-up) déclenché quand l'élément entre à l'écran, et rejoué
// à CHAQUE changement de cible.
//
// Bug corrigé le 2026-08-17 (constaté en prod : le hero affichait « 0,0% / 0+ /
// 0,0% » alors que l'API renvoyait 60 % / 3 610 / 65,4 %). L'ancienne version
// verrouillait l'animation avec un drapeau `started` posé définitivement : au
// premier rendu la cible vaut 0 (les données SWR ne sont pas encore arrivées),
// l'observer déclenchait donc une animation 0 → 0, et tout appel ultérieur était
// ignoré. Le garde-fou `done` n'aidait pas : quand la réponse arrivait AVANT la fin
// des 1,4 s d'animation — le cas normal — `done` était encore `false`, et la boucle
// en cours, qui avait capturé l'ancienne cible 0, réécrivait 0 jusqu'au bout.
// Résultat : les chiffres phares de la page d'accueil restaient à zéro.
//
// Ici on repart toujours de la valeur AFFICHÉE vers la nouvelle cible, en annulant
// l'animation précédente — la valeur ne peut donc plus rester bloquée.
function useCountUp(target: number, duration = 1400) {
  // État initialisé à la VRAIE valeur : un compteur qui démarre à 0 affiche un
  // chiffre faux tant qu'il n'a pas été animé. Sur un écran où la tuile est sous la
  // ligne de flottaison, l'observer ne se déclenche jamais et « 0,0% » restait
  // affiché indéfiniment à la place de la performance réelle.
  const [val, setVal] = useState(target);
  const ref = useRef<HTMLSpanElement>(null);
  const rafRef = useRef(0);
  const valRef = useRef(target);
  const visibleRef = useRef(false);

  // La boucle d'animation lit la valeur courante via une ref : la capturer depuis
  // l'état la figerait à celle du rendu où la boucle a démarré.
  useEffect(() => { valRef.current = val; }, [val]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const animateFrom = (start: number) => {
      cancelAnimationFrame(rafRef.current);
      if (start === target) { setVal(target); return; }
      if (typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
        setVal(target);
        return;
      }
      const t0 = performance.now();
      const tick = (now: number) => {
        const p = Math.min((now - t0) / duration, 1);
        const eased = 1 - Math.pow(1 - p, 3); // easeOutCubic
        setVal(start + (target - start) * eased);
        if (p < 1) rafRef.current = requestAnimationFrame(tick);
        else setVal(target);
      };
      rafRef.current = requestAnimationFrame(tick);
    };

    // Déjà vu à l'écran : la nouvelle cible (données live) s'anime depuis la valeur
    // affichée — jamais de retour à zéro.
    if (visibleRef.current) {
      animateFrom(valRef.current);
      return () => cancelAnimationFrame(rafRef.current);
    }

    // Pas encore vu : on affiche déjà le chiffre réel, et le compte à rebours ne se
    // joue (depuis 0) que si la tuile entre vraiment dans le viewport.
    setVal(target);
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => {
        if (e.isIntersecting) {
          visibleRef.current = true;
          io.disconnect();
          animateFrom(0);
        }
      }),
      { threshold: 0.3 },
    );
    io.observe(el);
    return () => { io.disconnect(); cancelAnimationFrame(rafRef.current); };
  }, [target, duration]);

  return { val, ref };
}

interface Item { value: number | null; suffix: string; decimals: number; label: string; cls: string }

function Stat({ value, suffix, decimals }: Item) {
  const { val, ref } = useCountUp(value ?? 0);
  if (value == null) return <span ref={ref}>—</span>;
  return (
    <span ref={ref}>
      {val.toLocaleString("fr-FR", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}
      {suffix}
    </span>
  );
}

export function HeroStats({ fallback }: { fallback?: HeroStatsFallback }) {
  // SOURCE UNIQUE : le track record. Les trois chiffres du hero doivent être les
  // mêmes que ceux du palmarès, sinon le visiteur qui clique voit d'autres valeurs
  // et n'a plus aucune raison de croire les premières.
  //
  // Le compteur venait de `/stats/public`, qui compte toutes les courses TERMINÉES
  // en base (18 357), pronostiquées ou non — affiché « courses analysées » à côté
  // d'une précision mesurée sur 3 630, il gonflait l'échantillon apparent.
  const { data: tr } = useSWR(
    "hero-track-record",
    () => statsApi.trackRecord().then((r) => r.data),
    { refreshInterval: 60_000, revalidateOnFocus: true, shouldRetryOnError: false },
  );

  const g = tr?.global ?? {};
  const accuracy = numOf(g.accuracy_top3) ?? fallback?.accuracy_top3 ?? null;
  const favori = numOf(g.favori_place_rate) ?? fallback?.favori_place_rate ?? null;
  const courses = numOf(g.nb_courses_analysees) ?? fallback?.courses_analysees ?? null;

  const items: Item[] = [
    { value: accuracy, suffix: "%", decimals: 1, label: "Précision Top-3", cls: "text-amber-300" },
    { value: courses, suffix: "", decimals: 0, label: "Courses analysées et notées", cls: "text-white" },
    { value: favori, suffix: "%", decimals: 1, label: "Favori placé", cls: "text-emerald-300" },
  ];

  return (
    <div className="mt-10 grid grid-cols-3 gap-2 sm:gap-4 max-w-xl mx-auto">
      {items.map((s) => (
        <div
          key={s.label}
          className="rounded-2xl bg-white/10 backdrop-blur-md ring-1 ring-white/15 px-2 py-4 sm:px-4 sm:py-5"
        >
          <div className={cn("text-2xl sm:text-4xl font-black tabular-nums", s.cls)}>
            <Stat {...s} />
          </div>
          <div className="text-[10px] sm:text-xs text-white/65 mt-1.5 leading-tight">{s.label}</div>
        </div>
      ))}
    </div>
  );
}
