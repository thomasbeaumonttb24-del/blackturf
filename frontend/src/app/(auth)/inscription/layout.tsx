import type { Metadata } from "next";
import { OG_IMAGE } from "@/lib/seo";

// La page elle-même est un composant client (formulaire) : elle ne peut pas exporter de
// `metadata`. Sans ce layout, /inscription héritait du titre et de la description de
// l'accueil — deux pages avec le même titre, ce que Google traite comme un doublon, et
// une description qui ne parlait pas du tout de la création de compte.
export const metadata: Metadata = {
  title: "Créer un compte gratuit",
  description:
    "Compte BlackTurf gratuit : programme PMU du jour, prédictions de l'algorithme et plan de mise. 1 classement offert chaque jour, tout débloqué dès 5 € sans abonnement.",
  alternates: { canonical: "/inscription" },
  openGraph: {
    title: "Créer un compte BlackTurf",
    description:
      "Programme PMU du jour, prédictions de l'algorithme et plan de mise sur votre budget. Compte gratuit, pass dès 5 €.",
    url: "https://blackturf.fr/inscription",
    images: [OG_IMAGE],
  },
};

export default function InscriptionLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
