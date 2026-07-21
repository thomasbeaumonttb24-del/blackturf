import Link from "next/link";
import type { Metadata } from "next";

// Page 404 globale : renvoie un vrai statut HTTP 404 (Next) avec un contenu utile +
// liens de retour, au lieu d'un soft-404. noindex pour ne pas polluer l'index.
export const metadata: Metadata = {
  title: "Page introuvable",
  robots: { index: false, follow: true },
};

export default function NotFound() {
  return (
    <main className="flex min-h-[60vh] flex-col items-center justify-center px-6 text-center">
      <p className="font-mono text-5xl font-bold text-brand-gold">404</p>
      <h1 className="mt-3 text-xl font-bold">Cette page n&apos;existe pas (ou plus)</h1>
      <p className="mt-2 max-w-md text-sm text-muted-foreground">
        La course ou la page demandée est introuvable. Elle a peut-être été retirée,
        ou l&apos;adresse est incorrecte.
      </p>
      <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
        <Link
          href="/programme"
          className="rounded-lg bg-brand-gold px-4 py-2 text-sm font-bold text-brand-dark transition-colors hover:bg-brand-amber"
        >
          Programme du jour
        </Link>
        <Link
          href="/"
          className="rounded-lg border border-border px-4 py-2 text-sm font-semibold text-muted-foreground transition-colors hover:text-foreground"
        >
          Accueil
        </Link>
      </div>
    </main>
  );
}
