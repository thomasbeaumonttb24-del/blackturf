"use client";

import { useEffect, useRef, useState } from "react";

// Partagé par le hero de l'accueil et celui de /track-record : même animation,
// même garantie (valeur réelle dès le rendu serveur, jamais bloquée à zéro).
//
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
export function useCountUp(target: number, duration = 1400) {
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
        const p = Math.min(Math.max((now - t0) / duration, 0), 1);
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
