import type { MetadataRoute } from "next";
import { fetchProgramme, jourParis } from "@/lib/seo";
import { ARTICLES } from "@/lib/blog";
import { HIPPODROMES } from "@/lib/hippodromes";
import { DISCIPLINES } from "@/lib/disciplines";

const BASE_URL = "https://blackturf.fr";

/**
 * Sitemap — régénéré toutes les 5 min côté serveur.
 *
 * Deux règles Google appliquées ici :
 *
 * 1. `<priority>` et `<changefreq>` sont explicitement IGNORÉS par Google. Ils ne sont
 *    donc plus émis : ils ne donnaient qu'une illusion de pilotage.
 * 2. `<lastmod>` n'est utilisé que s'il est cohérent et VÉRIFIABLE. Un `new Date()`
 *    appliqué à toutes les URLs à chaque régénération est un lastmod menteur : Google
 *    l'ignore, et cela décrédibilise le sitemap entier. Chaque URL porte donc ici une
 *    date qui correspond à une vraie modification de son contenu.
 *
 * Le sitemap ne liste que des URLs canoniques, en 200 et indexables : /login est en
 * noindex, elle n'y figure pas.
 */
export const revalidate = 300;

// Dates de dernière refonte réelle des pages éditoriales fixes. À mettre à jour QUAND on
// touche au contenu de la page, pas à chaque déploiement.
const MAJ = {
  accueil: "2026-08-23",
  tarifs: "2026-08-23",
  guides: "2026-06-23",
  guideTypesParis: "2026-06-23",
  guideMusique: "2026-06-23",
  guideValeur: "2026-06-23",
  blogIndex: "2026-06-23",
  hippodromesIndex: "2026-08-23",
  disciplinesIndex: "2026-08-23",
  newsletter: "2026-08-24",
  inscription: "2026-08-23",
  legal: "2026-07-02",
} as const;

const d = (iso: string) => new Date(`${iso}T12:00:00Z`);

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const now = new Date();
  const aujourdhui = jourParis();

  // Pages dont le contenu change réellement plusieurs fois par jour : `now` y est un
  // lastmod honnête.
  const pagesDuJour: MetadataRoute.Sitemap = [
    { url: `${BASE_URL}/programme`, lastModified: now },
    { url: `${BASE_URL}/quinte-du-jour`, lastModified: now },
    { url: `${BASE_URL}/resultats`, lastModified: now },
  ];

  const pagesFixes: MetadataRoute.Sitemap = [
    { url: BASE_URL, lastModified: d(MAJ.accueil) },
    { url: `${BASE_URL}/tarifs`, lastModified: d(MAJ.tarifs) },
    { url: `${BASE_URL}/guides`, lastModified: d(MAJ.guides) },
    { url: `${BASE_URL}/guides/types-de-paris-pmu`, lastModified: d(MAJ.guideTypesParis) },
    { url: `${BASE_URL}/guides/comment-lire-la-musique`, lastModified: d(MAJ.guideMusique) },
    { url: `${BASE_URL}/guides/pari-de-valeur`, lastModified: d(MAJ.guideValeur) },
    { url: `${BASE_URL}/blog`, lastModified: d(MAJ.blogIndex) },
    { url: `${BASE_URL}/hippodromes`, lastModified: d(MAJ.hippodromesIndex) },
    { url: `${BASE_URL}/disciplines`, lastModified: d(MAJ.disciplinesIndex) },
    { url: `${BASE_URL}/newsletter`, lastModified: d(MAJ.newsletter) },
    { url: `${BASE_URL}/inscription`, lastModified: d(MAJ.inscription) },
    { url: `${BASE_URL}/mentions-legales`, lastModified: d(MAJ.legal) },
    { url: `${BASE_URL}/cgu`, lastModified: d(MAJ.legal) },
    { url: `${BASE_URL}/cgv`, lastModified: d(MAJ.legal) },
    { url: `${BASE_URL}/confidentialite`, lastModified: d(MAJ.legal) },
  ];

  // Archives d'arrivées : une page par journée écoulée. Une arrivée et ses rapports ne
  // changent plus jamais — c'est le seul contenu du site qui ne se périme pas, et son
  // lastmod est donc la journée elle-même, en fin de programme.
  const archivesResultats: MetadataRoute.Sitemap = Array.from({ length: 30 }, (_, i) => {
    const j = jourParis(-(i + 1));
    return { url: `${BASE_URL}/resultats/${j}`, lastModified: new Date(`${j}T21:00:00Z`) };
  });

  const blogPages: MetadataRoute.Sitemap = ARTICLES.map((a) => ({
    url: `${BASE_URL}/blog/${a.slug}`,
    lastModified: d(a.updated),
  }));

  // Les pages hippodrome et discipline embarquent le programme du jour : leur contenu
  // change bien chaque jour, mais une fois — pas à chaque régénération.
  const debutDeJournee = new Date(`${aujourdhui}T04:00:00Z`);
  const hippodromePages: MetadataRoute.Sitemap = HIPPODROMES.map((h) => ({
    url: `${BASE_URL}/hippodromes/${h.slug}`,
    lastModified: debutDeJournee,
  }));
  const disciplinePages: MetadataRoute.Sitemap = DISCIPLINES.map((dd) => ({
    url: `${BASE_URL}/disciplines/${dd.slug}`,
    lastModified: debutDeJournee,
  }));

  // Courses de la veille, du jour et du lendemain. La veille porte les arrivées et les
  // rapports ; le lendemain permet à Google de découvrir une course AVANT qu'elle ne soit
  // courue — sans quoi la fiche n'est explorée qu'une fois la course finie et n'a jamais
  // eu sa chance sur « partants <course> ».
  // Le jour se calcule à Paris : en UTC, la journée bascule à 02 h heure française et le
  // sitemap listait alors les courses de la veille.
  const courseUrls: MetadataRoute.Sitemap = [];
  const seen = new Set<string>();
  const jours = [jourParis(-1), aujourdhui, jourParis(1)];
  const progs = await Promise.all(jours.map((j) => fetchProgramme(j)));
  for (const prog of progs) {
    for (const r of prog?.reunions ?? []) {
      for (const c of r.courses ?? []) {
        if (!c.course_id || seen.has(c.course_id)) continue;
        seen.add(c.course_id);
        // Une course terminée ne bouge plus une fois l'arrivée publiée ; une course à
        // venir voit ses cotes évoluer jusqu'au départ.
        courseUrls.push({
          url: `${BASE_URL}/courses/${c.course_id}`,
          lastModified: c.statut === "termine" ? new Date(c.date_heure) : now,
        });
      }
    }
  }

  return [
    ...pagesDuJour,
    ...pagesFixes,
    ...archivesResultats,
    ...blogPages,
    ...hippodromePages,
    ...disciplinePages,
    ...courseUrls,
  ];
}
