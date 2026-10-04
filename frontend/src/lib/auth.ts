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
  /** Nom public (classement du défi, Communauté). null = à choisir. */
  pseudo: string | null;
  is_admin?: boolean;
  // Essai ouvert mais bloqué faute de carte enregistrée : le compte reste en
  // `free` tant que le moyen de paiement n'est pas là. Sans ce signal, la perte
  // d'accès serait inexplicable pour l'abonné.
  essai_bloque_sans_carte?: boolean;
  essai_fin?: string | null;
  // Un abonnement Stripe existe et reste pilotable, MÊME quand `plan` vaut
  // `free`. Décider d'après `plan` seul cachait le portail Stripe à l'abonné
  // dont le paiement venait d'échouer — or c'est le seul endroit où changer de
  // carte, et /tarifs le refuse (409) tant que l'abonnement en échec vit.
  abonnement_gerable?: boolean;
  // Vrai tant que Stripe relance la carte. Sert à EXPLIQUER la perte d'accès.
  paiement_en_echec?: boolean;
  // Historique : essai de 7 jours encore disponible. L'essai est supprimé pour
  // les nouveaux clients (2026-10) ; le champ n'est plus lu par l'interface.
  essai_disponible?: boolean;
  // Filleul pas encore abonné : pas d'essai, 5 € déduits de son premier paiement.
  remise_parrainage?: boolean;
  // Pass sans renouvellement en cours : fin de l'accès (ISO). null = aucun pass.
  pass_fin?: string | null;
}

/** Compte sans formule payante (les deux libellés historiques du gratuit). */
export function estGratuit(user: AuthUser | null | undefined): boolean {
  return !!user && (user.plan === "free" || user.plan === "decouverte");
}

/** Compte gratuit à qui proposer directement les formules (pass dès 5 €,
 *  abonnements). Remplace `peutDemarrerEssai` : l'essai gratuit de 7 jours est
 *  supprimé pour les nouveaux clients (2026-10). Conditions : adresse confirmée
 *  (le checkout l'exige, sinon 403), aucun abonnement vivant, rien en attente de
 *  carte ni en échec de paiement. */
export function peutDebloquer(user: AuthUser | null | undefined): boolean {
  return estGratuit(user)
    && !!user!.email_verified
    && !user!.essai_bloque_sans_carte
    && !user!.paiement_en_echec
    && !user!.abonnement_gerable;
}

/** Filleul qui peut s'abonner avec sa remise de parrainage (même garde que `peutDebloquer`). */
export function peutProfiterRemise(user: AuthUser | null | undefined): boolean {
  return estGratuit(user)
    && !!user!.email_verified
    && !!user!.remise_parrainage
    && !user!.paiement_en_echec
    && !user!.abonnement_gerable;
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
