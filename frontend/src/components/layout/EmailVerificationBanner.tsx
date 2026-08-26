"use client";

import { useState } from "react";
import { MailWarning } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";

/**
 * Rappel de confirmation d'adresse.
 *
 * L'abonnement et l'assistant exigent désormais une adresse confirmée (l'essai
 * gratuit se multipliait sinon à raison d'une adresse bidon par compte, et les
 * rebonds abîmaient la délivrabilité de tous les envois). Sans ce rappel, le
 * refus n'arriverait qu'au moment de payer — trop tard et incompréhensible.
 */
export function EmailVerificationBanner() {
  const { user, loading } = useAuth();
  const [envoi, setEnvoi] = useState(false);
  const [masque, setMasque] = useState(false);

  if (loading || !user || user.email_verified || masque) return null;

  const renvoyer = async () => {
    setEnvoi(true);
    try {
      await api.post("/auth/resend-verification");
      toast.success(`Lien renvoyé à ${user.email}`);
    } catch {
      toast.error("Envoi impossible pour le moment");
    } finally {
      setEnvoi(false);
    }
  };

  return (
    <div className="border-b border-amber-200 bg-amber-50">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm text-amber-900">
        <MailWarning className="h-4 w-4 shrink-0" aria-hidden />
        <p className="min-w-0 flex-1">
          Confirmez votre adresse <span className="font-semibold">{user.email}</span> pour
          activer l&apos;abonnement et l&apos;assistant.
        </p>
        <button
          onClick={renvoyer}
          disabled={envoi}
          className="font-semibold underline underline-offset-2 hover:text-amber-950 disabled:opacity-50"
        >
          {envoi ? "Envoi…" : "Renvoyer le lien"}
        </button>
        <button
          onClick={() => setMasque(true)}
          className="text-amber-700 hover:text-amber-900"
          aria-label="Masquer ce rappel"
        >
          ✕
        </button>
      </div>
    </div>
  );
}
