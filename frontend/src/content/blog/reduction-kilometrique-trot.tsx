import Link from "next/link";

export const meta = {
  slug: "reduction-kilometrique-trot",
  title: "Réduction kilométrique : décrypter la vitesse au trot",
  description:
    "La réduction kilométrique (le temps au kilomètre) mesure la vitesse d'un trotteur. Comment la lire, la comparer à conditions égales et l'utiliser sans se tromper.",
  date: "2026-06-23",
  updated: "2026-06-23",
  tags: ["Trot", "Réduction kilométrique", "Data"],
  readingMinutes: 4,
};

export default function Body() {
  return (
    <>
      <p>
        Au trot, un chiffre revient sans cesse : la « réduc », ou réduction kilométrique. C&apos;est
        l&apos;indicateur de vitesse de référence — à condition de savoir le lire.
      </p>

      <h2>Ce qu&apos;elle mesure</h2>
      <p>
        La réduction kilométrique est le <strong>temps moyen mis pour parcourir un kilomètre</strong>,
        exprimé en minutes et secondes (par exemple 1&apos;12&quot;). Plus elle est basse, plus le
        cheval a été rapide. C&apos;est une mesure de vitesse intrinsèque, indépendante de la distance
        totale.
      </p>

      <h2>Comparer à conditions égales</h2>
      <p>
        Une réduc ne vaut que comparée à un contexte similaire. Plusieurs facteurs la faussent :
      </p>
      <ul>
        <li><strong>Le type de départ</strong> : autostart (départ lancé) donne des réducs plus rapides que le départ à la volte.</li>
        <li><strong>La distance</strong> : un cheval tient rarement la même réduc sur 2 100 m et sur 2 850 m.</li>
        <li><strong>La piste</strong> : taille, corde, état du terrain influent fortement.</li>
        <li><strong>Le déroulé</strong> : un cheval qui a couru à l&apos;extérieur a « payé » des mètres.</li>
      </ul>

      <h2>L&apos;erreur classique</h2>
      <p>
        Comparer brutalement la meilleure réduc de chaque partant sans tenir compte du contexte mène
        à de mauvaises conclusions. Une excellente réduc sur petite piste en autostart ne vaut pas une
        réduc moyenne sur grande piste à la volte.
      </p>

      <h2>L&apos;utiliser intelligemment</h2>
      <p>
        Croisez la réduc avec la <Link href="/guides/comment-lire-la-musique">musique</Link>, la
        ferrure et le couple driver/entraîneur — voir nos{" "}
        <Link href="/blog/strategies-paris-trot">5 clés pour parier au trot</Link>. BlackTurf intègre
        la réduction kilométrique parmi ses critères, normalisée par conditions.
      </p>

      <p><Link href="/programme">Voir les courses de trot du jour →</Link></p>
    </>
  );
}
