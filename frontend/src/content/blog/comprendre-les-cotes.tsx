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
 * Article de socle : presque tous les autres y renvoient pour « prélèvement » et
 * « probabilité implicite ». Il ne portait aucun chiffre maison — 336 mots de définitions
 * qu'on trouve partout. Refait le 2026-09-21 avec deux mesures qui n'existent que chez
 * nous : le rendement réel par tranche de cote, et ce que devient un cheval dont la cote
 * bouge entre l'ouverture et le départ.
 *
 * Sources : `participations.cote_pmu` (cote au départ), `cote_reference` (ouverture), et
 * l'arrivée officielle. Douze mois glissants, non-partants exclus.
 */
export const meta = {
  slug: "comprendre-les-cotes",
  title: "Cotes hippiques : tout comprendre, chiffres à l'appui",
  description:
    "Probabilité implicite, prélèvement, mouvement de cote : ce qu'une cote dit vraiment, mesuré sur 211 000 partants et un an de courses PMU.",
  date: "2026-06-23",
  updated: "2026-09-21",
  tags: ["Cotes", "PMU", "Bases"],
  readingMinutes: 9,
};

const C = {
  partants: "211 116",
  courses: "18 992",
  // Rendement d'une mise aveugle de 1 € en Simple Gagnant, par tranche de cote.
  tranches: [
    { cote: "Moins de 2", taux: 53.2, rendement: -13.2 },
    { cote: "2 à 3", taux: 35.6, rendement: -13.0 },
    { cote: "3 à 5", taux: 22.7, rendement: -11.9 },
    { cote: "5 à 10", taux: 12.7, rendement: -11.0 },
    { cote: "10 à 20", taux: 6.2, rendement: -17.5 },
    { cote: "20 et plus", taux: 1.8, rendement: -34.5 },
  ],
  // Mouvement entre la cote d'ouverture et la cote au départ.
  mouvements: [
    { libelle: "Baisse de plus de 20 %", n: "48 536", taux: 15.4, rendement: -14.1 },
    { libelle: "Baisse de 5 à 20 %", n: "22 715", taux: 13.4, rendement: -12.1 },
    { libelle: "Cote stable (± 5 %)", n: "14 371", taux: 10.9, rendement: -21.9 },
    { libelle: "Hausse de 5 à 20 %", n: "20 177", taux: 9.4, rendement: -18.7 },
    { libelle: "Hausse de plus de 20 %", n: "92 830", taux: 4.4, rendement: -30.1 },
  ],
};

const pct = (n: number) => `${String(n).replace(".", ",")} %`;

