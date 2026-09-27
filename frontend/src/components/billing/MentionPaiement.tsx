"use client";

import { Gift } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";

/**
 * Mention sous les boutons d'abonnement de /tarifs. La page est rendue côté
 * serveur (référencement) : seule cette ligne dépend du compte connecté. Un
 * filleul n'a pas d'essai, mais 5 € de remise — lui annoncer « aucun
 * prélèvement avant la fin de l'essai » serait faux.
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
      Carte requise, aucun prélèvement avant la fin de l&apos;essai
    </p>
  );
}
