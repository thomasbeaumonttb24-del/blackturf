import type { Metadata } from "next";
import { OG_IMAGE } from "@/lib/seo";
import Link from "next/link";
import { Container, SeoHero, Section } from "@/components/seo/kit";
import { NewsletterForm } from "@/components/newsletter/NewsletterForm";

export const metadata: Metadata = {
  title: "La lettre BlackTurf — le bilan chiffré de la semaine",
  description:
    "Chaque lundi : ce que le modèle a bien vu, ce qu'il a raté, et le résultat réel de la semaine — gains comme pertes. Un envoi, sans engagement.",
  alternates: { canonical: "/newsletter" },
  openGraph: {
    title: "La lettre BlackTurf",
    description: "Le bilan chiffré de la semaine, gains comme pertes. Un envoi par lundi.",
    url: "https://blackturf.fr/newsletter",
    images: [OG_IMAGE],
  },
};

export default function NewsletterPage() {
  return (
    <>
      <SeoHero
        eyebrow="Un envoi par semaine"
        breadcrumbs={[{ label: "Accueil", href: "/" }, { label: "La lettre" }]}
        title="La lettre"
        accent="du lundi"
        lead="Le bilan chiffré de la semaine écoulée : ce que le modèle a bien vu, ce qu'il a raté, et le résultat réel. Pertes comprises."
      />

      <Container>
        <NewsletterForm source="page-newsletter" />

        <Section title="Ce qu'il y a dedans">
          <ul className="space-y-3 text-sm leading-relaxed text-brand-charcoal">
            <li>
              <strong className="text-brand-dark">Le bilan de la semaine, en euros.</strong> Ce
              que les plans ont rapporté ou coûté, aux rapports réels publiés par le PMU — pas à
              des rapports théoriques.
            </li>
            <li>
              <strong className="text-brand-dark">Les meilleurs plans bénéficiaires.</strong> Jusqu’à trois
              plans classés par bénéfice net, avec la mise totale et le retour, mise incluse.
              Chaque plan a été enregistré avant le départ.
            </li>
            <li>
              <strong className="text-brand-dark">Un enseignement utilisable.</strong> Un point
              de méthode pour comprendre les résultats, les mises et le bénéfice net.
            </li>
          </ul>
        </Section>

        <Section title="Ce qu'il n'y a pas dedans">
          <p className="text-sm leading-relaxed text-brand-charcoal">
            Aucun pronostic « garanti » ni aucune promesse de gain. Le bilan inclut
            les plans perdants et distingue les profils, qui sont des stratégies alternatives.
            Les résultats des plans de référence ne sont pas les gains personnels des utilisateurs.
            Envoi le lundi dès 9 h, heure de Paris ; si les règlements sont incomplets,
            le bilan est différé.
          </p>
        </Section>

        <Section title="Vos données">
          <p className="text-sm leading-relaxed text-brand-charcoal">
            Votre adresse ne sert qu&apos;à cet envoi. Elle n&apos;est ni revendue, ni partagée.
            Rien ne part tant que vous n&apos;avez pas cliqué le lien de confirmation, et chaque
            lettre porte un lien de désinscription en un clic. Le détail est dans la{" "}
            <Link
              href="/confidentialite"
              className="font-medium text-brand-gold-dark hover:underline"
            >
              politique de confidentialité
            </Link>
            .
          </p>
        </Section>
      </Container>
    </>
  );
}
