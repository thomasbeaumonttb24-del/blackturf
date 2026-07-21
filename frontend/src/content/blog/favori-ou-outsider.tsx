import Link from "next/link";

export const meta = {
  slug: "favori-ou-outsider",
  title: "Favori ou outsider : que faut-il jouer ?",
  description:
    "Faut-il parier le favori ou chercher l'outsider ? Taux de réussite, rentabilité réelle, biais favori-outsider : ce que disent les chiffres pour parier malin au PMU.",
  date: "2026-06-23",
  updated: "2026-06-23",
  tags: ["Stratégie", "Favori", "Outsider"],
  readingMinutes: 4,
};

export default function Body() {
  return (
    <>
      <p>
        Éternel débat du turfiste : sécuriser avec le favori, ou viser le gros rapport de
        l&apos;outsider ? La bonne réponse n&apos;est ni l&apos;un ni l&apos;autre par principe —
        c&apos;est une question de <Link href="/guides/pari-de-valeur">valeur</Link>.
      </p>

      <h2>Le favori gagne souvent… et rapporte peu</h2>
      <p>
        Le favori s&apos;impose dans environ un tiers des courses : c&apos;est le choix le plus
        « sûr ». Mais tout le monde le sait, donc sa cote est basse et son espérance faible. Jouer
        systématiquement les favoris, c&apos;est perdre lentement le{" "}
        <Link href="/blog/comprendre-les-cotes">prélèvement PMU</Link>.
      </p>

      <h2>Le biais favori-outsider</h2>
      <p>
        Les études de marché montrent un biais connu : les parieurs <strong>sur-misent les très
        gros outsiders</strong> (l&apos;attrait du jackpot) et <strong>sous-estiment légèrement les
        favoris solides</strong>. Conséquence : les cotes extrêmes (40, 60, 100) sont presque
        toujours de mauvais paris, tandis que la zone intermédiaire recèle plus de valeur.
      </p>

      <h2>La vraie question : où est l&apos;écart ?</h2>
      <p>
        Un favori à 2,0 dont la probabilité réelle est 60 % est un excellent pari (espérance
        positive). Un outsider à 12,0 dont la probabilité réelle est 5 % est un piège. Ce n&apos;est
        pas le statut (favori/outsider) qui compte, mais l&apos;<strong>écart entre probabilité réelle
        et cote</strong>.
      </p>

      <h2>En pratique</h2>
      <p>
        Cherchez la valeur dans la fourchette de cotes moyennes (souvent 4 à 20), évitez les cotes
        extrêmes, et ne jouez le favori que lorsqu&apos;il est réellement sous-coté. C&apos;est
        exactement ce que calcule BlackTurf, course par course.{" "}
        <Link href="/programme">Voir les paris de valeur du jour →</Link>
      </p>
    </>
  );
}
