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
