import type { Metadata } from "next";
import { ogBase, twitterBase, jsonLd } from "@/lib/seo";
import { SeoHero, Container } from "@/components/seo/kit";
import { OutsidersPage } from "@/components/outsiders/Outsiders";

const title = "Outsiders du jour : les grosses cotes capables de se placer";
const description =
  "Chaque jour, les chevaux cotés 15 et plus que notre IA juge sous-estimés, avec leur chance réelle de finir placés et le bilan honnête des jours précédents.";

export const metadata: Metadata = {
  title,
  description,
  alternates: { canonical: "/outsiders" },
  openGraph: ogBase({ title, description, url: "/outsiders" }),
  twitter: twitterBase({ title, description }),
};

const breadcrumbJsonLd = {
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  itemListElement: [
    { "@type": "ListItem", position: 1, name: "Accueil", item: "https://blackturf.fr" },
    { "@type": "ListItem", position: 2, name: "Courses du jour", item: "https://blackturf.fr/programme" },
    { "@type": "ListItem", position: 3, name: "Outsiders du jour", item: "https://blackturf.fr/outsiders" },
  ],
};

export default function OutsidersDuJourPage() {
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd(breadcrumbJsonLd) }} />
      <SeoHero
        eyebrow="Mis à jour toutes les 5 minutes"
        breadcrumbs={[
          { label: "Accueil", href: "/" },
          { label: "Courses du jour", href: "/programme" },
          { label: "Outsiders du jour" },
        ]}
        title="Outsiders du jour"
        accent="— les grosses cotes à suivre"
        lead="Les chevaux cotés 15 et plus que notre cerveau des outsiders juge capables de finir dans les places, avec leur chance estimée, leurs raisons et le bilan réel."
      />
      <Container className="max-w-5xl">
        <OutsidersPage />
      </Container>
    </>
  );
}
