"use client";

import { Gift } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";

/**
 * Mention sous les boutons d'abonnement de /tarifs. La page est rendue côté
 * serveur (référencement) : seule cette ligne dépend du compte connecté. Un
 * filleul a 5 € de remise sur son premier paiement : la ligne le lui dit.
 * Contexte abonnement (Standard / Expert) : l'essai gratuit n'existe plus.
 */
export function MentionPaiement() {
  const { user } = useAuth();
  if (user?.remise_parrainage) {
    return (
      <p className="mt-2 flex items-center justify-center gap-1.5 text-center text-xs font-medium text-emerald-700">
        <Gift className="h-3.5 w-3.5" aria-hidden /> Parrainage : 5 € déduits de votre premier paiement
      </p>
    );
  }
  return (
    <p className="text-center text-xs text-muted-foreground mt-2">
      Paiement sécurisé Stripe · résiliable à tout moment depuis votre profil
    </p>
  );
}
