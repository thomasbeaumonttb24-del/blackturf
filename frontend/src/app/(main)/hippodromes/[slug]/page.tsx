import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { MapPin, Trophy, ChevronRight, CalendarDays } from "lucide-react";
import { HIPPODROMES, getHippodrome, matchHippodrome } from "@/lib/hippodromes";
import {
  fetchProgramme,
  fetchProfilLieux,
  fetchSeoIndex,
  decalerJours,
  jourCourtAnnee,
  disciplineLabel,
  OG_IMAGE,
  filAriane,
  jsonLd,
} from "@/lib/seo";
import { SeoHero, Container, Section, Chip } from "@/components/seo/kit";
import { ProfilChiffreLieu } from "@/components/seo/ProfilChiffre";

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
    openGraph: { title, description, url: `https://blackturf.fr/hippodromes/${h.slug}`, images: [OG_IMAGE] },
  };
}

function todayParis(): string {
  return new Intl.DateTimeFormat("fr-CA", { timeZone: "Europe/Paris" }).format(new Date());
}

export default async function HippodromePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const h = getHippodrome(slug);
  if (!h) notFound();

  const aujourdhui = todayParis();
  const prog = await fetchProgramme(aujourdhui);
  const todayCourses = (prog?.reunions ?? [])
    .filter((r) => matchHippodrome(r.hippodrome, h))
    .flatMap((r) => r.courses ?? []);

  /* Les trente derniers jours de courses sur cet hippodrome.
   *
   * La page ne montrait que le programme du jour : un hippodrome qui ne court pas
   * aujourd'hui — le cas de la plupart d'entre eux la plupart du temps — affichait une
   * fiche vide, dont le seul contenu propre était son paragraphe d'introduction. Une page
   * qui n'a rien à dire les trois quarts de l'année ne se maintient pas dans l'index, et
   * ne rend service à personne.
   *
   * Les dernières réunions courues y remédient : le contenu est réel, daté, et donne aux
   * fiches course de cet hippodrome un second chemin d'exploration, latéral cette fois. */
  const debutFenetre = decalerJours(aujourdhui, -30);
  const { courses: recentes } = await fetchSeoIndex(debutFenetre, aujourdhui, 3600);
  const parJour = new Map<string, number>();
  for (const c of recentes) {
    if (!c.termine || !matchHippodrome(c.hippodrome, h)) continue;
    parJour.set(c.jour, (parJour.get(c.jour) ?? 0) + 1);
  }
  const dernieresReunions = [...parJour.entries()]
    .sort((a, b) => b[0].localeCompare(a[0]))
    .slice(0, 12);

  /* Profil chiffré du lieu, tiré de l'historique complet du site.
   *
   * Les noms d'hippodrome de la base sont ceux du PMU (« HIPPODROME DE PARIS-VINCENNES ») ;
   * on retrouve le bon en réutilisant la règle de correspondance qui sert déjà au
   * programme du jour, plutôt qu'en pariant sur une égalité de chaînes. Plusieurs
   * libellés peuvent désigner le même lieu : on les additionne. */
  const profils = await fetchProfilLieux();
  const profil = (() => {
    const parts = Object.entries(profils?.lieux ?? {}).filter(([nom]) => matchHippodrome(nom, h));
    if (!parts.length) return null;
    return parts.reduce((acc, [, p]) => {
      if (!acc) return { ...p, disciplines: { ...p.disciplines } };
      acc.nb_courses += p.nb_courses;
      acc.nb_journees += p.nb_journees;
      acc.distance_min = Math.min(acc.distance_min ?? p.distance_min ?? 0, p.distance_min ?? Infinity);
      acc.distance_max = Math.max(acc.distance_max ?? 0, p.distance_max ?? 0);
      for (const [d, n] of Object.entries(p.disciplines)) acc.disciplines[d] = (acc.disciplines[d] ?? 0) + n;
      return acc;
    }, null as null | (typeof parts)[0][1]);
  })();

  const placeLd = {
    "@context": "https://schema.org",
    "@type": "SportsActivityLocation",
    name: h.name,
    address: { "@type": "PostalAddress", addressLocality: h.city, addressRegion: h.region, addressCountry: "FR" },
    url: `https://blackturf.fr/hippodromes/${h.slug}`,
    description: h.intro,
  };
  // Le fil balisé partait de « Hippodromes » alors que le fil AFFICHÉ commence par
  // « Accueil » : les deux disent maintenant la même chose.
  const breadcrumb = filAriane([
    { nom: "Accueil", url: "/" },
    { nom: "Hippodromes", url: "/hippodromes" },
    { nom: h.name },
  ]);

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd(placeLd) }} />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd(breadcrumb) }} />

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

        {profil && (
          <Section title={`Ce qui se court à ${h.city}`}>
            <ProfilChiffreLieu nom={h.name} p={profil} />
          </Section>
        )}

        {dernieresReunions.length > 0 && (
          <Section title={`Dernières réunions à ${h.city}`}>
            <p className="text-sm leading-relaxed text-brand-charcoal">
              Les arrivées et les rapports PMU des journées récemment courues sur cet
              hippodrome. Une arrivée publiée ne change plus : ces pages restent exactes.
            </p>
            <ul className="mt-4 flex flex-wrap gap-2">
              {dernieresReunions.map(([jour, nb]) => (
                <li key={jour}>
                  <Link
                    href={jour === aujourdhui ? "/resultats" : `/resultats/${jour}`}
                    className="inline-flex items-baseline gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm transition-colors hover:border-brand-gold-deep hover:text-brand-gold-dark"
                  >
                    <span className="font-display font-semibold text-brand-dark">
                      {jourCourtAnnee(jour)}
                    </span>
                    <span className="text-[11px] text-brand-charcoal">
                      {nb} course{nb > 1 ? "s" : ""}
                    </span>
                  </Link>
                </li>
              ))}
              <li>
                <Link
                  href="/resultats/archives"
                  className="inline-block rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm font-medium text-brand-gold-dark transition-colors hover:border-brand-gold-deep"
                >
                  Toutes les archives →
                </Link>
              </li>
            </ul>
          </Section>
        )}

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
