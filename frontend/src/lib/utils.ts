import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatCote(cote: number | null | undefined): string {
  if (!cote) return "—";
  return cote.toFixed(1);
}

export function formatEV(ev: number | null | undefined): string {
  if (ev === null || ev === undefined) return "—";
  const pct = (ev * 100).toFixed(1);
  return ev > 0 ? `+${pct}%` : `${pct}%`;
}

export function formatEuro(amount: number | null | undefined): string {
  if (amount === null || amount === undefined) return "—";
  return new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" }).format(amount);
}

export function formatDate(d: string | Date | null | undefined): string {
  if (!d) return "—";
  return new Intl.DateTimeFormat("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(new Date(d));
}

export function formatTime(d: string | Date | null | undefined): string {
  if (!d) return "—";
  return new Intl.DateTimeFormat("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(d));
}

export function formatDateTime(d: string | Date | null | undefined): string {
  if (!d) return "—";
  return new Intl.DateTimeFormat("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(d));
}

export function etoiles(niveau: number): string {
  return "⭐".repeat(Math.min(Math.max(niveau, 1), 4));
}

export function planLabel(plan: string): string {
  return {
    free: "Découverte",
    decouverte: "Découverte",
    starter: "Standard",
    standard: "Standard",
    pro: "Expert",
    expert: "Expert",
  }[plan] ?? plan;
}

export function planColor(plan: string): string {
  // Anciens noms conservés ici uniquement pour l'AFFICHAGE : le plan "pro" a été
  // supprimé du produit le 2026-08-16, mais une valeur héritée doit rester
  // colorée comme un abonné plutôt que de retomber sur le gris des comptes
  // gratuits. Ne pas s'en servir comme contrôle d'accès (cf. _normalize_plan).
  const p = plan === "starter" ? "standard" : plan === "pro" ? "expert" : plan;
  return (
    {
      free: "text-muted-foreground",
      decouverte: "text-muted-foreground",
      standard: "text-brand-gold",
      expert: "text-brand-emerald",
    }[p] ?? ""
  );
}

export function isPlanAtLeast(userPlan: string, required: "standard" | "expert"): boolean {
  const rank: Record<string, number> = { free: 0, decouverte: 0, starter: 1, standard: 1, pro: 2, expert: 2 };
  const reqRank = { standard: 1, expert: 2 }[required];
  return (rank[userPlan] ?? 0) >= reqRank;
}

export function disciplineIcon(discipline: string): string {
  return (
    {
      Plat: "🏇",
      "Attelé": "🐎",
      Monté: "🏇",
      Haies: "🚧",
      Steeple: "🚧",
      Cross: "🏞️",
    }[discipline] ?? "🏇"
  );
}

export function niveauCourseColor(niveau: string): string {
  return (
    {
      Group1: "text-brand-gold font-bold",
      Group2: "text-yellow-400",
      Group3: "text-yellow-300",
      Listed: "text-blue-400",
      Conditions: "text-muted-foreground",
      Réclamer: "text-muted-foreground",
    }[niveau] ?? ""
  );
}
