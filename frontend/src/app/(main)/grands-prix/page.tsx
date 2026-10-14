import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight, Trophy } from "lucide-react";
import { GRANDS_PRIX } from "@/lib/grandsPrix";
import { jourParis, jourCourtAnnee, filAriane, jsonLd, ogBase, twitterBase } from "@/lib/seo";
import { SeoHero, Container, Section } from "@/components/seo/kit";

export const revalidate = 3600;

const TITLE = "Grands Prix hippiques : Arc, Prix d'Amérique, Diane… pronostics et dates";
const DESCRIPTION =
  "Les grandes courses françaises de l'année : Prix d'Amérique, Grand Steeple-Chase de Paris, Prix de Diane, Arc de Triomphe… Dates, conditions, dernières arrivées et pronostic IA.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/grands-prix" },
  openGraph: ogBase({ title: TITLE, description: DESCRIPTION, url: "/grands-prix" }),
  twitter: twitterBase({ title: TITLE, description: DESCRIPTION }),
};

export default function GrandsPrixPage() {
  const aujourdhui = jourParis();
  const liste = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    itemListElement: GRANDS_PRIX.map((g, i) => ({
      "@type": "ListItem",
      position: i + 1,
      name: g.nom,
      url: `https://blackturf.fr/grands-prix/${g.slug}`,
    })),
  };
  const ariane = filAriane([{ nom: "Accueil", url: "/" }, { nom: "Grands Prix" }]);

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd(liste) }} />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd(ariane) }} />
      <SeoHero
        eyebrow="Le calendrier des grandes courses"
        title="Les Grands Prix"
        accent="hippiques"
        lead="De janvier à octobre, les courses qui font l'histoire du trot, du plat et de l'obstacle en France. Pour chacune : sa date, ses conditions, ses repères et les dernières arrivées."
        breadcrumbs={[{ label: "Accueil", href: "/" }, { label: "Grands Prix" }]}
      />
      <Container>
        <Section title="Dans l'ordre du calendrier">
          <ol className="grid gap-4 sm:grid-cols-2">
            {GRANDS_PRIX.map((g) => {
              const suivante = g.editions.find((e) => e.date >= aujourdhui);
              return (
                <li key={g.slug}>
                  <Link href={`/grands-prix/${g.slug}`} className="glass-card group flex h-full flex-col rounded-2xl p-5">
                    <div className="flex items-start justify-between gap-3">
                      <span className="icon-box flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-gold-soft text-brand-gold-dark">
                        <Trophy className="h-5 w-5" />
                      </span>
                      <span className="rounded-full border border-amber-200 bg-amber-50 px-2.5 py-0.5 text-[11px] font-semibold text-brand-gold-dark">
                        {g.categorie}
                      </span>
                    </div>
                    <h2 className="mt-4 font-display text-lg font-bold text-brand-dark transition-colors group-hover:text-brand-gold-dark">
                      {g.nom}
                    </h2>
                    <p className="mt-1 text-sm text-brand-charcoal">
                      {g.hippodrome} · {g.discipline} · {g.distance}
                    </p>
                    <p className="mt-3 flex-1 text-[13px] leading-relaxed text-brand-charcoal">{g.periode}.</p>
                    <div className="mt-4 flex items-center justify-between text-xs">
                      <span className="font-medium text-brand-dark">
                        {suivante
                          ? `Prochaine : ${jourCourtAnnee(suivante.date)}${suivante.officielle === false ? " (annoncée)" : ""}`
                          : `Depuis ${g.creation}`}
                      </span>
                      <ArrowRight className="h-4 w-4 text-brand-gold-dark/50 transition-all group-hover:translate-x-0.5 group-hover:text-brand-gold-dark" />
                    </div>
                  </Link>
                </li>
              );
            })}
          </ol>
        </Section>
      </Container>
    </>
  );
}
