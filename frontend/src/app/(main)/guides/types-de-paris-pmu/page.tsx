import type { Metadata } from "next";
import { OG_IMAGE } from "@/lib/seo";
import { Ticket } from "lucide-react";
import { SeoHero, Container, Section, DefCard, Callout, Chip } from "@/components/seo/kit";

export const metadata: Metadata = {
  title: "Tous les types de paris PMU expliqués",
  description:
    "Guide complet des paris PMU : Simple Gagnant et Placé, Couplé, Trio, Tiercé, Quarté+, Quinté+, 2sur4, Multi, Pick5. Conditions de gain, places payées selon le nombre de partants.",
  alternates: { canonical: "/guides/types-de-paris-pmu" },
  openGraph: {
    title: "Tous les types de paris PMU expliqués",
    description: "Conditions de gain et places payées de chaque pari PMU.",
    url: "https://blackturf.fr/guides/types-de-paris-pmu",
    type: "article",
    images: [OG_IMAGE],
  },
};

const FAQ = [
  { q: "Combien de places sont payées au Simple Placé ?", a: "De 4 à 7 partants, 2 places sont payées (1er et 2e). À partir de 8 partants, 3 places sont payées (1er, 2e, 3e). En dessous de 4 partants, le Placé n'est pas proposé." },
  { q: "Quelle différence entre Tiercé et Trio ?", a: "Les deux portent sur les 3 premiers chevaux. Le Trio se joue dans le désordre (l'ordre n'importe pas, dès 8 partants). Le Tiercé distingue l'ordre exact (rapport plus élevé) du désordre." },
  { q: "Qu'est-ce que le 2sur4 ?", a: "Il faut désigner 2 chevaux parmi les 4 premiers à l'arrivée, dans le désordre. Le 2sur4 est proposé à partir de 10 partants." },
  { q: "Comment fonctionne le Quinté+ ?", a: "Le Quinté+ porte sur les 5 premiers chevaux, mise de base 2€. Il paie plusieurs rapports : Ordre, Désordre, Bonus 4, Bonus 4 sur 5 et Bonus 3." },
];

