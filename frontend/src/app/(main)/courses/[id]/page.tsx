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
import { NewsletterForm } from "@/components/newsletter/NewsletterForm";
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

      {/* Fiche course en toutes lettres. Doublure volontairement sobre de l'application
          au-dessus : elle reste lisible sans JavaScript, s'imprime, et donne au moteur de
          recherche une formulation explicite de ce que contient la page. Elle ne rejoue
          PAS la mise en page de l'onglet Partants : ici, un tableau de référence — état
          civil de la course, engagés, et l'arrivée quand elle est connue. */}
      {course && (
        <section className="mx-auto max-w-5xl px-4 pb-16 sm:px-6">
          <div className="rounded-2xl border border-stone-200 bg-white p-5 sm:p-7">
            <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-stone-400">
              Fiche course
            </p>
            <h2 className="mt-1 font-display text-lg font-bold text-slate-900">
              {libelleCourse(course)} — {titleCase(course.hippodrome_nom)}
              {jour ? `, ${jourLong(jour)}` : ""}
            </h2>

            {/* État civil de la course : une donnée par case, plutôt qu'une phrase
                qui empile sept chiffres et qu'on relit deux fois. */}
            <dl className="mt-4 grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-stone-200 bg-stone-200 sm:grid-cols-3 lg:grid-cols-6">
              {[
                { k: "Course", v: codeReunionCourse(course.course_id) },
                { k: "Discipline", v: disciplineLabel(course.discipline) },
                { k: "Distance", v: `${course.distance.toLocaleString("fr-FR")} m` },
                { k: "Partants", v: String(course.nb_partants) },
                { k: "Départ", v: heureParis(course.date_heure) },
                {
                  k: "Allocation",
                  v: course.allocation
                    ? `${Math.round(course.allocation / 100).toLocaleString("fr-FR")} €`
                    : "—",
                },
              ].map((c) => (
                <div key={c.k} className="bg-white px-3 py-2.5">
                  <dt className="text-[11px] text-stone-400">{c.k}</dt>
                  <dd className="mt-0.5 font-display text-[13.5px] font-bold text-slate-900">{c.v}</dd>
                </div>
              ))}
            </dl>

            {(course.est_quinte || course.est_quarte || course.est_tierce) && (
              <div className="mt-3 flex flex-wrap gap-2">
                {course.est_quinte && (
                  <span className="rounded-full bg-amber-500 px-3 py-1 text-[11px] font-semibold text-white">
                    Support du Quinté+ du jour
                  </span>
                )}
                {course.est_quarte && !course.est_quinte && (
                  <span className="rounded-full bg-stone-900 px-3 py-1 text-[11px] font-semibold text-white">
                    Support du Quarté+
                  </span>
                )}
                {course.est_tierce && !course.est_quarte && !course.est_quinte && (
                  <span className="rounded-full bg-stone-100 px-3 py-1 text-[11px] font-semibold text-stone-700">
                    Support du Tiercé
                  </span>
                )}
              </div>
            )}

            <p className="mt-4 text-sm leading-relaxed text-stone-600">
              {resultats?.classement?.length
                ? `Arrivée officielle : ${resultats.classement
                    .slice(0, 5)
                    .map((l) => l.numero)
                    .join(" - ")}. Les rapports PMU, le détail de l'arrivée et le bilan du plan de mise sont affichés plus haut.`
                : `Les ${course.nb_partants} engagés, les cotes des principaux opérateurs et la probabilité calculée pour chaque cheval sont détaillés plus haut, onglet par onglet.`}
            </p>

            {course.conditions_texte && (
              <div className="mt-5 rounded-xl border border-stone-200 bg-stone-50/70 p-4">
                <h3 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-stone-400">
                  Conditions de la course
                </h3>
                <p className="mt-1.5 text-[13px] leading-relaxed text-stone-600">
                  {course.conditions_texte}
                </p>
              </div>
            )}

            <h3 className="mt-6 font-display text-[15px] font-bold text-slate-900">
              Tous les engagés ({course.nb_partants})
            </h3>
            <div className="mt-3 overflow-x-auto rounded-xl border border-stone-200">
              <table className="w-full min-w-[560px] border-collapse text-[13px]">
                <thead>
                  <tr className="bg-stone-50 text-left text-[11px] uppercase tracking-[0.08em] text-stone-400">
                    <th scope="col" className="px-3 py-2 font-semibold">N°</th>
                    <th scope="col" className="px-3 py-2 font-semibold">Cheval</th>
                    <th scope="col" className="px-3 py-2 font-semibold">Jockey / driver</th>
                    <th scope="col" className="px-3 py-2 font-semibold">Musique</th>
                    <th scope="col" className="px-3 py-2 text-right font-semibold">Cote</th>
                    {resultats?.classement?.length ? (
                      <th scope="col" className="px-3 py-2 text-right font-semibold">Arrivée</th>
                    ) : null}
                  </tr>
                </thead>
                <tbody>
                  {(course.partants ?? []).map((p) => {
                    const place =
                      resultats?.classement?.find((l) => l.numero === p.numero)?.position ?? null;
                    return (
                      <tr
                        key={p.numero}
                        className={`border-t border-stone-100 ${p.non_partant ? "text-stone-400" : "text-stone-600"}`}
                      >
                        <td className="px-3 py-2 font-display font-bold tabular-nums text-slate-900">
                          {p.numero}
                        </td>
                        <td className={`px-3 py-2 font-medium text-slate-900 ${p.non_partant ? "line-through opacity-60" : ""}`}>
                          {titleCase(p.nom_cheval)}
                          {p.non_partant ? (
                            <span className="ml-2 rounded-full bg-stone-100 px-2 py-0.5 text-[10.5px] font-semibold uppercase text-stone-500">
                              non-partant
                            </span>
                          ) : null}
                        </td>
                        <td className="px-3 py-2">{p.jockey ? titleCase(p.jockey) : "—"}</td>
                        <td className="px-3 py-2 font-mono text-[12px]">{p.musique || "—"}</td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {p.cote_pmu ? p.cote_pmu.toFixed(1) : "—"}
                        </td>
                        {resultats?.classement?.length ? (
                          <td className="px-3 py-2 text-right tabular-nums">
                            {place ? (
                              <span
                                className={
                                  place <= 3
                                    ? "rounded-full bg-emerald-600/10 px-2 py-0.5 text-[11px] font-semibold text-emerald-700"
                                    : "text-stone-500"
                                }
                              >
                                {place}
                                <span className="align-super text-[9px]">{place === 1 ? "er" : "e"}</span>
                              </span>
                            ) : (
                              "—"
                            )}
                          </td>
                        ) : null}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <nav className="mt-5 flex flex-wrap gap-2 text-[12.5px]">
              {[
                { href: "/programme", txt: "Programme PMU du jour" },
                { href: "/quinte-du-jour", txt: "Quinté+ du jour" },
                { href: "/resultats", txt: "Arrivées et rapports du jour" },
                { href: "/guides/types-de-paris-pmu", txt: "Comprendre les types de paris" },
              ].map((l) => (
                <a
                  key={l.href}
                  href={l.href}
                  className="rounded-full border border-stone-200 bg-stone-50 px-3 py-1.5 font-medium text-stone-600 transition-colors hover:border-brand-gold-deep hover:text-brand-gold-deep"
                >
                  {l.txt}
                </a>
              ))}
            </nav>
          </div>

          <div className="mt-10">
            <NewsletterForm source="course" />
          </div>
        </section>
      )}

    </>
  );
}
