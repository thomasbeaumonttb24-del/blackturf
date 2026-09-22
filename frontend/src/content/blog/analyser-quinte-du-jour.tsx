import Link from "next/link";
import { H2, Sommaire } from "@/components/blog/kit";

export const meta = {
  slug: "analyser-quinte-du-jour",
  title: "Analyser le Quinté+ du jour : la méthode et les chiffres",
  description:
    "Méthode en 6 étapes pour analyser le Quinté+, chiffres à l'appui : le favori gagne 27,5 % du temps, 88,7 % des arrivées ont un cheval à 20 ou plus.",
  date: "2026-06-23",
  updated: "2026-09-21",
  tags: ["Quinté+", "Méthode", "PMU"],
  readingMinutes: 7,
};

/* Mesuré le 2026-09-21 sur la base BlackTurf : les 364 Quinté+ terminés des douze derniers
 * mois, arrivées officielles PMU et cote PMU au départ. Les rapports Ordre et Désordre
 * viennent de `rapports_detail`, seul endroit où le PMU publie les deux (250 courses où
 * les deux combinaisons coïncident ; les autres sont écartées, jamais corrigées). */
const CHIFFRES = {
  quintes: 364,
  partantsMoyen: "15,6",
  favoriGagne: "27,5 %",
  favoriAilleurs: "33,8 %",
  favoriDansLes5: "65,1 %",
  unGrosDansLes5: "88,7 %",
  duTop5Marche: "2,6",
  desordreMedian: "231,75 €",
  desordreQ1: "54,85 €",
  desordreQ3: "1 956,60 €",
  ordreMedian: "12 744,40 €",
  sousCent: 93,
  milleEtPlus: 75,
  nRapports: 250,
};

