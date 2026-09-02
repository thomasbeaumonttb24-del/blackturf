import { MENTION_LEGALE, HASHTAGS } from "@/lib/visuels";

export const revalidate = 3600;

const SITE = "https://blackturf.fr";
const API = (process.env.NEXT_PUBLIC_API_URL || "https://api.blackturf.fr") + "/api/v1";

const nb = (n: number) => n.toLocaleString("fr-FR").replace(/[  ]/g, " ");
const pct = (n: number) => `${n.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} %`;

/**
 * Les six tuiles de la mosaïque de présentation, DANS LEUR ORDRE DE PUBLICATION.
 *
 * La grille d'un profil Instagram se remplit du plus récent en haut à gauche, puis vers
 * la droite. Pour que la mosaïque se reconstitue, il faut publier À L'ENVERS : la tuile
 * en bas à droite en premier, celle en haut à gauche en dernier.
 *
 * ─────────────────────────── CE QUE PORTE UNE LÉGENDE ──────────────────────────────────
 *
 * Le visuel affirme ; la légende démontre. Elle détaille donc ce que le visuel avance —
 * les familles de critères, ce que valent les taux, le contenu exact de chaque formule.
 * C'est ce qui sépare un compte de pronostics d'un compte de méthode : le premier
 * annonce, le second montre son travail.
 *
 * Contraintes : Instagram coupe vers 125 caractères, donc la première ligne porte
 * l'accroche ; le plafond dur est de 2 200 caractères, pied légal et mots-clés compris.
 *
 * ─────────────────────────── LA LIGNE À NE PAS FRANCHIR ────────────────────────────────
 *
 * Les taux affichés sont des taux de PRÉCISION, pas de rentabilité. Le ROI mesuré est
 * négatif, et la légende de la tuile des taux le dit — c'est ce qui empêche « 60,2 % »
 * d'être lu comme une promesse d'argent, et c'est aussi le seul argument qu'un
 * concurrent ne peut pas copier sans publier ses propres chiffres.
 */
