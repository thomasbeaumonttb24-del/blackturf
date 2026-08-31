import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatCote(cote: number | null | undefined): string {
  if (!cote) return "—";
  return cote.toFixed(1);
}

/**
 * Cote JUSTE (1/proba du modèle) — précision adaptée à l'ordre de grandeur.
 * À 1 décimale fixe, deux chevaux séparés de 2 % de probabilité s'affichaient au
 * même prix. Même règle que l'API (backend/services/cote_juste.py) : les deux
 * doivent rester synchronisées.
 */
export function formatCoteJuste(cote: number | null | undefined): string {
  if (!cote) return "—";
  return cote.toFixed(cote < 10 ? 2 : cote < 100 ? 1 : 0);
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

/**
 * Formate un montant dans sa devise réelle (code ISO 4217 fourni par l'API).
 *
 * Les gains de carrière viennent du PMU dans la devise LOCALE de la réunion :
 * pesos argentins à San Isidro, HKD à Sha Tin, TRY à Veliefendi… Les afficher
 * avec un « € » produisait des montants absurdes (jusqu'à 99 899 800 « € »).
 *
 * Sans devise connue on renvoie "—" : le projet interdit les chiffres inventés,
 * et un montant sans unité fiable en est un.
 */
export function formatMontantDevise(
  amount: number | null | undefined,
  devise: string | null | undefined,
): string {
  if (amount === null || amount === undefined || !devise) return "—";
  try {
    return new Intl.NumberFormat("fr-FR", {
      style: "currency",
      currency: devise,
      maximumFractionDigits: 0,
      // « € » pour l'euro (symbole universel côté public français) mais le CODE ISO
      // pour tout le reste : le symbole localisé du peso argentin est « $AR », trop
      // cryptique sur une fiche cheval. « 26 642 000 ARS » ne laisse aucun doute.
      currencyDisplay: devise === "EUR" ? "symbol" : "code",
    }).format(amount);
  } catch {
    // Code devise non reconnu par Intl → repli lisible, jamais de symbole faux
    return `${amount.toLocaleString("fr-FR")} ${devise}`;
  }
}

// Une heure de départ PMU est une heure de PARIS, pas une heure locale : sans `timeZone`
// explicite, Intl utilise le fuseau du runtime. Le conteneur serveur tourne en UTC, donc
// le HTML rendu côté serveur annonçait « 09:40 » là où le navigateur affiche « 11:40 » —
// deux dégâts : un écart d'hydratation, et une heure fausse dans la page indexée par
// Google. On fige donc Europe/Paris des deux côtés.
const TZ_PARIS = "Europe/Paris";

export function formatDate(d: string | Date | null | undefined): string {
  if (!d) return "—";
  return new Intl.DateTimeFormat("fr-FR", {
    timeZone: TZ_PARIS,
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(new Date(d));
}

export function formatTime(d: string | Date | null | undefined): string {
  if (!d) return "—";
  return new Intl.DateTimeFormat("fr-FR", {
    timeZone: TZ_PARIS,
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(d));
}

export function formatDateTime(d: string | Date | null | undefined): string {
  if (!d) return "—";
  return new Intl.DateTimeFormat("fr-FR", {
    timeZone: TZ_PARIS,
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
      standard: "text-brand-gold-dark",
      expert: "text-brand-emerald-dark",
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
      Group1: "text-brand-gold-dark font-bold",
      Group2: "text-yellow-400",
      Group3: "text-yellow-300",
      Listed: "text-blue-400",
      Conditions: "text-muted-foreground",
      Réclamer: "text-muted-foreground",
    }[niveau] ?? ""
  );
}
