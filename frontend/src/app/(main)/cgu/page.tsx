import { Metadata } from "next";
import { OG_IMAGE } from "@/lib/seo";

export const metadata: Metadata = {
  title: "Conditions Générales d’Utilisation",
  description: "CGU de la plateforme BlackTurf — conditions d'utilisation du service",
  alternates: { canonical: "/cgu" },
  // Sans og:title propre, la page héritait de celui de la racine — deux sources de
  // titre contradictoires, que Google ne sait pas départager.
  openGraph: { title: "Conditions Générales d’Utilisation — BlackTurf", url: "https://blackturf.fr/cgu", images: [OG_IMAGE] },
};

export default function CguPage() {
  return (
    <div className="mx-auto max-w-3xl px-4 sm:px-6 py-12 space-y-8">
      <h1 className="text-2xl font-bold">Conditions Générales d&apos;Utilisation</h1>
      <p className="text-xs text-muted-foreground">Dernière mise à jour : janvier 2026</p>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">1. Objet</h2>
        <p className="text-sm text-muted-foreground">
          Les présentes CGU régissent l'utilisation de la plateforme BlackTurf (blackturf.fr),
          outil d'aide à la décision basé sur l'intelligence artificielle pour les paris hippiques.
          BlackTurf (Thomas BEAUMONT, entrepreneur individuel) se réserve le droit de modifier ces CGU à tout moment.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">2. Avertissement jeu responsable</h2>
        <div className="rounded-xl border border-amber-500/30 bg-amber-50 p-4">
          <p className="text-sm font-semibold text-amber-700 mb-2">⚠️ Avertissement obligatoire</p>
          <ul className="text-sm text-muted-foreground space-y-1 list-disc list-inside">
            <li><strong>Interdit aux mineurs de moins de 18 ans.</strong></li>
            <li>Le jeu peut créer une dépendance. Jouez de façon responsable.</li>
            <li>Les performances passées ne garantissent pas les résultats futurs.</li>
            <li>BlackTurf est un outil d'aide à la décision, pas un oracle.</li>
            <li>Assistance : <strong>09 74 75 13 13</strong> — joueurs-info-service.fr (gratuit, 7j/7)</li>
          </ul>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">3. Description du service</h2>
        <p className="text-sm text-muted-foreground">
          BlackTurf propose des prédictions hippiques générées par un ensemble de modèles d'apprentissage
          automatique (XGBoost, LightGBM, CatBoost), la détection de paris de valeur, un outil de gestion
          de capital et un assistant IA. Ces informations sont fournies à titre indicatif uniquement.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">4. Inscription et accès</h2>
        <ul className="text-sm text-muted-foreground space-y-1 list-disc list-inside">
          <li>L'inscription est réservée aux personnes majeures (18+) résidant dans un pays où les paris hippiques sont légaux.</li>
          <li>Un seul compte par personne physique est autorisé.</li>
          <li>L'utilisateur est responsable de la confidentialité de ses identifiants.</li>
          <li>BlackTurf se réserve le droit de suspendre tout compte en cas d'utilisation abusive.</li>
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">5. Abonnements et paiements</h2>
        <ul className="text-sm text-muted-foreground space-y-1 list-disc list-inside">
          <li>Les abonnements sont gérés via Stripe (paiement sécurisé PCI-DSS).</li>
          <li>L'essai gratuit de 7 jours est disponible pour les plans Standard et Expert, une seule fois par compte. L'enregistrement d'une carte bancaire est requis pour l'ouvrir ; aucun montant n'est prélevé avant son terme, et l'abonnement peut être résilié à tout moment pendant l'essai sans être facturé.</li>
          <li>Résiliation possible à tout moment via le portail Stripe, sans pénalité.</li>
          <li>Remboursement : au cas par cas sur demande à contact@blackturf.fr.</li>
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">6. Limitation de responsabilité</h2>
        <p className="text-sm text-muted-foreground">
          BlackTurf fournit un outil d'aide à la décision. Toute décision de pari reste de la
          seule responsabilité de l'utilisateur. BlackTurf ne garantit aucun profit et ne saurait
          être tenu responsable des pertes financières résultant de l'utilisation du service.
          Les performances affichées (ROI simulé, précision Top-3) sont des résultats de backtest
          sur données historiques et ne constituent pas une promesse de gains futurs.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">7. Propriété intellectuelle</h2>
        <p className="text-sm text-muted-foreground">
          L'ensemble du contenu (modèles ML, interface, algorithmes, données agrégées) est la propriété
          exclusive de BlackTurf (Thomas BEAUMONT, entrepreneur individuel). Toute reproduction, distribution ou exploitation commerciale
          sans autorisation écrite est interdite.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">8. Droit applicable</h2>
        <p className="text-sm text-muted-foreground">
          Ces CGU sont soumises au droit français. En cas de litige, les parties rechercheront
          une solution amiable avant tout recours judiciaire. Tribunal compétent : Paris.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">9. Contact</h2>
        <p className="text-sm text-muted-foreground">
          contact@blackturf.fr — BlackTurf (Thomas BEAUMONT, entrepreneur individuel), France
        </p>
      </section>
    </div>
  );
}
