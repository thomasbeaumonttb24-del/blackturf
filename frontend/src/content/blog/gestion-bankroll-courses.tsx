import Link from "next/link";

export const meta = {
  slug: "gestion-bankroll-courses",
  title: "Gérer son capital aux courses : la méthode bankroll",
  description:
    "Mise fixe, mise proportionnelle, critère de Kelly fractionné : comment gérer son capital (bankroll) aux courses pour durer, encaisser la variance et éviter la ruine.",
  date: "2026-06-23",
  updated: "2026-06-23",
  tags: ["Bankroll", "Méthode", "Gestion"],
  readingMinutes: 5,
};

export default function Body() {
  return (
    <>
      <p>
        On parle toujours de pronostics, rarement de mises. C&apos;est une erreur : la gestion du
        capital (la « bankroll ») décide autant de votre résultat que le choix des chevaux. Un bon
        pronostic mal misé perd ; un pronostic moyen bien misé survit.
      </p>

      <h2>Première règle : un capital dédié</h2>
      <p>
        Définissez une somme que vous pouvez perdre entièrement sans impact sur votre vie. C&apos;est
        votre bankroll. Tout se calcule en pourcentage de ce capital — jamais en euros « au feeling ».
      </p>

      <h2>Mise fixe vs mise proportionnelle</h2>
      <p>
        La <strong>mise fixe</strong> (toujours le même montant) est simple et limite la casse. La{" "}
        <strong>mise proportionnelle</strong> (un % de la bankroll courante) s&apos;adapte : elle
        réduit automatiquement quand vous perdez, augmente quand vous gagnez. Plus robuste sur la
        durée.
      </p>

      <h2>Le critère de Kelly (fractionné)</h2>
      <p>
        Kelly calcule la mise optimale selon votre avantage : fraction ≈ (probabilité × cote − 1) /
        (cote − 1). En pratique, le « plein Kelly » est trop violent (grosse variance) — on utilise
        un <strong>Kelly fractionné</strong> (un quart à une moitié) pour lisser. La clé : ne miser
        gros que quand l&apos;<Link href="/guides/pari-de-valeur">espérance</Link> est réellement
        positive.
      </p>

      <h2>Accepter la variance</h2>
      <p>
        Même un edge réel traverse de longues séries perdantes. Les courses paient surtout par
        à-coups (gros rapports rares). Sans capital suffisant pour encaisser ces creux, on fait
        faillite avant que l&apos;avantage ne se matérialise. Comptez en centaines de paris, pas en
        soirées.
      </p>

      <h2>Tenir un suivi honnête</h2>
      <p>
        Notez chaque pari, son type, sa mise et son résultat. Le ROI réel se mesure sur la durée, pas
        sur le dernier coup. BlackTurf intègre un suivi de capital et un plan de mise par profil de
        risque pour automatiser cette discipline.{" "}
        <Link href="/programme">Voir le programme du jour →</Link>
      </p>

      <p className="text-sm text-muted-foreground">
        Le jeu comporte des risques : endettement, dépendance. Jouez de façon responsable.
      </p>
    </>
  );
}
