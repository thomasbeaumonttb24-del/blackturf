import { Metadata } from "next";

export const metadata: Metadata = {
  title: "Mentions légales — BlackTurf",
  description: "Mentions légales de la plateforme BlackTurf",
  alternates: { canonical: "/mentions-legales" },
};

export default function MentionsLegalesPage() {
  return (
    <div className="mx-auto max-w-3xl px-4 sm:px-6 py-12 prose prose-invert prose-sm max-w-none">
      <h1 className="text-2xl font-bold mb-8">Mentions légales</h1>

      <section className="mb-8">
        <h2 className="text-lg font-bold mb-3">Éditeur du site</h2>
        <p className="text-muted-foreground">
          Le site <strong>BlackTurf</strong> (blackturf.fr) est édité par :<br />
          <strong>Thomas BEAUMONT</strong> — Entrepreneur individuel (micro-entreprise)<br />
          Exploité sous le nom commercial « BlackTurf »<br />
          Siège : 10 rue Alix d&apos;Unienville, 33100 Bordeaux, France<br />
          SIREN : 907&nbsp;548&nbsp;184 — SIRET (siège) : 907&nbsp;548&nbsp;184&nbsp;00023<br />
          RCS Bordeaux — immatriculé le 01/04/2025<br />
          TVA : non applicable, article 293&nbsp;B du CGI (franchise en base)<br />
          Email : contact@blackturf.fr — Site : https://blackturf.fr
        </p>
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-bold mb-3">Directeur de la publication</h2>
        <p className="text-muted-foreground">
          Thomas BEAUMONT, en qualité d&apos;entrepreneur individuel.
        </p>
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-bold mb-3">Hébergement</h2>
        <p className="text-muted-foreground">
          Le site est hébergé par :<br />
          <strong>Hetzner Online GmbH</strong><br />
          Industriestr. 25, 91710 Gunzenhausen, Allemagne<br />
          Téléphone : +49&nbsp;(0)9831&nbsp;505-0 — Site : https://www.hetzner.com<br />
          Les données sont hébergées au sein de l&apos;Union Européenne.
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
          L&apos;ensemble des contenus du site (textes, algorithmes, interface, marque et nom commercial
          BlackTurf) est la propriété exclusive de Thomas BEAUMONT. Toute reproduction, représentation ou
          exploitation, totale ou partielle, sans autorisation écrite préalable est interdite.
        </p>
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-bold mb-3">Données personnelles &amp; cookies</h2>
        <p className="text-muted-foreground">
          Le traitement des données personnelles est détaillé dans notre{" "}
          <a href="/confidentialite" className="underline text-brand-gold">Politique de confidentialité</a>.
          Conformément au RGPD, vous disposez de droits d&apos;accès, de rectification, d&apos;effacement,
          de portabilité, de limitation et d&apos;opposition. Contact : privacy@blackturf.fr.
          Réclamation possible auprès de la CNIL (www.cnil.fr).
        </p>
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-bold mb-3">Conditions de vente</h2>
        <p className="text-muted-foreground">
          Les conditions applicables aux abonnements payants figurent dans nos{" "}
          <a href="/cgv" className="underline text-brand-gold">Conditions Générales de Vente</a>{" "}
          et nos <a href="/cgu" className="underline text-brand-gold">Conditions Générales d&apos;Utilisation</a>.
        </p>
      </section>

      <p className="text-xs text-muted-foreground mt-12">
        Dernière mise à jour : juin 2026
      </p>
    </div>
  );
}
