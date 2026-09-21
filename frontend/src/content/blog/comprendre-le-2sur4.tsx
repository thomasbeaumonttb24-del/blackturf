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
 * Article le plus court du blog avant reprise (272 mots), et l'un des plus faciles à
 * chiffrer : le 2sur4 se mesure entièrement sur l'arrivée, sans dépendre des rapports.
 *
 * ⚠ Les rapports 2sur4 de notre collecte ne sont PAS publiables : le détail PMU
 * renvoie la même valeur pour les six combinaisons gagnantes d'une même course, ce qui
 * n'a pas de sens pour un pari mutuel et trahit un artefact de collecte. L'article s'en
 * tient donc aux fréquences, qui viennent de l'arrivée officielle et des cotes au départ.
 * Ne pas ajouter de rapport ici sans avoir d'abord corrigé le scraper.
 */
export const meta = {
  slug: "comprendre-le-2sur4",
  title: "Le 2sur4 : le pari le plus accessible du PMU",
  description:
    "Deux chevaux parmi les quatre premiers : mesuré sur 2 584 courses, les deux favoris y arrivent 36,5 % du temps, contre 8,8 % au hasard.",
  date: "2026-06-23",
  updated: "2026-09-21",
  tags: ["2sur4", "PMU", "Accessible"],
  readingMinutes: 7,
};

const D = {
  courses: "2 584",
  partants: "12,7",
  deuxFavoris: 36.5,
  top4: 80.3,
  top6: 93.3,
  moyTop4: "2,17",
  hasard: 8.8,
};

