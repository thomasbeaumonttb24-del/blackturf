"use client";

/**
 * Code du lien de parrainage (`/inscription?parrain=…`).
 *
 * Mémorisé 30 jours : le visiteur qui arrive par le lien, ferme l'onglet et
 * revient s'inscrire plus tard garde sa remise. Le serveur reste seul juge —
 * un code mémorisé mais devenu invalide est simplement ignoré à l'affichage.
 */
const CLE = "bt_code_parrain";
const DUREE_MS = 30 * 24 * 3600 * 1000;

export function normaliserCode(valeur: string | null | undefined): string | null {
  const code = (valeur || "").toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 12);
  return code.length >= 6 ? code : null;
}

export function memoriserCodeParrain(code: string) {
  try {
    localStorage.setItem(CLE, JSON.stringify({ code, t: Date.now() }));
  } catch {
    /* stockage indisponible : le code reste dans l'URL */
  }
}

export function lireCodeParrain(): string | null {
  try {
    const brut = localStorage.getItem(CLE);
    if (!brut) return null;
    const v = JSON.parse(brut) as { code?: string; t?: number };
    if (!v.t || Date.now() - v.t > DUREE_MS) return null;
    return normaliserCode(v.code);
  } catch {
    return null;
  }
}

export function oublierCodeParrain() {
  try {
    localStorage.removeItem(CLE);
  } catch {
    /* rien à faire */
  }
}

export function euros(cents: number): string {
  return `${(cents / 100).toFixed(cents % 100 ? 2 : 0).replace(".", ",")} €`;
}
