import Link from "next/link";
import { H2, Sommaire } from "@/components/blog/kit";

export const meta = {
  slug: "champ-reduit-base-tickets",
  title: "Base et champ réduit : ce que coûte vraiment la couverture",
  description:
    "Combien de chevaux pour tenir un Quinté+ ? Mesuré sur 381 courses : 12 du marché couvrent deux arrivées sur trois, pour 1 584 € de tickets.",
  date: "2026-06-23",
  updated: "2026-09-21",
  tags: ["Méthode", "Tickets", "PMU"],
  readingMinutes: 6,
};

/* Mesuré le 2026-09-21 : les 381 Quinté+ dont l'arrivée complète figure dans la base,
 * qui commence le 2025-09-01 — la fenêtre demandée était de vingt-quatre mois, la base n'en
 * couvre que treize, et c'est ce qui est écrit. L'arrivée
 * complète est publiée. Les chevaux sont rangés par cote PMU croissante au départ ; on
 * compte combien des cinq premiers de la course figurent dans les N premiers du marché.
 * Le coût est le nombre de combinaisons C(N,5) à 2 € l'unité, hors Flexi. */
const COUVERTURE = [
  { n: 5, trouves: "2,65", complet: "1,6 %", combinaisons: 1, cout: "2 €" },
  { n: 6, trouves: "3,07", complet: "4,7 %", combinaisons: 6, cout: "12 €" },
  { n: 8, trouves: "3,70", complet: "18,1 %", combinaisons: 56, cout: "112 €" },
  { n: 10, trouves: "4,22", complet: "42,3 %", combinaisons: 252, cout: "504 €" },
  { n: 12, trouves: "4,60", complet: "65,9 %", combinaisons: 792, cout: "1 584 €" },
  { n: 15, trouves: "4,92", complet: "94,5 %", combinaisons: 3003, cout: "6 006 €" },
];

