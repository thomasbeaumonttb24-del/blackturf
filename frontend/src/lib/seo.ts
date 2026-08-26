// Server-side SEO data fetchers (no axios, no window). Used by sitemap.ts + server page
// wrappers (programme, course). Plain fetch + ISR cache so crawlers get real HTML without
// hammering the API. Best-effort: any failure returns empty so a page never 500s on SEO data.
const API = (process.env.NEXT_PUBLIC_API_URL || "https://api.blackturf.fr") + "/api/v1";

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
  return s
    .toLowerCase()
    .replace(/(^|[\s'\-])([a-zà-ÿ])/g, (_m, p: string, c: string) => p + c.toUpperCase())
    .replace(/^Hippodrome (De |Du |D'|Des |La |Le )/i, "")
    .trim();
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

/** "2026-08-23" → "dimanche 23 août 2026" */
export function jourLong(iso: string): string {
  const d = new Date(`${iso}T12:00:00Z`);
  return new Intl.DateTimeFormat("fr-FR", {
    timeZone: "Europe/Paris",
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(d);
}

/** "2026-08-23" → "23 août" (titres courts, sous la limite des 60 caractères) */
export function jourCourt(iso: string): string {
  const d = new Date(`${iso}T12:00:00Z`);
  return new Intl.DateTimeFormat("fr-FR", {
    timeZone: "Europe/Paris",
    day: "numeric",
    month: "long",
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
