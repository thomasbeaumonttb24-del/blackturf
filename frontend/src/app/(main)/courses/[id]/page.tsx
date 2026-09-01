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
  jourCourtAnnee,
  jourParis,
  jourDeCourseId,
  codeReunionCourse,
  ogBase,
  twitterBase,
  type SeoCourseDetail,
  type SeoResultats,

  jsonLd,
  fetchApercuCourse,
} from "@/lib/seo";
import { NewsletterForm } from "@/components/newsletter/NewsletterForm";
import CourseClient from "./CourseClient";

// ISR 2 min : les fiches à venir bougent (cotes, non-partants), les fiches terminées sont
// figées. Un crawl ne déclenche donc au pire qu'un appel API toutes les deux minutes.
export const revalidate = 120;

/**
 * Tableau vide, et c'est délibéré.
 *
 * Sans `generateStaticParams`, Next traite une route dynamique comme rendue à la demande
 * et n'en met JAMAIS le HTML en cache : chaque requête repassait par le rendu complet et
 * la réponse partait en `Cache-Control: private, no-cache, no-store`. Le `revalidate`
 * ci-dessus ne portait que sur les appels `fetch`, pas sur la page. Mesuré le 2026-08-26
 * en production : 1,18 s pour une fiche froide, contre 0,11 s sur les pages capables
 * d'ISR — sur un site qui publie près de dix-sept mille fiches, dont la quasi-totalité
 * est « froide » quand un robot s'y présente.
 *
 * La documentation de Next est explicite : il faut retourner un tableau vide pour que les
 * chemins soient régénérables à l'exécution. Vide, parce qu'il n'est pas question de
 * pré-générer dix-sept mille pages à chaque build : chaque fiche est rendue à sa première
 * demande, puis servie depuis le cache.
 */
export async function generateStaticParams() {
  return [];
}

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

  const title = titreCourse(c, termine);

  // Le nom d'un prix peut être long : on garde la date courte et une queue brève pour
  // rester sous les ~155-160 caractères après lesquels Google tronque l'extrait.
  const description =
    `${libelleCourse(c)} — ${hippo}, ${disc}, ${c.distance} m, ${c.nb_partants} partants` +
    (jour ? `, ${jourCourt(jour)} à ${heureParis(c.date_heure)}` : "") +
    (c.est_quinte ? ". Support du Quinté+" : "") +
    // Le mot « partants » figurait deux fois dans la même description (une fois dans le
    // décompte, une fois dans la queue). La queue dit maintenant ce que la page a de
    // singulier : la probabilité vient du modèle, pas d'un avis.
    (termine ? ". Arrivée et rapports PMU." : ". Cotes et probabilité de victoire calculée par l'IA.");

  return {
    title,
    description,
    alternates: { canonical: `/courses/${c.course_id}` },
    openGraph: ogBase({
      title,
      description,
      url: `/courses/${c.course_id}`,
      type: "article",
    }),
    twitter: twitterBase({ title, description }),
  };
}

/**
 * Titre d'une fiche course.
 *
 * L'ancien format — « R2C1 Paris-Vincennes — arrivée, rapports et partants » — avait deux
 * défauts mesurés le 2026-08-26 :
 *
 *  1. il ne portait aucune date, donc chaque R1C1 courue à Vichy depuis septembre 2025
 *     partageait exactement le même `<title>` ; sur près de dix-sept mille fiches, cela
 *     faisait autant de doublons entre lesquels Google devait trancher seul ;
 *  2. il omettait le nom du prix — pourtant l'intitulé de la course, affiché en `h1` et
 *     précisément ce qu'un parieur tape (« prix de saint-galmier arrivée »).
 *
 * Le nom du prix passe donc devant, la date rend le titre unique à vie. Le code de course
 * et l'hippodrome restent dans la description et dans le `h1` de la page.
 */
