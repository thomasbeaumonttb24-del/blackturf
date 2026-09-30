"use client";
export const dynamic = "force-dynamic";

import { useEffect, useState, Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import Image from "next/image";
import { Loader2, Check, MailCheck, Gift } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { champMotDePasse, MOT_DE_PASSE_AIDE, messageErreurApi } from "@/lib/motdepasse";
import { champPseudo, PSEUDO_AIDE } from "@/lib/pseudo";
import { authApi, parrainageApi } from "@/lib/api";
import { euros, lireCodeParrain, memoriserCodeParrain, normaliserCode, oublierCodeParrain } from "@/lib/parrainage";
import { cheminInterne, memoriserIntention, planEssai } from "@/lib/intentionEssai";
import { AVANTAGES_COMPTE_GRATUIT } from "@/components/billing/CompteGratuitCta";

const schema = z.object({
  prenom: z.string().min(1, "Prénom requis"),
  nom: z.string().optional(),
  pseudo: champPseudo,
  email: z.string().email("E-mail invalide"),
  password: champMotDePasse,
});

type FormData = z.infer<typeof schema>;

const PERKS = ["Programme PMU du jour", ...AVANTAGES_COMPTE_GRATUIT];

function InscriptionContent() {
  const [loading, setLoading] = useState(false);
  // Adresse à laquelle le lien vient de partir. Tant qu'elle est posée, on
  // affiche l'écran d'attente à la place du formulaire : l'inscription ne
  // connecte plus, elle envoie un lien.
  const [enAttente, setEnAttente] = useState<string | null>(null);
  const [renvoi, setRenvoi] = useState(false);
  const { register: registerAuth, user } = useAuth();
  const params = useSearchParams();
  // Intention d'arrivée : `?plan=expert` depuis « Essayer 7 jours », `?suite=/courses/…`
  // depuis un appel à créer un compte. Mémorisée pour l'écran de confirmation d'adresse.
  const plan = planEssai(params.get("plan"));
  const suite = cheminInterne(params.get("suite"));
  // Lien de parrainage : `?parrain=CODE`, ou le code mémorisé d'une visite précédente.
  const codeUrl = normaliserCode(params.get("parrain"));
  const [parrain, setParrain] = useState<{ code: string; prenom: string | null; remise: number } | null>(null);
  // Saisie manuelle : l'ami a reçu le code à l'oral, ou ouvre le lien sur un autre appareil.
  const [saisieOuverte, setSaisieOuverte] = useState(false);
  const [saisie, setSaisie] = useState("");
  const [verification, setVerification] = useState(false);
  // Adresse déjà rattachée à un compte confirmé (HTTP 400). Le 28/09, sept
  // tentatives en une journée : d'anciens inscrits qui avaient oublié leur
  // compte, face à un simple toast. On leur ouvre la porte au lieu de la fermer.
  const [dejaInscrit, setDejaInscrit] = useState<string | null>(null);
  const lienConnexion = suite ? `/login?redirect=${encodeURIComponent(suite)}` : "/login";

  async function appliquerCode(code: string, depuisLien: boolean) {
    setVerification(true);
    try {
      const { data } = await parrainageApi.verifier(code);
      if (data.valide) {
        memoriserCodeParrain(data.code);
        setParrain({ code: data.code, prenom: data.prenom, remise: data.remise_cents });
        setSaisieOuverte(false);
        if (!depuisLien) toast.success("Code appliqué : 5 € offerts sur votre premier abonnement");
      } else {
        oublierCodeParrain();
        toast.error(depuisLien ? "Ce lien de parrainage n'est plus valable." : "Code de parrainage inconnu. Vérifiez-le auprès de votre ami.");
      }
    } catch {
      if (!depuisLien) toast.error("Vérification impossible pour le moment. Réessayez.");
    } finally {
      setVerification(false);
    }
  }

  useEffect(() => {
    const code = codeUrl || lireCodeParrain();
    if (code) appliquerCode(code, true);
  }, [codeUrl]);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormData>({ resolver: zodResolver(schema) });

  async function onSubmit(data: FormData) {
    setLoading(true);
    setDejaInscrit(null);
    try {
      const res = await registerAuth({ ...data, code_parrain: parrain?.code });
      if (parrain) oublierCodeParrain();
      memoriserIntention({ plan, suite });
      setEnAttente(res.email);
    } catch (e: unknown) {
      const reponse = (e as { response?: { status?: number; data?: { detail?: unknown } } })?.response;
      const detail = reponse?.data?.detail;
      // /auth/register ne renvoie 400 que pour « Email déjà utilisé ».
      if (reponse?.status === 400) {
        setDejaInscrit(data.email);
        return;
      }
      toast.error(messageErreurApi(detail) || "Erreur lors de la création du compte");
    } finally {
      setLoading(false);
    }
  }

  async function renvoyerLien() {
    if (!enAttente) return;
    setRenvoi(true);
    try {
      await authApi.resendVerification(enAttente);
      toast.success("Lien renvoyé. Pensez à regarder dans les indésirables.");
    } catch {
      toast.error("Envoi impossible pour le moment. Réessayez dans une minute.");
    } finally {
      setRenvoi(false);
    }
  }

  // Écran d'attente. Il avait disparu lors de la refonte SEO de la page (colonne
  // de présentation sortie du <Suspense>) : après « Créer mon compte », le
  // formulaire restait affiché sans un mot, l'inscrit ne savait pas qu'un lien
  // l'attendait — 26 comptes gratuits sur 44 jamais confirmés au 2026-09-13.
  if (enAttente) {
    return (
      <div className="rounded-2xl border border-border bg-card p-8 shadow-2xl text-center">
        <div className="h-12 w-12 rounded-full bg-brand-gold/15 flex items-center justify-center mx-auto mb-4">
          <MailCheck className="h-6 w-6 text-brand-gold-dark" />
        </div>
        <h2 className="text-xl font-bold mb-2">Vérifiez votre boîte mail</h2>
        <p className="text-sm text-muted-foreground">
          Un lien de confirmation vient de partir à{" "}
          <span className="font-medium text-foreground">{enAttente}</span>. Ouvrez-le
          pour activer votre compte — il est valable 24 heures.
        </p>
        <p className="text-xs text-muted-foreground mt-3">
          Rien reçu au bout de deux minutes ? Regardez dans les indésirables.
        </p>
        <p className="text-xs text-muted-foreground mt-3">
          {parrain
            ? `Dès la confirmation, vos ${euros(parrain.remise)} de remise de parrainage vous attendent sur votre premier abonnement.`
            : `Dès la confirmation, votre essai ${plan === "expert" ? "Expert" : "Standard"} de 7 jours vous sera proposé.`}
        </p>

        <Button variant="outline" className="w-full mt-6" onClick={renvoyerLien} disabled={renvoi}>
          {renvoi ? <Loader2 className="h-4 w-4 animate-spin" /> : "Renvoyer le lien"}
        </Button>
        <p className="text-xs text-muted-foreground mt-4">
          Adresse erronée ?{" "}
          <button
            type="button"
            onClick={() => setEnAttente(null)}
            className="font-medium text-brand-gold-dark underline underline-offset-2"
          >
            Recommencer l&apos;inscription
          </button>
        </p>
      </div>
    );
  }

  return (
    <div>
          <div className="rounded-2xl border border-border bg-card p-8 shadow-2xl">
            {user && codeUrl && (
              <div className="mb-5 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                Vous avez déjà un compte : le parrainage est réservé aux nouveaux inscrits. Pour
                inviter vos amis, partagez votre propre lien depuis{" "}
                <Link href="/profil#parrainage" className="font-semibold underline underline-offset-2">
                  Profil → Parrainage
                </Link>.
              </div>
            )}
            {parrain && (
              <div className="mb-5 flex items-start gap-3 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">
                <Gift className="h-5 w-5 flex-shrink-0 text-emerald-700 mt-0.5" aria-hidden />
                <p>
                  <span className="font-semibold">
                    {parrain.prenom ? `${parrain.prenom} vous invite` : "Vous êtes invité"} :{" "}
                    {euros(parrain.remise)} offerts
                  </span>{" "}
                  sur votre premier abonnement Standard ou Expert, mensuel ou annuel.
                </p>
              </div>
            )}
            <h2 className="text-xl font-bold mb-1">Créer un compte</h2>
            <p className="text-sm text-muted-foreground mb-6">
              Déjà inscrit ?{" "}
              <Link
                href={lienConnexion}
                className="font-medium text-brand-gold-dark underline underline-offset-2"
              >
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
                <label className="block text-sm font-medium mb-1.5" htmlFor="pseudo">Pseudo</label>
                <input
                  id="pseudo"
                  {...register("pseudo")}
                  type="text"
                  placeholder="Turfiste75"
                  maxLength={20}
                  autoComplete="nickname"
                  className="w-full rounded-lg border border-input bg-background px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-ring"
                />
                {errors.pseudo ? (
                  <p className="text-xs text-destructive mt-1">{errors.pseudo.message}</p>
                ) : (
                  <p className="text-xs text-muted-foreground mt-1">
                    Votre nom public au classement du Défi du mois et dans la Communauté. {PSEUDO_AIDE}
                  </p>
                )}
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
                  placeholder="Au moins 10 caractères"
                  className="w-full rounded-lg border border-input bg-background px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-ring"
                  autoComplete="new-password"
                  aria-describedby="aide-mot-de-passe"
                />
                {errors.password ? (
                  <p className="text-xs text-destructive mt-1">{errors.password.message}</p>
                ) : (
                  <p id="aide-mot-de-passe" className="text-xs text-muted-foreground mt-1">
                    {MOT_DE_PASSE_AIDE}
                  </p>
                )}
              </div>

              {!parrain && (
                saisieOuverte ? (
                  <div>
                    <label className="block text-sm font-medium mb-1.5">Code de parrainage</label>
                    <div className="flex gap-2">
                      <input
                        value={saisie}
                        onChange={(e) => setSaisie(e.target.value.toUpperCase())}
                        placeholder="Ex. K7XQ4MPT"
                        maxLength={20}
                        autoCapitalize="characters"
                        className="w-full rounded-lg border border-input bg-background px-3 py-2.5 text-sm font-mono tracking-widest outline-none focus:ring-2 focus:ring-ring"
                      />
                      <Button
                        type="button"
                        variant="outline"
                        disabled={verification || !normaliserCode(saisie)}
                        onClick={() => { const c = normaliserCode(saisie); if (c) appliquerCode(c, false); }}
                      >
                        {verification ? <Loader2 className="h-4 w-4 animate-spin" /> : "Appliquer"}
                      </Button>
                    </div>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => setSaisieOuverte(true)}
                    className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-gold-dark underline underline-offset-2"
                  >
                    <Gift className="h-4 w-4" aria-hidden /> J&apos;ai un code de parrainage
                  </button>
                )
              )}

              {dejaInscrit && (
                <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
                  <p className="font-semibold">Vous avez déjà un compte BlackTurf</p>
                  <p className="mt-1">
                    L&apos;adresse <span className="font-medium">{dejaInscrit}</span> est déjà inscrite.
                    Connectez-vous, ou choisissez un nouveau mot de passe si vous ne vous en souvenez plus.
                  </p>
                  <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                    <Button asChild variant="brand" className="flex-1">
                      <Link href={lienConnexion}>Se connecter</Link>
                    </Button>
                    <Button asChild variant="outline" className="flex-1">
                      <Link href="/mot-de-passe-oublie">Mot de passe oublié</Link>
                    </Button>
                  </div>
                </div>
              )}

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
            <Image src="/logo-transparent.png" alt="Logo BlackTurf" width={40} height={40} priority className="object-contain" />
            <span className="text-2xl font-bold text-gray-900">Black<span className="text-amber-700">Turf</span></span>
          </Link>

          <h1 className="text-2xl md:text-3xl font-bold mb-4">
            Créez votre compte{" "}
            <span className="text-gradient">BlackTurf</span>
          </h1>
          <p className="text-muted-foreground mb-6 md:mb-8">
            Le marché des cotes en direct, le classement de l&apos;algorithme et un plan de mise
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
