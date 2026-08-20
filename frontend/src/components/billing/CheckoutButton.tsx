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
};

export function CheckoutButton({ plan, periodicite, label, variant = "brand", size = "lg", className }: Props) {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [loading, setLoading] = useState(false);

  async function startCheckout() {
    if (!user) {
      const query = new URLSearchParams({ plan, periodicite });
      router.push(`/inscription?${query.toString()}`);
      return;
    }

    setLoading(true);
    try {
      const response = await api.post("/stripe/checkout", { plan, periodicite });
      // Compte déjà abonné à une AUTRE formule : le backend a modifié l'abonnement
      // existant au lieu d'en ouvrir un second (aucun passage par Stripe Checkout,
      // donc aucun second prélèvement). Il n'y a plus qu'à confirmer.
      if (response.data.change_de_plan) {
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
      disabled={loading || authLoading}
      onClick={startCheckout}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : label}
    </Button>
  );
}
