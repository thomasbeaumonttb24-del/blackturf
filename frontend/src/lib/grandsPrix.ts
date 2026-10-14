/* Les grandes courses françaises : une page permanente chacune (« pronostic Arc de
 * Triomphe », « Prix d'Amérique 2027 »…), recherchées chaque année à date fixe.
 *
 * Le contenu éditorial ne porte que des faits recoupés sur plusieurs sources (France
 * Galop, LeTrot, presse hippique) : création, distance, période, conditions, quelques
 * repères historiques établis. Les arrivées des éditions récentes ne sont PAS écrites
 * ici : la page les lit dans la base du site, à partir de la date de l'édition et du nom
 * de la course (`match`). Rien de ce qui change d'une année à l'autre n'est figé à la
 * main, sauf la date des éditions. */

export interface Edition {
  annee: number;
  /** AAAA-MM-JJ, heure de Paris. */
  date: string;
  /** false : date annoncée mais pas encore au programme officiel. */
  officielle?: boolean;
}

export interface GrandPrix {
  slug: string;
  nom: string;
  /** Nom court pour les titres (« l'Arc », « le Prix d'Amérique »). */
  court: string;
  hippodromeSlug: string;
  hippodrome: string;
  discipline: "Plat" | "Trot attelé" | "Trot monté" | "Steeple-chase";
  distance: string;
  periode: string;
  categorie: string;
  conditions: string;
  creation: number;
  allocation?: string;
  intro: string;
  reperes: string[];
  /** Sous-chaînes du nom PMU de la course, en majuscules sans accents. */
  match: string[];
  /** Éditions connues, de la plus ancienne à la plus récente (futures comprises). */
  editions: Edition[];
}

