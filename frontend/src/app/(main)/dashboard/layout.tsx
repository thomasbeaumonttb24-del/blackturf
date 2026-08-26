import type { Metadata } from "next";

// Espace privé : `noindex`. Voir `assistant/layout.tsx` pour le détail.
export const metadata: Metadata = {
  title: "Tableau de bord",
  description: "Vos courses suivies, vos alertes et le résumé de votre activité du jour.",
  robots: { index: false, follow: true },
};

export default function EspacePriveLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
