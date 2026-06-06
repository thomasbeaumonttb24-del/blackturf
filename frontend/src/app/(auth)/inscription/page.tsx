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
import { Loader2, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";

const schema = z.object({
  prenom: z.string().min(1, "Prénom requis"),
  nom: z.string().optional(),
  email: z.string().email("E-mail invalide"),
  password: z.string().min(8, "8 caractères minimum"),
});

type FormData = z.infer<typeof schema>;

const PERKS = [
  "Programme PMU du jour",
  "Prédictions IA (limité)",
  "Suivi de capital",
  "7 jours d'essai Standard offert",
];

function InscriptionContent() {
  const [loading, setLoading] = useState(false);
  const { register: registerAuth } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const plan = params.get("plan") || "free";

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormData>({ resolver: zodResolver(schema) });

  async function onSubmit(data: FormData) {
    setLoading(true);
    try {
      await registerAuth(data);
      toast.success("Compte créé ! Bienvenue sur BlackTurf 🏇");
      if (plan !== "free") {
        router.push(`/tarifs?plan=${plan}`);
      } else {
        router.push("/programme");
      }
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(msg || "Erreur lors de la création du compte");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen gradient-hero flex items-center justify-center p-4">
      <div className="w-full max-w-4xl grid md:grid-cols-2 gap-8 items-center">
        {/* Left — value prop */}
        <div className="hidden md:block">
          <Link href="/" className="inline-flex items-center gap-2.5 mb-8">
            <Image src="/logo.png" alt="BlackTurf" width={40} height={40} className="rounded-xl object-contain" />
            <span className="text-2xl font-bold text-gray-900">Black<span className="text-amber-600">Turf</span></span>
          </Link>

          <h1 className="text-3xl font-bold mb-4">
            Rejoignez les parieurs<br />
            <span className="text-gradient">qui gagnent à long terme</span>
          </h1>
          <p className="text-muted-foreground mb-8">
            Créez votre compte gratuit et accédez aux analyses IA les plus précises du marché.
          </p>

          <ul className="space-y-3">
            {PERKS.map((perk) => (
              <li key={perk} className="flex items-center gap-3 text-sm">
                <div className="h-5 w-5 rounded-full bg-brand-gold/20 flex items-center justify-center flex-shrink-0">
                  <Check className="h-3 w-3 text-brand-gold" />
                </div>
                {perk}
              </li>
            ))}
          </ul>
        </div>

        {/* Right — form */}
        <div>
          <div className="md:hidden text-center mb-6">
            <Link href="/" className="inline-flex items-center gap-2.5">
              <Image src="/logo.png" alt="BlackTurf" width={36} height={36} className="rounded-lg object-contain" />
              <span className="text-xl font-bold text-gray-900">Black<span className="text-amber-600">Turf</span></span>
            </Link>
          </div>

          <div className="rounded-2xl border border-border bg-card p-8 shadow-2xl">
            <h2 className="text-xl font-bold mb-1">Créer un compte</h2>
            <p className="text-sm text-muted-foreground mb-6">
              Déjà inscrit ?{" "}
              <Link href="/login" className="text-brand-gold hover:underline">
                Se connecter
              </Link>
            </p>

            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium mb-1.5">Prénom</label>
                  <input
                    {...register("prenom")}
                    type="text"
                    placeholder="Jean"
                    className="w-full rounded-lg border border-input bg-background px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-ring"
                  />
                  {errors.prenom && (
                    <p className="text-xs text-destructive mt-1">{errors.prenom.message}</p>
                  )}
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1.5">Nom</label>
                  <input
                    {...register("nom")}
                    type="text"
                    placeholder="Dupont"
                    className="w-full rounded-lg border border-input bg-background px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium mb-1.5">E-mail</label>
                <input
                  {...register("email")}
                  type="email"
                  placeholder="jean@exemple.fr"
                  className="w-full rounded-lg border border-input bg-background px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-ring"
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
                  placeholder="8 caractères minimum"
                  className="w-full rounded-lg border border-input bg-background px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-ring"
                  autoComplete="new-password"
                />
                {errors.password && (
                  <p className="text-xs text-destructive mt-1">{errors.password.message}</p>
                )}
              </div>

              <Button type="submit" variant="brand" className="w-full" size="lg" disabled={loading}>
                {loading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  "Créer mon compte gratuitement"
                )}
              </Button>
            </form>

            <p className="text-center text-xs text-muted-foreground mt-4">
              En créant un compte, vous acceptez nos{" "}
              <Link href="/cgu" className="underline hover:text-foreground">CGU</Link>.
              <br />
              ⚠️ Interdit aux mineurs. Le jeu peut créer une dépendance.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function InscriptionPage() {
  return (
    <Suspense>
      <InscriptionContent />
    </Suspense>
  );
}
