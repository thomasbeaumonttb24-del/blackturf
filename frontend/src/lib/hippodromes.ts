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
];

export function getHippodrome(slug: string): Hippodrome | undefined {
  return HIPPODROMES.find((h) => h.slug === slug);
}

export function matchHippodrome(hippodromeNom: string | undefined, h: Hippodrome): boolean {
  if (!hippodromeNom) return false;
  const up = hippodromeNom.toUpperCase();
  return h.match.some((m) => up.includes(m));
}
