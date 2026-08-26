// Les pages d'authentification n'ont pas de chrome (ni Navbar ni Footer) : sans ce
// layout, aucune d'elles n'exposait de repère `main`. Une page sans repère principal
// oblige un lecteur d'écran — et un agent qui parcourt le DOM — à lire l'en-tête et la
// navigation avant d'atteindre le formulaire.
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return <main id="contenu">{children}</main>;
}
