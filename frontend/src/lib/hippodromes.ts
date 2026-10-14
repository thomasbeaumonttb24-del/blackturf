// Données éditoriales des principaux hippodromes français (evergreen, faits vérifiés).
// Règle d'intégrité : aucune course « signature » inventée — laissée vide si incertaine.
export interface Hippodrome {
  slug: string;
  name: string; // nom usuel
  city: string;
  region: string;
  disciplines: string[]; // Plat / Trot / Obstacle
  signature?: string; // course phare confirmée
  intro: string; // 2-3 phrases evergreen
  // termes apparaissant dans hippodrome_nom de l'API PMU (uppercase), pour rattacher les courses du jour
  match: string[];
}

export const HIPPODROMES: Hippodrome[] = [
  {
    slug: "vincennes",
    name: "Hippodrome de Vincennes",
    city: "Paris",
    region: "Île-de-France",
    disciplines: ["Trot"],
    signature: "Prix d'Amérique",
    intro:
      "Surnommé le « temple du trot », Vincennes accueille les plus grandes courses de trot attelé et monté, dont le mythique Prix d'Amérique en janvier. Sa piste exigeante en fait une référence mondiale de la discipline.",
    match: ["VINCENNES"],
  },
  {
    slug: "paris-longchamp",
    name: "Hippodrome ParisLongchamp",
    city: "Paris",
    region: "Île-de-France",
    disciplines: ["Plat"],
    signature: "Prix de l'Arc de Triomphe",
    intro:
      "Écrin du plat parisien, ParisLongchamp accueille chaque automne le Prix de l'Arc de Triomphe, l'une des courses les plus prestigieuses du monde. Un cadre de référence pour les meilleurs galopeurs.",
    match: ["LONGCHAMP", "PARISLONGCHAMP", "PARIS LONGCHAMP"],
  },
  {
    slug: "chantilly",
    name: "Hippodrome de Chantilly",
    city: "Chantilly",
    region: "Hauts-de-France",
    disciplines: ["Plat"],
    signature: "Prix du Jockey Club et Prix de Diane",
    intro:
      "Capitale française de l'entraînement, Chantilly accueille deux classiques majeurs du plat : le Prix du Jockey Club et le Prix de Diane. Un hippodrome d'exception au cœur d'un domaine historique.",
    match: ["CHANTILLY"],
  },
  {
    slug: "deauville",
    name: "Hippodrome de Deauville",
    city: "Deauville",
    region: "Normandie",
    disciplines: ["Plat", "Obstacle"],
    intro:
      "Rendez-vous estival incontournable, Deauville propose un meeting d'été très relevé sur le plat, doublé de ventes de yearlings réputées. La piste normande attire les meilleures écuries.",
    match: ["DEAUVILLE"],
  },
  {
    slug: "auteuil",
    name: "Hippodrome d'Auteuil",
    city: "Paris",
    region: "Île-de-France",
    disciplines: ["Obstacle"],
    signature: "Grand Steeple-Chase de Paris",
    intro:
      "Référence de l'obstacle en France, Auteuil accueille le Grand Steeple-Chase de Paris. Haies et steeple s'y disputent sur l'un des parcours les plus techniques du calendrier.",
    match: ["AUTEUIL"],
  },
  {
    slug: "saint-cloud",
    name: "Hippodrome de Saint-Cloud",
    city: "Saint-Cloud",
    region: "Île-de-France",
    disciplines: ["Plat"],
    signature: "Grand Prix de Saint-Cloud",
    intro:
      "Aux portes de Paris, Saint-Cloud est un hippodrome de plat réputé pour la qualité de sa piste et son Grand Prix éponyme, étape importante pour les chevaux d'âge.",
    match: ["SAINT-CLOUD", "SAINT CLOUD", "ST-CLOUD"],
  },
  {
    slug: "enghien",
    name: "Hippodrome d'Enghien-Soisy",
    city: "Soisy-sous-Montmorency",
    region: "Île-de-France",
    disciplines: ["Trot", "Obstacle"],
    intro:
      "Proche de Paris, Enghien combine trot et obstacle dans un cadre compact. Ses réunions nocturnes et son public fidèle en font un hippodrome animé de la région parisienne.",
    match: ["ENGHIEN"],
  },
  {
    slug: "cagnes-sur-mer",
    name: "Hippodrome de Cagnes-sur-Mer",
    city: "Cagnes-sur-Mer",
    region: "Provence-Alpes-Côte d'Azur",
    disciplines: ["Plat", "Trot"],
    intro:
      "Sur la Côte d'Azur, Cagnes-sur-Mer accueille un meeting d'hiver mêlant plat et trot, profitant d'un climat doux qui attire chevaux et parieurs de toute l'Europe.",
    match: ["CAGNES"],
  },
  {
    slug: "maisons-laffitte",
    name: "Hippodrome de Maisons-Laffitte",
    city: "Maisons-Laffitte",
    region: "Île-de-France",
    disciplines: ["Plat"],
    intro:
      "Connu pour sa longue ligne droite, Maisons-Laffitte est un hippodrome de plat historique des Yvelines, longtemps lié à un important centre d'entraînement.",
    match: ["MAISONS-LAFFITTE", "MAISONS LAFFITTE"],
  },
  {
    slug: "vichy",
    name: "Hippodrome de Vichy",
    city: "Vichy",
    region: "Auvergne-Rhône-Alpes",
    disciplines: ["Plat", "Trot"],
    intro:
      "Vichy propose un meeting d'été apprécié, alternant plat et trot. Son cadre thermal et ses réunions estivales en font une étape prisée du calendrier.",
    match: ["VICHY"],
  },
  {
    slug: "toulouse",
    name: "Hippodrome de Toulouse",
    city: "Toulouse",
    region: "Occitanie",
    disciplines: ["Plat", "Obstacle", "Trot"],
    intro:
      "Grand hippodrome du Sud-Ouest, Toulouse accueille les trois disciplines et constitue un pôle majeur des courses dans la région, notamment durant la saison hivernale.",
    match: ["TOULOUSE"],
  },
  {
    slug: "marseille-borely",
    name: "Hippodrome Marseille-Borély",
    city: "Marseille",
    region: "Provence-Alpes-Côte d'Azur",
    disciplines: ["Plat"],
    intro:
      "Au bord de la Méditerranée, Marseille-Borély est dédié au plat. Son cadre et son climat en font un hippodrome agréable et actif du Sud-Est.",
    match: ["BORELY", "MARSEILLE-BORELY", "MARSEILLE BORELY"],
  },
  {
    slug: "pau",
    name: "Hippodrome de Pau",
    city: "Pau",
    region: "Nouvelle-Aquitaine",
    disciplines: ["Plat", "Obstacle"],
    intro:
      "Pau accueille un réputé meeting d'hiver mêlant plat et obstacle, profitant d'un climat clément qui attire de nombreuses écuries en début d'année.",
    match: ["PAU"],
  },
  {
    slug: "compiegne",
    name: "Hippodrome de Compiègne",
    city: "Compiègne",
    region: "Hauts-de-France",
    disciplines: ["Plat", "Obstacle"],
    intro:
      "En lisière de forêt, Compiègne est un hippodrome de plat et d'obstacle proche de la région parisienne, support régulier de réunions de qualité.",
    match: ["COMPIEGNE", "COMPIÈGNE"],
  },
  {
    slug: "cabourg",
    name: "Hippodrome de Cabourg",
    city: "Cabourg",
    region: "Normandie",
    disciplines: ["Trot"],
    intro:
      "Hippodrome normand dédié au trot, Cabourg anime la saison estivale avec des réunions populaires à deux pas de la plage.",
    match: ["CABOURG"],
  },
  {
    slug: "le-croise-laroche",
    name: "Hippodrome du Croisé-Laroche",
    city: "Marcq-en-Barœul",
    region: "Hauts-de-France",
    disciplines: ["Trot"],
    intro:
      "Près de Lille, Le Croisé-Laroche est un hippodrome de trot très actif du Nord, support de nombreuses réunions tout au long de l'année.",
    match: ["CROISE-LAROCHE", "CROISÉ-LAROCHE", "CROISE LAROCHE"],
  },
  /* Ajoutés le 2026-10-14 : supports réguliers du Quinté+ qui n'avaient pas de fiche, si
   * bien que leurs courses ne pouvaient lier vers aucune page de lieu. Faits recoupés
   * sur plusieurs sources (offices de tourisme, LeTrot, presse hippique) ; ce qui ne
   * l'était pas (dotations, courses « phares ») a été laissé de côté. */
  {
    slug: "caen",
    name: "Hippodrome de Caen",
    city: "Caen",
    region: "Normandie",
    disciplines: ["Trot"],
    intro:
      "Installé dans la prairie caennaise, l'hippodrome de Caen est consacré au trot, attelé et monté, sur une piste en sable. Il accueille régulièrement des réunions PMU, dont des supports du Quinté+.",
    match: ["CAEN"],
  },
  {
    slug: "lyon-parilly",
    name: "Hippodrome de Lyon-Parilly",
    city: "Bron",
    region: "Auvergne-Rhône-Alpes",
    disciplines: ["Plat", "Obstacle", "Trot"],
    intro:
      "Ouvert en 1965 dans le parc de Parilly, à Bron, l'hippodrome de Lyon-Parilly accueille les trois disciplines : le plat et l'obstacle sur herbe, le trot sur une piste en pouzzolane. Ses réunions se concentrent au printemps et à l'automne.",
    match: ["PARILLY"],
  },
  {
    slug: "clairefontaine",
    name: "Hippodrome de Deauville-Clairefontaine",
    city: "Tourgéville",
    region: "Normandie",
    disciplines: ["Plat", "Obstacle", "Trot"],
    intro:
      "Aux portes de Deauville, l'hippodrome de Clairefontaine accueille plat, obstacle et trot. Sa saison, de l'été à l'automne, en fait l'un des rendez-vous de la côte normande.",
    match: ["CLAIREFONTAINE"],
  },
  {
    slug: "nantes",
    name: "Hippodrome de Nantes",
    city: "Nantes",
    region: "Pays de la Loire",
    disciplines: ["Plat", "Obstacle", "Trot"],
    intro:
      "Implanté dans le quartier du Petit Port depuis 1875, l'hippodrome de Nantes accueille le plat et l'obstacle sur herbe, et le trot sur une piste en pouzzolane.",
    match: ["NANTES"],
  },
  {
    slug: "bordeaux-le-bouscat",
    name: "Hippodrome de Bordeaux-Le Bouscat",
    city: "Le Bouscat",
    region: "Nouvelle-Aquitaine",
    disciplines: ["Plat", "Obstacle", "Trot"],
    intro:
      "Aux portes de Bordeaux, l'hippodrome du Bouscat réunit les trois disciplines : une piste de plat en herbe, des parcours de haies et de steeple-chase, et une piste de trot en sable.",
    match: ["BOUSCAT"],
  },
  {
    slug: "strasbourg",
    name: "Hippodrome de Strasbourg-Hoerdt",
    city: "Hoerdt",
    region: "Grand Est",
    disciplines: ["Trot", "Plat", "Obstacle"],
    intro:
      "Au nord de Strasbourg, l'hippodrome de Hoerdt accueille le trot, le plat et l'obstacle, cross-country compris, sur des pistes distinctes pour chaque discipline.",
    match: ["STRASBOURG", "HOERDT"],
  },
  {
    slug: "laval",
    name: "Hippodrome de Laval",
    city: "Laval",
    region: "Pays de la Loire",
    disciplines: ["Trot"],
    intro:
      "Ouvert en 1985 à Bellevue-la-Forêt, à quelques minutes du centre de Laval, l'hippodrome est entièrement consacré au trot. Il accueille chaque année une étape du Grand National du Trot.",
    match: ["LAVAL"],
  },
  {
    slug: "marseille-vivaux",
    name: "Hippodrome de Marseille-Vivaux",
    city: "Marseille",
    region: "Provence-Alpes-Côte d'Azur",
    disciplines: ["Trot", "Plat"],
    intro:
      "Dans le 10e arrondissement de Marseille, l'hippodrome de Pont-de-Vivaux accueille des réunions de trot et de plat tout au long de l'année, dont des réunions estivales en soirée.",
    match: ["VIVAUX"],
  },
  {
    slug: "le-lion-d-angers",
    name: "Hippodrome du Lion-d'Angers",
    city: "Le Lion-d'Angers",
    region: "Pays de la Loire",
    disciplines: ["Plat", "Obstacle"],
    intro:
      "Niché dans le parc de l'Isle-Briand, l'hippodrome du Lion-d'Angers accueille une douzaine de réunions par an, en plat et en obstacle. Il est réputé pour son parcours de cross-country.",
    match: ["LION D", "LION-D"],
  },
];

