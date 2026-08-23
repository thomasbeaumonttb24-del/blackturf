import Link from "next/link";

export const meta = {
  slug: "tierce-ordre-ou-desordre",
  title: "Tiercé : ordre ou désordre, comment choisir",
  description:
    "Tiercé dans l'ordre ou dans le désordre : différence de rapport et de probabilité, et la stratégie « ordre + désordre ».",
  date: "2026-06-23",
  updated: "2026-06-23",
  tags: ["Tiercé", "PMU", "Stratégie"],
  readingMinutes: 4,
};

export default function Body() {
  return (
    <>
      <p>
        Le Tiercé porte sur les 3 premiers chevaux. Mais un même ticket peut payer très différemment
        selon que vous trouvez l&apos;ordre exact ou non. Voici comment arbitrer.
      </p>

      <h2>Ordre vs désordre : la différence</h2>
      <p>
        Trouver les 3 premiers <strong>dans l&apos;ordre exact</strong> paie le rapport « Ordre »,
        nettement plus élevé. Les trouver <strong>dans le désordre</strong> (les bons chevaux, mauvais
        ordre) paie le rapport « Désordre », plus modeste mais bien plus probable à décrocher.
      </p>

      <h2>Pourquoi l&apos;ordre exact est rare</h2>
      <p>
        Désigner les 3 bons chevaux est déjà difficile ; les classer exactement multiplie la
        difficulté. Statistiquement, viser l&apos;ordre seul, c&apos;est accepter de perdre souvent un
        ticket « presque gagnant ». D&apos;où la stratégie classique.
      </p>

      <h2>La stratégie « ordre + désordre »</h2>
      <p>
        Beaucoup de parieurs jouent le même trio <strong>à la fois en ordre et en désordre</strong>.
        Si l&apos;ordre tombe, vous touchez le gros rapport ; sinon, le désordre vous sauve. Cela
        double la mise mais évite la frustration du « bons chevaux, mauvais ordre ».
      </p>

      <h2>Tiercé ou Trio ?</h2>
      <p>
        Si l&apos;ordre ne vous intéresse pas, le <Link href="/guides/types-de-paris-pmu">Trio</Link>{" "}
        (3 premiers, désordre uniquement, dès 8 partants) est souvent plus simple à appréhender. Le
        choix dépend de votre conviction sur la hiérarchie de tête.
      </p>

      <p>
        Quel que soit le pari, l&apos;essentiel reste de jouer des chevaux à{" "}
        <Link href="/guides/pari-de-valeur">valeur</Link>.{" "}
        <Link href="/programme">Voir le programme du jour →</Link>
      </p>
    </>
  );
}
