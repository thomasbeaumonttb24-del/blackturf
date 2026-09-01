import type { Metadata } from "next";
import { fetchTrackRecord, ogBase, twitterBase, jsonLd } from "@/lib/seo";
import { PalmaresResume } from "@/components/seo/PalmaresResume";

/**
 * `/track-record` — palmarès mesuré de l'algorithme.
 *
 * Cette page était en `noindex` et, faute de métadonnées propres, portait le titre et la
 * description de la page d'accueil. C'était l'actif le plus solide du site rendu
 * invisible : elle publie le taux de réussite mesuré sur près de quatre mille courses,
 * la comparaison avec un tirage au sort, ET le rendement réel du favori de l'algorithme,
 * négatif. Un site d'argent qui publie ses pertes est exactement ce que Google cherche à
 * distinguer d'un site qui promet des gains.
 *
 * Le `noindex` était justifié par une raison technique réelle : la page est un composant
 * client intégral, dont le HTML servi ne contenait qu'un squelette. Un résumé rendu côté
 * serveur y remédie — il porte les chiffres en toutes lettres, reste lisible sans
 * JavaScript, et conserve du texte utile même si l'API ne répond pas.
 */
export const revalidate = 900;

// Le titre disait « algorithme » ; personne ne tape ce mot. Les requêtes qui amènent ici
// sont « fiabilité pronostic IA », « taux de réussite IA hippique », « résultats pronostic
// IA » : c'est cette page qui y répond, et c'est le seul endroit du site où le terme est
// adossé à des chiffres vérifiables. Le partage des rôles reste net — /pronostics-ia
// explique la MÉTHODE, cette page publie les RÉSULTATS.
const TITLE = "Résultats de nos pronostics IA — taux de réussite mesuré";
const DESCRIPTION =
  "Ce que l'IA a produit course après course : taux de réussite comparé au hasard et au marché, et le rendement réel du favori — pertes comprises.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/track-record" },
  openGraph: ogBase({ title: TITLE, description: DESCRIPTION, url: "/track-record" }),
  twitter: twitterBase({ title: TITLE, description: DESCRIPTION }),
  robots: { index: true, follow: true },
};

const breadcrumbJsonLd = {
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  itemListElement: [
    { "@type": "ListItem", position: 1, name: "Accueil", item: "https://blackturf.fr" },
    { "@type": "ListItem", position: 2, name: "Palmarès", item: "https://blackturf.fr/track-record" },
  ],
};

export default async function TrackRecordLayout({ children }: { children: React.ReactNode }) {
  const tr = await fetchTrackRecord();
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLd(breadcrumbJsonLd) }}
      />
      {children}
      {/* Sous l'application, la même chose en toutes lettres : lisible sans JavaScript,
          imprimable, et explicite pour un moteur de recherche. Même parti pris que la
          doublure de la fiche course. */}
      <PalmaresResume tr={tr} />
    </>
  );
}
