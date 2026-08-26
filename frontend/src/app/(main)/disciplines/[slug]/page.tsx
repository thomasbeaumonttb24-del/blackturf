import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Check, ChevronRight, CalendarDays } from "lucide-react";
import { DISCIPLINES, getDiscipline, matchDiscipline } from "@/lib/disciplines";
import { fetchProgramme, disciplineLabel, titleCase, OG_IMAGE } from "@/lib/seo";
import { SeoHero, Container, Section, Chip } from "@/components/seo/kit";

export const dynamicParams = false;
export const revalidate = 300;

export function generateStaticParams() {
  return DISCIPLINES.map((d) => ({ slug: d.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const d = getDiscipline(slug);
  if (!d) return { title: "Discipline" };
  return {
    title: d.name,
    // Google tronque vers 155-160 caractères : l'intro de la discipline suffit, on
    // n'ajoute plus de queue promotionnelle qui serait coupée de toute façon.
    description: d.intro.slice(0, 155),
    alternates: { canonical: `/disciplines/${d.slug}` },
    openGraph: { title: `${d.name}`, description: d.intro, url: `https://blackturf.fr/disciplines/${d.slug}`, images: [OG_IMAGE] },
  };
}

function todayParis(): string {
  return new Intl.DateTimeFormat("fr-CA", { timeZone: "Europe/Paris" }).format(new Date());
}

export default async function DisciplinePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const d = getDiscipline(slug);
  if (!d) notFound();

  const prog = await fetchProgramme(todayParis());
  const courses = (prog?.reunions ?? []).flatMap((r) =>
    (r.courses ?? [])
      .filter((c) => matchDiscipline(c.discipline, d))
      .map((c) => ({ ...c, hippo: r.hippodrome })),
  );

  const breadcrumb = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "Disciplines", item: "https://blackturf.fr/disciplines" },
      { "@type": "ListItem", position: 2, name: d.short, item: `https://blackturf.fr/disciplines/${d.slug}` },
    ],
  };
  const low = d.short.toLowerCase();

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumb) }} />

      <SeoHero
        eyebrow="Discipline"
        title={d.name}
        lead={d.intro}
        breadcrumbs={[{ label: "Accueil", href: "/" }, { label: "Disciplines", href: "/disciplines" }, { label: d.short }]}
        chips={<Chip tone="gold">{d.short}</Chip>}
      />

      <Container>
        <Section title={`Les facteurs clés en ${low}`}>
          <div className="grid gap-3 sm:grid-cols-2">
            {d.points.map((p) => (
              <div key={p} className="flex items-start gap-3 rounded-xl border border-gray-200 bg-white p-4">
                <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-50 text-emerald-700">
                  <Check className="h-3.5 w-3.5" />
                </span>
                <span className="text-sm leading-relaxed text-brand-charcoal">{p}</span>
              </div>
            ))}
          </div>
        </Section>

        <Section title={`Courses de ${low} du jour`}>
          {courses.length > 0 ? (
            <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white">
              {courses.slice(0, 40).map((c, i) => (
                <Link
                  key={c.course_id}
                  href={`/courses/${c.course_id}`}
                  className={`flex items-center justify-between gap-3 px-4 py-3.5 text-sm transition-colors hover:bg-amber-50/50 ${i > 0 ? "border-t border-gray-100" : ""}`}
                >
                  <span className="flex items-center gap-3">
                    <span className="flex h-8 w-12 shrink-0 items-center justify-center rounded-lg bg-gradient-gold-soft font-display text-xs font-bold text-brand-gold-dark">
                      R{c.numero_reunion}C{c.numero}
                    </span>
                    <span className="font-medium text-brand-dark">{titleCase(c.hippo)}</span>
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
                Aucune course de {low} programmée aujourd&apos;hui. Voir le{" "}
                <Link href="/programme" className="font-medium text-brand-gold-dark underline">programme complet</Link>.
              </span>
            </div>
          )}
        </Section>

        <Section title="Pour aller plus loin">
          <p className="text-sm leading-relaxed text-brand-charcoal">
            {d.slug === "trot" ? (
              <>
                Voir nos guides : <Link href="/blog/strategies-paris-trot" className="font-medium text-brand-gold-dark underline">5 clés pour parier au trot</Link>{" "}
                et <Link href="/blog/reduction-kilometrique-trot" className="font-medium text-brand-gold-dark underline">la réduction kilométrique</Link>.
              </>
            ) : (
              <>
                Comprendre les <Link href="/guides/types-de-paris-pmu" className="font-medium text-brand-gold-dark underline">types de paris PMU</Link>{" "}
                et le <Link href="/guides/pari-de-valeur" className="font-medium text-brand-gold-dark underline">pari de valeur</Link>.
              </>
            )}
          </p>
        </Section>
      </Container>
    </>
  );
}
