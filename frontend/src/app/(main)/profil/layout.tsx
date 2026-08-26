import type { Metadata } from "next";

// Espace privé : `noindex`. Voir `assistant/layout.tsx` pour le détail.
export const metadata: Metadata = {
  title: "Mon compte",
  description: "Vos informations, votre abonnement et vos préférences de notification.",
  robots: { index: false, follow: true },
};

export default function EspacePriveLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
