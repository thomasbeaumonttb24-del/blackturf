import { Metadata } from "next";

export const metadata: Metadata = {
  title: "Conditions Générales de Vente",
  description:
    "Conditions Générales de Vente des abonnements BlackTurf : formules, durée, résiliation, droit de rétractation et facturation.",
  alternates: { canonical: "/cgv" },
};

export default function CGVPage() {
  return (
    <div className="mx-auto max-w-3xl px-4 sm:px-6 py-12 prose prose-invert prose-sm max-w-none">
      <h1 className="text-2xl font-bold mb-8">Conditions Générales de Vente (CGV)</h1>

      <section className="mb-8">
        <h2 className="text-lg font-bold mb-3">1. Identification du vendeur</h2>
        <p className="text-muted-foreground">
          Les présentes CGV régissent la vente des abonnements au service BlackTurf, édité par
          <strong> Thomas BEAUMONT</strong>, entrepreneur individuel (micro-entreprise), exploitant sous le
          nom commercial « BlackTurf », 10 rue Alix d&apos;Unienville, 33100 Bordeaux — SIREN 907&nbsp;548&nbsp;184,
          RCS Bordeaux. TVA non applicable, art. 293&nbsp;B du CGI. Contact : contact@blackturf.fr.
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
          <li><strong>Standard</strong> : 12&nbsp;€/mois ou 115&nbsp;€/an.</li>
          <li><strong>Expert</strong> : 19&nbsp;€/mois ou 182&nbsp;€/an.</li>
        </ul>
        <p className="text-muted-foreground">
          Les tarifs en vigueur sont ceux affichés sur la page{" "}
          <a href="/tarifs" className="underline text-brand-gold">Tarifs</a> au moment de la commande.
          Tout changement de tarif est sans effet sur les abonnements en cours jusqu&apos;à leur échéance.
        </p>
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-bold mb-3">4. Commande et paiement</h2>
        <p className="text-muted-foreground">
          Le paiement s&apos;effectue en ligne par carte bancaire via notre prestataire <strong>Stripe</strong>
          (paiement sécurisé). L&apos;abonnement est activé après confirmation du paiement. La commande vaut
          acceptation des présentes CGV, des{" "}
          <a href="/cgu" className="underline text-brand-gold">CGU</a> et de la{" "}
          <a href="/confidentialite" className="underline text-brand-gold">Politique de confidentialité</a>.
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

      <section className="mb-8">
        <h2 className="text-lg font-bold mb-3">7. Remboursement</h2>
        <p className="text-muted-foreground">
          Hors exercice du droit de rétractation (section 5), les sommes versées au titre d&apos;une période
          entamée ne sont pas remboursées, sauf disposition légale impérative ou geste commercial accordé au
          cas par cas sur demande à contact@blackturf.fr.
        </p>
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-bold mb-3">8. Médiation de la consommation</h2>
        <p className="text-muted-foreground">
          Conformément à l&apos;article L612-1 du Code de la consommation, le consommateur peut recourir
          gratuitement à un médiateur de la consommation en vue de la résolution amiable d&apos;un litige.
          Médiateur compétent : <strong>[médiateur à désigner — adhésion en cours]</strong>. En attendant, vous
          pouvez utiliser la plateforme européenne de Règlement en Ligne des Litiges :{" "}
          <a href="https://ec.europa.eu/consumers/odr" target="_blank" rel="noopener noreferrer" className="underline text-brand-gold">
            ec.europa.eu/consumers/odr
          </a>.
        </p>
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-bold mb-3">9. Responsabilité &amp; jeu responsable</h2>
        <p className="text-muted-foreground">
          BlackTurf est un outil d&apos;aide à la décision : les analyses et plans de mise <strong>ne
          garantissent aucun gain</strong> et ne constituent ni un conseil en investissement, ni une
          recommandation financière personnalisée. L&apos;utilisateur reste seul responsable de ses paris et de
          ses pertes éventuelles. Service strictement réservé aux personnes <strong>majeures (18 ans et
          plus)</strong>. Jeu responsable : joueurs-info-service.fr — 09&nbsp;74&nbsp;75&nbsp;13&nbsp;13. Voir les{" "}
          <a href="/cgu" className="underline text-brand-gold">CGU</a> pour le détail des limitations de responsabilité.
        </p>
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-bold mb-3">10. Droit applicable</h2>
        <p className="text-muted-foreground">
          Les présentes CGV sont soumises au droit français. En cas de litige, et après tentative de résolution
          amiable, les tribunaux français sont compétents.
        </p>
      </section>

      <p className="text-xs text-muted-foreground mt-12">
        Dernière mise à jour : juin 2026
      </p>
    </div>
  );
}
