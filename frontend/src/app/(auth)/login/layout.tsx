import type { Metadata } from "next";

// Page de connexion : aucune valeur en recherche, et elle portait jusqu'ici le titre et la
// description de l'accueil — un doublon pur aux yeux de Google. `noindex, follow` la
// retire de l'index sans couper le suivi des liens. Elle est aussi sortie du sitemap :
// une URL en noindex listée dans un sitemap est un signal contradictoire.
export const metadata: Metadata = {
  title: "Connexion",
  description: "Connectez-vous à votre compte BlackTurf.",
  robots: { index: false, follow: true },
  alternates: { canonical: "/login" },
};

export default function LoginLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
