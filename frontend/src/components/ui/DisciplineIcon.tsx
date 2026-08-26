/**
 * DisciplineIcon — pictogramme distinct par épreuve hippique.
 * Chaque discipline a sa propre scène (galop, sulky, cavalier, saut, terrain)
 * + sa couleur, pour un repérage immédiat dans le programme.
 */
import { cn } from "@/lib/utils";

export type DisciplineKey =
  | "Plat" | "Attelé" | "Monté" | "Haies" | "Steeple" | "Cross" | string;

/* Couleur + libellé court par discipline */
export const DISCIPLINE_META: Record<string, { color: string; bg: string; ring: string; short: string }> = {
  Plat:    { color: "#B45309", bg: "bg-amber-50",   ring: "ring-amber-200",   short: "Plat" },
  "Attelé":{ color: "#047857", bg: "bg-emerald-50", ring: "ring-emerald-200", short: "Attelé" },
  Monté:   { color: "#1D4ED8", bg: "bg-blue-50",    ring: "ring-blue-200",    short: "Monté" },
  Obstacle:{ color: "#C2410C", bg: "bg-orange-50",  ring: "ring-orange-200",  short: "Obstacle" },
  Haies:   { color: "#C2410C", bg: "bg-orange-50",  ring: "ring-orange-200",  short: "Haies" },
  Steeple: { color: "#B91C1C", bg: "bg-red-50",     ring: "ring-red-200",     short: "Steeple" },
  Cross:   { color: "#15803D", bg: "bg-green-50",   ring: "ring-green-200",   short: "Cross" },
};

/** Normalise la casse venant de la base ("OBSTACLE" → "Obstacle") pour matcher les clés. */
const normDiscipline = (d: string) =>
  d ? d.charAt(0).toUpperCase() + d.slice(1).toLowerCase() : d;

export function disciplineMeta(d: string) {
  const k = normDiscipline(d);
  return DISCIPLINE_META[k] ?? { color: "#6B7280", bg: "bg-gray-100", ring: "ring-gray-200", short: k };
}

/* Silhouettes détourées par discipline (masques transparents). */
const DISCIPLINE_IMG: Record<string, string> = {
  Plat:      "/img/disciplines/plat-v5.png",
  "Attelé":  "/img/disciplines/attele-v5.png",
  Monté:     "/img/disciplines/monte-v5.png",
  Obstacle:  "/img/disciplines/obstacle-v5.png",
  Haies:     "/img/disciplines/obstacle-v5.png",
  Steeple:   "/img/disciplines/obstacle-v5.png",
  Cross:     "/img/disciplines/obstacle-v5.png",
};

/** Silhouette teintée : le PNG sert de masque, la couleur vient de la discipline. */
function Silhouette({ url, color, className }: { url: string; color: string; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={className}
      style={{
        display: "inline-block",
        background: color,
        WebkitMask: `url(${url}) center/contain no-repeat`,
        mask: `url(${url}) center/contain no-repeat`,
      }}
    />
  );
}

