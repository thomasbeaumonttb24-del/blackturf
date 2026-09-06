import { jourParis, periodeCourte } from "@/lib/seo";
import { MENTION_LEGALE, HASHTAGS } from "@/lib/visuels";

/**
 * La publication du DIMANCHE : une tuile de la mosaïque, et sa légende.
 *
 * UNE SEULE TUILE PAR SEMAINE. La mosaïque du profil se remplit en six dimanches ;
 * au septième, l'image est complète et un nouveau cycle commence. C'est l'API qui dit
 * quelle tuile revient à quelle semaine (`/stats/bilan-semaine` → `tuile`), et pas ce
 * fichier : deux calculs parallèles finiraient par nommer deux tuiles différentes, et
 * la mosaïque se remplirait deux fois au même endroit en laissant un trou ailleurs.
 *
 * L'ordre de publication est à L'ENVERS de l'ordre de lecture — Instagram empile de la
 * plus récente à la plus ancienne, en haut à gauche.
 *
 * ATTENTION AU VOCABULAIRE — les montants sont ceux de PLANS calculés et réglés aux
 * rapports officiels du PMU, pas d'argent encaissé. « Misé » et « rendu » sont exacts ;
 * « gagné » ou « bénéfice » ne le seraient pas.
 */
export const revalidate = 600;

const SITE = "https://blackturf.fr";
const API = (process.env.NEXT_PUBLIC_API_URL || "https://api.blackturf.fr") + "/api/v1";

/** Les six angles, dans l'ordre de PUBLICATION. Chacun tient seul dans le fil. */
const ANGLES: Record<string, { titre: string; intro: string }> = {
  "1-2": {
    titre: "Vous entrez votre budget, le plan se calcule dessus",
    intro:
      "Pas un ticket type recopié pour tout le monde : un plan de jeu construit sur VOTRE mise, " +
      "course par course, avant le départ.",
  },
  "1-1": {
    titre: "Ce qu'on ne vous dira pas ailleurs",
    intro:
      "Les plans perdants sont publiés comme les autres. Un pronostiqueur qui ne montre que ses " +
      "réussites ne montre rien.",
  },
  "1-0": {
    titre: "Ce que BlackTurf fait, chaque jour",
    intro:
      "Chaque partant reçoit une probabilité calculée, chaque course un classement, chaque plan " +
      "une mise — le tout figé avant le départ et réglé aux rapports officiels.",
  },
  "0-2": {
    titre: "Ce que l'analyse a valu cette semaine",
    intro:
      "Le chiffre qui tient dans la durée n'est pas un gain : c'est la part des courses où le " +
      "gagnant réel figurait dans notre Top 3 — comparée à ce que trouverait le hasard.",
  },
  "0-1": {
    titre: "Le meilleur plan de la semaine",
    intro:
      "Calculé avant le départ, réglé au rapport officiel du PMU. Tous les autres sont en ligne, " +
      "gagnants comme perdants.",
  },
  "0-0": {
    titre: "Le programme, passé au calcul",
    intro:
      "Le programme PMU, les cotes et les rapports officiels sont en accès libre. Les prédictions, " +
      "les paris de valeur et le plan de mise commencent à 12 €/mois, avec 7 jours d'essai offerts.",
  },
};

const euro = (n: number) =>
  n
    .toLocaleString("fr-FR", {
      minimumFractionDigits: Number.isInteger(n) ? 0 : 2,
      maximumFractionDigits: 2,
    })
    .replace(/[  ]/g, " ");

