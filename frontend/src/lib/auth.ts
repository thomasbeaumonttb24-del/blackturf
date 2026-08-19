"use client";

export interface AuthUser {
  user_id: string;
  email: string;
  nom: string | null;
  prenom: string | null;
  plan: "free" | "decouverte" | "starter" | "standard" | "expert";
  created_at: string;
  profil_risque: string;
  email_verified: boolean;
  bankroll_initiale: number | null;
  is_admin?: boolean;
}

// Les JETONS ne sont plus stockés ici : ils vivent dans des cookies httpOnly posés
// par l'API, donc hors de portée de JavaScript — une XSS ne peut plus les lire.
// Seul le profil affiché reste en cache local : ce n'est pas un identifiant de
// session, juste de quoi peindre la navbar sans attendre /auth/me.
const USER_KEY = "user";
const LEGACY_ACCESS = "access_token";
const LEGACY_REFRESH = "refresh_token";

export function getStoredUser(): AuthUser | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(USER_KEY);
  try {
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function storeUser(user: AuthUser) {
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearAuth() {
  localStorage.removeItem(USER_KEY);
  // Reliquats des sessions d'avant les cookies : on les efface pour de bon.
  localStorage.removeItem(LEGACY_ACCESS);
  localStorage.removeItem(LEGACY_REFRESH);
}

/**
 * Jeton de rafraîchissement laissé par une session ouverte AVANT le passage aux
 * cookies. Sert une seule fois, au chargement : on l'échange contre des cookies
 * puis on le supprime (cf. AuthProvider). Sans cela, tous ces comptes seraient
 * déconnectés d'un coup au déploiement.
 */
export function takeLegacyRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  const token = localStorage.getItem(LEGACY_REFRESH);
  return token || null;
}

export function clearLegacyTokens() {
  localStorage.removeItem(LEGACY_ACCESS);
  localStorage.removeItem(LEGACY_REFRESH);
}

/**
 * Y a-t-il une session ouverte ? Les cookies de session sont httpOnly, donc
 * invisibles ici ; l'API pose en plus un témoin LISIBLE (`bt_session=1`, aucune
 * valeur secrète) sur le domaine parent. Sans lui, chaque visiteur anonyme
 * déclencherait un /auth/me en 401 à chaque chargement de page.
 */
export function hasSessionHint(): boolean {
  if (typeof document === "undefined") return false;
  return document.cookie.split("; ").some((c) => c.startsWith("bt_session="));
}