export async function GET() {
  const pied = `\n\n${MENTION_LEGALE}\n\n${HASHTAGS}`;

  let coursesEnBase = 0;
  let partantsAnalyses = 0;
  let precisionTop3: number | null = null;
  let hasardTop3: number | null = null;
  let favoriPlace: number | null = null;
  let favoriGagnant: number | null = null;
  let coursesMesurees = 0;
  try {
    const res = await fetch(`${API}/stats/chiffres-site`, { next: { revalidate: 3600 } });
    if (res.ok) {
      const d = await res.json();
      coursesEnBase = Number(d.courses_en_base ?? 0);
      partantsAnalyses = Number(d.partants_analyses ?? 0);
      precisionTop3 = d.precision_top3 ?? null;
      hasardTop3 = d.hasard_top3 ?? null;
      favoriPlace = d.favori_place ?? null;
      favoriGagnant = d.favori_gagnant ?? null;
      coursesMesurees = Number(d.courses_mesurees ?? 0);
    }
  } catch {
    // Les légendes restent publiables sans les chiffres ; elles n'en citeront aucun.
  }

  const tuiles = [
    {
      tuile: "1-2",
      image: `${SITE}/visuels/mosaique-site/1-2`,
      legende:
        `Moins cher qu'un ticket perdu.\n\n` +
        `DÉCOUVERTE — 0 €, pour toujours\n` +
        `Le programme PMU complet, les cotes comparées entre opérateurs, les arrivées et ` +
        `les rapports officiels. Et un plan de mise par jour.\n\n` +
        `STANDARD — 12 €/mois\n` +
        `Cinq plans de mise par jour, le suivi de votre capital réglé aux vrais rapports, ` +
        `et les alertes sur les courses que vous suivez.\n\n` +
        `EXPERT — 19 €/mois\n` +
        `Plans illimités, et les paris de valeur en temps réel : les chevaux dont la cote ` +
        `paie plus que leur risque réel, signalés dès que l'écart apparaît — les cotes ` +
        `bougent jusqu'au départ.\n\n` +
        `Sept jours d'essai gratuit. Annulation en deux clics. Vous jouez où vous voulez, ` +
        `au comptoir ou en ligne : aucune commission n'est prise sur vos gains.\n\n` +
        `${SITE}` + pied,
    },
    {
      tuile: "1-1",
      image: `${SITE}/visuels/mosaique-site/1-1`,
      legende:
        `Vous entrez 20 €. Le plan de jeu s'écrit tout seul.\n\n` +
        `C'est ce que fait BlackTurf que personne d'autre ne fait : un ticket type se ` +
        `recopie à l'identique pour tout le monde, une répartition non. Elle part de VOTRE ` +
        `budget et du profil que vous choisissez.\n\n` +
        `SÉCURITÉ — 40 % du budget, 8 €\n` +
        `Couplé Placé 2 + 4, probabilité estimée 41 %\n\n` +
        `RENDEMENT — 40 % du budget, 8 €\n` +
        `Simple Gagnant 4, probabilité estimée 17 %\n\n` +
        `GROS LOT — 20 % du budget, 4 €\n` +
        `Couplé Gagnant 2 + 4, probabilité estimée 9 %\n\n` +
        `Trois profils changent l'équilibre : prudent vise le petit rapport souvent, risqué ` +
        `le gros rapport rarement. Et à dix euros comme à cent, la répartition se recalcule ` +
        `— elle ne se contente pas de multiplier les mises.\n\n` +
        `Après l'arrivée, chaque pari est réglé au rapport PMU officiel et votre suivi se ` +
        `met à jour. Les paris perdus sont affichés aussi.\n\n` +
        `Plan d'exemple : les probabilités sont estimées, pas garanties.\n${SITE}` + pied,
    },
    {
      tuile: "1-0",
      image: `${SITE}/visuels/mosaique-site/1-0`,
      legende:
        `Tout le travail d'analyse, déjà fait. Trois gestes, et c'est joué.\n\n` +
        `01 — OUVREZ LA COURSE. Elle est déjà traitée : partants classés, probabilité de ` +
        `chacun, cote juste, et le niveau de confiance de la course.\n` +
        `02 — DONNEZ VOTRE BUDGET. Dix euros ou cent : la mise se répartit selon votre ` +
        `tolérance au risque, entre sécurité, rendement et coup.\n` +
        `03 — JOUEZ OÙ VOUS VOULEZ. Au comptoir ou en ligne, chez l'opérateur de votre ` +
        `choix. Aucune commission n'est prise sur vos gains.\n\n` +
        `Et ensuite, ça ne s'arrête pas : chaque pari est réglé au rapport PMU officiel et ` +
        `votre rendement réel se met à jour. Les paris perdus sont affichés aussi — c'est ` +
        `la seule façon qu'un suivi de capital veuille dire quelque chose.\n\n` +
        `Toutes les disciplines : plat, attelé, monté, obstacle.\n\n` +
        `7 jours offerts sur ${SITE}` + pied,
    },
    {
      tuile: "0-2",
      image: `${SITE}/visuels/mosaique-site/0-2`,
      legende:
        `80+ critères par cheval, dont ceux auxquels personne ne pense.\n\n` +
        `01 — LE CHEVAL, AU-DELÀ DE LA MUSIQUE\n` +
        `Contrecoup après un gros effort, surmenage, battu de peu, descente de catégorie, ` +
        `finit fort ou faiblit, indice d'endurance, classement ELO par discipline.\n\n` +
        `02 — LA PISTE ET LE SCÉNARIO\n` +
        `Biais de corde de l'hippodrome, nombre de meneurs, déferrage, œillères, ` +
        `pénétromètre, recul au départ, risque de faute, style de course croisé au terrain.\n\n` +
        `03 — LA LIGNÉE ET LES HOMMES\n` +
        `Réussite du père sur ce terrain, jockey sur ce cheval précis, confrontations ` +
        `directes, entraîneur sur cet hippodrome, kilomètres parcourus.\n\n` +
        `04 — CE QUE DIT LE MARCHÉ\n` +
        `Argent professionnel, coups de cote dans les 30 dernières minutes, écart entre ` +
        `opérateurs, structure du pool, consensus de la presse, qualité de l'opposition.\n\n` +
        `Et le modèle est recalibré chaque nuit sur les arrivées réelles de la journée. Ce ` +
        `qui s'est trompé hier corrige le pronostic d'aujourd'hui.\n\n` +
        `${SITE}` + pied,
    },
    {
      tuile: "0-1",
      image: `${SITE}/visuels/mosaique-site/0-1`,
      legende:
        (precisionTop3 !== null && hasardTop3 !== null
          ? `${pct(precisionTop3)} des courses, le gagnant est dans notre top 3. Le hasard fait ${pct(hasardTop3)}.\n\n`
          : `Le gagnant est dans notre top 3 deux fois plus souvent que le hasard.\n\n`) +
        `Un taux seul ne prouve rien. Sur des champs de onze partants en moyenne, la vraie ` +
        `question est : combien ferait un tirage au sort sur EXACTEMENT les mêmes courses ? ` +
        `C'est pour ça que les deux chiffres sont affichés ensemble.\n\n` +
        (favoriPlace !== null && favoriGagnant !== null
          ? `Notre favori termine dans les trois ${pct(favoriPlace)} du temps, et gagne ${pct(favoriGagnant)} du temps.\n\n`
          : "") +
        (coursesMesurees
          ? `Mesuré sur ${nb(coursesMesurees)} courses réglées aux rapports officiels du PMU, `
          : `Mesuré sur des courses réglées aux rapports officiels du PMU, `) +
        `avec le pronostic enregistré AVANT le départ. Aucune reconstruction après ` +
        `l'arrivée.\n\n` +
        `ET CE QUE ÇA NE DIT PAS : de la précision n'est pas de la rentabilité. Le PMU ` +
        `prélève environ 20 % des enjeux, et notre propre rendement mesuré reste négatif. ` +
        `Il est publié quand même, à côté de ces taux.\n\n` +
        `Tout est vérifiable : ${SITE}/track-record` + pied,
    },
    {
      tuile: "0-0",
      image: `${SITE}/visuels/mosaique-site/0-0`,
      legende:
        `Pendant qu'ils jouent au feeling, vous jouez aux chiffres.\n\n` +
        `BlackTurf reprend chaque course du programme PMU et en calcule, avant le départ, ` +
        `une probabilité pour chaque partant` +
        (coursesEnBase && partantsAnalyses
          ? ` — ${nb(coursesEnBase)} courses et ${nb(partantsAnalyses)} partants en base à ce jour`
          : "") +
        `.\n\n` +
        `COMMENT ÇA MARCHE, EN QUATRE TEMPS :\n\n` +
        `1. Le programme est récupéré dès sa publication, avec les partants, les ` +
        `partenaires, les conditions de course et l'état du terrain.\n` +
        `2. Chaque cheval est décrit par plus de 80 critères : forme, vitesse, ELO, jockey, ` +
        `entraîneur, distance, corde, terrain, scénario de course, marché.\n` +
        `3. Le modèle en tire une probabilité, donc une cote juste — celle que le cheval ` +
        `devrait avoir. Comparée à la cote réelle, elle dit où le marché se trompe.\n` +
        `4. Après l'arrivée, tout est réglé aux rapports officiels et publié, gagnant ou ` +
        `perdant.\n\n` +
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
