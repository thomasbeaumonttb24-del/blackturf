import {
  decalerJours,
  fetchJoursResultats,
  fetchSeoIndex,
  jourParis,
} from "@/lib/seo";
import { ARTICLES } from "@/lib/blog";
import { HIPPODROMES } from "@/lib/hippodromes";
import { DISCIPLINES } from "@/lib/disciplines";

/**
 * Sitemaps enfants — `pages.xml`, `resultats.xml`, `courses.xml`.
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
 *
 * Les treize sitemaps mensuels qui poussaient dix-neuf mille fiches d'archive ont été
 * retirés le 2026-09-21 : le raisonnement et les mesures sont dans `app/sitemap.xml`.
 */
export const revalidate = 3600;

const BASE = "https://blackturf.fr";

// Dates de dernière refonte réelle des pages éditoriales fixes. À mettre à jour QUAND on
// touche au contenu de la page, pas à chaque déploiement.
const MAJ = {
  accueil: "2026-09-01",
  tarifs: "2026-09-01",
  guides: "2026-09-01",
  guideTypesParis: "2026-09-01",
  guideMusique: "2026-09-01",
  guideValeur: "2026-06-23",
  blogIndex: "2026-09-01",
  hippodromesIndex: "2026-08-23",
  disciplinesIndex: "2026-08-23",
  newsletter: "2026-08-24",
  inscription: "2026-08-23",
  archives: "2026-08-26",
  pronosticsIa: "2026-09-01",
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
  const aujourdhui = jourParis();
  // Les pages hippodrome et discipline embarquent le programme du jour : leur contenu
  // change bien chaque jour, mais une fois — pas à chaque régénération.
  const debutDeJournee = iso(aujourdhui, "04:00:00");

  const entrees: Entree[] = [
    // Ces trois pages sont refaites chaque jour — programme du jour, quinté du jour,
    // arrivées du jour. Leur lastmod est celui du DÉBUT de journée et non l'heure de
    // régénération : le sitemap étant régénéré toutes les heures, `new Date()` y
    // déplaçait la date à chaque passage du cache. Un lastmod qui bouge sans que le
    // contenu bouge est un lastmod menteur, et Google finit par ignorer le fichier
    // entier — la page perdrait plus qu'elle ne gagnerait à se dire fraîche.
    { loc: `${BASE}/programme`, lastmod: debutDeJournee },
    { loc: `${BASE}/quinte-du-jour`, lastmod: debutDeJournee },
    { loc: `${BASE}/resultats`, lastmod: debutDeJournee },

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

/**
 * `resultats.xml` — toutes les journées qui portent une arrivée.
 *
 * C'est l'archive qui a une demande mesurée : Search Console montre des requêtes comme
 * « arrivée du 10 septembre 2025 » (position 10), « archives quinté 2025 » ou « archives
 * du pmu » sur ces pages, là où les fiches course d'archive font 9 impressions en
 * 90 jours. Une journée de résultats rassemble jusqu'à quatre-vingt-dix arrivées et
 * leurs rapports : c'est la page utile, et c'est elle qui mène aux fiches.
 *
 * Une journée passée ne change plus : son lastmod est figé à 21 h UTC, après la dernière
 * arrivée. La journée en cours a son adresse propre, `/resultats`, et n'est pas listée.
 */
async function sitemapResultats(): Promise<Response> {
  const aujourdhui = jourParis();
  const jours = await fetchJoursResultats();

  return rendre(
    jours
      .map((j) => j.jour)
      .filter((j) => j && j !== aujourdhui)
      .map((j) => ({ loc: `${BASE}/resultats/${j}`, lastmod: iso(j, "21:00:00") })),
  );
}

/**
 * `courses.xml` — la fenêtre de course vivante, et elle seule.
 *
 * Une fiche course n'intéresse la recherche que dans les jours qui entourent l'épreuve :
 * avant, pour les partants et les cotes ; après, pour l'arrivée et les rapports. Passé
 * ce délai elle se fige en archive, et Google le sait — sur 21 h de journal il ne
 * consacrait que 7 requêtes sur 267 à ce stock, tout en l'ayant déclaré au sitemap.
 *
 * Quatorze jours en arrière, un jour en avant : le lendemain est publié la veille au
 * soir, et deux semaines couvrent le temps qu'un lecteur met à chercher une arrivée
 * « récente ». Les fiches plus anciennes restent explorables par `/resultats/<jour>`.
 */
const FENETRE_COURSES_JOURS = 14;

async function sitemapCourses(): Promise<Response> {
  const aujourdhui = jourParis();
  const debut = decalerJours(aujourdhui, -FENETRE_COURSES_JOURS);
  const fin = decalerJours(aujourdhui, 1);
  const { courses } = await fetchSeoIndex(debut, fin, 600);

  return rendre(
    // Une course terminée est immuable : son lastmod est le jour de la course. Une
    // course encore à venir voit ses cotes bouger jusqu'au départ — mais un lastmod
    // à la seconde près serait du bruit : le début de journée suffit à dire « ça bouge ».
    courses.map((c) => ({
      loc: `${BASE}/courses/${c.id}`,
      lastmod: c.termine ? iso(c.jour, "21:00:00") : iso(aujourdhui, "04:00:00"),
    })),
  );
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
  if (nom === "resultats") return sitemapResultats();
  if (nom === "courses") return sitemapCourses();

  // Les anciens `/sitemaps/AAAA-MM.xml` tombent ici depuis le 2026-09-21. Un 404 est la
  // réponse juste : le fichier n'existe plus, et l'index ne le déclare plus. Google
  // retire de lui-même un enfant disparu de l'index qu'il a lu.
  return new Response(
    "Sitemap inconnu. Attendu : pages.xml, resultats.xml ou courses.xml.",
    { status: 404, headers: { "Content-Type": "text/plain; charset=utf-8" } },
  );
}
