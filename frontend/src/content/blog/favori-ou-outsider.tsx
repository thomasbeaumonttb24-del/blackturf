import Link from "next/link";

export const meta = {
  slug: "favori-ou-outsider",
  title: "Favori ou outsider : ce que disent 211 000 partants",
  description:
    "Taux de victoire et rendement par tranche de cote, mesurés sur un an de PMU : le favori gagne 33,7 % des courses, la cote de 20 et plus rend −34,5 %.",
  date: "2026-06-23",
  updated: "2026-09-21",
  tags: ["Stratégie", "Favori", "Outsider"],
  readingMinutes: 6,
};

/* Mesuré le 2026-09-21 sur la base BlackTurf : toutes les courses terminées des douze
 * derniers mois, arrivées officielles PMU, cote PMU au départ, non-partants exclus.
 * 211 116 partants sur 18 992 courses. Le rendement est celui d'une mise de 1 € en Simple
 * Gagnant sur CHAQUE cheval de la tranche : (somme des rapports encaissés − mises) / mises.
 * Refaire la mesure avant de mettre ces chiffres à jour — ne jamais les retoucher à vue. */
const TRANCHES = [
  { cote: "Moins de 2", partants: 3384, taux: "53,2 %", rendement: "−13,2 %" },
  { cote: "2 à 3", partants: 8087, taux: "35,6 %", rendement: "−13,0 %" },
  { cote: "3 à 5", partants: 19773, taux: "22,7 %", rendement: "−11,9 %" },
  { cote: "5 à 10", partants: 41389, taux: "12,7 %", rendement: "−11,0 %" },
  { cote: "10 à 20", partants: 47074, taux: "6,2 %", rendement: "−17,5 %" },
  { cote: "20 et plus", partants: 91409, taux: "1,8 %", rendement: "−34,5 %" },
];

const PELOTONS = [
  { taille: "8 partants ou moins", n: 3853, taux: "40,7 %" },
  { taille: "9 à 12 partants", n: 8362, taux: "34,4 %" },
  { taille: "13 à 16 partants", n: 6294, taux: "28,9 %" },
  { taille: "17 partants et plus", n: 483, taux: "27,1 %" },
];

