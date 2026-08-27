import type { Metadata } from "next";
import Link from "next/link";
import {
  fetchJoursResultats,
  jourParis,
  jourCourtAnnee,
  moisLong,
  ogBase,
  twitterBase,
  jsonLd,
} from "@/lib/seo";
import { SeoHero, Container, Section, Callout } from "@/components/seo/kit";

/**
 * `/resultats/archives` — toutes les journées d'arrivées, groupées par mois.
 *
 * Raison d'être : jusqu'au 2026-08-26, une journée passée n'était atteignable que par la
 * chaîne « ← journée précédente », de proche en proche. Atteindre le mois de septembre
 * 2025 demandait près de trois cent cinquante clics depuis l'accueil. Les pages
 * existaient, répondaient 200 et s'annonçaient indexables — mais aucun robot ne descend
 * à cette profondeur, et le sitemap ne listait que les trente derniers jours.
 *
 * Cette page ramène chacune de ces journées à trois clics de l'accueil (accueil →
 * résultats → archives → la journée), ce qui est le seuil au-delà duquel une page cesse
 * d'être explorée régulièrement.
 */
export const revalidate = 1800;

const TITLE = "Archives des résultats PMU — toutes les arrivées";
const DESCRIPTION =
  "Toutes les journées de courses PMU archivées : arrivées officielles et rapports, mois par mois, depuis septembre 2025.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/resultats/archives" },
  openGraph: ogBase({ title: TITLE, description: DESCRIPTION, url: "/resultats/archives" }),
  twitter: twitterBase({ title: TITLE, description: DESCRIPTION }),
};

export default async function ArchivesResultatsPage() {
  const jours = await fetchJoursResultats();
  const aujourdhui = jourParis();

  // Regroupement par mois, du plus récent au plus ancien.
  const parMois = new Map<string, Array<{ jour: string; nb_courses: number }>>();
  for (const j of jours) {
    const ym = j.jour.slice(0, 7);
    if (!parMois.has(ym)) parMois.set(ym, []);
    parMois.get(ym)!.push(j);
  }
  const mois = [...parMois.entries()].sort((a, b) => b[0].localeCompare(a[0]));
  const totalCourses = jours.reduce((s, j) => s + j.nb_courses, 0);

  const breadcrumbJsonLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "Accueil", item: "https://blackturf.fr" },
      { "@type": "ListItem", position: 2, name: "Résultats", item: "https://blackturf.fr/resultats" },
      { "@type": "ListItem", position: 3, name: "Archives", item: "https://blackturf.fr/resultats/archives" },
    ],
  };

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLd(breadcrumbJsonLd) }}
      />

      <SeoHero
        eyebrow="Arrivées officielles"
        breadcrumbs={[
          { label: "Accueil", href: "/" },
          { label: "Résultats", href: "/resultats" },
          { label: "Archives" },
        ]}
        title="Archives des résultats PMU"
        lead={
          jours.length
            ? `${jours.length.toLocaleString("fr-FR")} journées de courses archivées, ${totalCourses.toLocaleString(
                "fr-FR",
              )} arrivées au total. Les rapports d'une course ne changent plus une fois publiés : chacune de ces pages reste exacte indéfiniment.`
            : "Les journées archivées apparaîtront ici dès la publication des premières arrivées."
        }
      />

      <Container>
        {mois.map(([ym, liste]) => (
          <Section key={ym} title={moisLong(ym)}>
            <ul className="flex flex-wrap gap-2">
              {liste
                .slice()
                .sort((a, b) => b.jour.localeCompare(a.jour))
                .map((j) => (
                  <li key={j.jour}>
                    <Link
                      href={j.jour === aujourdhui ? "/resultats" : `/resultats/${j.jour}`}
                      className="inline-flex items-baseline gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-brand-charcoal transition-colors hover:border-brand-gold-deep hover:text-brand-gold-dark"
                      // L'intitulé porte la date complète : un lien « 12 » n'apprend rien
                      // à qui le lit hors contexte, robot compris.
                      title={`Arrivées et rapports du ${jourCourtAnnee(j.jour)}`}
                    >
                      <span className="font-display font-semibold text-brand-dark">
                        {jourCourtAnnee(j.jour)}
                      </span>
                      <span className="text-[11px] text-brand-charcoal">
                        {j.nb_courses} course{j.nb_courses > 1 ? "s" : ""}
                      </span>
                    </Link>
                  </li>
                ))}
            </ul>
          </Section>
        ))}

        {!mois.length && (
          <p className="text-sm text-brand-charcoal">
            Aucune journée archivée pour le moment. Voir le{" "}
            <Link href="/programme" className="font-medium text-brand-gold-dark underline">
              programme du jour
            </Link>
            .
          </p>
        )}

        <Callout href="/resultats" cta="Arrivées du jour">
          Les rapports d&apos;une course passée disent ce qu&apos;elle a payé — pas ce que paiera la
          suivante. BlackTurf note chaque pronostic aux rapports réels du PMU et publie le bilan,
          gains comme pertes.
        </Callout>
      </Container>
    </>
  );
}
