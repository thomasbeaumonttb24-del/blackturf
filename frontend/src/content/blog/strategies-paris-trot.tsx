import Link from "next/link";

export const meta = {
  slug: "strategies-paris-trot",
  title: "Parier le trot : 5 clés, et ce que la mesure en dit",
  description:
    "Ferrure, recul, réduction kilométrique, disqualification, drivers : cinq facteurs du trot, confrontés à un an de courses. Le déferrage ne bat pas sa cote.",
  date: "2026-06-23",
  updated: "2026-09-21",
  tags: ["Trot", "Stratégie", "Discipline"],
  readingMinutes: 6,
};

/* Mesuré le 2026-09-21 sur la base BlackTurf : les 8 710 courses de trot terminées des
 * douze derniers mois (7 686 attelé, 1 024 monté), arrivées officielles PMU et cote PMU au
 * départ. Le tableau du déferrage est calculé À COTE COMPARABLE (3 à 10), sans quoi il ne
 * comparerait que des niveaux de chevaux différents. */
const DEFERRAGE = [
  { equipement: "Déferré des quatre pieds", partants: 11737, taux: "15,9 %" },
  { equipement: "Déferré partiel", partants: 3272, taux: "15,9 %" },
  { equipement: "Ferré ou protégé", partants: 4745, taux: "15,7 %" },
];

export default function Body() {
  return (
    <>
      <p>
        Le trot est la discipline la plus jouée du PMU : <strong>8 710 courses</strong> sur les douze
        derniers mois dans la base BlackTurf, dont 7 686 en attelé et 1 024 en monté. Il a ses règles
        propres, et le parier comme du plat mène à l&apos;erreur. Voici cinq facteurs spécifiques —
        et ce que la mesure dit de chacun, y compris quand elle contredit l&apos;usage.
      </p>

      <h2>Le trot est plus « logique » que le plat</h2>
      <p>
        Le favori du marché gagne <strong>36,4 %</strong> des courses d&apos;attelé, contre 32,3 % en
        monté et 31,5 % au plat. Le rapport gagnant médian suit : <strong>4,60 €</strong> pour 1 € en
        attelé, contre 5,50 € au plat. Traduction : en trot, les surprises sont plus rares et paient
        moins. Un gros rapport y demande une vraie raison, pas un coup de dé.
      </p>

      <h2>1. La ferrure — le signal que le marché a déjà lu</h2>
      <p>
        Un cheval déferré gagne en vitesse pure, et le déferrage se lit sur la fiche de chaque
        partant. Reste à savoir s&apos;il se <em>joue</em>. À cote comparable — entre 3 et 10, pour
        comparer des chevaux de même niveau apparent — la réponse mesurée est non :
      </p>
      <div className="overflow-x-auto">
        <table>
          <caption className="sr-only">
            Taux de victoire selon la ferrure, en trot, à cote comparable (3 à 10)
          </caption>
          <thead>
            <tr>
              <th>Ferrure</th>
              <th>Partants</th>
              <th>Taux de victoire</th>
            </tr>
          </thead>
          <tbody>
            {DEFERRAGE.map((d) => (
              <tr key={d.equipement}>
                <td>
                  <strong>{d.equipement}</strong>
                </td>
                <td>{d.partants.toLocaleString("fr-FR")}</td>
                <td>{d.taux}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>
        Deux dixièmes de point d&apos;écart sur près de vingt mille partants : autant dire rien. Le
        déferrage fait bien courir plus vite, mais <strong>tout le monde le voit</strong>, et la cote
        l&apos;a déjà intégré. C&apos;est l&apos;illustration la plus nette de ce qu&apos;est un{" "}
        <Link href="/guides/pari-de-valeur">pari de valeur</Link> : un facteur vrai n&apos;est pas
        pour autant rentable. Ce qui paie, c&apos;est l&apos;information que le marché n&apos;a pas
        encore prise en compte — un déferrage <em>inhabituel</em> pour ce cheval, pas le déferrage en
        soi.
      </p>

      <h2>2. Le recul au départ</h2>
      <p>
        En handicap de distance, certains chevaux partent 25 mètres derrière. Le recul est un
        désavantage réel, d&apos;autant plus lourd que la course est courte : il faut le rattraper
        avant d&apos;avoir à se placer. La question n&apos;est pas « rend-il des mètres ? » mais « sa
        classe compense-t-elle ces mètres, sur CETTE distance ? ».
      </p>

      <h2>3. La réduction kilométrique</h2>
      <p>
        La « réduc » — le temps au kilomètre — mesure la vitesse intrinsèque, à condition de la
        comparer à conditions égales : distance, piste, départ à l&apos;autostart ou à la volte. Une
        excellente réduc récente sur une piste comparable vaut mieux que trois victoires sur petites
        pistes. Le détail du calcul est dans notre{" "}
        <Link href="/blog/reduction-kilometrique-trot">guide de la réduction kilométrique</Link>.
      </p>

      <h2>4. Le risque de disqualification, chiffré</h2>
      <p>
        Au trot, un cheval qui galope est disqualifié — le « Da » de la{" "}
        <Link href="/guides/comment-lire-la-musique">musique</Link>. Ce n&apos;est pas un accident
        rare : sur douze mois, <strong>6,1 % des partants classés en attelé</strong> ont été
        disqualifiés pour allure irrégulière, et <strong>9,3 % en monté</strong> — une ligne sur
        onze. Le monté est nettement plus périlleux, ce qui compte double sur un pari combiné :
        cinq chevaux à faire arriver, c&apos;est cinq occasions de faute.
      </p>
      <p>
        Conséquence pratique : sur un ticket combiné en monté, mieux vaut une base très régulière
        d&apos;allure qu&apos;un cheval plus rapide mais fautif. Un cheval qui multiplie les Da est un
        pari fragile, même quand il est le plus rapide du lot.
      </p>

      <h2>5. Le driver et l&apos;entraînement</h2>
      <p>
        Le couple driver-entraîneur pèse plus qu&apos;au plat, et la spécialité locale y est forte :
        chaque fiche d&apos;<Link href="/hippodromes">hippodrome</Link> publie les cinq drivers et les
        cinq entraîneurs qui y ont le plus gagné sur douze mois. À Vincennes, les trois premiers
        drivers pèsent à eux seuls 28 % des victoires des douze derniers mois. Un driver de pointe qui prend
        un cheval inhabituel reste un indice d&apos;engagement sérieux.
      </p>

      <p>
        Ces facteurs — ferrure, recul, réduc, régularité d&apos;allure, driver — comptent parmi ceux
        que le modèle de BlackTurf pondère, avec la cote du marché comme point de comparaison.{" "}
        <Link href="/disciplines/trot">Les courses de trot du jour</Link> sont analysées une par une,
        et <Link href="/track-record">le palmarès mesuré</Link> publie ce que ces analyses ont donné à
        l&apos;arrivée, pertes comprises.
      </p>
      <p className="text-sm">
        Méthode : courses de trot terminées entre le 21 septembre 2025 et le 21 septembre 2026,
        arrivées officielles PMU, cote PMU au départ, non-partants exclus. Le taux de disqualification
        rapporte les disqualifications pour allure irrégulière au nombre de lignes d&apos;arrivée
        publiées. Le tableau de ferrure ne retient que les partants cotés entre 3 et 10, pour ne pas
        comparer des chevaux de niveaux différents ; les partants dont l&apos;équipement n&apos;est
        pas renseigné sont exclus du tableau, pas corrigés.
      </p>
    </>
  );
}
