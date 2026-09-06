/**
 * Charte des visuels sociaux, partagée par toutes les images générées.
 *
 * Les visuels sont produits à partir des données RÉELLES du jour : le support du Quinté+,
 * son hippodrome, son arrivée, ses rapports. Rien n'y est saisi à la main, donc rien n'y
 * est faux — et surtout, produire le post du jour ne coûte plus une minute de travail.
 *
 * Format 1080×1080 : le carré passe partout (fil Instagram, aperçu Facebook, X). Un
 * visuel par format serait plus fin, mais multiplierait la maintenance pour un gain nul
 * tant que le compte n'a pas d'audience.
 */
export const TAILLE = 1080;

export const COULEURS = {
  fond: "#101216",
  fondClair: "#1A1D23",
  encre: "#F5F4EF",
  encreDouce: "#A8ADB6",
  or: "#E2A93F",
  orVif: "#F2BE55",
  vert: "#5FBF95",
  ligne: "#2A2E36",
} as const;

/**
 * Mention légale reprise sur chaque visuel et dans chaque légende.
 *
 * BlackTurf n'est pas un opérateur de jeux : la mention n'est pas imposée au même titre
 * qu'à un opérateur agréé. Elle est portée quand même, sur tout ce qui sort du site — un
 * contenu qui parle de paris sans jamais mentionner le risque n'est pas défendable, et
 * les plateformes le sanctionnent avant l'ANJ.
 */
export const MENTION_LEGALE =
  "Jouer comporte des risques : endettement, isolement, dépendance. " +
  "09 74 75 13 13 (appel non surtaxé). Interdit aux mineurs.";

export const MENTION_COURTE = "Interdit aux mineurs. Le jeu comporte des risques.";

/** Hashtags stables. Volontairement peu nombreux : une liste de 30 mots-clés sent le spam. */
export const HASHTAGS = [
  "#PMU",
  "#courseshippiques",
  "#quinté",
  "#turf",
  "#pronostics",
  "#hippisme",
].join(" ");

/**
 * La journée demandée par un visuel, ou celle du jour.
 *
 * `?jour=AAAA-MM-JJ` N'EST PAS UN CONFORT. Les visuels de bilan se publient le
 * LENDEMAIN MATIN : les dernières courses du programme sont sud-américaines et se
 * courent jusqu'à 23 h 30, réglées une vingtaine de minutes plus tard — et le
 * rattrapage nocturne en règle encore au petit matin (165 plans le 2026-09-06 à
 * 04 h 19). Une route qui rend toujours « aujourd'hui » perd donc définitivement le
 * visuel de la veille au premier passage de minuit : le 2026-09-05 n'était déjà plus
 * récupérable au réveil.
 *
 * Une valeur mal formée est IGNORÉE au profit du jour courant, jamais rejetée : un
 * visuel qui renvoie 422 ne se publie pas, un visuel du mauvais jour se voit.
 */
export function jourDemande(url: string, defaut: string): string {
  try {
    const brut = new URL(url).searchParams.get("jour");
    if (!brut || !/^\d{4}-\d{2}-\d{2}$/.test(brut)) return defaut;
    // Contrôle de validité réel : « 2026-02-31 » passe la forme mais n'existe pas.
    const d = new Date(`${brut}T12:00:00Z`);
    if (Number.isNaN(d.getTime())) return defaut;
    return d.toISOString().slice(0, 10) === brut ? brut : defaut;
  } catch {
    return defaut;
  }
}
