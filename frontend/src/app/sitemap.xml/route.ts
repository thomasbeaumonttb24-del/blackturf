import { jourParis } from "@/lib/seo";

/**
 * `/sitemap.xml` — index de sitemaps.
 *
 * Pourquoi un index, et pourquoi écrit à la main.
 *
 * `generateSitemaps()` de Next découpe bien un sitemap, mais expose les morceaux sur
 * `/sitemap/<id>.xml` sans garantir l'index sur `/sitemap.xml` : or c'est cette adresse
 * que déclare `robots.txt` et que connaît Search Console. On écrit donc l'index
 * explicitement, ce qui a l'avantage de nommer les fichiers par leur rôle plutôt que par
 * un numéro opaque — un sitemap qui se lit à l'œil se diagnostique à l'œil.
 *
 * ── Pourquoi trois fichiers et non quinze (2026-09-21) ────────────────────────────────
 *
 * L'index déclarait 20 641 URLs : les 55 pages du site, et treize sitemaps mensuels
 * portant près de dix-neuf mille fiches course d'archive. Mesuré le 2026-09-21 par
 * l'inspection d'URL de Search Console, sur les 51 pages qui comptent :
 *
 *   • 19 n'avaient JAMAIS été explorées, dont sept « URL inconnue de Google » —
 *     `/hippodromes/paris-longchamp`, `/hippodromes/saint-cloud`, `/disciplines/plat`,
 *     `/blog/chatgpt-pronostic-hippique`… toutes listées dans `pages.xml` depuis le mois
 *     d'août, toutes liées depuis leur page d'index ;
 *   • pendant ce temps, les 19 000 fiches d'archive produisaient 9 impressions et
 *     0 clic en 90 jours, et Googlebot ne leur consacrait que 7 requêtes sur 267.
 *
 * Demander l'exploration de dix-neuf mille pages qu'on n'obtient pas, c'est noyer les
 * cinquante-cinq qu'on veut. Les fiches d'archive ne disparaissent pas pour autant :
 * elles répondent 200, restent « index, follow » et gardent leur chemin d'exploration
 * par `/resultats/<jour>` et `/resultats/archives`. Ce qui change, c'est qu'on cesse de
 * les POUSSER.
 *
 * `lastmod` reste soumis à la règle de Google : il n'est émis que s'il correspond à une
 * modification réelle. Un `new Date()` à chaque régénération — ce que faisait cet
 * index toutes les heures — est un lastmod menteur, et Google finit par ignorer le
 * fichier entier. Les trois enfants portent donc le début de la journée parisienne :
 * leur contenu change bien une fois par jour, pas à chaque passage du cache.
 */
export const revalidate = 3600;

const BASE = "https://blackturf.fr";

export async function GET() {
  // 04:00 UTC : après la publication du programme du lendemain, avant la première course.
  const debutDeJournee = `${jourParis()}T04:00:00Z`;

  const entrees = [
    { loc: `${BASE}/sitemaps/pages.xml`, lastmod: debutDeJournee },
    { loc: `${BASE}/sitemaps/resultats.xml`, lastmod: debutDeJournee },
    { loc: `${BASE}/sitemaps/courses.xml`, lastmod: debutDeJournee },
  ];

  const xml =
    `<?xml version="1.0" encoding="UTF-8"?>\n` +
    `<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n` +
    entrees
      .map((e) => `<sitemap><loc>${e.loc}</loc><lastmod>${e.lastmod}</lastmod></sitemap>`)
      .join("\n") +
    `\n</sitemapindex>`;

  return new Response(xml, {
    headers: {
      "Content-Type": "application/xml; charset=utf-8",
      "Cache-Control": "public, max-age=0, s-maxage=3600, stale-while-revalidate=86400",
    },
  });
}
