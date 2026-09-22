"use client";

/**
 * Ce que le visiteur voulait faire QUAND il a créé son compte.
 *
 * L'inscription ne connecte pas : elle envoie un lien de confirmation, et la
 * session ne s'ouvre qu'au clic dans l'e-mail. Entre les deux, `?plan=expert`
 * (bouton « Essayer 7 jours » de /tarifs) et la page d'origine (une course, le
 * marché des cotes) étaient perdus — l'écran de confirmation renvoyait tout le
 * monde vers /programme, sans un mot sur l'essai.
 *
 * Gardé en localStorage : si le lien est ouvert sur un autre appareil, rien n'est
 * retrouvé et l'écran de confirmation retombe sur ses valeurs par défaut (essai
 * Standard, programme). Chaque accès est protégé : le stockage peut lever.
 */
const CLE = "bt_intention_inscription";
const DUREE_MS = 7 * 24 * 3600 * 1000;

export type PlanEssai = "standard" | "expert";

export interface IntentionInscription {
  plan: PlanEssai | null;
  suite: string | null;
}

/** Chemin interne uniquement : un `?suite=https://…` ne doit jamais faire sortir du site. */
export function cheminInterne(valeur: string | null | undefined): string | null {
  if (!valeur || !valeur.startsWith("/") || valeur.startsWith("//") || valeur.includes("\\")) return null;
  return valeur;
}

export function planEssai(valeur: string | null | undefined): PlanEssai | null {
  return valeur === "standard" || valeur === "expert" ? valeur : null;
}

export function memoriserIntention(intention: IntentionInscription) {
  try {
    localStorage.setItem(CLE, JSON.stringify({ ...intention, t: Date.now() }));
  } catch {
    /* stockage indisponible : l'écran de confirmation prendra ses valeurs par défaut */
  }
}

export function lireIntention(): IntentionInscription {
  try {
    const brut = localStorage.getItem(CLE);
    if (!brut) return { plan: null, suite: null };
    const v = JSON.parse(brut) as { plan?: string; suite?: string; t?: number };
    if (!v.t || Date.now() - v.t > DUREE_MS) return { plan: null, suite: null };
    return { plan: planEssai(v.plan), suite: cheminInterne(v.suite) };
  } catch {
    return { plan: null, suite: null };
  }
}

export function oublierIntention() {
  try {
    localStorage.removeItem(CLE);
  } catch {
    /* rien à faire */
  }
}
