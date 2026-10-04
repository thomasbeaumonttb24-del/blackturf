import { Metadata } from "next";
import { OG_IMAGE } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Conditions Générales de Vente",
  description:
    "Conditions Générales de Vente des abonnements BlackTurf : formules, durée, résiliation, droit de rétractation et facturation.",
  alternates: { canonical: "/cgv" },
  // Sans og:title propre, la page héritait de celui de la racine — deux sources de
  // titre contradictoires, que Google ne sait pas départager.
  openGraph: { title: "Conditions Générales de Vente — BlackTurf", url: "https://blackturf.fr/cgv", images: [OG_IMAGE] },
};

export default function CGVPage() {
  return (
    <div className="mx-auto max-w-3xl px-4 sm:px-6 py-12 prose prose-invert prose-sm max-w-none">
      <h1 className="text-2xl font-bold mb-8">Conditions Générales de Vente (CGV)</h1>

      <section className="mb-8">
        <h2 className="text-lg font-bold mb-3">1. Identification du vendeur</h2>
        <p className="text-muted-foreground">
          Les présentes CGV régissent la vente des abonnements au service BlackTurf, édité par
          un entrepreneur individuel (micro-entreprise) exploitant sous le
          nom commercial « BlackTurf ». TVA non applicable, art. 293&nbsp;B du CGI. Contact : contact@blackturf.fr.
        </p>
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-bold mb-3">2. Objet</h2>
        <p className="text-muted-foreground">
          BlackTurf fournit un service numérique d&apos;<strong>aide à la décision et de conseil sportif</strong>
          (analyses, pronostics hippiques, plans de mise) accessible en ligne par abonnement. Le service ne
          collecte aucun pari et ne constitue pas un opérateur de jeux d&apos;argent.
        </p>
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-bold mb-3">3. Offres et prix</h2>
        <p className="text-muted-foreground">
          Les prix sont indiqués en euros, toutes taxes comprises (TVA non applicable, art. 293&nbsp;B du CGI) :
        </p>
        <ul className="space-y-1.5 text-muted-foreground list-disc list-inside">
          <li><strong>Découverte</strong> : gratuit (0&nbsp;€).</li>
          <li><strong>Standard</strong> : 12&nbsp;€/mois ou 115,20&nbsp;€/an.</li>
          <li><strong>Expert</strong> : 19&nbsp;€/mois ou 182,40&nbsp;€/an.</li>
          <li>
            <strong>Pass sans abonnement</strong> (accès Expert, paiement unique) : Pass Jour 5&nbsp;€ (24&nbsp;h),
            Pass Semaine 12&nbsp;€ (7&nbsp;jours), Pass Mois 24&nbsp;€ (30&nbsp;jours). Voir section 6 bis.
          </li>
        </ul>
        <p className="text-muted-foreground">
          Les tarifs en vigueur sont ceux affichés sur la page{" "}
          <a href="/tarifs" className="underline text-brand-gold-dark">Tarifs</a> au moment de la commande.
          Tout changement de tarif est sans effet sur les abonnements en cours jusqu&apos;à leur échéance.
        </p>
        <p className="text-muted-foreground">
          <strong>Défi du mois.</strong> Le concours gratuit de pronostics en points est régi par son règlement
          (page <a href="/defi" className="underline text-brand-gold-dark">Défi du mois</a>). Sa récompense
          (30 jours de la formule Expert) n&apos;a aucune valeur monétaire et ne s&apos;échange pas contre de
          l&apos;argent ; pour un abonné payant, elle est accordée sous forme de réduction équivalente sur ses
          prochaines factures d&apos;abonnement.
        </p>
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-bold mb-3">4. Commande et paiement</h2>
        <p className="text-muted-foreground">
          Le paiement s&apos;effectue en ligne par carte bancaire via notre prestataire <strong>Stripe</strong>
          (paiement sécurisé). L&apos;abonnement est activé après confirmation du paiement. La commande vaut
          acceptation des présentes CGV, des{" "}
          <a href="/cgu" className="underline text-brand-gold-dark">CGU</a> et de la{" "}
          <a href="/confidentialite" className="underline text-brand-gold-dark">Politique de confidentialité</a>.
        </p>
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-bold mb-3">5. Droit de rétractation (14 jours)</h2>
        <div className="rounded-xl border border-brand-gold/20 bg-brand-gold/5 p-4 text-sm text-muted-foreground">
          <p className="mb-2">
            Conformément aux articles L221-18 et suivants du Code de la consommation, vous disposez d&apos;un
            <strong> délai de 14 jours</strong> à compter de la souscription pour exercer votre droit de
            rétractation, sans avoir à justifier de motif.
          </p>
          <p className="mb-2">
            <strong>Renonciation pour service numérique fourni immédiatement (art. L221-28, 13°) :</strong> en
            souscrivant et en accédant immédiatement au service, vous demandez expressément son exécution avant
            la fin du délai de rétractation et <strong>reconnaissez perdre votre droit de rétractation</strong>
            une fois le service pleinement exécuté. Tant que vous n&apos;avez pas accédé au contenu premium, le
            droit de rétractation reste exerçable.
          </p>
          <p>
            Pour vous rétracter : écrivez à contact@blackturf.fr (ou utilisez le formulaire-type de
            rétractation). Remboursement sous 14 jours par le moyen de paiement d&apos;origine.
          </p>
          <p className="mt-2">
            <strong>Pass sans abonnement :</strong> l&apos;accès est ouvert dès le paiement. Sur la page de paiement, avant de payer, vous
            cochez une case par laquelle vous demandez l&apos;exécution immédiate du service et renoncez
            expressément à votre droit de rétractation (art. L221-28, 13°). Cette renonciation vous est
            confirmée par e-mail. Le pass n&apos;ouvre donc pas de droit de rétractation.
          </p>
        </div>
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-bold mb-3">6. Durée, reconduction et résiliation</h2>
        <p className="text-muted-foreground">
          L&apos;abonnement est conclu pour la durée choisie (mensuelle ou annuelle) et se renouvelle par
          <strong> reconduction tacite</strong> pour une durée identique, sauf résiliation. Conformément à la
          <strong> loi Chatel</strong> (art. L215-1 et s. du Code de la consommation), vous êtes informé par
          email, au plus tôt 3 mois et au plus tard 1 mois avant l&apos;échéance, de la possibilité de ne pas
          reconduire. À défaut d&apos;information, vous pouvez résilier à tout moment sans frais à compter de la
          reconduction. La <strong>résiliation s&apos;effectue en ligne</strong> depuis votre espace « Profil »
          (fonctionnalité « résilier en quelques clics », art. L215-1-1) ou par email à contact@blackturf.fr.
          La résiliation prend effet à la fin de la période en cours ; l&apos;accès reste ouvert jusque-là.
        </p>
      </section>

      <section className="mb-8" id="passes">
        <h2 className="text-lg font-bold mb-3">6 bis. Pass sans abonnement</h2>
        <ul className="text-muted-foreground list-disc pl-5 space-y-1.5">
          <li>
            Le pass donne accès à l&apos;ensemble des fonctionnalités de la formule Expert pendant la durée
            achetée (24&nbsp;heures, 7&nbsp;jours ou 30&nbsp;jours), décomptée à partir de la confirmation du
            paiement.
          </li>
          <li>
            <strong>Paiement unique, sans reconduction</strong> : aucun autre prélèvement n&apos;a lieu ; l&apos;accès
            prend fin automatiquement à l&apos;échéance. Il n&apos;y a rien à résilier.
          </li>
          <li>
            Un pass acheté alors qu&apos;un autre est en cours commence à l&apos;échéance du précédent. Le cumul
            est limité : un nouveau pass ne peut être acheté lorsque l&apos;accès est déjà ouvert pour plus de
            31&nbsp;jours. Un abonné Expert, qui dispose déjà d&apos;un accès illimité, ne peut pas acheter de pass.
          </li>
          <li>
            <strong>Ni annulation, ni remboursement</strong> une fois le paiement confirmé (voir section 5), sauf
            disposition légale impérative, notamment en cas d&apos;indisponibilité du service imputable à BlackTurf.
          </li>
          <li>
            Un paiement remboursé ou contesté auprès de la banque met fin immédiatement à l&apos;accès
            correspondant.
          </li>
          <li>Le pass est personnel et attaché au compte qui l&apos;a acheté.</li>
        </ul>
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-bold mb-3">7. Remboursement</h2>
        <p className="text-muted-foreground">
          Hors exercice du droit de rétractation (section 5), les sommes versées au titre d&apos;une période
          entamée ne sont pas remboursées, sauf disposition légale impérative ou geste commercial accordé au
          cas par cas sur demande à contact@blackturf.fr.
        </p>
      </section>

      <section className="mb-8" id="parrainage">
        <h2 className="text-lg font-bold mb-3">8. Programme de parrainage</h2>
        <p className="text-muted-foreground">
          Tout titulaire d&apos;un compte BlackTurf dont l&apos;adresse e-mail est confirmée (le « parrain ») peut
          inviter de nouveaux utilisateurs (les « filleuls ») au moyen de son lien ou de son code de
          parrainage personnel, disponible dans son espace « Profil ».
        </p>
        <ul className="text-muted-foreground list-disc pl-5 space-y-1.5 mt-3">
          <li>
            <strong>Avantage du filleul</strong> : une remise de 5 € TTC sur sa première facture payante
            (formule Standard ou Expert, mensuelle ou annuelle), appliquée automatiquement lors du paiement.
            Elle s&apos;applique aussi au premier Pass Semaine ou Pass Mois (soit 7&nbsp;€ ou 19&nbsp;€), mais jamais au
            Pass Jour. Elle ne vaut qu&apos;une seule fois, quel que soit le premier achat.
          </li>
          <li>
            <strong>Avantage du parrain</strong> : un crédit de 5 € TTC par filleul, acquis uniquement lorsque le
            premier paiement du filleul (abonnement, Pass Semaine ou Pass Mois — jamais un Pass Jour) a été
            effectivement encaissé. Ce crédit est imputé automatiquement sur
            les prochaines factures d&apos;abonnement du parrain ; il n&apos;est ni remboursable, ni cessible, ni
            convertible en espèces.
          </li>
          <li>
            <strong>Plafond</strong> : les crédits imputés sur une même période de facturation mensuelle sont
            limités au nombre nécessaire pour couvrir la mensualité (4 pour la formule Expert, 3 pour la formule
            Standard). Les crédits acquis au-delà sont reportés sur les périodes suivantes. Un reliquat inférieur
            au montant d&apos;une facture est déduit de la facture suivante. Le parrain qui ne règle aucune
            facture (abonnement offert ou non encore souscrit) conserve ses crédits jusqu&apos;à sa première
            facture payante.
          </li>
          <li>
            <strong>Conditions</strong> : le filleul doit être un nouveau client, créer son compte au moyen du
            lien ou du code du parrain, et régler avec un moyen de paiement qui lui est propre. Un compte ne peut
            avoir qu&apos;un seul parrain, fixé à sa création, et nul ne peut se parrainer lui-même.
          </li>
          <li>
            <strong>Annulation</strong> : si le paiement du filleul ayant ouvert droit au crédit est remboursé ou
            contesté, le crédit correspondant est annulé. En cas d&apos;utilisation abusive ou frauduleuse
            (notamment comptes multiples ou moyen de paiement déjà rattaché à un autre compte), BlackTurf peut
            refuser ou annuler les avantages concernés, la remise indûment accordée pouvant être réintégrée à la
            facture suivante du filleul.
          </li>
        </ul>
        <p className="text-muted-foreground mt-3">
          BlackTurf peut modifier ou mettre fin au programme à tout moment ; les crédits déjà acquis restent
          imputables dans les conditions ci-dessus.
        </p>
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-bold mb-3">9. Médiation de la consommation</h2>
        <p className="text-muted-foreground">
          Conformément à l&apos;article L612-1 du Code de la consommation, le consommateur peut recourir
          gratuitement à un médiateur de la consommation en vue de la résolution amiable d&apos;un litige.
          Médiateur compétent : <strong>[médiateur à désigner — adhésion en cours]</strong>. En attendant, vous
          pouvez utiliser la plateforme européenne de Règlement en Ligne des Litiges :{" "}
          <a href="https://ec.europa.eu/consumers/odr" target="_blank" rel="noopener noreferrer" className="underline text-brand-gold-dark">
            ec.europa.eu/consumers/odr
          </a>.
        </p>
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-bold mb-3">10. Responsabilité &amp; jeu responsable</h2>
        <p className="text-muted-foreground">
          BlackTurf est un outil d&apos;aide à la décision : les analyses et plans de mise <strong>ne
          garantissent aucun gain</strong> et ne constituent ni un conseil en investissement, ni une
          recommandation financière personnalisée. L&apos;utilisateur reste seul responsable de ses paris et de
          ses pertes éventuelles. Service strictement réservé aux personnes <strong>majeures (18 ans et
          plus)</strong>. Jeu responsable : joueurs-info-service.fr — 09&nbsp;74&nbsp;75&nbsp;13&nbsp;13. Voir les{" "}
          <a href="/cgu" className="underline text-brand-gold-dark">CGU</a> pour le détail des limitations de responsabilité.
        </p>
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-bold mb-3">11. Droit applicable</h2>
        <p className="text-muted-foreground">
          Les présentes CGV sont soumises au droit français. En cas de litige, et après tentative de résolution
          amiable, les tribunaux français sont compétents.
        </p>
      </section>

      <p className="text-xs text-muted-foreground mt-12">
        Dernière mise à jour : septembre 2026
      </p>
    </div>
  );
}
