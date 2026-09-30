"use client";

import useSWR from "swr";
import { statsApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useCountUp } from "@/hooks/useCountUp";
import { Tilt } from "@/components/track-record/effets";

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
    // Même libellé que la carte de la section « preuves » : le chiffre mesure la
    // présence du gagnant réel dans notre top-3, et « Précision Top-3 » laissait le
    // visiteur libre de lire autre chose.
    { value: accuracy, suffix: "%", decimals: 1, label: "Gagnant dans le Top-3", cls: "text-amber-300" },
    { value: courses, suffix: "", decimals: 0, label: "Courses analysées et notées", cls: "text-white" },
    { value: favori, suffix: "%", decimals: 1, label: "Favori placé", cls: "text-emerald-300" },
  ];

  return (
    <div className="mx-auto mt-5 grid max-w-2xl grid-cols-3 gap-2 sm:mt-10 sm:gap-4">
      {items.map((s, i) => (
        <Tilt
          key={s.label}
          max={10}
          className="tr-rise rounded-2xl bg-gradient-to-b from-white/[0.16] to-white/[0.05] px-2 py-3 ring-1 ring-white/20 shadow-[0_20px_40px_-24px_rgba(0,0,0,.8)] backdrop-blur-md sm:px-4 sm:py-5"
          style={{ animationDelay: `${i * 60}ms` }}
        >
          <span className="absolute inset-x-4 top-0 h-px bg-gradient-to-r from-transparent via-amber-200/70 to-transparent" aria-hidden="true" />
          <div className={cn("tr-pop font-display text-[1.35rem] font-black leading-tight tabular-nums sm:text-4xl", s.cls)}>
            <Stat {...s} />
          </div>
          <div className="mt-1 text-[10px] font-medium leading-tight text-white/75 sm:mt-1.5 sm:text-xs">{s.label}</div>
        </Tilt>
      ))}
    </div>
  );
}
