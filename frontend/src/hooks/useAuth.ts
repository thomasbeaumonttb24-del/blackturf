"use client";

import { useEffect, useState, useCallback } from "react";
import { authApi } from "@/lib/api";
import { AuthUser, getStoredUser, storeTokens, storeUser, clearAuth } from "@/lib/auth";
import { useRouter } from "next/navigation";

export function useAuth() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    const stored = getStoredUser();
    if (stored) {
      setUser(stored);
    }
    setLoading(false);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const res = await authApi.login(email, password);
    const { access_token, refresh_token } = res.data;
    storeTokens(access_token, refresh_token);

    const meRes = await authApi.me();
    storeUser(meRes.data);
    setUser(meRes.data);
    return meRes.data;
  }, []);

  const register = useCallback(
    async (data: { email: string; password: string; nom?: string; prenom?: string }) => {
      const res = await authApi.register(data);
      const { access_token, refresh_token } = res.data;
      storeTokens(access_token, refresh_token);

      const meRes = await authApi.me();
      storeUser(meRes.data);
      setUser(meRes.data);
      return meRes.data;
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

  return { user, loading, login, register, logout, refreshUser };
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