export default function Body() {
  return (
    <>
      <Chapo>
        Une cote ne dit pas « ce cheval va gagner ». Elle dit combien d&apos;argent a été misé sur
        lui, et rien d&apos;autre. Tout le reste — la probabilité qu&apos;elle implique, la marge
        qu&apos;elle cache, ce que son mouvement annonce — se déduit, et surtout se mesure.
      </Chapo>

      <Chiffres
        items={[
          { valeur: C.partants, libelle: "partants mesurés", detail: `sur ${C.courses} courses` },
          { valeur: "−11,0 %", libelle: "meilleure tranche de cote", detail: "de 5 à 10, mise aveugle" },
          { valeur: "−34,5 %", libelle: "pire tranche de cote", detail: "20 et plus" },
          { valeur: "1 / cote", libelle: "probabilité implicite", detail: "la formule à retenir" },
        ]}
        source="Douze mois de courses terminées, arrivées officielles PMU et cote au départ. Mesure du 21 septembre 2026."
      />

      <Sommaire
        items={[
          { id: "implicite", label: "Cote et probabilité implicite" },
          { id: "mutuel", label: "Pari mutuel : la cote n'est jamais acquise" },
          { id: "prelevement", label: "Le prélèvement, ce mur invisible" },
          { id: "tranches", label: "Ce que rend vraiment chaque tranche de cote" },
          { id: "mouvement", label: "Lire le mouvement d'une cote" },
          { id: "cloture", label: "La cote de clôture, juge de paix" },
          { id: "retenir", label: "Ce qu'il faut retenir" },
        ]}
      />

      <H2 id="implicite">Cote et probabilité implicite</H2>
      <p>
        Au PMU — un pari <strong>mutuel</strong> — la cote découle de la répartition des mises : les
        parieurs jouent les uns contre les autres, et l&apos;opérateur se sert au passage. La règle
        de lecture tient en une ligne : <strong>probabilité implicite ≈ 1 / cote</strong>.
      </p>
      <p>
        Un cheval à 5,0 « vaut » donc environ 20 % de chances aux yeux du marché ; un cheval à 2,0,
        50 % ; un cheval à 25, 4 %. C&apos;est cette probabilité-là — pas la cote elle-même —
        qu&apos;il faut comparer à votre propre estimation pour repérer un{" "}
        <Link href="/guides/pari-de-valeur">pari de valeur</Link>. Un cheval n&apos;est jamais
        « trop coté » dans l&apos;absolu : il l&apos;est par rapport à une chance estimée ailleurs.
      </p>

      <H2 id="mutuel">Pari mutuel : la cote n&apos;est jamais acquise</H2>
      <p>
        Contrairement à un bookmaker à cote fixe, le PMU ne vous garantit pas le prix affiché au
        moment où vous misez. La cote bouge jusqu&apos;au départ, et c&apos;est la{" "}
        <strong>cote finale</strong> qui détermine votre gain. Celle que vous voyez trente minutes
        avant est une projection, calculée sur les enjeux déjà engagés.
      </p>
      <p>
        Cette mécanique a une conséquence souvent ignorée : sur un cheval très joué à la dernière
        minute, vous encaisserez moins que ce que l&apos;écran annonçait. Sur un cheval délaissé,
        plus. Le prix réel de votre pari n&apos;est connu qu&apos;au moment du départ.
      </p>

      <H2 id="prelevement">Le prélèvement, ce mur invisible</H2>
      <p>
        Le PMU prélève une part des enjeux avant de redistribuer — de l&apos;ordre de 15 à 30 %
        selon la formule de pari. Mécaniquement, la somme des probabilités implicites d&apos;une
        course dépasse 100 % : le marché est « surcoté » de ce prélèvement.
      </p>

      <Encadre titre="Ce que ça implique, concrètement" ton="cle">
        <p>
          Aucune stratégie mécanique ne peut être rentable si elle se contente de suivre le marché.
          Miser systématiquement sur le favori, sur l&apos;outsider, sur le cheval le plus joué :
          toutes ces règles perdent, parce qu&apos;elles paient la marge sans rien apporter que le
          marché ne sache déjà. La seule rentabilité possible vient d&apos;un écart{" "}
          <em>mesuré</em> entre la vraie chance d&apos;un cheval et son prix.
        </p>
      </Encadre>

      <H2 id="tranches">Ce que rend vraiment chaque tranche de cote</H2>
      <p>
        Voici la mesure. On prend les {C.partants} partants des douze derniers mois, on les range
        par tranche de cote, et on calcule ce qu&apos;aurait rendu une mise de 1 € en Simple Gagnant
        sur <em>chacun</em> d&apos;eux.
      </p>

      <Barres
        titre="Perte d'une mise aveugle de 1 €, par tranche de cote"
        legende="Toutes les tranches perdent — c'est le prélèvement. Mais elles ne perdent pas également, et l'écart est le fait le plus utile de cet article."
        barres={C.tranches.map((t) => ({
          label: `Cote ${t.cote.toLowerCase()} — gagne ${pct(t.taux)} du temps`,
          valeur: Math.abs(t.rendement),
          affichage: `−${String(Math.abs(t.rendement)).replace(".", ",")} %`,
          accent: t.cote === "20 et plus",
        }))}
        max={38}
        source={`${C.partants} partants, ${C.courses} courses, cote PMU au départ, non-partants exclus.`}
      />

      <p>
        De <strong>moins de 2 à 10</strong>, la perte tourne autour de 11 à 13 % : à peu près le
        prélèvement, ni plus ni moins. Au-delà, elle s&apos;effondre —{" "}
        <strong>−17,5 %</strong> entre 10 et 20, <strong>−34,5 %</strong> à partir de 20. C&apos;est
        le <strong>biais favori-outsider</strong> : les parieurs sur-misent les gros rapports, ce qui
        écrase leur cote sous leur vraie chance. Un cheval à 20 et plus gagne 1,8 fois sur cent, et
        le marché le paie comme s&apos;il gagnait nettement plus souvent.
      </p>
      <p>
        La conclusion va à rebours de l&apos;intuition : ce n&apos;est pas dans les grosses cotes que
        se cache la valeur, c&apos;est là qu&apos;elle est systématiquement absente. Le détail par
        rang de cote et par taille de peloton est dans{" "}
        <Link href="/blog/favori-ou-outsider">favori ou outsider</Link>.
      </p>

      <H2 id="mouvement">Lire le mouvement d&apos;une cote</H2>
      <p>
        Une cote qui se raccourcit signale un afflux d&apos;argent ; une dérive à la hausse,
        l&apos;inverse. Tout le monde le sait. Ce que presque personne ne publie, c&apos;est ce que
        ces mouvements donnent à l&apos;arrivée. Nous comparons ici la cote d&apos;ouverture à la
        cote au départ, sur les mêmes douze mois :
      </p>

      <Barres
        titre="Rendement selon le mouvement de la cote, de l'ouverture au départ"
        legende="Perte d'une mise de 1 € en Simple Gagnant sur tous les chevaux de la catégorie. Le taux de victoire de chaque catégorie figure dans le libellé."
        barres={C.mouvements.map((m) => ({
          label: `${m.libelle} — gagne ${pct(m.taux)} du temps`,
          valeur: Math.abs(m.rendement),
          affichage: `−${String(Math.abs(m.rendement)).replace(".", ",")} %`,
          accent: m.libelle.startsWith("Baisse de 5"),
        }))}
        max={34}
        source="Cote d'ouverture et cote au départ relevées par notre collecte, non-partants exclus. Les chevaux sans cote d'ouverture publiée sont hors mesure."
      />

      <p>
        Trois enseignements, et le troisième surprend :
      </p>
      <ul>
        <li>
          <strong>suivre l&apos;argent coûte moins cher que le fuir.</strong> Les chevaux dont la
          cote baisse perdent 12 à 14 % ; ceux dont elle grimpe fortement en perdent 30 ;
        </li>
        <li>
          <strong>la dérive est un mauvais signe, et elle est massive</strong> : {C.mouvements[4].n}{" "}
          partants sur la période ont vu leur cote monter de plus de 20 % — ce sont, pour
          l&apos;essentiel, les gros outsiders délaissés à mesure que l&apos;heure tourne ;
        </li>
        <li>
          <strong>la cote qui ne bouge pas rend moins bien que la cote qui baisse</strong> (−21,9 %
          contre −12,1 %). Une cote immobile, ce n&apos;est pas un marché confiant : c&apos;est un
          marché indifférent.
        </li>
      </ul>

      <Encadre titre="Le piège de lecture" ton="garde">
        <p>
          Ces catégories ne contiennent pas les mêmes chevaux : la cote moyenne d&apos;un cheval en
          forte baisse est de 13, celle d&apos;un cheval en forte hausse de 60. Le tableau ne dit
          donc pas « jouez tous les chevaux dont la cote baisse » — cette règle perd encore 14 %. Il
          dit que le mouvement <em>porte une information réelle</em>, et qu&apos;un modèle a intérêt
          à s&apos;en servir. C&apos;est le cas du{" "}
          <Link href="/pronostics-ia">nôtre</Link>, qui suit le mouvement de cote parmi ses variables.
        </p>
      </Encadre>

      <H2 id="cloture">La cote de clôture, juge de paix</H2>
      <p>
        Puisque la cote finale agrège tout ce que le marché a appris, elle constitue la meilleure
        estimation disponible de la vraie chance d&apos;un cheval. D&apos;où la mesure qui départage
        les pronostiqueurs sérieux des autres : la <strong>valeur à la clôture</strong>. Elle
        compare la cote obtenue au moment du pari à la cote finale.
      </p>
      <p>
        Prendre régulièrement un prix supérieur à la clôture, c&apos;est avoir vu avant le marché —
        et c&apos;est la chose la plus difficile à obtenir par chance. Sur le <Link href="/track-record">palmarès public</Link>,{" "}
        <strong>58,2 %</strong> des paris enregistrés l&apos;ont été au-dessus de la cote de
        clôture, avec un écart médian de +22,2 %.
      </p>

      <H2 id="retenir">Ce qu&apos;il faut retenir</H2>
      <ul>
        <li>la cote est un prix, pas une prédiction : elle mesure l&apos;argent, pas le cheval ;</li>
        <li>probabilité implicite ≈ 1 / cote, et la somme des probabilités d&apos;une course dépasse 100 % — c&apos;est le prélèvement ;</li>
        <li>les tranches de 3 à 10 sont les moins chères ; au-delà de 20, le marché est très au-dessus de la réalité ;</li>
        <li>un mouvement de cote informe, mais ne constitue pas une stratégie à lui seul ;</li>
        <li>la cote de clôture est l&apos;étalon : battre ce prix, régulièrement, est le seul signe d&apos;avantage qui ne s&apos;explique pas par la chance.</li>
      </ul>

      <Suite href="/programme" cta="Voir les cotes du jour">
        Cotes PMU en direct, probabilité calculée par cheval et écart entre les deux : c&apos;est
        exactement la comparaison décrite ici, faite course par course.
      </Suite>

      <Methode>
        <p>
          Mesures du 21 septembre 2026 sur les courses terminées des douze derniers mois :{" "}
          {C.courses} courses portant une arrivée officielle et une cote PMU exploitable, soit{" "}
          {C.partants} partants, non-partants exclus.
        </p>
        <p>
          Le rendement est celui d&apos;une mise de 1 € en Simple Gagnant sur chaque cheval de la
          catégorie, rapport officiel encaissé en cas de victoire : (gains − mises) / mises. Le
          mouvement de cote compare la cote d&apos;ouverture publiée à la dernière cote avant le
          départ ; les partants sans cote d&apos;ouverture sont écartés, pas corrigés.
        </p>
      </Methode>
    </>
  );
}
