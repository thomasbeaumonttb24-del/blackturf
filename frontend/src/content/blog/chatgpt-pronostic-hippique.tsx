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
 * Cet article existe pour une requête que le site ne captait pas du tout : « ChatGPT
 * pronostic hippique », et toutes ses variantes (« demander à une IA de pronostiquer »,
 * « quelle IA pour les courses »). C'est le point d'entrée le plus fréquent dans le sujet
 * pour quelqu'un qui n'a jamais entendu parler de modèles de classement.
 *
 * Il ne recouvre pas /blog/ia-pronostics-hippiques, qui traite d'une autre question — « le
 * machine learning peut-il battre les courses ? » —, ni la page pilier /pronostics-ia, qui
 * décrit une méthode. Ici, la question est : que se passe-t-il concrètement quand on tape
 * la demande dans un agent conversationnel.
 *
 * Chiffres relevés le 2026-09-21 sur `/api/v1/stats/track-record`, endpoint public qui
 * sert aussi la page /track-record. Ils décrivent la cohorte mesurée depuis le 2026-06-06.
 * Les remplacer en bloc lors d'une mise à jour — jamais à la main, jamais partiellement.
 */
export const meta = {
  slug: "chatgpt-pronostic-hippique",
  title: "Peut-on demander ses pronostics hippiques à ChatGPT ?",
  description:
    "Ce que produit un agent conversationnel à qui on demande un pronostic PMU, et ce que 5 398 courses mesurées disent de la valeur de sa réponse.",
  date: "2026-09-01",
  updated: "2026-09-21",
  tags: ["IA", "ChatGPT", "Méthode"],
  readingMinutes: 10,
};

const MESURE = {
  courses: "5 398",
  depuis: "6 juin 2026",
  iaTop1: 27.6,
  iaTop3: 60.8,
  hasardTop1: 9.8,
  hasardTop3: 29.4,
  brier: "0,190",
  partantsMoyen: "11,2",
  // Cohorte de comparaison : les 5 221 courses où le classement du marché et celui du
  // modèle portent sur les mêmes partants.
  cohorte: "5 221",
  marcheTop1: 29.0,
  marcheTop3: 62.2,
  iaTop1Cohorte: 28.8,
  iaTop3Cohorte: 61.8,
  roiMarche: -17.85,
  roiIa: -12.38,
  clvN: "5 456",
  clvPct: 58.2,
  clvMediane: "+22,2 %",
};

