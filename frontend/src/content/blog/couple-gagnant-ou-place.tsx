import Link from "next/link";

export const meta = {
  slug: "couple-gagnant-ou-place",
  title: "Couplé gagnant ou couplé placé : lequel choisir ?",
  description:
    "Couplé gagnant ou couplé placé : différences de conditions, de rapport et de probabilité, et lequel choisir selon la course.",
  date: "2026-06-23",
  updated: "2026-06-23",
  tags: ["Couplé", "PMU", "Bases"],
  readingMinutes: 3,
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