/* ── Glyphes SVG (viewBox 0 0 32 24), trait = currentColor ── */
function Glyph({ discipline }: { discipline: string }) {
  const common = {
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  // Corps + tête de cheval réutilisés (profil galopant vers la droite)
  const horse = (
    <>
      {/* corps */}
      <path d="M7 14c1.5-2 4-3 7-2.5 1.5.3 2.5-.2 3.2-1.1l1.6-2c.4-.5 1-.7 1.6-.5l1.2.4" {...common} />
      {/* encolure + tête */}
      <path d="M21.2 8.3c.9.3 1.6 1 1.9 1.9l.5 1.5" {...common} />
      {/* croupe */}
      <path d="M7 14c-.6 1-.8 2-.6 3" {...common} />
    </>
  );

  switch (discipline) {
    case "Plat": // galop monté — jambes étendues + jockey ramassé
      return (
        <svg viewBox="0 0 32 24" className="h-full w-full">
          {horse}
          {/* jambes étendues (galop) */}
          <path d="M9 14l-3 5M13 14l-2 5M17.5 13l1.5 5M20.5 12l2.5 4.5" {...common} />
          {/* jockey ramassé */}
          <circle cx="13" cy="8.5" r="1.6" fill="currentColor" stroke="none" />
          <path d="M11.6 10c1-1 2.4-1.2 3.6-.6" {...common} />
        </svg>
      );
    case "Monté": // trot monté — cheval plus dressé + cavalier vertical
      return (
        <svg viewBox="0 0 32 24" className="h-full w-full">
          {horse}
          <path d="M9 14l-1.5 5M13 14l-.5 5M17.5 13l1 5M21 12l1.8 5" {...common} />
          {/* cavalier vertical */}
          <circle cx="13.5" cy="6.5" r="1.6" fill="currentColor" stroke="none" />
          <path d="M13.5 8.2v3" {...common} />
        </svg>
      );
    case "Attelé": // trot attelé — sulky (roue) + driver derrière
      return (
        <svg viewBox="0 0 32 24" className="h-full w-full">
          {horse}
          <path d="M9 14l-1 5M12.5 14v5M16.5 13l.5 5" {...common} />
          {/* brancards du sulky */}
          <path d="M6.5 14.5L2.5 17M6.8 16L3 18.5" {...common} />
          {/* roue */}
          <circle cx="3.5" cy="18.5" r="3" {...common} />
          <circle cx="3.5" cy="18.5" r="0.6" fill="currentColor" stroke="none" />
          {/* driver assis bas */}
          <circle cx="6" cy="11.5" r="1.3" fill="currentColor" stroke="none" />
        </svg>
      );
    case "Haies": // saut d'obstacle bas — cheval en arc au-dessus d'une haie
      return (
        <svg viewBox="0 0 32 24" className="h-full w-full">
          {/* cheval en arc */}
          <path d="M6 16c2-4 6-6 10-5 2 .5 3.2-.2 4.2-1.4l1.4-1.7c.4-.5 1-.6 1.6-.4" {...common} />
          <path d="M22 9.6c.9.3 1.5 1 1.8 1.9" {...common} />
          {/* jambes repliées (saut) */}
          <path d="M8.5 13l-1 3M12 11.5l-.5 3M16 11l.5 3M19.5 10.5l1 3" {...common} />
          {/* haie */}
          <path d="M4 20h7M7.5 20v-3.5M5.5 17.5h4" {...common} />
        </svg>
      );
    case "Steeple": // steeple — saut d'une barre haute (obstacle massif)
      return (
        <svg viewBox="0 0 32 24" className="h-full w-full">
          <path d="M6 15c2-5 7-7 11-5.5 1.8.7 3-.1 4-1.4l1.2-1.6c.4-.5 1-.6 1.6-.4" {...common} />
          <path d="M23 6.5c.9.3 1.5 1 1.8 1.9" {...common} />
          <path d="M9 12l-1 3M12.5 10.5l-.5 3.5M16.5 10l.5 3.5M20 9.5l1 3" {...common} />
          {/* obstacle massif (haie de steeple) */}
          <path d="M3 20h8M4.5 20v-5M7 20v-5M9.5 20v-5M3.5 16h7" {...common} />
        </svg>
      );
    case "Cross": // cross-country — cheval + drapeau/terrain
      return (
        <svg viewBox="0 0 32 24" className="h-full w-full">
          {horse}
          <path d="M9 14l-1.5 4.5M13 14l-1 4.5M17.5 13l1 4.5M21 12l1.5 4.5" {...common} />
          <circle cx="13" cy="7.5" r="1.5" fill="currentColor" stroke="none" />
          {/* drapeau de jalonnement */}
          <path d="M27 5v9" {...common} />
          <path d="M27 5l4 1.5-4 1.5z" fill="currentColor" stroke="none" />
          {/* relief */}
          <path d="M2 20c3-1.5 6-1.5 9 0" {...common} />
        </svg>
      );
    default: // fallback — cheval simple
      return (
        <svg viewBox="0 0 32 24" className="h-full w-full">
          {horse}
          <path d="M9 14l-1.5 5M13 14l-1 5M17.5 13l1 5M21 12l1.5 5" {...common} />
        </svg>
      );
  }
}

/** Badge carré coloré contenant le pictogramme de l'épreuve. */
export function DisciplineIcon({
  discipline, size = "md", className,
}: { discipline: string; size?: "sm" | "md" | "lg"; className?: string }) {
  const k = normDiscipline(discipline);
  const m = disciplineMeta(discipline);
  const img = DISCIPLINE_IMG[k];
  const box = size === "sm" ? "h-6 w-8 p-[3px]" : size === "lg" ? "h-10 w-14 p-1.5" : "h-8 w-11 p-1";
  return (
    <span
      className={cn(
        "inline-flex items-center justify-center rounded-lg ring-1 flex-shrink-0",
        img ? "bg-white" : m.bg,
        m.ring, box, className,
      )}
      style={{ color: m.color }}
      title={discipline}
      aria-label={discipline}
    >
      {img ? (
        <Silhouette url={img} color={m.color} className="h-full w-full" />
      ) : (
        <Glyph discipline={k} />
      )}
    </span>
  );
}

/** Variante inline (juste le glyphe, hérite la couleur du parent). */
export function DisciplineGlyph({ discipline, className }: { discipline: string; className?: string }) {
  return (
    <span className={cn("inline-block h-4 w-5 align-middle", className)}>
      <Glyph discipline={normDiscipline(discipline)} />
    </span>
  );
}

/** Logo PNG nu (sans cadre) pour usage inline — ex. chips de filtre. Fallback glyphe. */
export function DisciplineImg({ discipline, className }: { discipline: string; className?: string }) {
  const k = normDiscipline(discipline);
  const img = DISCIPLINE_IMG[k];
  if (!img) {
    return (
      <span className={cn("inline-block align-middle", className)} style={{ color: disciplineMeta(discipline).color }}>
        <Glyph discipline={k} />
      </span>
    );
  }
  return <Silhouette url={img} color={disciplineMeta(discipline).color} className={cn("align-middle", className)} />;
}