export default function Body() {
  return (
    <>
      <p>
        Le Quinté+ est le pari roi du PMU : cinq chevaux à trouver, des rapports qui peuvent
        s&apos;envoler, et chaque jour une nouvelle course support. Une méthode vaut mieux que
        l&apos;intuition — et une méthode appuyée sur des chiffres vaut mieux qu&apos;une méthode
        seule. Les {CHIFFRES.quintes} Quinté+ des douze derniers mois disent déjà beaucoup de ce
        qu&apos;il faut chercher.
      </p>

      <Sommaire
        items={[
          { id: "ce-qu-une-arrivee-de-quinte-contient-en-", label: "Ce qu'une arrivée de Quinté+ contient, en moyenne" },
          { id: "1-lire-les-conditions-de-course", label: "1. Lire les conditions de course" },
          { id: "2-filtrer-la-forme-sans-se-faire-pieger", label: "2. Filtrer la forme — sans se faire piéger" },
          { id: "3-evaluer-le-couple-jockey-entraineur", label: "3. Évaluer le couple jockey / entraîneur" },
          { id: "4-confronter-probabilite-et-cote", label: "4. Confronter probabilité et cote" },
          { id: "5-construire-le-champ", label: "5. Construire le champ" },
          { id: "6-savoir-ce-que-ca-paie-avant-de-miser", label: "6. Savoir ce que ça paie, avant de miser" },
        ]}
      />

      <H2 id="ce-qu-une-arrivee-de-quinte-contient-en-">Ce qu&apos;une arrivée de Quinté+ contient, en moyenne</H2>
      <ul>
        <li>
          <strong>{CHIFFRES.partantsMoyen} partants</strong> au départ : le peloton le plus large
          de la journée, et la première raison pour laquelle le Quinté+ paie.
        </li>
        <li>
          Le favori du marché gagne <strong>{CHIFFRES.favoriGagne}</strong> des Quinté+, contre{" "}
          {CHIFFRES.favoriAilleurs} dans les autres courses. Il figure dans les cinq premiers{" "}
          <strong>{CHIFFRES.favoriDansLes5}</strong> du temps : le battre est fréquent, l&apos;ignorer
          est cher.
        </li>
        <li>
          <strong>{CHIFFRES.unGrosDansLes5}</strong> des arrivées contiennent au moins un cheval
          coté <strong>20 ou plus</strong> au départ. Un ticket composé uniquement des premières
          cotes est donc battu neuf fois sur dix.
        </li>
        <li>
          En moyenne, seuls <strong>{CHIFFRES.duTop5Marche} des cinq premiers du marché</strong>{" "}
          terminent dans les cinq premiers de la course. Les deux ou trois autres places viennent
          d&apos;ailleurs — c&apos;est là que se joue le rapport.
        </li>
      </ul>

      <H2 id="1-lire-les-conditions-de-course">1. Lire les conditions de course</H2>
      <p>
        Handicap ou course de groupe ? Distance, discipline, état du terrain, allocation. Un
        handicap divisé serré n&apos;a rien à voir avec un Quinté+ de spécialistes : les conditions
        fixent le niveau d&apos;incertitude, donc le potentiel de gros rapport. Les fiches
        d&apos;<Link href="/hippodromes">hippodrome</Link> donnent le contexte du lieu — ce qui
        s&apos;y court, et à quelle fréquence le favori y passe.
      </p>

      <H2 id="2-filtrer-la-forme-sans-se-faire-pieger">2. Filtrer la forme — sans se faire piéger</H2>
      <p>
        Lisez la <Link href="/guides/comment-lire-la-musique">musique des chevaux</Link>, mais
        méfiez-vous : la forme évidente est sur-jouée par le public, donc sa cote est écrasée. Les
        chiffres ci-dessus le montrent autrement — le marché place en moyenne{" "}
        {CHIFFRES.duTop5Marche} de ses cinq premiers dans l&apos;arrivée : il a raison à moitié, et
        la moitié qui lui échappe est précisément ce que vous cherchez.
      </p>

      <H2 id="3-evaluer-le-couple-jockey-entraineur">3. Évaluer le couple jockey / entraîneur</H2>
      <p>
        Sur le Quinté+, l&apos;association jockey-entraîneur et l&apos;engagement — le cheval est-il
        placé là pour gagner ? — pèsent lourd. Un entraîneur qui déplace un cheval sur 600 km a
        rarement fait le voyage pour rien. Chaque fiche d&apos;hippodrome publie les cinq jockeys ou
        drivers et les cinq entraîneurs qui y gagnent le plus sur douze mois : une spécialité locale
        se lit mieux là que dans un classement national.
      </p>

      <H2 id="4-confronter-probabilite-et-cote">4. Confronter probabilité et cote</H2>
      <p>
        C&apos;est le cœur de l&apos;analyse : un cheval n&apos;est intéressant que si sa chance
        réelle dépasse ce que sa cote implique. C&apos;est la définition du{" "}
        <Link href="/guides/pari-de-valeur">pari de valeur</Link>. Un favori à 1,8 « juste » ne
        rapporte rien ; un cheval à 9,0 sous-estimé, oui. Et cela vaut dans les deux sens :{" "}
        <Link href="/blog/favori-ou-outsider">mesuré sur 211 000 partants</Link>, les cotes de 20 et
        plus rendent −34,5 %, contre −11 % pour la zone 5 à 10. Viser gros n&apos;est pas viser
        juste.
      </p>

      <H2 id="5-construire-le-champ">5. Construire le champ</H2>
      <p>
        Base (un ou deux chevaux de confiance) puis champ d&apos;outsiders à valeur — et comme neuf
        arrivées sur dix contiennent un cheval à 20 ou plus, ce champ n&apos;est pas un luxe. Le
        Quinté+ paie aussi ses bonus (Bonus 4, Bonus 4 sur 5, Bonus 3) : viser les cinq places
        exactes est rarement rentable, mieux vaut sécuriser les bonus avec une base solide. Le{" "}
        <Link href="/blog/quinte-flexi-strategie">Flexi</Link> permet de jouer plus de combinaisons
        pour la même mise, contre une part du rapport ; le{" "}
        <Link href="/blog/champ-reduit-base-tickets">champ réduit</Link> explique comment
        construire le ticket lui-même.
      </p>

      <H2 id="6-savoir-ce-que-ca-paie-avant-de-miser">6. Savoir ce que ça paie, avant de miser</H2>
      <p>
        Sur {CHIFFRES.nRapports} Quinté+ dont le PMU publie les deux rapports, le{" "}
        <strong>Désordre médian est de {CHIFFRES.desordreMedian}</strong> pour 1 € — mais la
        dispersion est énorme : un quart des courses paient moins de {CHIFFRES.desordreQ1}, un quart
        plus de {CHIFFRES.desordreQ3}. {CHIFFRES.sousCent} Quinté+ sur {CHIFFRES.nRapports} ont payé
        moins de 100 €, et {CHIFFRES.milleEtPlus} ont payé plus de 1 000 €. L&apos;Ordre, lui, paie{" "}
        {CHIFFRES.ordreMedian} en médiane — le détail de ce rapport, et la raison pour laquelle il ne
        vaut pas ce qu&apos;on croit, sont dans{" "}
        <Link href="/blog/quinte-ordre-ou-desordre">Quinté+ dans l&apos;ordre ou le désordre</Link>.
      </p>
      <p>
        Conséquence sur la mise : un bon pronostic mal misé reste perdant. Fixez une fraction de
        capital par course et tenez-la — voir notre méthode de{" "}
        <Link href="/blog/gestion-bankroll-courses">gestion de bankroll</Link>.
      </p>

      <p>
        BlackTurf applique cette logique automatiquement : une probabilité par cheval, comparée à la
        cote PMU en direct.{" "}
        <Link href="/quinte-du-jour">Voir le Quinté+ du jour analysé →</Link> Et{" "}
        <Link href="/track-record">le palmarès mesuré</Link> publie ce que ces analyses ont donné à
        l&apos;arrivée, pertes comprises.
      </p>
      <p className="text-sm">
        Méthode : {CHIFFRES.quintes} Quinté+ terminés entre le 21 septembre 2025 et le 21 septembre
        2026, arrivées officielles PMU, cote PMU au départ, non-partants exclus. Les rapports Ordre
        et Désordre proviennent du détail publié par le PMU, sur les {CHIFFRES.nRapports} courses où
        les deux combinaisons coïncident.
      </p>
    </>
  );
}
