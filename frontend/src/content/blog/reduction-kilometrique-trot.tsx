import Link from "next/link";
import {
  Barres,
  Chapo,
  Chiffres,
  Encadre,
  H2,
  Methode,
  Sommaire,
  Suite,
} from "@/components/blog/kit";

/**
 * Dernier article vraiment mince du blog (299 mots). Il expliquait correctement ce
 * qu'est une réduction kilométrique sans jamais donner d'ordre de grandeur — donc sans
 * permettre au lecteur de juger une réduc qu'il a sous les yeux.
 *
 * Chiffres du 2026-09-22 : `resultats.classement[].reduction_km`, publiée par le PMU
 * ligne par ligne. Douze mois glissants, trot attelé et monté.
 */
export const meta = {
  slug: "reduction-kilometrique-trot",
  title: "Réduction kilométrique : lire la vitesse d'un trotteur",
  description:
    "Ce qu'est une bonne réduc, chiffres à l'appui : 75,0 s/km pour un vainqueur d'attelé, mais 73,5 à Vincennes et 75,4 au-delà de 3 000 mètres.",
  date: "2026-06-23",
  updated: "2026-09-22",
  tags: ["Trot", "Réduction kilométrique", "Data"],
  readingMinutes: 8,
};

const RK = {
  vainqueursAttele: "7 493",
  medAttele: "75,0",
  d1Attele: "72,6",
  med2a5Attele: "75,4",
  medMonte: "74,4",
  distances: [
    { tranche: "Moins de 2 000 m", n: 345, rk: 74.0 },
    { tranche: "2 000 à 2 500 m", n: 2605, rk: 74.7 },
    { tranche: "2 500 à 3 000 m", n: 4230, rk: 75.1 },
    { tranche: "3 000 m et plus", n: 313, rk: 75.4 },
  ],
  pistes: [
    { nom: "Vincennes", n: 589, rk: 73.5 },
    { nom: "Enghien-Soisy", n: 148, rk: 74.2 },
    { nom: "Le Croisé-Laroche", n: 124, rk: 74.4 },
    { nom: "Cabourg", n: 148, rk: 74.5 },
  ],
};

const s = (n: number) => String(n).replace(".", ",");

