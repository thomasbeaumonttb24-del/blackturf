import type { Metadata } from "next";
import Link from "next/link";
import { Clock, ArrowRight, Newspaper } from "lucide-react";
import { ARTICLES, formatDateFr } from "@/lib/blog";
import { SeoHero, Container, Callout, Chip } from "@/components/seo/kit";

export const metadata: Metadata = {
  title: "Blog — paris hippiques & analyse PMU",
  description:
    "Le blog BlackTurf : méthodes d'analyse des courses PMU, stratégie de paris de valeur, gestion de bankroll, cotes, trot et intelligence artificielle appliquée aux pronostics.",
  alternates: { canonical: "/blog" },
  openGraph: {
    title: "Blog BlackTurf — paris hippiques & analyse PMU",
    description: "Méthodes, stratégie et data pour mieux parier au PMU. Articles clairs et sans bullshit.",
    url: "https://blackturf.fr/blog",
  },
};

export default function BlogIndex() {
  const [featured, ...rest] = ARTICLES;
  const blogLd = {
    "@context": "https://schema.org",
    "@type": "Blog",
    name: "Blog BlackTurf",
    url: "https://blackturf.fr/blog",
    inLanguage: "fr-FR",
    blogPost: ARTICLES.map((a) => ({
      "@type": "BlogPosting",
      headline: a.title,
      description: a.description,
      datePublished: a.date,
      dateModified: a.updated,
      url: `https://blackturf.fr/blog/${a.slug}`,
    })),
  };

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(blogLd) }} />

      <SeoHero
        eyebrow="Le Blog"
        title="Paris hippiques &"
        accent="analyse PMU"
        lead="Méthodes, stratégie et data pour mieux parier au PMU — sans promesses magiques. Chaque article va droit au but : comprendre, mesurer, décider."
        breadcrumbs={[{ label: "Accueil", href: "/" }, { label: "Blog" }]}
        chips={
          <>
            <Chip tone="gold"><Newspaper className="h-3 w-3" /> {ARTICLES.length} articles</Chip>
            <Chip>Méthode &amp; data</Chip>
            <Chip>100 % gratuit</Chip>
          </>
        }
      />

      <Container>
        {/* Article vedette */}
        {featured && (
          <Link
            href={`/blog/${featured.slug}`}
            className="glass-card group block overflow-hidden rounded-3xl p-6 sm:p-8"
          >
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-brand-gold-dark">
              <span className="rounded-full bg-amber-50 px-2 py-0.5">À la une</span>
              {featured.tags.slice(0, 1).map((t) => (
                <span key={t} className="text-brand-charcoal/50">{t}</span>
              ))}
            </div>
            <h2 className="mt-3 font-display text-2xl font-bold tracking-tight text-brand-dark transition-colors group-hover:text-brand-gold-deep sm:text-3xl">
              {featured.title}
            </h2>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-brand-charcoal/80 sm:text-base">
              {featured.description}
            </p>
            <div className="mt-4 flex items-center gap-3 text-xs text-brand-charcoal/60">
              <time dateTime={featured.date}>{formatDateFr(featured.date)}</time>
              <span className="inline-flex items-center gap-1"><Clock className="h-3 w-3" /> {featured.readingMinutes} min</span>
              <span className="inline-flex items-center gap-1 font-medium text-brand-gold-deep">
                Lire <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
              </span>
            </div>
          </Link>
        )}

        {/* Grille des autres articles */}
        <div className="mt-6 grid gap-5 sm:grid-cols-2">
          {rest.map((a) => (
            <Link
              key={a.slug}
              href={`/blog/${a.slug}`}
              className="glass-card group flex flex-col rounded-2xl p-5"
            >
              <div className="flex flex-wrap items-center gap-2 text-[11px] text-brand-charcoal/55">
                <time dateTime={a.date}>{formatDateFr(a.date)}</time>
                <span>·</span>
                <span className="inline-flex items-center gap-1"><Clock className="h-3 w-3" /> {a.readingMinutes} min</span>
              </div>
              <h3 className="mt-2 font-display text-lg font-semibold leading-snug text-brand-dark transition-colors group-hover:text-brand-gold-deep">
                {a.title}
              </h3>
              <p className="mt-1.5 flex-1 text-sm leading-relaxed text-brand-charcoal/75">{a.description}</p>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {a.tags.slice(0, 2).map((t) => (
                  <span key={t} className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-brand-gold-dark">
                    {t}
                  </span>
                ))}
              </div>
            </Link>
          ))}
        </div>

        <Callout href="/programme" cta="Voir le programme">
          Envie de passer à la pratique ? Le programme PMU du jour est analysé course par course par
          l&apos;IA BlackTurf — partants, cotes en direct et paris de valeur.
        </Callout>
      </Container>
    </>
  );
}