const pct = (n: number) =>
  n.toLocaleString("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

export async function GET(req: Request) {
  const brut = new URL(req.url).searchParams.get("semaine");
  const url = new URL(`${API}/stats/bilan-semaine`);
  if (brut && /^\d{4}-\d{2}-\d{2}$/.test(brut)) url.searchParams.set("fin", brut);

  let d: Record<string, unknown> | null = null;
  try {
    const res = await fetch(url.toString(), { next: { revalidate: 600 } });
    if (res.ok) d = await res.json();
  } catch {
    d = null;
  }

  if (!d) {
    return Response.json(
      { pret: false, attente: "Le bilan de la semaine n'est pas disponible." },
      { headers: { "Cache-Control": "public, max-age=60" } },
    );
  }

  const a = (d.analyse ?? {}) as Record<string, number | null>;
  const m = d.meilleur_plan as Record<string, unknown> | null;
  const mj = d.meilleure_journee as Record<string, unknown> | null;
  const tuile = String(d.tuile ?? "1-2");
  const angle = ANGLES[tuile] ?? ANGLES["1-2"];
  const periode = periodeCourte(String(d.debut), String(d.fin));
  const semaine = String(d.fin);

  const lignes: string[] = [`${angle.titre} — ${periode}.`, "", angle.intro, ""];

  if (a.pct_top3 !== null && a.pct_top3 !== undefined) {
    lignes.push(
      `${pct(Number(a.pct_top3))} % des courses où le gagnant était dans notre Top 3 ` +
        `(${a.nb_top3} sur ${a.nb_courses_analysees} analysées` +
        (a.hasard_top3 !== null && a.hasard_top3 !== undefined
          ? ` ; un tirage au sort en trouverait ${pct(Number(a.hasard_top3))} %).`
          : ")."),
      "",
    );
  }

  // Le podium, comme sur le visuel : la légende et l'image doivent dire la même
  // chose. Une course n'y figure qu'une fois — le dédoublonnage est fait par l'API.
  const podium = (Array.isArray(d.meilleurs_plans) ? d.meilleurs_plans : []) as Record<
    string,
    unknown
  >[];
  if (m) {
    lignes.push(
      "Meilleur plan de la semaine : " +
        [m.type_pari, m.hippodrome, m.code].filter(Boolean).join(" · ") +
        ` — ${euro(Number(m.mise))} € misés, ${euro(Number(m.retour))} € rendus.`,
    );
    for (const p of podium.slice(1, 3)) {
      lignes.push(
        "Puis " +
          [p.type_pari, p.hippodrome, p.code].filter(Boolean).join(" · ") +
          ` — ${euro(Number(p.mise))} € misés, ${euro(Number(p.retour))} € rendus.`,
      );
    }
    lignes.push("");
  }

  if (mj) {
    lignes.push(
      `Meilleure journée : ${pct(Number(mj.pct_top3))} % de Top 3 sur ` +
        `${mj.nb_courses} courses.`,
      "",
    );
  }

  lignes.push(
    // Le nombre de plans GAGNANTS ne sort jamais sans le nombre TOTAL calculé :
    // sans dénominateur, la phrase se lirait comme si tous les plans avaient gagné.
    `Au total, les plans de la semaine ont rendu ${euro(Number(d.total_retour ?? 0))} €, ` +
      `réglés aux rapports officiels du PMU : ${d.nb_plans_gagnants} plans gagnants ` +
      `sur les ${d.nb_plans} calculés, sur ${d.nb_courses} courses et ` +
      `${d.nb_hippodromes} hippodromes.`,
    "",
    `Tous les résultats, course par course : ${SITE}`,
    "",
    "Les résultats passés ne préjugent pas des résultats futurs.",
    MENTION_LEGALE,
    "",
    HASHTAGS,
  );

  return Response.json(
    {
      pret: Number(d.nb_plans ?? 0) > 0,
      semaine: { debut: d.debut, fin: d.fin, periode },
      // Rang dans le cycle : « 1re sur 6 ». C'est ce qui dit où on en est du
      // remplissage de la mosaïque, et quand elle sera complète.
      rang: d.rang_dans_le_cycle,
      total: d.semaines_par_mosaique,
      cycle: d.cycle,
      tuile,
      image: `${SITE}/visuels/mosaique/${tuile}?semaine=${semaine}`,
      fichier: `blackturf-mosaique-${semaine}-${tuile}.jpg`,
      legende: lignes.join("\n"),
      // Aperçu de l'image entière une fois les six publiées.
      apercu_mosaique: `${SITE}/visuels/mosaique/apercu?semaine=${semaine}`,
    },
    { headers: { "Cache-Control": "public, max-age=600" } },
  );
}
