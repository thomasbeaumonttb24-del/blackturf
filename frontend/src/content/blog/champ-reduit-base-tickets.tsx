import Link from "next/link";

export const meta = {
  slug: "champ-reduit-base-tickets",
  title: "Base et champ réduit : construire ses tickets PMU",
  description:
    "Base, champ total, champ réduit : construire un ticket PMU qui couvre sans exploser la mise. Méthode et exemples chiffrés.",
  date: "2026-06-23",
  updated: "2026-06-23",
  tags: ["Méthode", "Tickets", "PMU"],
  readingMinutes: 5,
};

export default function Body() {
  return (
    <>
      <p>
        Sur les paris à plusieurs chevaux (Tiercé, Quarté+, Quinté+), la façon de construire son
        ticket compte autant que le choix des chevaux. Maîtriser la base et le champ évite de payer
        des combinaisons inutiles.
      </p>

      <h2>La base</h2>
      <p>
        La <strong>base</strong> regroupe les chevaux dont vous êtes le plus sûr — ils figurent dans
        toutes vos combinaisons. Une base solide réduit le nombre de tickets et concentre la mise là
        où vous avez de la conviction.
      </p>

      <h2>Le champ</h2>
      <p>
        Le <strong>champ</strong>, ce sont les chevaux ajoutés autour de la base pour compléter
        l&apos;arrivée. Plus le champ est large, plus vous couvrez de scénarios… et plus le ticket
        coûte cher : le nombre de combinaisons grimpe vite.
      </p>

      <h2>Champ total vs champ réduit</h2>
      <p>
        Le <strong>champ total</strong> génère toutes les combinaisons possibles entre vos chevaux —
        complet mais coûteux. Le <strong>champ réduit</strong> n&apos;en retient qu&apos;une partie
        (par exemple « ces 2 chevaux obligatoirement dans les 3 ») : moins de combinaisons, mise
        maîtrisée, au prix d&apos;une couverture partielle.
      </p>

      <h2>Maîtriser le coût</h2>
      <p>
        Le piège est de gonfler le champ « pour être sûr ». Chaque cheval ajouté multiplie les
        combinaisons et dilue l&apos;<Link href="/guides/pari-de-valeur">espérance</Link> : vous payez
        plus de prélèvement. Le <Link href="/blog/quinte-flexi-strategie">Flexi</Link> peut aider à
        contenir la mise sur les gros champs.
      </p>

      <h2>La règle d&apos;or</h2>
      <p>
        Un bon ticket n&apos;est pas le plus large, c&apos;est celui qui couvre les scénarios{" "}
        <strong>les plus probables et les mieux payés</strong>. Concentrez sur la valeur, pas sur la
        couverture. Associez-le à une <Link href="/blog/gestion-bankroll-courses">gestion de bankroll</Link>{" "}
        rigoureuse.
      </p>

      <p>
        Détail des types de paris dans le{" "}
        <Link href="/guides/types-de-paris-pmu">guide PMU</Link>.{" "}
        <Link href="/programme">Voir le programme du jour →</Link>
      </p>
    </>
  );
}
