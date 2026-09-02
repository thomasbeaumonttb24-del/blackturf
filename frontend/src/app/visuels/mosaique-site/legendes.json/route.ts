import { MENTION_LEGALE, HASHTAGS } from "@/lib/visuels";

export const revalidate = 3600;

const SITE = "https://blackturf.fr";
const API = (process.env.NEXT_PUBLIC_API_URL || "https://api.blackturf.fr") + "/api/v1";

const nb = (n: number) => n.toLocaleString("fr-FR").replace(/[  ]/g, " ");

/**
 * Les six tuiles de la mosaïque de présentation, DANS LEUR ORDRE DE PUBLICATION.
 *
 * La grille d'un profil Instagram se remplit du plus récent en haut à gauche, puis vers
 * la droite. Pour que la mosaïque se reconstitue, il faut publier À L'ENVERS : la tuile
 * en bas à droite en premier, celle en haut à gauche en dernier. Publier dans l'ordre de
 * lecture donnerait une image tête-bêche.
 *
 * Chaque tuile porte sa propre légende : dans le fil, personne ne voit jamais la
 * mosaïque, seulement une tuile isolée. Et la première ligne est la seule qu'on lise à
 * coup sûr — Instagram coupe vers 125 caractères — donc elle porte l'accroche, jamais un
 * préambule.
 *
 * VOCABULAIRE VERROUILLÉ : aucune promesse de gain, aucun taux de réussite. Le ROI
 * mesuré est négatif ; ce qui se vend ici est la méthode et la transparence, pas le
 * rendement.
 */
export async function GET() {
  const pied = `\n\n${MENTION_LEGALE}\n\n${HASHTAGS}`;

  let coursesReglees = 0;
  let journeesPubliees = 0;
  let coursesEnBase = 0;
  let partantsAnalyses = 0;
  try {
    const res = await fetch(`${API}/stats/chiffres-site`, { next: { revalidate: 3600 } });
    if (res.ok) {
      const d = await res.json();
      coursesReglees = Number(d.courses_reglees ?? 0);
      journeesPubliees = Number(d.journees_publiees ?? 0);
      coursesEnBase = Number(d.courses_en_base ?? 0);
      partantsAnalyses = Number(d.partants_analyses ?? 0);
    }
  } catch {
    // Les légendes restent publiables sans les chiffres ; elles n'en citeront aucun.
  }

  const tuiles = [
    {
      tuile: "1-2",
      image: `${SITE}/visuels/mosaique-site/1-2`,
      legende:
        `7 jours offerts, puis 12 €/mois. Et le programme reste gratuit.\n\n` +
        `Vous créez un compte, vous entrez votre budget : le plan de jeu se calcule dessus. ` +
        `Pas un ticket type recopié pour tout le monde.\n\n` +
        `• Découverte, 0 € — programme, cotes, arrivées et rapports officiels\n` +
        `• Standard, 12 €/mois — prédictions et plan de mise\n` +
        `• Expert, 19 €/mois — paris de valeur en temps réel\n\n` +
        `Résiliable à tout moment. ${SITE}` + pied,
    },
    {
      tuile: "1-1",
      image: `${SITE}/visuels/mosaique-site/1-1`,
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
      image: `${SITE}/visuels/mosaique-site/1-0`,
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
        `7 jours offerts sur ${SITE}` + pied,
    },
    {
      tuile: "0-2",
      image: `${SITE}/visuels/mosaique-site/0-2`,
      legende:
        `80 critères par cheval, à chaque course.\n\n` +
        `Forme récente, distance, corde, driver ou jockey, entraîneur, gains, temps de ` +
        `référence, cotes du marché… Le modèle en tire une probabilité pour chaque partant, ` +
        `publiée AVANT le départ.\n\n` +
        `Ce n'est pas un avis de spécialiste : c'est un calcul, et il est daté.\n\n` +
        `${SITE}` + pied,
    },
    {
      tuile: "0-1",
      image: `${SITE}/visuels/mosaique-site/0-1`,
      legende:
        (coursesReglees
          ? `${nb(coursesReglees)} courses réglées aux rapports officiels du PMU.\n\n`
          : `Nos pronostics sont réglés aux rapports officiels du PMU.\n\n`) +
        `C'est le chiffre que les sites de pronostics ne publient jamais : le dénominateur. ` +
        `Tout le monde montre ses coups gagnants — presque personne ne dit sur combien de ` +
        `courses.\n\n` +
        `Chaque pronostic est figé AVANT le départ, puis réglé à l'arrivée aux vrais ` +
        `rapports. Aucune reconstruction après coup` +
        (journeesPubliees ? `, sur ${nb(journeesPubliees)} journées publiées` : "") +
        ` — gagnantes comme perdantes.\n\n` +
        `Le bilan est public : ${SITE}/track-record` + pied,
    },
    {
      tuile: "0-0",
      image: `${SITE}/visuels/mosaique-site/0-0`,
      legende:
        `Le programme du jour, passé au calcul. Pas au feeling.\n\n` +
        `BlackTurf analyse chaque course du programme PMU et publie, avant le départ, une ` +
        `probabilité pour chaque partant` +
        (coursesEnBase && partantsAnalyses
          ? ` — ${nb(coursesEnBase)} courses et ${nb(partantsAnalyses)} partants en base à ce jour`
          : "") +
        `.\n\n` +
        `Le programme, les cotes comparées et les rapports officiels sont en accès libre. ` +
        `Les prédictions et le plan de mise commencent à 12 €/mois, avec 7 jours offerts.\n\n` +
        `Faites défiler le profil : les six publications forment une seule image.\n\n` +
        `${SITE}` + pied,
    },
  ];

  return Response.json(
    { serie: "site", ordre: "publication a l'envers : bas-droite d'abord, haut-gauche en dernier", tuiles },
    { headers: { "Cache-Control": "public, max-age=3600" } },
  );
}
