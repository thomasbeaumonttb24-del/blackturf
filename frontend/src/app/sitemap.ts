import type { MetadataRoute } from "next";
import { fetchProgramme } from "@/lib/seo";
import { ARTICLES } from "@/lib/blog";
import { HIPPODROMES } from "@/lib/hippodromes";
import { DISCIPLINES } from "@/lib/disciplines";

const BASE_URL = "https://blackturf.fr";

// ISR : régénéré toutes les 5 min côté serveur. Le sitemap liste les pages statiques, les guides,
// les articles de blog + les courses publiques du jour (contenu frais quotidien → Google découvre
// les URLs de courses qui étaient invisibles tant qu'elles n'étaient rendues que côté client).
export const revalidate = 300;

function yyyymmdd(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const now = new Date();

  const staticPages: MetadataRoute.Sitemap = [
    { url: BASE_URL, lastModified: now, changeFrequency: "daily", priority: 1 },
    { url: `${BASE_URL}/programme`, lastModified: now, changeFrequency: "hourly", priority: 0.95 },
    { url: `${BASE_URL}/tarifs`, lastModified: now, changeFrequency: "weekly", priority: 0.9 },
    { url: `${BASE_URL}/guides`, lastModified: now, changeFrequency: "weekly", priority: 0.7 },
    { url: `${BASE_URL}/guides/types-de-paris-pmu`, lastModified: now, changeFrequency: "monthly", priority: 0.65 },
    { url: `${BASE_URL}/guides/comment-lire-la-musique`, lastModified: now, changeFrequency: "monthly", priority: 0.65 },
    { url: `${BASE_URL}/guides/pari-de-valeur`, lastModified: now, changeFrequency: "monthly", priority: 0.65 },
    { url: `${BASE_URL}/blog`, lastModified: now, changeFrequency: "weekly", priority: 0.7 },
    { url: `${BASE_URL}/hippodromes`, lastModified: now, changeFrequency: "weekly", priority: 0.7 },
    { url: `${BASE_URL}/disciplines`, lastModified: now, changeFrequency: "weekly", priority: 0.65 },
    { url: `${BASE_URL}/inscription`, lastModified: now, changeFrequency: "monthly", priority: 0.8 },
    { url: `${BASE_URL}/login`, lastModified: now, changeFrequency: "monthly", priority: 0.4 },
    { url: `${BASE_URL}/mentions-legales`, lastModified: now, changeFrequency: "yearly", priority: 0.2 },
    { url: `${BASE_URL}/cgu`, lastModified: now, changeFrequency: "yearly", priority: 0.2 },
    { url: `${BASE_URL}/confidentialite`, lastModified: now, changeFrequency: "yearly", priority: 0.2 },
  ];

  const blogPages: MetadataRoute.Sitemap = ARTICLES.map((a) => ({
    url: `${BASE_URL}/blog/${a.slug}`,
    lastModified: new Date(a.updated + "T12:00:00Z"),
    changeFrequency: "monthly" as const,
    priority: 0.6,
  }));

  const hippodromePages: MetadataRoute.Sitemap = HIPPODROMES.map((h) => ({
    url: `${BASE_URL}/hippodromes/${h.slug}`,
    lastModified: now,
    changeFrequency: "daily" as const,
    priority: 0.6,
  }));

  const disciplinePages: MetadataRoute.Sitemap = DISCIPLINES.map((d) => ({
    url: `${BASE_URL}/disciplines/${d.slug}`,
    lastModified: now,
    changeFrequency: "daily" as const,
    priority: 0.6,
  }));

  // Courses du jour (publiques). Best-effort : si l'API ne répond pas, on garde les statiques.
  const courseUrls: MetadataRoute.Sitemap = [];
  const seen = new Set<string>();
  const prog = await fetchProgramme(yyyymmdd(now));
  if (prog?.reunions) {
    for (const r of prog.reunions) {
      for (const c of r.courses ?? []) {
        if (!c.course_id || seen.has(c.course_id)) continue;
        seen.add(c.course_id);
        courseUrls.push({
          url: `${BASE_URL}/courses/${c.course_id}`,
          lastModified: now,
          changeFrequency: "hourly",
          priority: 0.7,
        });
      }
    }
  }

  return [...staticPages, ...blogPages, ...hippodromePages, ...disciplinePages, ...courseUrls];
}
