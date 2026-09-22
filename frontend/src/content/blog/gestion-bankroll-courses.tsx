import Link from "next/link";
import {
  Barres,
  Chapo,
  Chiffres,
  Comparatif,
  Encadre,
  H2,
  Methode,
  Sommaire,
  Suite,
} from "@/components/blog/kit";

/**
 * Article de méthode : il ne repose pas sur une mesure nouvelle mais sur de
 * l'arithmétique vérifiable (Kelly, probabilité de ruine, longueur des séries
 * perdantes) appliquée aux fréquences DÉJÀ mesurées sur ce site — taux de réussite du
 * favori, dispersion des rapports du Quinté+.
 *
 * Les longueurs de séries perdantes sont calculées, pas mesurées : pour un pari qui
 * gagne p fois sur cent, la probabilité d'enchaîner n pertes est (1−p)^n. C'est écrit
 * dans le bloc de méthode pour qu'on ne les prenne pas pour un relevé.
 */
export const meta = {
  slug: "gestion-bankroll-courses",
  title: "Gérer son capital aux courses : la méthode bankroll",
  description:
    "Mise fixe, mise proportionnelle, Kelly fractionné : combien miser, et pourquoi dix pertes d'affilée arrivent une fois sur quatre sur les cotes de 5 à 10.",
  date: "2026-06-23",
  updated: "2026-09-22",
  tags: ["Bankroll", "Méthode", "Gestion"],
  readingMinutes: 9,
};

/* Probabilité d'enchaîner N pertes d'affilée, selon le taux de réussite du pari.
 * (1 − p)^n, arrondi au point. Sert à montrer qu'une « mauvaise passe » n'a rien
 * d'anormal — c'est l'arithmétique du jeu, pas un signe que la méthode est cassée. */
const SERIES = [
  { pari: "Favori du marché (gagne 33,7 %)", n: 10, proba: 1.6 },
  { pari: "Cote de 5 à 10 (gagne 12,7 %)", n: 10, proba: 25.7 },
  { pari: "Cote de 10 à 20 (gagne 6,2 %)", n: 20, proba: 27.8 },
  { pari: "Quinté+ à cinq chevaux (gagne 1,6 %)", n: 50, proba: 44.6 },
];

