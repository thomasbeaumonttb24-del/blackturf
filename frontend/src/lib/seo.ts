// Server-side SEO data fetchers (no axios, no window). Used by the sitemap routes + server
// page wrappers (programme, course). Plain fetch + ISR cache so crawlers get real HTML
// without hammering the API. Best-effort: any failure returns empty so a page never 500s
// on SEO data.
import type { Metadata } from "next";

const API = (process.env.NEXT_PUBLIC_API_URL || "https://api.blackturf.fr") + "/api/v1";

/* ───────────────────────────── Open Graph ─────────────────────────────
 * Next ne FUSIONNE pas `openGraph` : dès qu'une page déclare cet objet, il REMPLACE
 * entièrement celui du layout racine — y compris `images`. Toutes les pages qui
 * posaient leur propre titre OG perdaient donc l'illustration, et un partage de fiche
 * course, de programme ou d'article ne montrait aucune vignette. Constaté sur les huit
 * gabarits du site le 2026-08-26 : seule l'accueil, qui n'écrase rien, gardait la sienne.
 *
 * `ogBase()` reconstruit le socle commun (image + site + locale) pour que chaque page
 * n'ait plus qu'à poser son titre et son URL. Une page qui a sa propre illustration
 * passe simplement `image`.
 */
export const OG_IMAGE = { url: "/og-image.jpg", width: 1200, height: 630, alt: "BlackTurf" };

export function ogBase(o: {
  title: string;
  description: string;
  url: string;
  type?: "website" | "article";
  image?: { url: string; width: number; height: number; alt: string };
}): NonNullable<Metadata["openGraph"]> {
  return {
    title: o.title,
    description: o.description,
    url: o.url.startsWith("http") ? o.url : `https://blackturf.fr${o.url}`,
    siteName: "BlackTurf",
    locale: "fr_FR",
    type: o.type ?? "website",
    images: [o.image ?? OG_IMAGE],
  };
}

/** Carte Twitter alignée sur l'Open Graph — même remarque : `twitter` est écrasé, pas fusionné. */
export function twitterBase(o: {
  title: string;
  description: string;
  image?: string;
}): NonNullable<Metadata["twitter"]> {
  return {
    card: "summary_large_image",
    title: o.title,
    description: o.description,
    images: [o.image ?? OG_IMAGE.url],
  };
}

export interface SeoCourse {
  course_id: string;
  nom: string | null;
  numero: number;
  numero_reunion: number;
  date_heure: string;
  hippodrome_nom: string;
  discipline: string;
  distance: number;
  nb_partants: number;
  statut: string;
  est_quinte: boolean;
  est_quarte: boolean;
  est_tierce: boolean;
  est_2sur4?: boolean;
  conditions_texte?: string | null;
  allocation?: number | null;
  // Présents dans /programme comme dans /courses/{id} : déclarés ici pour que la donnée
  // récupérée côté serveur soit directement injectable dans le composant client.
  penetrometre_coef: number | null;
  penetrometre_desc: string | null;
  pool_total_eur: number | null;
}

export interface SeoReunion {
  reunion_id: string;
  hippodrome: string;
  numero: number;
  courses: SeoCourse[];
}

export interface SeoProgramme {
  date: string;
  nb_courses: number;
  reunions: SeoReunion[];
}

export async function fetchProgramme(jour?: string): Promise<SeoProgramme | null> {
  try {
    const url = `${API}/programme${jour ? `?jour=${encodeURIComponent(jour)}` : ""}`;
    const res = await fetch(url, { next: { revalidate: 300 } });
    if (!res.ok) return null;
    return (await res.json()) as SeoProgramme;
  } catch {
    return null;
  }
}

export async function fetchCourse(id: string): Promise<SeoCourse | null> {
  try {
    const res = await fetch(`${API}/courses/${encodeURIComponent(id)}`, {
      next: { revalidate: 300 },
    });
    if (!res.ok) return null;
    return (await res.json()) as SeoCourse;
  } catch {
    return null;
  }
}

// Comme fetchCourse mais distingue le 404 explicite (course inexistante → vraie page 404,
// évite le soft-404 GSC) d'une erreur transitoire (API down → on garde le shell client en 200,
// pour ne JAMAIS désindexer une course valide sur un simple hoquet réseau).
export type CourseFetch =
  | { status: "ok"; course: SeoCourse }
  | { status: "notfound" }
  | { status: "error" };

export async function fetchCourseResult(id: string): Promise<CourseFetch> {
  try {
    const res = await fetch(`${API}/courses/${encodeURIComponent(id)}`, {
      next: { revalidate: 300 },
    });
    if (res.status === 404) return { status: "notfound" };
    if (!res.ok) return { status: "error" };
    return { status: "ok", course: (await res.json()) as SeoCourse };
  } catch {
    return { status: "error" };
  }
}

