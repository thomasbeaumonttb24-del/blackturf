"use client";

/**
 * Briques visuelles de « Mon espace » : compteur animé, anneau de jauge,
 * courbe du capital et titres de section.
 *
 * Même règle que le palmarès (`components/track-record/effets.tsx`) : la valeur
 * affichée par défaut est la VRAIE valeur ; l'animation n'est qu'un bonus, sautée
 * si l'utilisateur a demandé à réduire les animations.
 */

import { useEffect, useId, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { Star } from "lucide-react";
import { Reveal } from "@/components/track-record/effets";
import { cn } from "@/lib/utils";

function mouvementReduit() {
  return typeof window !== "undefined"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export const nf = (n: number, d = 0) =>
  n.toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d });

/**
 * Compte de 0 jusqu'à `valeur` à la première valeur reçue, puis glisse d'une
 * valeur à l'autre lors des rafraîchissements.
 */
function useCompteur(valeur: number, duree = 1300) {
  const [val, setVal] = useState(valeur);
  const depart = useRef<number | null>(null);

  useEffect(() => {
    if (mouvementReduit()) { setVal(valeur); depart.current = valeur; return; }
    const de = depart.current ?? 0;
    depart.current = valeur;
    if (de === valeur) { setVal(valeur); return; }
    let raf = 0;
    const t0 = performance.now();
    const tick = (now: number) => {
      const p = Math.min((now - t0) / duree, 1);
      const e = 1 - Math.pow(1 - p, 3);
      setVal(de + (valeur - de) * e);
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    // Filet : un onglet en arrière-plan gèle rAF, la vraie valeur finit affichée.
    const garde = setTimeout(() => { cancelAnimationFrame(raf); setVal(valeur); }, duree + 600);
    return () => { cancelAnimationFrame(raf); clearTimeout(garde); };
  }, [valeur, duree]);

  return val;
}

export function Compteur({ valeur, decimales = 0, prefixe = "", suffixe = "", signe = false, className }: {
  valeur: number | null | undefined;
  decimales?: number;
  prefixe?: string;
  suffixe?: string;
  /** Affiche « + » devant une valeur positive. */
  signe?: boolean;
  className?: string;
}) {
  const v = useCompteur(valeur ?? 0);
  if (valeur == null) return <span className={className}>—</span>;
  const plus = signe && valeur > 0 ? "+" : "";
  return <span className={cn("tabular-nums", className)}>{plus}{prefixe}{nf(v, decimales)}{suffixe}</span>;
}

/** Anneau de jauge : se remplit à l'affichage (`pct` entre 0 et 100). */
export function Anneau({ pct, taille = 96, epaisseur = 9, couleur = "#F59E0B", fond = "rgba(255,255,255,.12)", children }: {
  pct: number;
  taille?: number;
  epaisseur?: number;
  couleur?: string | [string, string];
  fond?: string;
  children?: ReactNode;
}) {
  const id = useId().replace(/:/g, "");
  const r = (taille - epaisseur) / 2;
  const c = 2 * Math.PI * r;
  const off = c * (1 - Math.max(0, Math.min(100, pct)) / 100);
  const [a, b] = Array.isArray(couleur) ? couleur : [couleur, couleur];
  return (
    <div className="relative shrink-0" style={{ width: taille, height: taille }}>
      <svg width={taille} height={taille} viewBox={`0 0 ${taille} ${taille}`} className="-rotate-90" aria-hidden="true">
        <defs>
          <linearGradient id={`g${id}`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor={a} />
            <stop offset="100%" stopColor={b} />
          </linearGradient>
        </defs>
        <circle cx={taille / 2} cy={taille / 2} r={r} fill="none" stroke={fond} strokeWidth={epaisseur} />
        <circle
          cx={taille / 2} cy={taille / 2} r={r} fill="none"
          stroke={`url(#g${id})`} strokeWidth={epaisseur} strokeLinecap="round"
          strokeDasharray={c}
          className="ring-anim"
          style={{ strokeDashoffset: off, "--c": c, "--off": off } as React.CSSProperties}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center">{children}</div>
    </div>
  );
}

/**
 * Courbe du capital sur les derniers paris réglés. `points` = capital après
 * chaque pari, dans l'ordre chronologique.
 */
export function CourbeCapital({ points, hauteur = 140 }: { points: number[]; hauteur?: number }) {
  const id = useId().replace(/:/g, "");
  // Le SVG est dessiné à la largeur réelle du cadre : sans déformation, le trait
  // garde son épaisseur et le point final reste rond.
  const cadre = useRef<HTMLDivElement>(null);
  const [L, setL] = useState(600);
  useEffect(() => {
    const el = cadre.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const maj = () => setL(Math.max(120, Math.round(el.clientWidth)));
    maj();
    const ro = new ResizeObserver(maj);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const H = hauteur;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const etendue = max - min || 1;
  const pas = L / (points.length - 1);
  const xy = points.map((v, i) => [i * pas, H - 10 - ((v - min) / etendue) * (H - 24)] as const);
  const d = xy.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const trait = "#1C1917";
  const aire = "#D97706";
  const [xf, yf] = xy[xy.length - 1];

  return (
    <div ref={cadre} className="w-full" style={{ height: H }}>
    <svg width={L} height={H} viewBox={`0 0 ${L} ${H}`} className="block overflow-visible" aria-hidden="true">
      <defs>
        <linearGradient id={`a${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={aire} stopOpacity=".16" />
          <stop offset="100%" stopColor={aire} stopOpacity="0" />
        </linearGradient>
      </defs>
      {[0.25, 0.5, 0.75].map((f) => (
        <line key={f} x1="0" x2={L} y1={H * f} y2={H * f} stroke="rgba(120,113,108,.12)" />
      ))}
      <path d={`${d} L${L} ${H} L0 ${H} Z`} fill={`url(#a${id})`} className="esp-aire" />
      <path
        d={d} fill="none" stroke={trait} strokeWidth="1.75" strokeLinejoin="round" strokeLinecap="round"
        pathLength={1} className="esp-trace"
      />
      <circle cx={xf} cy={yf} r="9" fill={aire} opacity=".15" className="esp-aire" />
      <circle cx={xf} cy={yf} r="4" fill="#fff" stroke={aire} strokeWidth="2" className="esp-aire" />
    </svg>
    </div>
  );
}

/** Titre de section : sur-titre discret à filet doré, titre en display. */
export function SectionTitre({ sur, titre, aside, className }: {
  sur: string;
  titre: string;
  aside?: ReactNode;
  className?: string;
}) {
  return (
    <Reveal className={cn("mb-5 flex items-end justify-between gap-3", className)}>
      <div className="min-w-0">
        <span className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.2em] text-stone-500">
          <span className="h-px w-5 bg-amber-600/70" aria-hidden="true" /> {sur}
        </span>
        <h2 className="mt-2 font-display text-xl font-medium tracking-tight text-stone-900 sm:text-[1.65rem]">{titre}</h2>
      </div>
      {aside && <div className="shrink-0">{aside}</div>}
    </Reveal>
  );
}

/**
 * Plan en relief, repris de l'accueil (`.scene3d`) : légèrement incliné au repos,
 * il suit le pointeur de quelques degrés. Ombre au sol pour l'asseoir.
 */
export function Plan3D({ children, sens = 1, className }: { children: ReactNode; sens?: 1 | -1; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
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
    <div ref={ref} onPointerMove={onMove} onPointerLeave={onLeave} className={cn("scene3d relative", className)} style={{ "--sens": sens } as CSSProperties}>
      <div className="scene3d-plan">{children}</div>
      <div className="pointer-events-none absolute inset-x-[14%] -bottom-7 -z-10 h-9 rounded-[100%] bg-stone-900/20 blur-2xl" aria-hidden="true" />
    </div>
  );
}

/** Niveau d'un pari de valeur, de 1 à 4 étoiles. */
export function Etoiles({ n, taille = "h-3.5 w-3.5", vides = true, className }: {
  n: number;
  taille?: string;
  /** Faux : n'affiche que les étoiles pleines (boutons de filtre sur fond sombre). */
  vides?: boolean;
  className?: string;
}) {
  const k = Math.max(0, Math.min(4, n));
  return (
    <span role="img" className={cn("inline-flex items-center gap-0.5", className)} aria-label={`${k} étoile${k > 1 ? "s" : ""} sur 4`}>
      {Array.from({ length: vides ? 4 : k }).map((_, i) => (
        <Star key={i} aria-hidden="true" className={cn(taille, i < k ? "fill-amber-500 text-amber-500" : "fill-stone-200 text-stone-200")} />
      ))}
    </span>
  );
}
