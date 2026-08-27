import type { Metadata } from "next";
import { OG_IMAGE, filAriane } from "@/lib/seo";
import { Ticket, Music, Target, BookOpen } from "lucide-react";
import { SeoHero, Container, LinkCard, Callout, Chip } from "@/components/seo/kit";

export const metadata: Metadata = {
  title: "Guides paris hippiques PMU",
  description:
    "Guides gratuits pour parier au PMU : types de paris, lecture de la musique d'un cheval, stratégie de pari de valeur.",
  alternates: { canonical: "/guides" },
  openGraph: {
    title: "Guides paris hippiques PMU",
    description: "Apprenez à parier au PMU : types de paris, lecture de la musique, paris de valeur.",
    url: "https://blackturf.fr/guides",
    images: [OG_IMAGE],
  },
};

const GUIDES = [
  {
    href: "/guides/types-de-paris-pmu",
    title: "Tous les types de paris PMU",
    desc: "Simple, Couplé, Trio, Tiercé, Quarté+, Quinté+, 2sur4, Multi, Pick5 : conditions de gain et places payées.",
    icon: <Ticket className="h-5 w-5" />,
  },
  {
    href: "/guides/comment-lire-la-musique",
    title: "Comment lire la musique d'un cheval",
    desc: "Décrypter la musique (1a 2p 0a Da…) : chiffres, lettres de discipline et disqualifications.",
    icon: <Music className="h-5 w-5" />,
  },
  {
    href: "/guides/pari-de-valeur",
    title: "Le pari de valeur expliqué",
    desc: "Probabilité vs cote, espérance de gain, et comment viser la valeur plutôt que le favori.",
    icon: <Target className="h-5 w-5" />,
  },
];

export default function GuidesIndex() {
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    name: "Guides paris hippiques PMU",
    itemListElement: GUIDES.map((g, i) => ({
      "@type": "ListItem",
      position: i + 1,
      url: `https://blackturf.fr${g.href}`,
      name: g.title,
    })),
  };

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(filAriane([{ nom: "Accueil", url: "/" }, { nom: "Guides" }])) }} />

      <SeoHero
        eyebrow="Ressources"
        title="Guides des paris"
        accent="hippiques PMU"
        lead="Tout pour comprendre et mieux parier sur les courses PMU : les types de paris et leurs conditions de gain, la lecture de la musique des chevaux, et la logique du pari de valeur."
        breadcrumbs={[{ label: "Accueil", href: "/" }, { label: "Guides" }]}
        chips={
          <>
            <Chip tone="gold"><BookOpen className="h-3 w-3" /> Guides gratuits</Chip>
            <Chip>Niveau débutant à confirmé</Chip>
          </>
        }
      />

      <Container>
        <div className="grid gap-5 sm:grid-cols-2">
          {GUIDES.map((g) => (
            <LinkCard key={g.href} href={g.href} title={g.title} desc={g.desc} icon={g.icon} accent="Lire le guide" />
          ))}
        </div>

        <Callout href="/programme" cta="Voir le programme">
          Passez à la pratique : le programme PMU du jour est analysé course par course par l&apos;IA
          BlackTurf — partants, cotes en direct et paris de valeur.
        </Callout>
      </Container>
    </>
  );
}
