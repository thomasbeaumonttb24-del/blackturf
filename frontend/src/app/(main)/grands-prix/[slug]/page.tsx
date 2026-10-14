import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { CalendarDays, Trophy } from "lucide-react";
import { GRANDS_PRIX, getGrandPrix, estCeGrandPrix, type GrandPrix, type Edition } from "@/lib/grandsPrix";
import {
  fetchProgramme,
  fetchResultats,
  jourParis,
  jourLong,
  heureParis,
  filAriane,
  jsonLd,
  ogBase,
  twitterBase,
  PREMIER_JOUR_ARCHIVE,
  type SeoCourse,
  type SeoResultats,
} from "@/lib/seo";
import { SeoHero, Container, Section, Callout, Chip } from "@/components/seo/kit";
import { Carte3D } from "@/components/seo/Carte3D";
import { PhotoLieu, photoHippodrome } from "@/components/seo/PhotoLieu";
import { Podium } from "@/components/seo/Podium";
import { NewsletterForm } from "@/components/newsletter/NewsletterForm";

export const dynamicParams = false;
export const revalidate = 3600;

export function generateStaticParams() {
  return GRANDS_PRIX.map((g) => ({ slug: g.slug }));
}

/** La prochaine édition à venir (aujourd'hui compris), ou null. */
function prochaine(g: GrandPrix, aujourdhui: string): Edition | null {
  return g.editions.find((e) => e.date >= aujourdhui) ?? null;
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const g = getGrandPrix(slug);
  if (!g) return { title: "Grand Prix" };
  const p = prochaine(g, jourParis());
  // « Pronostic <course> <année> » : la requête des jours qui précèdent l'épreuve ; le reste
  // de l'année, la page répond à « <course> » (histoire, conditions, dernières arrivées).
  const title = p
    ? `${g.nom} ${p.annee} : pronostic, partants et date`
    : `${g.nom} : pronostic, histoire et derniers résultats`;
  const description = `${g.nom} à ${g.hippodrome} : ${g.discipline.toLowerCase()}, ${g.distance}, ${g.periode.toLowerCase()}. Conditions, repères historiques, dernières arrivées et pronostic IA.`;
  return {
    title,
    description,
    alternates: { canonical: `/grands-prix/${g.slug}` },
    openGraph: ogBase({ title, description, url: `/grands-prix/${g.slug}`, type: "article" }),
    twitter: twitterBase({ title, description }),
  };
}

type Trouvee = { edition: Edition; course: SeoCourse; resultats: SeoResultats | null };

/** Retrouve la course dans le programme de sa date, par son nom. Une édition absente
 *  de la base (avant la mise en service, ou pas encore publiée) ne renvoie rien. */
async function chercher(g: GrandPrix, edition: Edition): Promise<Trouvee | null> {
  if (edition.date < PREMIER_JOUR_ARCHIVE) return null;
  const prog = await fetchProgramme(edition.date);
  const course = (prog?.reunions ?? [])
    .flatMap((r) => r.courses ?? [])
    .find((c) => estCeGrandPrix(c.nom, g));
  if (!course) return null;
  const resultats = course.statut === "termine" ? await fetchResultats(course.course_id) : null;
  return { edition, course, resultats };
}

