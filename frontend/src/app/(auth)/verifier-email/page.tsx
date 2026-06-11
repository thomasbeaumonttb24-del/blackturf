"use client";
export const dynamic = "force-dynamic";

import { useEffect, useState, Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { CheckCircle, XCircle, Loader2, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";

function VerifierEmailContent() {
  const params = useSearchParams();
  const token = params.get("token");
  const { refreshUser } = useAuth();
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");

  useEffect(() => {
    if (!token) {
      setStatus("error");
      return;
    }
    api.get(`/auth/verify-email?token=${token}`)
      .then(async () => {
        setStatus("success");
        try { await refreshUser(); } catch { /* ignore */ }
      })
      .catch(() => setStatus("error"));
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="min-h-screen gradient-hero flex items-center justify-center p-4">
      <div className="w-full max-w-md text-center">
        <Link href="/" className="inline-flex items-center gap-2 mb-8 justify-center">
          <div className="h-10 w-10 rounded-xl bg-brand-gold flex items-center justify-center">
            <Zap className="h-5 w-5 text-white" />
          </div>
          <span className="text-2xl font-bold">Black<span className="text-brand-gold">Turf</span></span>
        </Link>

        <div className="rounded-2xl border border-border bg-card p-8 shadow-2xl">
          {status === "loading" && (
            <div className="py-4">
              <Loader2 className="h-12 w-12 animate-spin text-brand-gold mx-auto mb-4" />
              <p className="text-muted-foreground">Vérification en cours...</p>
            </div>
          )}

          {status === "success" && (
            <div className="py-4">
              <CheckCircle className="h-12 w-12 text-brand-emerald mx-auto mb-4" />
              <h1 className="text-xl font-bold mb-2">Email vérifié !</h1>
              <p className="text-sm text-muted-foreground mb-6">
                Votre adresse email est confirmée. Vous avez maintenant accès à toutes les fonctionnalités.
              </p>
              <Button variant="brand" asChild>
                <Link href="/programme">Accéder au programme</Link>
              </Button>
            </div>
          )}

          {status === "error" && (
            <div className="py-4">
              <XCircle className="h-12 w-12 text-destructive mx-auto mb-4" />
              <h1 className="text-xl font-bold mb-2">Lien invalide</h1>
              <p className="text-sm text-muted-foreground mb-6">
                Ce lien de vérification est expiré ou invalide. Connectez-vous pour en recevoir un nouveau.
              </p>
              <Button variant="brand" asChild>
                <Link href="/login">Se connecter</Link>
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function VerifierEmailPage() {
  return (
    <Suspense>
      <VerifierEmailContent />
    </Suspense>
  );
}
