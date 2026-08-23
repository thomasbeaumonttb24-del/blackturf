import { jourParis, jourLong } from "@/lib/seo";
import { MENTION_LEGALE, HASHTAGS } from "@/lib/visuels";

export const revalidate = 900;

const SITE = "https://blackturf.fr";

/**
 * Les six tuiles, DANS LEUR ORDRE DE PUBLICATION.
 *
 * La grille d'un profil Instagram se remplit du plus récent en haut à gauche, puis vers
 * la droite. Pour que la mosaïque se reconstitue, il faut donc publier À L'ENVERS : la
 * tuile en bas à droite en premier, celle en haut à gauche en dernier. Publier dans
 * l'ordre de lecture donnerait une image en miroir, tête-bêche.
 *
 * Chaque tuile porte sa propre légende : dans le fil, un abonné ne verra jamais que la
 * tuile isolée, jamais la mosaïque. La dernière publiée — celle qui restera en tête du
 * profil — porte le message complet.
 *
 * ── CE QU'UNE LÉGENDE DOIT FAIRE ────────────────────────────────────────────────────
 *
 * Instagram coupe au bout d'environ 125 caractères : la première ligne est la seule
 * qu'on lit à coup sûr. Elle porte donc l'accroche, jamais un préambule. Vient ensuite
 * la substance, puis UN appel à l'action, puis le pied légal.
 *
 * Vocabulaire verrouillé : « misés » et « rendus par le plan ». Jamais « gagné », jamais
 * « bénéfice » — ce sont des plans calculés puis réglés aux rapports réels du PMU, pas
 * de l'argent encaissé. Et aucune promesse de gain, nulle part : le ROI mesuré est
 * négatif, l'argument de vente est la transparence, pas le rendement.
 */
const API = (process.env.NEXT_PUBLIC_API_URL || "https://api.blackturf.fr") + "/api/v1";

interface PlanJour {
  hippodrome: string;
  code: string;
  mise: number;
  retour: number;
}

/** Mêmes règles d'écriture que sur les visuels : centimes seulement s'il y en a. */
const euro = (n: number) =>
  n.toLocaleString("fr-FR", {
    minimumFractionDigits: Number.isInteger(n) ? 0 : 2,
    maximumFractionDigits: 2,
  });

const ligne = (p: PlanJour) =>
  `${p.hippodrome} ${p.code} : ${euro(p.mise)} € misés, ${euro(p.retour)} € rendus par le plan.`;

/**
 * Les plans du jour, lus sur la même source que les visuels.
 *
 * Ils étaient écrits en dur — les légendes annonçaient donc Vincennes et 883 € quel que
 * soit le jour, alors que les images, elles, affichaient les vrais chiffres. Une légende
 * qui contredit son image sur des montants est bien pire que pas de montants du tout.
 */
async function plansDuJour(): Promise<PlanJour[]> {
  try {
    const res = await fetch(`${API}/stats/meilleurs-plans-jour`, { next: { revalidate: 600 } });
    if (!res.ok) return [];
    const d = await res.json();
    return (d.plans ?? []).map((p: Record<string, unknown>) => ({
      hippodrome: String(p.hippodrome ?? ""),
      code: String(p.code ?? ""),
      mise: Number(p.mise ?? 0),
      retour: Number(p.retour ?? 0),
    }));
  } catch {
    return [];
  }
}

