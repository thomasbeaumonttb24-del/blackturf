import Link from "next/link";

export const meta = {
  slug: "comprendre-les-cotes",
  title: "Cotes hippiques : tout comprendre",
  description:
    "Cote PMU, probabilité implicite, cote de référence et cote finale : comment lire les cotes hippiques, ce qu'elles disent vraiment et comment elles bougent jusqu'au départ.",
  date: "2026-06-23",
  updated: "2026-06-23",
  tags: ["Cotes", "PMU", "Bases"],
  readingMinutes: 4,
};

export default function Body() {
  return (
    <>
      <p>
        La cote est l&apos;information la plus regardée — et la plus mal comprise. Elle ne dit pas
        « ce cheval va gagner » : elle reflète l&apos;argent que les parieurs ont misé sur lui. La
        comprendre, c&apos;est comprendre le marché.
      </p>

      <h2>Cote et probabilité implicite</h2>
      <p>
        Au PMU (pari mutuel), la cote dépend de la répartition des mises. Règle simple :{" "}
        <strong>probabilité implicite ≈ 1 / cote</strong>. Un cheval à 5,0 « vaut » environ 20 % de
        chances aux yeux du marché. C&apos;est cette probabilité-là que vous devez comparer à votre
        propre estimation pour détecter un{" "}
        <Link href="/guides/pari-de-valeur">pari de valeur</Link>.
      </p>

      <h2>Pari mutuel ≠ cote fixe</h2>
      <p>
        Contrairement aux bookmakers à cote fixe, la cote PMU n&apos;est définitive qu&apos;au
        départ. Elle bouge en continu selon les mises. La cote affichée avant la course est donc une
        estimation : c&apos;est la <em>cote finale</em> qui détermine votre gain.
      </p>

      <h2>Le prélèvement, ce mur invisible</h2>
      <p>
        Le PMU prélève 15 à 30 % des enjeux selon le type de pari. Mécaniquement, la somme des
        probabilités implicites dépasse 100 % : le marché est « surcoté » de ce prélèvement. C&apos;est
        pourquoi suivre aveuglément les favoris fait perdre sur la durée — vous payez la marge sans
        avantage.
      </p>

      <h2>Lire le mouvement des cotes</h2>
      <p>
        Une cote qui se raccourcit fortement signale un afflux d&apos;argent (« le cheval est joué »).
        Une dérive à la hausse, l&apos;inverse. Ces mouvements sont un signal — pas une vérité : le
        marché se trompe régulièrement, et c&apos;est précisément là que se trouve la valeur.
      </p>

      <p>
        BlackTurf suit la cote PMU en direct et la recalcule contre sa propre probabilité jusqu&apos;à
        l&apos;approche du départ.{" "}
        <Link href="/programme">Voir les cotes en direct du jour →</Link>
      </p>
    </>
  );
}
