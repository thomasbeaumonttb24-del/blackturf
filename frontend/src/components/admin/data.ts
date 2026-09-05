"use client";

/**
 * Accès aux données du back-office, en un seul endroit.
 *
 * La console est découpée en quatre pages, et la barre de navigation affiche
 * des pastilles d'alerte qui viennent des MÊMES appels que les pages. Si chaque
 * écran déclarait sa propre clé SWR, la même route serait appelée deux fois par
 * cycle de rafraîchissement — deux fois toutes les 20 s pour `/errors`.
 *
 * Ici les clés sont posées une fois : SWR déduplique, et un `mutate()` déclenché
 * depuis une page rafraîchit aussi la pastille de la barre.
 */

import * as React from "react";
import useSWR from "swr";
import { adminApi, statsApi } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import type {
  AbonnementsData, CompteLigne, DashboardData, ModelVersion,
  PalmaresNet, ScraperStatus, SystemError,
} from "./types";
import { MOUVEMENTS_ECHEC, scraperSain } from "./types";

/** Cadences. Un chiffre qui ne bouge qu'une fois par nuit n'a pas à être
 *  redemandé toutes les 20 s ; une erreur runtime, si. */
export const CADENCE = {
  vite: 20_000,
  normal: 30_000,
  lent: 60_000,
} as const;

export function useEstAdmin() {
  const { user, loading } = useAuth();
  return { estAdmin: !!user?.is_admin, chargement: loading, user };
}

export function useDashboard() {
  const { estAdmin } = useEstAdmin();
  return useSWR<DashboardData>(
    estAdmin ? "/admin-dashboard" : null,
    () => adminApi.dashboard().then((r) => r.data),
    { refreshInterval: CADENCE.normal, keepPreviousData: true },
  );
}

export function useErreurs() {
  const { estAdmin } = useEstAdmin();
  return useSWR<{ count_24h: number; errors: SystemError[] }>(
    estAdmin ? "/admin-errors" : null,
    () => adminApi.errors().then((r) => r.data),
    { refreshInterval: CADENCE.vite, keepPreviousData: true },
  );
}

export function useModeles() {
  const { estAdmin } = useEstAdmin();
  return useSWR<ModelVersion[]>(
    estAdmin ? "/admin-models" : null,
    () => adminApi.models().then((r) => r.data),
    { refreshInterval: CADENCE.lent, keepPreviousData: true },
  );
}

export function useScrapers() {
  const { estAdmin } = useEstAdmin();
  return useSWR<ScraperStatus>(
    estAdmin ? "/admin-scraper-status" : null,
    () => adminApi.scraperStatus().then((r) => r.data),
    { refreshInterval: CADENCE.lent, keepPreviousData: true },
  );
}

export function useAbonnements() {
  const { estAdmin } = useEstAdmin();
  return useSWR<AbonnementsData>(
    estAdmin ? "/admin-abonnements" : null,
    () => adminApi.abonnements().then((r) => r.data),
    { refreshInterval: CADENCE.normal, revalidateOnFocus: true, keepPreviousData: true },
  );
}

export function useComptes(recherche: string) {
  const { estAdmin } = useEstAdmin();
  return useSWR<CompteLigne[]>(
    estAdmin ? ["/admin-users", recherche] : null,
    () => adminApi.users({ limit: 200, search: recherche || undefined }).then((r) => r.data),
    { refreshInterval: CADENCE.normal, revalidateOnFocus: true, keepPreviousData: true },
  );
}

/** Rentabilité RÉELLE par profil (net + ROI) — réservé admin, hors palmarès public. */
export function usePalmaresNet() {
  const { estAdmin } = useEstAdmin();
  return useSWR<PalmaresNet>(
    estAdmin ? "/admin-palmares-net" : null,
    () => statsApi.palmaresGagnants().then((r) => r.data),
    { refreshInterval: CADENCE.lent, revalidateOnFocus: true, keepPreviousData: true },
  );
}

export interface CompteurAlertes {
  erreursOuvertes: number;
  scrapersKo: number;
  incidentsPaiement: number;
  essaisSansCarte: number;
  /** Incidents JAMAIS VUS, par destination de la navigation. */
  nouveaux: Record<string, number>;
  /** Total non vu, toutes rubriques confondues. */
  total: number;
  /** À appeler quand l'écran d'une destination est réellement affiché. */
  marquerVu: (href: string) => void;
}

/**
 * Une clé décrit UN incident, pas une de ses occurrences.
 *
 * C'est ce qui permet à une pastille de ne pas revenir à chaque battement :
 * une exception qui se répète garde son `id`, un scraper qui reste en panne
 * garde son couple source+statut. Ce qui produit une clé neuve, c'est un
 * incident neuf — ou un incident qui change de nature (`ok_but_empty` qui
 * devient `erreur`), et là il mérite bien de resonner.
 */