export function getHippodrome(slug: string): Hippodrome | undefined {
  return HIPPODROMES.find((h) => h.slug === slug);
}

/** Le nom sans « Hippodrome », mais AVEC son article : « de Vincennes », « du
 *  Croisé-Laroche », « d'Auteuil ». Écrit pour être collé derrière « la piste » — « la
 *  piste de Croisé-Laroche » serait fautif, et dépose une faute sur seize pages. Un nom
 *  sans article en reçoit un : « ParisLongchamp » → « de ParisLongchamp ». Le nom complet
 *  reste celui du titre et du balisage. */
/**
 * Le slug de la fiche correspondant à un libellé d'hippodrome du PMU, s'il en existe une.
 *
 * Sert au maillage interne. Mesuré le 2026-09-21 : les seize fiches d'hippodrome
 * n'étaient liées QUE depuis `/hippodromes`, page elle-même explorée une fois par
 * quinzaine — et sept d'entre elles étaient « URL inconnue de Google », jamais explorées,
 * bien que présentes au sitemap depuis un mois. Les pages que Googlebot visite tous les
 * jours sont le programme, les résultats et les fiches course : c'est de là que le lien
 * doit partir.
 */
export function slugHippodrome(hippodromeNom: string | undefined): string | null {
  if (!hippodromeNom) return null;
  // La correspondance la plus précise l'emporte : « DEAUVILLE-CLAIREFONTAINE » contient
  // aussi « DEAUVILLE », mais désigne Clairefontaine.
  const up = hippodromeNom.toUpperCase();
  let meilleur: { slug: string; longueur: number } | null = null;
  for (const h of HIPPODROMES) {
    for (const m of h.match) {
      if (up.includes(m) && (!meilleur || m.length > meilleur.longueur)) meilleur = { slug: h.slug, longueur: m.length };
    }
  }
  return meilleur?.slug ?? null;
}

export function nomCourt(h: Hippodrome): string {
  const reste = h.name.replace(/^Hippodrome\s+/i, "").trim();
  if (!reste) return h.name;
  return /^(de la |de l'|des |du |de |d')/i.test(reste) ? reste : `de ${reste}`;
}

/** « Hippodrome de Vincennes » → « Vincennes », « Hippodrome d'Auteuil » → « Auteuil » :
 *  le nom tel qu'on le tape dans une recherche (« pronostic Vincennes »). */
export function nomLieu(h: Hippodrome): string {
  return h.name.replace(/^Hippodrome\s+/i, "").replace(/^(de la |de l'|des |du |de |d')/i, "").trim() || h.name;
}

export function matchHippodrome(hippodromeNom: string | undefined, h: Hippodrome): boolean {
  if (!hippodromeNom) return false;
  const up = hippodromeNom.toUpperCase();
  return h.match.some((m) => up.includes(m));
}
