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
 * C'est l'article le mieux placé du site sur une requête hors marque : « tiercé ordre »
 * et ses variantes, position moyenne 7,5 en août 2026. Il porte donc la mesure maison qui
 * n'existe nulle part ailleurs — le facteur entre le rapport Ordre et le rapport Désordre,
 * relevé course par course.
 *
 * Chiffres refaits le 2026-09-21 sur les douze derniers mois (la version précédente
 * portait sur 300 courses relevées en juin). Source : `resultats.rapports_detail`, seul
 * endroit où le PMU publie LES DEUX rapports d'un même Tiercé — `rapports` n'en garde
 * qu'un. Ne garder que les lignes où les deux combinaisons coïncident.
 */
export const meta = {
  slug: "tierce-ordre-ou-desordre",
  title: "Tiercé ordre ou désordre : lequel rapporte le plus ?",
  description:
    "Mesuré sur 358 Tiercés : l'ordre exact paie 6,1 fois le désordre — exactement le rapport des chances. Ce que ça change pour votre ticket.",
  date: "2026-06-23",
  updated: "2026-09-21",
  tags: ["Tiercé", "PMU", "Stratégie"],
  readingMinutes: 8,
};

const T = {
  n: "358",
  ordreMed: "380,80 €",
  desMed: "60,70 €",
  desQ1: "26,33 €",
  desQ3: "165,43 €",
  facteurMed: "6,09",
  facteurQ1: "5,83",
  facteurQ3: "6,57",
  sup10: 3,
  desMoins20: 66,
  desPlus200: 73,
  // Couverture du trio d'arrivée par les N premières cotes, sur 363 Tiercés.
  couverture: [
    { n: 3, pct: 4.1, trouves: "1,26", combinaisons: 1 },
    { n: 4, pct: 12.4, trouves: "1,59", combinaisons: 4 },
    { n: 5, pct: 21.2, trouves: "1,85", combinaisons: 10 },
    { n: 6, pct: 32.0, trouves: "2,08", combinaisons: 20 },
    { n: 8, pct: 50.7, trouves: "2,39", combinaisons: 56 },
  ],
};

