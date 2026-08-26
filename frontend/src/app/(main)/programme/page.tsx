import type { Metadata } from "next";
import {
  fetchProgramme,
  fetchValueBetsCompteur,
  jourParis,
  jourLong,
  jourCourt,
  heureParis,
  titleCase,
  disciplineLabel,
} from "@/lib/seo";
import { NewsletterForm } from "@/components/newsletter/NewsletterForm";
import { PreuvesRecentesCard } from "@/components/courses/insights";
import ProgrammeClient from "./ProgrammeClient";

// ISR 5 min : le programme du jour est régénéré côté serveur, donc Googlebot reçoit un
// HTML déjà rempli sans que chaque crawl tape l'API.
export const revalidate = 300;

export async function generateMetadata(): Promise<Metadata> {
  const jour = jourParis();
  const prog = await fetchProgramme(jour);
  const nbCourses = prog?.nb_courses ?? 0;
  const nbReunions = prog?.reunions?.length ?? 0;
  const hippodromes = (prog?.reunions ?? [])
    .map((r) => titleCase(r.hippodrome))
    .filter(Boolean)
    .slice(0, 2)
    .join(", ");

  const title = nbCourses
    ? `Programme PMU du ${jourCourt(jour)} — ${nbCourses} courses, ${nbReunions} réunions`
    : `Programme PMU du jour — réunions et courses`;
  // Google tronque l'extrait autour de 155-160 caractères : l'information la plus
  // spécifique (date, volume, hippodromes) passe devant, la promesse produit derrière.
  const description = nbCourses
    ? `Les ${nbCourses} courses PMU du ${jourLong(jour)}, sur ${nbReunions} réunions${
        hippodromes ? ` : ${hippodromes}` : ""
      }. Partants, cotes et heure de départ.`
    : "Le programme PMU du jour, réunion par réunion : partants, cotes et heures de départ.";

  return {
    title,
    description,
    alternates: { canonical: "/programme" },
    openGraph: {
      title,
      description,
      url: "https://blackturf.fr/programme",
      type: "website",
    },
  };
}

export default async function ProgrammePage() {
  const jour = jourParis();
  const [prog, compteurVB] = await Promise.all([fetchProgramme(jour), fetchValueBetsCompteur(3)]);

  // ItemList des courses du jour → Google comprend la page comme un index d'événements
  // datés et non comme une page générique, ce qui aide la fraîcheur (Top Stories / query
  // deserves freshness sur « programme pmu <date> »).
  const itemListJsonLd = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    name: `Programme PMU du ${jourLong(jour)}`,
    numberOfItems: prog?.nb_courses ?? 0,
    itemListElement: (prog?.reunions ?? []).flatMap((r) =>
      (r.courses ?? []).map((c, i) => ({
        "@type": "ListItem",
        position: i + 1,
        url: `https://blackturf.fr/courses/${c.course_id}`,
        name: `${titleCase(c.hippodrome_nom)} — ${c.nom ?? `Course ${c.numero}`} (${heureParis(
          c.date_heure,
        )})`,
      })),
    ),
  };

  const breadcrumbJsonLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "Accueil", item: "https://blackturf.fr" },
      { "@type": "ListItem", position: 2, name: "Programme du jour", item: "https://blackturf.fr/programme" },
    ],
  };

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(itemListJsonLd) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumbJsonLd) }}
      />
      <ProgrammeClient initialProgramme={prog} initialJour={jour} initialCompteurVB={compteurVB} />

      {/* Le visiteur qui découvre le site par le programme ne voit, sinon, qu'une
          liste d'horaires : rien ne lui dit qu'un modèle tourne derrière. Ces six
          courses courues, avec le rang donné au gagnant, sont vérifiables une par
          une — et ce sont les plus récentes, pas les mieux réussies. */}
      <section className="mx-auto mb-10 max-w-7xl px-4 sm:px-6 lg:px-8">
        <PreuvesRecentesCard />
      </section>

      {/* Récapitulatif texte du jour. Le composant client, lui, est une application :
          filtres, compte à rebours, cotes live. Ce bloc est la version stable et
          imprimable du programme — utile au visiteur pressé, et lisible par un robot
          d'indexation même si le JavaScript ne s'exécute pas. */}
      <section className="mx-auto max-w-7xl px-4 pb-16 sm:px-6 lg:px-8">
        <h2 className="font-display text-xl font-bold text-gray-900">
          Toutes les courses du {jourLong(jour)}
        </h2>
        <p className="mt-2 max-w-3xl text-sm text-gray-600">
          {prog?.nb_courses
            ? `${prog.nb_courses} courses réparties sur ${prog.reunions.length} réunions. Cliquez sur une course pour ouvrir sa fiche : partants, cotes des principaux opérateurs, arrivée et rapports officiels une fois la course courue.`
            : "Le programme du jour n'est pas encore disponible. Il est publié par le PMU la veille au soir."}
        </p>

        <div className="mt-6 space-y-8">
          {(prog?.reunions ?? []).map((r) => (
            <div key={r.reunion_id}>
              <h3 className="text-sm font-bold uppercase tracking-wide text-gray-700">
                R{r.numero} — {titleCase(r.hippodrome)}
              </h3>
              <ul className="mt-2 grid gap-x-6 gap-y-1 sm:grid-cols-2 lg:grid-cols-3">
                {(r.courses ?? []).map((c) => (
                  <li key={c.course_id} className="text-sm text-gray-600">
                    <a
                      href={`/courses/${c.course_id}`}
                      className="hover:text-brand-gold-dark hover:underline"
                    >
                      <span className="tabular-nums font-medium text-gray-800">
                        {heureParis(c.date_heure)}
                      </span>{" "}
                      C{c.numero} · {titleCase(c.nom ?? "")}
                    </a>{" "}
                    <span className="text-gray-600">
                      ({disciplineLabel(c.discipline)}, {c.distance} m, {c.nb_partants} partants
                      {c.est_quinte ? ", Quinté+" : ""})
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-12 max-w-2xl">
          <NewsletterForm source="programme" />
        </div>
      </section>
    </>
  );
}
