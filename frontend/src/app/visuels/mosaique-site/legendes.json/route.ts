import { MENTION_LEGALE } from "@/lib/visuels";

export const revalidate = 3600;

const SITE = "https://blackturf.fr";
const API = (process.env.NEXT_PUBLIC_API_URL || "https://api.blackturf.fr") + "/api/v1";

const nb = (n: number) => n.toLocaleString("fr-FR").replace(/[  ]/g, " ");
const pct = (n: number) => `${n.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} %`;

/**
 * Les six tuiles de la mosaïque de présentation, DANS LEUR ORDRE DE PUBLICATION.
 *
 * La grille d'un profil Instagram se remplit du plus récent en haut à gauche : pour que
 * la mosaïque se reconstitue, il faut publier À L'ENVERS — bas-droite en premier,
 * haut-gauche en dernier.
 *
 * ══════════════════════ COMMENT CES LÉGENDES SONT ÉCRITES ═══════════════════════════
 *
 * 1. LA PREMIÈRE LIGNE FAIT TOUT. Instagram tronque vers 125 caractères et n'affiche
 *    que « … plus ». Cette ligne porte donc l'accroche entière et se suffit à elle-même ;
 *    aucune ne commence par « BlackTurf est… ».
 *
 * 2. LE TEXTE EST INDEXÉ, PAS SEULEMENT LES HASHTAGS. La recherche Instagram lit le
 *    contenu des légendes : les expressions réellement tapées par les parieurs —
 *    « pronostic PMU », « quinté du jour », « courses hippiques », « trot attelé » —
 *    doivent apparaître dans les phrases, pas seulement en mots-clés à la fin.
 *
 * 3. LES HASHTAGS CHANGENT À CHAQUE PUBLICATION. Six posts d'affilée portant la même
 *    liste est exactement le motif qu'un système de classement lit comme automatisé.
 *    Chaque tuile mélange donc quelques mots-clés à forte portée et quelques-uns à
 *    forte intention, qui ramènent moins de monde mais des gens concernés.
 *
 * 4. UNE ACTION PEU COÛTEUSE EST DEMANDÉE. Enregistrer et partager pèsent davantage
 *    qu'un « j'aime » ; une vraie question ouverte fait des commentaires. Chaque
 *    légende en demande UNE, jamais trois.
 *
 * 5. AUCUN EMOJI DÉCORATIF. Le produit vend de la rigueur ; une légende constellée
 *    d'emojis ressemble à tous les comptes de pronostics qu'on veut justement ne pas
 *    imiter. La ponctuation structure, les emojis non.
 *
 * ══════════════════════ CE QUI NE SE NÉGOCIE PAS ════════════════════════════════════
 *
 * Aucune promesse de gain, aucun taux présenté comme une rentabilité, mention de jeu
 * responsable sur les six. Le ROI mesuré est négatif : ce qui se vend est la méthode et
 * la vérifiabilité. Plafond dur d'Instagram : 2 200 caractères, pied compris.
 */

/** Mention légale + mots-clés propres à la tuile. */
const pied = (tags: string[]) => `\n\n${MENTION_LEGALE}\n\n${tags.join(" ")}`;