export default function Body() {
  return (
    <>
      <Chapo>
        Deux chevaux parmi les quatre premiers, dans le désordre : c&apos;est la condition de gain la
        plus souple du PMU. Sur un an de courses, les deux favoris du marché y parviennent{" "}
        <strong>plus d&apos;une fois sur trois</strong> — là où deux chevaux tirés au hasard n&apos;y
        arrivent qu&apos;une fois sur onze.
      </Chapo>

      <Chiffres
        items={[
          { valeur: D.courses, libelle: "courses mesurées", detail: `${D.partants} partants en moyenne` },
          { valeur: `${String(D.deuxFavoris).replace(".", ",")} %`, libelle: "les deux favoris dans les 4 premiers", detail: "la combinaison la plus jouée" },
          { valeur: `${String(D.top4).replace(".", ",")} %`, libelle: "au moins deux des 4 premières cotes", detail: "donc un ticket gagnant existe" },
          { valeur: `${String(D.hasard).replace(".", ",")} %`, libelle: "deux chevaux au hasard", detail: "le plancher à battre" },
        ]}
        source="Courses proposant le 2sur4, terminées entre septembre 2025 et septembre 2026. Arrivées officielles PMU, cotes au départ, non-partants exclus."
      />

      <Sommaire
        items={[
          { id: "principe", label: "Le principe, et pourquoi il est plus souple" },
          { id: "chiffres", label: "Ce que la mesure dit de sa difficulté" },
          { id: "combinatoire", label: "La combinatoire, refaite à la main" },
          { id: "jouer", label: "Comment le jouer sans tomber dans le piège" },
          { id: "quand", label: "Quand le 2sur4 est le bon pari" },
        ]}
      />

      <H2 id="principe">Le principe, et pourquoi il est plus souple</H2>
      <p>
        Le 2sur4 demande de désigner <strong>deux chevaux parmi les quatre premiers</strong> à
        l&apos;arrivée, sans condition d&apos;ordre. Pas d&apos;ordre exact, pas de quatuor complet à
        reconstituer : deux noms dans le bon wagon suffisent. Le pari est proposé à partir de dix
        partants.
      </p>
      <p>
        Cette souplesse en fait le contraire exact du{" "}
        <Link href="/blog/tierce-ordre-ou-desordre">Tiercé dans l&apos;ordre</Link>, où une
        inversion de deux chevaux fait tout perdre. Là où le Tiercé sanctionne l&apos;erreur de
        classement, le 2sur4 ne juge que la sélection.
      </p>

      <H2 id="chiffres">Ce que la mesure dit de sa difficulté</H2>
      <p>
        Nous avons repris les <strong>{D.courses} courses</strong> proposant le 2sur4 sur les douze
        derniers mois, et regardé, pour chacune, où les chevaux les plus joués avaient fini.
      </p>

      <Barres
        titre="Part des courses où le ticket est gagnant, selon la sélection"
        legende="Un ticket 2sur4 gagne dès que deux des chevaux retenus figurent dans les quatre premiers."
        barres={[
          { label: "Deux chevaux au hasard", valeur: D.hasard },
          { label: "Les deux premières cotes", valeur: D.deuxFavoris, accent: true },
          { label: "Deux quelconques des 4 premières cotes", valeur: D.top4 },
          { label: "Deux quelconques des 6 premières cotes", valeur: D.top6 },
        ]}
        max={100}
        source={`${D.courses} courses, arrivées officielles PMU. Les trois dernières lignes supposent qu'on joue toutes les paires possibles de la sélection — 1, 6 et 15 combinaisons respectivement.`}
      />

      <p>
        Trois lectures utiles. D&apos;abord, <strong>le pari est réellement accessible</strong> :
        même la sélection la plus bête qui soit — les deux favoris — passe plus d&apos;une fois sur
        trois. Ensuite, <strong>élargir marche</strong>, ce qui est rare : couvrir les six premières
        cotes rend le ticket gagnant dans {String(D.top6).replace(".", ",")} % des courses. Enfin,
        en moyenne <strong>{D.moyTop4} des quatre premières cotes</strong> terminent effectivement
        dans les quatre premiers : le marché a raison à moitié, et c&apos;est l&apos;autre moitié
        qui fait les rapports.
      </p>

      <Encadre titre="Le piège du raisonnement" ton="garde">
        <p>
          Ces fréquences ne sont pas des rendements. Un ticket qui gagne une fois sur trois peut
          parfaitement perdre de l&apos;argent : tout dépend de ce qu&apos;il paie, et la
          combinaison des deux favoris est justement la plus jouée de toutes — donc la moins bien
          payée. C&apos;est la même règle que partout ailleurs :{" "}
          <Link href="/blog/comprendre-les-cotes">la fréquence et le prix se lisent ensemble</Link>,
          jamais l&apos;une sans l&apos;autre.
        </p>
      </Encadre>

      <H2 id="combinatoire">La combinatoire, refaite à la main</H2>
      <p>
        Le chiffre de référence — {String(D.hasard).replace(".", ",")} % au hasard — se retrouve à
        la main. Dans une course de treize partants, on peut former 78 paires différentes ; les
        quatre premiers de l&apos;arrivée en contiennent six (4 × 3 ÷ 2). Une paire tirée au sort a
        donc 6 chances sur 78, soit 7,7 %. Moyenné sur la taille réelle des pelotons de
        l&apos;échantillon, le plancher du hasard s&apos;établit à {String(D.hasard).replace(".", ",")} %.
      </p>
      <p>
        À titre de comparaison, trouver le trio d&apos;un{" "}
        <Link href="/blog/tierce-ordre-ou-desordre">Tiercé</Link> au hasard dans la même course,
        c&apos;est une chance sur 286 dans le désordre — et une sur 1 716 dans l&apos;ordre. Le
        2sur4 joue dans une autre catégorie de difficulté, et c&apos;est précisément pour cela
        qu&apos;il paie moins.
      </p>

      <H2 id="jouer">Comment le jouer sans tomber dans le piège</H2>
      <ul>
        <li>
          <strong>Associez un favori solide à un outsider défendable.</strong> Si l&apos;outsider
          accroche le quatuor, le rapport change de dimension — alors que deux favoris donnent la
          combinaison que tout le monde a jouée.
        </li>
        <li>
          <strong>Ne confondez pas large et rentable.</strong> Six chevaux, c&apos;est quinze
          combinaisons : le ticket gagne {String(D.top6).replace(".", ",")} % du temps, mais coûte
          quinze fois la mise de base. Le calcul complet de ce compromis est dans{" "}
          <Link href="/blog/champ-reduit-base-tickets">base et champ réduit</Link>.
        </li>
        <li>
          <strong>Regardez la taille du peloton.</strong> À dix partants, il y a 45 paires
          possibles ; à seize, 120. Le même ticket n&apos;a pas du tout la même valeur selon le
          champ, et c&apos;est le premier réflexe à prendre.
        </li>
        <li>
          <strong>Méfiez-vous des chevaux à très grosse cote.</strong> Mesuré sur un an, un cheval
          coté 20 ou plus ne gagne que 1,8 % des courses et rend −34,5 % à qui le joue
          systématiquement — le détail est dans{" "}
          <Link href="/blog/favori-ou-outsider">favori ou outsider</Link>.
        </li>
      </ul>

      <H2 id="quand">Quand le 2sur4 est le bon pari</H2>
      <p>
        Le 2sur4 récompense la sélection, pas le classement. Il est donc à sa place quand vous avez
        une conviction sur <em>qui</em> sera devant sans avoir d&apos;idée sur l&apos;ordre — le cas
        le plus fréquent dans un gros peloton. À l&apos;inverse, si votre conviction porte sur un
        vainqueur précis, le Simple Gagnant ou le{" "}
        <Link href="/blog/couple-gagnant-ou-place">Couplé</Link> exploitent mieux cette information.
      </p>
      <p>
        C&apos;est aussi un bon pari de fond pour une bankroll modeste : la fréquence de gain limite
        les séries perdantes, ce qui compte autant que l&apos;espérance quand on joue régulièrement.
        Voir notre méthode de{" "}
        <Link href="/blog/gestion-bankroll-courses">gestion de capital</Link>.
      </p>

      <Suite href="/programme" cta="Voir le programme">
        Les courses qui proposent le 2sur4 sont signalées sur le programme du jour, avec la
        probabilité calculée pour chaque cheval et la cote du marché en face.
      </Suite>

      <Methode>
        <p>
          Mesures du 21 septembre 2026 sur les {D.courses} courses proposant le 2sur4, terminées
          entre septembre 2025 et septembre 2026, dont les quatre premières places sont publiées.
          Cotes PMU au départ, non-partants exclus ; les courses sans cote exploitable sont
          écartées, pas corrigées.
        </p>
        <p>
          Les fréquences portent sur l&apos;arrivée, pas sur les gains : un ticket est compté
          gagnant dès que deux chevaux de la sélection figurent dans les quatre premiers. Le taux
          « au hasard » est calculé sur la taille moyenne des pelotons de l&apos;échantillon
          ({D.partants} partants).
        </p>
      </Methode>
    </>
  );
}