export default function Body() {
  return (
    <>
      <Chapo>
        On parle toujours de pronostics, rarement de mises. C&apos;est une erreur d&apos;ordre de
        grandeur : à avantage égal, deux plans de mise différents donnent l&apos;un un capital qui
        dure, l&apos;autre un compte vidé avant que l&apos;avantage ait eu le temps d&apos;exister.
      </Chapo>

      <Chiffres
        items={[
          { valeur: "1 à 3 %", libelle: "de la bankroll par pari", detail: "l'ordre de grandeur prudent" },
          { valeur: "¼ Kelly", libelle: "fraction raisonnable", detail: "le plein Kelly est trop violent" },
          { valeur: "26 %", libelle: "de chances d'enchaîner 10 pertes", detail: "sur un pari qui gagne 12,7 %" },
          { valeur: "300+", libelle: "paris avant de juger", detail: "en dessous, c'est du bruit" },
        ]}
      />

      <Sommaire
        items={[
          { id: "capital", label: "Première règle : un capital dédié" },
          { id: "fixe-proportionnelle", label: "Mise fixe ou mise proportionnelle ?" },
          { id: "kelly", label: "Kelly, et pourquoi on le divise" },
          { id: "variance", label: "La variance, en chiffres" },
          { id: "suivi", label: "Tenir un suivi qui ne s'arrange pas" },
          { id: "erreurs", label: "Les quatre erreurs qui ruinent" },
        ]}
      />

      <H2 id="capital">Première règle : un capital dédié</H2>
      <p>
        Définissez une somme que vous pouvez perdre entièrement sans conséquence sur votre vie.
        C&apos;est votre bankroll. Tout se calcule ensuite en <strong>pourcentage de ce
        capital</strong>, jamais en euros décidés au feeling devant une course.
      </p>
      <p>
        Cette règle n&apos;a rien de moral : elle est mathématique. Une mise exprimée en pourcentage
        décroît automatiquement quand le capital baisse, ce qui rend la ruine complète impossible en
        théorie. Une mise en euros fixes, elle, ne s&apos;adapte pas — et c&apos;est toujours la
        dernière série perdante qui coûte le compte.
      </p>

      <H2 id="fixe-proportionnelle">Mise fixe ou mise proportionnelle ?</H2>

      <Comparatif
        titre="Deux façons de calculer la mise"
        colonnes={["Mise fixe", "Mise proportionnelle"]}
        lignes={[
          { critere: "Règle", a: "toujours le même montant, par exemple 5 €", b: "toujours le même pourcentage, par exemple 2 % du capital" },
          { critere: "Quand ça va mal", a: "la mise reste la même : la part du capital engagée augmente", b: "la mise diminue d'elle-même : le capital dure plus longtemps" },
          { critere: "Quand ça va bien", a: "vous n'exploitez pas les gains", b: "la mise grandit avec le capital" },
          { critere: "Ruine complète", a: "possible", b: "impossible en théorie — le capital s'approche de zéro sans l'atteindre" },
          { critere: "Pour qui", a: "débuter, tester une méthode sur peu de paris", b: "jouer régulièrement sur plusieurs mois" },
        ]}
      />

      <H2 id="kelly">Kelly, et pourquoi on le divise</H2>
      <p>
        Le critère de Kelly calcule la fraction du capital à engager en fonction de l&apos;avantage
        réel :
      </p>
      <p>
        <strong>fraction = (probabilité × cote − 1) ÷ (cote − 1)</strong>
      </p>
      <p>
        Un exemple concret. Vous estimez qu&apos;un cheval a 25 % de chances, et sa cote est de 5,0
        — le marché lui en donne donc 20 %. Kelly conseille (0,25 × 5 − 1) ÷ 4 ={" "}
        <strong>6,25 % du capital</strong>. C&apos;est énorme, et c&apos;est exactement pourquoi
        personne de sérieux ne joue le plein Kelly : la formule suppose que votre probabilité est
        juste. Si elle est surestimée de deux points — ce qui n&apos;est rien —, la mise optimale
        s&apos;effondre.
      </p>

      <Encadre titre="La règle pratique" ton="cle">
        <p>
          On joue un <strong>quart de Kelly</strong>, parfois une moitié. Sur l&apos;exemple
          ci-dessus, cela donne 1,6 % du capital au lieu de 6,25 %. Le gain espéré baisse peu, la
          variance baisse beaucoup — et surtout, une erreur d&apos;estimation ne devient plus
          fatale. Si votre avantage n&apos;est pas mesuré mais supposé, restez entre{" "}
          <strong>1 et 3 %</strong> quoi qu&apos;il arrive.
        </p>
      </Encadre>

      <H2 id="variance">La variance, en chiffres</H2>
      <p>
        La raison d&apos;être de tout ce qui précède tient en une ligne : même une méthode qui
        gagne traverse des séries perdantes plus longues qu&apos;on ne l&apos;imagine. Pour un pari
        qui gagne p fois sur cent, la probabilité d&apos;enchaîner n pertes vaut (1 − p)<sup>n</sup>.
        Le résultat n&apos;a rien d&apos;intuitif :
      </p>

      <Barres
        titre="Probabilité de traverser une série perdante, selon le pari"
        legende="Calcul direct à partir des taux de réussite mesurés sur nos douze derniers mois de courses."
        barres={SERIES.map((s) => ({
          label: `${s.pari} — ${s.n} pertes d'affilée`,
          valeur: s.proba,
          accent: s.n === 10 && s.pari.startsWith("Cote de 5"),
        }))}
        max={50}
        source="Taux de réussite issus des mesures publiées dans « favori ou outsider » et « base et champ réduit »."
      />

      <p>
        Lecture : en jouant des chevaux cotés 5 à 10 — la tranche la moins chère du marché —{" "}
        <strong>une série de dix pertes consécutives a une chance sur quatre de se produire</strong>.
        Ce n&apos;est pas de la malchance, c&apos;est le régime normal du jeu. Et sur un Quinté+ à
        cinq chevaux, enchaîner cinquante tickets perdants est plus probable que l&apos;inverse.
      </p>
      <p>
        D&apos;où la règle de dimensionnement : votre capital doit encaisser la plus longue série
        plausible <em>sans</em> vous faire changer de plan. À 2 % de mise, dix pertes coûtent 18 %
        du capital ; à 10 % de mise, elles en coûtent 65 %, et le plan ne tient plus.
      </p>

      <H2 id="suivi">Tenir un suivi qui ne s&apos;arrange pas</H2>
      <p>
        Notez chaque pari : date, course, type, mise, cote obtenue, résultat. Deux colonnes valent
        plus que toutes les autres — la <strong>cote obtenue</strong>, parce qu&apos;elle décide du
        gain, et la <strong>date d&apos;enregistrement</strong>, parce qu&apos;un pari noté après la
        course ne prouve rien.
      </p>
      <p>
        Le seuil de jugement est plus haut qu&apos;on ne croit : sous trois cents paris, un résultat
        ne distingue pas une méthode d&apos;une série de chance. C&apos;est le même principe que
        pour un{" "}
        <Link href="/blog/chatgpt-pronostic-hippique">pronostic annoncé « par IA »</Link> : sans
        dénominateur ni horodatage, un taux de réussite ne veut rien dire. Notre propre{" "}
        <Link href="/track-record">palmarès</Link> est publié sous cette contrainte, périodes
        perdantes comprises.
      </p>

      <H2 id="erreurs">Les quatre erreurs qui ruinent</H2>
      <ul>
        <li>
          <strong>Doubler après une perte.</strong> La martingale transforme une série normale en
          ruine certaine : il suffit d&apos;une série de dix — qui, on vient de le voir, arrive une
          fois sur quatre.
        </li>
        <li>
          <strong>Miser plus quand « on le sent ».</strong> La taille de la mise doit venir de
          l&apos;écart mesuré entre probabilité et cote, jamais d&apos;une impression.
        </li>
        <li>
          <strong>Changer de plan au milieu d&apos;une série.</strong> Un plan de mise ne se juge
          pas sur vingt paris. Le changer en cours de route, c&apos;est n&apos;en avoir aucun.
        </li>
        <li>
          <strong>Chercher le gros rapport pour se refaire.</strong> Les cotes de 20 et plus rendent{" "}
          <strong>−34,5 %</strong> à qui les joue systématiquement — c&apos;est la pire tranche du
          marché, détaillée dans{" "}
          <Link href="/blog/favori-ou-outsider">favori ou outsider</Link>.
        </li>
      </ul>

      <Suite href="/track-record" cta="Voir le palmarès">
        Un plan de mise ne vaut que branché sur un avantage réel. Le nôtre est publié en continu :
        réussite, calibration, valeur à la clôture, et les mois perdants avec le reste.
      </Suite>

      <Methode>
        <p>
          Les probabilités de série perdante sont <strong>calculées</strong>, pas relevées : pour un
          pari qui gagne p fois sur cent, la probabilité d&apos;enchaîner n pertes vaut (1 − p)
          élevé à la puissance n, en supposant les courses indépendantes. Les taux de réussite qui
          alimentent le calcul, eux, sont mesurés sur les douze derniers mois de courses (voir
          « favori ou outsider » pour les cotes, « base et champ réduit » pour le Quinté+).
        </p>
        <p>
          L&apos;exemple de Kelly suppose une probabilité estimée de 25 % contre une cote de 5,0. La
          formule ne dit rien de la justesse de cette estimation : c&apos;est précisément la raison
          pour laquelle on n&apos;en joue qu&apos;une fraction.
        </p>
      </Methode>

      <p className="text-sm text-muted-foreground">
        Le jeu comporte des risques : endettement, isolement, dépendance. Jouez de façon
        responsable. Interdit aux mineurs.
      </p>
    </>
  );
}
