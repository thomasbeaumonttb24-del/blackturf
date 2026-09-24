"use client";
export const dynamic = "force-dynamic";

import { useEffect, useState, Suspense } from "react";
import Link from "next/link";
import Image from "next/image";
import { useSearchParams } from "next/navigation";
import { CheckCircle, XCircle, Loader2, Gift } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api, authApi } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import { peutDemarrerEssai } from "@/lib/auth";
import { lireIntention, oublierIntention, type IntentionInscription } from "@/lib/intentionEssai";
import { CheckoutButton } from "@/components/billing/CheckoutButton";

function VerifierEmailContent() {
  const params = useSearchParams();
  const token = params.get("token");
  const { user, refreshUser } = useAuth();
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  // Le lien n'est valable que 24 h. Celui qui arrive trop tard ne peut pas se
  // connecter pour en redemander un : le renvoi doit donc être ici même.
  const [email, setEmail] = useState("");
  const [renvoi, setRenvoi] = useState(false);
  const [renvoye, setRenvoye] = useState(false);
  const [intention, setIntention] = useState<IntentionInscription>({ plan: null, suite: null });

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
        // Le profil d'abord : l'écran de succès décide d'après lui s'il propose l'essai.
        try { await refreshUser(); } catch { /* ignore */ }
        setIntention(lireIntention());
        oublierIntention();
        setStatus("success");
      })
      .catch(() => setStatus("error"));
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  const suite = intention.suite ?? "/programme";
  const planPropose = intention.plan ?? "standard";

  return (
    <div className="min-h-screen gradient-hero flex items-center justify-center p-4">
      <div className="w-full max-w-md text-center">
        <Link href="/" className="inline-flex items-center gap-2 mb-8 justify-center">
          <Image src="/logo-transparent.png" alt="BlackTurf" width={40} height={40} priority className="object-contain" />
          <span className="text-2xl font-bold">Black<span className="text-brand-gold-dark">Turf</span></span>
        </Link>

        <div className="rounded-2xl border border-border bg-card p-8 shadow-2xl">
          {status === "loading" && (
            <div className="py-4">
              <Loader2 className="h-12 w-12 animate-spin text-brand-gold-dark mx-auto mb-4" />
              <p className="text-muted-foreground">Vérification en cours...</p>
            </div>
          )}

          {/* Premier moment où le compte est connecté ET confirmé : c'est ici que
              l'essai se prend en un clic. Avant, le seul bouton menait au programme,
              et l'essai n'était plus jamais évoqué (2 essais sur 44 comptes gratuits). */}
          {status === "success" && peutDemarrerEssai(user) && (
            <div className="py-2">
              <CheckCircle className="h-12 w-12 text-brand-emerald-dark mx-auto mb-4" />
              <h1 className="text-xl font-bold mb-2">Adresse confirmée, bienvenue !</h1>
              <p className="text-sm text-muted-foreground mb-5">
                Votre compte gratuit est actif : marché des cotes en direct, classement de
                l&apos;algorithme et un plan de mise par jour.
              </p>
              <div className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-4 text-left mb-5">
                <p className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                  <Gift className="h-4 w-4 text-emerald-700" aria-hidden />
                  7 jours {planPropose === "expert" ? "Expert" : "Standard"} offerts
                </p>
                <p className="mt-1 text-[13px] leading-5 text-stone-600">
                  {planPropose === "expert"
                    ? "Pronostics illimités, paris de valeur en temps réel, assistant IA."
                    : "Pronostics sur 5 courses par jour, paris de valeur, calculateur de mise complet."}
                </p>
              </div>
              <CheckoutButton plan={planPropose} periodicite="monthly" label="Démarrer mes 7 jours gratuits" />
              <p className="text-xs text-muted-foreground mt-2">
                Carte demandée, 0 € prélevé avant la fin de l&apos;essai. Résiliable en un clic.
              </p>
              <p className="text-sm mt-5">
                <Link href={suite} className="font-medium text-slate-600 underline underline-offset-2 hover:text-slate-900">
                  {intention.suite ? "Plus tard — reprendre où j'en étais" : "Plus tard — voir le programme"}
                </Link>
              </p>
            </div>
          )}

          {status === "success" && !peutDemarrerEssai(user) && (
            <div className="py-4">
              <CheckCircle className="h-12 w-12 text-brand-emerald-dark mx-auto mb-4" />
              <h1 className="text-xl font-bold mb-2">Adresse confirmée !</h1>
              <p className="text-sm text-muted-foreground mb-6">
                Votre compte est actif et vous êtes connecté. Bonne route sur BlackTurf.
              </p>
              <Button variant="brand" asChild>
                <Link href={suite}>{intention.suite ? "Reprendre où j'en étais" : "Accéder au programme"}</Link>
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