export default function Body() {
  return (
    <>
      <Chapo>
        Un modèle de langage répond toujours. Demandez-lui le quinté, il vous rendra cinq numéros,
        des noms, une justification qui se tient — et rien, dans le texte, n&apos;indiquera s&apos;il
        a raisonné ou s&apos;il a inventé. La vraie question n&apos;est pas « sait-il répondre ? »
        mais « que vaut sa réponse ? ». Elle se tranche par la mesure.
      </Chapo>

      <Chiffres
        items={[
          { valeur: MESURE.courses, libelle: "courses notées", detail: `depuis le ${MESURE.depuis}` },
          {
            valeur: `${String(MESURE.iaTop3).replace(".", ",")} %`,
            libelle: "vainqueur dans le trio annoncé",
            detail: `contre ${String(MESURE.hasardTop3).replace(".", ",")} % au hasard`,
          },
          { valeur: MESURE.brier, libelle: "score de Brier", detail: "plus c'est bas, mieux c'est" },
          {
            valeur: `${String(MESURE.clvPct).replace(".", ",")} %`,
            libelle: "paris pris au-dessus de la cote de clôture",
            detail: `sur ${MESURE.clvN} paris`,
          },
        ]}
        source="Mesures du 21 septembre 2026, publiées en continu sur la page Palmarès. Un agent conversationnel ne publie aucun équivalent, pour une raison de fond expliquée plus bas."
      />

      <Sommaire
        items={[
          { id: "ce-qui-se-passe", label: "Ce qui se passe quand on lui pose la question" },
          { id: "naviguer", label: "Naviguer sur le web ne suffit pas" },
          { id: "deux-familles", label: "Deux familles d'IA qu'on confond" },
          { id: "mesure", label: "Ce que dit la mesure, chiffres à l'appui" },
          { id: "ce-quil-fait-bien", label: "Ce qu'un agent conversationnel fait très bien" },
          { id: "juger", label: "Juger n'importe quel pronostic annoncé « par IA »" },
          { id: "resume", label: "En résumé" },
        ]}
      />

      <H2 id="ce-qui-se-passe">Ce qui se passe quand on lui pose la question</H2>
      <p>
        Un agent conversationnel est entraîné à produire la suite de mots la plus vraisemblable.
        Demandez-lui un pronostic sur une course, et il vous rendra un texte parfaitement formé :
        des numéros, des noms de chevaux, des cotes, un ordre d&apos;arrivée probable, souvent une
        justification qui se tient. Ce texte a l&apos;apparence exacte d&apos;une analyse. Il en a
        rarement le contenu.
      </p>
      <p>Trois manques expliquent l&apos;écart, et aucun n&apos;est un défaut de version :</p>
      <ul>
        <li>
          <strong>Il n&apos;a pas les partants.</strong> La composition définitive d&apos;une course
          n&apos;est arrêtée que la veille, et les non-partants tombent parfois dans l&apos;heure qui
          précède le départ. Sans accès en direct au programme officiel, le modèle reconstitue de
          mémoire — c&apos;est-à-dire qu&apos;il invente des chevaux plausibles.
        </li>
        <li>
          <strong>Il n&apos;a pas les cotes.</strong> Or la cote est l&apos;information centrale :
          elle dit ce que le marché pense déjà. Un pronostic qui l&apos;ignore ne peut pas, par
          construction, repérer un cheval sous-évalué — il peut seulement désigner un cheval.
        </li>
        <li>
          <strong>Il ne mesure pas son erreur.</strong> Un agent conversationnel ne conserve aucune
          trace de ses prédictions passées et n&apos;est jamais noté sur elles. Il ne peut donc pas
          vous dire à quelle fréquence il a eu raison, et vous non plus.
        </li>
      </ul>

      <Encadre titre="Le point qui décide" ton="cle">
        <p>
          Un pronostic sans historique vérifiable n&apos;est pas une prédiction, c&apos;est une
          opinion. Elle peut être juste un jour et fausse le lendemain sans que rien, dans le texte,
          ne permette de faire la différence — et c&apos;est exactement ce qui la rend coûteuse :
          vous ne pouvez pas savoir quand cesser de la suivre.
        </p>
      </Encadre>

      <H2 id="naviguer">Naviguer sur le web ne suffit pas</H2>
      <p>
        Les agents récents savent consulter des pages en direct, ce qui règle une partie du
        problème : ils peuvent lire le programme et relever des cotes. Mais lire une donnée et
        l&apos;exploiter sont deux choses distinctes. Estimer la probabilité de victoire d&apos;un
        cheval suppose de peser des dizaines de variables les unes contre les autres — forme
        récente, distance, terrain, couple jockey-entraîneur, mouvements de cote — avec des{" "}
        <strong>poids appris sur des dizaines de milliers de courses réelles</strong>. Ces poids
        n&apos;existent nulle part dans un modèle de langage ; ils s&apos;obtiennent en entraînant un
        modèle sur des résultats passés, puis en vérifiant qu&apos;il ne s&apos;est pas trompé.
      </p>
      <p>
        Un exemple rend la différence concrète. Sur les courses de trot, le déferrage passe pour le
        signal qui fait gagner. Mesuré à cote comparable sur un an, il ne change{" "}
        <strong>rien</strong> :{" "}
        <Link href="/blog/strategies-paris-trot">15,9 % de victoires pour les déferrés des quatre
        pieds contre 15,7 % pour les ferrés</Link>. Un agent conversationnel reprendra la croyance,
        parce qu&apos;elle est écrite partout ; un modèle entraîné sur les arrivées l&apos;aura
        corrigée tout seul, parce que les résultats ne la confirment pas.
      </p>
      <p>
        Autrement dit : la lecture de la page apporte les faits, pas le jugement. L&apos;agent
        continue de produire une synthèse littéraire de ce qu&apos;il a lu, et la met en forme avec
        l&apos;assurance qui caractérise ce type d&apos;outil.
      </p>

      <H2 id="deux-familles">Deux familles d&apos;IA qu&apos;on confond</H2>
      <p>
        Le mot « IA » recouvre des objets très différents. D&apos;un côté les{" "}
        <strong>modèles de langage</strong>, entraînés à écrire et évalués sur la qualité du texte.
        De l&apos;autre les <strong>modèles de prédiction supervisés</strong>, entraînés sur des
        données tabulaires et des résultats connus, évalués sur l&apos;écart entre ce qu&apos;ils ont
        annoncé et ce qui est arrivé.
      </p>

      <Comparatif
        titre="Ce qui sépare les deux outils, ligne par ligne"
        colonnes={["Agent conversationnel", "Modèle de prédiction"]}
        lignes={[
          {
            critere: "Entraîné sur",
            a: "des textes, pour produire la suite de mots la plus vraisemblable",
            b: "des courses passées, avec leur arrivée officielle comme correction",
          },
          {
            critere: "Évalué sur",
            a: "la qualité de la rédaction",
            b: "l'écart entre la probabilité annoncée et ce qui s'est produit",
          },
          {
            critere: "Accès aux partants du jour",
            a: "aucun, sauf s'il consulte la page — et il la lit, il ne la pèse pas",
            b: "le programme officiel, non-partants compris, jusqu'au départ",
          },
          {
            critere: "Usage de la cote",
            a: "décorative : elle est citée, pas comparée",
            b: "point de comparaison central : la valeur est l'écart à la cote",
          },
          {
            critere: "Historique vérifiable",
            a: "aucun : rien n'est conservé, rien n'est noté",
            b: (
              <>
                chaque pronostic horodaté avant le départ, puis noté —{" "}
                <Link href="/track-record">Nos performances</Link>
              </>
            ),
          },
          {
            critere: "Se trompe en disant",
            a: "« ce cheval a tout pour lui aujourd'hui »",
            b: "« ce cheval a 18 % de chances » — et on peut vérifier la fréquence",
          },
        ]}
      />

      <p>
        Le pronostic hippique relève de la seconde famille. On y mesure une{" "}
        <Link href="/pronostics-ia">calibration</Link> — quand le modèle annonce 20 % de chances, le
        cheval doit gagner environ une fois sur cinq — et non une aisance rédactionnelle. Un modèle
        bien calibré peut d&apos;ailleurs être ennuyeux à lire : il n&apos;a pas d&apos;avis, il a
        une distribution.
      </p>

      <H2 id="mesure">Ce que dit la mesure, chiffres à l&apos;appui</H2>
      <p>
        Puisque tout l&apos;argument porte sur la vérifiabilité, voici les chiffres du modèle de
        BlackTurf, tels qu&apos;ils sont publiés — un agent conversationnel, lui, n&apos;a rien à
        opposer, ce qui est précisément le sujet. Sur <strong>{MESURE.courses} courses</strong>{" "}
        notées depuis le {MESURE.depuis}, pour des pelotons de {MESURE.partantsMoyen} partants en
        moyenne :
      </p>

      <Barres
        titre="Le vainqueur figure-t-il dans les trois chevaux annoncés ?"
        legende="Part des courses où le gagnant fait partie du trio de tête du classement. Le hasard sert de plancher, le marché de juge de paix."
        barres={[
          { label: "Tirage au hasard", valeur: MESURE.hasardTop3 },
          { label: "Modèle BlackTurf", valeur: MESURE.iaTop3Cohorte, accent: true },
          { label: "Classement par les cotes", valeur: MESURE.marcheTop3 },
        ]}
        max={70}
        source={`Cohorte commune de ${MESURE.cohorte} courses, mêmes partants pour les deux classements. Mesure du 21 septembre 2026.`}
      />

      <p>
        Le premier enseignement est le plus honnête : <strong>le modèle ne bat pas le marché</strong>{" "}
        en précision brute. {String(MESURE.iaTop3Cohorte).replace(".", ",")} % contre{" "}
        {String(MESURE.marcheTop3).replace(".", ",")} % pour le classement par les cotes : il en est
        à un demi-point, ce qui, sur cinq mille courses, veut dire « à égalité ». Tout site qui
        annonce écraser le marché en précision devrait publier cette comparaison-là ; presque aucun
        ne le fait.
      </p>
      <p>
        L&apos;écart ne se joue pas sur la précision, il se joue sur le <strong>prix</strong>. À
        réussite comparable, les chevaux désignés par le modèle sont payés plus cher — et sur un
        pari, c&apos;est le prix qui décide du résultat final :
      </p>

      <Barres
        titre="Perte d'une mise systématique sur le cheval de tête"
        legende="Miser 1 € en Simple Gagnant sur le premier du classement, à chaque course. Toutes les stratégies perdent — c'est le prélèvement PMU. La question est de combien."
        barres={[
          { label: "Premier des cotes", valeur: Math.abs(MESURE.roiMarche), affichage: "−17,9 %" },
          {
            label: "Premier du modèle",
            valeur: Math.abs(MESURE.roiIa),
            affichage: "−12,4 %",
            accent: true,
          },
        ]}
        max={22}
        source="Même cohorte, mêmes courses, même mise. L'écart de 5,5 points vient du rapport encaissé, pas d'un taux de réussite supérieur."
      />

      <p>
        La troisième mesure est la plus difficile à obtenir par chance, et c&apos;est celle que
        regardent les professionnels : la <strong>valeur à la clôture</strong>. Elle compare la cote
        au moment du pari à la cote finale, une fois que tout le monde a misé.{" "}
        <strong>{String(MESURE.clvPct).replace(".", ",")} %</strong> des {MESURE.clvN} paris pris
        l&apos;ont été à une cote supérieure à la clôture, avec un écart médian de{" "}
        {MESURE.clvMediane}. Traduction : le modèle a vu avant le marché, et assez souvent pour que
        ce ne soit pas du bruit.
      </p>

      <Encadre titre="Ce que ces chiffres ne disent pas" ton="garde">
        <p>
          Aucun de ces résultats ne promet un gain. Une mise systématique sur le cheval de tête perd
          encore 12,4 % : le prélèvement PMU reste supérieur à l&apos;avantage mesuré. Ces chiffres
          disent une chose, et une seule — le classement est meilleur que le hasard, à parité avec le
          marché, et mieux payé que lui. Ce qui se joue ensuite relève de la{" "}
          <Link href="/blog/gestion-bankroll-courses">sélection et de la mise</Link>, pas du modèle.
        </p>
      </Encadre>

      <H2 id="ce-quil-fait-bien">Ce qu&apos;un agent conversationnel fait très bien pour un parieur</H2>
      <p>
        Écarter l&apos;usage « donne-moi le quinté » ne veut pas dire écarter l&apos;outil. Sur tout
        ce qui relève de la compréhension et de l&apos;explication, il est excellent :
      </p>
      <ul>
        <li>
          expliquer un règlement ou une formule de pari — même si un{" "}
          <Link href="/guides/types-de-paris-pmu">guide des types de paris PMU</Link> vérifié reste
          plus sûr sur les conditions de gain exactes ;
        </li>
        <li>
          décoder un vocabulaire technique : la{" "}
          <Link href="/blog/reduction-kilometrique-trot">réduction kilométrique</Link>, un handicap,
          un déferrage ;
        </li>
        <li>
          faire une arithmétique de ticket : combien de combinaisons pour huit chevaux, ce que coûte
          un <Link href="/blog/champ-reduit-base-tickets">champ réduit</Link>, ce que change un
          Flexi ;
        </li>
        <li>
          reformuler une méthode de{" "}
          <Link href="/blog/gestion-bankroll-courses">gestion de capital</Link> et l&apos;appliquer à
          votre bankroll ;
        </li>
        <li>
          résumer une analyse déjà produite ailleurs, ou vous aider à comprendre pourquoi un modèle a
          classé un cheval devant un autre.
        </li>
      </ul>
      <p>
        La ligne de partage tient en deux verbes : demandez-lui d&apos;<strong>expliquer</strong>,
        pas de <strong>prédire</strong>. Le premier usage s&apos;appuie sur ce qu&apos;il sait
        vraiment faire — reformuler des connaissances stables. Le second lui demande une chose
        qu&apos;il n&apos;a aucun moyen de produire : une probabilité vérifiée.
      </p>

      <H2 id="juger">Juger n&apos;importe quel pronostic annoncé « par IA »</H2>
      <p>
        La méthode vaut pour un agent conversationnel comme pour un site payant. Trois questions
        suffisent à trier :
      </p>
      <ul>
        <li>
          <strong>Sur combien de courses, et depuis quand ?</strong> Un taux de réussite sans
          dénominateur ni période ne se vérifie pas. « 70 % de réussite » sur dix courses choisies
          est un chiffre vide.
        </li>
        <li>
          <strong>Horodaté avant le départ ?</strong> Une prédiction qui n&apos;existait pas avant la
          course n&apos;en est pas une. C&apos;est le point où la quasi-totalité des palmarès
          publiés s&apos;effondre.
        </li>
        <li>
          <strong>Comparé à quoi ?</strong> Le plus souvent esquivé. Se comparer au hasard flatte :
          sur onze partants, un tirage au sort place déjà le gagnant dans un trio{" "}
          {String(MESURE.hasardTop3).replace(".", ",")} % du temps. Le vrai point de comparaison est
          le classement par les cotes — l&apos;opinion agrégée de tous les autres parieurs, qui est
          gratuite et redoutable.
        </li>
      </ul>
      <p>
        Un quatrième critère sépare les sérieux des autres : <strong>publient-ils leurs pertes ?</strong>{" "}
        Un palmarès qui ne montre que des semaines gagnantes a été filtré, et un palmarès filtré ne
        mesure plus rien.
      </p>

      <H2 id="resume">En résumé</H2>
      <p>
        Un agent conversationnel est un excellent professeur et un mauvais pronostiqueur. Il ne
        dispose ni des partants du jour, ni des cotes, ni d&apos;une mesure de sa propre justesse, et
        sa fluidité rend ses erreurs indétectables à la lecture. Le pronostic relève d&apos;un autre
        outil : un modèle entraîné sur l&apos;historique réel des courses, réentraîné quand les
        résultats tombent, et noté sur ce qu&apos;il a annoncé — y compris quand la note est mauvaise.
      </p>

      <Suite href="/track-record" cta="Voir nos performances">
        Tous les chiffres de cet article sortent de la même page, recalculée en continu : réussite,
        calibration, valeur à la clôture, et les périodes perdantes avec le reste.
      </Suite>

      <p>
        La méthode employée ici est détaillée sur{" "}
        <Link href="/pronostics-ia">comment fonctionne l&apos;algorithme</Link>, et les analyses du
        jour sont visibles sur le <Link href="/programme">programme PMU</Link>.
      </p>

      <Methode>
        <p>
          Chiffres relevés le 21 septembre 2026 sur l&apos;endpoint public qui alimente la page
          Palmarès. Cohorte principale : {MESURE.courses} courses notées depuis le {MESURE.depuis},{" "}
          {MESURE.partantsMoyen} partants en moyenne, pronostics horodatés avant le départ.
        </p>
        <p>
          La comparaison avec le marché porte sur {MESURE.cohorte} courses — celles où le classement
          par les cotes et celui du modèle reposent sur exactement les mêmes partants, non-partants
          exclus. Sans cette restriction, les deux classements ne joueraient pas la même course et la
          comparaison n&apos;aurait aucun sens.
        </p>
        <p>
          Le rendement est celui d&apos;une mise de 1 € en Simple Gagnant sur le premier du
          classement, à chaque course, rapport officiel PMU encaissé en cas de victoire. La valeur à
          la clôture compare la cote enregistrée avec le pronostic à la dernière cote publiée avant
          le départ.
        </p>
      </Methode>
    </>
  );
}