const DISCIPLINE_LABEL: Record<string, string> = {
  PLAT: "Plat",
  TROT: "Trot",
  TROT_ATTELE: "Trot attelé",
  TROT_MONTE: "Trot monté",
  OBSTACLE: "Obstacle",
  HAIES: "Haies",
  STEEPLE: "Steeple-chase",
  STEEPLECHASE: "Steeple-chase",
  CROSS: "Cross-country",
};

export function disciplineLabel(d?: string | null): string {
  if (!d) return "Course";
  return DISCIPLINE_LABEL[d.toUpperCase()] ?? (d.charAt(0) + d.slice(1).toLowerCase());
}

export function titleCase(s?: string | null): string {
  if (!s) return "";
  return (
    s
      .toLowerCase()
      .replace(/(^|[\s'\-])([a-zà-ÿ])/g, (_m, p: string, c: string) => p + c.toUpperCase())
      // Le préfixe administratif ne se retirait que suivi d'une particule : « Hippodrome
      // De Vincennes » devenait « Vincennes », mais « Hippodrome Gelsenkirchen All »
      // restait entier — et se retrouvait tel quel dans les titres et les descriptions
      // envoyés à Google. Six hippodromes sur les soixante-quinze vus en trente jours
      // étaient dans ce cas, tous étrangers. La particule est désormais facultative, et
      // la forme abrégée « HIPPO DE » que porte le PMU est reconnue elle aussi.
      .replace(/^Hippo(?:drome)? (?:De |Du |D'|Des |La |Le )?/i, "")
      .trim()
  );
}

/* ───────────────────────── Jour « courses » (Europe/Paris) ─────────────────────────
 * Le jour hippique se lit à Paris, jamais en UTC : un serveur en UTC bascule de journée
 * à 00:00 UTC (02:00 à Paris l'été) et vide le programme pendant deux heures. Ces deux
 * helpers donnent le MÊME résultat côté serveur (SSR) et côté client (hydratation), quel
 * que soit le fuseau de la machine → aucun mismatch d'hydratation sur les dates.
 */
export function jourParis(offsetJours = 0, base?: Date): string {
  const d = base ? new Date(base) : new Date();
  d.setUTCDate(d.getUTCDate() + offsetJours);
  return new Intl.DateTimeFormat("fr-CA", {
    timeZone: "Europe/Paris",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(d); // fr-CA → "YYYY-MM-DD"
}

/* En français le premier jour du mois s'écrit « 1er », jamais « 1 » : `Intl` ne connaît
 * pas cette règle et sortait « Résultats PMU du 1 mai ». Corrigé ici une fois pour
 * toutes, donc dans les titres, les pages et les visuels qui partagent ces helpers. */
function premierDuMois(rendu: string): string {
  return rendu.replace(/(^|\s)1(\s\p{L})/u, "$11er$2");
}

/** "2026-08-23" → "dimanche 23 août 2026" */
export function jourLong(iso: string): string {
  const d = new Date(`${iso}T12:00:00Z`);
  return premierDuMois(
    new Intl.DateTimeFormat("fr-FR", {
      timeZone: "Europe/Paris",
      weekday: "long",
      day: "numeric",
      month: "long",
      year: "numeric",
    }).format(d),
  );
}

/** "2026-08-23" → "23 août" (titres courts, sous la limite des 60 caractères) */
export function jourCourt(iso: string): string {
  const d = new Date(`${iso}T12:00:00Z`);
  return premierDuMois(
    new Intl.DateTimeFormat("fr-FR", {
      timeZone: "Europe/Paris",
      day: "numeric",
      month: "long",
    }).format(d),
  );
}

/** "2026-08-23" → "23 août 2026". Porte l'année : un titre de page d'archive doit
 *  rester unique d'une année sur l'autre, sinon deux journées différentes portent le
 *  même `<title>` et Google en choisit une seule. */
export function jourCourtAnnee(iso: string): string {
  const d = new Date(`${iso}T12:00:00Z`);
  return premierDuMois(
    new Intl.DateTimeFormat("fr-FR", {
      timeZone: "Europe/Paris",
      day: "numeric",
      month: "long",
      year: "numeric",
    }).format(d),
  );
}

/* Première journée réellement couverte par la base (vérifié le 2026-08-26 : le
 * 2025-08-31 renvoie zéro course, le 2025-09-01 en renvoie 45). Sert de borne unique à
 * la validation des URLs d'archives ET à la découpe mensuelle des sitemaps : les deux
 * doivent s'accorder, sinon le sitemap annonce des journées que la page refuse en 404. */
export const PREMIER_JOUR_ARCHIVE = "2025-09-01";

/** Liste des mois "AAAA-MM" du plus récent au plus ancien, du mois courant à celui de
 *  `PREMIER_JOUR_ARCHIVE`. */
export function moisArchives(aujourdhui = jourParis()): string[] {
  const out: string[] = [];
  const debut = PREMIER_JOUR_ARCHIVE.slice(0, 7);
  let [y, m] = aujourdhui.slice(0, 7).split("-").map(Number);
  for (let garde = 0; garde < 600; garde++) {
    const ym = `${y}-${String(m).padStart(2, "0")}`;
    out.push(ym);
    if (ym <= debut) break;
    m -= 1;
    if (m === 0) { m = 12; y -= 1; }
  }
  return out;
}

/** Premier et dernier jour d'un mois "AAAA-MM", bornés à la fenêtre réellement couverte. */
export function bornesDuMois(ym: string, aujourdhui = jourParis()): { debut: string; fin: string } {
  const [y, m] = ym.split("-").map(Number);
  const dernier = new Date(Date.UTC(y, m, 0)).getUTCDate(); // jour 0 du mois suivant
  const debut = `${ym}-01`;
  const fin = `${ym}-${String(dernier).padStart(2, "0")}`;
  return {
    debut: debut < PREMIER_JOUR_ARCHIVE ? PREMIER_JOUR_ARCHIVE : debut,
    fin: fin > aujourdhui ? aujourdhui : fin,
  };
}

/** "2026-08" → "août 2026" (regroupement par mois des archives) */
export function moisLong(ym: string): string {
  const d = new Date(`${ym}-01T12:00:00Z`);
  return new Intl.DateTimeFormat("fr-FR", {
    timeZone: "Europe/Paris",
    month: "long",
    year: "numeric",
  }).format(d);
}

/** ISO datetime → "09:40" (heure de Paris) */
export function heureParis(iso: string): string {
  return new Intl.DateTimeFormat("fr-FR", {
    timeZone: "Europe/Paris",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}

/** "23082026R2C1" → "2026-08-23" (le course_id porte la date en DDMMYYYY) */
export function jourDeCourseId(courseId: string): string | null {
  const m = courseId.match(/^(\d{2})(\d{2})(\d{4})/);
  return m ? `${m[3]}-${m[2]}-${m[1]}` : null;
}

/** "23082026R2C1" → "R2C1" */
export function codeReunionCourse(courseId: string): string {
  return courseId.match(/R\d+C\d+$/)?.[0] ?? courseId;
}

/* ───────────────────────── Détail course + partants (SSR) ───────────────────────── */

export interface SeoPartant {
  numero: number;
  nom_cheval: string;
  age?: number | null;
  sexe?: string | null;
  jockey?: string | null;
  entraineur?: string | null;
  cote_pmu?: number | null;
  musique?: string | null;
  non_partant?: boolean;
  handicap_poids?: number | null;
  numero_corde?: number | null;
}

export interface SeoCourseDetail extends SeoCourse {
  partants?: SeoPartant[];
  montant_offert_1er?: number | null;
  terrain_officiel?: string | null;
}

export type CourseDetailFetch =
  | { status: "ok"; course: SeoCourseDetail }
  | { status: "notfound" }
  | { status: "error" };

/** Détail complet (avec partants) pour le rendu serveur de la fiche course. */
export async function fetchCourseDetail(id: string): Promise<CourseDetailFetch> {
  try {
    const res = await fetch(`${API}/courses/${encodeURIComponent(id)}`, {
      next: { revalidate: 120 },
    });
    if (res.status === 404) return { status: "notfound" };
    if (!res.ok) return { status: "error" };
    return { status: "ok", course: (await res.json()) as SeoCourseDetail };
  } catch {
    return { status: "error" };
  }
}

export interface SeoResultatLigne {
  position: number;
  numero: number;
  nom: string;
  temps?: number | null;
  reduction_km?: number | null;
  incident?: string | null;
}

export interface SeoResultats {
  course_id: string;
  classement: SeoResultatLigne[] | null;
  rapports: Record<string, number> | null;
  rapports_detail: Record<string, Array<{ libelle: string; rapport: number; combinaison: string }>> | null;
  temps_gagnant?: number | null;
  commentaire?: string | null;
}

/** Arrivée officielle + rapports PMU. null = pas encore publiée (course non courue). */
export async function fetchResultats(id: string): Promise<SeoResultats | null> {
  try {
    const res = await fetch(`${API}/courses/${encodeURIComponent(id)}/resultats`, {
      next: { revalidate: 120 },
    });
    if (!res.ok) return null;
    return (await res.json()) as SeoResultats;
  } catch {
    return null;
  }
}

/* ── Compteur de paris de valeur (bandeau haut du programme) ──────────────────
   Ce compteur était chargé UNIQUEMENT côté navigateur : le bandeau n'existait pas dans
   le HTML, apparaissait après l'hydratation puis après l'aller-retour réseau, et devenait
   au passage le plus gros bloc de texte de l'écran — donc l'élément LCP, mesuré à 4,0 s
   sur mobile pour un premier rendu à 1,2 s. Le rendre côté serveur le fait exister dès le
   premier octet ; SWR continue de le rafraîchir toutes les minutes par-dessus. */
export async function fetchValueBetsCompteur(
  niveauMin = 3,
): Promise<{ count: number; niveau_min: number } | null> {
  try {
    const res = await fetch(`${API}/value-bets/compteur?niveau_min=${niveauMin}`, {
      next: { revalidate: 60 },
    });
    if (!res.ok) return null;
    return (await res.json()) as { count: number; niveau_min: number };
  } catch {
    return null;
  }
}

/* ───────────────── Index d'exploration (sitemaps + page d'archives) ─────────────────
 * Voir `/api/v1/seo/index` côté backend pour le pourquoi : sans ces deux appels, les
 * fiches course et les journées de résultats passées n'ont aucun chemin d'accès.
 */
export interface SeoIndexCourse {
  id: string;
  jour: string; // AAAA-MM-JJ
  termine: boolean;
  hippodrome: string;
}

/** "2026-08-26" + n jours → "2026-08-xx" (arithmétique en UTC midi, sans dérive de fuseau). */
export function decalerJours(jour: string, n: number): string {
  const d = new Date(`${jour}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** Courses courues entre deux dates (bornes incluses). Max 62 jours par appel. */
export async function fetchSeoIndex(
  debut: string,
  fin: string,
  revalidate = 3600,
): Promise<{ courses: SeoIndexCourse[]; jours: string[] }> {
  try {
    const res = await fetch(`${API}/seo/index?debut=${debut}&fin=${fin}`, {
      next: { revalidate },
    });
    if (!res.ok) return { courses: [], jours: [] };
    const d = (await res.json()) as { courses?: SeoIndexCourse[]; jours?: string[] };
    return { courses: d.courses ?? [], jours: d.jours ?? [] };
  } catch {
    return { courses: [], jours: [] };
  }
}

/**
 * Toutes les arrivées d'une journée, en un seul appel.
 *
 * Remplace un `Promise.all` sur `fetchResultats()` course par course : jusqu'à
 * quatre-vingt-dix requêtes simultanées vers l'API, dont nginx rejetait tout ce qui
 * dépassait trente connexions par IP. Les échecs devenaient des arrivées manquantes,
 * silencieusement, et la page amputée partait en cache. Voir `/api/v1/seo/arrivees`.
 */
export async function fetchArriveesDuJour(
  jour: string,
  revalidate = 300,
): Promise<Record<string, SeoResultats> | null> {
  try {
    const res = await fetch(`${API}/seo/arrivees?jour=${jour}`, { next: { revalidate } });
    if (!res.ok) return null;
    const d = (await res.json()) as { arrivees?: Record<string, SeoResultats> };
    return d.arrivees ?? {};
  } catch {
    return null;
  }
}

/** Toutes les journées portant une arrivée, de la plus récente à la plus ancienne. */
export async function fetchJoursResultats(): Promise<Array<{ jour: string; nb_courses: number }>> {
  try {
    const res = await fetch(`${API}/seo/jours-resultats`, { next: { revalidate: 1800 } });
    if (!res.ok) return [];
    const d = (await res.json()) as { jours?: Array<{ jour: string; nb_courses: number }> };
    return d.jours ?? [];
  } catch {
    return [];
  }
}

/* ───────────────────────── Track record (rendu serveur) ───────────────────────── */
export interface SeoTrackRecord {
  global: {
    accuracy_top1: number;
    accuracy_top3: number;
    brier_moyen: number | null;
    nb_courses_analysees: number;
    nb_courses_rejouables: number;
    mesure_depuis: string | null;
    hasard_top1: number;
    hasard_top3: number;
    nb_partants_moyen: number;
    favori_win_rate: number;
    favori_place_rate: number;
    nb_favoris_evalues: number;
    favori_roi: number | null;
    favori_mise_totale: number | null;
    favori_gain_total: number | null;
    favori_net: number | null;
  };
  by_discipline?: Array<{
    discipline: string;
    nb_courses: number;
    accuracy_top1: number;
    accuracy_top3: number;
  }>;
  updated_at?: string;
}

/** Chiffres du palmarès, servis par un cache « stale-while-revalidate » côté API
 *  (128 ms mesurés en prod). Best-effort : la page reste valable sans eux. */
export async function fetchTrackRecord(): Promise<SeoTrackRecord | null> {
  try {
    const res = await fetch(`${API}/stats/track-record`, { next: { revalidate: 900 } });
    if (!res.ok) return null;
    return (await res.json()) as SeoTrackRecord;
  } catch {
    return null;
  }
}
