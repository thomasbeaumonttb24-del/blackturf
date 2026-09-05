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
  /** Total porté par la barre de navigation, toutes rubriques confondues. */
  total: number;
}

/**
 * Ce qui mérite qu'on quitte la page qu'on regarde.
 *
 * Compté en INCIDENTS, pas en lignes : un seul échec de paiement écrit deux
 * mouvements à quelques secondes d'écart (le statut Stripe `past_due`, puis
 * `paiement_echoue`). Compter les lignes annoncerait deux échecs pour un.
 */
export function useAlertes(): CompteurAlertes {
  const { data: erreurs } = useErreurs();
  const { data: scrapers } = useScrapers();
  const { data: abos } = useAbonnements();

  const erreursOuvertes = (erreurs?.errors ?? []).filter((e) => !e.resolved).length;
  const scrapersKo = Object.values(scrapers ?? {}).filter((s) => !scraperSain(s.statut)).length;

  const echecs = (abos?.mouvements ?? [])
    .filter((m) => MOUVEMENTS_ECHEC.has(m.type)
      && Date.now() - new Date(m.created_at).getTime() < 7 * 86_400_000)
    .sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at));
  const incidentsPaiement = echecs.filter((m, i) => !echecs.slice(0, i).some(
    (p) => p.email === m.email
      && Math.abs(+new Date(p.created_at) - +new Date(m.created_at)) < 5 * 60_000,
  )).length;

  const essaisSansCarte = abos?.resume.en_essai_sans_carte ?? 0;

  return {
    erreursOuvertes,
    scrapersKo,
    incidentsPaiement,
    essaisSansCarte,
    total: erreursOuvertes + scrapersKo + incidentsPaiement,
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