export default function Body() {
  return (
    <>
      <Chapo>
        Trouver les trois premiers dans l&apos;ordre exact paie environ six fois plus que de les
        trouver dans le désordre. Ce n&apos;est pas une prime au courage : trois chevaux se rangent
        de six façons. L&apos;ordre paie exactement ce qu&apos;il coûte en probabilité — ce qui
        change n&apos;est pas le gain espéré, c&apos;est la régularité.
      </Chapo>

      <Chiffres
        items={[
          { valeur: T.ordreMed, libelle: "rapport Ordre médian", detail: "pour 1 € joué" },
          { valeur: T.desMed, libelle: "rapport Désordre médian", detail: "pour 1 € joué" },
          { valeur: `×${T.facteurMed}`, libelle: "facteur Ordre / Désordre", detail: `moitié des courses entre ×${T.facteurQ1} et ×${T.facteurQ3}` },
          { valeur: "6", libelle: "façons de ranger trois chevaux", detail: "3 × 2 × 1 — la théorie" },
        ]}
        source={`Mesuré le 21 septembre 2026 sur les ${T.n} Tiercés des douze derniers mois dont le PMU publie les deux rapports.`}
      />

      <Sommaire
        items={[
          { id: "difference", label: "Ordre, désordre : ce qui change vraiment" },
          { id: "combien", label: "Combien l'ordre paie-t-il de plus ? La mesure" },
          { id: "pourquoi-six", label: "Pourquoi 6, et pourquoi ça règle le débat" },
          { id: "ce-que-paie", label: "Ce que paie un Tiercé, en vrai" },
          { id: "combien-chevaux", label: "Combien de chevaux faut-il pour tenir le trio ?" },
          { id: "strategie", label: "La stratégie « ordre + désordre »" },
          { id: "quinte", label: "Et au Quinté+, ce ×6 devient quoi ?" },
          { id: "trio", label: "Tiercé ou Trio ?" },
        ]}
      />

      <H2 id="difference">Ordre, désordre : ce qui change vraiment</H2>
      <p>
        Le Tiercé porte sur les trois premiers chevaux de l&apos;arrivée. Les trouver{" "}
        <strong>dans l&apos;ordre exact</strong> paie le rapport « Ordre » ; les trouver{" "}
        <strong>dans le désordre</strong> — les bons chevaux, mal classés — paie le rapport
        « Désordre », plus modeste. Jusque-là, tout le monde est d&apos;accord.
      </p>
      <p>
        Le désaccord commence après : <em>de combien</em> l&apos;ordre paie-t-il plus ? Les forums
        avancent des multiples au doigt mouillé, de trois à cinquante. La question se tranche par la
        mesure, et la mesure est reproductible — le PMU publie les deux rapports de chaque Tiercé.
      </p>

      <H2 id="combien">Combien l&apos;ordre paie-t-il de plus ? La mesure</H2>
      <p>
        Sur les <strong>{T.n} Tiercés</strong> des douze derniers mois dont les deux rapports sont
        publiés :
      </p>

      <Comparatif
        titre="Ce que paie un même trio, selon la formule"
        colonnes={["Désordre", "Ordre exact"]}
        lignes={[
          { critere: "Rapport médian", a: `${T.desMed} pour 1 €`, b: `${T.ordreMed} pour 1 €` },
          {
            critere: "Fréquence",
            a: "six fois plus probable — n'importe lequel des six rangements gagne",
            b: "un seul rangement sur six est payant",
          },
          {
            critere: "Dispersion",
            a: `moitié des courses entre ${T.desQ1} et ${T.desQ3}`,
            b: "suit la même dispersion, multipliée par le facteur",
          },
          {
            critere: "Espérance à la longue",
            a: "identique à l'autre, prélèvement PMU déduit",
            b: "identique à l'autre, prélèvement PMU déduit",
          },
          {
            critere: "Ce que vous achetez",
            a: "de la régularité : vous encaissez souvent, petit",
            b: "de la variance : vous encaissez rarement, gros",
          },
        ]}
      />

      <p>
        Le facteur médian est de <strong>×{T.facteurMed}</strong>, et il est remarquablement
        stable : la moitié des courses tombe entre ×{T.facteurQ1} et ×{T.facteurQ3}, et le facteur
        ne dépasse ×10 que dans <strong>{T.sup10} courses sur {T.n}</strong>. Sur une donnée de
        marché, une telle stabilité est rare — et elle a une explication simple.
      </p>

      <H2 id="pourquoi-six">Pourquoi 6, et pourquoi ça règle le débat</H2>
      <p>
        Ce 6 n&apos;est pas un hasard de tirage. Trois chevaux se rangent de{" "}
        <strong>3 × 2 × 1 = 6 façons</strong> : trouver les bons dans n&apos;importe quel ordre est
        donc exactement <strong>six fois plus probable</strong> que de tomber sur l&apos;ordre exact.
        Le rapport mesuré, ×{T.facteurMed}, colle à ce ×6 théorique.
      </p>

      <Encadre titre="La conclusion qui en découle" ton="cle">
        <p>
          <strong>L&apos;ordre ne paie pas mieux que ce qu&apos;il coûte en probabilité.</strong> Ce
          n&apos;est ni une bonne affaire cachée, ni un piège tendu par le PMU : à la longue, les
          deux formules reviennent au même une fois le prélèvement appliqué. Le choix n&apos;est
          donc pas « lequel rapporte le plus », mais « quelle irrégularité je supporte ». Si
          encaisser une fois sur six vous fait abandonner avant, le désordre est fait pour vous — et
          ce n&apos;est pas une faiblesse, c&apos;est une{" "}
          <Link href="/blog/gestion-bankroll-courses">contrainte de bankroll</Link>.
        </p>
      </Encadre>

      <H2 id="ce-que-paie">Ce que paie un Tiercé, en vrai</H2>
      <p>
        Le rapport médian cache l&apos;essentiel : la dispersion. Un Tiercé « médian » à{" "}
        {T.desMed} n&apos;existe pratiquement jamais — les rapports réels vont du presque rien au
        très gros, et c&apos;est cette distribution qu&apos;il faut avoir en tête avant de miser.
      </p>
      <ul>
        <li>
          <strong>{T.desMoins20} Tiercés sur {T.n}</strong> ont payé{" "}
          <strong>moins de 20 €</strong> en désordre — un trio de favoris qui sort dans
          l&apos;ordre attendu rapporte le prix d&apos;un sandwich ;
        </li>
        <li>
          la moitié des courses paie entre <strong>{T.desQ1}</strong> et{" "}
          <strong>{T.desQ3}</strong> ;
        </li>
        <li>
          <strong>{T.desPlus200} Tiercés</strong> ont dépassé <strong>200 €</strong>, et ce sont
          eux qui font la rentabilité d&apos;une saison.
        </li>
      </ul>
      <p>
        Conséquence pratique, valable pour tous les paris combinés : un ticket qui ne contient que
        des premières cotes gagne souvent et rapporte peu. La valeur se trouve dans les trios où{" "}
        <strong>un</strong> cheval n&apos;était pas attendu — pas trois, un.
      </p>

      <H2 id="combien-chevaux">Combien de chevaux faut-il pour tenir le trio ?</H2>
      <p>
        Voici la contrepartie chiffrée de ce qui précède. On part du ticket le plus simple : prendre
        les N premiers chevaux du marché — les N cotes les plus basses — et jouer toutes les
        combinaisons de trois qu&apos;on peut en tirer.
      </p>

      <Barres
        titre="Part des Tiercés où les trois arrivants figurent dans les N premières cotes"
        legende="Mesuré sur 363 Tiercés des douze derniers mois. Le nombre de combinaisons à jouer figure entre parenthèses."
        barres={T.couverture.map((c) => ({
          label: `${c.n} premiers du marché (${c.combinaisons} combinaison${c.combinaisons > 1 ? "s" : ""})`,
          valeur: c.pct,
          accent: c.n === 6,
        }))}
        max={60}
        source="Cotes PMU au départ, non-partants exclus. Une course dont les cotes manquent est écartée, pas corrigée."
      />

      <p>
        Les trois favoris du marché ne donnent le trio complet que <strong>4,1 %</strong> du temps :
        autant dire que le Tiercé « évident » n&apos;existe pas. Il faut monter à{" "}
        <strong>six chevaux</strong> — vingt combinaisons — pour tenir une course sur trois, et à
        huit chevaux pour dépasser une sur deux. Chaque cheval ajouté multiplie le nombre de tickets
        bien plus vite qu&apos;il n&apos;augmente vos chances : c&apos;est exactement le calcul
        développé dans{" "}
        <Link href="/blog/champ-reduit-base-tickets">base et champ réduit</Link>.
      </p>

      <H2 id="strategie">La stratégie « ordre + désordre »</H2>
      <p>
        Beaucoup de parieurs jouent le même trio <strong>à la fois en ordre et en désordre</strong>.
        Si l&apos;ordre tombe, ils touchent le gros rapport ; sinon, le désordre sauve le ticket.
        C&apos;est confortable, et il faut savoir ce que ça coûte : la mise double, pour un gain
        espéré qui ne double pas — puisque, on vient de le voir, l&apos;ordre est payé à sa juste
        probabilité.
      </p>
      <p>
        Autrement dit, cette double mise n&apos;achète pas de la rentabilité, elle achète du{" "}
        <strong>confort psychologique</strong> : ne pas subir le « bons chevaux, mauvais ordre ».
        C&apos;est un choix défendable, à condition de l&apos;appeler par son nom et de le compter
        dans la mise.
      </p>

      <H2 id="quinte">Et au Quinté+, ce ×6 devient quoi ?</H2>
      <p>
        La belle régularité vue ici est propre au Tiercé. Au Quinté+, cinq chevaux se rangent de{" "}
        <strong>120 façons</strong>, mais le rapport ne suit pas : le facteur médian mesuré est de{" "}
        <strong>×72,8</strong>, et il descend <strong>sous ×10 dans 29 % des Quintés</strong> —
        précisément ceux qui paient le plus gros. La corrélation est claire : l&apos;ordre paie bien
        les Quintés logiques et mal les Quintés à surprise.
      </p>
      <p>
        Deuxième différence, moins connue : au Tiercé l&apos;ordre est une formule qu&apos;on
        choisit et qu&apos;on paie ; au Quinté+ c&apos;est un bonus automatique qui ne coûte rien de
        plus.{" "}
        <Link href="/blog/quinte-ordre-ou-desordre">
          Le détail chiffré, Quinté par Quinté
        </Link>
        .
      </p>

      <H2 id="trio">Tiercé ou Trio ?</H2>
      <p>
        Si l&apos;ordre ne vous intéresse pas, le{" "}
        <Link href="/guides/types-de-paris-pmu">Trio</Link> — les trois premiers en désordre
        uniquement, proposé dès huit partants — répond à la même intuition sans la formule Ordre.
        Le choix dépend de votre conviction sur la hiérarchie de tête : si vous êtes sûr du
        vainqueur mais pas du reste, l&apos;ordre a du sens ; si vous avez trois noms sans idée de
        leur classement, il n&apos;en a aucun.
      </p>

      <Suite href="/quinte-du-jour" cta="Voir la course du jour">
        Les mêmes chiffres, appliqués à la course du jour : probabilité par cheval, cotes en direct,
        et la hiérarchie du modèle comparée à celle du marché.
      </Suite>

      <p>
        Quel que soit le pari, l&apos;essentiel reste de jouer des chevaux à{" "}
        <Link href="/guides/pari-de-valeur">valeur</Link> — et de savoir ce que le marché paie déjà,
        détaillé dans <Link href="/blog/favori-ou-outsider">favori ou outsider</Link>.
      </p>

      <Methode>
        <p>
          Rapports relevés le 21 septembre 2026 sur les Tiercés terminés des douze derniers mois. Le
          PMU publie les deux rapports d&apos;un même Tiercé dans le détail des rapports ; seules
          les courses où les deux portent sur la même combinaison sont retenues — {T.n} sur la
          période. Les autres sont écartées, jamais corrigées.
        </p>
        <p>
          La couverture du trio porte sur 363 Tiercés dont les trois premières places sont publiées,
          avec les cotes PMU au départ et hors non-partants. Le nombre de combinaisons est le nombre
          de trios distincts tirés de N chevaux, à multiplier par la mise unitaire de votre
          opérateur pour obtenir le coût du ticket.
        </p>
      </Methode>
    </>
  );
}
