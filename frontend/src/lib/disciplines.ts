// Hub éditorial des disciplines hippiques (evergreen). Les courses du jour sont filtrées sur le
// champ `discipline` de l'API PMU (uppercase) via `match`.
export interface Discipline {
  slug: string;
  name: string; // titre de page
  short: string; // label court
  intro: string;
  points: string[]; // facteurs clés de la discipline
  match: string[]; // termes uppercase dans discipline (API)
}

export const DISCIPLINES: Discipline[] = [
  {
    slug: "trot",
    name: "Le trot : attelé, monté et paris",
    short: "Trot",
    intro:
      "Le trot (attelé ou monté) impose une allure régulière : un cheval qui galope est disqualifié. C'est la discipline la plus représentée au PMU, avec Vincennes pour temple. Vitesse, ferrure et régularité d'allure y font la différence.",
    points: [
      "La ferrure (déferré ou non) influence fortement la vitesse pure.",
      "La réduction kilométrique mesure la vitesse, à comparer à conditions égales.",
      "Le type de départ (autostart ou volte) et le recul changent la donne.",
      "Le risque de disqualification (faute d'allure) pénalise les chevaux irréguliers.",
    ],
    match: ["TROT", "ATTELE", "ATTELÉ", "MONTE", "MONTÉ"],
  },
  {
    slug: "plat",
    name: "Le plat : galop, vitesse et classe",
    short: "Plat",
    intro:
      "Le plat est la course de galop sans obstacle, du sprint au long. C'est la discipline des classiques (Arc, Jockey Club, Diane) et des grandes pistes comme ParisLongchamp, Chantilly ou Deauville. La place au départ (la corde) et la distance de prédilection y sont déterminantes.",
    points: [
      "La corde (numéro de stalle) pèse selon la piste et la distance.",
      "La distance de prédilection (sprinteur vs tenant) oriente le choix.",
      "Le poids porté en handicap équilibre les chances.",
      "La classe et la descente de catégorie révèlent des opportunités.",
    ],
    match: ["PLAT"],
  },
  {
    slug: "obstacle",
    name: "L'obstacle : haies, steeple et cross",
    short: "Obstacle",
    intro:
      "L'obstacle regroupe les haies, le steeple-chase et le cross. C'est la discipline du saut et de l'endurance, dont Auteuil est la référence avec le Grand Steeple-Chase de Paris. L'expérience du parcours et la sûreté à l'obstacle priment souvent sur la pure vitesse.",
    points: [
      "L'expérience de l'obstacle et la sûreté de saut limitent les chutes.",
      "La connaissance du parcours (Auteuil notamment) est un atout.",
      "L'état du terrain (souple/lourd) influence fortement le résultat.",
      "L'endurance compte autant que la vitesse sur les longues distances.",
    ],
    match: ["OBSTACLE", "HAIES", "STEEPLE", "CROSS"],
  },
];

export function getDiscipline(slug: string): Discipline | undefined {
  return DISCIPLINES.find((d) => d.slug === slug);
}

export function matchDiscipline(discipline: string | undefined, d: Discipline): boolean {
  if (!discipline) return false;
  const up = discipline.toUpperCase();
  return d.match.some((m) => up.includes(m));
}
