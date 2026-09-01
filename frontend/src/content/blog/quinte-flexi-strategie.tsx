import Link from "next/link";

/**
 * Article développé le 2026-09-01 sur une mesure Search Console, pas sur une intuition.
 *
 * Constat : la page se classait 15,3ᵉ sur « flexi 4 chevaux » (19 impressions sur 90 j,
 * marché FRANÇAIS — l'une des rares requêtes non-marque du site où la demande est
 * hexagonale) avec **zéro clic**, et pour cause : en 465 mots elle n'énonçait AUCUN
 * chiffre. Ni le nombre de combinaisons, ni le prix d'un ticket, ni ce que rapporte un
 * Flexi qui tombe. Elle décrivait un mécanisme sans jamais répondre à la question posée.
 *
 * Ajouts : le tableau des combinaisons et des coûts (arithmétique vérifiable :
 * C(n,5) × 2 € × taux), ce que paie un ticket au taux choisi en s'appuyant sur le
 * rapport médian mesuré sur 249 Quintés (voir /blog/quinte-ordre-ou-desordre), et une
 * section qui traite frontalement « flexi 4 chevaux » — un Quinté Flexi exige au moins
 * 5 chevaux, la requête repose sur une confusion qu'il faut lever plutôt qu'ignorer.
 *
 * Les taux 50 / 25 / 10 % et la mise de base de 2 € sont les règles PMU ; le détail exact
 * de l'offre peut varier selon l'opérateur, ce que l'article dit.
 */
export const meta = {
  slug: "quinte-flexi-strategie",
  title: "Quinté+ Flexi : combien ça coûte, selon le nombre de chevaux",
  description:
    "Le tableau complet : combinaisons, prix du ticket et gain réel du Quinté+ Flexi à 50 %, 25 % ou 10 %, de 5 à 10 chevaux. Et pourquoi 4 chevaux est impossible.",
  date: "2026-06-23",
  updated: "2026-09-01",
  tags: ["Quinté+", "Flexi", "Stratégie"],
  readingMinutes: 8,
};

const LIGNES = [
  { n: 5, c: 1, cent: "2,00 €", cinquante: "1,00 €", vingtcinq: "0,50 €", dix: "0,20 €" },
  { n: 6, c: 6, cent: "12,00 €", cinquante: "6,00 €", vingtcinq: "3,00 €", dix: "1,20 €" },
  { n: 7, c: 21, cent: "42,00 €", cinquante: "21,00 €", vingtcinq: "10,50 €", dix: "4,20 €" },
  { n: 8, c: 56, cent: "112,00 €", cinquante: "56,00 €", vingtcinq: "28,00 €", dix: "11,20 €" },
  { n: 9, c: 126, cent: "252,00 €", cinquante: "126,00 €", vingtcinq: "63,00 €", dix: "25,20 €" },
  { n: 10, c: 252, cent: "504,00 €", cinquante: "252,00 €", vingtcinq: "126,00 €", dix: "50,40 €" },
];

