import type { MetadataRoute } from "next";
import { fetchProgramme, jourParis } from "@/lib/seo";
import { ARTICLES } from "@/lib/blog";
import { HIPPODROMES } from "@/lib/hippodromes";
import { DISCIPLINES } from "@/lib/disciplines";

const BASE_URL = "https://blackturf.fr";

// ISR : régénéré toutes les 5 min côté serveur. Le sitemap liste les pages statiques, les guides,
// les articles de blog + les courses publiques du jour (contenu frais quotidien → Google découvre
// les URLs de courses qui étaient invisibles tant qu'elles n'étaient rendues que côté client).
export const revalidate = 300;

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const now = new Date();

  const staticPages: MetadataRoute.Sitemap = [
    { url: BASE_URL, lastModified: now, changeFrequency: "daily", priority: 1 },
    { url: `${BASE_URL}/programme`, lastModified: now, changeFrequency: "hourly", priority: 0.95 },
    // Pages « du jour » : contenu neuf chaque matin, ce sont elles qui portent la
    // fraîcheur du site pour Google (et les requêtes les plus tapées du turf).
    { url: `${BASE_URL}/quinte-du-jour`, lastModified: now, changeFrequency: "daily", priority: 0.95 },
    { url: `${BASE_URL}/resultats`, lastModified: now, changeFrequency: "hourly", priority: 0.9 },
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
    { url: `${BASE_URL}/cgv`, lastModified: now, changeFrequency: "yearly", priority: 0.2 },
    { url: `${BASE_URL}/confidentialite`, lastModified: now, changeFrequency: "yearly", priority: 0.2 },
  ];

  // Archives d'arrivées : une page par journée écoulée. Contrairement au programme, une
  // arrivée et ses rapports ne changent plus jamais — c'est le seul contenu du site qui
  // ne se périme pas. On expose les 30 derniers jours ; les plus anciens restent
  // accessibles par la navigation « journée précédente ».
  const archivesResultats: MetadataRoute.Sitemap = Array.from({ length: 30 }, (_, i) => {
    const j = jourParis(-(i + 1));
    return {
      url: `${BASE_URL}/resultats/${j}`,
      lastModified: new Date(`${j}T22:00:00Z`),
      changeFrequency: "yearly" as const,
      priority: 0.55,
    };
  });

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

  // Courses de la veille, du jour et du lendemain. La veille porte les arrivées et les
  // rapports (le contenu qui vieillit le mieux), le lendemain permet à Google de découvrir
  // une course AVANT qu'elle ne soit courue — sans quoi la fiche n'est explorée qu'une fois
  // la course finie et n'a jamais eu sa chance sur « partants <course> ».
  // Le jour se calcule à Paris : en UTC, la journée bascule à 02 h du matin heure française
  // et le sitemap listait alors les courses de la veille.
  const courseUrls: MetadataRoute.Sitemap = [];
  const seen = new Set<string>();
  const jours = [jourParis(-1), jourParis(0), jourParis(1)];
  const progs = await Promise.all(jours.map((j) => fetchProgramme(j)));
  for (const prog of progs) {
    for (const r of prog?.reunions ?? []) {
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

  return [...staticPages, ...archivesResultats, ...blogPages, ...hippodromePages, ...disciplinePages, ...courseUrls];
}
