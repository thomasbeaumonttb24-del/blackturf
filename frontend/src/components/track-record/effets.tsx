"use client";

/**
 * Effets de relief du palmarès : apparition au défilement et cartes inclinables.
 *
 * Règle commune : l'état servi est l'état FINAL. Un bloc n'est masqué (pour être
 * révélé ensuite) que si le script tourne, que l'utilisateur n'a pas demandé à
 * réduire les animations ET que le bloc est encore sous la ligne de flottaison.
 * Un robot, une capture automatisée ou un navigateur sans IntersectionObserver
 * voient donc toujours la page complète — jamais une section vide.
 */

import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { cn } from "@/lib/utils";

function mouvementReduit() {
  return typeof window !== "undefined"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * `hidden` vaut vrai tant qu'un bloc armé n'est pas encore entré à l'écran :
 * sert aux apparitions comme aux jauges qui se remplissent.
 */
export function useReveal<T extends HTMLElement = HTMLDivElement>(seuil = 0.18) {
  const ref = useRef<T>(null);
  const [armed, setArmed] = useState(false);
  const [inView, setInView] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined" || mouvementReduit()) {
      setInView(true);
      return;
    }
    // Déjà visible au montage : on ne le cache pas (pas de clignotement).
    if (el.getBoundingClientRect().top < window.innerHeight * 0.92) {
      setInView(true);
      return;
    }
    setArmed(true);
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => {
        if (e.isIntersecting) { setInView(true); io.disconnect(); }
      }),
      { threshold: seuil, rootMargin: "0px 0px -6% 0px" },
    );
    io.observe(el);
    // Filet : quoi qu'il arrive, le contenu finit affiché.
    const garde = setTimeout(() => setInView(true), 9000);
    return () => { io.disconnect(); clearTimeout(garde); };
  }, [seuil]);

  return { ref, hidden: armed && !inView };
}

export function Reveal({ children, className, delay = 0, as: Tag = "div" }: {
  children: ReactNode;
  className?: string;
  delay?: number;
  as?: "div" | "section" | "li" | "article";
}) {
  const { ref, hidden } = useReveal<HTMLDivElement>();
  return (
    <Tag
      ref={ref as any}
      className={cn("tr-reveal", hidden && "tr-armed", className)}
      style={{ "--tr-delay": `${delay}ms` } as CSSProperties}
    >
      {children}
    </Tag>
  );
}

/**
 * Carte qui s'incline vers le pointeur, avec un reflet qui le suit.
 * Uniquement à la souris : au doigt, l'inclinaison gênerait le défilement.
 */
export function Tilt({ children, className, max = 7, style }: {
  children: ReactNode;
  className?: string;
  max?: number;
  style?: CSSProperties;
}) {
  const ref = useRef<HTMLDivElement>(null);

  const onMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.pointerType !== "mouse" || mouvementReduit()) return;
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width;
    const y = (e.clientY - r.top) / r.height;
    el.classList.add("tr-tilting");
    el.style.setProperty("--ry", `${((x - 0.5) * 2 * max).toFixed(2)}deg`);
    el.style.setProperty("--rx", `${((0.5 - y) * 2 * max).toFixed(2)}deg`);
    el.style.setProperty("--mx", `${(x * 100).toFixed(1)}%`);
    el.style.setProperty("--my", `${(y * 100).toFixed(1)}%`);
  };
  const onLeave = () => {
    const el = ref.current;
    if (!el) return;
    el.classList.remove("tr-tilting");
    el.style.setProperty("--rx", "0deg");
    el.style.setProperty("--ry", "0deg");
  };

  return (
    <div ref={ref} onPointerMove={onMove} onPointerLeave={onLeave} className={cn("tr-tilt relative", className)} style={style}>
      {children}
      <span className="tr-glare" aria-hidden="true" />
    </div>
  );
}
