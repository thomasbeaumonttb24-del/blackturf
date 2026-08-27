import type { Metadata } from "next";
import { OG_IMAGE, jsonLd } from "@/lib/seo";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Clock, ArrowRight, ArrowLeft } from "lucide-react";
import { ARTICLES, getArticle, formatDateFr } from "@/lib/blog";
import { SeoHero, Container, Chip } from "@/components/seo/kit";

export const dynamicParams = false;

export function generateStaticParams() {
  return ARTICLES.map((a) => ({ slug: a.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const a = getArticle(slug);
  if (!a) return { title: "Article introuvable" };
  return {
    title: a.title,
    description: a.description,
    alternates: { canonical: `/blog/${a.slug}` },
    openGraph: {
      title: `${a.title}`,
      description: a.description,
      url: `https://blackturf.fr/blog/${a.slug}`,
      type: "article",
      publishedTime: a.date,
      modifiedTime: a.updated,
      tags: a.tags,
      images: [OG_IMAGE],
    },
  };
}

export default async function BlogArticle({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const a = getArticle(slug);
  if (!a) notFound();
  const { Body } = a;

  const articleLd = {
    "@context": "https://schema.org",
    "@type": "BlogPosting",
    headline: a.title,
    description: a.description,
    datePublished: a.date,
    dateModified: a.updated,
    keywords: a.tags.join(", "),
    // L'auteur était déclaré comme l'organisation elle-même, et n'apparaissait nulle part
    // sur la page. Sur un sujet d'argent, un contenu sans auteur identifiable ne dit pas
    // qui répond de ce qui est écrit. La personne qui édite le site — nommée dans les
    // mentions légales — signe désormais les articles, et cette signature est AFFICHÉE
    // sous le titre : un balisage qui n'a pas de contrepartie visible n'a pas lieu d'être.
    author: {
      "@type": "Person",
      name: "Thomas Beaumont",
      url: "https://blackturf.fr/mentions-legales",
    },
    publisher: {
      "@type": "Organization",
      name: "BlackTurf",
      logo: { "@type": "ImageObject", url: "https://blackturf.fr/logo.png" },
    },
    mainEntityOfPage: `https://blackturf.fr/blog/${a.slug}`,
  };
  // Le fil d'Ariane partait de « Blog » : la racine du site n'y figurait pas, alors que le
  // fil affiché en haut de page, lui, commence bien par « Accueil ». Les deux disent
  // maintenant la même chose.
  const breadcrumb = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "Accueil", item: "https://blackturf.fr" },
      { "@type": "ListItem", position: 2, name: "Blog", item: "https://blackturf.fr/blog" },
      { "@type": "ListItem", position: 3, name: a.title, item: `https://blackturf.fr/blog/${a.slug}` },
    ],
  };

  const related = ARTICLES.filter((x) => x.slug !== a.slug).slice(0, 3);

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd(articleLd) }} />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd(breadcrumb) }} />

      <SeoHero
        eyebrow={a.tags[0]}
        title={a.title}
        breadcrumbs={[{ label: "Accueil", href: "/" }, { label: "Blog", href: "/blog" }, { label: a.tags[0] ?? "Article" }]}
        chips={
          <>
            {/* Signature visible : contrepartie du `author` déclaré en données
                structurées, et information que le lecteur est en droit d'avoir. */}
            <Chip>
              <Link href="/mentions-legales" className="hover:underline">
                Par Thomas Beaumont
              </Link>
            </Chip>
            <Chip><time dateTime={a.date}>{formatDateFr(a.date)}</time></Chip>
            {a.updated !== a.date && (
              <Chip>
                Mis à jour le <time dateTime={a.updated}>{formatDateFr(a.updated)}</time>
              </Chip>
            )}
            <Chip><Clock className="h-3 w-3" /> {a.readingMinutes} min de lecture</Chip>
            {a.tags.slice(1).map((t) => <Chip key={t} tone="gold">{t}</Chip>)}
          </>
        }
      />

      <Container className="max-w-3xl">
        <article className="blog-prose">
          <Body />
        </article>

        <div className="mt-10 border-t border-gray-200 pt-6">
          <Link href="/blog" className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-gold-dark hover:underline">
            <ArrowLeft className="h-4 w-4" /> Tous les articles
          </Link>
        </div>

        {related.length > 0 && (
          <section className="mt-10">
            <h2 className="font-display text-xl font-bold tracking-tight text-brand-dark">À lire aussi</h2>
            <div className="mt-4 grid gap-4 sm:grid-cols-3">
              {related.map((r) => (
                <Link key={r.slug} href={`/blog/${r.slug}`} className="glass-card group rounded-2xl p-4">
                  <div className="text-[11px] text-brand-charcoal">{r.readingMinutes} min</div>
                  <h3 className="mt-1 font-display text-sm font-semibold leading-snug text-brand-dark transition-colors group-hover:text-brand-gold-dark">
                    {r.title}
                  </h3>
                  <span className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-brand-gold-dark">
                    Lire <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
                  </span>
                </Link>
              ))}
            </div>
          </section>
        )}
      </Container>
    </>
  );
}