export default function GuideTypesParis() {
  const articleLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: "Tous les types de paris PMU expliqués",
    description: metadata.description,
    author: { "@type": "Organization", name: "BlackTurf" },
    publisher: { "@type": "Organization", name: "BlackTurf", logo: { "@type": "ImageObject", url: "https://blackturf.fr/logo.png" } },
    mainEntityOfPage: "https://blackturf.fr/guides/types-de-paris-pmu",
  };
  const faqLd = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: FAQ.map((f) => ({ "@type": "Question", name: f.q, acceptedAnswer: { "@type": "Answer", text: f.a } })),
  };
  const breadcrumb = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "Guides", item: "https://blackturf.fr/guides" },
      { "@type": "ListItem", position: 2, name: "Types de paris PMU", item: "https://blackturf.fr/guides/types-de-paris-pmu" },
    ],
  };

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(articleLd) }} />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(faqLd) }} />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumb) }} />

      <SeoHero
        eyebrow="Guide"
        title="Tous les types de"
        accent="paris PMU"
        lead="Chaque course PMU propose plusieurs paris, du plus simple au plus relevé. Voici leurs conditions de gain et le nombre de places payées — la règle qui change le plus souvent selon le nombre de partants."
        breadcrumbs={[{ label: "Accueil", href: "/" }, { label: "Guides", href: "/guides" }, { label: "Types de paris" }]}
        chips={<><Chip tone="gold"><Ticket className="h-3 w-3" /> 11 paris</Chip><Chip>Conditions de gain</Chip></>}
      />

      <Container>
        {/* Highlight règle des places */}
        <div className="rounded-2xl border border-amber-200 bg-gradient-to-br from-amber-50 to-white p-5 sm:p-6">
          <h2 className="font-display text-lg font-bold text-brand-dark">Places payées : la règle clé</h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <div className="rounded-xl bg-white p-4 text-center ring-1 ring-amber-100">
              <div className="font-display text-2xl font-bold text-gradient">4 à 7</div>
              <div className="mt-1 text-xs text-brand-charcoal">partants → 2 places (1er, 2e)</div>
            </div>
            <div className="rounded-xl bg-white p-4 text-center ring-1 ring-amber-100">
              <div className="font-display text-2xl font-bold text-gradient">8 +</div>
              <div className="mt-1 text-xs text-brand-charcoal">partants → 3 places (1er, 2e, 3e)</div>
            </div>
            <div className="rounded-xl bg-white p-4 text-center ring-1 ring-amber-100">
              <div className="font-display text-2xl font-bold text-brand-charcoal">&lt; 4</div>
              <div className="mt-1 text-xs text-brand-charcoal">partants → pas de Placé</div>
            </div>
          </div>
          <p className="mt-3 text-xs text-brand-charcoal">S&apos;applique au Simple Placé, au Couplé Placé et au Trio.</p>
        </div>

        <Section title="Sur un seul cheval">
          <div className="grid gap-3 sm:grid-cols-2">
            <DefCard term="Simple Gagnant">Votre cheval doit finir 1er.</DefCard>
            <DefCard term="Simple Placé">Votre cheval doit finir dans les places payées (voir règle ci-dessus).</DefCard>
          </div>
        </Section>

        <Section title="Sur deux chevaux">
          <div className="grid gap-3 sm:grid-cols-2">
            <DefCard term="Couplé Gagnant">Les 2 chevaux finissent 1er et 2e, ordre indifférent.</DefCard>
            <DefCard term="Couplé Placé">Les 2 chevaux finissent dans les 3 premiers (à partir de 8 partants).</DefCard>
            <DefCard term="Couplé Ordre">Les 2 chevaux dans l&apos;ordre exact (1er puis 2e).</DefCard>
            <DefCard term="2sur4">2 chevaux parmi les 4 premiers, dans le désordre. À partir de 10 partants.</DefCard>
          </div>
        </Section>

        <Section title="Sur trois chevaux et plus">
          <div className="grid gap-3 sm:grid-cols-2">
            <DefCard term="Trio">Les 3 premiers dans le désordre (ordre exact requis si moins de 8 partants).</DefCard>
            <DefCard term="Tiercé">Les 3 premiers : rapport Ordre (exact) supérieur au Désordre.</DefCard>
            <DefCard term="Quarté+">Les 4 premiers : rapports Ordre, Désordre et Bonus 3.</DefCard>
            <DefCard term="Quinté+">Les 5 premiers, mise 2€ : Ordre, Désordre, Bonus 4, Bonus 4 sur 5, Bonus 3.</DefCard>
          </div>
        </Section>

        <Section title="Paris à gros potentiel">
          <div className="grid gap-3 sm:grid-cols-2">
            <DefCard term="Multi">Les 4 premiers en désordre, sélection de 4 à 7 chevaux, mise plate 3€. À partir de 14 partants (Mini Multi de 10 à 13). Le Multi en 4 paie bien plus que le Multi en 7.</DefCard>
            <DefCard term="Pick5">Les 5 premiers en désordre uniquement, mise 1€, sans bonus.</DefCard>
          </div>
        </Section>

        <Callout href="/programme" cta="Voir le programme">
          BlackTurf calcule pour chaque course les paris au meilleur rapport probabilité/cote.
        </Callout>

        <Section title="Questions fréquentes">
          <div className="space-y-3">
            {FAQ.map((f) => (
              <details key={f.q} className="group rounded-xl border border-gray-200 bg-white p-4">
                <summary className="cursor-pointer list-none font-display text-sm font-semibold text-brand-dark marker:hidden">
                  {f.q}
                </summary>
                <p className="mt-2 text-sm leading-relaxed text-brand-charcoal">{f.a}</p>
              </details>
            ))}
          </div>
        </Section>
      </Container>
    </>
  );
}
