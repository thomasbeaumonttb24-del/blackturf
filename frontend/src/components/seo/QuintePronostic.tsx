import { CasaqueNumero } from "@/components/courses/identite-cheval";
import Link from "next/link";
import {
  fetchCourseDetail,
  fetchResultats,
  fetchApercuCourse,
  fetchQuinte,
  jourLong,
  jourCourt,
  heureParis,
  titleCase,
  disciplineLabel,
  codeReunionCourse,
  jsonLd,
} from "@/lib/seo";
import { lieuCourse } from "@/lib/lieux";
import { rapportsTries, libellePari, formatRapport } from "@/lib/rapports";
import { SeoHero, Container, Section, Callout } from "@/components/seo/kit";
import { Carte3D } from "@/components/seo/Carte3D";
import { NewsletterForm } from "@/components/newsletter/NewsletterForm";
import { PreuvesRecentesCard } from "@/components/courses/insights";
import { AnalyseIA } from "./AnalyseIA";

/** Le Quinté+ d'aujourd'hui (`/quinte-du-jour`) ou de demain (`/quinte-de-demain`) :
 *  même contenu, rendu côté serveur, pour une journée donnée. */
const PAGE_JOUR = {
  nom: "Quinté+ du jour",
  url: "/quinte-du-jour",
  eyebrow: "Mis à jour chaque jour",
  autreUrl: "/quinte-de-demain",
  autreCta: "Quinté+ de demain",
  autreTexte: "Le Quinté+ de demain est en ligne dès la publication des partants, la veille : analyse de l'IA et cotes, à préparer dès ce soir.",
};
const PAGE_DEMAIN = {
  nom: "Quinté+ de demain",
  url: "/quinte-de-demain",
  eyebrow: "Publié la veille",
  autreUrl: "/quinte-du-jour",
  autreCta: "Quinté+ du jour",
  autreTexte: "Le Quinté+ d'aujourd'hui : partants, analyse de l'IA, puis l'arrivée officielle et les rapports PMU.",
};