export async function GET() {
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
        `Un ticket perdu coûte plus cher qu'un mois d'abonnement.\n\n` +
        `Faites le calcul une fois : combien part chaque semaine en tickets qui ne ` +
        `passent pas ? Le pronostic PMU calculé coûte moins que deux d'entre eux.\n\n` +
        `DÉCOUVERTE — 0 €, pour toujours\n` +
        `Programme PMU complet, cotes comparées entre opérateurs, arrivées et rapports ` +
        `officiels. Et un plan de mise par jour.\n\n` +
        `STANDARD — 12 €/mois\n` +
        `Cinq plans de mise par jour, suivi de votre capital réglé aux vrais rapports, ` +
        `alertes sur les courses que vous suivez.\n\n` +
        `EXPERT — 19 €/mois\n` +
        `Plans illimités et paris de valeur en temps réel : les chevaux dont la cote paie ` +
        `plus que leur risque réel, signalés dès que l'écart apparaît.\n\n` +
        `Sept jours d'essai gratuit, annulation en deux clics. Vous jouez où vous voulez, ` +
        `au comptoir ou en ligne : aucune commission n'est prise sur vos gains.\n\n` +
        `Vous misez combien par semaine, vous ? Dites-le en commentaire.\n` +
        `${SITE}` +
        pied([
          "#pmu",
          "#turf",
          "#parishippiques",
          "#pronosticpmu",
          "#courseshippiques",
          "#turfiste",
          "#quinte",
          "#blackturf",
        ]),
    },
    {
      tuile: "1-1",
      image: `${SITE}/visuels/mosaique-site/1-1`,
      legende:
        `Vous entrez 20 €. Le plan de jeu s'écrit tout seul.\n\n` +
        `Voilà l'écran, tel quel. Vous choisissez un profil — prudent, modéré, risqué — ` +
        `vous donnez votre budget, et la mise se répartit :\n\n` +
        `SÉCURITÉ · 40 % du budget · 8,00 €\n` +
        `Couplé Placé N°2 + N°4 · probabilité estimée 41 %\n\n` +
        `RENDEMENT · 40 % du budget · 8,00 €\n` +
        `Simple Gagnant N°4 · probabilité estimée 17 %\n\n` +
        `GROS LOT · 20 % du budget · 4,00 €\n` +
        `Couplé Gagnant N°2 + N°4 · probabilité estimée 9 %\n\n` +
        `C'est ce qu'aucun ticket type ne fait : un pronostic recopié à l'identique pour ` +
        `tout le monde ignore votre budget. À dix euros comme à cent, la répartition se ` +
        `recalcule — elle ne se contente pas de multiplier les mises.\n\n` +
        `Après l'arrivée, chaque pari est réglé au rapport PMU officiel et votre suivi se ` +
        `met à jour. Les paris perdus sont affichés aussi, et notre rendement réellement ` +
        `mesuré est publié, négatif compris.\n\n` +
        `Plan d'exemple : rendement et gains sont estimés, jamais garantis.\n\n` +
        `Enregistrez ce post pour retrouver la répartition avant votre prochaine course.\n` +
        `${SITE}` +
        pied([
          "#pmu",
          "#pronosticpmu",
          "#parishippiques",
          "#couplegagnant",
          "#simplegagnant",
          "#turf",
          "#gestiondebankroll",
          "#blackturf",
        ]),
    },
    {
      tuile: "1-0",
      image: `${SITE}/visuels/mosaique-site/1-0`,
      legende:
        `Le dépouillement du programme, fait pendant que vous dormez.\n\n` +
        `Trois gestes, et c'est joué :\n\n` +
        `01 — OUVREZ LA COURSE. Elle est déjà traitée : partants classés, probabilité de ` +
        `chacun, cote juste, niveau de confiance de la course.\n` +
        `02 — DONNEZ VOTRE BUDGET. Dix euros ou cent, la mise se répartit selon votre ` +
        `tolérance au risque.\n` +
        `03 — JOUEZ OÙ VOUS VOULEZ. Au comptoir ou en ligne, chez l'opérateur de votre ` +
        `choix. Aucune commission n'est prise sur vos gains.\n\n` +
        `Ce que vous obtenez, chaque jour : tout le programme analysé, les cotes du PMU et ` +
        `des principaux opérateurs côte à côte, les paris de valeur signalés, votre capital ` +
        `suivi sans triche — les paris perdus sont affichés aussi — et une alerte dès qu'un ` +
        `signal sort sur une course que vous suivez.\n\n` +
        `Toutes les disciplines : plat, trot attelé, monté, obstacle.\n\n` +
        `Vous y passez combien de temps chaque jour, vous, sur le programme ?\n` +
        `7 jours offerts sur ${SITE}` +
        pied([
          "#courseshippiques",
          "#pmu",
          "#trotattele",
          "#galop",
          "#pronosticturf",
          "#turfiste",
          "#hippisme",
          "#blackturf",
        ]),
    },
    {
      tuile: "0-2",
      image: `${SITE}/visuels/mosaique-site/0-2`,
      legende:
        `80+ critères par cheval — dont ceux auxquels personne ne pense.\n\n` +
        `Tout le monde regarde la musique et la cote. Voilà ce que l'algorithme regarde en ` +
        `plus, sur chaque partant de chaque course du programme PMU :\n\n` +
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
        `opérateurs, structure du pool, consensus de la presse.\n\n` +
        `Et le modèle est recalibré chaque nuit sur les arrivées réelles : ce qui s'est ` +
        `trompé hier corrige le pronostic d'aujourd'hui.\n\n` +
        `Lequel de ces critères vous surprend le plus ? Répondez en commentaire.\n` +
        `${SITE}` +
        pied([
          "#pronosticpmu",
          "#turf",
          "#trotattele",
          "#deferrage",
          "#courseshippiques",
          "#datascience",
          "#intelligenceartificielle",
          "#blackturf",
        ]),
    },
    {
      tuile: "0-1",
      image: `${SITE}/visuels/mosaique-site/0-1`,
      legende:
        (precisionTop3 !== null && hasardTop3 !== null
          ? `${pct(precisionTop3)} des courses, le gagnant est dans notre top 3. Le hasard fait ${pct(hasardTop3)}.\n\n`
          : `Le gagnant est dans notre top 3 deux fois plus souvent que le hasard.\n\n`) +
        `Un taux tout seul ne prouve rien. Sur des champs de onze partants en moyenne, la ` +
        `seule question qui vaille est : combien ferait un tirage au sort sur exactement ` +
        `les mêmes courses ? C'est pour ça que les deux chiffres sont affichés ensemble — ` +
        `et c'est le chiffre que les sites de pronostics ne publient jamais.\n\n` +
        (favoriPlace !== null && favoriGagnant !== null
          ? `Notre favori termine dans les trois ${pct(favoriPlace)} du temps et gagne ${pct(favoriGagnant)} du temps.\n\n`
          : "") +
        (coursesMesurees
          ? `Mesuré sur ${nb(coursesMesurees)} courses réglées aux rapports officiels du PMU, `
          : `Mesuré sur des courses réglées aux rapports officiels du PMU, `) +
        `pronostic enregistré et horodaté AVANT le départ. Aucune reconstruction après ` +
        `l'arrivée : le comparateur vérifie que l'enregistrement précède l'heure de la ` +
        `course.\n\n` +
        `ET CE QUE ÇA NE DIT PAS. De la précision n'est pas de la rentabilité. Le PMU ` +
        `prélève environ 20 % des enjeux, et notre propre rendement mesuré reste négatif. ` +
        `Il est publié quand même, à côté de ces taux.\n\n` +
        `Enregistrez ce post et revenez vérifier dans un mois : les chiffres sont publics ` +
        `et ils bougent.\n` +
        `${SITE}/track-record` +
        pied([
          "#pronosticpmu",
          "#pmu",
          "#quinte",
          "#courseshippiques",
          "#parishippiques",
          "#transparence",
          "#turf",
          "#blackturf",
        ]),
    },
    {
      tuile: "0-0",
      image: `${SITE}/visuels/mosaique-site/0-0`,
      legende:
        `Pendant qu'ils jouent au feeling, vous jouez aux chiffres.\n\n` +
        `BlackTurf reprend chaque course du programme PMU et calcule, avant le départ, une ` +
        `probabilité pour chaque partant` +
        (coursesEnBase && partantsAnalyses
          ? ` — ${nb(coursesEnBase)} courses et ${nb(partantsAnalyses)} partants en base à ce jour`
          : "") +
        `.\n\n` +
        `EN QUATRE TEMPS :\n` +
        `1. Le programme est récupéré dès sa publication, avec les partants, les ` +
        `partenaires, les conditions et l'état du terrain.\n` +
        `2. Chaque cheval est décrit par plus de 80 critères : forme, vitesse, ELO, jockey, ` +
        `entraîneur, distance, corde, terrain, scénario de course, marché.\n` +
        `3. Le modèle en tire une probabilité, donc une cote juste — celle que le cheval ` +
        `devrait avoir. Comparée à la cote réelle, elle dit où le marché se trompe.\n` +
        `4. Après l'arrivée, tout est réglé aux rapports officiels et publié, gagnant ou ` +
        `perdant.\n\n` +
        `Programme, cotes comparées et rapports officiels en accès libre. Prédictions et ` +
        `plan de mise à partir de 12 €/mois, avec 7 jours offerts.\n\n` +
        `Faites défiler le profil : les six publications ne forment qu'une seule image.\n` +
        `Abonnez-vous au compte, le bilan tombe chaque semaine.\n` +
        `${SITE}` +
        pied([
          "#pmu",
          "#pronosticpmu",
          "#quintedujour",
          "#courseshippiques",
          "#parishippiques",
          "#turf",
          "#hippisme",
          "#blackturf",
        ]),
    },
  ];

  return Response.json(
    { serie: "site", ordre: "publication a l'envers : bas-droite d'abord, haut-gauche en dernier", tuiles },
    { headers: { "Cache-Control": "public, max-age=3600" } },
  );
}
