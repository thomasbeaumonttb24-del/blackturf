import Link from "next/link";
import {
  Barres,
  Chapo,
  Chiffres,
  Comparatif,
  Encadre,
  H2,
  Methode,
  Sommaire,
  Suite,
} from "@/components/blog/kit";

/**
 * L'article portait déjà la mesure maison du facteur Gagnant/Placé (×2,7 contre une
 * difficulté ×3). Repris le 2026-09-22 avec le kit de mise en page et une seconde série
 * de mesures : la FRÉQUENCE à laquelle les chevaux les plus joués remplissent la
 * condition, qui manquait pour décider quoi que ce soit.
 *
 * Attention à la tentation de multiplier fréquence par rapport médian pour en tirer un
 * rendement : le rapport dépend de la combinaison sortie, et celle des deux favoris est
 * la plus jouée donc la moins payée. L'encadré le dit au lecteur.
 */
export const meta = {
  slug: "couple-gagnant-ou-place",
  title: "Couplé gagnant ou couplé placé : lequel choisir ?",
  description:
    "Mesuré sur 16 827 courses : le gagnant paie 2,7 fois le placé alors qu'il est 3 fois plus dur. Les deux favoris y arrivent 13,9 % du temps.",
  date: "2026-06-23",
  updated: "2026-09-22",
  tags: ["Couplé", "PMU", "Bases"],
  readingMinutes: 8,
};

const CP = {
  n: "16 827",
  partants: "12,0",
  cgMed: "20,00 €",
  cgQ1: "9,70 €",
  cgQ3: "45,30 €",
  cpMed: "7,30 €",
  cpQ1: "4,10 €",
  cpQ3: "14,20 €",
  facteur: "2,7",
  fav2Gagnant: 13.9,
  fav2Place: 28.0,
  top3Place: 52.2,
  top4Place: 69.8,
};

