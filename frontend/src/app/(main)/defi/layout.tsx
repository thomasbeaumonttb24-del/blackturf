import type { Metadata } from "next";
import { ogBase, twitterBase } from "@/lib/seo";

// La page affiche le mois en cours et le compte à rebours de fin de mois : rendue à
// chaque visite, sinon le HTML figé au build dirait « Septembre · J-3 » en octobre et
// l'hydratation échouerait dès le lendemain du déploiement.
export const dynamic = "force-dynamic";

// Page publique : le classement se consulte sans compte, c'est ce qui donne envie
// d'en ouvrir un pour jouer.
const TITLE = "Défi du mois : concours de pronostics PMU gratuit";
const DESCRIPTION =
  "Le concours de pronostics BlackTurf : 1 000 points par mois, des paris réglés au rapport PMU officiel, et 30 jours Expert offerts au meilleur solde.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/defi" },
  openGraph: ogBase({ title: TITLE, description: DESCRIPTION, url: "/defi" }),
  twitter: twitterBase({ title: TITLE, description: DESCRIPTION }),
};

export default function DefiLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
