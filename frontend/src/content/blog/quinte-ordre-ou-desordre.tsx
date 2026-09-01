import Link from "next/link";

/**
 * Requête visée : « quinté ordre ou désordre », « rapport quinté dans l'ordre »,
 * « quinté dans l'ordre combien ça rapporte ».
 *
 * Pourquoi cet article et pas un autre : sur 90 jours, le corpus qui produit
 * réellement des impressions sur ce domaine est ENTIÈREMENT composé d'explications de
 * mécanique de pari — /blog/tierce-ordre-ou-desordre à lui seul fait 466 impressions,
 * soit 30 % du site. Le champ « IA » est réel mais minuscule (35 impressions sur 90
 * jours). On réplique donc un motif prouvé sur ce domaine plutôt que d'en deviner un.
 *
 * Anti-cannibalisation avec /blog/tierce-ordre-ou-desordre : pari différent, grappe de
 * requêtes différente, et surtout conclusion OPPOSÉE — au Tiercé le rapport ordre est
 * d'une régularité d'horloge, au Quinté il ne l'est pas du tout. Les deux articles se
 * citent et s'appuient l'un sur l'autre.
 *
 * TOUS les chiffres viennent d'une mesure sur les rapports officiels PMU en base
 * (249 Quintés du 2025-09-01 au 2026-09-01, table `resultats.rapports_detail`), et la
 * méthode a été validée en reproduisant d'abord le ×6,1 déjà publié sur le Tiercé.
 * Ne jamais les retoucher sans refaire la mesure.
 */
export const meta = {
  slug: "quinte-ordre-ou-desordre",
  title: "Quinté+ dans l'ordre : combien ça rapporte vraiment ?",
  description:
    "Mesuré sur 249 Quintés : l'ordre exact paie 72 fois le désordre en médiane, mais moins de 10 fois dans 29 % des courses — et jamais au-delà de 120.",
  date: "2026-09-01",
  updated: "2026-09-01",
  tags: ["Quinté+", "PMU", "Rapports"],
  readingMinutes: 7,
};

