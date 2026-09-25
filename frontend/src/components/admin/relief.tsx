"use client";

/**
 * Briques « relief » de la console (refonte 3D du 2026-09-25).
 *
 * Aucune ne fabrique de donnée : elles MISENT EN SCÈNE des chiffres déjà
 * mesurés. Un compteur qui s'anime part de la valeur précédente et s'arrête
 * sur la valeur exacte reçue de l'API ; un anneau 3D découpe des parts réelles.
 *
 * Toutes respectent `prefers-reduced-motion` : l'animation saute directement à
 * l'état final, la lecture reste identique.
 */

import * as React from "react";
import { cn } from "@/lib/utils";

/* ─────────────────────────── mouvement réduit ──────────────────────────── */

function useMouvementReduit() {
  const [reduit, setReduit] = React.useState(false);
  React.useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduit(mq.matches);
    const f = () => setReduit(mq.matches);
    mq.addEventListener?.("change", f);
    return () => mq.removeEventListener?.("change", f);
  }, []);
  return reduit;
}

/* ─────────────────────────────── inclinaison ───────────────────────────── */

/**
 * Carte qui s'incline sous le pointeur, avec un reflet qui suit le doigt.
 * Amplitude bornée à quelques degrés : c'est un relief, pas un manège.
 * Désactivée au toucher (le doigt masque déjà la carte) et en mouvement réduit.
 */
