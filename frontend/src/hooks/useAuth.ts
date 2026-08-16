"use client";

import { createContext, createElement, useContext, useEffect, useState, useCallback, type ReactNode } from "react";
import { authApi } from "@/lib/api";
import { AuthUser, getStoredUser, storeTokens, storeUser, clearAuth } from "@/lib/auth";
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
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    const cached = getStoredUser();
    setUser(cached);
    setLoading(false);
    // Revalide la session au chargement : un access_token expire (ex. mobile) ne doit pas
    // laisser un "user" fantome connecte (-> "aucune analyse disponible"). On appelle
    // /auth/me meme si access_token a disparu du localStorage (mais pas "user") : sans
    // token la requete part sans header, 401 "Not authenticated", l intercepteur tente le
    // refresh via refresh_token, et si ca echoue aussi il nettoie et redirige vers /login.
    // Avant ce fix, ce cas (access_token absent, "user" encore en cache) ne revalidait
    // jamais rien : navbar affichait "connecte" a vie, toutes les requetes API 401
    // silencieuses, aucune analyse IA / plan de mise ne s'affichait jamais.
    if (cached && typeof window !== "undefined") {
      authApi
        .me()
        .then((res) => {
          storeUser(res.data);
          setUser(res.data);
        })
        .catch(() => {
          /* gere par l intercepteur api (refresh / redirect) */
        });
    }
    // Synchro entre onglets : un login/logout dans un autre onglet met à jour celui-ci.
    const onStorage = (e: StorageEvent) => {
      if (e.key === "access_token" || e.key === "user") {
        setUser(getStoredUser());
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const res = await authApi.login(email, password);
    const { access_token, refresh_token } = res.data;
    storeTokens(access_token, refresh_token);
    try {
      const meRes = await authApi.me();
      storeUser(meRes.data);
      setUser(meRes.data);
      return meRes.data;
    } catch (e) {
      // me() a échoué après stockage des tokens → état incohérent : on nettoie.
      clearAuth();
      setUser(null);
      throw e;
    }
  }, []);

  const register = useCallback(
    async (data: { email: string; password: string; nom?: string; prenom?: string }) => {
      const res = await authApi.register(data);
      const { access_token, refresh_token } = res.data;
      storeTokens(access_token, refresh_token);
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
