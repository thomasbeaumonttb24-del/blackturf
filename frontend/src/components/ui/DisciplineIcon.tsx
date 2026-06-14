/**
 * DisciplineIcon — pictogramme distinct par épreuve hippique.
 * Cheval stylisé (galop vers la droite) + élément propre à l'épreuve
 * (jockey, sulky, haie, drapeau) et badge teinté par discipline.
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

/* ── Glyphes SVG (viewBox 0 0 32 24) — cheval duotone (corps plein + détails) ── */
function Glyph({ discipline }: { discipline: string }) {
  const line = {
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.7,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };

  // Corps plein (masse → look « designé », pas filaire) : croupe, dos, encolure, tête.
  const body = (
    <path
      fill="currentColor"
      opacity="0.16"
      d="M5.6 14.2c1.7-1.9 4.3-2.8 6.9-2.4 1.4.2 2.5-.3 3.3-1.4l1.5-2c.5-.7 1.4-1 2.2-.8l1.4.4c.6.2 1 .8.9 1.4-.1.5-.5.9-1 1l-.7.1c.8.9 1.2 2 1.2 3.2 0 .5-.1 1-.2 1.5-.2.7-.9 1.2-1.6 1.2H7c-.8 0-1.5-.5-1.8-1.2-.2-.5-.2-1.1 0-1.6l.4-.1z"
    />
  );

  // Tête + encolure + naseau + oreille (contour net par-dessus la masse).
  const headNeck = (
    <>
      <path d="M5.6 14.2C7.3 12.3 9.9 11.4 12.5 11.8c1.4.2 2.5-.3 3.3-1.4l1.5-2c.5-.7 1.4-1 2.2-.8" {...line} />
      <path d="M19.5 7.6l1.6.5c.6.2.9.8.7 1.4l-.4 1.2" {...line} />
      <path d="M19.2 7.5l.4-1.6" {...line} />
      <path d="M21.4 9.5l-1.5.4" {...line} />
    </>
  );

  // Queue flottante.
  const tail = <path d="M5.6 14.2c-1.7.1-3.2.9-4.2 2.3-.5.7-.6 1.6-.3 2.5" {...line} />;

  // Jambes au galop (réutilisées).
  const galop = <path d="M8.4 16.4l-1.6 4.4M11.8 16.6l-.7 4.4M15.4 16.2l1 4.4M18.4 15.4l1.9 4.2" {...line} />;

  // Jockey (calotte pleine + buste).
  const jockey = (cx: number, cy: number) => (
    <>
      <circle cx={cx} cy={cy} r="1.7" fill="currentColor" stroke="none" />
      <path d={`M${cx - 1.4} ${cy + 1.5}c.9-.9 2.2-1 3.2-.4`} {...line} />
    </>
  );

  switch (discipline) {
    case "Plat": // galop monté — jockey ramassé
      return (
        <svg viewBox="0 0 32 24" className="h-full w-full">
          {body}{headNeck}{tail}{galop}{jockey(12.5, 8.2)}
        </svg>
      );
    case "Monté": // trot monté — cavalier plus vertical
      return (
        <svg viewBox="0 0 32 24" className="h-full w-full">
          {body}{headNeck}{tail}
          <path d="M8.6 16.4l-1 4.4M12 16.6l-.4 4.4M15.4 16.2l.8 4.4M18.6 15.6l1.4 4.4" {...line} />
          <circle cx="12.8" cy="6.6" r="1.7" fill="currentColor" stroke="none" />
          <path d="M12.8 8.3v3" {...line} />
        </svg>
      );
    case "Attelé": // trot attelé — sulky (roue + brancards) + driver
      return (
        <svg viewBox="0 0 32 24" className="h-full w-full">
          {body}{headNeck}
          <path d="M8.6 16.4l-1 4.2M12.2 16.6v4.2M15.6 16.2l.5 4.2" {...line} />
          <path d="M5.8 15.2L1.8 18M6.2 16.8L2.4 19.4" {...line} />
          <circle cx="2.6" cy="19" r="3" {...line} />
          <circle cx="2.6" cy="19" r="0.7" fill="currentColor" stroke="none" />
          <circle cx="5.6" cy="12.4" r="1.4" fill="currentColor" stroke="none" />
        </svg>
      );
    case "Haies": // saut bas — cheval en suspension + haie légère
      return (
        <svg viewBox="0 0 32 24" className="h-full w-full">
          {body}{headNeck}
          {/* jambes repliées (saut) */}
          <path d="M8.6 16l-1 3M12.2 15.6l-.5 3M15.8 15.4l.5 3M18.8 15l1 3" {...line} />
          {jockey(12.5, 8)}
          {/* haie */}
          <path d="M3 21h7M6.5 21v-3.4M4.5 18.4h4" {...line} />
        </svg>
      );
    case "Steeple": // steeple — obstacle massif
      return (
        <svg viewBox="0 0 32 24" className="h-full w-full">
          {body}{headNeck}
          <path d="M8.6 15.6l-1 3M12.2 15.2l-.4 3.2M15.8 15l.5 3.2M18.8 14.6l1 3" {...line} />
          {jockey(12.5, 7.6)}
          <path d="M2.5 21h8M4 21v-4.6M6.5 21v-4.6M9 21v-4.6M3 17.2h7" {...line} />
        </svg>
      );
    case "Cross": // cross — cheval + drapeau de jalonnement
      return (
        <svg viewBox="0 0 32 24" className="h-full w-full">
          {body}{headNeck}{tail}{galop}{jockey(12.5, 7.6)}
          <path d="M27 4.5v10" {...line} />
          <path d="M27 4.5l4 1.6-4 1.6z" fill="currentColor" stroke="none" />
        </svg>
      );
    default: // fallback — cheval au galop
      return (
        <svg viewBox="0 0 32 24" className="h-full w-full">
          {body}{headNeck}{tail}{galop}
        </svg>
      );
  }
}

/** Badge teinté contenant le pictogramme de l'épreuve (dégradé + anneau + ombre douce). */
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
      <Glyph discipline={discipline} />
    </span>
  );
}

/** Variante inline (juste le glyphe, hérite la couleur du parent). */
export function DisciplineGlyph({ discipline, className }: { discipline: string; className?: string }) {
  return (
    <span className={cn("inline-block h-4 w-5 align-middle", className)}>
      <Glyph discipline={discipline} />
    </span>
  );
}
