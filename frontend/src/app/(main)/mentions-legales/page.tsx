import { Metadata } from "next";

export const metadata: Metadata = {
  title: "Mentions légales — BlackTurf",
  description: "Mentions légales de la plateforme BlackTurf",
};

export default function MentionsLegalesPage() {
  return (
    <div className="mx-auto max-w-3xl px-4 sm:px-6 py-12 prose prose-invert prose-sm max-w-none">
      <h1 className="text-2xl font-bold mb-8">Mentions légales</h1>

      <section className="mb-8">
        <h2 className="text-lg font-bold mb-3">Éditeur</h2>
        <p className="text-muted-foreground">
          BlackTurf SAS<br />
          Siège social : France<br />
          Email : contact@blackturf.fr<br />
          Site : https://blackturf.fr
        </p>
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-bold mb-3">Hébergement</h2>
        <p className="text-muted-foreground">
          Hébergé sur infrastructure cloud sécurisée (PostgreSQL + Redis + Docker).
          Les données sont stockées en Europe (Union Européenne).
        </p>
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-bold mb-3">Avertissement jeu responsable</h2>
        <div className="rounded-xl border border-brand-gold/20 bg-brand-gold/5 p-4 text-sm">
          <p className="font-semibold mb-2">⚠️ Jeu responsable — à lire attentivement</p>
          <ul className="space-y-1.5 text-muted-foreground list-disc list-inside">
            <li>BlackTurf est un <strong>outil d&apos;aide à la décision</strong>, pas un service de paris.</li>
            <li>Les prédictions ne constituent <strong>en aucun cas une garantie de gain</strong>.</li>
            <li>Les paris comportent des <strong>risques de pertes financières</strong>.</li>
            <li>BlackTurf est <strong>strictement interdit aux mineurs</strong> (moins de 18 ans).</li>
            <li>Les performances passées ne préjugent pas des performances futures.</li>
            <li>Ne misez jamais plus que ce que vous pouvez vous permettre de perdre.</li>
          </ul>
          <p className="mt-3">
            En cas de problème avec le jeu :{" "}
            <a href="https://www.joueurs-info-service.fr" target="_blank" rel="noopener noreferrer" className="underline text-brand-gold">
              joueurs-info-service.fr
            </a>
            {" "}— <strong>09 74 75 13 13</strong> (appel gratuit, 7j/7, 8h-2h)
          </p>
        </div>
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-bold mb-3">Propriété intellectuelle</h2>
        <p className="text-muted-foreground">
          Tous les contenus du site (textes, algorithmes, interface, marque BlackTurf) sont la propriété
          exclusive de BlackTurf SAS. Toute reproduction sans autorisation est interdite.
        </p>
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-bold mb-3">Données personnelles</h2>
        <p className="text-muted-foreground">
          Les données collectées (email, historique de paris) sont utilisées uniquement pour le
          fonctionnement du service. Elles ne sont jamais revendues à des tiers.
          Conformément au RGPD, vous disposez d&apos;un droit d&apos;accès, de rectification et de suppression.
          Email : privacy@blackturf.fr
        </p>
      </section>

      <p className="text-xs text-muted-foreground mt-12">
        Dernière mise à jour : mai 2026
      </p>
    </div>
  );
}
