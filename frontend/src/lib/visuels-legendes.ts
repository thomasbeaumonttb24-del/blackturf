import {
  fetchProgramme,
  fetchResultats,
  jourParis,
  heureParis,
  titleCase,
  disciplineLabel,
  codeReunionCourse,
  type SeoCourse,
} from "@/lib/seo";
import { rapportsTries, libellePari, formatRapport } from "@/lib/rapports";
import { MENTION_LEGALE, HASHTAGS } from "@/lib/visuels";

const SITE = "https://blackturf.fr";

/**
 * Légendes des publications du jour.
 *
 * Source unique : la page /studio les affiche, et le service de publication automatique
 * du backend les récupère par `/visuels/legendes.json`. Deux rédactions parallèles
 * finiraient par diverger, et c'est la version publiée qui aurait tort.
 *
 * Aucune légende ne contient de pronostic ni de projection de gain : elles circulent hors
 * du site et ne doivent pas pouvoir se lire comme une promesse. La mention de jeu
 * responsable y est systématique.
 */
export interface Publication {
  cle: "matin" | "soir";
  titre: string;
  image: string;
  fichier: string;
  legende: string;
  /** false = données pas encore disponibles : ne rien publier. */
  pret: boolean;
}

async function quinteDuJour(jour: string): Promise<SeoCourse | null> {
  const prog = await fetchProgramme(jour);
  for (const r of prog?.reunions ?? []) {
    for (const c of r.courses ?? []) if (c.est_quinte) return c;
  }
  return null;
}

export async function publicationsDuJour(): Promise<Publication[]> {
  const jour = jourParis();
  const quinte = await quinteDuJour(jour);
  const resultats = quinte ? await fetchResultats(quinte.course_id) : null;
  const classement = resultats?.classement?.slice(0, 5) ?? [];
  const rapports = rapportsTries(resultats?.rapports).slice(0, 4);

  const legendeMatin = quinte
    ? [
        `Quinté+ du jour — ${titleCase(quinte.hippodrome_nom)}.`,
        "",
        `${codeReunionCourse(quinte.course_id)} · ${disciplineLabel(quinte.discipline)} · ${
          quinte.distance
        } m · ${quinte.nb_partants} partants · départ ${heureParis(quinte.date_heure)}.`,
        "",
        "Partants, cotes comparées et probabilité calculée pour chaque cheval :",
        `${SITE}/quinte-du-jour`,
        "",
        MENTION_LEGALE,
        "",
        HASHTAGS,
      ].join("\n")
    : [
        "Le support du Quinté+ n'est pas encore publié — le PMU le désigne la veille au soir.",
        "",
        `Le programme complet du jour est en ligne : ${SITE}/programme`,
        "",
        MENTION_LEGALE,
        "",
        HASHTAGS,
      ].join("\n");

  const legendeSoir = classement.length
    ? [
        `Arrivée du Quinté+ — ${titleCase(quinte!.hippodrome_nom)}.`,
        "",
        classement.map((l) => l.numero).join(" - "),
        "",
        ...classement.map((l) => `${l.position}. n°${l.numero} ${titleCase(l.nom)}`),
        "",
        ...(rapports.length
          ? [
              "Rapports officiels pour 1 € :",
              rapports.map(([c, v]) => `${libellePari(c)} ${formatRapport(v)} €`).join(" · "),
              "",
            ]
          : []),
        `Toutes les arrivées et tous les rapports du jour : ${SITE}/resultats`,
        "",
        MENTION_LEGALE,
        "",
        HASHTAGS,
      ].join("\n")
    : "L'arrivée n'est pas encore publiée. Cette légende se remplit seule dès que le PMU publie les rapports.";

  return [
    {
      cle: "matin",
      titre: "Post du matin — Quinté+ du jour",
      image: `${SITE}/visuels/quinte.jpg`,
      fichier: `blackturf-quinte-${jour}.jpg`,
      legende: legendeMatin,
      pret: Boolean(quinte),
    },
    {
      cle: "soir",
      titre: "Post du soir — arrivée et rapports",
      image: `${SITE}/visuels/arrivee.jpg`,
      fichier: `blackturf-arrivee-${jour}.jpg`,
      legende: legendeSoir,
      pret: classement.length > 0,
    },
  ];
}