export function Relief3D({
  children, className, amplitude = 7, as: Tag = "div", ...rest
}: React.HTMLAttributes<HTMLElement> & { amplitude?: number; as?: "div" | "section" | "article" }) {
  const ref = React.useRef<HTMLElement | null>(null);
  const reduit = useMouvementReduit();

  const bouger = (e: React.PointerEvent<HTMLElement>) => {
    if (reduit || e.pointerType === "touch" || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width;
    const y = (e.clientY - r.top) / r.height;
    const el = ref.current;
    el.dataset.actif = "1";
    el.style.setProperty("--ry", `${(x - 0.5) * amplitude * 2}deg`);
    el.style.setProperty("--rx", `${(0.5 - y) * amplitude * 2}deg`);
    el.style.setProperty("--gx", `${x * 100}%`);
    el.style.setProperty("--gy", `${y * 100}%`);
  };
  const quitter = () => {
    const el = ref.current;
    if (!el) return;
    el.dataset.actif = "0";
    el.style.setProperty("--rx", "0deg");
    el.style.setProperty("--ry", "0deg");
  };

  return React.createElement(
    Tag,
    {
      ...rest,
      ref,
      onPointerMove: bouger,
      onPointerLeave: quitter,
      className: cn("bt-tilt relative", className),
    },
    <>
      {children}
      <span aria-hidden className="bt-reflet" />
    </>,
  );
}

/* ──────────────────────────────── compteur ─────────────────────────────── */

/**
 * Chiffre qui roule de l'ancienne valeur vers la nouvelle à chaque
 * rafraîchissement — c'est ce qui rend visible qu'une donnée vient de bouger.
 */
export function Compteur({
  valeur, format, duree = 900, className,
}: {
  valeur: number | null | undefined;
  format: (v: number) => string;
  duree?: number;
  className?: string;
}) {
  const reduit = useMouvementReduit();
  const [affiche, setAffiche] = React.useState<number | null>(valeur ?? null);
  const precedent = React.useRef<number | null>(valeur ?? null);
  const [flash, setFlash] = React.useState<"hausse" | "baisse" | null>(null);

  React.useEffect(() => {
    if (valeur == null || !isFinite(valeur)) { setAffiche(null); return; }
    const depart = precedent.current ?? 0;
    const change = precedent.current != null && precedent.current !== valeur;
    precedent.current = valeur;
    if (change) {
      setFlash(valeur > depart ? "hausse" : "baisse");
      const t = window.setTimeout(() => setFlash(null), 1400);
      if (reduit) { setAffiche(valeur); return () => window.clearTimeout(t); }
    }
    if (reduit || depart === valeur) { setAffiche(valeur); return; }
    let raf = 0;
    const t0 = performance.now();
    const pas = (t: number) => {
      const p = Math.min(1, (t - t0) / duree);
      const e = 1 - Math.pow(1 - p, 3);
      setAffiche(depart + (valeur - depart) * e);
      if (p < 1) raf = requestAnimationFrame(pas);
      else setAffiche(valeur);
    };
    raf = requestAnimationFrame(pas);
    return () => cancelAnimationFrame(raf);
  }, [valeur, duree, reduit]);

  return (
    <span
      className={cn(
        "tabular-nums transition-[color,text-shadow] duration-700",
        flash === "hausse" && "text-emerald-300 [text-shadow:0_0_18px_rgba(52,211,153,0.6)]",
        flash === "baisse" && "text-red-300 [text-shadow:0_0_18px_rgba(248,113,113,0.6)]",
        className,
      )}
    >
      {affiche == null ? "—" : format(affiche)}
    </span>
  );
}

/* ─────────────────────────────── sparkline ─────────────────────────────── */

/** Mini-courbe en aire, avec lueur et point final. */
export function Sparkline({
  valeurs, couleur = "#f5b544", hauteur = 36, className,
}: {
  valeurs: Array<number | null | undefined>;
  couleur?: string;
  hauteur?: number;
  className?: string;
}) {
  const id = React.useId().replace(/:/g, "");
  const pts = valeurs.map((v) => (v == null || !isFinite(v) ? null : v));
  const reels = pts.filter((v): v is number => v != null);
  if (reels.length < 2) return <div style={{ height: hauteur }} className={className} />;
  const min = Math.min(...reels);
  const max = Math.max(...reels);
  const w = 100;
  const h = hauteur;
  const pad = 3;
  const xy = pts
    .map((v, i) => v == null ? null : [
      (i / (pts.length - 1)) * w,
      max === min ? h / 2 : pad + (1 - (v - min) / (max - min)) * (h - pad * 2),
    ] as const)
    .filter((p): p is readonly [number, number] => p != null);
  const ligne = xy.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(2)},${p[1].toFixed(2)}`).join(" ");
  const aire = `${ligne} L${xy[xy.length - 1][0]},${h} L${xy[0][0]},${h} Z`;
  const dernier = xy[xy.length - 1];
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className={cn("w-full overflow-visible", className)} style={{ height: h }} aria-hidden>
      <defs>
        <linearGradient id={`sp-${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={couleur} stopOpacity={0.45} />
          <stop offset="100%" stopColor={couleur} stopOpacity={0} />
        </linearGradient>
      </defs>
      <path d={aire} fill={`url(#sp-${id})`} />
      <path d={ligne} fill="none" stroke={couleur} strokeWidth={1.6} vectorEffect="non-scaling-stroke"
        style={{ filter: `drop-shadow(0 0 4px ${couleur})` }} />
      <circle cx={dernier[0]} cy={dernier[1]} r={2.2} fill={couleur} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

/* ─────────────────────────────── anneau 3D ─────────────────────────────── */

export interface Part { cle: string; label: string; n: number; couleur: string }

/**
 * Anneau extrudé en vraie 3D CSS : N couches du même dégradé conique empilées
 * sur l'axe Z, les plus basses assombries — l'épaisseur est réelle, elle se
 * voit quand l'anneau tourne. Le total et la légende restent en texte à côté :
 * la couleur ne porte jamais seule l'information.
 */
export function Anneau3D({
  parts, taille = 180, epaisseur = 14, tourne = true, centre, className,
}: {
  parts: ReadonlyArray<Part>;
  taille?: number;
  epaisseur?: number;
  tourne?: boolean;
  centre?: React.ReactNode;
  className?: string;
}) {
  const total = parts.reduce((s, p) => s + Math.max(0, p.n), 0);
  let acc = 0;
  const arrets = total > 0
    ? parts.filter((p) => p.n > 0).map((p) => {
      const a = (acc / total) * 360;
      acc += p.n;
      const b = (acc / total) * 360;
      return `${p.couleur} ${a}deg ${b - 0.8}deg, rgba(0,0,0,0) ${b - 0.8}deg ${b}deg`;
    }).join(", ")
    : "rgba(255,255,255,0.08) 0deg 360deg";
  const fond = `conic-gradient(${arrets})`;

  return (
    <div className={cn("relative flex items-center justify-center", className)} style={{ width: taille, height: taille }}>
      <div className="bt-anneau-scene absolute inset-0 flex items-center justify-center">
        <div className="bt-anneau" data-tourne={tourne ? "1" : "0"} style={{ width: taille * 0.92, height: taille * 0.92 }}>
          {Array.from({ length: epaisseur }).map((_, i) => (
            <i
              key={i}
              style={{
                background: fond,
                transform: `translateZ(${i - epaisseur}px)`,
                filter: i === epaisseur - 1 ? "brightness(1.1) saturate(1.1)" : `brightness(${0.35 + (i / epaisseur) * 0.4})`,
              }}
            />
          ))}
          {/* Ombre portée au sol */}
          <i
            style={{
              transform: `translateZ(${-epaisseur - 8}px) scale(1.05)`,
              background: "radial-gradient(circle, rgba(0,0,0,0.7), transparent 70%)",
              filter: "blur(10px)",
              WebkitMask: "none",
              mask: "none",
            }}
          />
        </div>
      </div>
      {centre && <div className="relative z-10 text-center">{centre}</div>}
    </div>
  );
}

/* ─────────────────────────── barres 3D (recharts) ──────────────────────── */

/**
 * Forme de barre en prisme pour `<Bar shape={…}>` : une face avant en dégradé,
 * une face de dessus plus claire et un flanc droit plus sombre. La hauteur de la
 * face avant reste EXACTEMENT celle de la valeur ; le volume se dessine en
 * retrait, au-dessus et à droite, sans fausser la lecture sur l'axe.
 */
export function formeBarre3D(couleur: string, profondeur = 8) {
  return function Barre3D(props: unknown) {
    const { x, y, width, height } = props as { x: number; y: number; width: number; height: number };
    if (!isFinite(x) || !isFinite(y) || !width || !height || height <= 0) return <g />;
    const d = Math.min(profondeur, width * 0.45);
    const w = width - d;
    const id = `b3d-${couleur.replace(/[^a-z0-9]/gi, "")}`;
    return (
      <g>
        <defs>
          <linearGradient id={`${id}-f`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={couleur} stopOpacity={1} />
            <stop offset="100%" stopColor={couleur} stopOpacity={0.55} />
          </linearGradient>
        </defs>
        {/* flanc */}
        <path d={`M${x + w},${y} L${x + w + d},${y - d * 0.6} L${x + w + d},${y + height - d * 0.6} L${x + w},${y + height} Z`}
          fill={couleur} style={{ filter: "brightness(0.55)" }} />
        {/* dessus */}
        <path d={`M${x},${y} L${x + d},${y - d * 0.6} L${x + w + d},${y - d * 0.6} L${x + w},${y} Z`}
          fill={couleur} style={{ filter: "brightness(1.35)" }} />
        {/* face */}
        <rect x={x} y={y} width={w} height={height} fill={`url(#${id}-f)`} />
        <rect x={x} y={y} width={w} height={Math.min(2, height)} fill="rgba(255,255,255,0.45)" />
      </g>
    );
  };
}

/* ─────────────────────────── infobulle en verre ────────────────────────── */

export function InfobulleVerre({
  active, payload, label, formatLabel, formatValeur,
}: {
  active?: boolean;
  payload?: Array<{ name?: string; value?: number; color?: string; dataKey?: string; payload?: Record<string, unknown> }>;
  label?: string | number;
  formatLabel?: (l: string | number) => React.ReactNode;
  formatValeur?: (v: number, cle?: string) => React.ReactNode;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="min-w-[10rem] rounded-xl border border-amber-300/25 bg-[#0b0e19]/95 p-3 text-xs shadow-2xl backdrop-blur">
      {label != null && (
        <div className="mb-2 font-semibold text-amber-300">{formatLabel ? formatLabel(label) : label}</div>
      )}
      <div className="space-y-1">
        {payload.filter((p) => p.value != null).map((p) => (
          <div key={String(p.dataKey ?? p.name)} className="flex items-center justify-between gap-4">
            <span className="flex items-center gap-1.5 text-white/70">
              <span className="h-2 w-2 rounded-full" style={{ background: p.color, boxShadow: `0 0 8px ${p.color}` }} />
              {p.name}
            </span>
            <span className="font-semibold tabular-nums text-white">
              {formatValeur ? formatValeur(Number(p.value), p.dataKey) : p.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ──────────────────────────── fraîcheur live ───────────────────────────── */

/**
 * « Synchronisé il y a 12 s » — chaque panneau en direct dit l'âge de SA
 * donnée. Un tableau qui ne bouge pas peut être à jour ou figé : sans ce
 * témoin, impossible de le savoir.
 */
export function Fraicheur({
  depuis: t, enCours, cadence, className,
}: {
  /** Horodatage (ms) de la dernière réception. */
  depuis: number | null | undefined;
  enCours?: boolean;
  /** Cadence de rafraîchissement attendue, en ms — au-delà de 3×, le témoin vire à l'ambre. */
  cadence?: number;
  className?: string;
}) {
  const [, force] = React.useReducer((x: number) => x + 1, 0);
  React.useEffect(() => {
    const i = window.setInterval(force, 1000);
    return () => window.clearInterval(i);
  }, []);
  const age = t ? Math.max(0, Math.round((Date.now() - t) / 1000)) : null;
  const perime = age != null && cadence != null && age * 1000 > cadence * 3;
  const texte = enCours ? "synchro…" : age == null ? "en attente" : age < 60 ? `il y a ${age} s` : `il y a ${Math.floor(age / 60)} min`;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-semibold",
        perime ? "border-amber-400/30 bg-amber-400/10 text-amber-300" : "border-emerald-400/25 bg-emerald-400/10 text-emerald-300",
        className,
      )}
      title="Âge de la donnée affichée"
    >
      <span className="relative flex h-1.5 w-1.5">
        {!perime && <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-70 motion-safe:animate-ping" />}
        <span className={cn("relative inline-flex h-1.5 w-1.5 rounded-full", perime ? "bg-amber-400" : "bg-emerald-400")} />
      </span>
      LIVE · {texte}
    </span>
  );
}

/** Horodatage de la dernière réception d'une donnée SWR (change à chaque réponse). */
export function useRecuLe(data: unknown): number | null {
  const [t, setT] = React.useState<number | null>(null);
  React.useEffect(() => { if (data !== undefined) setT(Date.now()); }, [data]);
  return t;
}

/* ─────────────────────────── jauge circulaire ──────────────────────────── */

/** Jauge en arc — pour un taux (conversion, précision) lu d'un coup d'œil. */
export function Jauge({
  valeur, max = 100, couleur = "#f5b544", taille = 120, epaisseur = 10, children,
}: {
  valeur: number | null | undefined;
  max?: number;
  couleur?: string;
  taille?: number;
  epaisseur?: number;
  children?: React.ReactNode;
}) {
  const r = (taille - epaisseur) / 2;
  const c = 2 * Math.PI * r;
  const arc = c * 0.75;
  const frac = valeur == null || !isFinite(valeur) ? 0 : Math.max(0, Math.min(1, valeur / max));
  return (
    <div className="relative" style={{ width: taille, height: taille }}>
      <svg width={taille} height={taille} className="-rotate-[225deg]" aria-hidden>
        <circle cx={taille / 2} cy={taille / 2} r={r} fill="none" stroke="rgba(255,255,255,0.08)"
          strokeWidth={epaisseur} strokeDasharray={`${arc} ${c}`} strokeLinecap="round" />
        <circle cx={taille / 2} cy={taille / 2} r={r} fill="none" stroke={couleur}
          strokeWidth={epaisseur} strokeDasharray={`${arc * frac} ${c}`} strokeLinecap="round"
          style={{ filter: `drop-shadow(0 0 6px ${couleur})`, transition: "stroke-dasharray 1s cubic-bezier(.16,1,.3,1)" }} />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center">{children}</div>
    </div>
  );
}
