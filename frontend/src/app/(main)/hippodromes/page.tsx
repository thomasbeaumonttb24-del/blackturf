import type { Metadata } from "next";
import Link from "next/link";
import { MapPin, Trophy, ArrowRight } from "lucide-react";
import { HIPPODROMES } from "@/lib/hippodromes";
import { SeoHero, Container, Callout, Chip } from "@/components/seo/kit";

export const metadata: Metadata = {
  title: "Hippodromes français — courses PMU par hippodrome",
  description:
    "Les grands hippodromes français : Vincennes, ParisLongchamp, Chantilly, Deauville, Auteuil. Disciplines, courses phares et programme du jour.",
  alternates: { canonical: "/hippodromes" },
  openGraph: {
    title: "Hippodromes français — courses PMU",
    description: "Vincennes, ParisLongchamp, Chantilly, Deauville, Auteuil… et le programme du jour.",
    url: "https://blackturf.fr/hippodromes",
  },
};

export default function HippodromesIndex() {
  const sorted = [...HIPPODROMES].sort((a, b) => a.name.localeCompare(b.name, "fr"));
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    name: "Hippodromes français",
    numberOfItems: sorted.length,
    itemListElement: sorted.map((h, i) => ({
      "@type": "ListItem",
      position: i + 1,
      url: `https://blackturf.fr/hippodromes/${h.slug}`,
      name: h.name,
    })),
  };

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />

      <SeoHero
        eyebrow="Hippodromes"
        title="Les hippodromes"
        accent="français"
        lead="Plat, trot, obstacle : découvrez les grands hippodromes de France, leurs disciplines et leurs courses phares — et retrouvez pour chacun le programme PMU du jour analysé par l'IA BlackTurf."
        breadcrumbs={[{ label: "Accueil", href: "/" }, { label: "Hippodromes" }]}
        chips={<><Chip tone="gold"><MapPin className="h-3 w-3" /> {sorted.length} hippodromes</Chip><Chip>Programme du jour inclus</Chip></>}
      />

      <Container>
        <div className="grid gap-5 sm:grid-cols-2">
          {sorted.map((h) => (
            <Link key={h.slug} href={`/hippodromes/${h.slug}`} className="glass-card group flex flex-col rounded-2xl p-5">
              <div className="flex items-start justify-between gap-2">
                <h2 className="font-display text-lg font-semibold text-brand-dark transition-colors group-hover:text-brand-gold-deep">
                  {h.name}
                </h2>
                <ArrowRight className="mt-1 h-4 w-4 shrink-0 text-brand-gold/50 transition-all group-hover:translate-x-0.5 group-hover:text-brand-gold-deep" />
              </div>
              <p className="mt-1 inline-flex items-center gap-1 text-xs text-brand-charcoal/60">
                <MapPin className="h-3 w-3" /> {h.city} · {h.region}
              </p>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {h.disciplines.map((d) => (
                  <span key={d} className="rounded-full border border-gray-200 bg-white px-2 py-0.5 text-[11px] font-medium text-brand-charcoal/80">{d}</span>
                ))}
              </div>
              {h.signature && (
                <p className="mt-3 inline-flex items-center gap-1.5 text-xs font-medium text-brand-gold-dark">
                  <Trophy className="h-3.5 w-3.5" /> {h.signature}
                </p>
              )}
            </Link>
          ))}
        </div>

        <Callout href="/programme" cta="Voir le programme">
          Voir toutes les réunions du jour, tous hippodromes confondus, sur le programme PMU.
        </Callout>
      </Container>
    </>
  );
}
