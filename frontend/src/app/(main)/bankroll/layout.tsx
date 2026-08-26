import type { Metadata } from "next";

// Espace privé : `noindex`. Voir `assistant/layout.tsx` pour le détail — même situation,
// même raison : la page s'annonçait « index, follow » en héritant du layout racine, alors
// qu'elle ne sert qu'un squelette vide à un visiteur anonyme.
export const metadata: Metadata = {
  title: "Suivi du capital",
  description:
    "Le journal de vos mises et de vos gains, course par course, avec l'évolution réelle de votre capital.",
  robots: { index: false, follow: true },
};

export default function EspacePriveLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
