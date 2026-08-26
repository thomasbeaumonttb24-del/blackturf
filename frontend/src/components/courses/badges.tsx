"use client";

/* Badges présentationnels purs de la fiche course — extraits du monolithe pour
   réutilisation (classement, partants, marché, autres pages). Aucune logique
   métier : juste de l'affichage à partir de valeurs déjà calculées. */
import { Activity } from "lucide-react";
import { cn } from "@/lib/utils";

export function ConfidenceMeter({ score, size = "md" }: { score: number; size?: "sm" | "md" }) {
  // confidence_score est déjà en pourcentage (0-100) côté backend.
  const pct = Math.round(Math.min(Math.max(score, 0), 100));
  const color = pct >= 70 ? "#10B981" : pct >= 50 ? "#F59E0B" : "#EF4444";
  return (
    <div className={cn("flex items-center gap-2", size === "sm" && "text-xs")}>
      <div className={cn("rounded-full bg-muted/50 overflow-hidden", size === "md" ? "h-2 w-24" : "h-1.5 w-16")}>
        <div className="h-full rounded-full transition-all duration-700" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="font-mono font-bold tabular-nums" style={{ color, fontSize: size === "sm" ? 10 : 12 }}>
        {pct}
      </span>
    </div>
  );
}

export function EVBadge({ ev }: { ev: number }) {
  const pct = (ev * 100).toFixed(0);
  const positive = ev > 0;
  return (
    <span className={cn(
      "inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-bold font-mono",
      positive ? "bg-brand-emerald/15 text-brand-emerald-dark" : "bg-brand-red/15 text-brand-red"
    )}>
      {positive ? "+" : ""}{pct}%
    </span>
  );
}

export function ELOBadge({ elo }: { elo: number | null }) {
  if (!elo) return <span className="text-muted-foreground text-xs">—</span>;
  const tier = elo >= 1700 ? "#F59E0B" : elo >= 1500 ? "#3B82F6" : elo >= 1300 ? "#10B981" : "#6B7280";
  return (
    <span className="font-mono font-bold text-xs tabular-nums" style={{ color: tier }}>
      {Math.round(elo)}
    </span>
  );
}

const RUNNING_STYLE_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  mene:      { label: "Mène",      color: "text-red-700",   bg: "bg-red-50 ring-red-200" },
  suit_tete: { label: "Suit tête", color: "text-orange-700", bg: "bg-orange-50 ring-orange-200" },
  placier:   { label: "Placier",   color: "text-blue-700",  bg: "bg-blue-50 ring-blue-200" },
  ferme:     { label: "Ferme",     color: "text-emerald-700", bg: "bg-emerald-50 ring-emerald-200" },
  irregulier:{ label: "Irrégulier", color: "text-gray-600", bg: "bg-gray-50 ring-gray-200" },
};
export function RunningStyleBadge({ style }: { style: string | null }) {
  if (!style) return null;
  const cfg = RUNNING_STYLE_CONFIG[style] ?? RUNNING_STYLE_CONFIG.irregulier;
  return (
    <span className={cn("inline-flex items-center rounded-full px-1.5 py-0 text-[9px] font-semibold ring-1 uppercase tracking-wide", cfg.bg, cfg.color)}>
      {cfg.label}
    </span>
  );
}

/* Musique (forme codée, max 10 perfs). Chiffre = place · lettre = discipline. */
const DISCIPLINE_MUSIQUE: Record<string, string> = {
  a: "attelé", m: "monté", p: "plat", h: "haies", s: "steeple", c: "cross", e: "épreuve",
};
export function MusiqueDisplay({ musique, plain = false }: { musique: string | null; plain?: boolean }) {
  if (!musique || !musique.trim()) {
    return <span className="text-xs text-muted-foreground">{plain ? "—" : "Aucune musique"}</span>;
  }
  const tokens = (musique.match(/\(\d{2,4}\)|[0-9A-Za-z][a-z]/g) || [])
    .filter((t) => !t.startsWith("("))
    .slice(0, 10);
  const headOf = (t: string) => t[0];
  // Variante sobre : texte mono discret, sans boîtes colorées (ligne du tableau).
  if (plain) {
    return (
      <span className="font-mono text-[11px] tracking-tight text-muted-foreground">
        {tokens.join(" ")}
      </span>
    );
  }
  const cls = (h: string) =>
    h === "1" ? "bg-amber-100 text-amber-700 ring-amber-300"
    : h === "2" || h === "3" ? "bg-blue-50 text-blue-700 ring-blue-200"
    : /[4-9]/.test(h) ? "bg-gray-100 text-gray-600 ring-gray-200"
    : "bg-rose-50 text-rose-700 ring-rose-200";
  const titleOf = (t: string) => {
    const h = headOf(t);
    const disc = DISCIPLINE_MUSIQUE[t.slice(-1).toLowerCase()];
    const place =
      h === "1" ? "Vainqueur" : h === "0" ? "Non classé (hors des places)"
      : h === "D" ? "Disqualifié" : h === "T" ? "Tombé" : h === "A" ? "Arrêté"
      : h === "R" ? "Rétrogradé / non classé" : h === "N" ? "Non partant"
      : /[2-9]/.test(h) ? `${h}ᵉ` : t;
    return disc ? `${place} · ${disc}` : place;
  };
  return (
    <div className="flex flex-wrap items-center gap-1">
      {tokens.map((t, i) => {
        const h = headOf(t);
        return (
          <span key={i} title={titleOf(t)}
            className={cn("inline-flex h-5 min-w-[1.45rem] items-center justify-center rounded px-1 text-[10px] font-bold ring-1", cls(h))}>
            {t}
          </span>
        );
      })}
    </div>
  );
}

export function PenetroBadge({ coef, desc }: { coef: number; desc: string }) {
  const color =
    coef < 3.0 ? "text-amber-700 bg-amber-50 ring-amber-200" :
    coef < 5.0 ? "text-green-700 bg-green-50 ring-green-200" :
    coef < 7.0 ? "text-blue-700 bg-blue-50 ring-blue-200" :
               "text-indigo-700 bg-indigo-50 ring-indigo-200";
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ring-1", color)}>
      🌿 {desc} ({coef.toFixed(1)})
    </span>
  );
}

export function PoolBadge({ poolEur }: { poolEur: number }) {
  const label =
    poolEur >= 1_000_000 ? `${(poolEur / 1_000_000).toFixed(1)}M€` :
    poolEur >= 1_000 ? `${Math.round(poolEur / 1_000)}k€` :
    `${poolEur}€`;
  return (
    <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold bg-violet-50 ring-1 ring-violet-200 text-violet-700">
      <Activity className="h-3 w-3" /> Pool {label}
    </span>
  );
}
