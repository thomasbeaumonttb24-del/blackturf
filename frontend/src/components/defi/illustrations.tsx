/**
 * Illustrations vectorielles du Défi du mois : médaille, trophée, laurier, décor.
 * Tout est en SVG inline (net à toutes les tailles, aucun fichier à charger) et
 * reste dans la palette du site : crème, or, ambre, avec des reflets métalliques.
 */
import { useId } from "react";
import { cn } from "@/lib/utils";

/** Médaille or à ruban : l'emblème du défi. */
export function MedailleSvg({ taille = 44, className }: { taille?: number; className?: string }) {
  const id = useId().replace(/:/g, "");
  return (
    <svg width={taille} height={taille} viewBox="0 0 64 64" className={cn("shrink-0 drop-shadow-[0_6px_10px_rgba(180,83,9,.28)]", className)} aria-hidden="true">
      <defs>
        <linearGradient id={`r${id}`} x1="0" x2="1">
          <stop offset="0" stopColor="#B91C1C" /><stop offset=".5" stopColor="#E11D48" /><stop offset="1" stopColor="#9F1239" />
        </linearGradient>
        <radialGradient id={`o${id}`} cx=".35" cy=".3" r=".8">
          <stop offset="0" stopColor="#FFF7D6" /><stop offset=".35" stopColor="#FCD34D" /><stop offset=".75" stopColor="#D97706" /><stop offset="1" stopColor="#92400E" />
        </radialGradient>
        <linearGradient id={`b${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#FDE68A" /><stop offset="1" stopColor="#B45309" />
        </linearGradient>
      </defs>
      <path d="M20 2h10l6 20h-10z" fill={`url(#r${id})`} />
      <path d="M44 2H34l-6 20h10z" fill={`url(#r${id})`} opacity=".92" />
      <path d="M24 2h3l5 17h-3z" fill="#fff" opacity=".35" />
      <circle cx="32" cy="40" r="20" fill={`url(#b${id})`} />
      <circle cx="32" cy="40" r="17" fill={`url(#o${id})`} />
      <circle cx="32" cy="40" r="13" fill="none" stroke="#FEF3C7" strokeOpacity=".7" strokeWidth="1.2" strokeDasharray="2 2.4" />
      <path d="M32 31.5l2.7 5.5 6 .9-4.35 4.25 1.03 6-5.38-2.83-5.38 2.83 1.03-6-4.35-4.25 6-.9z" fill="#FFFBEB" stroke="#B45309" strokeWidth=".8" strokeLinejoin="round" />
      <ellipse cx="25" cy="31" rx="6" ry="3" fill="#fff" opacity=".45" transform="rotate(-30 25 31)" />
    </svg>
  );
}

/** Trophée sur socle, avec reflets : illustration de l'en-tête de la page. */
export function TropheeSvg({ className }: { className?: string }) {
  const id = useId().replace(/:/g, "");
  return (
    <svg viewBox="0 0 200 200" className={cn("drop-shadow-[0_24px_30px_rgba(180,83,9,.25)]", className)} aria-hidden="true">
      <defs>
        <linearGradient id={`c${id}`} x1="0" x2="1">
          <stop offset="0" stopColor="#B45309" /><stop offset=".22" stopColor="#FCD34D" /><stop offset=".45" stopColor="#FFF7D6" />
          <stop offset=".62" stopColor="#F59E0B" /><stop offset="1" stopColor="#92400E" />
        </linearGradient>
        <linearGradient id={`s${id}`} x1="0" x2="1">
          <stop offset="0" stopColor="#44403C" /><stop offset=".5" stopColor="#78716C" /><stop offset="1" stopColor="#292524" />
        </linearGradient>
        <linearGradient id={`p${id}`} x1="0" x2="1">
          <stop offset="0" stopColor="#D6D3D1" /><stop offset=".5" stopColor="#FAFAF9" /><stop offset="1" stopColor="#A8A29E" />
        </linearGradient>
        <radialGradient id={`h${id}`} cx=".5" cy=".5" r=".5">
          <stop offset="0" stopColor="#FDE68A" stopOpacity=".9" /><stop offset="1" stopColor="#FDE68A" stopOpacity="0" />
        </radialGradient>
      </defs>
      <circle cx="100" cy="86" r="82" fill={`url(#h${id})`} />
      {/* anses */}
      <path d="M58 52c-26 0-30 42 8 52" fill="none" stroke={`url(#c${id})`} strokeWidth="9" strokeLinecap="round" />
      <path d="M142 52c26 0 30 42-8 52" fill="none" stroke={`url(#c${id})`} strokeWidth="9" strokeLinecap="round" />
      {/* coupe */}
      <path d="M52 40h96c0 44-18 74-48 78-30-4-48-34-48-78z" fill={`url(#c${id})`} />
      <path d="M52 40h96v8H52z" fill="#FFF7D6" opacity=".55" />
      <path d="M68 50c2 26 10 44 22 54" fill="none" stroke="#fff" strokeOpacity=".55" strokeWidth="5" strokeLinecap="round" />
      {/* étoile */}
      <path d="M100 58l5.8 11.8 13 1.9-9.4 9.2 2.2 12.9-11.6-6.1-11.6 6.1 2.2-12.9-9.4-9.2 13-1.9z" fill="#FFFBEB" stroke="#B45309" strokeWidth="1.5" strokeLinejoin="round" />
      {/* pied */}
      <path d="M92 118h16l4 22H88z" fill={`url(#c${id})`} />
      <rect x="74" y="140" width="52" height="10" rx="3" fill={`url(#c${id})`} />
      <rect x="62" y="150" width="76" height="26" rx="5" fill={`url(#s${id})`} />
      <rect x="76" y="157" width="48" height="12" rx="2" fill={`url(#p${id})`} />
      <rect x="62" y="150" width="76" height="3" rx="1.5" fill="#fff" opacity=".18" />
    </svg>
  );
}

/** Couronne de laurier (encadre l'avatar du 1er). */
export function LaurierSvg({ className }: { className?: string }) {
  const feuille = (x: number, y: number, r: number, k: number) => (
    <ellipse key={k} cx={x} cy={y} rx="3.4" ry="7.5" transform={`rotate(${r} ${x} ${y})`} />
  );
  const gauche = [[16, 56, -20], [11, 46, -38], [9, 35, -58], [11, 24, -80], [17, 15, -102], [25, 9, -124]];
  return (
    <svg viewBox="0 0 100 70" className={className} aria-hidden="true">
      <g fill="#D97706" opacity=".9">
        {gauche.map(([x, y, r], i) => feuille(x, y, r, i))}
        {gauche.map(([x, y, r], i) => feuille(100 - x, y, -r, i + 10))}
      </g>
      <g fill="#FCD34D" opacity=".55">
        {gauche.map(([x, y, r], i) => <ellipse key={i} cx={x - 0.8} cy={y - 1} rx="1.3" ry="4.5" transform={`rotate(${r} ${x} ${y})`} />)}
      </g>
    </svg>
  );
}

/** Décor d'en-tête : rayons dorés + trame de points, en filigrane. */
export function DecorRayons({ className }: { className?: string }) {
  const id = useId().replace(/:/g, "");
  return (
    <svg className={cn("pointer-events-none absolute inset-0 h-full w-full", className)} preserveAspectRatio="xMaxYMin slice" viewBox="0 0 400 240" aria-hidden="true">
      <defs>
        <radialGradient id={`g${id}`} cx="1" cy="0" r="1">
          <stop offset="0" stopColor="#F59E0B" stopOpacity=".22" /><stop offset=".6" stopColor="#F59E0B" stopOpacity="0" />
        </radialGradient>
        <pattern id={`d${id}`} width="12" height="12" patternUnits="userSpaceOnUse">
          <circle cx="1.5" cy="1.5" r="1" fill="#B45309" opacity=".09" />
        </pattern>
      </defs>
      <rect width="400" height="240" fill={`url(#d${id})`} />
      <g transform="translate(400 0)" fill="#F59E0B" opacity=".07">
        {Array.from({ length: 14 }).map((_, i) => (
          <path key={i} d="M0 0L-420 -26L-420 26Z" transform={`rotate(${90 + i * 13})`} />
        ))}
      </g>
      <rect width="400" height="240" fill={`url(#g${id})`} />
    </svg>
  );
}
