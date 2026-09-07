"use client";

import { useState } from "react";
import { AlertTriangle } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";

/**
 * Prélèvement refusé par la banque, accès coupé, carte à remplacer.
 *
 * Depuis le 2026-08-27 un impayé rétrograde immédiatement le compte en `free`
 * (décision de l'exploitant : la fenêtre de relance de Stripe dure jusqu'à trois
 * semaines, c'était trois semaines de produit livré sans un centime encaissé).
 * L'abonnement Stripe, lui, reste vivant et les relances suivent leur cours.
 *
 * L'impasse que ce bandeau ferme, constatée le 2026-09-03 sur deux abonnés à
 * 19 €/mois : la rétrogradation en `free` faisait disparaître de la page profil
 * le bouton « Gérer l'abonnement via Stripe » — le seul chemin pour changer de
 * carte — et /tarifs refusait un nouveau checkout (409, `past_due` compte parmi
 * les statuts vivants) en renvoyant vers ce bouton devenu invisible. L'abonné
 * perdait l'accès sans un mot et sans porte de sortie.
 *
 * Volontairement NON masquable : tant que la carte n'est pas remplacée, il n'y a
 * rien d'autre à faire dans l'application.
 */
export function PaiementEchoueBanner() {
  const { user, loading } = useAuth();
  const [ouverture, setOuverture] = useState(false);

  // `essai_bloque_sans_carte` a son propre bandeau et sa propre explication :
  // deux bandeaux empilés diraient deux fois la même chose à qui n'a jamais eu
  // de carte enregistrée.
  if (loading || !user || !user.paiement_en_echec || user.essai_bloque_sans_carte) {
    return null;
  }

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
    <div className="border-b border-red-200 bg-red-50">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm text-red-900">
        <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden />
        <p className="min-w-0 flex-1">
          Votre dernier paiement a été <span className="font-semibold">refusé par votre
          banque</span> : l&apos;accès à votre formule est suspendu. Mettez votre carte à
          jour pour le rétablir immédiatement — votre abonnement n&apos;est pas résilié.
        </p>
        <button
          onClick={ouvrirPortail}
          disabled={ouverture}
          className="font-semibold underline underline-offset-2 hover:text-red-950 disabled:opacity-50"
        >
          {ouverture ? "Ouverture…" : "Mettre ma carte à jour"}
        </button>
      </div>
    </div>
  );
}
