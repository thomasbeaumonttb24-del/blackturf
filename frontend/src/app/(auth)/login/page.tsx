"use client";
export const dynamic = "force-dynamic";

import { useState, Suspense } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import Image from "next/image";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";

const schema = z.object({
  email: z.string().email("E-mail invalide"),
  password: z.string().min(6, "Mot de passe requis"),
});

type FormData = z.infer<typeof schema>;

function LoginContent() {
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const redirect = params.get("redirect") || "/programme";

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormData>({ resolver: zodResolver(schema) });

  async function onSubmit(data: FormData) {
    setLoading(true);
    try {
      await login(data.email, data.password);
      toast.success("Bienvenue sur BlackTurf !");
      router.push(redirect);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(msg || "Identifiants incorrects");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen gradient-hero flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Logo */}
        <div className="text-center mb-8">
          <Link href="/" className="inline-flex items-center gap-2.5 mb-4">
            <Image src="/logo.png" alt="BlackTurf" width={40} height={40} priority className="rounded-xl object-contain" />
            <span className="text-2xl font-bold text-gray-900">Black<span className="text-amber-700">Turf</span></span>
          </Link>
          <h1 className="text-2xl font-bold text-gray-900">Connexion</h1>
          <p className="text-gray-600 text-sm mt-1">
            Pas encore inscrit ?{" "}
            <Link href="/inscription" className="text-amber-700 hover:underline font-medium">
              Créer un compte
            </Link>
          </p>
        </div>

        {/* Card */}
        <div className="rounded-2xl border border-gray-200 bg-white p-8 shadow-xl shadow-black/[0.06]">
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-1.5">E-mail</label>
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

            <div>
              <label className="block text-sm font-medium mb-1.5">Mot de passe</label>
              <input
                {...register("password")}
                type="password"
                placeholder="••••••••"
                className="w-full rounded-lg border border-input bg-background px-3 py-2.5 text-sm outline-none ring-offset-background placeholder:text-muted-foreground focus:ring-2 focus:ring-ring"
                autoComplete="current-password"
              />
              {errors.password && (
                <p className="text-xs text-destructive mt-1">{errors.password.message}</p>
              )}
            </div>

            <div className="flex justify-end">
              <Link href="/mot-de-passe-oublie" className="text-xs text-muted-foreground hover:text-foreground">
                Mot de passe oublié ?
              </Link>
            </div>

            <Button type="submit" variant="brand" className="w-full" size="lg" disabled={loading}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Se connecter"}
            </Button>
          </form>

          {/* BOUTON GOOGLE RETIRÉ le 2026-08-31 — il n'a jamais fonctionné.
              Il pointait en GET sur `/api/v1/auth/google`, une route déclarée en
              POST (elle échange un code contre un jeton) : le clic partait sur un
              HTTP 405. Et même en la corrigeant, `google_client_id` n'est pas posé
              en production, donc la route répond « OAuth Google non configuré ».
              Mesure : 0 compte sur 26 porte un `google_id`.
              Un bouton mort dans un tunnel d'inscription coûte plus qu'il ne
              rapporte : le prospect qui le choisit se heurte à une erreur et ne
              recommence pas. Pour le rétablir il faut, DANS CET ORDRE :
                1. créer les identifiants OAuth dans Google Cloud Console
                   (type « Web », origine https://blackturf.fr, URI de redirection
                   https://blackturf.fr/auth/google/callback) ;
                2. poser GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET dans .env ET les
                   énumérer dans le bloc `environment:` du service api du compose
                   — sans quoi ils n'atteignent jamais le conteneur, en silence ;
                3. écrire la page de callback qui récupère le `code` et le POSTe
                   sur /api/v1/auth/google, puis remettre ce bouton. */}
        </div>

        <p className="text-center text-xs text-muted-foreground mt-6">
          En vous connectant, vous acceptez nos{" "}
          <Link href="/cgu" className="underline hover:text-foreground">CGU</Link>
          {" "}et notre{" "}
          <Link href="/confidentialite" className="underline hover:text-foreground">politique de confidentialité</Link>.
        </p>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginContent />
    </Suspense>
  );
}