export default function Body() {
  return (
    <>
      <Chapo>
        La réduction kilométrique est le seul chiffre de vitesse publié au trot — et le plus mal
        utilisé. Une « bonne réduc » n&apos;existe pas dans l&apos;absolu : elle dépend de la
        distance, de la piste et du type de départ. Voici les ordres de grandeur réels, mesurés sur
        un an de courses, pour savoir ce que vaut celle que vous avez sous les yeux.
      </Chapo>

      <Chiffres
        items={[
          { valeur: `${RK.medAttele} s`, libelle: "réduc médiane d'un vainqueur", detail: "au trot attelé, par kilomètre" },
          { valeur: `${RK.d1Attele} s`, libelle: "le dixième le plus rapide", detail: "2,4 s/km sous la médiane" },
          { valeur: "73,5 s", libelle: "à Vincennes, à distance égale", detail: "la piste la plus rapide de France" },
          { valeur: `${RK.vainqueursAttele}`, libelle: "vainqueurs mesurés", detail: "douze derniers mois" },
        ]}
        source="Réductions publiées par le PMU ligne par ligne, relevées le 22 septembre 2026."
      />

      <Sommaire
        items={[
          { id: "definition", label: "Ce que mesure la réduction kilométrique" },
          { id: "ordres", label: "Ce qu'est une bonne réduc, en chiffres" },
          { id: "distance", label: "L'effet distance, mesuré" },
          { id: "piste", label: "L'effet piste : une seconde entre Vincennes et le reste" },
          { id: "erreur", label: "L'erreur classique" },
          { id: "utiliser", label: "L'utiliser intelligemment" },
        ]}
      />

      <H2 id="definition">Ce que mesure la réduction kilométrique</H2>
      <p>
        La réduction kilométrique — la « réduc » — est le <strong>temps moyen mis pour parcourir un
        kilomètre</strong>, exprimé en minutes et secondes : 1&apos;15&quot; signifie 75 secondes au
        kilomètre. Plus elle est basse, plus le cheval a été rapide. Elle ramène tous les temps à une
        unité commune, quelle que soit la distance de la course.
      </p>
      <p>
        C&apos;est sa force et son piège : la ramener à une unité commune ne la rend pas comparable
        pour autant. Un kilomètre couru sur une piste rapide à l&apos;autostart n&apos;a rien à voir
        avec un kilomètre couru à la volte sur une petite piste, et les chiffres qui suivent le
        montrent.
      </p>

      <H2 id="ordres">Ce qu&apos;est une bonne réduc, en chiffres</H2>
      <p>
        Sur les <strong>{RK.vainqueursAttele} vainqueurs</strong> de trot attelé des douze derniers
        mois, la réduction médiane est de <strong>{RK.medAttele} secondes</strong> au kilomètre,
        soit 1&apos;15&quot;. Les 10 % les plus rapides descendent sous <strong>{RK.d1Attele}</strong>,
        c&apos;est-à-dire 1&apos;12&quot;6.
      </p>
      <p>
        Autre repère, plus parlant encore : les chevaux classés de la 2ᵉ à la 5ᵉ place affichent une
        médiane de <strong>{RK.med2a5Attele}</strong>. L&apos;écart entre gagner et finir dans les
        cinq premiers se joue donc sur <strong>quatre dixièmes de seconde par kilomètre</strong>.
        C&apos;est peu, et c&apos;est exactement pourquoi une réduc lue sans son contexte ne
        départage rien : la marge à expliquer est plus petite que l&apos;effet de la piste ou de la
        distance.
      </p>
      <p>
        Au trot monté, la médiane du vainqueur tombe à <strong>{RK.medMonte}</strong> — les courses
        montées se disputent en moyenne sur des distances plus courtes, ce qui suffit à expliquer
        l&apos;écart. Là encore, comparer un chiffre à l&apos;autre sans regarder les conditions
        induit en erreur.
      </p>

      <H2 id="distance">L&apos;effet distance, mesuré</H2>

      <Barres
        titre="Réduction médiane du vainqueur, selon la distance (trot attelé)"
        legende="Plus la course est longue, plus la réduc monte : un cheval ne tient pas la même vitesse sur 1 900 et sur 3 100 mètres."
        barres={RK.distances.map((d) => ({
          label: `${d.tranche} — ${d.n.toLocaleString("fr-FR")} courses`,
          valeur: d.rk,
          affichage: `${s(d.rk)} s/km`,
          accent: d.tranche === "3 000 m et plus",
        }))}
        max={78}
        source="Douze derniers mois, vainqueurs uniquement. L'échelle démarre à zéro : les écarts sont réels mais resserrés."
      />

      <p>
        Un peu plus d&apos;une seconde sépare les courses de moins de 2 000 mètres des courses de
        3 000 et plus. Rapporté à l&apos;écart de quatre dixièmes qui sépare un vainqueur de ses
        poursuivants, c&apos;est considérable : <strong>comparer deux réducs courues sur des
        distances différentes, c&apos;est comparer trois fois le bruit qu&apos;on cherche à
        mesurer</strong>.
      </p>

      <H2 id="piste">L&apos;effet piste : une seconde entre Vincennes et le reste</H2>
      <p>
        Pour isoler la piste, il faut neutraliser la distance. Voici donc les mêmes courses —
        attelé, entre 2 500 et 3 000 mètres — réparties par hippodrome :
      </p>

      <Barres
        titre="Réduction médiane du vainqueur à distance comparable (2 500 à 3 000 m)"
        legende="Mêmes conditions de distance et de discipline : ce qui reste est l'effet de la piste et du niveau des courses qui s'y disputent."
        barres={RK.pistes.map((p) => ({
          label: `${p.nom} — ${p.n} courses`,
          valeur: p.rk,
          affichage: `${s(p.rk)} s/km`,
          accent: p.nom === "Vincennes",
        }))}
        max={78}
        source="Hippodromes ayant accueilli au moins 40 courses dans cette fourchette sur douze mois."
      />

      <p>
        Vincennes sort à <strong>73,5 s/km</strong> contre 74,2 à 74,5 ailleurs : près d&apos;une
        seconde d&apos;écart, à distance et discipline identiques. Deux causes se mélangent et il
        faut le dire — la piste y est réputée rapide, mais les courses qui s&apos;y disputent sont
        aussi les mieux dotées, donc les mieux courues. Le chiffre ne sépare pas les deux effets ; il
        suffit néanmoins à la règle pratique : <strong>une réduc de Vincennes ne se compare pas
        telle quelle à une réduc de province.</strong>
      </p>

      <Encadre titre="Les quatre facteurs qui faussent une réduc" ton="cle">
        <ul>
          <li>
            <strong>Le type de départ</strong> : l&apos;autostart, départ lancé, donne des réducs
            plus rapides que le départ à la volte.
          </li>
          <li>
            <strong>La distance</strong> : plus d&apos;une seconde d&apos;écart entre les courtes et
            les longues, mesuré ci-dessus.
          </li>
          <li>
            <strong>La piste</strong> : taille, corde, état du terrain — jusqu&apos;à une seconde
            entre Vincennes et une piste de province.
          </li>
          <li>
            <strong>Le déroulé</strong> : un cheval resté à l&apos;extérieur a parcouru plus de
            mètres que ne le dit la distance officielle. Sa réduc réelle est meilleure que celle
            qu&apos;on lit.
          </li>
        </ul>
      </Encadre>

      <H2 id="erreur">L&apos;erreur classique</H2>
      <p>
        Elle consiste à aligner la meilleure réduc de chaque partant et à classer. Vu les ordres de
        grandeur ci-dessus, cela revient à classer les chevaux par la piste où ils ont couru et par
        la distance de leur meilleure course — pas par leur vitesse. Une excellente réduc obtenue en
        autostart sur une piste rapide ne vaut pas une réduc médiocre à la volte sur 3 000 mètres,
        et l&apos;écart de contexte dépasse largement l&apos;écart de talent.
      </p>
      <p>
        C&apos;est la même mécanique que pour le déferrage, mesurée dans{" "}
        <Link href="/blog/strategies-paris-trot">nos cinq clés pour parier au trot</Link> : un
        facteur vrai n&apos;est utile que <em>normalisé</em>, et un facteur que tout le monde lit de
        travers finit souvent dans la cote de travers aussi.
      </p>

      <H2 id="utiliser">L&apos;utiliser intelligemment</H2>
      <ul>
        <li>
          comparez toujours <strong>à distance, piste et type de départ comparables</strong> — à
          défaut, ne comparez pas ;
        </li>
        <li>
          regardez l&apos;<strong>écart à la médiane de la course</strong>, pas la valeur absolue :
          une réduc de 76 dans une course où le vainqueur a fait 77 est excellente ;
        </li>
        <li>
          croisez avec la <Link href="/guides/comment-lire-la-musique">musique</Link>, la ferrure et
          le couple driver-entraîneur — la vitesse pure ne dit rien de la régularité d&apos;allure,
          qui coûte 6,1 % des lignes d&apos;arrivée en attelé ;
        </li>
        <li>
          méfiez-vous d&apos;une réduc unique : une seule course ne distingue pas un cheval rapide
          d&apos;une course lente.
        </li>
      </ul>
      <p>
        C&apos;est exactement ce travail de normalisation que fait un modèle entraîné sur
        l&apos;historique : il n&apos;apprend pas « 74 est mieux que 75 », il apprend « 74 sur cette
        piste, à cette distance, pour ce type de départ, vaut tant ». Le détail de la méthode est sur{" "}
        <Link href="/pronostics-ia">la page de l&apos;algorithme</Link>.
      </p>

      <Suite href="/disciplines/trot" cta="Voir le trot du jour">
        Les courses de trot du jour, avec pour chaque partant la probabilité calculée et la cote du
        marché en face.
      </Suite>

      <Methode>
        <p>
          Mesures du 22 septembre 2026 sur les courses de trot terminées des douze derniers mois. La
          réduction kilométrique est celle publiée par le PMU pour chaque cheval classé ; les lignes
          sans réduction publiée sont écartées, pas reconstituées.
        </p>
        <p>
          Les comparaisons par piste portent sur le trot attelé entre 2 500 et 3 000 mètres, et
          seuls les hippodromes totalisant au moins quarante courses dans cette fourchette sont
          retenus. Ces chiffres ne séparent pas l&apos;effet de la piste de celui du niveau des
          courses qui s&apos;y disputent : ils décrivent ce qu&apos;on observe, pas une cause.
        </p>
      </Methode>
    </>
  );
}
