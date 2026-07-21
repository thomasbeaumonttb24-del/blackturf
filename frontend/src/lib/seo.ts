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
