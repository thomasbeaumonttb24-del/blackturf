"use client";
export const dynamic = "force-dynamic";

import { useEffect, useState, Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { CheckCircle, XCircle, Loader2, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api, authApi } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";

function VerifierEmailContent() {
  const params = useSearchParams();
  const token = params.get("token");
  const { refreshUser } = useAuth();
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  // Le lien n'est valable que 24 h. Celui qui arrive trop tard ne peut pas se
  // connecter pour en redemander un : le renvoi doit donc être ici même.
  const [email, setEmail] = useState("");
  const [renvoi, setRenvoi] = useState(false);
  const [renvoye, setRenvoye] = useState(false);

  async function renvoyerLien(e: React.FormEvent) {
    e.preventDefault();
    if (!email) return;
    setRenvoi(true);
    try {
      await authApi.resendVerification(email);
      setRenvoye(true);
    } finally {
      setRenvoi(false);
    }
  }

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
              <h1 className="text-xl font-bold mb-2">Adresse confirmée !</h1>
              <p className="text-sm text-muted-foreground mb-6">
                Votre compte est actif et vous êtes connecté. Bonne route sur BlackTurf.
              </p>
              <Button variant="brand" asChild>
                <Link href="/programme">Accéder au programme</Link>
              </Button>
            </div>
          )}

          {status === "error" && (
            <div className="py-4">
              <XCircle className="h-12 w-12 text-destructive mx-auto mb-4" />
              <h1 className="text-xl font-bold mb-2">Lien expiré ou invalide</h1>
              <p className="text-sm text-muted-foreground mb-6">
                Un lien de confirmation ne vit que 24 heures. Indiquez votre adresse :
                nous vous en envoyons un nouveau.
              </p>

              {renvoye ? (
                <p className="text-sm text-brand-emerald">
                  C&apos;est envoyé. Ouvrez le nouveau lien depuis votre boîte mail
                  (pensez aux indésirables).
                </p>
              ) : (
                <form onSubmit={renvoyerLien} className="space-y-3 text-left">
                  <input
                    type="email"
                    required
                    value={email}
                    onChange={(ev) => setEmail(ev.target.value)}
                    placeholder="vous@exemple.fr"
                    className="w-full rounded-lg border border-input bg-background px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-ring"
                    autoComplete="email"
                  />
                  <Button type="submit" variant="brand" className="w-full" disabled={renvoi}>
                    {renvoi ? <Loader2 className="h-4 w-4 animate-spin" /> : "Recevoir un nouveau lien"}
                  </Button>
                </form>
              )}

              <p className="text-xs text-muted-foreground mt-4">
                <Link href="/login" className="hover:underline">Retour à la connexion</Link>
              </p>
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
