"use client";

import { useState } from "react";
import { CreditCard } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";

/**
 * Essai ouvert, carte manquante, accès fermé.
 *
 * Depuis le 2026-08-20 un essai sans moyen de paiement n'ouvre plus l'accès :
 * l'abonnement existe chez Stripe, mais le compte reste en `free`. Sans ce
 * rappel, l'abonné vivrait une panne inexplicable — il a « pris un abonnement »
 * et ne voit rien. Le bandeau dit ce qui manque et mène droit au portail Stripe,
 * seul endroit où saisir une carte (l'application ne touche jamais aux données
 * bancaires).
 *
 * Volontairement NON masquable : il n'y a rien d'autre à faire dans
 * l'application tant que la carte n'est pas enregistrée.
 */
export function EssaiSansCarteBanner() {
  const { user, loading } = useAuth();
  const [ouverture, setOuverture] = useState(false);

  if (loading || !user || !user.essai_bloque_sans_carte) return null;

  const finEssai = user.essai_fin
    ? new Date(user.essai_fin).toLocaleDateString("fr-FR", { timeZone: "Europe/Paris", day: "2-digit", month: "long", hour: "2-digit", minute: "2-digit",
      })
    : null;

  const ouvrirPortail = async () => {
    setOuverture(true);
    try {
      const { data } = await api.post("/stripe/portal");
      window.location.assign(data.url);
    } catch {
      toast.error("Impossible d'ouvrir la gestion de paiement pour le moment");
      setOuverture(false);
    }
  };

  return (
    <div className="border-b border-amber-200 bg-amber-50">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm text-amber-900">
        <CreditCard className="h-4 w-4 shrink-0" aria-hidden />
        <p className="min-w-0 flex-1">
          Votre essai est ouvert mais <span className="font-semibold">aucune carte n&apos;est
          enregistrée</span> : l&apos;accès reste fermé tant qu&apos;elle manque.
          {finEssai ? ` Votre essai court jusqu'au ${finEssai}.` : ""} Aucun montant
          n&apos;est prélevé avant la fin de l&apos;essai.
        </p>
        <button
          onClick={ouvrirPortail}
          disabled={ouverture}
          className="font-semibold underline underline-offset-2 hover:text-amber-950 disabled:opacity-50"
        >
          {ouverture ? "Ouverture…" : "Enregistrer ma carte"}
        </button>
      </div>
    </div>
  );
}