export default function Body() {
  return (
    <>
      <p>
        Couvrir 6, 7 ou 8 chevaux au Quinté+ coûte vite cher : le nombre de combinaisons explose. Le
        Flexi est la réponse du PMU à ce problème — à condition de comprendre ce qu&apos;on échange.
        Voici les chiffres exacts, combinaison par combinaison, plutôt que le principe seul.
      </p>

      <h2>Le principe du Flexi</h2>
      <p>
        Le Flexi vous laisse jouer un ticket à <strong>50 %, 25 % ou 10 %</strong> de la mise de base.
        Vous misez moins, donc vous pouvez élargir votre champ ; en contrepartie, vous touchez la même
        fraction du rapport. Un Flexi à 25 % qui « tombe » paie un quart du rapport plein.
      </p>

      <h2>Combien coûte un Quinté+ Flexi, cheval par cheval</h2>
      <p>
        Le calcul n&apos;a rien de mystérieux. Jouer <strong>n</strong> chevaux au Quinté+ revient à
        jouer toutes les combinaisons de 5 qu&apos;on peut en tirer, soit C(n,5) tickets à{" "}
        <strong>2 € la combinaison</strong>. Le Flexi multiplie ce total par le taux choisi.
      </p>
      <div className="overflow-x-auto">
        <table>
          <caption className="sr-only">
            Coût d&apos;un Quinté+ Flexi selon le nombre de chevaux et le taux choisi
          </caption>
          <thead>
            <tr>
              <th>Chevaux</th>
              <th>Combinaisons</th>
              <th>100 %</th>
              <th>Flexi 50 %</th>
              <th>Flexi 25 %</th>
              <th>Flexi 10 %</th>
            </tr>
          </thead>
          <tbody>
            {LIGNES.map((l) => (
              <tr key={l.n}>
                <td>
                  <strong>{l.n}</strong>
                </td>
                <td>{l.c}</td>
                <td>{l.cent}</td>
                <td>{l.cinquante}</td>
                <td>{l.vingtcinq}</td>
                <td>{l.dix}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>
        La lecture importante n&apos;est pas le prix mais sa <strong>progression</strong> : passer de
        6 à 7 chevaux multiplie le ticket par 3,5 ; de 7 à 8, encore par 2,7. Chaque cheval ajouté
        coûte beaucoup plus cher que le précédent. C&apos;est cette courbe, et pas le budget en
        lui-même, qui doit décider où l&apos;on s&apos;arrête.
      </p>
      <p>
        Selon l&apos;opérateur, une mise minimale par ticket peut s&apos;appliquer et tous les taux ne
        sont pas toujours proposés. Le principe de calcul, lui, ne change pas.
      </p>

      <h2>Et si ça tombe, on touche quoi ?</h2>
      <p>
        C&apos;est la moitié de l&apos;équation que la plupart des présentations oublient. Un Quinté+
        gagnant paie <strong>2 × le rapport</strong> pour un ticket plein — et le taux Flexi
        s&apos;applique à ce gain exactement comme il s&apos;est appliqué à la mise.
      </p>
      <p>
        Nous avons mesuré le rapport du Quinté+ dans le désordre sur{" "}
        <Link href="/blog/quinte-ordre-ou-desordre">249 courses d&apos;une année complète</Link> : sa
        médiane est de <strong>230,20 € pour 1 €</strong>. Un ticket gagnant vaut donc, en médiane :
      </p>
      <ul>
        <li>
          à <strong>100 %</strong> : environ <strong>460 €</strong> ;
        </li>
        <li>
          à <strong>25 %</strong> : environ <strong>115 €</strong> ;
        </li>
        <li>
          à <strong>10 %</strong> : environ <strong>46 €</strong>.
        </li>
      </ul>
      <p>
        Ces montants ne dépendent <em>pas</em> du nombre de chevaux joués : élargir le champ augmente
        vos chances de toucher, jamais la somme touchée. Le Flexi, lui, ne change ni l&apos;une ni
        l&apos;autre — il met les deux à l&apos;échelle.
      </p>

      <h2>« Flexi 4 chevaux » : pourquoi ça n&apos;existe pas</h2>
      <p>
        C&apos;est l&apos;une des recherches les plus fréquentes sur le sujet, et elle repose sur une
        confusion qu&apos;il vaut mieux lever tout de suite : <strong>un Quinté+ porte sur cinq
        chevaux</strong>. On ne peut donc pas en jouer quatre, avec ou sans Flexi. Le Flexi sert à
        jouer <em>plus</em> de cinq chevaux à moindre coût, jamais moins.
      </p>
      <p>Quand on cherche « flexi 4 chevaux », on veut en général l&apos;une de ces trois choses :</p>
      <ul>
        <li>
          <strong>quatre chevaux de base plus un champ</strong> — vous êtes sûr de quatre noms et vous
          complétez la cinquième place par plusieurs candidats. C&apos;est un{" "}
          <Link href="/blog/champ-reduit-base-tickets">champ réduit</Link>, et c&apos;est exactement
          l&apos;usage pour lequel le Flexi a été conçu ;
        </li>
        <li>
          <strong>un pari qui porte réellement sur quatre chevaux</strong> : le Quarté+, ou le{" "}
          <Link href="/blog/comprendre-le-2sur4">2 sur 4</Link> si vous voulez seulement deux
          chevaux parmi les quatre premiers ;
        </li>
        <li>
          <strong>le Multi</strong>, qui se joue en 4, 5, 6 ou 7 chevaux — c&apos;est le seul pari du
          programme dont le nom porte le nombre de chevaux, d&apos;où la confusion fréquente avec le
          Flexi. Le détail des formules figure dans notre{" "}
          <Link href="/guides/types-de-paris-pmu">guide des paris PMU</Link>.
        </li>
      </ul>

      <h2>Un échange, pas un cadeau</h2>
      <p>
        Le Flexi ne change pas votre <Link href="/guides/pari-de-valeur">espérance</Link> : il met à
        l&apos;échelle mise et gain. Son intérêt n&apos;est pas « gagner plus », mais{" "}
        <strong>jouer une combinaison plus large à budget constant</strong> — utile quand vous tenez
        une base solide mais hésitez sur les places 4 et 5.
      </p>
      <p>
        La vraie question, à budget fixé, est donc : <strong>vaut-il mieux 6 chevaux à 50 % ou 8
        chevaux à 10 % ?</strong> Le premier coûte 6 €, le second 11,20 € ; mais si l&apos;on ramène
        au même budget, le second couvre neuf fois plus de combinaisons pour un gain cinq fois plus
        petit. Aucune des deux options ne domine l&apos;autre : le choix dépend entièrement de la
        qualité des chevaux ajoutés. Deux chevaux de plus qui n&apos;ont aucune chance sérieuse ne
        font qu&apos;acheter du prélèvement.
      </p>

      <h2>Quand l&apos;utiliser</h2>
      <ul>
        <li>Vous avez 1-2 chevaux de confiance et beaucoup d&apos;incertitude derrière.</li>
        <li>La course est ouverte (handicap à gros effectif) et vous voulez sécuriser les bonus.</li>
        <li>Votre budget par course est limité mais vous refusez de vous réduire à 5 noms.</li>
      </ul>

      <h2>Quand l&apos;éviter</h2>
      <p>
        Si vous n&apos;avez aucune conviction, le Flexi ne fait qu&apos;étaler une mise sans valeur sur
        plus de combinaisons. Élargir un champ sans edge revient à payer plus de prélèvement. Mieux
        vaut un ticket resserré sur de vrais paris de valeur.
      </p>
      <p>
        Le rappel qui vaut pour toutes les formules : le pari mutuel prélève environ 20 % des enjeux
        avant redistribution. Aucune mécanique de mise, Flexi compris, ne fait baisser ce seuil — seul
        un avantage réel sur l&apos;estimation des chances le franchit.
      </p>

      <p>
        Voir les types de paris en détail dans notre{" "}
        <Link href="/guides/types-de-paris-pmu">guide des paris PMU</Link>, le{" "}
        <Link href="/blog/analyser-quinte-du-jour">Quinté+ du jour analysé</Link>, ou{" "}
        <Link href="/programme">le programme et les analyses du jour</Link>.
      </p>
    </>
  );
}
