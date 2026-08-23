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
 */
export async function GET() {
  const jour = jourParis();
  const pied = `\n\n${MENTION_LEGALE}\n\n${HASHTAGS}`;

  const tuiles = [
    {
      tuile: "1-2",
      image: `${SITE}/visuels/mosaique/1-2`,
      legende:
        `7 jours d'essai offerts sur BlackTurf.\n\n` +
        `Le programme PMU du jour et les rapports officiels sont en accès libre. ` +
        `Les prédictions, les paris de valeur et le plan de mise commencent à 12 €/mois.\n\n` +
        `${SITE}` + pied,
    },
    {
      tuile: "1-1",
      image: `${SITE}/visuels/mosaique/1-1`,
      legende:
        `Le PMU prélève environ 20 % des enjeux.\n\n` +
        `Personne ne peut promettre un gain régulier là-dessus, et quiconque le fait vous ` +
        `ment. Ce qui se mesure, c'est l'écart entre la probabilité réelle d'un cheval et ` +
        `celle qu'implique sa cote.\n\n` +
        `C'est ce que BlackTurf calcule, course par course.` + pied,
    },
    {
      tuile: "1-0",
      image: `${SITE}/visuels/mosaique/1-0`,
      legende:
        `Ce que fait BlackTurf, concrètement.\n\n` +
        `• 80 critères par cheval, une probabilité calculée pour chaque partant, avant le départ\n` +
        `• Un plan de jeu calculé sur VOTRE mise, pas un ticket type\n` +
        `• Les cotes du PMU et des principaux opérateurs côte à côte\n` +
        `• Le bilan publié, jours rouges compris\n\n` +
        `${SITE}` + pied,
    },
    {
      tuile: "0-2",
      image: `${SITE}/visuels/mosaique/0-2`,
      legende:
        `Les deux autres plans du jour.\n\n` +
        `Lion d'Angers R5C1 et R5C2 : 10 € misés sur chacun.\n\n` +
        `Tous les plans, course par course, sur ${SITE}` + pied,
    },
    {
      tuile: "0-1",
      image: `${SITE}/visuels/mosaique/0-1`,
      legende:
        `Le meilleur plan BlackTurf du jour.\n\n` +
        `Paris-Vincennes R1C4 : 10 € misés.\n\n` +
        `Le plan est calculé AVANT le départ, puis réglé aux rapports officiels du PMU. ` +
        `Tous les plans du jour sont sur ${SITE}` + pied,
    },
    {
      tuile: "0-0",
      image: `${SITE}/visuels/mosaique/0-0`,
      legende:
        `Résultats PMU du ${jourLong(jour)}.\n\n` +
        `Toutes les courses du jour analysées, arrivées et rapports officiels en accès ` +
        `libre, course par course.\n\n` +
        `Faites défiler le profil : les six publications forment une seule image.\n\n` +
        `${SITE}` + pied,
    },
  ];

  return Response.json(
    { jour, ordre: "publication a l'envers : bas-droite d'abord, haut-gauche en dernier", tuiles },
    { headers: { "Cache-Control": "public, max-age=900" } },
  );
}
