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
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      let msg: string | undefined;
      if (Array.isArray(detail)) {
        msg = detail.map((d) => (d as { msg?: string })?.msg).filter(Boolean).join(", ");
      } else if (typeof detail === "string") {
        msg = detail;
      }
      toast.error(msg || "Erreur lors de la création du compte");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
          <div className="rounded-2xl border border-border bg-card p-8 shadow-2xl">
            <h2 className="text-xl font-bold mb-1">Créer un compte</h2>
            <p className="text-sm text-muted-foreground mb-6">
              Déjà inscrit ?{" "}
              <Link href="/login" className="font-medium text-brand-gold-dark underline underline-offset-2">
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
  );
}

export default function InscriptionPage() {
  return (
    <div className="min-h-screen gradient-hero flex items-center justify-center p-4">
      <div className="w-full max-w-4xl grid md:grid-cols-2 gap-8 items-center">
        {/* Colonne de présentation — entièrement statique, donc rendue côté serveur.
            Elle se trouvait auparavant DANS le <Suspense> : or l'appel à useSearchParams
            fait basculer tout le sous-arbre en rendu navigateur, et la page arrivait au
            robot d'indexation sans <h1> et sans une ligne de texte. Seul le formulaire a
            besoin des paramètres d'URL, lui seul reste sous Suspense.
            Le titre reste visible sur mobile (indexation mobile-first) ; seule la liste
            des avantages est repliée sur petit écran. */}
        <div>
          <Link href="/" className="inline-flex items-center gap-2.5 mb-6 md:mb-8">
            <Image src="/logo.png" alt="Logo BlackTurf" width={40} height={40} priority className="rounded-xl object-contain" />
            <span className="text-2xl font-bold text-gray-900">Black<span className="text-amber-700">Turf</span></span>
          </Link>

          <h1 className="text-2xl md:text-3xl font-bold mb-4">
            Créez votre compte{" "}
            <span className="text-gradient">BlackTurf</span>
          </h1>
          <p className="text-muted-foreground mb-6 md:mb-8">
            Le programme PMU du jour, les prédictions de l&apos;algorithme et un plan de mise
            calculé sur votre budget. Compte gratuit, 7 jours d&apos;essai Standard offerts.
          </p>

          <ul className="hidden md:flex flex-col gap-3">
            {PERKS.map((perk) => (
              <li key={perk} className="flex items-center gap-3 text-sm">
                <div className="h-5 w-5 rounded-full bg-brand-gold/20 flex items-center justify-center flex-shrink-0">
                  <Check className="h-3 w-3 text-brand-gold-dark" />
                </div>
                {perk}
              </li>
            ))}
          </ul>
        </div>

        <Suspense>
          <InscriptionContent />
        </Suspense>
      </div>
    </div>
  );
}
