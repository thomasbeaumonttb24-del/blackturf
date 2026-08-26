import type { Metadata } from "next";

/**
 * Espace privé : `noindex`.
 *
 * Cette page est interdite d'exploration par robots.txt, mais elle s'annonçait pourtant
 * « index, follow » — elle héritait du réglage du layout racine. Un visiteur anonyme n'y
 * reçoit qu'un squelette vide portant le titre de la page d'accueil, avant une
 * redirection vers la connexion côté navigateur : c'est un soft-404 pour Search Console,
 * et un doublon de titre de plus.
 *
 * Le `noindex` ne sera pas lu tant que robots.txt bloquera l'exploration — une directive
 * posée sur une page qu'un robot n'a pas le droit de charger reste lettre morte. Il est
 * là pour que la page soit correcte le jour où elle serait explorée : par un robot qui
 * ignore robots.txt, ou si l'exclusion venait à être levée.
 *
 * Le titre, lui, sert dès maintenant — c'est celui de l'onglet du navigateur.
 */
export const metadata: Metadata = {
  title: "Assistant IA",
  description:
    "Poser une question sur une course, un cheval ou une stratégie, et obtenir une réponse appuyée sur les données du site.",
  robots: { index: false, follow: true },
};

export default function EspacePriveLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
