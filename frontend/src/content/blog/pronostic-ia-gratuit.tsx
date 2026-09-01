import Link from "next/link";

/**
 * Requête visée : « pronostic IA gratuit », « pronostic hippique gratuit intelligence
 * artificielle », « voir les pronostics sans abonnement ». C'est une intention
 * transactionnelle que ni la page pilier /pronostics-ia (la méthode) ni /track-record
 * (les résultats) ne traitent, et que /tarifs traite en grille de prix, pas en réponse.
 *
 * L'article décrit exactement ce qu'un visiteur non connecté voit, sans le survendre : le
 * nom des chevaux est masqué CÔTÉ SERVEUR dans l'aperçu, la probabilité et la cote juste
 * ne le sont pas. Toute évolution du plan Découverte doit être répercutée ici.
 */
export const meta = {
  slug: "pronostic-ia-gratuit",
  title: "Pronostic hippique par IA gratuit : ce qu'on voit sans payer",
  description:
    "Ce qu'un visiteur non abonné voit d'une analyse par IA : classement, probabilités, cote juste, palmarès complet — et ce qui reste réservé.",
  date: "2026-09-01",
  updated: "2026-09-01",
  tags: ["IA", "Gratuit", "Méthode"],
  readingMinutes: 6,
};

export default function Body() {
  return (
    <>
      <p>
        « Pronostic gratuit » est la promesse la plus répandue du turf en ligne, et la plus
        élastique : elle désigne aussi bien un vrai contenu ouvert qu&apos;un titre d&apos;article
        qui s&apos;arrête sur un formulaire. Autant dire les choses dans l&apos;ordre : voici
        exactement ce qu&apos;un visiteur non connecté peut consulter ici, et ce qui ne
        l&apos;est pas.
      </p>

      <h2>Ce qui est ouvert à tout le monde</h2>
      <p>
        <strong>Le programme complet du jour.</strong> Toutes les réunions, toutes les courses,
        l&apos;heure de départ en heure de Paris, la discipline, la distance, le nombre de partants.
        Rien n&apos;est réservé : le <Link href="/programme">programme PMU</Link> est une page
        publique, y compris ses fiches course.
      </p>
      <p>
        <strong>Les partants et les cotes.</strong> Chaque fiche course publie la liste des
        engagés, leur jockey, leur musique et la cote PMU, non-partants signalés.
      </p>
      <p>
        <strong>Le classement calculé par le modèle, avec ses probabilités.</strong> C&apos;est le
        point que la plupart des sites gardent fermé, et il ne l&apos;est pas ici. Sur une fiche
        course, un visiteur non abonné voit le rang de chaque cheval dans le classement du modèle,
        sa <strong>probabilité de victoire</strong> et la <strong>cote juste</strong> qui en
        découle — c&apos;est-à-dire le prix auquel ce cheval devrait être payé si l&apos;estimation
        est exacte. Ce qui est masqué, c&apos;est <em>le nom et le numéro</em> du cheval qui occupe
        chaque rang.
      </p>
      <p>
        Le choix peut surprendre ; il est délibéré. Les chiffres sont ce qui permet de juger
        l&apos;outil : on peut lire la forme de la distribution, voir si le modèle est tranché ou
        partagé, comparer sa cote juste à la cote affichée. L&apos;identité du cheval, elle, est ce
        qui a une valeur marchande immédiate. Le masquage est appliqué côté serveur — la ligne
        n&apos;est pas floutée en surface, elle ne quitte pas le serveur.
      </p>
      <p>
        <strong>Une course entièrement révélée par jour.</strong> Le compte gratuit ouvre le
        classement complet, noms compris, sur une course quotidienne, et une alerte par jour.
      </p>
      <p>
        <strong>Tous les résultats et tous les rapports.</strong> Les{" "}
        <Link href="/resultats">arrivées officielles</Link> et les rapports PMU sont publiés sans
        restriction, ainsi que les archives des journées passées.
      </p>
      <p>
        <strong>Le palmarès intégral.</strong> C&apos;est la partie qu&apos;un site qui vend des
        pronostics a le plus intérêt à cacher, et c&apos;est la plus utile : le{" "}
        <Link href="/track-record">palmarès</Link> publie le taux de réussite mesuré course après
        course, sa comparaison avec le classement par les cotes, le score de calibration et le
        rendement réel — <strong>y compris quand il est négatif</strong>. Aucune sélection, aucune
        période retirée.
      </p>

      <h2>Ce qui est réservé</h2>
      <p>
        L&apos;abonnement ouvre le nom des chevaux sur davantage de courses, les{" "}
        <Link href="/guides/pari-de-valeur">paris de valeur</Link> en continu, le calculateur de
        mise adossé à un budget et à un profil de risque, les alertes, et le suivi de capital. Le
        détail figure sur la <Link href="/tarifs">page des tarifs</Link>.
      </p>

      <h2>Pourquoi « gratuit » ne devrait jamais être le critère de choix</h2>
      <p>
        Un pronostic gratuit et un pronostic payant ont exactement la même valeur si ni
        l&apos;un ni l&apos;autre n&apos;est vérifiable. La question utile n&apos;est pas le prix,
        c&apos;est la <strong>traçabilité</strong> :
      </p>
      <ul>
        <li>
          la prédiction était-elle publiée <strong>avant</strong> le départ, et horodatée ?
        </li>
        <li>
          combien de courses composent le taux de réussite affiché, et sur quelle période ?
        </li>
        <li>
          les journées perdantes figurent-elles dans l&apos;historique, ou seulement les gagnantes ?
        </li>
        <li>
          la comparaison est-elle faite avec le hasard — ce qui flatte — ou avec le{" "}
          <strong>classement par les cotes</strong>, qui est le vrai adversaire ?
        </li>
      </ul>
      <p>
        Un site qui publie ces quatre éléments donne les moyens de le contredire. C&apos;est le
        seul signal qui vaille, gratuit ou non.
      </p>

      <h2>Le rappel qui va avec</h2>
      <p>
        Aucun modèle, gratuit ou payant, ne rend le pari hippique rentable par principe. Le pari
        mutuel est un jeu à somme négative : environ 20 % des enjeux sont prélevés avant toute
        redistribution, et cet écart doit être comblé avant de parler de gain. Ce qu&apos;une
        analyse par IA peut apporter, c&apos;est une estimation plus juste que celle qu&apos;on
        ferait à l&apos;œil, et le repérage des cotes trop généreuses — pas une promesse.
      </p>
      <p>
        Pour comprendre ce que fait exactement le modèle et sur quelles données il apprend :{" "}
        <Link href="/pronostics-ia">comment fonctionne l&apos;algorithme</Link>. Pour vérifier ce
        qu&apos;il a produit : le <Link href="/track-record">palmarès mesuré</Link>. Pour voir les
        analyses du jour : le <Link href="/programme">programme PMU</Link>.
      </p>
    </>
  );
}
