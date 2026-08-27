import {
  bornesDuMois,
  fetchSeoIndex,
  jourParis,
  moisArchives,
  PREMIER_JOUR_ARCHIVE,
} from "@/lib/seo";
import { ARTICLES } from "@/lib/blog";
import { HIPPODROMES } from "@/lib/hippodromes";
import { DISCIPLINES } from "@/lib/disciplines";

/**
 * Sitemaps enfants — `/sitemaps/pages.xml` et `/sitemaps/AAAA-MM.xml`.
 *
 * Deux règles Google gouvernent ce fichier :
 *
 * 1. `<priority>` et `<changefreq>` sont explicitement ignorés. Ils ne sont pas émis :
 *    ils ne donnaient qu'une illusion de pilotage.
 * 2. `<lastmod>` n'est pris en compte que s'il est cohérent et vérifiable. Un
 *    `new Date()` posé sur toutes les URLs à chaque régénération est un lastmod menteur,
 *    que Google finit par ignorer — pour ce sitemap-là et pour les autres. Chaque URL
 *    porte donc une date qui correspond à une modification réelle de son contenu.
 *
 * Seules des URLs canoniques, en 200 et indexables, sont listées : `/login`, `/recherche`
 * et `/value-bets` sont en `noindex` et n'y figurent donc pas — une URL en noindex
 * listée dans un sitemap est un signal contradictoire.
 */
export const revalidate = 3600;

const BASE = "https://blackturf.fr";

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
  archives: "2026-08-26",
  pronosticsIa: "2026-08-27",
  legal: "2026-07-02",
} as const;

type Entree = { loc: string; lastmod?: string };

const iso = (jourIso: string, heure = "12:00:00") => `${jourIso}T${heure}Z`;

function rendre(entrees: Entree[]): Response {
  const xml =
    `<?xml version="1.0" encoding="UTF-8"?>\n` +
    `<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n` +
    entrees
      .map(
        (e) =>
          `<url><loc>${e.loc}</loc>` +
          (e.lastmod ? `<lastmod>${e.lastmod}</lastmod>` : "") +
          `</url>`,
      )
      .join("\n") +
    `\n</urlset>`;

  return new Response(xml, {
    headers: {
      "Content-Type": "application/xml; charset=utf-8",
      "Cache-Control": "public, max-age=0, s-maxage=3600, stale-while-revalidate=86400",
    },
  });
}

/** Pages fixes, pages du jour, rubriques éditoriales. */
function sitemapPages(): Response {
  const maintenant = new Date().toISOString();
  const aujourdhui = jourParis();
  // Les pages hippodrome et discipline embarquent le programme du jour : leur contenu
  // change bien chaque jour, mais une fois — pas à chaque régénération.
  const debutDeJournee = iso(aujourdhui, "04:00:00");

  const entrees: Entree[] = [
    // Contenu réellement renouvelé plusieurs fois par jour : `maintenant` est honnête.
    { loc: `${BASE}/programme`, lastmod: maintenant },
    { loc: `${BASE}/quinte-du-jour`, lastmod: maintenant },
    { loc: `${BASE}/resultats`, lastmod: maintenant },

    { loc: BASE, lastmod: iso(MAJ.accueil) },
    { loc: `${BASE}/tarifs`, lastmod: iso(MAJ.tarifs) },
    { loc: `${BASE}/pronostics-ia`, lastmod: iso(MAJ.pronosticsIa) },
    // Le palmarès est passé en `index` le 2026-08-26 mais était resté hors du sitemap.
    // Son contenu chiffré est régénéré toutes les quinze minutes.
    { loc: `${BASE}/track-record`, lastmod: debutDeJournee },
    { loc: `${BASE}/guides`, lastmod: iso(MAJ.guides) },
    { loc: `${BASE}/guides/types-de-paris-pmu`, lastmod: iso(MAJ.guideTypesParis) },
    { loc: `${BASE}/guides/comment-lire-la-musique`, lastmod: iso(MAJ.guideMusique) },
    { loc: `${BASE}/guides/pari-de-valeur`, lastmod: iso(MAJ.guideValeur) },
    { loc: `${BASE}/blog`, lastmod: iso(MAJ.blogIndex) },
    { loc: `${BASE}/hippodromes`, lastmod: iso(MAJ.hippodromesIndex) },
    { loc: `${BASE}/disciplines`, lastmod: iso(MAJ.disciplinesIndex) },
    { loc: `${BASE}/resultats/archives`, lastmod: debutDeJournee },
    { loc: `${BASE}/newsletter`, lastmod: iso(MAJ.newsletter) },
    { loc: `${BASE}/inscription`, lastmod: iso(MAJ.inscription) },
    { loc: `${BASE}/mentions-legales`, lastmod: iso(MAJ.legal) },
    { loc: `${BASE}/cgu`, lastmod: iso(MAJ.legal) },
    { loc: `${BASE}/cgv`, lastmod: iso(MAJ.legal) },
    { loc: `${BASE}/confidentialite`, lastmod: iso(MAJ.legal) },

    ...ARTICLES.map((a) => ({ loc: `${BASE}/blog/${a.slug}`, lastmod: iso(a.updated) })),
    ...HIPPODROMES.map((h) => ({ loc: `${BASE}/hippodromes/${h.slug}`, lastmod: debutDeJournee })),
    ...DISCIPLINES.map((d) => ({ loc: `${BASE}/disciplines/${d.slug}`, lastmod: debutDeJournee })),
  ];

  return rendre(entrees);
}

