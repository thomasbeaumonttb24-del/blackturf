/**
 * DisciplineIcon — pictogramme cheval (silhouette réaliste) par épreuve.
 * Même cheval réaliste, teinté à la couleur de la discipline (repérage immédiat).
 * Silhouette : Material Design Icons « horse » (Pictogrammers, licence Apache 2.0).
 */
import { cn } from "@/lib/utils";

export type DisciplineKey =
  | "Plat" | "Attelé" | "Monté" | "Haies" | "Steeple" | "Cross" | string;

/* Couleur + libellé court par discipline */
export const DISCIPLINE_META: Record<string, { color: string; bg: string; ring: string; short: string }> = {
  Plat:    { color: "#B45309", bg: "bg-amber-50",   ring: "ring-amber-200",   short: "Plat" },
  "Attelé":{ color: "#047857", bg: "bg-emerald-50", ring: "ring-emerald-200", short: "Attelé" },
  Monté:   { color: "#1D4ED8", bg: "bg-blue-50",    ring: "ring-blue-200",    short: "Monté" },
  Haies:   { color: "#C2410C", bg: "bg-orange-50",  ring: "ring-orange-200",  short: "Haies" },
  Steeple: { color: "#B91C1C", bg: "bg-red-50",     ring: "ring-red-200",     short: "Steeple" },
  Cross:   { color: "#15803D", bg: "bg-green-50",   ring: "ring-green-200",   short: "Cross" },
};

export function disciplineMeta(d: string) {
  return DISCIPLINE_META[d] ?? { color: "#6B7280", bg: "bg-gray-100", ring: "ring-gray-200", short: d };
}

/* Silhouette de cheval réaliste (viewBox 24, fill currentColor). */
const HORSE_D =
  "M22 6v3.5l-1.5.5l-1.54-2.46c-.13-.21-.46-.12-.46.13v3.58c0 .98-.39 1.86-1 2.53V21H15v-6h-.25c-.21 0-.42-.03-.62-.06l-4.44-.74l-1.12 2.01l.96 4.79H7l-1-4.75c-.03-.3 0-.6.16-.86l1.02-1.81a3.27 3.27 0 0 1-1.68-2.77c-.04.15-.06.37-.03.69c.03.44.14 1.09.07 1.81c-.04.72-.37 1.46-.79 1.95c-.43.49-.9.83-1.4 1.09l-.7-.7c.19-.47.38-.89.42-1.28c.06-.37-.01-.67-.12-.94l-.53-1.13c-.21-.51-.47-1.25-.42-2.12c.03-.85.5-1.96 1.39-2.57c.9-.61 1.87-.69 2.66-.53c.5.1 1.01.34 1.45.68c.37-.17.8-.26 1.25-.26h5.75V7c0-2.21 1.79-4 4-4H22l-.89 1.34c.54.36.89.97.89 1.66";

function HorseGlyph({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="currentColor" aria-hidden="true">
      <path d={HORSE_D} />
    </svg>
  );
}

/** Badge teinté contenant le cheval (dégradé + anneau + ombre douce). */
export function DisciplineIcon({
  discipline, size = "md", className,
}: { discipline: string; size?: "sm" | "md" | "lg"; className?: string }) {
  const m = disciplineMeta(discipline);
  const box = size === "sm" ? "h-6 w-6 p-1" : size === "lg" ? "h-10 w-10 p-2" : "h-8 w-8 p-1.5";
  return (
    <span
      className={cn(
        "inline-flex items-center justify-center rounded-xl ring-1 shadow-sm flex-shrink-0",
        m.ring, box, className,
      )}
      style={{
        color: m.color,
        background: `linear-gradient(135deg, ${m.color}1f, ${m.color}08)`,
      }}
      title={discipline}
      aria-label={discipline}
    >
      <HorseGlyph className="h-full w-full" />
    </span>
  );
}

/** Variante inline (juste le cheval, hérite la couleur du parent). */
export function DisciplineGlyph({ className }: { discipline?: string; className?: string }) {
  return <HorseGlyph className={cn("inline-block align-middle h-4 w-4", className)} />;
}
