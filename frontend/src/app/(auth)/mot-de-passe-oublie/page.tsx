"use client";

import { useState } from "react";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { Zap, Loader2, ArrowLeft, CheckCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

const schema = z.object({
  email: z.string().email("Email invalide"),
});

type FormData = z.infer<typeof schema>;

export default function MotDePasseOubliePage() {
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  const { register, handleSubmit, formState: { errors } } = useForm<FormData>({
    resolver: zodResolver(schema),
  });

  async function onSubmit(data: FormData) {
    setLoading(true);
    try {
      await api.post("/auth/forgot-password", { email: data.email });
      setSent(true);
    } catch {
      // Always show success to avoid email enumeration
      setSent(true);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen gradient-hero flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <Link href="/" className="inline-flex items-center gap-2 mb-4">
            <div className="h-10 w-10 rounded-xl bg-brand-gold flex items-center justify-center">
              <Zap className="h-5 w-5 text-white" />
            </div>
            <span className="text-2xl font-bold">Black<span className="text-brand-gold">Turf</span></span>
          </Link>
          <h1 className="text-2xl font-bold">Mot de passe oublié</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Entrez votre email pour recevoir un lien de réinitialisation.
          </p>
        </div>

        <div className="rounded-2xl border border-border bg-card p-8 shadow-2xl">
          {sent ? (
            <div className="text-center py-4">
              <CheckCircle className="h-12 w-12 text-brand-emerald mx-auto mb-4" />
              <h2 className="font-bold text-lg mb-2">Email envoyé !</h2>
              <p className="text-sm text-muted-foreground mb-6">
                Si un compte existe avec cette adresse, vous recevrez un lien de réinitialisation
                dans les prochaines minutes. Vérifiez vos spams.
              </p>
              <Button variant="outline" asChild>
                <Link href="/login">
                  <ArrowLeft className="h-4 w-4" /> Retour à la connexion
                </Link>
              </Button>
            </div>
          ) : (
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-1.5">Email</label>
                <input
                  {...register("email")}
                  type="email"
                  placeholder="vous@exemple.fr"
                  className="w-full rounded-lg border border-input bg-background px-3 py-2.5 text-sm outline-none ring-offset-background placeholder:text-muted-foreground focus:ring-2 focus:ring-ring"
                  autoComplete="email"
                />
                {errors.email && (
                  <p className="text-xs text-destructive mt-1">{errors.email.message}</p>
                )}
              </div>

              <Button type="submit" variant="brand" className="w-full" size="lg" disabled={loading}>
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Envoyer le lien"}
              </Button>

              <div className="text-center">
                <Link href="/login" className="text-sm text-muted-foreground hover:text-foreground flex items-center justify-center gap-1">
                  <ArrowLeft className="h-3 w-3" /> Retour à la connexion
                </Link>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
