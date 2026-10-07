"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { api } from "@/lib/api";

type Props = {
  plan: "standard" | "expert";
  periodicite: "monthly" | "annual";
  label: string;
  variant?: "brand" | "brand-outline" | "outline";
  size?: "default" | "lg" | "xl";
  className?: string;
  // Code de l'offre anniversaire, déjà vérifié éligible par l'API (mensuel seulement).
  codePromo?: string;
};

export function CheckoutButton({ plan, periodicite, label, variant = "brand", size = "lg", className, codePromo }: Props) {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  // Filleul : le bouton annonce sa remise de 5 € sur le premier paiement.
  // Abonné : ce bouton CHANGE sa formule — il le dit, et ne propose jamais
  // sa propre formule.
  const abonne = Boolean(user?.abonnement_gerable) && (user?.plan === "standard" || user?.plan === "expert");
  // Déjà abonné : le passage mensuel ↔ annuel se fait sur demande (il refacture
  // tout et déplace l'échéance) — le bouton annuel ne propose donc rien.
  const annuelPourAbonne = abonne && periodicite === "annual";
  const formuleActuelle = (abonne && user?.plan === plan && periodicite === "monthly") || annuelPourAbonne;
  const nomPlan = plan === "expert" ? "Expert" : "Standard";
  const libelle = annuelPourAbonne
    ? "Annuel : sur demande (contact@blackturf.fr)"
    : formuleActuelle
      ? "Votre formule actuelle"
      : abonne
        ? `Passer en ${nomPlan} — ${plan === "expert" ? "19" : "12"} €/mois`
        : user?.remise_parrainage ?`${label} — 5 € offerts` : label;

  async function startCheckout() {
    if (!user) {
      const query = new URLSearchParams({ plan, periodicite });
      router.push(`/inscription?${query.toString()}`);
      return;
    }

    // Pass en cours : l'abonnement démarre (et se paie) aujourd'hui, le pass ne
    // se met pas en pause. On le dit avant le paiement plutôt qu'après.
    if (user.pass_fin && !abonne) {
      const fin = new Date(user.pass_fin).toLocaleString("fr-FR", {
        day: "numeric", month: "long", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Paris",
      });
      if (!window.confirm(`Votre pass court jusqu'au ${fin}. L'abonnement ${nomPlan} démarre dès aujourd'hui (premier paiement maintenant). Continuer ?`)) {
        return;
      }
    }

    setLoading(true);
    try {
      const code_promo = codePromo && !abonne && periodicite === "monthly" ? codePromo : undefined;
      let response = await api.post("/stripe/checkout", { plan, periodicite, code_promo });
      // Compte déjà abonné à une AUTRE formule : rien n'est modifié tant que le
      // client n'a pas lu et accepté ce qui va se passer (montant prélevé
      // aujourd'hui, crédit, prochaine facture), chiffré par Stripe. Le
      // 2026-09-29, un clic à 8 s d'une souscription Expert l'avait rétrogradé.
      if (response.data.confirmation_requise) {
        const message: string = response.data.apercu?.message || `Passer en ${nomPlan} ?`;
        if (!window.confirm(message)) {
          setLoading(false);
          return;
        }
        // Même date de prorata que l'aperçu : le montant débité est celui annoncé.
        response = await api.post("/stripe/checkout", {
          plan, periodicite, confirmer: true, proration_date: response.data.apercu?.proration_date,
        });
      }
      if (response.data.paiement_requis) {
        toast.info(response.data.message || "Paiement à confirmer auprès de votre banque");
      } else if (response.data.change_de_plan) {
        toast.success(response.data.message || "Votre formule a été modifiée");
      }
      window.location.assign(response.data.url);
    } catch (error: unknown) {
      const response = (error as { response?: { data?: { detail?: string }; status?: number } })?.response;
      const detail = response?.data?.detail;
      toast.error(detail || "Impossible d'ouvrir le paiement sécurisé");
      // 409 = compte déjà abonné à cette formule ; 403 = adresse e-mail pas encore
      // confirmée. Dans les deux cas la suite se joue sur le profil.
      if (response?.status === 409 || response?.status === 403) {
        router.push("/profil");
      }
      setLoading(false);
    }
  }

  return (
    <Button
      type="button"
      variant={variant}
      className={className || "w-full"}
      size={size}
      disabled={loading || authLoading || formuleActuelle}
      onClick={startCheckout}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : libelle}
    </Button>
  );
}
