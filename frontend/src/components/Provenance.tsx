"use client";

/**
 * Provenance de la visite — mesure ce que rapporte chaque publication ou publicité.
 *
 * Arrivée avec `utm_source` (lien de bio, publicité Facebook/Instagram…) : on garde
 * « source:campagne » 30 jours dans le cookie `bt_src`, PREMIÈRE visite seulement
 * (un retour plus tard par un autre lien ne réécrit pas l'origine). L'API le relit
 * à la création du compte et le range dans `users.provenance`. Rien d'autre ne part :
 * ni identifiant, ni page, ni outil tiers.
 */

import { useEffect } from "react";

const COOKIE = "bt_src";
const nettoyer = (v: string | null) => (v ?? "").toLowerCase().replace(/[^a-z0-9_.-]/g, "").slice(0, 38);

export default function Provenance() {
  useEffect(() => {
    try {
      if (document.cookie.split("; ").some((c) => c.startsWith(`${COOKIE}=`))) return;
      const q = new URLSearchParams(window.location.search);
      const source = nettoyer(q.get("utm_source"));
      if (!source) return;
      const campagne = nettoyer(q.get("utm_campaign"));
      const valeur = campagne ? `${source}:${campagne}` : source;
      // Domaine parent : l'API peut vivre sur un sous-domaine (api.blackturf.fr).
      const domaine = window.location.hostname.endsWith("blackturf.fr") ? "; domain=.blackturf.fr" : "";
      const secure = window.location.protocol === "https:" ? "; secure" : "";
      document.cookie = `${COOKIE}=${valeur}; path=/; max-age=${30 * 86400}; samesite=lax${domaine}${secure}`;
    } catch {
      /* cookies refusés : visite non attribuée, rien de plus */
    }
  }, []);
  return null;
}