export default function Body() {
  return (
    <>
      <p>
        Trouver les cinq premiers d&apos;un Quinté+ <strong>dans l&apos;ordre exact</strong>, c&apos;est
        l&apos;image d&apos;Épinal du turf : le ticket qui change une vie. La question que personne ne
        pose est de savoir combien cet ordre exact rapporte <em>de plus</em> que le même ticket dans
        le désordre. Nous avons relevé les deux rapports officiels du PMU sur{" "}
        <strong>249 Quintés courus entre le 1<sup>er</sup> septembre 2025 et le 1<sup>er</sup> septembre
        2026</strong>. La réponse est beaucoup moins flatteuse qu&apos;on ne l&apos;imagine.
      </p>

      <h2>D&apos;abord, une précision : l&apos;ordre ne se joue pas</h2>
      <p>
        Contrairement à ce que beaucoup croient, « Quinté dans l&apos;ordre » n&apos;est pas un pari
        distinct qu&apos;on choisirait au guichet. Vous jouez cinq chevaux ; si l&apos;arrivée
        respecte exactement votre classement, vous êtes payé au rapport <strong>Ordre</strong> ; sinon,
        et si vos cinq chevaux sont bien les cinq premiers, au rapport <strong>Désordre</strong>. Le
        bonus est automatique. La seule chose que vous décidez, c&apos;est l&apos;ordre dans lequel
        vous rangez votre sélection — et donc la peine que vous vous donnez à la classer.
      </p>
      <p>
        La question devient alors très concrète : <strong>est-ce que classer sa sélection vaut le
        travail que ça demande ?</strong>
      </p>

      <h2>Ce que dit la théorie</h2>
      <p>
        Cinq chevaux se rangent de <strong>5 × 4 × 3 × 2 × 1 = 120 façons</strong>. Trouver les bons
        dans n&apos;importe quel ordre est donc exactement 120 fois plus probable que de tomber sur
        l&apos;ordre exact. Si les rapports suivaient les probabilités, l&apos;ordre devrait payer
        120 fois le désordre.
      </p>
      <p>
        Au Tiercé, ce raisonnement fonctionne à merveille : trois chevaux se rangent de 6 façons, et{" "}
        <Link href="/blog/tierce-ordre-ou-desordre">le rapport mesuré est de ×6,1</Link>, avec une
        régularité d&apos;horloge — la moitié des courses tombe entre ×5,8 et ×6,6. Au Quinté, la
        mécanique se dérègle complètement.
      </p>

      <h2>Ce que disent les 249 courses</h2>
      <ul>
        <li>
          rapport <strong>Ordre</strong> médian : <strong>12 848,70 €</strong> pour 1 € ;
        </li>
        <li>
          rapport <strong>Désordre</strong> médian : <strong>230,20 €</strong> pour 1 € ;
        </li>
        <li>
          facteur médian : <strong>×72,8</strong> — bien en dessous des ×120 théoriques ;
        </li>
        <li>
          et surtout, une dispersion énorme : de <strong>×1,2</strong> au minimum à{" "}
          <strong>×121,3</strong> au maximum.
        </li>
      </ul>
      <p>
        Deux chiffres résument l&apos;affaire. <strong>Dans 29 % des Quintés (73 sur 249),
        l&apos;ordre exact paie moins de dix fois le désordre</strong> — pour un exploit 120 fois plus
        difficile. À l&apos;inverse, seuls <strong>17 % atteignent le ×100</strong>.
      </p>
      <p>
        Notez aussi le plafond : sur un an, <strong>aucun Quinté n&apos;a dépassé ×121,3</strong> —
        c&apos;est-à-dire le nombre de permutations, à l&apos;arrondi des rapports près.
        Le nombre de permutations n&apos;est donc pas une moyenne autour de laquelle les rapports
        oscilleraient : c&apos;est une <strong>borne haute</strong>, atteinte au mieux, jamais franchie.
        L&apos;ordre exact ne peut donc, au mieux, que rendre justice à sa difficulté — jamais la
        surpayer.
      </p>

      <h2>Le résultat qui surprend : l&apos;ordre paie mal les gros Quintés</h2>
      <p>
        On s&apos;attendrait à ce que les Quintés à surprise, ceux dont on rêve, soient aussi ceux où
        l&apos;ordre exact fait exploser le gain. C&apos;est <strong>l&apos;inverse</strong>, et le lien
        est très net : la corrélation entre le facteur ordre/désordre et le rapport du désordre est de{" "}
        <strong>−0,85</strong> — l&apos;une des relations les plus franches qu&apos;on puisse mesurer
        sur des rapports de courses.
      </p>
      <ul>
        <li>
          Quand l&apos;ordre paie <strong>moins de ×10</strong>, le désordre rapportait déjà{" "}
          <strong>12 395,80 €</strong> en médiane. Ce sont les Quintés à outsiders.
        </li>
        <li>
          Quand l&apos;ordre paie <strong>×100 ou plus</strong>, le désordre ne rapportait que{" "}
          <strong>43,00 €</strong>. Ce sont les Quintés logiques, gagnés par les favoris.
        </li>
      </ul>
      <p>
        Autrement dit : <strong>le multiplicateur de l&apos;ordre est généreux quand il n&apos;y a pas
        grand-chose à multiplier, et dérisoire quand le jackpot est là.</strong> Sur un Quinté à
        12 000 €, vous ne jouez pas pour 120 fois plus, vous jouez pour environ dix fois plus.
      </p>
      <p>
        Le point de départ est une identité, pas une théorie : un rapport n&apos;est pas un prix
        affiché d&apos;avance, c&apos;est une masse d&apos;enjeux divisée par le nombre de gagnants.
        Le facteur ordre/désordre ne mesure donc pas une difficulté, il mesure un{" "}
        <strong>rapport entre deux nombres de gagnants</strong>. Pour qu&apos;il atteigne ×120, il
        faudrait qu&apos;il y ait 120 fois moins de tickets à l&apos;ordre exact qu&apos;au désordre.
        Sur les arrivées improbables, ce n&apos;est manifestement pas le cas — l&apos;explication la
        plus naturelle étant que les rares parieurs qui trouvent une combinaison improbable la
        trouvent souvent aussi dans le bon ordre. Nous ne l&apos;avons pas mesurée directement : le
        PMU ne publie pas le nombre de gagnants par rapport, seulement les rapports eux-mêmes.
      </p>

      <h2>Ce qu&apos;il faut en faire</h2>
      <ul>
        <li>
          <strong>Ne construisez pas votre sélection pour l&apos;ordre.</strong> L&apos;espérance de
          gain apportée par le classement exact est réelle mais faible, et elle est la plus faible
          précisément sur les courses qui rapportent le plus. Le travail utile est de trouver{" "}
          <em>les cinq bons chevaux</em>.
        </li>
        <li>
          <strong>Classez quand même votre sélection sérieusement</strong> — ça ne coûte rien : le
          bonus est automatique, il n&apos;y a pas de mise supplémentaire à payer pour y avoir droit.
          C&apos;est un billet de loterie offert, pas un investissement.
        </li>
        <li>
          <strong>Méfiez-vous des promesses bâties sur le rapport Ordre.</strong> Un « Quinté dans
          l&apos;ordre à 206 000 € » — c&apos;est le maximum observé sur l&apos;année — existe, mais
          il ne dit rien de ce qu&apos;un pari rapporte en moyenne. La médiane, elle, est 16 fois plus
          basse.
        </li>
        <li>
          Le levier qui compte reste ailleurs : dans l&apos;écart entre la probabilité réelle
          d&apos;un cheval et ce que paie sa cote. C&apos;est l&apos;objet du{" "}
          <Link href="/guides/pari-de-valeur">pari de valeur</Link>.
        </li>
      </ul>

      <h2>Comment ces chiffres ont été obtenus</h2>
      <p>
        Chaque Quinté+ de la période a été relevé avec ses <strong>rapports officiels PMU</strong>,
        Ordre et Désordre, pour une même combinaison gagnante. Aucun rapport n&apos;est estimé ni
        reconstitué. Les 249 courses retenues sont celles où les deux rapports portent bien sur la
        même arrivée ; les autres sont écartées plutôt que corrigées.
      </p>
      <p>
        La méthode a d&apos;abord été validée sur le Tiercé, dont le facteur avait été mesuré
        séparément : elle retrouve exactement le <strong>×6,1</strong> déjà publié, sur 359 courses.
        Un résultat qui contredit l&apos;intuition ne vaut que si la méthode sait d&apos;abord
        reproduire un résultat connu.
      </p>
      <p>
        Le même principe s&apos;applique à tout ce que nous publions : les analyses du{" "}
        <Link href="/programme">programme du jour</Link> sont notées aux rapports réels, et le{" "}
        <Link href="/track-record">palmarès</Link> en porte le détail, pertes comprises.
      </p>
    </>
  );
}
