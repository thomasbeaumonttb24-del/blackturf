import { moisArchives } from "@/lib/seo";

/**
 * `/sitemap.xml` — index de sitemaps.
 *
 * Pourquoi un index, et pourquoi écrit à la main.
 *
 * Le sitemap unique généré par `app/sitemap.ts` ne pouvait, par construction, contenir
 * que les URLs qu'il savait énumérer sans exploser : les pages fixes, trente journées de
 * résultats et les courses de la veille au lendemain. Soit 161 URLs, quand le site en
 * publie près de dix-sept mille. Tout le reste — onze mois de fiches course et de
 * journées d'arrivées — répondait 200 et « index, follow » sans qu'aucun chemin n'y mène.
 *
 * `generateSitemaps()` de Next découpe bien un sitemap, mais expose les morceaux sur
 * `/sitemap/<id>.xml` sans garantir l'index sur `/sitemap.xml` : or c'est cette adresse
 * que déclare `robots.txt` et que connaît Search Console. On écrit donc l'index
 * explicitement, ce qui a l'avantage de nommer les fichiers par leur mois plutôt que par
 * un numéro opaque — un sitemap qui se lit à l'œil se diagnostique à l'œil.
 *
 * `lastmod` reste soumis à la même règle que le reste du site : il n'est émis que
 * lorsqu'il correspond à une modification réelle. Un mois passé est figé à son dernier
 * jour ; seuls le mois courant et le sitemap des pages portent l'heure de génération.
 */
export const revalidate = 3600;

const BASE = "https://blackturf.fr";

export async function GET() {
  const mois = moisArchives();
  const moisCourant = mois[0];
  const maintenant = new Date().toISOString();

  const entrees: Array<{ loc: string; lastmod: string }> = [
    { loc: `${BASE}/sitemaps/pages.xml`, lastmod: maintenant },
    ...mois.map((ym) => {
      // Dernier jour du mois à 21 h UTC : après la dernière arrivée de la journée. Pour
      // le mois en cours, la génération fait foi.
      const [y, m] = ym.split("-").map(Number);
      const dernier = new Date(Date.UTC(y, m, 0, 21, 0, 0));
      return {
        loc: `${BASE}/sitemaps/${ym}.xml`,
        lastmod: ym === moisCourant ? maintenant : dernier.toISOString(),
      };
    }),
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