export async function GET() {
  const jour = jourParis();
  const pied = `\n\n${MENTION_LEGALE}\n\n${HASHTAGS}`;
  const [p1, p2, p3] = await plansDuJour();

  const tuiles = [
    {
      tuile: "1-2",
      image: `${SITE}/visuels/mosaique/1-2`,
      legende:
        `Vous entrez votre budget. Le plan du jour se calcule dessus.\n\n` +
        `Pas un ticket type recopié pour tout le monde : un plan de jeu construit sur VOTRE ` +
        `mise, course par course, avant le départ.\n\n` +
        `Le programme PMU, les cotes et les rapports officiels sont en accès libre. ` +
        `Les prédictions, les paris de valeur et le plan de mise commencent à 12 €/mois — ` +
        `avec 7 jours d'essai offerts, résiliable à tout moment.\n\n` +
        `${SITE}` + pied,
    },
    {
      tuile: "1-1",
      image: `${SITE}/visuels/mosaique/1-1`,
      legende:
        `Le PMU prélève environ 20 % des enjeux. Voilà ce que personne ne vous dira.\n\n` +
        `Sur 100 € joués, environ 80 € repartent aux parieurs. Personne ne peut promettre ` +
        `un gain régulier là-dessus, et quiconque vous le promet vous ment ou ne sait pas ` +
        `compter.\n\n` +
        `Ce qui se mesure, en revanche, c'est l'écart entre la probabilité réelle d'un ` +
        `cheval et celle qu'implique sa cote. C'est ce que BlackTurf calcule, course par ` +
        `course — et ce qu'il publie ensuite, résultat en main.\n\n` +
        `Le seul service de pronostics qui publie aussi ses pertes.\n\n` +
        `${SITE}` + pied,
    },
    {
      tuile: "1-0",
      image: `${SITE}/visuels/mosaique/1-0`,
      legende:
        `Le dépouillement du programme, fait pendant que vous dormez.\n\n` +
        `• Il lit le programme pour vous — 80 critères par cheval, une probabilité pour ` +
        `chaque partant, publiée avant le départ\n` +
        `• Il calcule sur VOTRE mise — vous entrez votre budget, le plan se construit dessus\n` +
        `• Il compare les cotes — PMU et principaux opérateurs côte à côte, pour voir où la ` +
        `cote décroche\n` +
        `• Il publie son bilan — chaque plan réglé aux rapports réels, journées rouges ` +
        `comprises\n` +
        `• Il répond à vos questions — une course, un partant, un type de pari\n\n` +
        `7 jours d'essai offerts sur ${SITE}` + pied,
    },
    {
      tuile: "0-2",
      image: `${SITE}/visuels/mosaique/0-2`,
      legende:
        `Les deux autres plans qui ont tenu aujourd'hui.\n\n` +
        [p2, p3].filter(Boolean).map((p) => ligne(p!)).join("\n") +
        `\n\nTrois plans sur les courses du jour — et tous les autres sont en ligne eux ` +
        `aussi, gagnants comme perdants. C'est le principe : on ne montre pas que les bons ` +
        `jours.\n\n` +
        `${SITE}` + pied,
    },
    {
      tuile: "0-1",
      image: `${SITE}/visuels/mosaique/0-1`,
      legende:
        (p1
          ? `${euro(p1.mise)} € misés. ${euro(p1.retour)} € rendus par le plan. Calculé avant le départ.\n\n` +
            `${p1.hippodrome} ${p1.code}. `
          : `Le meilleur plan BlackTurf du jour.\n\n`) +
        `Le plan a été construit avant que les chevaux entrent en ` +
        `piste, puis réglé aux rapports officiels du PMU — pas rejoué après coup.\n\n` +
        `C'est le meilleur plan de la journée, pas la journée. Les autres sont publiés ` +
        `aussi, y compris ceux qui n'ont rien rendu.\n\n` +
        `Tous les plans du jour sur ${SITE}` + pied,
    },
    {
      tuile: "0-0",
      image: `${SITE}/visuels/mosaique/0-0`,
      legende:
        `Le programme du jour, passé au calcul. Pas au feeling.\n\n` +
        `Résultats PMU du ${jourLong(jour)} : toutes les courses de la journée analysées, ` +
        `arrivées et rapports officiels en accès libre, course par course.\n\n` +
        `Faites défiler le profil : les six publications forment une seule image.\n\n` +
        `${SITE}` + pied,
    },
  ];

  return Response.json(
    { jour, ordre: "publication a l'envers : bas-droite d'abord, haut-gauche en dernier", tuiles },
    { headers: { "Cache-Control": "public, max-age=900" } },
  );
}