export const GRANDS_PRIX: GrandPrix[] = [
  {
    slug: "prix-d-amerique",
    nom: "Prix d'Amérique",
    court: "le Prix d'Amérique",
    hippodromeSlug: "vincennes",
    hippodrome: "Vincennes",
    discipline: "Trot attelé",
    distance: "2 700 m",
    periode: "Dernier dimanche de janvier",
    categorie: "Groupe I",
    conditions: "Trotteurs de 4 à 11 ans, hongres exclus, sélectionnés sur leurs gains.",
    creation: 1920,
    allocation: "1 000 000 €",
    intro:
      "Couru chaque fin janvier sur la grande piste de Vincennes, le Prix d'Amérique est la course la plus prestigieuse du trot mondial. Disputé à l'attelé sur 2 700 mètres, il réunit l'élite des trotteurs européens et clôt le meeting d'hiver.",
    reperes: [
      "Créé en 1920, il est devenu le championnat du monde officieux du trot attelé.",
      "Ourasi est le seul cheval à l'avoir remporté quatre fois.",
      "Il se court une semaine après le Prix de Cornulier, sommet du trot monté.",
      "C'est l'une des courses les plus jouées de l'année au PMU.",
    ],
    match: ["AMERIQUE"],
    editions: [
      { annee: 2026, date: "2026-01-25" },
      { annee: 2027, date: "2027-01-31", officielle: false },
    ],
  },
  {
    slug: "prix-de-cornulier",
    nom: "Prix de Cornulier",
    court: "le Prix de Cornulier",
    hippodromeSlug: "vincennes",
    hippodrome: "Vincennes",
    discipline: "Trot monté",
    distance: "2 700 m",
    periode: "Janvier, une semaine avant le Prix d'Amérique",
    categorie: "Groupe I",
    conditions: "Trotteurs de 4 ans et plus, hongres exclus.",
    creation: 1931,
    intro:
      "Le Prix de Cornulier est la plus grande course de trot monté au monde. Courue en janvier à Vincennes, sur 2 700 mètres, elle sacre le meilleur trotteur sous la selle de l'hiver, une semaine avant le Prix d'Amérique.",
    reperes: [
      "Créé en 1931, il est la référence absolue du trot monté.",
      "Le trot monté est une spécialité presque exclusivement française.",
      "Plusieurs champions se sont illustrés au monté comme à l'attelé, dans les deux grandes courses de janvier.",
    ],
    match: ["CORNULIER"],
    editions: [{ annee: 2026, date: "2026-01-18" }],
  },
  {
    slug: "grand-steeple-chase-de-paris",
    nom: "Grand Steeple-Chase de Paris",
    court: "le Grand Steeple-Chase de Paris",
    hippodromeSlug: "auteuil",
    hippodrome: "Auteuil",
    discipline: "Steeple-chase",
    distance: "Environ 6 000 m",
    periode: "Un dimanche de mai",
    categorie: "Groupe 1",
    conditions: "Chevaux de 5 ans et plus.",
    creation: 1874,
    intro:
      "Le Grand Steeple-Chase de Paris est la plus grande course d'obstacles de France. Couru chaque printemps à Auteuil, sur près de six kilomètres et une vingtaine d'obstacles, il demande autant d'endurance que de sauts.",
    reperes: [
      "Couru pour la première fois en 1874, il est l'un des plus anciens grands prix français.",
      "C'est la course la plus longue et la plus sélective du calendrier français de l'obstacle.",
      "Plusieurs chevaux l'ont remporté trois fois, signe d'une course de spécialistes.",
    ],
    match: ["STEEPLE-CHASE DE PARIS", "STEEPLE CHASE DE PARIS"],
    editions: [{ annee: 2026, date: "2026-05-17" }],
  },
  {
    slug: "prix-du-jockey-club",
    nom: "Prix du Jockey Club",
    court: "le Prix du Jockey Club",
    hippodromeSlug: "chantilly",
    hippodrome: "Chantilly",
    discipline: "Plat",
    distance: "2 100 m",
    periode: "Fin mai ou début juin, un dimanche",
    categorie: "Groupe 1",
    conditions: "Poulains et pouliches de 3 ans.",
    creation: 1836,
    intro:
      "Surnommé le « Derby français », le Prix du Jockey Club se court à Chantilly au début de l'été. Réservé aux chevaux de 3 ans, il désigne le meilleur poulain de sa génération sur 2 100 mètres.",
    reperes: [
      "Couru pour la première fois en 1836, sur le modèle du Derby d'Epsom.",
      "Longtemps disputé sur 2 400 mètres, il se court sur 2 100 mètres depuis 2005.",
      "Il est souvent une étape vers le Prix de l'Arc de Triomphe à l'automne.",
    ],
    match: ["JOCKEY CLUB"],
    editions: [{ annee: 2026, date: "2026-05-31" }],
  },
  {
    slug: "prix-de-diane",
    nom: "Prix de Diane",
    court: "le Prix de Diane",
    hippodromeSlug: "chantilly",
    hippodrome: "Chantilly",
    discipline: "Plat",
    distance: "2 100 m",
    periode: "Un dimanche de mi-juin",
    categorie: "Groupe 1",
    conditions: "Pouliches de 3 ans.",
    creation: 1843,
    intro:
      "Le Prix de Diane est la grande course des pouliches de 3 ans, l'équivalent français des Oaks anglaises. Couru en juin sur 2 100 mètres à Chantilly, il est aussi l'un des rendez-vous mondains de l'été.",
    reperes: [
      "Créé en 1843, il est l'une des plus anciennes courses de plat françaises.",
      "Il est réservé aux pouliches de 3 ans.",
      "Trêve l'a gagné en 2013 avant de remporter deux fois le Prix de l'Arc de Triomphe.",
    ],
    match: ["DIANE"],
    editions: [{ annee: 2026, date: "2026-06-14" }],
  },
  {
    slug: "grand-prix-de-paris",
    nom: "Grand Prix de Paris",
    court: "le Grand Prix de Paris",
    hippodromeSlug: "paris-longchamp",
    hippodrome: "ParisLongchamp",
    discipline: "Plat",
    distance: "2 400 m",
    periode: "Autour du 14 juillet",
    categorie: "Groupe 1",
    conditions: "Poulains et pouliches de 3 ans.",
    creation: 1863,
    intro:
      "Couru à ParisLongchamp autour du 14 juillet, le Grand Prix de Paris réunit les meilleurs 3 ans sur 2 400 mètres, la distance de l'Arc. Il compte parmi les plus anciennes grandes courses françaises.",
    reperes: [
      "Créé en 1863, sa première édition est remportée par The Ranger.",
      "Gladiateur, vainqueur de la Triple Couronne anglaise, s'y impose en 1865.",
      "Il se court sur 2 400 mètres depuis 2005.",
    ],
    match: ["GRAND PRIX DE PARIS"],
    editions: [{ annee: 2026, date: "2026-07-14" }],
  },
  {
    slug: "prix-de-l-arc-de-triomphe",
    nom: "Prix de l'Arc de Triomphe",
    court: "l'Arc de Triomphe",
    hippodromeSlug: "paris-longchamp",
    hippodrome: "ParisLongchamp",
    discipline: "Plat",
    distance: "2 400 m",
    periode: "Premier dimanche d'octobre",
    categorie: "Groupe 1",
    conditions: "Chevaux de 3 ans et plus, entiers et juments.",
    creation: 1920,
    allocation: "5 000 000 €",
    intro:
      "Le Prix de l'Arc de Triomphe est la course de plat la plus prestigieuse d'Europe. Couru le premier dimanche d'octobre à ParisLongchamp sur 2 400 mètres, il oppose les meilleurs chevaux de 3 ans et plus du monde entier.",
    reperes: [
      "Première édition le 3 octobre 1920, remportée par Comrade.",
      "André Fabre détient le record de victoires chez les entraîneurs, avec huit succès.",
      "Frankie Dettori l'a remporté six fois, un record chez les jockeys.",
      "Danedream détient le record de l'épreuve à ParisLongchamp, établi en 2011.",
    ],
    match: ["ARC DE TRIOMPHE"],
    editions: [
      { annee: 2025, date: "2025-10-05" },
      { annee: 2026, date: "2026-10-04" },
    ],
  },
];

export function getGrandPrix(slug: string): GrandPrix | undefined {
  return GRANDS_PRIX.find((g) => g.slug === slug);
}

/** Majuscules sans accents : les noms PMU sont en capitales, parfois accentuées. */
export function normaliserNom(s: string): string {
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase().replace(/[’']/g, "'");
}

export function estCeGrandPrix(nomCourse: string | null | undefined, g: GrandPrix): boolean {
  if (!nomCourse) return false;
  const n = normaliserNom(nomCourse);
  return g.match.some((m) => n.includes(m));
}

/** Le grand prix associé à un hippodrome, pour le lien depuis sa fiche. */
export function grandsPrixDuLieu(hippodromeSlug: string): GrandPrix[] {
  return GRANDS_PRIX.filter((g) => g.hippodromeSlug === hippodromeSlug);
}
