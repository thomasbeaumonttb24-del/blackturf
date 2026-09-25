"use client";

/**
 * Briques graphiques de la console (reprise « sobre et pro » du 2026-09-25).
 *
 * La première version de la journée misait sur la 3D (barres en prisme, anneau
 * extrudé, cartes inclinables, lueurs). L'exploitant l'a trouvée trop « IA » :
 * il veut des COURBES, belles, détaillées et précises, dans un registre de
 * rapport financier. D'où les règles de ce fichier :
 *
 *   · une couleur de donnée principale (ardoise), l'or pour l'accent, le vert
 *     et le rouge seulement pour un signe ;
 *   · des traits fins (1,75 px), un remplissage à peine teinté, des points
 *     marqués aux valeurs réelles — jamais de point inventé entre deux mesures ;
 *   · des infobulles qui donnent le chiffre exact ET son contexte (variation,
 *     détail), plutôt qu'une simple valeur ;
 *   · aucune lueur, aucune ombre portée, aucune animation décorative.
 *
 * Aucune brique ne fabrique de donnée : elles mettent en forme des chiffres
 * déjà mesurés par l'API.
 */

import * as React from "react";
import { cn } from "@/lib/utils";

/* ─────────────────────────────── palette ───────────────────────────────── */

export const PALETTE = {
  encre: "#1b2230",
  ardoise: "#27456b",
  ardoiseMoyen: "#6f8bab",
  ardoiseClair: "#c9d5e3",
  or: "#a8741a",
  orClair: "#e9d3a6",
  vert: "#0f7b5a",
  rouge: "#b42318",
  violet: "#6b5b95",
  gris: "#b9bec6",
  grille: "#ecebe6",
  axe: "#6b7079",
} as const;

/** Couleurs des formules, identiques sur tous les écrans. */
export const COULEUR_FORMULE = { standard: PALETTE.ardoiseMoyen, expert: PALETTE.or } as const;

/** Réglages communs des axes : petits, gris, sans trait d'axe. */
export const AXE = {
  tick: { fontSize: 11, fill: PALETTE.axe },
  tickLine: false,
  axisLine: false,
} as const;

/* ──────────────────────────────── compteur ─────────────────────────────── */

/**
 * Chiffre qui glisse de l'ancienne valeur vers la nouvelle quand la donnée est
 * rafraîchie : c'est ce qui rend visible qu'un chiffre vient de bouger. Court
 * (0,5 s) et sans effet de couleur ; instantané en mouvement réduit.
 */
export function Compteur({
  valeur, format, duree = 500, className,
}: {
  valeur: number | null | undefined;
  format: (v: number) => string;
  duree?: number;
  className?: string;
}) {
  const [affiche, setAffiche] = React.useState<number | null>(valeur ?? null);
  const precedent = React.useRef<number | null>(valeur ?? null);

  React.useEffect(() => {
    if (valeur == null || !isFinite(valeur)) { setAffiche(null); return; }
    const depart = precedent.current;
    precedent.current = valeur;
    const reduit = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (depart == null || depart === valeur || reduit) { setAffiche(valeur); return; }
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
  }, [valeur, duree]);

  return <span className={cn("tabular-nums", className)}>{affiche == null ? "—" : format(affiche)}</span>;
}

/* ─────────────────────────────── sparkline ─────────────────────────────── */

