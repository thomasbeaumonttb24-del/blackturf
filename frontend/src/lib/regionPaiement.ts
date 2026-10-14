/**
 * Région de paiement probable du visiteur, déduite du fuseau horaire du navigateur.
 *
 * Pourquoi (analyse du 2026-10-14) : 12 % de l'usage réel du site vient du Maroc,
 * mais Stripe y refuse 93 % des paiements (25 refus pour 2 ventes, toujours
 * `card_declined` : la banque émettrice bloque). Une carte marocaine n'est payable
 * sur un site étranger qu'une fois la dotation « e-commerce / paiements
 * internationaux » activée. Ailleurs hors d'Europe, même logique : carte nationale
 * non utilisable à l'international, paiements en ligne à l'étranger désactivés.
 *
 * Le fuseau horaire plutôt qu'une géolocalisation IP : aucun service tiers, rien
 * à envoyer, et il suit l'appareil (un expatrié au Maroc a bien une carte
 * marocaine). DOM-TOM et Europe → `null` : rien à expliquer, les cartes passent.
 * Calculé côté client uniquement (le fuseau n'existe pas au rendu serveur).
 */

export type RegionPaiement = "maroc" | "maghreb" | "afrique" | "international";

// Outre-mer français : cartes françaises, rien à expliquer.
const FUSEAUX_FRANCE = new Set([
  "Indian/Reunion", "Indian/Mayotte", "America/Guadeloupe", "America/Martinique",
  "America/Cayenne", "America/St_Barthelemy", "America/Marigot", "America/Miquelon",
  "Pacific/Noumea", "Pacific/Tahiti", "Pacific/Marquesas", "Pacific/Gambier",
  "Pacific/Wallis",
]);

export function regionDepuisFuseau(fuseau: string | undefined | null): RegionPaiement | null {
  if (!fuseau) return null;
  if (FUSEAUX_FRANCE.has(fuseau)) return null;
  // Europe (UE, Royaume-Uni, Suisse…) : cartes acceptées sans démarche.
  // Exceptions hors espace de paiement européen : Russie, Biélorussie, Turquie.
  if (fuseau.startsWith("Europe/") || fuseau.startsWith("Atlantic/Canary") || fuseau.startsWith("Atlantic/Madeira")
      || fuseau.startsWith("Atlantic/Azores")) {
    const horsEurope = ["Europe/Moscow", "Europe/Minsk", "Europe/Istanbul", "Europe/Volgograd",
      "Europe/Kirov", "Europe/Samara", "Europe/Saratov", "Europe/Ulyanovsk", "Europe/Astrakhan"];
    return horsEurope.includes(fuseau) ? "international" : null;
  }
  if (fuseau === "Africa/Casablanca" || fuseau === "Africa/El_Aaiun") return "maroc";
  if (fuseau === "Africa/Algiers" || fuseau === "Africa/Tunis") return "maghreb";
  if (fuseau.startsWith("Africa/")) return "afrique";
  // Ni Europe ni Afrique : ailleurs dans le monde. `Etc/UTC` et consorts (VPN,
  // machines mal réglées) ne disent rien : on s'abstient.
  if (fuseau.startsWith("Etc/") || fuseau === "UTC") return null;
  return "international";
}

export function regionPaiement(): RegionPaiement | null {
  try {
    return regionDepuisFuseau(Intl.DateTimeFormat().resolvedOptions().timeZone);
  } catch {
    return null;
  }
}
