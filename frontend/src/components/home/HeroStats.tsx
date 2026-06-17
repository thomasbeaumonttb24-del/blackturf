"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

// Compteur animé (count-up) déclenché quand l'élément entre à l'écran.
function useCountUp(target: number, duration = 1400) {
  const [val, setVal] = useState(0);
  const ref = useRef<HTMLSpanElement>(null);
  const started = useRef(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const run = () => {
      if (started.current) return;
      started.current = true;
      if (typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        setVal(target);
        return;
      }
      const t0 = performance.now();
      const tick = (now: number) => {
        const p = Math.min((now - t0) / duration, 1);
        const eased = 1 - Math.pow(1 - p, 3); // easeOutCubic
        setVal(target * eased);
        if (p < 1) requestAnimationFrame(tick);
        else setVal(target);
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
  return { val, ref };
}

export interface HeroStatItem {
  value: number | null;
  suffix?: string;     // ex "%" ou "+"
  decimals?: number;   // décimales affichées (0 par défaut)
  label: string;
  cls: string;         // couleur du chiffre
}

function Stat({ value, suffix = "", decimals = 0 }: HeroStatItem) {
  const { val, ref } = useCountUp(value ?? 0);
  if (value == null) return <span ref={ref}>—</span>;
  return (
    <span ref={ref}>
      {val.toLocaleString("fr-FR", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}
      {suffix}
    </span>
  );
}

export function HeroStats({ items }: { items: HeroStatItem[] }) {
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
