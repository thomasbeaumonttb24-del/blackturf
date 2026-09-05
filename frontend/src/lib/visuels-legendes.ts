import {
  fetchProgramme,
  fetchResultats,
  jourParis,
  jourLong,
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
  cle: "matin" | "soir" | "story";
  titre: string;
  image: string;
  fichier: string;
  legende: string;
  /** false = données pas encore disponibles : ne rien publier. */
  pret: boolean;
  /** Pourquoi ce n'est pas encore publiable. Affiché tel quel dans /studio. */
  attente?: string;
}

const API = (process.env.NEXT_PUBLIC_API_URL || "https://api.blackturf.fr") + "/api/v1";

interface BilanJour {
  totalRetour: number;
  nbPlans: number;
  nbPlansGagnants: number;
  pctTop3: number | null;
  nbTop3: number;
  nbAnalysees: number;
  hasardTop3: number | null;
  meilleur: { hippodrome: string; code: string; mise: number; retour: number; net: number;
              typePari: string | null } | null;
  /** Journée entièrement courue ET réglée : condition de publication. */
  journeeComplete: boolean;
  resteAVenir: { coursesAVenir: number; coursesEnAttente: number; plansNonRegles: number };
}

/**
 * Le bilan chiffré de la journée, pour la story du soir.
 *
 * `total_retour` est ce que les plans ont RENDU, réglé aux vrais rapports PMU. Ce n'est
 * ni un bénéfice ni de l'argent encaissé : la légende dit « rendu », jamais « gagné ».
 * Le nombre total de plans accompagne toujours le nombre de gagnants — « 29 plans
 * gagnants » tout seul se lirait comme si tous avaient gagné.
 */
async function bilanDuJour(): Promise<BilanJour | null> {
  try {
    const res = await fetch(`${API}/stats/meilleurs-plans-jour`, { next: { revalidate: 600 } });
    if (!res.ok) return null;
    const d = await res.json();
    const a = d.analyse ?? {};
    const p = (d.plans ?? [])[0];
    const nombre = (v: unknown) => (v === null || v === undefined ? null : Number(v));
    return {
      totalRetour: Number(d.total_retour ?? 0),
      nbPlans: Number(d.nb_plans ?? 0),
      nbPlansGagnants: Number(d.nb_plans_gagnants ?? 0),
      pctTop3: nombre(a.pct_top3),
      nbTop3: Number(a.nb_top3 ?? 0),
      nbAnalysees: Number(a.nb_courses_analysees ?? 0),
      hasardTop3: nombre(a.hasard_top3),
      journeeComplete: Boolean(d.journee_complete),
      resteAVenir: {
        coursesAVenir: Number(d.reste_a_venir?.courses_a_venir ?? 0),
        coursesEnAttente: Number(d.reste_a_venir?.courses_en_attente ?? 0),
        plansNonRegles: Number(d.reste_a_venir?.plans_non_regles ?? 0),
      },
      meilleur: p
        ? {
            hippodrome: String(p.hippodrome ?? ""),
            code: String(p.code ?? ""),
            mise: Number(p.mise ?? 0),
            retour: Number(p.retour ?? 0),
            net: Number(p.net ?? 0),
            typePari: p.type_pari ? String(p.type_pari) : null,
          }
        : null,
    };
  } catch {
    return null;
  }
}

const euro = (n: number) =>
  n.toLocaleString("fr-FR", {
    minimumFractionDigits: Number.isInteger(n) ? 0 : 2,
    maximumFractionDigits: 2,
  });

const pct = (n: number) =>
  n.toLocaleString("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

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

  const bilan = await bilanDuJour();
  const legendeStory = bilan
    ? [
        `Performance du jour — ${jourLong(jour)}.`,
        "",
        ...(bilan.pctTop3 !== null
          ? [
              `${pct(bilan.pctTop3)} % des courses où le gagnant était dans notre Top 3 ` +
                `(${bilan.nbTop3} sur ${bilan.nbAnalysees} analysées` +
                (bilan.hasardTop3 !== null
                  ? ` ; un tirage au sort en trouverait ${pct(bilan.hasardTop3)} %).`
                  : ")."),
              "",
            ]
          : []),
        ...(bilan.meilleur
          ? [
              "Meilleur plan de la journée : " +
                [bilan.meilleur.typePari, bilan.meilleur.hippodrome, bilan.meilleur.code]
                  .filter(Boolean)
                  .join(" · ") +
                ` — ${euro(bilan.meilleur.mise)} € misés, ${euro(bilan.meilleur.retour)} € rendus.`,
              "",
            ]
          : []),
        `Au total, les plans du jour ont rendu ${euro(bilan.totalRetour)} €, réglés aux ` +
          "rapports officiels du PMU : " +
          `${bilan.nbPlansGagnants} plans gagnants sur les ${bilan.nbPlans} calculés.`,
        "",
        `Chiffres recalculés en direct sur le site : ${SITE}`,
        "",
        "Les résultats passés ne préjugent pas des résultats futurs.",
        MENTION_LEGALE,
        "",
        HASHTAGS,
      ].join("\n")
    : "Le bilan du jour n'est pas encore réglé. Cette légende se remplit seule dès que les rapports du PMU sont publiés.";

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
    {
      // Story verticale : elle n'entre PAS dans la publication automatique (le job du
      // backend ne connaît que « matin » et « soir »). Elle se publie à la main depuis
      // /studio, une fois la journée courue.
      cle: "story",
      titre: "Story du soir — performance de la journée",
      image: `${SITE}/visuels/story.jpg`,
      fichier: `blackturf-story-${jour}.jpg`,
      legende: legendeStory,
      // RÈGLE DE PUBLICATION : après le DERNIER RÈGLEMENT de la journée, jamais avant.
      // « Au moins un plan réglé » ne suffisait pas : à 11 h du matin un tiers des
      // courses sont réglées, et le total publié aurait été démenti par la soirée.
      pret: Boolean(bilan && bilan.nbPlans > 0 && bilan.journeeComplete),
      attente: bilan ? attenteStory(bilan) : undefined,
    },
  ];
}

/**
 * Ce qu'on attend encore avant de pouvoir publier la story — en clair.
 *
 * Un drapeau « pas prêt » sans motif est indébogable un soir de publication : on ne
 * sait pas s'il faut attendre dix minutes ou aller regarder un scraper.
 */
function attenteStory(b: BilanJour): string | undefined {
  if (b.nbPlans === 0) return "Aucun plan de la journée n'est encore réglé.";
  if (b.journeeComplete) return undefined;
  const r = b.resteAVenir;
  const morceaux: string[] = [];
  if (r.coursesAVenir > 0) {
    morceaux.push(
      r.coursesAVenir === 1 ? "1 course pas encore partie" : `${r.coursesAVenir} courses pas encore parties`,
    );
  }
  if (r.coursesEnAttente > 0) {
    morceaux.push(
      r.coursesEnAttente === 1
        ? "1 course courue sans arrivée publiée"
        : `${r.coursesEnAttente} courses courues sans arrivée publiée`,
    );
  }
  if (r.plansNonRegles > 0) {
    morceaux.push(
      r.plansNonRegles === 1 ? "1 plan pas encore réglé" : `${r.plansNonRegles} plans pas encore réglés`,
    );
  }
  if (!morceaux.length) return undefined;
  return `La journée n'est pas terminée : ${morceaux.join(", ")}. Les chiffres bougeront encore.`;
}
