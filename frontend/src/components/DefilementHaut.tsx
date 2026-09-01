"use client";

import { useEffect } from "react";
import { usePathname, useSearchParams } from "next/navigation";

/**
 * Toute page s'ouvre EN HAUT.
 *
 * Le problème observé : en ouvrant l'onglet « Plan de mise » d'une fiche course, on
 * atterrissait en bas de page. Deux mécanismes s'additionnaient.
 *
 * 1. Les onglets de la fiche course réécrivent l'URL en `#plan`, `#marche`… via
 *    `history.replaceState`. Au RECHARGEMENT de cette URL, le navigateur restaure la
 *    position de défilement mémorisée pour elle — celle où l'on était dans l'onglet
 *    précédent, souvent bien plus long. On arrivait donc au milieu, ou en bas quand le
 *    nouvel onglet est plus court.
 *
 * 2. Le contenu arrive APRÈS le premier rendu (les données de course sont chargées côté
 *    client). La restauration navigateur s'applique à une page encore courte, puis la
 *    page grandit : la position finale n'a aucun rapport avec celle qu'on avait quittée.
 *
 * On coupe donc la restauration automatique et on remonte en haut à chaque changement
 * d'URL. `scrollRestoration = "manual"` désactive aussi la restauration sur Précédent /
 * Suivant : c'est assumé et c'est le comportement demandé — une page s'ouvre toujours en
 * haut, quel que soit le chemin par lequel on y arrive.
 *
 * Ce que ce composant ne casse PAS :
 * — les ancres réelles (`<a href="#section">`) cliquées dans la page : elles ne changent
 *   ni le chemin ni les paramètres, donc l'effet ne se redéclenche pas ;
 * — le changement d'onglet SANS rechargement : lui aussi ne touche qu'au fragment.
 *
 * `useSearchParams` impose une frontière Suspense côté appelant (règle Next : ce hook
 * bloque le pré-rendu statique). Le composant est donc monté sous `<Suspense>` dans le
 * layout racine, sinon toutes les pages basculeraient en rendu dynamique.
 */
export default function DefilementHaut() {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (typeof window === "undefined") return;
    // Certains navigateurs en mode privé refusent l'écriture : ne jamais casser la
    // page pour un réglage de confort.
    try {
      if ("scrollRestoration" in window.history) {
        window.history.scrollRestoration = "manual";
      }
    } catch {
      /* réglage indisponible : on remonte quand même ci-dessous */
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    // `instant` et non `smooth` : à l'ouverture d'une page, une animation de défilement
    // donne l'impression que la page a bougé toute seule.
    window.scrollTo({ top: 0, left: 0, behavior: "instant" as ScrollBehavior });
  }, [pathname, searchParams]);

  return null;
}
