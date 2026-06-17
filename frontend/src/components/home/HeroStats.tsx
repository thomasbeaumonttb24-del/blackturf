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

// Compteur animé (count-up) déclenché quand l'élément entre à l'écran ;
// se met à jour si la valeur live change après coup.
function useCountUp(target: number, duration = 1400) {
  const [val, setVal] = useState(0);
  const ref = useRef<HTMLSpanElement>(null);
  const started = useRef(false);
  const done = useRef(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const run = () => {
      if (started.current) return;
      started.current = true;
      if (typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        setVal(target); done.current = true; return;
      }
      const t0 = performance.now();
      const tick = (now: number) => {
        const p = Math.min((now - t0) / duration, 1);
        const eased = 1 - Math.pow(1 - p, 3); // easeOutCubic
        setVal(target * eased);
        if (p < 1) requestAnimationFrame(tick);
        else { setVal(target); done.current = true; }
      };
      requestAnimationFrame(tick);
    };
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => e.isIntersecting && run()),
      { threshold: 0.3 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [target, duration]);
  // Si la valeur live change une fois l'animation terminée → on s'aligne.
  useEffect(() => { if (done.current) setVal(target); }, [target]);
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
  // Live : track-record (précision + favori placé) + public (courses analysées).
  const { data: tr } = useSWR(
    "hero-track-record",
    () => statsApi.trackRecord().then((r) => r.data),
    { refreshInterval: 60_000, revalidateOnFocus: true, shouldRetryOnError: false },
  );
  const { data: pub } = useSWR(
    "hero-public",
    () => statsApi.public().then((r) => r.data),
    { refreshInterval: 60_000, revalidateOnFocus: true, shouldRetryOnError: false },
  );

  const g = tr?.global ?? {};
  const accuracy = numOf(g.accuracy_top3) ?? fallback?.accuracy_top3 ?? null;
  const favori = numOf(g.favori_place_rate) ?? fallback?.favori_place_rate ?? null;
  const courses = numOf(pub?.nb_courses_analysees) ?? fallback?.courses_analysees ?? null;

  const items: Item[] = [
    { value: accuracy, suffix: "%", decimals: 1, label: "Précision Top-3", cls: "text-amber-300" },
    { value: courses, suffix: "+", decimals: 0, label: "Courses analysées", cls: "text-white" },
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
