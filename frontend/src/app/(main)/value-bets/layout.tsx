import type { Metadata } from "next";

/**
 * `/value-bets` — paris de valeur du jour.
 *
 * Reste en `noindex` : la page n'a de sens qu'à l'instant présent, son contenu est
 * réservé aux abonnés, et son HTML servi ne contient qu'un squelette côté client. Une
 * page indexée sur laquelle un visiteur venu de Google tombe sur un écran vide est un
 * soft-404 pour Search Console, et une déception pour le visiteur.
 *
 * En revanche elle porte désormais SON titre : sans métadonnées propres, elle héritait de
 * ceux de la page d'accueil. Un `noindex` évite l'indexation, il n'empêche ni le partage,
 * ni l'affichage du titre dans un onglet, ni sa reprise par un agent conversationnel.
 * L'intention pédagogique est renvoyée vers le guide, lui indexable.
 */
const TITLE = "Paris de valeur du jour";
const DESCRIPTION =
  "Les chevaux dont la probabilité calculée dépasse ce que dit leur cote, course par course. Mis à jour en continu jusqu'au départ.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  // `follow` : le crawler ne retient pas la page mais suit ses liens sortants.
  robots: { index: false, follow: true },
};

export default function NoIndexLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
