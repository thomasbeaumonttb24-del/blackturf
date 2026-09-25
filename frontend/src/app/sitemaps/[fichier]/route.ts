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

/**
 * Un sitemap VIDE est un mensonge, pas une réponse.
 *
 * `fetchSeoIndex` et `fetchJoursResultats` renvoient un tableau vide quand l'API ne répond
 * pas — c'est leur contrat, et il convient partout ailleurs. Ici il produirait un `<urlset>`
 * sans une seule URL, que Next mettrait en cache pour une heure et que Google lirait comme
 * « ce site n'a plus de pages ». Un 503 dit la vérité : indisponible, reviens.
 */
function indisponible(quoi: string): Response {
  return new Response(`Sitemap ${quoi} momentanément indisponible.`, {
    status: 503,
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "no-store",
      "Retry-After": "600",
    },
  });
}

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
async function sitemapPages(): Promise<Response> {
  const aujourdhui = jourParis();
  // Les pages hippodrome et discipline embarquent le programme du jour : leur contenu
  // change bien chaque jour, mais une fois — pas à chaque régénération.
  const debutDeJournee = iso(aujourdhui, "04:00:00");

  /* Le programme, le quinté et les arrivées changent PLUSIEURS FOIS PAR JOUR : cotes qui
   * bougent jusqu'au départ, non-partants déclarés, arrivées publiées au fil de l'après-midi.
   *
   * Ni `new Date()` ni le début de journée ne conviennent. Le premier déplace la date à
   * chaque régénération du sitemap, même quand rien n'a bougé — un lastmod menteur, que
   * Google finit par ignorer pour tout le fichier. Le second sous-déclare l'inverse : il
   * dit « rien n'a changé depuis 4 h » d'une page dont les cotes viennent d'être réécrites.
   *
   * `derniere_maj` est la dernière écriture RÉELLE en base sur une course du jour. Elle
   * bouge quand le contenu bouge, et seulement là. Repli sur le début de journée si l'API
   * ne répond pas — jamais sur l'heure courante. */
  const { derniereMaj } = await fetchSeoIndex(aujourdhui, aujourdhui, 600);
  const majDuJour = derniereMaj ?? debutDeJournee;

  const entrees: Entree[] = [
    { loc: `${BASE}/programme`, lastmod: majDuJour },
    { loc: `${BASE}/quinte-du-jour`, lastmod: majDuJour },
    { loc: `${BASE}/resultats`, lastmod: majDuJour },

    { loc: BASE, lastmod: iso(MAJ.accueil) },
    { loc: `${BASE}/tarifs`, lastmod: iso(MAJ.tarifs) },
    { loc: `${BASE}/pronostics-ia`, lastmod: iso(MAJ.pronosticsIa) },
    // Le palmarès est passé en `index` le 2026-08-26 mais était resté hors du sitemap.
    // Son contenu chiffré est régénéré toutes les quinze minutes.
    { loc: `${BASE}/track-record`, lastmod: debutDeJournee },
    // Défi du mois : classement public, mis à jour après chaque arrivée.
    { loc: `${BASE}/defi`, lastmod: debutDeJournee },
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
  if (!jours.length) return indisponible("des résultats");

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
  if (!courses.length) return indisponible("des courses");

  return rendre(
    // Une course COURUE est immuable : arrivée et rapports ne changent plus, son lastmod
    // est le soir de la course. Une course À VENIR, elle, bouge jusqu'au départ — cotes,
    // non-partants, prévisions — et c'est `maj` (l'`updated_at` de la base) qui le dit,
    // pas une heure conventionnelle. Repli sur le début de journée si le champ manque,
    // jamais sur l'heure courante : une date inventée vaut moins qu'une date prudente.
    courses.map((c) => ({
      loc: `${BASE}/courses/${c.id}`,
      lastmod: c.termine
        ? iso(c.jour, "21:00:00")
        : (c.maj ?? iso(aujourdhui, "04:00:00")),
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

  if (nom === "pages") return await sitemapPages();
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
