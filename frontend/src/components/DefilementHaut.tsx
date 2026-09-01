"use client";

import { useEffect, useRef } from "react";
import { usePathname, useSearchParams } from "next/navigation";

/**
 * Une page s'ouvre EN HAUT — sauf quand l'URL désigne une section qui existe.
 *
 * Deux mécanismes distincts renvoyaient le lecteur au milieu ou en bas d'une page.
 * Ils ont été mesurés séparément sur la production avant d'écrire ce composant :
 *
 *  A. RECHARGEMENT — le navigateur restaure la position mémorisée pour l'URL. Sur une
 *     fiche course rechargée en `#plan` : 1 004 px restaurés sur une page de 1 724,
 *     soit le bas. Le contenu arrivant après le premier rendu, la position restaurée
 *     n'a de toute façon aucun rapport avec la page finale.
 *
 *  B. FRAGMENTS SANS CIBLE — les onglets de la fiche course écrivent `#plan`,
 *     `#partants`, `#marche`… alors qu'AUCUN élément ne porte ces identifiants
 *     (vérifié : `getElementById('plan')` renvoie null). Ce sont des fragments d'état,
 *     pas des ancres. Le navigateur ne saute nulle part et la position reste celle
 *     d'avant.
 *
 * D'où la règle, qui distingue les deux familles de fragments par leur CIBLE :
 *
 *     fragment avec un élément correspondant  → ne rien faire, le navigateur a sauté
 *     fragment sans élément, ou pas de fragment → remonter en haut
 *
 * C'est ce que la première version ratait : elle remontait en haut sans regarder, et
 * écrasait le saut d'ancre réussi de `/#tarifs` (mesuré : 8 638 px avant, 0 après).
 * Les ancres réelles du site — `#contenu` (lien d'évitement clavier), `#tarifs`,
 * `#faq`, `#preuves`… — sont rendues côté serveur, donc leur cible existe dès le
 * premier rendu. Le test `getElementById` les reconnaît.
 *
 * `useSearchParams` impose une frontière Suspense côté appelant : sans elle, toutes
 * les pages basculeraient en rendu dynamique et perdraient leur ISR.
 */
export default function DefilementHaut() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const premierRendu = useRef(true);

  useEffect(() => {
    if (typeof window === "undefined") return;
    // Couper la restauration de position : c'est elle qui rouvre une page au milieu
    // après un rechargement. Certains navigateurs en mode privé refusent l'écriture —
    // ne jamais casser la page pour un réglage de confort.
    try {
      if ("scrollRestoration" in window.history) {
        window.history.scrollRestoration = "manual";
      }
    } catch {
      /* réglage indisponible : la remise à zéro ci-dessous suffit dans la plupart des cas */
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;

    // PREMIER MONTAGE — on ne demande pas POURQUOI le navigateur aurait défilé, on
    // regarde s'il l'a FAIT. Tester le fragment ne suffit pas : Chrome retire la
    // directive `:~:text=` de `location.hash` avant de la donner au document, pour que
    // les pages ne puissent pas lire ce que l'utilisateur a cherché. Une page arrivant
    // d'un extrait en vedette Google voit donc un hash VIDE alors que le navigateur l'a
    // positionnée sur un passage. Un test `getElementById` l'aurait ratée.
    //
    // La position déjà prise couvre les trois cas d'un coup — ancre `id`, fragment de
    // texte, lien profond — sans avoir à les distinguer : si le navigateur a positionné
    // la page, c'est une intention de l'appelant et on ne l'écrase pas.
    //
    // `requestAnimationFrame` laisse au navigateur le temps d'appliquer ce saut avant
    // qu'on lise `scrollY` : le lire dans l'effet lui-même donnerait 0 trop tôt.
    if (premierRendu.current) {
      premierRendu.current = false;
      window.requestAnimationFrame(() => {
        if (window.scrollY === 0) {
          window.scrollTo({ top: 0, left: 0, behavior: "instant" as ScrollBehavior });
        }
      });
      return;
    }

    // NAVIGATIONS SUIVANTES — une ancre reste respectée : elle ne change ni le chemin
    // ni les paramètres, donc cet effet ne se déclenche pas pour elle.
    const fragment = window.location.hash;
    if (fragment.length > 1) {
      let cible: Element | null = null;
      try {
        cible = document.getElementById(decodeURIComponent(fragment.slice(1)));
      } catch {
        cible = null;            // fragment non décodable : traité comme sans cible
      }
      if (cible) return;
    }

    // `instant` et non `smooth` : à l'ouverture d'une page, une animation donne
    // l'impression que la page a bougé toute seule.
    window.scrollTo({ top: 0, left: 0, behavior: "instant" as ScrollBehavior });
  }, [pathname, searchParams]);

  return null;
}
