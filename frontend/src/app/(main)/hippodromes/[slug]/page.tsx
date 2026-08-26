import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { MapPin, Trophy, ChevronRight, CalendarDays } from "lucide-react";
import { HIPPODROMES, getHippodrome, matchHippodrome } from "@/lib/hippodromes";
import { fetchProgramme, disciplineLabel } from "@/lib/seo";
import { SeoHero, Container, Section, Chip } from "@/components/seo/kit";

export const dynamicParams = false;
export const revalidate = 300;

export function generateStaticParams() {
  return HIPPODROMES.map((h) => ({ slug: h.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const h = getHippodrome(slug);
  if (!h) return { title: "Hippodrome" };
  const title = `${h.name} — programme et courses PMU`;
  const description =
    `${h.name} (${h.city}, ${h.region}) : ${h.disciplines.join(", ")}.` +
    (h.signature ? ` Course phare : ${h.signature}.` : "") +
    " Programme du jour, partants et cotes.";
  return {
    title,
    description,
    alternates: { canonical: `/hippodromes/${h.slug}` },
    openGraph: { title, description, url: `https://blackturf.fr/hippodromes/${h.slug}` },
  };
}

function todayParis(): string {
  return new Intl.DateTimeFormat("fr-CA", { timeZone: "Europe/Paris" }).format(new Date());
}

export default async function HippodromePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const h = getHippodrome(slug);
  if (!h) notFound();

  const prog = await fetchProgramme(todayParis());
  const todayCourses = (prog?.reunions ?? [])
    .filter((r) => matchHippodrome(r.hippodrome, h))
    .flatMap((r) => r.courses ?? []);

  const placeLd = {
    "@context": "https://schema.org",
    "@type": "SportsActivityLocation",
    name: h.name,
    address: { "@type": "PostalAddress", addressLocality: h.city, addressRegion: h.region, addressCountry: "FR" },
    url: `https://blackturf.fr/hippodromes/${h.slug}`,
    description: h.intro,
  };
  const breadcrumb = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "Hippodromes", item: "https://blackturf.fr/hippodromes" },
      { "@type": "ListItem", position: 2, name: h.name, item: `https://blackturf.fr/hippodromes/${h.slug}` },
    ],
  };

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(placeLd) }} />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumb) }} />

      <SeoHero
        eyebrow={`${h.city} · ${h.region}`}
        title={h.name}
        lead={h.intro}
        breadcrumbs={[{ label: "Accueil", href: "/" }, { label: "Hippodromes", href: "/hippodromes" }, { label: h.name }]}
        chips={
          <>
            {h.disciplines.map((d) => <Chip key={d}>{d}</Chip>)}
            {h.signature && <Chip tone="gold"><Trophy className="h-3 w-3" /> {h.signature}</Chip>}
          </>
        }
      />

      <Container>
        <Section title={`Courses du jour à ${h.city}`}>
          {todayCourses.length > 0 ? (
            <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white">
              {todayCourses.map((c, i) => (
                <Link
                  key={c.course_id}
                  href={`/courses/${c.course_id}`}
                  className={`flex items-center justify-between gap-3 px-4 py-3.5 text-sm transition-colors hover:bg-amber-50/50 ${i > 0 ? "border-t border-gray-100" : ""}`}
                >
                  <span className="flex items-center gap-3">
                    <span className="flex h-8 w-12 shrink-0 items-center justify-center rounded-lg bg-gradient-gold-soft font-display text-xs font-bold text-brand-gold-dark">
                      R{c.numero_reunion}C{c.numero}
                    </span>
                    <span className="font-medium text-brand-dark">{c.nom || `Course ${c.numero}`}</span>
                  </span>
                  <span className="flex shrink-0 items-center gap-2 text-xs text-brand-charcoal">
                    {disciplineLabel(c.discipline)}{c.distance ? ` · ${c.distance}m` : ""}
                    <ChevronRight className="h-4 w-4 text-brand-gold-dark/40" />
                  </span>
                </Link>
              ))}
            </div>
          ) : (
            <div className="flex items-center gap-3 rounded-2xl border border-gray-200 bg-gray-50/50 px-4 py-5 text-sm text-brand-charcoal">
              <CalendarDays className="h-5 w-5 text-brand-charcoal" />
              <span>
                Aucune course programmée aujourd&apos;hui sur cet hippodrome. Consultez le{" "}
                <Link href="/programme" className="font-medium text-brand-gold-dark underline">programme du jour</Link>.
              </span>
            </div>
          )}
        </Section>

        <Section title={`Mieux parier sur les courses de ${h.city}`}>
          <p className="text-sm leading-relaxed text-brand-charcoal">
            Quel que soit l&apos;hippodrome, la clé reste la même : trouver les{" "}
            <Link href="/guides/pari-de-valeur" className="font-medium text-brand-gold-dark underline">paris de valeur</Link>.
            Découvrez aussi nos guides sur les{" "}
            <Link href="/guides/types-de-paris-pmu" className="font-medium text-brand-gold-dark underline">types de paris PMU</Link>{" "}
            et la <Link href="/guides/comment-lire-la-musique" className="font-medium text-brand-gold-dark underline">lecture de la musique</Link>.
          </p>
        </Section>
      </Container>
    </>
  );
}
