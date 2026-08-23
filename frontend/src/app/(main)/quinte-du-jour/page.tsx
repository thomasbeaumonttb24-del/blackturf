import type { Metadata } from "next";
import Link from "next/link";
import {
  fetchProgramme,
  fetchCourseDetail,
  fetchResultats,
  jourParis,
  jourLong,
  jourCourt,
  heureParis,
  titleCase,
  disciplineLabel,
  codeReunionCourse,
  type SeoCourse,
} from "@/lib/seo";
import { rapportsTries, libellePari, formatRapport } from "@/lib/rapports";
import { SeoHero, Container, Section, Callout } from "@/components/seo/kit";

export const revalidate = 300;

/** La course support du Quinté+ du jour (une seule par journée PMU). */
async function quinteDuJour(jour: string): Promise<SeoCourse | null> {
  const prog = await fetchProgramme(jour);
  for (const r of prog?.reunions ?? []) {
    for (const c of r.courses ?? []) if (c.est_quinte) return c;
  }
  return null;
}

export async function generateMetadata(): Promise<Metadata> {
  const jour = jourParis();
  const c = await quinteDuJour(jour);

  const title = c
    ? `Quinté+ du ${jourCourt(jour)} — ${titleCase(c.hippodrome_nom)}, partants et arrivée`
    : `Quinté+ du jour — partants, pronostic et arrivée`;
  // Extrait tronqué par Google vers 155-160 caractères : date, lieu et heure d'abord.
  const description = c
    ? `Quinté+ du ${jourLong(jour)} à ${titleCase(c.hippodrome_nom)} : ${
        c.nb_partants
      } partants, départ à ${heureParis(c.date_heure)}. Partants, cotes, arrivée et rapports.`
    : "Le Quinté+ du jour : hippodrome, partants, cotes, puis l'arrivée officielle et les rapports PMU.";

  return {
    title,
    description,
    alternates: { canonical: "/quinte-du-jour" },
    openGraph: { title, description, url: "https://blackturf.fr/quinte-du-jour" },
  };
}