/** Mini-courbe lissée : trait fin, remplissage très pâle, dernier point marqué. */
export function Sparkline({
  valeurs, couleur = PALETTE.ardoise, hauteur = 40, className,
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
  const w = 200;
  const h = hauteur;
  const pad = 4;
  const xy = pts
    .map((v, i) => v == null ? null : [
      (i / (pts.length - 1)) * w,
      max === min ? h / 2 : pad + (1 - (v - min) / (max - min)) * (h - pad * 2),
    ] as const)
    .filter((p): p is readonly [number, number] => p != null);
  // Courbe de Catmull-Rom convertie en Bézier : lisse sans dépasser les points.
  const chemin = xy.reduce((acc, p, i, a) => {
    if (i === 0) return `M${p[0]},${p[1]}`;
    const p0 = a[i - 2] ?? a[i - 1];
    const p1 = a[i - 1];
    const p2 = p;
    const p3 = a[i + 1] ?? p;
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
    const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    return `${acc} C${c1[0]},${c1[1]} ${c2[0]},${c2[1]} ${p2[0]},${p2[1]}`;
  }, "");
  const dernier = xy[xy.length - 1];
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className={cn("w-full overflow-visible", className)} style={{ height: h }} aria-hidden>
      <defs>
        <linearGradient id={`sp-${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={couleur} stopOpacity={0.14} />
          <stop offset="100%" stopColor={couleur} stopOpacity={0} />
        </linearGradient>
      </defs>
      <path d={`${chemin} L${dernier[0]},${h} L${xy[0][0]},${h} Z`} fill={`url(#sp-${id})`} />
      <path d={chemin} fill="none" stroke={couleur} strokeWidth={1.5} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
      <circle cx={dernier[0]} cy={dernier[1]} r={2.5} fill="#fff" stroke={couleur} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

/* ──────────────────────────────── anneau ───────────────────────────────── */

export interface Part { cle: string; label: string; n: number; couleur: string }

/**
 * Anneau de répartition plat, segments séparés par un fin blanc. Le total est
 * au centre, la légende chiffrée reste à côté : la couleur ne porte jamais
 * seule l'information.
 */
export function Anneau({
  parts, taille = 168, epaisseur = 18, centre, className,
}: {
  parts: ReadonlyArray<Part>;
  taille?: number;
  epaisseur?: number;
  centre?: React.ReactNode;
  className?: string;
}) {
  const r = (taille - epaisseur) / 2;
  const c = 2 * Math.PI * r;
  const total = parts.reduce((s, p) => s + Math.max(0, p.n), 0);
  const visibles = parts.filter((p) => p.n > 0);
  const ecart = visibles.length > 1 ? 2 : 0;
  let acc = 0;
  return (
    <div className={cn("relative shrink-0", className)} style={{ width: taille, height: taille }}>
      <svg width={taille} height={taille} className="-rotate-90" role="img"
        aria-label={parts.map((p) => `${p.label} : ${p.n}`).join(", ")}>
        <circle cx={taille / 2} cy={taille / 2} r={r} fill="none" stroke="#f1efea" strokeWidth={epaisseur} />
        {total > 0 && visibles.map((p) => {
          const long = (p.n / total) * c;
          const seg = (
            <circle
              key={p.cle}
              cx={taille / 2} cy={taille / 2} r={r} fill="none"
              stroke={p.couleur} strokeWidth={epaisseur}
              strokeDasharray={`${Math.max(0, long - ecart)} ${c}`}
              strokeDashoffset={-acc}
            >
              <title>{`${p.label} : ${p.n}`}</title>
            </circle>
          );
          acc += long;
          return seg;
        })}
      </svg>
      {centre && <div className="absolute inset-0 flex flex-col items-center justify-center text-center">{centre}</div>}
    </div>
  );
}

/* ─────────────────────────────── infobulle ─────────────────────────────── */

export interface LigneInfobulle {
  label: string;
  valeur: React.ReactNode;
  couleur?: string;
  /** Trait pointillé dans la pastille — pour une série prévisionnelle. */
  pointille?: boolean;
  /** Ligne secondaire, en retrait et en gris. */
  secondaire?: boolean;
}

/**
 * Infobulle de graphique : un titre, des lignes alignées (pastille, libellé,
 * valeur tabulaire), un pied optionnel pour le contexte (variation, effectif).
 */
export function Infobulle({
  titre, lignes, pied,
}: {
  titre: React.ReactNode;
  lignes: LigneInfobulle[];
  pied?: React.ReactNode;
}) {
  return (
    <div className="min-w-[13rem] rounded-lg border border-border bg-white px-3 py-2.5 text-xs shadow-[0_10px_30px_-10px_rgba(16,24,40,0.25)]">
      <div className="mb-1.5 font-semibold text-foreground">{titre}</div>
      <div className="space-y-1">
        {lignes.map((l) => (
          <div key={l.label} className={cn("flex items-center justify-between gap-5", l.secondaire && "pl-3.5 text-muted-foreground")}>
            <span className="flex items-center gap-1.5 text-muted-foreground">
              {l.couleur && (
                <span
                  aria-hidden
                  className="inline-block h-0 w-2.5"
                  style={{ borderTop: `2px ${l.pointille ? "dashed" : "solid"} ${l.couleur}` }}
                />
              )}
              {l.label}
            </span>
            <span className={cn("tabular-nums", l.secondaire ? "font-medium" : "font-semibold text-foreground")}>{l.valeur}</span>
          </div>
        ))}
      </div>
      {pied && <div className="mt-2 border-t border-border pt-1.5 text-muted-foreground">{pied}</div>}
    </div>
  );
}

/** Pastille de légende en trait (plein ou pointillé), pour les courbes. */
export function Legende({ items, className }: {
  items: Array<{ label: string; couleur: string; pointille?: boolean; aire?: boolean }>;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted-foreground", className)}>
      {items.map((i) => (
        <span key={i.label} className="inline-flex items-center gap-1.5">
          {i.aire ? (
            <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: i.couleur, opacity: 0.35, border: `1px solid ${i.couleur}` }} />
          ) : (
            <span aria-hidden className="inline-block w-4" style={{ borderTop: `2px ${i.pointille ? "dashed" : "solid"} ${i.couleur}` }} />
          )}
          {i.label}
        </span>
      ))}
    </div>
  );
}

/* ──────────────────────────── fraîcheur live ───────────────────────────── */

/**
 * « Actualisé il y a 12 s » — chaque écran rafraîchi en continu dit l'âge de
 * SA donnée. Au-delà de trois cadences sans réponse, le témoin passe à l'ambre :
 * un tableau figé ne se distingue pas autrement d'un tableau à jour.
 */
export function Fraicheur({
  depuis: t, cadence, className,
}: {
  depuis: number | null | undefined;
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
  const texte = age == null ? "en attente" : age < 60 ? `il y a ${age} s` : `il y a ${Math.floor(age / 60)} min`;
  return (
    <span
      className={cn("inline-flex items-center gap-1.5 whitespace-nowrap text-xs text-muted-foreground", className)}
      title="Âge de la donnée affichée — actualisation automatique"
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", perime ? "bg-amber-500" : "bg-emerald-600")} aria-hidden />
      Actualisé {texte}
    </span>
  );
}

/** Horodatage de la dernière réception d'une donnée SWR (change à chaque réponse). */
export function useRecuLe(data: unknown): number | null {
  const [t, setT] = React.useState<number | null>(null);
  React.useEffect(() => { if (data !== undefined) setT(Date.now()); }, [data]);
  return t;
}
