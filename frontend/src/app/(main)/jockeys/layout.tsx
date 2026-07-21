import type { Metadata } from "next";

// Pages sans contenu indexable (gated / shell client / recherche interne) : noindex pour
// éviter le "Crawled - currently not indexed" / thin content dans Search Console.
// follow:true → le crawler suit quand même les liens sortants. (À retirer le jour où la
// page passe en SSR avec contenu réel — ex. statistiques / track-record = potentiel SEO.)
export const metadata: Metadata = {
  robots: { index: false, follow: true },
};

export default function NoIndexLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