export default async function QuinteDuJourPage() {
  const jour = jourParis();
  const resume = await quinteDuJour(jour);
  const detail = resume ? await fetchCourseDetail(resume.course_id) : null;
  const course = detail?.status === "ok" ? detail.course : null;
  const resultats =
    course?.statut === "termine" ? await fetchResultats(course.course_id) : null;

  const rapports = rapportsTries(resultats?.rapports);
  const quinteDetail = resultats?.rapports_detail?.e_quinte_plus ?? [];

  return (
    <>
      <SeoHero
        eyebrow="Mis à jour chaque jour"
        breadcrumbs={[
          { label: "Accueil", href: "/" },
          { label: "Programme", href: "/programme" },
          { label: "Quinté+ du jour" },
        ]}
        title={`Quinté+ du ${jourCourt(jour)}`}
        accent={course ? `— ${titleCase(course.hippodrome_nom)}` : undefined}
        lead={
          course
            ? `${codeReunionCourse(course.course_id)} · ${disciplineLabel(course.discipline)} · ${
                course.distance
              } m · ${course.nb_partants} partants · départ à ${heureParis(course.date_heure)}.`
            : "Le support du Quinté+ n'est pas encore publié pour aujourd'hui. Le PMU le désigne la veille au soir."
        }
      />

      <Container>
        {course ? (
          <>
            <Section title={`${titleCase(course.nom ?? "")} — ${titleCase(course.hippodrome_nom)}`}>
              <p className="text-sm leading-relaxed text-brand-charcoal/85">
                Le Quinté+ du {jourLong(jour)} se dispute à {titleCase(course.hippodrome_nom)} sur{" "}
                {course.distance} mètres ({disciplineLabel(course.discipline)}), avec{" "}
                {course.nb_partants} partants au départ de {heureParis(course.date_heure)}.
                {course.allocation
                  ? ` L'allocation totale est de ${Math.round(course.allocation / 100).toLocaleString(
                      "fr-FR",
                    )} €.`
                  : ""}{" "}
                Le détail course par course — cotes des principaux opérateurs, probabilité calculée
                par cheval et plan de mise adapté à votre budget — est sur{" "}
                <Link
                  href={`/courses/${course.course_id}`}
                  className="font-medium text-brand-gold-deep underline-offset-2 hover:underline"
                >
                  la fiche de la course
                </Link>
                .
              </p>
              {course.conditions_texte && (
                <p className="mt-4 text-[13px] leading-relaxed text-brand-charcoal/70">
                  {course.conditions_texte}
                </p>
              )}
            </Section>

            <Section title={`Les ${course.nb_partants} partants du Quinté+`}>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[520px] text-sm">
                  <thead>
                    <tr className="border-b border-amber-100 text-left text-[11px] uppercase tracking-wide text-brand-charcoal/60">
                      <th className="py-2 pr-3">N°</th>
                      <th className="py-2 pr-3">Cheval</th>
                      <th className="py-2 pr-3">Jockey</th>
                      <th className="py-2 pr-3">Musique</th>
                      <th className="py-2 pr-3 text-right">Cote</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(course.partants ?? []).map((p) => (
                      <tr
                        key={p.numero}
                        className={`border-b border-amber-50 ${p.non_partant ? "opacity-40" : ""}`}
                      >
                        <td className="py-2 pr-3 font-semibold tabular-nums">{p.numero}</td>
                        <td className="py-2 pr-3 font-medium text-brand-dark">
                          {titleCase(p.nom_cheval)}
                          {p.non_partant ? " (non-partant)" : ""}
                        </td>
                        <td className="py-2 pr-3 text-brand-charcoal/80">
                          {p.jockey ? titleCase(p.jockey) : "—"}
                        </td>
                        <td className="py-2 pr-3 font-mono text-[12px] text-brand-charcoal/70">
                          {p.musique ?? "—"}
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums">
                          {p.cote_pmu ? p.cote_pmu.toFixed(1) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>

            {resultats?.classement?.length ? (
              <Section title="Arrivée officielle du Quinté+">
                <p className="text-sm text-brand-charcoal/85">
                  Arrivée du Quinté+ du {jourLong(jour)} à {titleCase(course.hippodrome_nom)} :{" "}
                  <strong className="tabular-nums">
                    {resultats.classement
                      .slice(0, 5)
                      .map((l) => l.numero)
                      .join(" - ")}
                  </strong>
                </p>
                <ol className="mt-3 space-y-1 text-sm text-brand-charcoal/85">
                  {resultats.classement.slice(0, 8).map((l) => (
                    <li key={l.position}>
                      <span className="font-semibold tabular-nums">{l.position}.</span> n°{l.numero}{" "}
                      {titleCase(l.nom)}
                      {l.reduction_km ? ` — RK ${l.reduction_km}` : ""}
                    </li>
                  ))}
                </ol>
              </Section>
            ) : null}

            {rapports.length ? (
              <Section title="Rapports PMU officiels">
                <p className="text-sm text-brand-charcoal/70">
                  Rapports pour 1 € de mise, publiés par le PMU après l&apos;arrivée.
                </p>
                <div className="mt-3 overflow-x-auto">
                  <table className="w-full min-w-[380px] text-sm">
                    <tbody>
                      {rapports.map(([code, val]) => (
                        <tr key={code} className="border-b border-amber-50">
                          <td className="py-2 pr-3 text-brand-charcoal/85">{libellePari(code)}</td>
                          <td className="py-2 text-right font-semibold tabular-nums text-brand-dark">
                            {formatRapport(val)} €
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {quinteDetail.length ? (
                  <>
                    <h3 className="mt-6 text-sm font-bold text-brand-dark">
                      Détail du Quinté+ (ordre, désordre, bonus)
                    </h3>
                    <ul className="mt-2 space-y-1 text-sm text-brand-charcoal/85">
                      {quinteDetail.map((d, i) => (
                        <li key={`${d.libelle}-${i}`}>
                          {d.libelle} — <span className="tabular-nums">{d.combinaison}</span> :{" "}
                          <strong className="tabular-nums">{formatRapport(d.rapport)} €</strong>
                        </li>
                      ))}
                    </ul>
                  </>
                ) : null}
              </Section>
            ) : null}

            <Callout href={`/courses/${course.course_id}`} cta="Ouvrir la fiche course">
              Cotes comparées, probabilité par cheval et plan de mise calculé sur votre budget :
              tout le détail du Quinté+ est sur la fiche de la course.
            </Callout>
          </>
        ) : (
          <Section title="Pas encore de Quinté+ publié">
            <p className="text-sm text-brand-charcoal/85">
              Le PMU désigne la course support du Quinté+ la veille au soir. En attendant, le{" "}
              <Link href="/programme" className="font-medium text-brand-gold-deep hover:underline">
                programme complet du jour
              </Link>{" "}
              est déjà disponible.
            </p>
          </Section>
        )}

        <Section title="Comment lire un Quinté+">
          <p className="text-sm leading-relaxed text-brand-charcoal/85">
            Le Quinté+ demande de désigner les cinq premiers chevaux d&apos;une course. Trouvé dans
            l&apos;ordre exact, il paie souvent plusieurs milliers d&apos;euros ; dans le désordre,
            quelques centaines. Le PMU prélève environ 20 % des enjeux avant redistribution : sur ce
            type de pari, le seul avantage possible vient d&apos;un écart entre la probabilité
            réelle d&apos;un cheval et celle qu&apos;implique sa cote — c&apos;est exactement ce que
            mesure BlackTurf, sans promettre de gain.{" "}
            <Link href="/guides/pari-de-valeur" className="font-medium text-brand-gold-deep hover:underline">
              Comprendre le pari de valeur
            </Link>{" "}
            ·{" "}
            <Link href="/guides/types-de-paris-pmu" className="font-medium text-brand-gold-deep hover:underline">
              Tous les types de paris PMU
            </Link>
          </p>
        </Section>
      </Container>
    </>
  );
}