function titreCourse(c: SeoCourseDetail, termine: boolean): string {
  const jour = jourDeCourseId(c.course_id);
  // Le mot « IA » figure dans le titre des courses à venir, pas dans celui des courses
  // courues : sur une course à venir, ce que la page apporte de plus que le programme du
  // PMU EST l'analyse du modèle ; une fois l'arrivée connue, l'intention de recherche
  // bascule sur « arrivée » et « rapports ». Le terme est exact — la page publie bien une
  // probabilité par cheval calculée par le modèle — et n'est écrit qu'une fois.
  const suffixe = termine ? "arrivée et rapports" : "pronostic IA et partants";
  const dateTxt = jour ? ` du ${jourCourtAnnee(jour)}` : "";
  const nom = titleCase(c.nom ?? "");

  // Sans nom de prix (courses étrangères, imports partiels), le couple code + hippodrome
  // reste discriminant dès lors que la date est présente.
  if (!nom) {
    return `${codeReunionCourse(c.course_id)} ${titleCase(c.hippodrome_nom)} — ${suffixe}${dateTxt}`;
  }

  // Google recoupe le titre autour de 60-65 caractères : au-delà, c'est la fin — donc la
  // date, seule garante de l'unicité — qui disparaîtrait. On raccourcit le nom du prix
  // plutôt que de laisser tomber la date, et on coupe sur un mot entier : « Prix De
  // L'Agriculture De P… » se lit moins bien que « Prix De L'Agriculture… ».
  const fixe = ` — ${suffixe}${dateTxt}`;
  const budget = 65 - fixe.length;
  if (nom.length <= budget) return `${nom}${fixe}`;

  const coupe = nom.slice(0, Math.max(14, budget - 1));
  const dernierEspace = coupe.lastIndexOf(" ");
  // Un mot unique plus long que le budget se coupe quand même : mieux vaut un titre
  // tronqué qu'un titre qui déborde et perd sa date.
  const nomCourt = dernierEspace > 12 ? coupe.slice(0, dernierEspace) : coupe.trimEnd();
  return `${nomCourt}…${fixe}`;
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
  //
  // Le cheval était typé `Person` et son jockey placé en `affiliation` de type
  // `Organization` : un cheval n'est pas une personne et un driver n'est pas une société.
  // Schema.org n'a pas de type « cheval de course » ; `SportsTeam` est le porteur correct
  // d'un binôme cheval + jockey — un compétiteur composé de plusieurs individus — et
  // `athlete` y déclare le jockey, qui, lui, est bien une personne.
  const partants = (c.partants ?? []).filter((p) => !p.non_partant);
  if (partants.length) {
    event.competitor = partants.map((p) => ({
      "@type": "SportsTeam",
      name: titleCase(p.nom_cheval),
      ...(p.jockey ? { athlete: { "@type": "Person", name: titleCase(p.jockey) } } : {}),
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
  // En parallèle : l'arrivée (course terminée) et l'aperçu de l'analyse. Les deux
  // appels sont indépendants — les enchaîner ajouterait leur latence l'une à
  // l'autre sur le chemin du rendu, et cette page est rendue à la demande.
  const [resultats, apercu] = course
    ? await Promise.all([
        course.statut === "termine" ? fetchResultats(id) : Promise.resolve(null),
        fetchApercuCourse(id),
      ])
    : [null, null];

  const jour = course ? jourDeCourseId(course.course_id) : null;
  const estAujourdhui = jour === jourParis();

  // Le fil d'Ariane d'une course PASSÉE pointait vers « Programme du jour », c'est-à-dire
  // vers le programme d'aujourd'hui : un parent qui ne contient pas l'enfant. Une fiche
  // archivée remonte désormais vers sa journée d'arrivées, qui la liste réellement.
  const parent = course
    ? estAujourdhui || !jour
      ? { name: "Programme du jour", item: "https://blackturf.fr/programme" }
      : { name: `Résultats du ${jourCourtAnnee(jour)}`, item: `https://blackturf.fr/resultats/${jour}` }
    : null;

  const breadcrumbJsonLd =
    course && parent
      ? {
          "@context": "https://schema.org",
          "@type": "BreadcrumbList",
          itemListElement: [
            { "@type": "ListItem", position: 1, name: "Accueil", item: "https://blackturf.fr" },
            { "@type": "ListItem", position: 2, ...parent },
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
          dangerouslySetInnerHTML={{ __html: jsonLd(jsonLdCourse(course, resultats)) }}
        />
      )}
      {breadcrumbJsonLd && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: jsonLd(breadcrumbJsonLd) }}
        />
      )}

      {/* Le composant client reçoit la course ET, si elle est courue, son arrivée : son
          premier rendu — celui du HTML servi — contient donc le nom de la course, les
          partants, les cotes et le classement, au lieu d'un message d'attente. */}
      <CourseClient initialCourse={course as never} initialResultats={resultats as never} />

      {/* Fiche course en toutes lettres. Doublure volontairement sobre de l'application
          au-dessus : elle reste lisible sans JavaScript, s'imprime, et donne au moteur de
          recherche une formulation explicite de ce que contient la page. Elle ne rejoue
          PAS la mise en page de l'onglet Partants : ici, un tableau de référence — état
          civil de la course, engagés, et l'arrivée quand elle est connue. */}
      {course && (
        <section className="mx-auto max-w-5xl px-4 pb-16 sm:px-6">
          {/* `<details>` natif : le contenu reste dans le HTML servi — lisible sans
              JavaScript et par un robot d'indexation, ce qui est toute la raison
              d'être de ce bloc — mais il ne déroule plus douze lignes de tableau
              sous une page déjà longue tant que le lecteur ne l'a pas demandé. */}
          <details className="group rounded-2xl border border-stone-200 bg-white">
            <summary className="flex cursor-pointer list-none items-center gap-3 p-5 sm:p-7 [&::-webkit-details-marker]:hidden">
              <span className="min-w-0">
                <span className="block text-[11px] font-semibold uppercase tracking-[0.12em] text-stone-600">
                  Fiche course
                </span>
                <h2 className="mt-1 font-display text-lg font-bold text-slate-900">
                  {libelleCourse(course)} — {titleCase(course.hippodrome_nom)}
                  {jour ? `, ${jourLong(jour)}` : ""}
                </h2>
              </span>
              <span className="ml-auto flex shrink-0 items-center gap-2 text-[12px] font-medium text-stone-600">
                <span className="hidden sm:inline">Engagés, conditions et arrivée</span>
                <svg className="h-4 w-4 transition-transform group-open:rotate-180" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <path d="m6 9 6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </span>
            </summary>
            <div className="px-5 pb-5 sm:px-7 sm:pb-7">

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
                  <dt className="text-[11px] text-stone-600">{c.k}</dt>
                  <dd className="mt-0.5 font-display text-[13.5px] font-bold text-slate-900">{c.v}</dd>
                </div>
              ))}
            </dl>

            {(course.est_quinte || course.est_quarte || course.est_tierce) && (
              <div className="mt-3 flex flex-wrap gap-2">
                {course.est_quinte && (
                  <span className="rounded-full bg-amber-500 px-3 py-1 text-[11px] font-semibold text-brand-dark">
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
                <h3 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-stone-600">
                  Conditions de la course
                </h3>
                <p className="mt-1.5 text-[13px] leading-relaxed text-stone-600">
                  {course.conditions_texte}
                </p>
              </div>
            )}

            {/* ── L'ANALYSE, EN CLAIR DANS LE HTML SERVI ──────────────────────
                Le HTML d'une fiche course ne contenait AUCUNE probabilité :
                `grep proba_top1 course.html` renvoyait 0, sur ~17 000 fiches
                publiées. Tout arrivait par un `fetch` du navigateur — donc
                invisible pour un moteur de recherche, et invisible pour un
                visiteur avant l'hydratation, sur la page même censée convertir.

                Rien de nouveau n'est publié ici : le masquage est appliqué CÔTÉ
                SERVEUR par `/courses/{id}/apercu` (ligne non révélée → ni numéro
                ni nom ne quittent l'API ; seuls le rang, les probabilités et la
                cote juste sortent, et la cote juste n'est que 1/proba). C'est le
                même contenu que l'application affiche déjà, simplement présent
                dès le premier octet. */}
            {apercu && apercu.classement.length > 0 && (
              <>
                <h3 className="mt-6 font-display text-[15px] font-bold text-slate-900">
                  Analyse IA de la course ({apercu.nb_analyses} chevaux notés)
                </h3>
                <p className="mt-1.5 text-[13px] leading-relaxed text-stone-600">
                  {apercu.proba_top1 != null && (
                    <>
                      Le premier du classement est donné gagnant à{" "}
                      {(apercu.proba_top1 * 100).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} %
                      {apercu.confiance != null ? `, avec une confiance de ${apercu.confiance}/100` : ""}.{" "}
                    </>
                  )}
                  {apercu.accord_marche === true && "Il est aussi le favori des cotes. "}
                  {apercu.accord_marche === false && "Le marché, lui, en désigne un autre. "}
                  {/* L'accord était figé au pluriel : « 1 chevaux sont crédités » s'affichait tel
                      quel sur toutes les fiches à un seul écarté. */}
                  {apercu.nb_ecartes > 0 &&
                    (apercu.nb_ecartes === 1
                      ? `1 cheval est crédité de moins de 3 % de chances. `
                      : `${apercu.nb_ecartes} chevaux sont crédités de moins de 3 % de chances. `)}
                  La cote juste est l&apos;inverse de la probabilité : au-dessus, le cheval est
                  payé plus qu&apos;il ne vaut ; en dessous, moins.{" "}
                  <a
                    href="/pronostics-ia"
                    className="font-medium text-brand-gold-dark underline-offset-2 hover:underline"
                  >
                    Comment l&apos;IA calcule ces probabilités
                  </a>
                  .
                </p>
                <div className="mt-3 overflow-x-auto rounded-xl border border-stone-200">
                  <table className="w-full min-w-[460px] border-collapse text-[13px]">
                    <caption className="sr-only">
                      Classement prédit par BlackTurf, probabilité de victoire et cote juste
                    </caption>
                    <thead>
                      <tr className="bg-stone-50 text-left text-[11px] uppercase tracking-[0.08em] text-stone-600">
                        <th scope="col" className="px-3 py-2 font-semibold">Rang</th>
                        <th scope="col" className="px-3 py-2 font-semibold">Cheval</th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">Proba. victoire</th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">Cote juste</th>
                      </tr>
                    </thead>
                    <tbody>
                      {apercu.classement.map((l) => (
                        <tr key={l.rang} className="border-t border-stone-100 text-stone-600">
                          <td className="px-3 py-2 font-display font-bold tabular-nums text-slate-900">
                            {l.rang}
                          </td>
                          <td className="px-3 py-2 font-medium text-slate-900">
                            {l.revele && l.nom ? (
                              <>
                                {l.numero != null && (
                                  <span className="mr-1.5 tabular-nums text-stone-600">{l.numero}</span>
                                )}
                                {titleCase(l.nom)}
                              </>
                            ) : (
                              // Masqué PAR LE SERVEUR : le nom n'existe pas dans la
                              // réponse. Pas un flou CSS, qui se retire en deux clics.
                              <span className="text-stone-500">Réservé aux abonnés</span>
                            )}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {l.proba_top1 != null
                              ? `${(l.proba_top1 * 100).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} %`
                              : "—"}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {l.cote_juste != null
                              ? l.cote_juste.toLocaleString("fr-FR", { maximumFractionDigits: 1 })
                              : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}

            <h3 className="mt-6 font-display text-[15px] font-bold text-slate-900">
              Tous les engagés ({course.nb_partants})
            </h3>
            <div className="mt-3 overflow-x-auto rounded-xl border border-stone-200">
              <table className="w-full min-w-[560px] border-collapse text-[13px]">
                <thead>
                  <tr className="bg-stone-50 text-left text-[11px] uppercase tracking-[0.08em] text-stone-600">
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
                        className={`border-t border-stone-100 ${p.non_partant ? "text-stone-600" : "text-stone-600"}`}
                      >
                        <td className="px-3 py-2 font-display font-bold tabular-nums text-slate-900">
                          {p.numero}
                        </td>
                        <td className={`px-3 py-2 font-medium text-slate-900 ${p.non_partant ? "line-through opacity-60" : ""}`}>
                          {titleCase(p.nom_cheval)}
                          {p.non_partant ? (
                            <span className="ml-2 rounded-full bg-stone-100 px-2 py-0.5 text-[10.5px] font-semibold uppercase text-stone-600">
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
                                    : "text-stone-600"
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
                { href: "/pronostics-ia", txt: "Comment l'IA analyse une course" },
                { href: "/track-record", txt: "Les résultats mesurés de l'IA" },
              ].map((l) => (
                <a
                  key={l.href}
                  href={l.href}
                  className="rounded-full border border-stone-200 bg-stone-50 px-3 py-1.5 font-medium text-stone-600 transition-colors hover:border-brand-gold-deep hover:text-brand-gold-dark"
                >
                  {l.txt}
                </a>
              ))}
            </nav>
            </div>
          </details>

          <div className="mt-10">
            <NewsletterForm source="course" />
          </div>
        </section>
      )}

    </>
  );
}