export default function Body() {
  return (
    <>
      <Chapo>
        Le Couplé se joue sur deux chevaux, sous deux formes qui n&apos;ont rien à voir. Le Gagnant
        exige les deux premiers, le Placé se contente des places payées — trois fois plus facile. Et
        le rapport, lui, n&apos;est que 2,7 fois plus élevé : l&apos;écart penche légèrement du côté
        du Placé, contre sa réputation de pari au rabais.
      </Chapo>

      <Chiffres
        items={[
          { valeur: CP.cgMed, libelle: "Couplé Gagnant médian", detail: "pour 1 € joué" },
          { valeur: CP.cpMed, libelle: "Couplé Placé médian", detail: "pour 1 € joué" },
          { valeur: `×${CP.facteur}`, libelle: "facteur Gagnant / Placé", detail: "pour une difficulté ×3" },
          { valeur: `${String(CP.fav2Place).replace(".", ",")} %`, libelle: "les deux favoris tous deux placés", detail: "contre 13,9 % en gagnant" },
        ]}
        source={`Mesuré le 22 septembre 2026 sur ${CP.n} courses d'au moins huit partants, terminées sur les douze derniers mois.`}
      />

      <Sommaire
        items={[
          { id: "deux-formes", label: "Deux formes, deux conditions de gain" },
          { id: "combien", label: "Combien le Gagnant paie-t-il de plus ?" },
          { id: "difficulte", label: "Or il est trois fois plus difficile" },
          { id: "frequences", label: "À quelle fréquence le ticket passe" },
          { id: "choisir", label: "Lequel choisir, selon la course" },
          { id: "places", label: "Rappel sur les places payées" },
        ]}
      />

      <H2 id="deux-formes">Deux formes, deux conditions de gain</H2>

      <Comparatif
        titre="Couplé Gagnant et Couplé Placé, face à face"
        colonnes={["Couplé Gagnant", "Couplé Placé"]}
        lignes={[
          { critere: "Condition", a: "vos deux chevaux finissent 1er et 2e, ordre indifférent", b: "vos deux chevaux figurent dans les places payées" },
          { critere: "Places concernées", a: "les 2 premières", b: "les 3 premières dès 8 partants (2 en dessous)" },
          { critere: "Rapport médian", a: `${CP.cgMed} pour 1 €`, b: `${CP.cpMed} pour 1 €` },
          { critere: "Moitié des courses entre", a: `${CP.cgQ1} et ${CP.cgQ3}`, b: `${CP.cpQ1} et ${CP.cpQ3}` },
          { critere: "Avec les deux favoris", a: `passe ${String(CP.fav2Gagnant).replace(".", ",")} % du temps`, b: `passe ${String(CP.fav2Place).replace(".", ",")} % du temps` },
          { critere: "Pour qui", a: "conviction forte sur les deux meilleurs", b: "conviction sur la qualité, pas sur le classement" },
        ]}
      />

      <H2 id="combien">Combien le Gagnant paie-t-il de plus ?</H2>
      <p>
        Sur les <strong>{CP.n} courses</strong> d&apos;au moins huit partants des douze derniers
        mois, le Couplé Gagnant paie <strong>{CP.cgMed}</strong> en médiane contre{" "}
        <strong>{CP.cpMed}</strong> pour le Placé — un facteur de <strong>×{CP.facteur}</strong>. Ce
        facteur est stable : il ne bouge pas d&apos;un pouce selon la taille du champ.
      </p>
      <p>
        La dispersion, elle, est forte des deux côtés : la moitié des Couplés Gagnants tombe entre{" "}
        {CP.cgQ1} et {CP.cgQ3}. Un Couplé « moyen » n&apos;existe donc pas plus ici
        qu&apos;ailleurs — ce sont les quelques gros rapports qui font le résultat d&apos;une saison.
      </p>

      <H2 id="difficulte">Or il est trois fois plus difficile</H2>
      <p>
        Deux chevaux donnés ont exactement <strong>trois fois plus de chances</strong> de figurer
        tous les deux dans le trio de tête que dans le duo de tête. C&apos;est de la combinatoire
        pure : un trio contient trois paires (A-B, A-C, B-C), un duo n&apos;en contient qu&apos;une.
      </p>

      <Encadre titre="Le déséquilibre, et ce qu'il vaut" ton="cle">
        <p>
          Le Gagnant est trois fois plus dur et paie 2,7 fois plus. Le supplément{" "}
          <strong>ne couvre donc pas tout à fait le surcroît de difficulté</strong>, et l&apos;écart
          — de l&apos;ordre de 10 % — penche du côté du Placé.
        </p>
        <p>
          Deux précautions avant d&apos;en faire une règle : ce sont des médianes, pas des
          espérances de gain ; et 10 % reste petit devant le prélèvement du PMU, identique sur les
          deux formules. Aucune des deux n&apos;est une martingale. Mais le Placé ne mérite pas sa
          réputation de pari au rabais.
        </p>
      </Encadre>

      <H2 id="frequences">À quelle fréquence le ticket passe</H2>
      <p>
        Le rapport ne dit que la moitié de l&apos;histoire. Voici l&apos;autre : à quelle fréquence
        la condition est remplie, selon les chevaux retenus.
      </p>

      <Barres
        titre="Part des courses où le ticket est gagnant"
        legende="Sélections construites sur les cotes au départ. Les deux dernières lignes supposent qu'on joue toutes les paires de la sélection — trois et six combinaisons."
        barres={[
          { label: "Les deux favoris, en Couplé Gagnant", valeur: CP.fav2Gagnant },
          { label: "Les deux favoris, en Couplé Placé", valeur: CP.fav2Place, accent: true },
          { label: "Deux des 3 premières cotes, en Placé", valeur: CP.top3Place },
          { label: "Deux des 4 premières cotes, en Placé", valeur: CP.top4Place },
        ]}
        max={80}
        source={`${CP.n} courses d'au moins huit partants, arrivées officielles PMU, non-partants exclus.`}
      />

      <p>
        Deux enseignements. Le premier : même la sélection la plus évidente — les deux premières
        cotes — ne remplit la condition du Gagnant qu&apos;{" "}
        <strong>une fois sur sept</strong>. Le Couplé Gagnant est un pari difficile, y compris quand
        on ne prend aucun risque. Le second : en Placé, couvrir les quatre premières cotes fait
        passer le ticket dans <strong>{String(CP.top4Place).replace(".", ",")} %</strong> des
        courses — au prix de six combinaisons.
      </p>

      <Encadre titre="Ne multipliez pas ces deux chiffres" ton="garde">
        <p>
          Il est tentant de croiser la fréquence et le rapport médian pour en tirer un rendement.
          C&apos;est faux : le rapport dépend de la combinaison qui sort, et celle des deux favoris
          est la plus jouée de toutes, donc la moins bien payée. Les fréquences ci-dessus disent la
          difficulté ; les rapports médians disent ce que paie une course quelconque. Croiser les
          deux reviendrait à payer le trio des favoris au prix d&apos;un trio de surprise — la même
          erreur que corrige{" "}
          <Link href="/blog/comprendre-les-cotes">l&apos;article sur les cotes</Link>.
        </p>
      </Encadre>

      <H2 id="choisir">Lequel choisir, selon la course</H2>
      <ul>
        <li>
          <strong>Course ouverte, gros peloton :</strong> le Placé sécurise, et l&apos;incertitude
          maintient le rapport à un niveau correct. C&apos;est le cas le plus fréquent.
        </li>
        <li>
          <strong>Deux chevaux nettement au-dessus du lot :</strong> le Gagnant exploite cette
          conviction — et lui seul la paie. Encore faut-il que la conviction vienne d&apos;une
          analyse, pas de la seule lecture des cotes.
        </li>
        <li>
          <strong>Un favori et un outsider défendable :</strong> le Placé est presque toujours le
          meilleur compromis. L&apos;outsider accroche plus souvent une place qu&apos;une deuxième
          place, et le rapport grimpe quand même.
        </li>
        <li>
          <strong>Moins de huit partants :</strong> le Placé n&apos;est généralement pas proposé, et
          quand il l&apos;est, il ne couvre que deux places — ce qui le rapproche du Gagnant sans en
          avoir le rapport.
        </li>
      </ul>

      <H2 id="places">Rappel sur les places payées</H2>
      <p>
        De 4 à 7 partants, deux places sont payées ; à partir de 8, trois places. Cette règle
        conditionne tout le Couplé Placé, et elle change la valeur de votre ticket d&apos;une course
        à l&apos;autre — un même pari n&apos;a pas le même sens à sept ou à huit partants. Le détail
        de chaque formule est dans notre{" "}
        <Link href="/guides/types-de-paris-pmu">guide des types de paris PMU</Link>.
      </p>
      <p>
        Le raisonnement vaut d&apos;ailleurs pour les autres paris à condition souple : le{" "}
        <Link href="/blog/comprendre-le-2sur4">2sur4</Link> pousse la même logique encore plus loin,
        avec quatre places ouvertes.
      </p>

      <Suite href="/programme" cta="Voir le programme">
        Pour chaque course du jour : la probabilité calculée de chaque cheval, la cote du marché en
        face, et l&apos;écart entre les deux — de quoi choisir la formule en connaissance de cause.
      </Suite>

      <p>
        Comme toujours, cherchez la <Link href="/guides/pari-de-valeur">valeur</Link> avant le
        statut : un favori bien coté vaut mieux qu&apos;un outsider mal coté, et réciproquement.
      </p>

      <Methode>
        <p>
          Mesures du 22 septembre 2026 sur les {CP.n} courses d&apos;au moins huit partants
          terminées entre septembre 2025 et septembre 2026, dont l&apos;arrivée et les deux rapports
          Couplé sont publiés. Cotes PMU au départ, non-partants exclus.
        </p>
        <p>
          Les rapports sont des médianes de course, pas des espérances de gain : ils décrivent ce
          que paie une course prise au hasard, pas ce que rapporterait une stratégie. Les fréquences
          portent uniquement sur l&apos;arrivée — un ticket est compté gagnant dès que la condition
          est remplie, quel qu&apos;ait été son prix.
        </p>
      </Methode>
    </>
  );
}
