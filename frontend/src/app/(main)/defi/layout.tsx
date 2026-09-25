import type { Metadata } from "next";

// Page publique : le classement se consulte sans compte, c'est ce qui donne envie
// d'en ouvrir un pour jouer.
export const metadata: Metadata = {
  title: "Défi du mois",
  description:
    "Le concours de pronostics BlackTurf : 1 000 points par mois, des paris réglés au rapport PMU officiel, et un abonnement offert au meilleur solde.",
};

export default function DefiLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