export async function QuintePronostic({ jour, demain = false }: { jour: string; demain?: boolean }) {
  const page = demain ? PAGE_DEMAIN : PAGE_JOUR;
  const resume = await fetchQuinte(jour);
  const detail = resume ? await fetchCourseDetail(resume.course_id) : null;
  const course = detail?.status === "ok" ? detail.course : null;
  // Arrivée et analyse IA en parallèle : deux appels indépendants.
  const [resultats, apercu] = course
    ? await Promise.all([
        course.statut === "termine" ? fetchResultats(course.course_id) : Promise.resolve(null),
        // L'analyse est un complément : une API qui refuse cet appel (429, panne) ne
        // doit pas faire tomber la page du Quinté+, qui vit très bien sans.
        fetchApercuCourse(course.course_id).catch(() => null),
      ])
    : [null, null];

  const rapports = rapportsTries(resultats?.rapports);
  const quinteDetail = resultats?.rapports_detail?.e_quinte_plus ?? [];

  /* Données structurées. C'est la page de plus forte intention du site — « quinté du
   * jour », « arrivée quinté » — et c'était la seule des pages éditoriales à n'émettre
   * aucun balisage propre : ni fil d'Ariane, ni événement, alors que la fiche course de
   * cette même épreuve en portait un complet. Le `SportsEvent` est ici la même épreuve,
   * décrite depuis son adresse permanente. */
  const lieu = course ? lieuCourse(course.hippodrome_nom) : null;
  const hippo = lieu?.nom ?? null;
  const gagnant = resultats?.classement?.find((l) => l.position === 1);

  const eventJsonLd = course
    ? {
        "@context": "https://schema.org",
        "@type": "SportsEvent",
        name: `Quinté+ du ${jourLong(jour)} — ${titleCase(course.nom ?? "")} à ${hippo}`,
        startDate: course.date_heure,
        eventStatus:
          course.statut === "annule"
            ? "https://schema.org/EventCancelled"
            : "https://schema.org/EventScheduled",
        eventAttendanceMode: "https://schema.org/OfflineEventAttendanceMode",
        sport: `Course hippique — ${disciplineLabel(course.discipline)}`,
        // L'URL canonique de l'événement reste la fiche course : elle est permanente,
        // là où /quinte-du-jour désigne une épreuve différente chaque jour.
        url: `https://blackturf.fr/courses/${course.course_id}`,
        location: {
          "@type": "Place",
          name: hippo,
          address: { "@type": "PostalAddress", addressLocality: hippo, addressCountry: "FR" },
        },
        description: `${disciplineLabel(course.discipline)}, ${course.distance} mètres, ${
          course.nb_partants
        } partants, départ à ${heureParis(course.date_heure)}.`,
        ...(gagnant
          ? { about: `Vainqueur : ${titleCase(gagnant.nom)} (n°${gagnant.numero}).` }
          : {}),
      }
    : null;

  const breadcrumbJsonLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "Accueil", item: "https://blackturf.fr" },
      { "@type": "ListItem", position: 2, name: "Courses du jour", item: "https://blackturf.fr/programme" },
      {
        "@type": "ListItem",
        position: 3,
        name: page.nom,
        item: `https://blackturf.fr${page.url}`,
      },
    ],
  };

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLd(breadcrumbJsonLd) }}
      />
      {eventJsonLd && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: jsonLd(eventJsonLd) }}
        />
      )}

      <SeoHero
        eyebrow={page.eyebrow}
        breadcrumbs={[
          { label: "Accueil", href: "/" },
          { label: "Courses du jour", href: "/programme" },
          { label: page.nom },
        ]}
        title={demain ? `Pronostic Quinté+ de demain, ${jourCourt(jour)}` : `Pronostic Quinté+ du ${jourCourt(jour)}`}
        accent={lieu ? `— ${lieu.nom}` : undefined}
        lead={
          course
            ? `${codeReunionCourse(course.course_id)} · ${disciplineLabel(course.discipline)} · ${
                course.distance
              } m · ${course.nb_partants} partants · départ à ${heureParis(course.date_heure)}.`
            : demain
              ? "Le Quinté+ de demain n'est pas encore au programme. Les partants sont publiés la veille de la course : la page se remplit dès qu'ils sont connus."
              : "Le Quinté+ du jour n'est pas encore au programme. Les partants sont publiés la veille de la course."
        }
      >
        {course && (
          <Carte3D
            surtitre={`Quinté+ · ${jourLong(jour)}`}
            titre={titleCase(course.nom ?? "") || `Quinté+ ${lieu?.a}`}
            faits={[
              { label: "Hippodrome", valeur: lieu?.nom },
              { label: "Départ", valeur: heureParis(course.date_heure) },
              { label: "Course", valeur: codeReunionCourse(course.course_id) },
              { label: "Discipline", valeur: disciplineLabel(course.discipline) },
              { label: "Distance", valeur: `${course.distance.toLocaleString("fr-FR")} m` },
              { label: "Partants", valeur: course.nb_partants },
            ]}
            pied={
              course.allocation
                ? `Allocation : ${Math.round(course.allocation / 100).toLocaleString("fr-FR")} €.`
                : undefined
            }
          />
        )}
      </SeoHero>

      <Container>
        {course ? (
          <>
            <Section title={`${titleCase(course.nom ?? "")} — ${lieu?.nom}`}>
              <p className="text-sm leading-relaxed text-brand-charcoal">
                Le Quinté+ {demain ? <>de demain, {jourLong(jour)},</> : <>du {jourLong(jour)}</>} se dispute {lieu?.a} sur{" "}
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
                  className="font-medium text-brand-gold-dark underline-offset-2 hover:underline"
                >
                  la fiche de la course
                </Link>
                .
              </p>
              {course.conditions_texte && (
                <p className="mt-4 text-[13px] leading-relaxed text-brand-charcoal">
                  {course.conditions_texte}
                </p>
              )}
            </Section>

            {/* Le pronostic lui-même, dans le HTML servi : c'est ce que cherche
                « pronostic quinté du jour », et la page ne montrait que les partants. */}
            {apercu && (
              <Section title="Le pronostic IA du Quinté+">
                <AnalyseIA apercu={apercu} titre="Classement de l'IA" />
              </Section>
            )}

            <Section title={`Les ${course.nb_partants} partants du Quinté+`}>
              <div className="overflow-x-auto">
                {/* Sur téléphone : numéro, cheval, cote. Jockey et musique faisaient
                    défiler la table et coupaient la colonne de droite. */}
                <table className="w-full text-sm sm:min-w-[520px]">
                  <thead>
                    <tr className="border-b border-amber-100 text-left text-[11px] uppercase tracking-wide text-brand-charcoal">
                      <th className="py-2 pr-3">N°</th>
                      <th className="py-2 pr-3">Cheval</th>
                      <th className="hidden py-2 pr-3 sm:table-cell">Jockey</th>
                      <th className="hidden py-2 pr-3 sm:table-cell">Musique</th>
                      <th className="py-2 pr-3 text-right">Cote</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(course.partants ?? []).map((p) => (
                      <tr
                        key={p.numero}
                        // Les non-partants étaient grisés par `opacity-40`, ce qui faisait
                        // tomber leur texte à 2,09:1 — illisible, et c'était le dernier
                        // échec de contraste de la page. L'information est déjà portée par
                        // la mention « (non-partant) » accolée au nom : un fond légèrement
                        // teinté suffit à les distinguer sans toucher au contraste du texte.
                        className={`border-b border-amber-50 ${p.non_partant ? "bg-stone-100/70" : ""}`}
                      >
                        <td className="py-2 pr-3 font-semibold tabular-nums"><CasaqueNumero numero={p.numero} imgUrl={p.casaque_image_url} /></td>
                        <td className="py-2 pr-3 font-medium text-brand-dark">
                          {titleCase(p.nom_cheval)}
                          {p.non_partant ? " (non-partant)" : ""}
                        </td>
                        <td className="hidden py-2 pr-3 text-brand-charcoal sm:table-cell">
                          {p.jockey ? titleCase(p.jockey) : "—"}
                        </td>
                        <td className="hidden py-2 pr-3 font-mono text-[12px] text-brand-charcoal sm:table-cell">
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
                <p className="text-sm text-brand-charcoal">
                  Arrivée du Quinté+ du {jourLong(jour)} {lieu?.a} :{" "}
                  <strong className="tabular-nums">
                    {resultats.classement
                      .slice(0, 5)
                      .map((l) => l.numero)
                      .join(" - ")}
                  </strong>
                </p>
                <ol className="mt-3 space-y-1 text-sm text-brand-charcoal">
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
                <p className="text-sm text-brand-charcoal">
                  Rapports pour 1 € de mise, publiés par le PMU après l&apos;arrivée.
                </p>
                <div className="mt-3 overflow-x-auto">
                  <table className="w-full text-sm">
                    <tbody>
                      {rapports.map(([code, val]) => (
                        <tr key={code} className="border-b border-amber-50">
                          <td className="py-2 pr-3 text-brand-charcoal">{libellePari(code)}</td>
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
                    <ul className="mt-2 space-y-1 text-sm text-brand-charcoal">
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
            <p className="text-sm text-brand-charcoal">
              Les partants du Quinté+ sont publiés la veille de la course.{" "}
              {demain ? (
                <>
                  En attendant, retrouvez le{" "}
                  <Link href="/quinte-du-jour" className="font-medium text-brand-gold-dark hover:underline">
                    pronostic du Quinté+ du jour
                  </Link>
                  .
                </>
              ) : (
                <>
                  En attendant, le{" "}
                  <Link href="/programme" className="font-medium text-brand-gold-dark hover:underline">
                    programme complet du jour
                  </Link>{" "}
                  est déjà disponible.
                </>
              )}
            </p>
          </Section>
        )}

        {/* Le Quinté+ attire le trafic le plus large de la journée, souvent des
            visiteurs qui ne connaissent pas le site : ces six courses courues, avec
            le rang donné au gagnant, sont la preuve la plus courte à lire. */}
        <div className="mt-10">
          <PreuvesRecentesCard />
        </div>

        <Callout href={page.autreUrl} cta={page.autreCta}>
          {page.autreTexte}
        </Callout>

        <div className="mt-10">
          <NewsletterForm source={demain ? "quinte-de-demain" : "quinte-du-jour"} />
        </div>

        <Section title="Comment lire un Quinté+">
          <p className="text-sm leading-relaxed text-brand-charcoal">
            Le Quinté+ demande de désigner les cinq premiers chevaux d&apos;une course. Trouvé dans
            l&apos;ordre exact, il paie souvent plusieurs milliers d&apos;euros ; dans le désordre,
            quelques centaines. Le PMU prélève environ 20 % des enjeux avant redistribution : sur ce
            type de pari, le seul avantage possible vient d&apos;un écart entre la probabilité
            réelle d&apos;un cheval et celle qu&apos;implique sa cote — c&apos;est exactement ce que
            mesure BlackTurf, sans promettre de gain.{" "}
            <Link href="/guides/pari-de-valeur" className="font-medium text-brand-gold-dark hover:underline">
              Comprendre le pari de valeur
            </Link>{" "}
            ·{" "}
            <Link href="/guides/types-de-paris-pmu" className="font-medium text-brand-gold-dark hover:underline">
              Tous les types de paris PMU
            </Link>
          </p>
        </Section>
      </Container>
    </>
  );
}
