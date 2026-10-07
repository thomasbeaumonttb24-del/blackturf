"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AuthUser } from "@/lib/auth";

/**
 * Offre anniversaire (−50 % le 1er mois, mensuel). Le code n'est JAMAIS écrit
 * dans le front : il vient du lien du mail (`/tarifs?code=…`) ou de l'API, qui
 * ne le révèle qu'aux comptes éligibles (backend/services/offre_anniversaire.py).
 */
export type OffreAnniversaire = {
  eligible: true;
  code: string;
  pourcent: number;
  fin: string;
  fin_texte: string;
  prix: Record<"standard" | "expert", { avant: number; apres: number }>;
};

// Code arrivé par le lien du mail : gardé le temps de se connecter.
const CLE_CODE = "bt_code_promo";

export function memoriserCodeDuLien(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const code = new URLSearchParams(window.location.search).get("code");
    if (code) sessionStorage.setItem(CLE_CODE, code);
    return code || sessionStorage.getItem(CLE_CODE);
  } catch {
    return null;
  }
}

// Une seule requête par compte et par chargement de page, partagée par la
// fenêtre et la page Tarifs.
type Reponse = OffreAnniversaire | { eligible: false; raison?: string };
const enCours = new Map<string, Promise<Reponse>>();

function charger(userId: string): Promise<Reponse> {
  let p = enCours.get(userId);
  if (!p) {
    p = api.get("/stripe/offre-anniversaire")
      .then((r) => r.data as Reponse)
      .catch(() => ({ eligible: false as const }));
    enCours.set(userId, p);
  }
  return p;
}

/** `offre` : l'offre (avec le code) si le compte y a droit ; `raison` : pourquoi
 *  sinon. Les deux restent nuls tant que la réponse n'est pas arrivée. */
export function useOffreAnniversaire(user: AuthUser | null): { offre: OffreAnniversaire | null; raison: string | null } {
  const [rep, setRep] = useState<Reponse | null>(null);
  useEffect(() => {
    if (!user) {
      setRep(null);
      return;
    }
    let annule = false;
    charger(user.user_id).then((r) => !annule && setRep(r));
    return () => {
      annule = true;
    };
  }, [user]);
  if (!rep) return { offre: null, raison: null };
  return rep.eligible ? { offre: rep, raison: null } : { offre: null, raison: rep.raison ?? null };
}

export function euros(cents: number): string {
  return cents % 100 === 0 ? `${cents / 100}€` : `${(cents / 100).toFixed(2).replace(".", ",")}€`;
}
