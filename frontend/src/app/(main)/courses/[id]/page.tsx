import type { Metadata } from "next";
import { notFound } from "next/navigation";
import {
  fetchCourseDetail,
  fetchResultats,
  disciplineLabel,
  titleCase,
  heureParis,
  jourLong,
  jourCourt,
  jourDeCourseId,
  codeReunionCourse,
  type SeoCourseDetail,
  type SeoResultats,
} from "@/lib/seo";
import CourseClient from "./CourseClient";

// ISR 2 min : les fiches à venir bougent (cotes, non-partants), les fiches terminées sont
// figées. Un crawl ne déclenche donc au pire qu'un appel API toutes les deux minutes.
export const revalidate = 120;

type Props = { params: Promise<{ id: string }> };

function libelleCourse(c: SeoCourseDetail): string {
  return titleCase(c.nom ?? "") || `Course ${codeReunionCourse(c.course_id)}`;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const res = await fetchCourseDetail(id);

  if (res.status !== "ok") {
    // Course inconnue OU API en panne : on ne fabrique pas de titre, mais on ne pose pas
    // non plus de noindex sur un simple hoquet réseau — le rendu ci-dessous décide.
    return { title: "Course PMU", alternates: { canonical: `/courses/${id}` } };
  }

  const c = res.course;
  const code = codeReunionCourse(c.course_id);
  const hippo = titleCase(c.hippodrome_nom);
  const jour = jourDeCourseId(c.course_id);
  const disc = disciplineLabel(c.discipline);
  const termine = c.statut === "termine";

  // Le titre reprend les formulations réellement tapées : « partants R2C1 », « arrivée et
  // rapports », le nom du prix, l'hippodrome. Sans dépasser ~60 caractères utiles.
  const title = termine
    ? `${code} ${hippo} — arrivée, rapports et partants`
    : `${code} ${hippo} — partants, cotes et pronostic`;

  // Le nom d'un prix peut être long : on garde la date courte et une queue brève pour
  // rester sous les ~155-160 caractères après lesquels Google tronque l'extrait.
  const description =
    `${libelleCourse(c)} — ${hippo}, ${disc}, ${c.distance} m, ${c.nb_partants} partants` +
    (jour ? `, ${jourCourt(jour)} à ${heureParis(c.date_heure)}` : "") +
    (c.est_quinte ? ". Support du Quinté+" : "") +
    (termine ? ". Arrivée et rapports PMU." : ". Partants, cotes et probabilité par cheval.");

  return {
    title,
    description,
    alternates: { canonical: `/courses/${c.course_id}` },
    openGraph: {
      title,
      description,
      url: `https://blackturf.fr/courses/${c.course_id}`,
      type: "article",
    },
  };
}

function jsonLdCourse(c: SeoCourseDetail, resultats: SeoResultats | null) {
  const hippo = titleCase(c.hippodrome_nom);
  const jour = jourDeCourseId(c.course_id);
  const gagnant = resultats?.classement?.find((l) => l.position === 1);

  const event: Record<string, unknown> = {
    "@context": "https://schema.org",
    "@type": "SportsEvent",
    name: `${libelleCourse(c)} — ${hippo}`,
    startDate: c.date_heure,
    eventStatus:
      c.statut === "annule"
        ? "https://schema.org/EventCancelled"
        : "https://schema.org/EventScheduled",
    eventAttendanceMode: "https://schema.org/OfflineEventAttendanceMode",
    sport: `Course hippique — ${disciplineLabel(c.discipline)}`,
    url: `https://blackturf.fr/courses/${c.course_id}`,
    location: { "@type": "Place", name: hippo, address: { "@type": "PostalAddress", addressCountry: "FR" } },
    description:
      `${disciplineLabel(c.discipline)}, ${c.distance} mètres, ${c.nb_partants} partants` +
      (jour ? `, le ${jourLong(jour)}` : "") +
      ".",
  };

  // Les chevaux engagés sont les « compétiteurs » de l'événement : c'est ce qui donne à
  // Google le lien entre le nom d'un cheval et cette course.
  const partants = (c.partants ?? []).filter((p) => !p.non_partant);
  if (partants.length) {
    event.competitor = partants.map((p) => ({
      "@type": "Person",
      name: titleCase(p.nom_cheval),
      ...(p.jockey ? { affiliation: { "@type": "Organization", name: titleCase(p.jockey) } } : {}),
    }));
  }
  if (gagnant) {
    event.about = `Vainqueur : ${titleCase(gagnant.nom)} (n°${gagnant.numero}).`;
  }
  return event;
}

