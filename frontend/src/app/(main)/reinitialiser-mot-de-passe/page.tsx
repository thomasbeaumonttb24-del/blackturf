"use client";

import { useState, Suspense } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { Zap, Loader2, ArrowLeft, CheckCircle, Eye, EyeOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

const schema = z.object({
  password: z.string().min(8, "8 caractères minimum"),
  confirm: z.string(),
}).refine((d) => d.password === d.confirm, {
  message: "Les mots de passe ne correspondent pas",
  path: ["confirm"],
});

type FormData = z.infer<typeof schema>;

function ReinitialiserContent() {
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [showPwd, setShowPwd] = useState(false);
  const params = useSearchParams();
  const router = useRouter();
  const token = params.get("token");

  const { register, handleSubmit, formState: { errors } } = useForm<FormData>({
    resolver: zodResolver(schema),
  });

  async function onSubmit(data: FormData) {
    if (!token) {
      toast.error("Token manquant");
      return;
    }
    setLoading(true);
    try {
      await api.post("/auth/reset-password", { token, password: data.password });
      setDone(true);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(msg || "Lien expiré ou invalide. Redemandez un email.");
    } finally {
      setLoading(false);
    }
  }

  if (!token) {
    return (
      <div className="min-h-screen gradient-hero flex items-center justify-center p-4">
        <div className="text-center">
          <p className="text-muted-foreground mb-4">Lien invalide.</p>
          <Button variant="brand" asChild>
            <Link href="/mot-de-passe-oublie">Redemander un lien</Link>
          </Button>
        </div>
      </div>
    );
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
          <h1 className="text-2xl font-bold">Nouveau mot de passe</h1>
        </div>

        <div className="rounded-2xl border border-border bg-card p-8 shadow-2xl">
          {done ? (
            <div className="text-center py-4">
              <CheckCircle className="h-12 w-12 text-brand-emerald mx-auto mb-4" />
              <h2 className="font-bold text-lg mb-2">Mot de passe mis à jour !</h2>
              <p className="text-sm text-muted-foreground mb-6">
                Vous pouvez maintenant vous connecter avec votre nouveau mot de passe.
              </p>
              <Button variant="brand" onClick={() => router.push("/login")}>
                Se connecter
              </Button>
            </div>
          ) : (
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-1.5">Nouveau mot de passe</label>
                <div className="relative">
                  <input
                    {...register("password")}
                    type={showPwd ? "text" : "password"}
                    placeholder="8 caractères minimum"
                    className="w-full rounded-lg border border-input bg-background px-3 py-2.5 pr-10 text-sm outline-none focus:ring-2 focus:ring-ring"
                    autoComplete="new-password"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPwd(!showPwd)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  >
                    {showPwd ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
                {errors.password && <p className="text-xs text-destructive mt-1">{errors.password.message}</p>}
              </div>

              <div>
                <label className="block text-sm font-medium mb-1.5">Confirmer le mot de passe</label>
                <input
                  {...register("confirm")}
                  type={showPwd ? "text" : "password"}
                  placeholder="Répétez le mot de passe"
                  className="w-full rounded-lg border border-input bg-background px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-ring"
                  autoComplete="new-password"
                />
                {errors.confirm && <p className="text-xs text-destructive mt-1">{errors.confirm.message}</p>}
              </div>

              <Button type="submit" variant="brand" className="w-full" size="lg" disabled={loading}>
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Réinitialiser le mot de passe"}
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

export default function ReinitialiserMotDePassePage() {
  return (
    <Suspense>
      <ReinitialiserContent />
    </Suspense>
  );
}
