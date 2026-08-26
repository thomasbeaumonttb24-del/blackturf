import { Metadata } from "next";
import { OG_IMAGE } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Politique de confidentialité",
  description: "Politique de confidentialité et traitement des données personnelles — BlackTurf",
  alternates: { canonical: "/confidentialite" },
  // Sans og:title propre, la page héritait de celui de la racine — deux sources de
  // titre contradictoires, que Google ne sait pas départager.
  openGraph: { title: "Politique de confidentialité — BlackTurf", url: "https://blackturf.fr/confidentialite", images: [OG_IMAGE] },
};

export default function ConfidentialitePage() {
  return (
    <div className="mx-auto max-w-3xl px-4 sm:px-6 py-12 space-y-8">
      <h1 className="text-2xl font-bold">Politique de confidentialité</h1>
      <p className="text-xs text-muted-foreground">Dernière mise à jour : juin 2026</p>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">1. Responsable du traitement</h2>
        <p className="text-sm text-muted-foreground">
          Thomas BEAUMONT — entrepreneur individuel exploitant sous le nom commercial « BlackTurf »,
          10 rue Alix d&apos;Unienville, 33100 Bordeaux (SIREN 907&nbsp;548&nbsp;184).<br />
          Contact données personnelles : <strong>privacy@blackturf.fr</strong><br />
          Hébergement : Union Européenne (Hetzner Online GmbH, Allemagne).
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">2. Données collectées</h2>
        <ul className="text-sm text-muted-foreground space-y-1 list-disc list-inside">
          <li>Informations de compte : e-mail, prénom, nom (optionnel)</li>
          <li>Données d'utilisation : courses consultées, paris enregistrés, capital</li>
          <li>Données de paiement : gérées exclusivement par Stripe (nous ne stockons aucun numéro de carte)</li>
          <li>Données de navigation : adresse IP, navigateur, logs d'accès (fins de sécurité)</li>
          <li>Préférences push : token de notification si activé</li>
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">3. Finalités du traitement</h2>
        <ul className="text-sm text-muted-foreground space-y-1 list-disc list-inside">
          <li>Fourniture du service (prédictions IA, conseils de mise, alertes)</li>
          <li>Gestion des abonnements et facturation (via Stripe)</li>
          <li>Amélioration du modèle ML (données agrégées et anonymisées)</li>
          <li>Sécurité de la plateforme</li>
          <li>Envoi d'alertes paris de valeur (avec consentement)</li>
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">4. Base légale</h2>
        <p className="text-sm text-muted-foreground">
          Exécution du contrat (fourniture du service), intérêt légitime (sécurité, amélioration),
          et consentement pour les communications marketing et notifications push.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">5. Durée de conservation</h2>
        <ul className="text-sm text-muted-foreground space-y-1 list-disc list-inside">
          <li>Compte actif : durée de vie du compte</li>
          <li>Après suppression : 30 jours (sauvegarde), puis effacement définitif</li>
          <li>Logs de sécurité : 12 mois</li>
          <li>Données comptables : 10 ans (obligation légale)</li>
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">6. Partage des données</h2>
        <p className="text-sm text-muted-foreground">
          Vos données ne sont pas vendues. Sous-traitants strictement nécessaires :
          Stripe (paiements), Resend (emails transactionnels), Anthropic (IA), hébergeur Hetzner (EU).
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">7. Transferts hors Union Européenne</h2>
        <p className="text-sm text-muted-foreground">
          Certains sous-traitants (Stripe, Anthropic) sont susceptibles de traiter des données en dehors de
          l&apos;Union Européenne (notamment aux États-Unis). Ces transferts sont encadrés par les
          <strong> Clauses Contractuelles Types</strong> de la Commission européenne et/ou le mécanisme
          <strong> EU-US Data Privacy Framework</strong>, garantissant un niveau de protection adéquat.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">8. Décisions automatisées</h2>
        <p className="text-sm text-muted-foreground">
          Les pronostics et plans de mise sont générés par des modèles statistiques à partir de données de
          courses et, le cas échéant, de votre historique. Ils constituent une <strong>aide à la décision</strong> :
          aucune décision produisant des effets juridiques n&apos;est prise de façon entièrement automatisée ;
          vous restez seul décideur de vos paris.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">9. Vos droits (RGPD)</h2>
        <p className="text-sm text-muted-foreground">
          Vous disposez des droits d'accès, de rectification, d'effacement, de portabilité,
          de limitation et d'opposition. Pour exercer ces droits : <strong>privacy@blackturf.fr</strong>.
          Réponse sous 30 jours. Droit de recours auprès de la <strong>CNIL</strong> (cnil.fr).
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">10. Cookies</h2>
        <p className="text-sm text-muted-foreground">
          Cookies strictement nécessaires uniquement (session JWT, préférences interface).
          Pas de cookies publicitaires ni de trackers tiers.
        </p>
      </section>

      <div className="rounded-xl border border-border/50 bg-muted/20 p-4 text-xs text-muted-foreground">
        <strong>⚠️ Jeu responsable</strong> — Les données de paris sont conservées pour vous aider
        à suivre votre bankroll. Si vous souhaitez supprimer toutes vos données, contactez-nous.
        09 74 75 13 13 — joueurs-info-service.fr
      </div>
    </div>
  );
}
