import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight, Layers } from "lucide-react";
import { DISCIPLINES } from "@/lib/disciplines";
import { SeoHero, Container, Callout, Chip } from "@/components/seo/kit";

export const metadata: Metadata = {
  title: "Disciplines hippiques : trot, plat, obstacle",
  description:
    "Trot, plat, obstacle : comprendre les trois disciplines des courses PMU, leurs facteurs clés et leurs paris. Et le programme du jour course par course, par discipline.",
  alternates: { canonical: "/disciplines" },
  openGraph: {
    title: "Disciplines hippiques : trot, plat, obstacle",
    description: "Comprendre le trot, le plat et l'obstacle, et le programme du jour par discipline.",
    url: "https://blackturf.fr/disciplines",
  },
};

export default function DisciplinesIndex() {
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    name: "Disciplines hippiques",
    numberOfItems: DISCIPLINES.length,
    itemListElement: DISCIPLINES.map((d, i) => ({
      "@type": "ListItem",
      position: i + 1,
      url: `https://blackturf.fr/disciplines/${d.slug}`,
      name: d.short,
    })),
  };

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />

      <SeoHero
        eyebrow="Disciplines"
        title="Les disciplines"
        accent="hippiques"
        lead="Les courses PMU se répartissent en trois disciplines, chacune avec ses codes et ses facteurs de réussite. Comprenez-les, puis retrouvez le programme du jour filtré par discipline."
        breadcrumbs={[{ label: "Accueil", href: "/" }, { label: "Disciplines" }]}
        chips={<><Chip tone="gold"><Layers className="h-3 w-3" /> 3 disciplines</Chip><Chip>Courses du jour incluses</Chip></>}
      />

      <Container>
        <div className="grid gap-5 sm:grid-cols-3">
          {DISCIPLINES.map((d) => (
            <Link key={d.slug} href={`/disciplines/${d.slug}`} className="glass-card group flex flex-col rounded-2xl p-5">
              <h2 className="font-display text-lg font-semibold text-brand-dark transition-colors group-hover:text-brand-gold-dark">
                {d.short}
              </h2>
              <p className="mt-2 flex-1 text-sm leading-relaxed text-brand-charcoal">{d.intro}</p>
              <span className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-brand-gold-dark">
                Découvrir <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
              </span>
            </Link>
          ))}
        </div>

        <Callout href="/programme" cta="Voir le programme">
          Voir toutes les réunions du jour, toutes disciplines confondues, sur le programme PMU.
        </Callout>
      </Container>
    </>
  );
}