export default async function GrandPrixPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const g = getGrandPrix(slug);
  if (!g) notFound();

  const aujourdhui = jourParis();
  const prochaineEdition = prochaine(g, aujourdhui);
  // Les éditions publiées (passées, ou la prochaine si son programme est déjà sorti).
  const candidates = g.editions.filter((e) => e.date <= jourParis(1));
  const trouvees = (await Promise.all(candidates.map((e) => chercher(g, e)))).filter(
    (t): t is Trouvee => t !== null,
  );
  const passees = trouvees
    .filter((t) => t.resultats?.classement?.length)
    .sort((a, b) => b.edition.date.localeCompare(a.edition.date));
  const aVenir = trouvees.find((t) => t.edition.date >= aujourdhui && !t.resultats?.classement?.length) ?? null;

  const photo = photoHippodrome(g.hippodromeSlug);

  const evenement = prochaineEdition
    ? {
        "@context": "https://schema.org",
        "@type": "SportsEvent",
        name: `${g.nom} ${prochaineEdition.annee}`,
        startDate: aVenir?.course.date_heure ?? prochaineEdition.date,
        eventStatus: "https://schema.org/EventScheduled",
        eventAttendanceMode: "https://schema.org/OfflineEventAttendanceMode",
        sport: `Course hippique — ${g.discipline}`,
        location: {
          "@type": "Place",
          name: `Hippodrome ${g.hippodrome}`,
          address: { "@type": "PostalAddress", addressCountry: "FR" },
        },
        description: `${g.discipline}, ${g.distance}. ${g.conditions}`,
        url: `https://blackturf.fr/grands-prix/${g.slug}`,
      }
    : null;
  const ariane = filAriane([
    { nom: "Accueil", url: "/" },
    { nom: "Grands Prix", url: "/grands-prix" },
    { nom: g.nom },
  ]);

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd(ariane) }} />
      {evenement && <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd(evenement) }} />}

      <SeoHero
        eyebrow={`Grand Prix · ${g.discipline}`}
        title={g.nom}
        lead={g.intro}
        breadcrumbs={[{ label: "Accueil", href: "/" }, { label: "Grands Prix", href: "/grands-prix" }, { label: g.nom }]}
        chips={
          <>
            <Chip tone="gold"><Trophy className="h-3 w-3" /> {g.categorie}</Chip>
            <Chip>{g.periode}</Chip>
          </>
        }
      >
        {photo && <PhotoLieu photo={photo} alt={`Hippodrome ${g.hippodrome}, où se court ${g.court}`} />}
        <Carte3D
          className={photo ? "-mt-6 sm:-mt-28 sm:ml-8" : "mt-8"}
          surtitre={`${g.categorie} · ${g.discipline}`}
          titre={
            prochaineEdition
              ? `Prochaine édition : ${jourLong(prochaineEdition.date)}${prochaineEdition.officielle === false ? " (annoncée)" : ""}`
              : `Chaque année : ${g.periode.charAt(0).toLowerCase()}${g.periode.slice(1)}`
          }
          faits={[
            { label: "Discipline", valeur: g.discipline },
            { label: "Distance", valeur: g.distance },
            { label: "Catégorie", valeur: g.categorie },
            { label: "Créé en", valeur: g.creation },
            ...(g.allocation ? [{ label: "Allocation", valeur: g.allocation }] : []),
            { label: "Hippodrome", valeur: g.hippodrome },
          ]}
          pied={g.conditions}
        />
      </SeoHero>

      <Container>
        {aVenir && (
          <Section title={`${g.nom} ${aVenir.edition.annee} : le pronostic`}>
            <Callout href={`/courses/${aVenir.course.course_id}`} cta="Voir le pronostic IA">
              Le {jourLong(aVenir.edition.date)}, départ à {heureParis(aVenir.course.date_heure)} :{" "}
              {aVenir.course.nb_partants} partants. Partants, cotes et classement de l&apos;IA sur la fiche de la course.
            </Callout>
          </Section>
        )}

        {passees.length > 0 && (
          <Section title="Les dernières éditions">
            <div className="grid gap-6 sm:grid-cols-2">
              {passees.map((t) => (
                <div key={t.edition.date} className="glass-card rounded-2xl p-5">
                  <div className="mb-4 flex items-baseline justify-between gap-2">
                    <h3 className="font-display text-lg font-bold text-brand-dark">{t.edition.annee}</h3>
                    <span className="text-xs text-brand-charcoal">{jourLong(t.edition.date)}</span>
                  </div>
                  <Podium classement={t.resultats?.classement ?? []} href={`/courses/${t.course.course_id}`} />
                </div>
              ))}
            </div>
            <p className="mt-3 text-xs text-brand-charcoal">
              Arrivées officielles du PMU, telles qu&apos;enregistrées par BlackTurf.
            </p>
          </Section>
        )}

        <Section title={`${g.nom} en quelques repères`}>
          <ol className="grid gap-3 sm:grid-cols-2">
            {g.reperes.map((r, i) => (
              <li key={i} className="card-hover flex gap-3 rounded-2xl border border-gray-200 bg-white p-4">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-gold font-display text-sm font-bold text-brand-dark shadow-sm">
                  {i + 1}
                </span>
                <p className="text-sm leading-relaxed text-brand-charcoal">{r}</p>
              </li>
            ))}
          </ol>
        </Section>

        <Section title="Bien jouer un Grand Prix">
          <p className="text-sm leading-relaxed text-brand-charcoal">
            Les grandes courses attirent des enjeux records : les favoris y sont souvent très joués, et leur
            cote descend en dessous de leur chance réelle. C&apos;est précisément l&apos;écart que mesure
            BlackTurf, cheval par cheval, sans jamais promettre de gain.{" "}
            <Link href="/guides/pari-de-valeur" className="font-medium text-brand-gold-dark hover:underline">
              Comprendre le pari de valeur
            </Link>{" "}
            ·{" "}
            <Link href={`/hippodromes/${g.hippodromeSlug}`} className="font-medium text-brand-gold-dark hover:underline">
              L&apos;hippodrome {g.hippodrome}
            </Link>{" "}
            ·{" "}
            <Link href="/grands-prix" className="font-medium text-brand-gold-dark hover:underline">
              Tous les Grands Prix
            </Link>
          </p>
        </Section>

        {!aVenir && (
          <Callout href="/quinte-du-jour" cta="Quinté+ du jour">
            <CalendarDays className="mr-1.5 inline h-4 w-4 align-[-2px] text-brand-gold-dark" />
            En attendant la prochaine édition, l&apos;IA analyse chaque jour le Quinté+ et toutes les courses PMU.
          </Callout>
        )}

        <div className="mt-10">
          <NewsletterForm source={`grand-prix-${g.slug}`} />
        </div>
      </Container>
    </>
  );
}
