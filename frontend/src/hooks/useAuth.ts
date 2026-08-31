"use client";

import { createContext, createElement, useContext, useEffect, useState, useCallback, type ReactNode } from "react";
import { authApi, refreshSession } from "@/lib/api";
import {
  AuthUser,
  getStoredUser,
  storeUser,
  clearAuth,
  takeLegacyRefreshToken,
  clearLegacyTokens,
  hasSessionHint,
} from "@/lib/auth";
import { useRouter } from "next/navigation";

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<AuthUser>;
  register: (data: { email: string; password: string; nom?: string; prenom?: string }) => Promise<AuthUser>;
  logout: () => void;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/**
 * Fournit UN SEUL état d'auth partagé à toute l'app. Sans ce provider, chaque
 * appel à useAuth() créait son propre useState → après login, Navbar/BottomNav
 * ne se mettaient à jour qu'au refresh de page (états séparés).
 *
 * La session vit dans des cookies httpOnly : le code ne peut donc PAS savoir
 * d'avance s'il y en a une. On demande à /auth/me, qui fait autorité ; le profil
 * gardé en localStorage ne sert qu'à afficher la navbar sans attendre la réponse.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    let annule = false;

    const amorcer = async () => {
      const cached = getStoredUser();
      setUser(cached);

      // BASCULE : une session ouverte AVANT le passage aux cookies n'a que ses
      // jetons en localStorage. On les échange une fois contre des cookies, puis
      // on les efface — sinon tous ces comptes seraient déconnectés au déploiement.
      const legacy = takeLegacyRefreshToken();
      if (legacy) {
        try {
          await refreshSession(legacy);
        } catch {
          /* jeton périmé : /auth/me tranchera juste en dessous */
        }
        clearLegacyTokens();
      }

      // Visiteur sans la moindre trace de session : inutile d'aller chercher un 401.
      if (!legacy && !hasSessionHint()) {
        if (cached) clearAuth();
        if (!annule) {
          setUser(null);
          setLoading(false);
        }
        return;
      }

      try {
        const res = await authApi.me();
        if (annule) return;
        storeUser(res.data);
        setUser(res.data);
      } catch {
        // Pas de session valide (l'intercepteur d'api.ts a déjà tenté un refresh).
        // On ne laisse JAMAIS survivre un profil en cache sans session : sinon la
        // navbar affiche un compte connecté à vie, avec son ancien plan, pendant
        // que toutes les requêtes tombent en 401 (constaté en prod 2026-08-16).
        if (annule) return;
        clearAuth();
        setUser(null);
      } finally {
        if (!annule) setLoading(false);
      }
    };

    amorcer();

    // Synchro entre onglets : un login/logout dans un autre onglet met à jour celui-ci.
    const onStorage = (e: StorageEvent) => {
      if (e.key === "user") setUser(getStoredUser());
    };
    window.addEventListener("storage", onStorage);
    return () => {
      annule = true;
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    // Les cookies de session sont posés par la réponse de /auth/login.
    await authApi.login(email, password);
    try {
      const meRes = await authApi.me();
      storeUser(meRes.data);
      setUser(meRes.data);
      return meRes.data;
    } catch (e) {
      clearAuth();
      setUser(null);
      throw e;
    }
  }, []);

  const register = useCallback(
    async (data: { email: string; password: string; nom?: string; prenom?: string }) => {
      await authApi.register(data);
      try {
        const meRes = await authApi.me();
        storeUser(meRes.data);
        setUser(meRes.data);
        return meRes.data;
      } catch (e) {
        clearAuth();
        setUser(null);
        throw e;
      }
    },
    []
  );

  const logout = useCallback(() => {
    // Un cookie httpOnly ne s'efface que côté serveur : on n'attend pas la réponse
    // pour vider l'écran, mais l'appel doit partir.
    authApi.logout().catch(() => {});
    clearAuth();
    setUser(null);
    router.push("/");
  }, [router]);

  const refreshUser = useCallback(async () => {
    try {
      const res = await authApi.me();
      storeUser(res.data);
      setUser(res.data);
    } catch {
      clearAuth();
      setUser(null);
    }
  }, []);

  return createElement(
    AuthContext.Provider,
    { value: { user, loading, login, register, logout, refreshUser } },
    children
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth doit être utilisé à l'intérieur de <AuthProvider>");
  }
  return ctx;
}

export function useRequireAuth(redirectTo = "/login") {
  const { user, loading, refreshUser } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) {
      router.push(redirectTo);
    }
  }, [user, loading, router, redirectTo]);

  return { user, loading, refreshUser };
}

export function useRequirePro() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && user && ["free", "decouverte"].includes(user.plan)) {
      router.push("/tarifs");
    }
    if (!loading && !user) {
      router.push("/login");
    }
  }, [user, loading, router]);

  return { user, loading };
}
