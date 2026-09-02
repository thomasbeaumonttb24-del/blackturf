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
 * ─────────────────────────── CE QUE PORTE UNE LÉGENDE ──────────────────────────────────
 *
 * Le visuel tient en une phrase ; la légende, elle, est le seul endroit où l'on peut
 * DÉMONTRER. Elle détaille donc ce que le visuel affirme — les familles de critères, ce
 * que « réglé » veut dire, ce que contient chaque formule. C'est aussi ce qui distingue
 * un compte de pronostics d'un compte de méthode : le premier annonce, le second montre
 * son travail.
 *
 * Contraintes de forme : Instagram coupe vers 125 caractères, donc la première ligne
 * porte l'accroche et jamais un préambule ; le plafond dur est de 2 200 caractères, pied
 * légal et mots-clés compris.
 *
 * VOCABULAIRE VERROUILLÉ : aucune promesse de gain, aucun taux de réussite. Le ROI
 * mesuré est négatif ; ce qui se vend ici est la méthode et la transparence.
 *
 * Les familles de critères listées plus bas correspondent aux variables réellement
 * calculées dans `backend/ml/features.py`. Décrire des critères qu'on ne calcule pas
 * serait un mensonge vérifiable par quiconque lit le track-record.
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
        `Ce que contient chaque formule :\n\n` +
        `DÉCOUVERTE — 0 €\n` +
        `Le programme PMU complet du jour, les partants, les cotes comparées entre ` +
        `opérateurs, les arrivées et les rapports officiels. Sans compte, sans carte.\n\n` +
        `STANDARD — 12 €/mois\n` +
        `Les prédictions : une probabilité calculée pour chaque partant, publiée avant le ` +
        `départ, avec la cote juste qui en découle. Et le plan de mise, construit sur VOTRE ` +
        `budget — vous entrez ce que vous voulez engager, le plan se calcule dessus. Trois ` +
        `profils : prudent, modéré, risqué.\n\n` +
        `EXPERT — 19 €/mois\n` +
        `En plus : les paris de valeur en temps réel, c'est-à-dire les chevaux dont la cote ` +
        `du marché est plus haute que leur chance calculée, signalés dès que l'écart ` +
        `apparaît — les cotes bougent jusqu'au départ.\n\n` +
        `7 jours d'essai, résiliable à tout moment.\n${SITE}` + pied,
    },
    {
      tuile: "1-1",
      image: `${SITE}/visuels/mosaique-site/1-1`,
      legende:
        `Votre vrai adversaire, ce n'est pas le favori. C'est le prélèvement.\n\n` +
        `Le PMU est un pari mutuel : les joueurs jouent les uns contre les autres, et la ` +
        `maison prend sa part avant de redistribuer. Sur 100 € misés, environ 80 € ` +
        `repartent aux gagnants. Les 20 € restants sont partis, quoi que vous jouiez.\n\n` +
        `Conséquence que personne n'écrit : aucun pronostiqueur n'efface ces 20 %. Un site ` +
        `qui vous promet un gain régulier vous ment, ou ne sait pas compter.\n\n` +
        `Ce qui se joue, c'est le reste. Une cote n'est pas une probabilité : elle reflète ` +
        `ce que la FOULE a misé. Un cheval à 8,0 est jugé à 12,5 % de chances par le marché. ` +
        `S'il en vaut réellement 18 %, il est sous-coté — et c'est le seul endroit où un ` +
        `avantage existe.\n\n` +
        `BlackTurf mesure cet écart sur chaque partant, avant le départ, puis publie le ` +
        `résultat aux vrais rapports. Y compris quand il a tort.\n\n` +
        `Le bilan complet, pertes comprises : ${SITE}/track-record` + pied,
    },
    {
      tuile: "1-0",
      image: `${SITE}/visuels/mosaique-site/1-0`,
      legende:
        `Le dépouillement du programme, fait pendant que vous dormez.\n\n` +
        `IL LIT LE PROGRAMME — toutes les réunions, toutes les courses, tous les partants. ` +
        `Chaque cheval reçoit une probabilité, publiée avant le départ.\n\n` +
        `IL CALCULE SUR VOTRE MISE — vous entrez votre budget, le plan de jeu se construit ` +
        `dessus : quels chevaux, quels types de paris, combien sur chacun. Pas un ticket ` +
        `type recopié à l'identique pour tout le monde.\n\n` +
        `IL COMPARE LES COTES — PMU et principaux opérateurs côte à côte, avec l'historique ` +
        `du mouvement. On voit quand une cote décroche, et dans quel sens.\n\n` +
        `IL PUBLIE SON BILAN — chaque plan est réglé aux rapports réels du PMU. Les ` +
        `journées perdantes restent en ligne, à la même place que les autres.\n\n` +
        `IL RÉPOND À VOS QUESTIONS — une course, un partant, un type de pari : l'assistant ` +
        `répond sur vos données, pas sur des généralités.\n\n` +
        `7 jours offerts sur ${SITE}` + pied,
    },
    {
      tuile: "0-2",
      image: `${SITE}/visuels/mosaique-site/0-2`,
      legende:
        `80 critères par cheval, à chaque course. Voici lesquels.\n\n` +
        `LE CHEVAL — forme sur 1, 3, 5 et 10 sorties, tendance, régularité, classement ELO ` +
        `par discipline et écart au reste du champ, gains rapportés au nombre de courses, ` +
        `âge, sexe, jours de repos, fraîcheur, montée ou descente de catégorie.\n\n` +
        `LA VITESSE — figures de vitesse récente, moyenne et meilleure, constance ` +
        `chronométrique, indice d'endurance sur la distance.\n\n` +
        `L'HUMAIN — taux de victoire et de place du jockey ou du driver et de l'entraîneur, ` +
        `forme sur 7 et 30 jours, réussite sur cet hippodrome précis, synergie du couple ` +
        `cheval-jockey, association jockey-entraîneur.\n\n` +
        `LA COURSE — nombre de partants, dotation, niveau, distance, discipline, corde et ` +
        `biais de corde, état du terrain et pénétromètre, météo, heure, hippodrome.\n\n` +
        `LE SCÉNARIO — style de course (mène ou suit), conflit de train entre les meneurs, ` +
        `qualité de l'opposition. Au trot : déferrage, recul au départ, risque de galop.\n\n` +
        `LE MARCHÉ — cotes des opérateurs, probabilité implicite, rang de cote, mouvement ` +
        `dans les 30 dernières minutes, concentration des enjeux.\n\n` +
        `Ce n'est pas un avis. C'est un calcul, et il est daté.\n${SITE}` + pied,
    },
    {
      tuile: "0-1",
      image: `${SITE}/visuels/mosaique-site/0-1`,
      legende:
        (coursesReglees
          ? `${nb(coursesReglees)} courses réglées aux rapports officiels du PMU.\n\n`
          : `Nos pronostics sont réglés aux rapports officiels du PMU.\n\n`) +
        `C'est le chiffre que les sites de pronostics ne publient jamais : le dénominateur. ` +
        `Tout le monde montre ses coups gagnants. Presque personne ne dit sur combien de ` +
        `courses ils ont été trouvés — et sans ce nombre, une capture d'écran ne prouve ` +
        `rien.\n\n` +
        `CE QUE « RÉGLÉ » VEUT DIRE ICI :\n` +
        `1. le plan est calculé et ENREGISTRÉ avant le départ, horodaté ;\n` +
        `2. la course est courue, les rapports officiels du PMU tombent ;\n` +
        `3. le plan est confronté à ces rapports, sans retouche.\n\n` +
        `Un pronostic reconstruit après l'arrivée ne compte pas, et il est exclu par ` +
        `construction : le comparateur vérifie que l'enregistrement précède l'heure de la ` +
        `course` +
        (journeesPubliees ? `. ${nb(journeesPubliees)} journées ont été publiées ainsi` : "") +
        `, gagnantes comme perdantes.\n\n` +
        `Le ROI réel y est affiché aussi, y compris quand il est négatif. C'est le prix de ` +
        `la seule chose qui compte : pouvoir être vérifié.\n\n` +
        `${SITE}/track-record` + pied,
    },
    {
      tuile: "0-0",
      image: `${SITE}/visuels/mosaique-site/0-0`,
      legende:
        `Le programme du jour, passé au calcul. Pas au feeling.\n\n` +
        `BlackTurf reprend chaque course du programme PMU et en calcule, avant le départ, ` +
        `une probabilité pour chaque partant` +
        (coursesEnBase && partantsAnalyses
          ? ` — ${nb(coursesEnBase)} courses et ${nb(partantsAnalyses)} partants en base à ce jour`
          : "") +
        `.\n\n` +
        `COMMENT ÇA MARCHE, EN QUATRE TEMPS :\n\n` +
        `1. Le programme est récupéré dès sa publication, avec les partants, les ` +
        `partenaires, les conditions de course et l'état du terrain.\n` +
        `2. Chaque cheval est décrit par 80 critères : forme, vitesse, ELO, jockey, ` +
        `entraîneur, distance, corde, terrain, style de course, marché.\n` +
        `3. Le modèle en tire une probabilité, donc une cote juste — celle que le cheval ` +
        `devrait avoir. Comparée à la cote réelle, elle dit où le marché se trompe.\n` +
        `4. Après l'arrivée, tout est réglé aux rapports officiels et publié.\n\n` +
        `Le programme, les cotes comparées et les rapports sont en accès libre. Les ` +
        `prédictions et le plan de mise commencent à 12 €/mois, avec 7 jours offerts.\n\n` +
        `Faites défiler le profil : les six publications forment une seule image.\n` +
        `${SITE}` + pied,
    },
  ];

  return Response.json(
    { serie: "site", ordre: "publication a l'envers : bas-droite d'abord, haut-gauche en dernier", tuiles },
    { headers: { "Cache-Control": "public, max-age=3600" } },
  );
}
