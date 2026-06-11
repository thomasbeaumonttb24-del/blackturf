"use client";
import { useEffect, useRef, useState } from "react";

interface Props {
  end: number;
  duration?: number;
  decimals?: number;
  prefix?: string;
  suffix?: string;
  className?: string;
}

export function AnimatedCounter({ end, duration = 2000, decimals = 0, prefix = "", suffix = "", className = "" }: Props) {
  const [display, setDisplay] = useState(0);
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    let started = false;        // une animation par changement de `end` (effet re-run)
    let raf = 0;
    let cancelled = false;
    const prefersReduced =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

    const animate = () => {
      if (prefersReduced) { setDisplay(end); return; }
      const startTime = performance.now();
      const tick = (now: number) => {
        if (cancelled) return;
        const p = Math.min((now - startTime) / duration, 1);
        const eased = 1 - Math.pow(1 - p, 3);
        setDisplay(eased * end);
        if (p < 1) raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
    };

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !started) {
          started = true;
          animate();
        }
      },
      { threshold: 0.5 }
    );
    observer.observe(el);

    // Annule le RAF en cours (sinon setState après unmount = fuite + warning).
    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      observer.disconnect();
    };
  }, [end, duration]);

  return (
    <span ref={ref} className={className}>
      {prefix}{display.toFixed(decimals)}{suffix}
    </span>
  );
}