export default function Body() {
  return (
    <>
      <p>
        Sur les paris à plusieurs chevaux — Tiercé, Quarté+, Quinté+ — la façon de construire le
        ticket compte autant que le choix des chevaux. Et la question « combien de chevaux
        faut-il ? » a une réponse chiffrée, pas une réponse d&apos;opinion.
      </p>

      <Sommaire
        items={[
          { id: "ce-que-coute-la-couverture-mesure", label: "Ce que coûte la couverture, mesuré" },
          { id: "la-base-la-ou-le-jugement-remplace-la-co", label: "La base : là où le jugement remplace la couverture" },
          { id: "champ-total-champ-reduit-flexi", label: "Champ total, champ réduit, Flexi" },
          { id: "la-regle-d-or", label: "La règle d'or" },
        ]}
      />

      <H2 id="ce-que-coute-la-couverture-mesure">Ce que coûte la couverture, mesuré</H2>
      <p>
        Le tableau ci-dessous part du ticket le plus simple qui soit : prendre les N premiers
        chevaux du marché — les N cotes les plus basses au départ — et jouer toutes les
        combinaisons de cinq qu&apos;on peut en tirer. Mesuré sur les{" "}
        <strong>381 Quinté+</strong> que porte la base, de septembre 2025 à septembre 2026.
      </p>
      <div className="overflow-x-auto">
        <table>
          <caption className="sr-only">
            Couverture d&apos;une arrivée de Quinté+ et coût du ticket selon le nombre de chevaux
            retenus
          </caption>
          <thead>
            <tr>
              <th>Chevaux retenus</th>
              <th>Chevaux trouvés sur 5</th>
              <th>Arrivée complète</th>
              <th>Combinaisons</th>
              <th>Coût</th>
            </tr>
          </thead>
          <tbody>
            {COUVERTURE.map((c) => (
              <tr key={c.n}>
                <td>
                  <strong>{c.n} premiers du marché</strong>
                </td>
                <td>{c.trouves}</td>
                <td>{c.complet}</td>
                <td>{c.combinaisons.toLocaleString("fr-FR")}</td>
                <td>{c.cout}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>
        Deux enseignements, et ils vont dans le même sens. D&apos;abord,{" "}
        <strong>le marché seul ne suffit jamais</strong> : ses cinq favoris ne donnent l&apos;arrivée
        complète que <strong>1,6 %</strong> du temps. Ensuite, la couverture se paie à un rythme
        insoutenable : passer de 8 à 12 chevaux fait grimper la réussite de 18 % à 66 %, mais la
        mise de 112 € à <strong>1 584 €</strong>. À 15 chevaux on couvre presque tout (94,5 %) pour
        6 006 € — soit plus que le rapport médian d&apos;un Quinté+ Désordre, qui est de 232 €.
      </p>
      <p>
        Autrement dit : <strong>élargir n&apos;est pas une stratégie</strong>, c&apos;est une façon
        coûteuse d&apos;acheter de la certitude. Le ticket rentable est celui qui remplace des
        chevaux par du jugement.
      </p>

      <H2 id="la-base-la-ou-le-jugement-remplace-la-co">La base : là où le jugement remplace la couverture</H2>
      <p>
        La <strong>base</strong> regroupe les chevaux présents dans toutes vos combinaisons. Chaque
        cheval passé de « champ » à « base » divise le nombre de tickets — c&apos;est
        arithmétique — mais transfère le risque sur votre conviction : si la base tombe, tout
        tombe. Deux repères mesurés pour la choisir :
      </p>
      <ul>
        <li>
          le favori du marché termine dans les cinq premiers <strong>65,1 %</strong> du temps. Une
          base « favori » n&apos;est pas absurde, mais elle échoue une fois sur trois ;
        </li>
        <li>
          <strong>88,7 %</strong> des arrivées de Quinté+ contiennent au moins un cheval coté 20 ou
          plus. Un ticket composé uniquement de premières cotes est battu neuf fois sur dix.
        </li>
      </ul>
      <p>
        La base se cherche donc parmi les chevaux solides, et le champ doit contenir au moins un
        outsider défendable — pas dix, un. Le détail de ce que rapportent les outsiders est dans{" "}
        <Link href="/blog/favori-ou-outsider">favori ou outsider</Link>.
      </p>

      <H2 id="champ-total-champ-reduit-flexi">Champ total, champ réduit, Flexi</H2>
      <p>
        Le <strong>champ total</strong> génère toutes les combinaisons entre vos chevaux :
        c&apos;est le tableau ci-dessus, et c&apos;est cher. Le <strong>champ réduit</strong>{" "}
        n&apos;en retient qu&apos;une partie — par exemple « ces deux chevaux obligatoirement dans
        les trois premiers » : moins de combinaisons, mise maîtrisée, couverture partielle assumée.
        Le <Link href="/blog/quinte-flexi-strategie">Flexi</Link>, lui, ne réduit pas les
        combinaisons mais le prix de chacune, contre une part proportionnelle du rapport — 50 % de
        la mise, 50 % du gain.
      </p>
      <p>
        Les trois répondent à la même contrainte : vous ne pouvez pas couvrir large et garder une
        espérance. Chaque combinaison ajoutée paie son propre{" "}
        <Link href="/blog/comprendre-les-cotes">prélèvement</Link>.
      </p>

      <H2 id="la-regle-d-or">La règle d&apos;or</H2>
      <p>
        Un bon ticket n&apos;est pas le plus large : c&apos;est celui qui couvre les scénarios{" "}
        <strong>les plus probables ET les mieux payés</strong>. Les chiffres ci-dessus montrent
        pourquoi la première partie ne suffit pas — couvrir 94,5 % des arrivées est à la portée de
        n&apos;importe qui, à 6 006 € le ticket. Concentrez sur la{" "}
        <Link href="/guides/pari-de-valeur">valeur</Link>, et tenez la mise avec une{" "}
        <Link href="/blog/gestion-bankroll-courses">gestion de bankroll</Link> stricte.
      </p>

      <p>
        Détail des types de paris dans le{" "}
        <Link href="/guides/types-de-paris-pmu">guide PMU</Link>, méthode complète dans{" "}
        <Link href="/blog/analyser-quinte-du-jour">analyser le Quinté+ du jour</Link>.{" "}
        <Link href="/quinte-du-jour">Voir le Quinté+ du jour →</Link>
      </p>
      <p className="text-sm">
        Méthode : 381 Quinté+ terminés entre le 1er septembre 2025 et le 21 septembre 2026, dont les cinq
        premières places sont publiées, cote PMU au départ, non-partants exclus. Le coût suppose
        2 € la combinaison, hors Flexi et hors bonus. Les courses sans cote exploitable sont
        écartées, pas corrigées.
      </p>
    </>
  );
}
