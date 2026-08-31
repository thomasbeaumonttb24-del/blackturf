import type { Metadata } from "next";
import { OG_IMAGE, jsonLd } from "@/lib/seo";
import { Music } from "lucide-react";
import { SeoHero, Container, Section, Callout, Chip } from "@/components/seo/kit";

export const metadata: Metadata = {
  title: "Comment lire la musique d'un cheval",
  description:
    "Lire la musique d'un cheval (1a 2p 0a Da…) : ce que disent les chiffres, les lettres de discipline et les abréviations de disqualification.",
  alternates: { canonical: "/guides/comment-lire-la-musique" },
  openGraph: {
    title: "Comment lire la musique d'un cheval",
    description: "Décrypter la musique : chiffres, lettres de discipline et abréviations.",
    url: "https://blackturf.fr/guides/comment-lire-la-musique",
    type: "article",
    images: [OG_IMAGE],
  },
};

const LETTERS = [
  ["a", "Attelé (trot attelé)"],
  ["m", "Monté (trot monté)"],
  ["p", "Plat"],
  ["h", "Haies"],
  ["s", "Steeple-chase"],
  ["c", "Cross-country"],
  ["o", "Obstacle (générique)"],
];

const CODES = [
  ["1 à 9", "Place à l'arrivée (1 = victoire, 2 = deuxième, etc.)"],
  ["0", "Non placé (au-delà de la 9e place)"],
  ["D / Da", "Disqualifié (Da = disqualifié pour allure au trot)"],
  ["T", "Tombé"],
  ["A", "Arrêté"],
  ["Ret", "Resté au poteau / non partant"],
  ["(24)", "Séparateur d'année — les courses précédentes datent de 2024"],
];

const EXAMPLE = [
  ["1", "a"], ["2", "a"], ["0", "a"], ["D", "a"], ["3", "a"],
];

export default function GuideMusique() {
  const articleLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: "Comment lire la musique d'un cheval",
    description: metadata.description,
    author: { "@type": "Organization", name: "BlackTurf" },
    publisher: { "@type": "Organization", name: "BlackTurf", logo: { "@type": "ImageObject", url: "https://blackturf.fr/logo.png" } },
    mainEntityOfPage: "https://blackturf.fr/guides/comment-lire-la-musique",
  };
  const breadcrumb = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "Guides", item: "https://blackturf.fr/guides" },
      { "@type": "ListItem", position: 2, name: "Lire la musique", item: "https://blackturf.fr/guides/comment-lire-la-musique" },
    ],
  };

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd(articleLd) }} />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd(breadcrumb) }} />

      <SeoHero
        eyebrow="Guide"
        title="Lire la"
        accent="musique d'un cheval"
        lead="La « musique » résume les dernières performances d'un cheval, de la plus récente à la plus ancienne. Chaque sortie est notée par un chiffre (sa place) suivi d'une lettre (la discipline)."
        breadcrumbs={[{ label: "Accueil", href: "/" }, { label: "Guides", href: "/guides" }, { label: "Lire la musique" }]}
        chips={<><Chip tone="gold"><Music className="h-3 w-3" /> Décryptage</Chip><Chip>Trot · Plat · Obstacle</Chip></>}
      />

      <Container>
        {/* Exemple visuel */}
        <div className="rounded-2xl border border-amber-200 bg-gradient-to-br from-amber-50 to-white p-5 sm:p-6">
          <p className="text-xs font-semibold uppercase tracking-wider text-brand-gold-dark">Exemple — à lire de gauche à droite</p>
          <div className="mt-3 flex flex-wrap items-end gap-2">
            {EXAMPLE.map(([n, l], i) => (
              <span key={i} className="inline-flex items-baseline rounded-lg bg-white px-3 py-2 font-mono text-lg font-bold text-brand-dark ring-1 ring-amber-100">
                <span className={n === "D" ? "text-brand-red" : "text-brand-gold-dark"}>{n}</span>
                <span className="text-sm text-brand-charcoal">{l}</span>
              </span>
            ))}
          </div>
          <p className="mt-3 text-sm text-brand-charcoal">
            Victoire, puis 2e, puis non placé, puis disqualifié, puis 3e — toutes en trot attelé. La course la plus récente est à gauche.
          </p>
        </div>

        <Section title="Les chiffres et abréviations">
          <div className="overflow-hidden rounded-xl border border-gray-200">
            {CODES.map(([c, d], i) => (
              <div key={c} className={`flex gap-4 px-4 py-3 text-sm ${i % 2 ? "bg-amber-50/40" : "bg-white"}`}>
                <span className="w-20 shrink-0 font-mono font-semibold text-brand-gold-dark">{c}</span>
                <span className="text-brand-charcoal">{d}</span>
              </div>
            ))}
          </div>
        </Section>

        <Section title="Les lettres de discipline">
          <div className="grid gap-2.5 sm:grid-cols-2">
            {LETTERS.map(([l, d]) => (
              <div key={l} className="card-hover flex items-center gap-3 rounded-xl border border-gray-200 bg-white px-4 py-3 text-sm">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-gold-soft font-mono font-bold text-brand-gold-dark">{l}</span>
                <span className="text-brand-charcoal">{d}</span>
              </div>
            ))}
          </div>
        </Section>

        <Section title="Ce que la musique révèle (et ses limites)">
          <p className="text-sm leading-relaxed text-brand-charcoal">
            Une série de places rapprochées (1a 2a 1a) signale une forme régulière. Mais attention : la « bonne forme » est aussi celle que le public voit — elle est donc souvent sur-jouée, ce qui écrase la cote. Lire la musique sert à comprendre le contexte (montée de catégorie, changement de discipline, disqualifications), pas à parier mécaniquement.
          </p>
          <p className="mt-3 text-sm leading-relaxed text-brand-charcoal">
            C&apos;est pourquoi BlackTurf croise la musique avec 80+ autres critères (couple jockey/entraîneur, ELO, pedigree, terrain, confrontations directes…) plutôt que de s&apos;y fier seule.
          </p>
        </Section>

        <Callout href="/programme" cta="Voir le programme">
          Voir la musique décodée et colorée de chaque partant sur le programme du jour.
        </Callout>
      </Container>
    </>
  );
}
