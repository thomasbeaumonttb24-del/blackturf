import type { Metadata } from "next";

/**
 * Espace privé : `noindex`, et `/chat` est interdit d'exploration par robots.txt.
 * Les conversations entre membres n'ont rien à faire dans un index de recherche —
 * un visiteur anonyme n'y reçoit de toute façon qu'une redirection vers la connexion.
 */
export const metadata: Metadata = {
  title: "Communauté",
  description: "Le salon de discussion en direct des membres BlackTurf.",
  robots: { index: false, follow: false },
};

export default function EspacePriveLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