/** Un mois d'archives : les journées d'arrivées et toutes leurs fiches course. */
async function sitemapMois(ym: string): Promise<Response> {
  const aujourdhui = jourParis();
  const { debut, fin } = bornesDuMois(ym, aujourdhui);
  // Le mois en cours bouge encore (courses ajoutées, arrivées publiées) ; un mois clos
  // est figé et peut être mis en cache longtemps côté Next.
  const revalider = ym === aujourdhui.slice(0, 7) ? 600 : 21600;
  const { courses, jours } = await fetchSeoIndex(debut, fin, revalider);

  const entrees: Entree[] = [
    // Une journée d'arrivées ne change plus après 21 h UTC. La journée en cours a son
    // adresse propre, `/resultats`, et n'est donc jamais listée ici.
    ...jours
      .filter((j) => j !== aujourdhui)
      .map((j) => ({ loc: `${BASE}/resultats/${j}`, lastmod: iso(j, "21:00:00") })),
    // Une course terminée est immuable : son lastmod est le jour de la course. Une
    // course encore à venir voit ses cotes bouger jusqu'au départ.
    ...courses.map((c) => ({
      loc: `${BASE}/courses/${c.id}`,
      lastmod: c.termine ? iso(c.jour, "21:00:00") : new Date().toISOString(),
    })),
  ];

  return rendre(entrees);
}

export async function GET(
  _req: Request,
  ctx: { params: Promise<{ fichier: string }> },
) {
  const { fichier } = await ctx.params;

  // L'extension est EXIGÉE. Sans ce contrôle, `/sitemaps/2025-09` répondait 200 au même
  // titre que `/sitemaps/2025-09.xml` : deux adresses pour un contenu identique, dont une
  // que rien ne référence. C'est précisément le genre de doublon qu'un sitemap est censé
  // éviter, pas produire.
  if (!fichier.endsWith(".xml")) {
    return new Response("Sitemap inconnu : l'extension .xml est requise.", {
      status: 404,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  }
  const nom = fichier.slice(0, -".xml".length);

  if (nom === "pages") return sitemapPages();

  // Seuls les mois réellement couverts sont servis : sans cette liste blanche, un robot
  // fabriquerait « /sitemaps/1998-04.xml » à l'infini et chaque requête interrogerait
  // l'API pour rien.
  if (moisArchives().includes(nom)) return sitemapMois(nom);

  return new Response(
    `Sitemap inconnu. Attendu : pages.xml, ou un mois entre ${PREMIER_JOUR_ARCHIVE.slice(0, 7)}.xml et ${jourParis().slice(0, 7)}.xml.`,
    { status: 404, headers: { "Content-Type": "text/plain; charset=utf-8" } },
  );
}