export default function Body() {
  return (
    <>
      <p>
        Éternel débat du turfiste : sécuriser avec le favori, ou viser le gros rapport de
        l&apos;outsider ? La question se tranche par la mesure, pas par le tempérament. Voici ce
        que donnent les <strong>211 116 partants</strong> des 18 992 courses terminées des douze
        derniers mois dans la base BlackTurf — arrivées officielles, cote PMU au départ,
        non-partants exclus.
      </p>

      <h2>Taux de victoire et rendement, par tranche de cote</h2>
      <p>
        Le rendement de la dernière colonne est celui d&apos;une stratégie aveugle : miser 1 € en
        Simple Gagnant sur <em>chaque</em> cheval de la tranche, toute l&apos;année.
      </p>
      <div className="overflow-x-auto">
        <table>
          <caption className="sr-only">
            Taux de victoire et rendement par tranche de cote PMU sur douze mois
          </caption>
          <thead>
            <tr>
              <th>Cote au départ</th>
              <th>Partants</th>
              <th>Victoires</th>
              <th>Rendement</th>
            </tr>
          </thead>
          <tbody>
            {TRANCHES.map((t) => (
              <tr key={t.cote}>
                <td>
                  <strong>{t.cote}</strong>
                </td>
                <td>{t.partants.toLocaleString("fr-FR")}</td>
                <td>{t.taux}</td>
                <td>{t.rendement}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>Le biais favori-outsider, mesuré chez nous</h2>
      <p>
        Toutes les tranches perdent : c&apos;est le{" "}
        <Link href="/blog/comprendre-les-cotes">prélèvement PMU</Link>, prélevé sur chaque enjeu
        avant redistribution. Mais elles ne perdent pas également. De <strong>moins de 2 à 10</strong>,
        la perte tourne autour de 11 à 13 % — soit à peu près le prélèvement, ni plus ni moins.
        Au-delà, elle s&apos;effondre : <strong>−17,5 %</strong> entre 10 et 20, et{" "}
        <strong>−34,5 %</strong> à partir de 20.
      </p>
      <p>
        C&apos;est le biais favori-outsider, et il est net : les parieurs sur-misent les gros
        outsiders — l&apos;attrait du jackpot — ce qui écrase leur cote sous leur vraie chance. Un
        cheval à 20 et plus gagne <strong>1,8 fois sur cent</strong>. Le marché le paie comme
        s&apos;il gagnait nettement plus souvent.
      </p>
      <p>
        La conclusion pratique va à rebours de l&apos;intuition : ce n&apos;est pas dans les grosses
        cotes que se cache la valeur, c&apos;est là qu&apos;elle est <em>systématiquement</em>{" "}
        absente. Un outsider ne se joue que sur une raison précise, jamais par principe.
      </p>

      <h2>Le favori gagne un tiers des courses — et plus le champ est réduit</h2>
      <p>
        Le favori du marché — le cheval de cote la plus basse au départ — l&apos;emporte dans{" "}
        <strong>33,7 %</strong> des courses. Ce chiffre dépend d&apos;une chose avant tout : le
        nombre de concurrents.
      </p>
      <div className="overflow-x-auto">
        <table>
          <caption className="sr-only">
            Taux de victoire du favori PMU selon la taille du peloton
          </caption>
          <thead>
            <tr>
              <th>Peloton</th>
              <th>Courses</th>
              <th>Le favori gagne</th>
            </tr>
          </thead>
          <tbody>
            {PELOTONS.map((p) => (
              <tr key={p.taille}>
                <td>
                  <strong>{p.taille}</strong>
                </td>
                <td>{p.n.toLocaleString("fr-FR")}</td>
                <td>{p.taux}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>
        Dans un Quinté+, où le peloton est large et le lot relevé, le favori ne gagne plus que{" "}
        <strong>27,5 %</strong> du temps, contre 33,8 % dans les autres courses. C&apos;est
        précisément pour cela que le Quinté+ paie : il est difficile.
      </p>

      <h2>Le deuxième et le troisième de la cote ne sauvent rien</h2>
      <p>
        On lit souvent qu&apos;il vaut mieux jouer le deuxième favori, « moins évident donc mieux
        payé ». La mesure ne le confirme pas : le 2ᵉ de la cote gagne 19,4 % des courses pour un
        rendement de −11,5 %, le 3ᵉ 13,5 % pour −11,7 %, le 4ᵉ 9,5 % pour −15,8 % et le 5ᵉ 6,8 %
        pour −22,6 %. Autrement dit, les quatre premiers du marché se valent à peu près, et tout
        ce qui vient après coûte cher.
      </p>

      <h2>Alors, que faut-il jouer ?</h2>
      <p>
        Ni le favori ni l&apos;outsider par principe : ce qui compte est l&apos;
        <strong>écart entre la probabilité réelle et la cote</strong>. Un favori à 2,0 dont la
        chance réelle est de 60 % est un bon pari ; un outsider à 25 dont la chance réelle est de
        2 % est un mauvais pari, même s&apos;il gagne parfois. C&apos;est la définition du{" "}
        <Link href="/guides/pari-de-valeur">pari de valeur</Link>, et c&apos;est ce que le modèle
        de BlackTurf calcule course par course — une probabilité par cheval, comparée à la cote du
        marché.
      </p>
      <p>
        Les chiffres ci-dessus disent où le marché se trompe en moyenne. Ils ne disent pas quel
        cheval battre aujourd&apos;hui :{" "}
        <Link href="/programme">le programme du jour</Link> porte l&apos;analyse course par
        course, et <Link href="/track-record">le palmarès mesuré</Link> publie ce que ces analyses
        ont donné à l&apos;arrivée, pertes comprises.
      </p>
      <p className="text-sm">
        Méthode : courses terminées du 21 septembre 2025 au 21 septembre 2026, arrivées officielles
        PMU, cote PMU au départ, non-partants exclus. Le favori est le cheval de cote la plus basse
        ; en cas d&apos;égalité, le plus petit numéro. Les 19 078 courses de la période portent une
        arrivée ; 18 992 portent en plus une cote PMU exploitable, et ce sont celles-là qui sont
        mesurées — les 86 autres ne sont pas corrigées, elles sont écartées.
      </p>
    </>
  );
}