export default async function CoursePage({ params }: Props) {
  const { id } = await params;
  const res = await fetchCourseDetail(id);

  // 404 explicite de l'API → vraie page 404. On distingue le 404 d'une panne réseau :
  // désindexer des centaines de fiches valides sur un hoquet de l'API coûterait des
  // semaines de réindexation.
  if (res.status === "notfound") notFound();

  const course = res.status === "ok" ? res.course : null;
  const resultats = course?.statut === "termine" ? await fetchResultats(id) : null;

  const jour = course ? jourDeCourseId(course.course_id) : null;
  const breadcrumbJsonLd = course
    ? {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        itemListElement: [
          { "@type": "ListItem", position: 1, name: "Accueil", item: "https://blackturf.fr" },
          { "@type": "ListItem", position: 2, name: "Programme du jour", item: "https://blackturf.fr/programme" },
          {
            "@type": "ListItem",
            position: 3,
            name: `${codeReunionCourse(course.course_id)} — ${titleCase(course.hippodrome_nom)}`,
            item: `https://blackturf.fr/courses/${course.course_id}`,
          },
        ],
      }
    : null;

  return (
    <>
      {course && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLdCourse(course, resultats)) }}
        />
      )}
      {breadcrumbJsonLd && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumbJsonLd) }}
        />
      )}

      {/* Le composant client reçoit la course déjà chargée : son premier rendu (celui du
          HTML servi) contient donc le nom de la course, les partants et les cotes. */}
      <CourseClient initialCourse={course as never} />

      {/* Résumé texte de la course. Doublure volontairement sobre de l'application
          au-dessus : elle reste lisible sans JavaScript, s'imprime, et donne au moteur de
          recherche une formulation en toutes lettres de ce que contient la page. */}
      {course && (
        <section className="mx-auto max-w-5xl px-4 pb-16 sm:px-6">
          <h2 className="font-display text-lg font-bold text-gray-900">
            {libelleCourse(course)} — {titleCase(course.hippodrome_nom)}
            {jour ? `, ${jourLong(jour)}` : ""}
          </h2>
          <p className="mt-2 text-sm leading-relaxed text-gray-600">
            {codeReunionCourse(course.course_id)} : {disciplineLabel(course.discipline)} de{" "}
            {course.distance} mètres, {course.nb_partants} partants, départ à{" "}
            {heureParis(course.date_heure)}
            {course.allocation
              ? `, pour une allocation de ${Math.round(course.allocation / 100).toLocaleString("fr-FR")} €`
              : ""}
            .{" "}
            {course.est_quinte
              ? "Cette course est le support du Quinté+ du jour. "
              : course.est_quarte
              ? "Cette course est support du Quarté+. "
              : ""}
            {resultats?.classement?.length
              ? `Arrivée officielle : ${resultats.classement
                  .slice(0, 5)
                  .map((l) => l.numero)
                  .join(" - ")}.`
              : "Les partants, les cotes des principaux opérateurs et la probabilité calculée pour chaque cheval sont détaillés ci-dessus."}
          </p>

          {course.conditions_texte && (
            <>
              <h3 className="mt-6 text-sm font-bold text-gray-800">Conditions de la course</h3>
              <p className="mt-1 text-[13px] leading-relaxed text-gray-500">
                {course.conditions_texte}
              </p>
            </>
          )}

          <h3 className="mt-6 text-sm font-bold text-gray-800">
            Liste des partants ({course.nb_partants})
          </h3>
          <ol className="mt-2 grid gap-x-6 gap-y-1 text-[13px] text-gray-600 sm:grid-cols-2">
            {(course.partants ?? []).map((p) => (
              <li key={p.numero} className={p.non_partant ? "line-through opacity-50" : ""}>
                <span className="font-semibold tabular-nums text-gray-800">{p.numero}.</span>{" "}
                {titleCase(p.nom_cheval)}
                {p.jockey ? ` — ${titleCase(p.jockey)}` : ""}
                {p.musique ? ` (${p.musique})` : ""}
                {p.cote_pmu ? ` · cote ${p.cote_pmu.toFixed(1)}` : ""}
                {p.non_partant ? " · non-partant" : ""}
              </li>
            ))}
          </ol>

          <nav className="mt-6 flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-gray-500">
            <a href="/programme" className="hover:text-brand-gold-deep hover:underline">
              Programme PMU du jour
            </a>
            <a href="/quinte-du-jour" className="hover:text-brand-gold-deep hover:underline">
              Quinté+ du jour
            </a>
            <a href="/resultats" className="hover:text-brand-gold-deep hover:underline">
              Arrivées et rapports du jour
            </a>
            <a href="/guides/types-de-paris-pmu" className="hover:text-brand-gold-deep hover:underline">
              Comprendre les types de paris
            </a>
          </nav>
        </section>
      )}
    </>
  );
}
