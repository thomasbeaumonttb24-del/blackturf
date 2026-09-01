import Link from "next/link";

export const meta = {
  slug: "tierce-ordre-ou-desordre",
  title: "Tiercé ordre ou désordre : lequel rapporte le plus ?",
  description:
    "Mesuré sur 300 courses : l'ordre exact paie 6,1 fois le désordre — soit très exactement le rapport des chances. Ce que ça change pour votre ticket.",
  date: "2026-06-23",
  updated: "2026-09-01",
  tags: ["Tiercé", "PMU", "Stratégie"],
  readingMinutes: 6,
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

      <h2>Combien l&apos;ordre paie-t-il vraiment de plus&nbsp;?</h2>
      <p>
        La question se tranche par la mesure, pas par l&apos;intuition. Sur{" "}
        <strong>300 Tiercés</strong> dont nous avons relevé les deux rapports officiels
        du PMU&nbsp;:
      </p>
      <ul>
        <li>rapport <strong>Ordre</strong> médian&nbsp;: <strong>401,30&nbsp;€</strong> pour 1&nbsp;€ ;</li>
        <li>rapport <strong>Désordre</strong> médian&nbsp;: <strong>64,90&nbsp;€</strong> pour 1&nbsp;€ ;</li>
        <li>
          soit un facteur médian de <strong>6,1</strong>, remarquablement stable&nbsp;:
          la moitié des courses tombe entre ×5,8 et ×6,6, et l&apos;écart ne dépasse
          ×10 que dans 1&nbsp;% des cas.
        </li>
      </ul>

      <h2>Pourquoi 6, et pourquoi ça change tout</h2>
      <p>
        Ce 6 n&apos;est pas un hasard. Trois chevaux se rangent de{" "}
        <strong>3 × 2 × 1 = 6 façons</strong> différentes&nbsp;: trouver les bons dans
        n&apos;importe quel ordre est donc exactement <strong>six fois plus probable</strong>{" "}
        que de tomber sur l&apos;ordre exact.
      </p>
      <p>
        Le rapport mesuré, ×6,1, colle à ce ×6 théorique. Autrement dit&nbsp;:{" "}
        <strong>
          l&apos;ordre ne paie pas mieux que ce qu&apos;il coûte en probabilité
        </strong>
        . Ce n&apos;est pas une bonne affaire cachée, ni un piège. Sur la durée,
        les deux formules reviennent au même une fois le prélèvement du PMU appliqué&nbsp;;
        ce qui change, c&apos;est la <strong>régularité</strong>&nbsp;: le désordre paie
        six fois plus souvent, six fois moins gros.
      </p>
      <p>
        Le choix n&apos;est donc pas «&nbsp;lequel rapporte le plus&nbsp;» mais «&nbsp;quelle
        irrégularité j&apos;accepte&nbsp;». Si encaisser rarement vous fait décrocher,
        le désordre est fait pour vous.
      </p>

      <h2>La stratégie « ordre + désordre »</h2>
      <p>
        Beaucoup de parieurs jouent le même trio <strong>à la fois en ordre et en désordre</strong>.
        Si l&apos;ordre tombe, vous touchez le gros rapport ; sinon, le désordre vous sauve. Cela
        double la mise mais évite la frustration du « bons chevaux, mauvais ordre ».
      </p>

      <h2>Et au Quinté+, ce ×6 devient quoi ?</h2>
      <p>
        La régularité vue ici est propre au Tiercé. Au Quinté+, cinq chevaux se rangent de 120
        façons, mais le rapport ne suit pas : mesuré sur 249 courses, le facteur médian est de
        <strong> ×72,8</strong>, et il descend <strong>sous ×10 dans 29 % des Quintés</strong> —
        précisément ceux qui paient le plus gros. Deuxième différence, moins connue : au Tiercé
        l&apos;ordre est une formule qu&apos;on choisit, au Quinté+ c&apos;est un bonus
        automatique qui ne coûte rien de plus.{" "}
        <Link href="/blog/quinte-ordre-ou-desordre">
          Le détail chiffré, Quinté par Quinté
        </Link>
        .
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
