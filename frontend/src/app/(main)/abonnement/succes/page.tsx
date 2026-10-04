"use client";
export const dynamic = "force-dynamic";

import { useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { CheckCircle, Loader2, ArrowRight, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useAuth } from "@/hooks/useAuth";
import { ParrainageAppel } from "@/components/billing/ParrainageAppel";
import { api } from "@/lib/api";

const NOMS_PASS: Record<string, string> = { jour: "Pass Jour", semaine: "Pass Semaine", mois: "Pass Mois" };

/** Retour de paiement d'un pass : le SERVEUR relit la session chez Stripe et
 *  accorde l'accès (idempotent avec le webhook). L'adresse seule n'ouvre rien. */
function PassSucces({ duree, sessionId }: { duree: string; sessionId: string }) {
  const { refreshUser } = useAuth();
  const [etat, setEtat] = useState<"attente" | "ok" | "echec">("attente");
  const [fin, setFin] = useState<string | null>(null);

  useEffect(() => {
    let annule = false;
    const confirmer = async () => {
      // Paiement par carte : encaissé à la redirection. Quelques essais couvrent
      // le cas d'une banque lente à confirmer.
      for (let i = 0; i < 6 && !annule; i++) {
        try {
          const r = await api.post("/stripe/pass/confirmer", { session_id: sessionId });
          if (annule) return;
          setFin(r.data.fin);
          setEtat("ok");
          await refreshUser().catch(() => {});
          return;
        } catch (error: unknown) {
          const status = (error as { response?: { status?: number } })?.response?.status;
          if (status !== 409) break;
          await new Promise((res) => setTimeout(res, 2500));
        }
      }
      if (!annule) setEtat("echec");
    };
    confirmer();
    return () => { annule = true; };
  }, [sessionId, refreshUser]);

  const nom = NOMS_PASS[duree] || "Pass";
  const finTexte = fin
    ? new Date(fin).toLocaleString("fr-FR", { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Paris" })
    : null;

  return (
    <div className="min-h-[70vh] flex items-center justify-center px-4">
      <div className="max-w-lg w-full text-center space-y-6">
        {etat === "attente" && (
          <div className="space-y-4">
            <Loader2 className="h-12 w-12 animate-spin text-brand-gold-dark mx-auto" />
            <p className="text-muted-foreground">Activation de votre {nom}…</p>
          </div>
        )}
        {etat === "echec" && (
          <p className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            Votre paiement est en cours de confirmation. Votre accès s&apos;ouvre dès que votre banque
            l&apos;a validé : rechargez cette page dans une minute. Un souci ? contact@blackturf.fr
          </p>
        )}
        {etat === "ok" && (
          <div className="animate-fade-in space-y-6">
            <div className="h-20 w-20 rounded-full bg-brand-emerald/15 border border-brand-emerald/30 flex items-center justify-center mx-auto gold-glow">
              <CheckCircle className="h-10 w-10 text-brand-emerald-dark" />
            </div>
            <div>
              <h1 className="text-3xl font-extrabold mb-2">
                Votre <span className="text-gradient">{nom}</span> est actif !
              </h1>
              <p className="text-muted-foreground">
                Accès Expert complet{finTexte ? <> jusqu&apos;au <strong>{finTexte}</strong></> : null}. Aucun
                renouvellement : rien d&apos;autre ne sera prélevé. Une confirmation vous a été envoyée par e-mail.
              </p>
            </div>
            <div className="flex flex-col sm:flex-row gap-3 justify-center">
              <Button asChild className="bg-brand-gold hover:bg-brand-amber text-brand-dark font-bold" size="lg">
                <Link href="/programme">Voir les courses du jour <ArrowRight className="h-4 w-4" /></Link>
              </Button>
              <Button variant="outline" size="lg" asChild>
                <Link href="/value-bets">Paris de valeur</Link>
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function AbonnementSuccesContent() {
  const searchParams = useSearchParams();
  const pass = searchParams.get("pass");
  const sessionId = searchParams.get("session_id");
  if (pass && sessionId) return <PassSucces duree={pass} sessionId={sessionId} />;
  return <AbonnementSuccesAbonnement />;
}

function AbonnementSuccesAbonnement() {
  const searchParams = useSearchParams();
  const { user, refreshUser } = useAuth();
  const [loading, setLoading] = useState(true);
  const plan = searchParams.get("plan") || "standard";
  // `change=1` : changement de formule sur l'abonnement existant, pas une
  // première souscription — dire « Bienvenue » serait faux.
  const changementDeFormule = searchParams.get("change") === "1";
  const sens = searchParams.get("sens");
  const pendantEssai = searchParams.get("essai") === "1";
  const detailChangement = pendantEssai
    ? "Votre essai gratuit continue : aucun prélèvement avant sa fin, puis le tarif de votre nouvelle formule."
    : sens === "hausse" || sens === "periodicite"
      ? "La différence au prorata a été réglée aujourd'hui ; ensuite, le tarif de votre nouvelle formule à chaque échéance."
      : "Le temps non utilisé de votre ancienne formule est déduit de votre prochaine facture.";

  useEffect(() => {
    // Refresh user pour mettre à jour le plan après paiement Stripe
    const refresh = async () => {
      await new Promise((r) => setTimeout(r, 2000)); // attendre webhook Stripe
      await refreshUser().catch(() => {});
      setLoading(false);
    };
    refresh();
  }, [refreshUser]);

  const planLabel = plan === "expert" ? "Expert" : "Standard";
  // L'adresse dit ce qui a été DEMANDÉ ; seul le compte relu dit ce qui est actif.
  // Paiement pas encore confirmé (webhook en route, essai refusé à régler) : on
  // ne souhaite pas « Bienvenue en Expert » à un compte qui ne l'est pas.
  const planActif = !loading && user?.plan === plan;
  const planDesc =
    plan === "expert"
      ? "Prédictions illimitées, assistant IA, créateur de stratégies, simulation sur 365 jours."
      : "5 prédictions par jour, paris de valeur, calculateur de mise, alertes notifications & e-mail.";

  return (
    <div className="min-h-[70vh] flex items-center justify-center px-4">
      <div className="max-w-lg w-full text-center">
        {loading ? (
          <div className="space-y-4">
            <Loader2 className="h-12 w-12 animate-spin text-brand-gold-dark mx-auto" />
            <p className="text-muted-foreground">Activation de votre abonnement…</p>
          </div>
        ) : (
          <div className="animate-fade-in space-y-6">
            {/* Success icon */}
            <div className="h-20 w-20 rounded-full bg-brand-emerald/15 border border-brand-emerald/30 flex items-center justify-center mx-auto gold-glow">
              <CheckCircle className="h-10 w-10 text-brand-emerald-dark" />
            </div>

            {!planActif && (
              <p className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                Votre paiement est en cours de confirmation. L&apos;accès {planLabel} s&apos;ouvre dès
                que votre banque l&apos;a validé ; rechargez cette page dans une minute. Si un
                paiement est en attente, réglez-le depuis votre{" "}
                <Link href="/profil" className="font-semibold underline">profil</Link>.
              </p>
            )}
            <div>
              <h1 className="text-3xl font-extrabold mb-2">
                {!planActif ? "Demande enregistrée — " : changementDeFormule ? "Vous êtes maintenant en " : "Bienvenue sur BlackTurf "}
                <span className="text-gradient">{planLabel}</span> !
              </h1>
              <p className="text-muted-foreground">{planDesc}</p>
              {changementDeFormule && (
                <p className="text-muted-foreground text-sm mt-2">
                  Votre abonnement a été modifié — aucun second abonnement n&apos;a été
                  créé. {detailChangement}
                </p>
              )}
            </div>

            <Card className="border-brand-gold/20 bg-brand-gold/5">
              <CardContent className="p-5 space-y-3">
                <p className="text-sm font-semibold text-brand-gold-dark mb-3">
                  🎯 Pour commencer maintenant :
                </p>
                {[
                  { icon: "🏇", text: "Consultez le programme du jour et ses analyses IA" },
                  { icon: "⭐", text: "Repérez les paris de valeur en temps réel" },
                  plan === "expert"
                    ? { icon: "🤖", text: "Testez l'assistant IA — posez vos questions en langage naturel" }
                    : { icon: "💰", text: "Utilisez le calculateur de mise personnalisé" },
                  { icon: "📈", text: "Configurez vos alertes push pour ne rien rater" },
                ].map((item, i) => (
                  <div key={i} className="flex items-start gap-3 text-sm">
                    <span className="text-base flex-shrink-0">{item.icon}</span>
                    <span className="text-muted-foreground">{item.text}</span>
                  </div>
                ))}
              </CardContent>
            </Card>

            <div className="flex flex-col sm:flex-row gap-3 justify-center">
              <Button
                asChild
                className="bg-brand-gold hover:bg-brand-amber text-brand-dark font-bold"
                size="lg"
              >
                <Link href="/programme">
                  Voir les courses du jour <ArrowRight className="h-4 w-4" />
                </Link>
              </Button>
              {plan === "expert" && (
                <Button variant="outline" size="lg" asChild>
                  <Link href="/assistant">
                    <Zap className="h-4 w-4" /> Assistant IA
                  </Link>
                </Button>
              )}
              <Button variant="outline" size="lg" asChild>
                <Link href="/value-bets">Paris de valeur</Link>
              </Button>
            </div>

            {/* Le moment où l'abonné est le plus convaincu : c'est là qu'il invite. */}
            <ParrainageAppel contexte="bienvenue" />

            <p className="text-xs text-muted-foreground">
              Gérez votre abonnement à tout moment depuis{" "}
              <Link href="/profil" className="underline hover:text-foreground">
                votre profil
              </Link>
              .
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

export default function AbonnementSuccesPage() {
  return (
    <Suspense>
      <AbonnementSuccesContent />
    </Suspense>
  );
}
