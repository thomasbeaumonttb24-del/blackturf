import Link from "next/link";

export const meta = {
  slug: "couple-gagnant-ou-place",
  title: "Couplé gagnant ou couplé placé : lequel choisir ?",
  description:
    "Mesuré sur 16 964 courses : le gagnant paie 2,7 fois le placé, alors qu'il est 3 fois plus dur. Ce que ça change selon la course.",
  date: "2026-06-23",
  updated: "2026-09-01",
  tags: ["Couplé", "PMU", "Bases"],
  readingMinutes: 5,
};

export default function Body() {
  return (
    <>
      <p>
        Le Couplé se joue sur deux chevaux, mais sous deux formes très différentes. Choisir entre
        gagnant et placé change radicalement vos chances — et votre rapport.
      </p>

      <h2>Couplé gagnant</h2>
      <p>
        Vos 2 chevaux doivent finir <strong>1er et 2e</strong>, dans n&apos;importe quel ordre.
        Difficile, donc bien payé. C&apos;est un pari de conviction : vous pensez tenir les deux
        meilleurs de la course.
      </p>

      <h2>Couplé placé</h2>
      <p>
        Vos 2 chevaux doivent figurer <strong>parmi les places payées</strong>. À partir de 8
        partants, cela signifie 2 chevaux dans le top 3 — bien plus accessible, donc moins rémunérateur.
        En dessous de 8 partants, le Couplé Placé n&apos;est généralement pas proposé.
      </p>

      <h2>Combien le gagnant paie-t-il de plus&nbsp;?</h2>
      <p>
        Là encore, la mesure tranche mieux que l&apos;intuition. Sur{" "}
        <strong>16 964 courses</strong> dont nous avons relevé les deux rapports officiels
        du PMU&nbsp;:
      </p>
      <ul>
        <li>Couplé <strong>Gagnant</strong> médian&nbsp;: <strong>20,00&nbsp;€</strong> pour 1&nbsp;€ ;</li>
        <li>Couplé <strong>Placé</strong> médian&nbsp;: <strong>7,30&nbsp;€</strong> pour 1&nbsp;€ ;</li>
        <li>
          soit un facteur médian de <strong>2,7</strong> — et il ne bouge pas d&apos;un
          pouce selon la taille du champ&nbsp;: ×2,7 à 9 partants ou moins, ×2,7 entre
          10 et 13, ×2,7 au-delà de 14.
        </li>
      </ul>

      <h2>Or le gagnant est trois fois plus difficile</h2>
      <p>
        Deux chevaux donnés ont exactement <strong>trois fois plus de chances</strong> de
        figurer tous les deux dans le top 3 que dans le top 2. C&apos;est une simple
        affaire de combinaisons&nbsp;: il y a 3 paires possibles dans un trio de tête
        contre une seule dans un duo.
      </p>
      <p>
        Le rapport, lui, n&apos;est que de 2,7. Le supplément payé par le Gagnant{" "}
        <strong>ne couvre donc pas tout à fait le surcroît de difficulté</strong>, et
        l&apos;écart penche légèrement du côté du Placé. Deux précautions avant d&apos;en
        faire une règle&nbsp;: ce sont des médianes, pas des espérances de gain, et
        l&apos;écart — 10&nbsp;% environ — reste petit devant le prélèvement du PMU,
        qui est le même sur les deux formules. Autrement dit&nbsp;: aucune des deux
        n&apos;est une martingale, mais le Placé ne mérite pas sa réputation de pari
        au rabais.
      </p>

      <h2>Lequel choisir ?</h2>
      <ul>
        <li><strong>Course ouverte, beaucoup de partants</strong> : le placé sécurise, le rapport reste correct grâce à l&apos;incertitude.</li>
        <li><strong>Deux chevaux nettement au-dessus</strong> : le gagnant maximise le rapport.</li>
        <li><strong>Un favori + un outsider</strong> : le placé est souvent le meilleur compromis risque/rapport.</li>
      </ul>

      <h2>Rappel sur les places</h2>
      <p>
        4 à 7 partants = 2 places payées ; 8 partants et plus = 3 places. Cette règle, détaillée dans
        notre <Link href="/guides/types-de-paris-pmu">guide des paris PMU</Link>, conditionne tout le
        Couplé Placé.
      </p>

      <p>
        Comme toujours, cherchez la <Link href="/guides/pari-de-valeur">valeur</Link> avant le statut.{" "}
        <Link href="/programme">Voir le programme du jour →</Link>
      </p>
    </>
  );
}