function clesIncidents(
  href: string,
  erreurs?: { errors: SystemError[] },
  scrapers?: ScraperStatus,
  abos?: AbonnementsData,
): string[] {
  if (href === "/admin/systeme") {
    return [
      ...(erreurs?.errors ?? []).filter((e) => !e.resolved).map((e, i) => `err:${e.id ?? `${e.source}:${e.message.slice(0, 60)}:${i}`}`),
      ...Object.entries(scrapers ?? {})
        .filter(([, s]) => !scraperSain(s.statut))
        .map(([source, s]) => `scr:${source}:${s.statut}`),
    ];
  }
  if (href === "/admin/abonnements") {
    return incidentsPaiement(abos).uniques.map((m) => `pay:${m.email ?? "?"}:${m.created_at}`);
  }
  return [];
}

const CLE_VUS = "bt.admin.incidents-vus";
/** Un acquittement ne sert plus à rien passé la fenêtre des incidents (7 j) ;
 *  borner la liste évite qu'elle grossisse indéfiniment dans le stockage. */
const MAX_VUS = 300;

function lireVus(): Record<string, string[]> {
  try {
    const brut = window.localStorage.getItem(CLE_VUS);
    return brut ? (JSON.parse(brut) as Record<string, string[]>) : {};
  } catch {
    return {};
  }
}

/**
 * Ce qui mérite qu'on quitte la page qu'on regarde — et seulement tant qu'on
 * ne l'a pas encore regardé.
 *
 * Avant, la pastille comptait un ÉTAT : un paiement échoué il y a huit heures
 * reste dans la fenêtre de sept jours, donc la pastille restait allumée après
 * lecture, indéfiniment. Une alerte qui ne s'éteint jamais cesse d'être lue —
 * c'est le mécanisme même de la lassitude aux alarmes.
 *
 * Elle compte désormais ce qui est NOUVEAU depuis la dernière fois que l'écran
 * a été ouvert. L'état, lui, ne disparaît nulle part : le bloc « Ce qui demande
 * une action » du Pilotage et les écrans eux-mêmes continuent de tout montrer.
 * La pastille dit « viens voir », la page dit « voilà où on en est ».
 *
 * Les incidents restent comptés en INCIDENTS, pas en lignes : un seul échec de
 * paiement écrit deux mouvements à quelques secondes d'écart (le statut Stripe
 * `past_due`, puis `paiement_echoue`). Compter les lignes annoncerait deux
 * échecs pour un.
 */
export function useAlertes(): CompteurAlertes {
  const { data: erreurs } = useErreurs();
  const { data: scrapers } = useScrapers();
  const { data: abos } = useAbonnements();

  // `null` tant que le stockage n'a pas été lu : côté serveur et au premier
  // rendu, on ne connaît pas les acquittements. Afficher une pastille pleine
  // puis la voir s'éteindre serait un clignotement à chaque navigation.
  const [vus, setVus] = React.useState<Record<string, string[]> | null>(null);
  React.useEffect(() => { setVus(lireVus()); }, []);

  const erreursOuvertes = (erreurs?.errors ?? []).filter((e) => !e.resolved).length;
  const scrapersKo = Object.values(scrapers ?? {}).filter((s) => !scraperSain(s.statut)).length;
  const nbIncidentsPaiement = incidentsPaiement(abos).uniques.length;
  const essaisSansCarte = abos?.resume.en_essai_sans_carte ?? 0;

  const marquerVu = React.useCallback((href: string) => {
    const cles = clesIncidents(href, erreurs, scrapers, abos);
    setVus((precedent) => {
      const base = precedent ?? lireVus();
      const deja = base[href] ?? [];
      const inconnues = cles.filter((c) => !deja.includes(c));
      if (inconnues.length === 0) return base;
      const suivant = { ...base, [href]: [...deja, ...inconnues].slice(-MAX_VUS) };
      try { window.localStorage.setItem(CLE_VUS, JSON.stringify(suivant)); } catch { /* stockage refusé */ }
      return suivant;
    });
  }, [erreurs, scrapers, abos]);

  const nouveaux: Record<string, number> = {};
  for (const href of ["/admin/systeme", "/admin/abonnements"]) {
    const cles = clesIncidents(href, erreurs, scrapers, abos);
    const deja = vus?.[href] ?? [];
    // Tant que le stockage n'est pas lu, on n'annonce rien : mieux vaut une
    // pastille qui arrive avec un temps de retard qu'une qui s'allume à tort.
    nouveaux[href] = vus === null ? 0 : cles.filter((c) => !deja.includes(c)).length;
  }

  return {
    erreursOuvertes,
    scrapersKo,
    incidentsPaiement: nbIncidentsPaiement,
    essaisSansCarte,
    nouveaux,
    total: Object.values(nouveaux).reduce((s, n) => s + n, 0),
    marquerVu,
  };
}

/** Incidents de paiement des 7 derniers jours, dédoublonnés — vue détaillée. */
export function incidentsPaiement(abos?: AbonnementsData) {
  const echecs = (abos?.mouvements ?? [])
    .filter((m) => MOUVEMENTS_ECHEC.has(m.type)
      && Date.now() - new Date(m.created_at).getTime() < 7 * 86_400_000)
    .sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at));
  const uniques = echecs.filter((m, i) => !echecs.slice(0, i).some(
    (p) => p.email === m.email
      && Math.abs(+new Date(p.created_at) - +new Date(m.created_at)) < 5 * 60_000,
  ));
  return { tous: echecs, uniques, dernier: echecs[0] };
}
