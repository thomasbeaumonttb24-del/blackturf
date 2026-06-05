"use client";

export interface AuthUser {
  user_id: string;
  email: string;
  nom: string | null;
  prenom: string | null;
  plan: "free" | "decouverte" | "starter" | "standard" | "pro" | "expert";
  created_at: string;
  profil_risque: string;
  email_verified: boolean;
  bankroll_initiale: number | null;
  is_admin?: boolean;
}

export function getStoredUser(): AuthUser | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem("user");
  try {
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function storeTokens(accessToken: string, refreshToken: string) {
  localStorage.setItem("access_token", accessToken);
  localStorage.setItem("refresh_token", refreshToken);
}

export function storeUser(user: AuthUser) {
  localStorage.setItem("user", JSON.stringify(user));
}

export function clearAuth() {
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
  localStorage.removeItem("user");
}

export function isAuthenticated(): boolean {
  return !!localStorage.getItem("access_token");
}

export function getAccessToken(): string | null {
  return localStorage.getItem("access_token");
}
