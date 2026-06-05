"use client";

import { useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { CheckCircle, Loader2, ArrowRight, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useAuth } from "@/hooks/useAuth";

function AbonnementSuccesContent() {
  const searchParams = useSearchParams();
  const { refreshUser } = useAuth();
  const [loading, setLoading] = useState(true);
  const plan = searchParams.get("plan") || "standard";

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
  const planDesc =
    plan === "expert"
      ? "Prédictions illimitées, assistant IA, créateur de stratégies, backtest 365 jours."
      : "5 prédictions/jour, value bets, calculateur de mise, alertes push & email.";

  return (
    <div className="min-h-[70vh] flex items-center justify-center px-4">
      <div className="max-w-lg w-full text-center">
        {loading ? (
          <div className="space-y-4">
            <Loader2 className="h-12 w-12 animate-spin text-brand-gold mx-auto" />
            <p className="text-muted-foreground">Activation de votre abonnement…</p>
          </div>
        ) : (
          <div className="animate-fade-in space-y-6">
            {/* Success icon */}
            <div className="h-20 w-20 rounded-full bg-brand-emerald/15 border border-brand-emerald/30 flex items-center justify-center mx-auto gold-glow">
              <CheckCircle className="h-10 w-10 text-brand-emerald" />
            </div>

            <div>
              <h1 className="text-3xl font-extrabold mb-2">
                Bienvenue sur BlackTurf{" "}
                <span className="text-gradient">{planLabel}</span> !
              </h1>
              <p className="text-muted-foreground">{planDesc}</p>
            </div>

            <Card className="border-brand-gold/20 bg-brand-gold/5">
              <CardContent className="p-5 space-y-3">
                <p className="text-sm font-semibold text-brand-gold mb-3">
                  🎯 Pour commencer maintenant :
                </p>
                {[
                  { icon: "🏇", text: "Consultez le programme du jour et ses analyses IA" },
                  { icon: "⭐", text: "Repérez les value bets en temps réel" },
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
                  Voir le programme <ArrowRight className="h-4 w-4" />
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
                <Link href="/value-bets">Value Bets live</Link>
              </Button>
            </div>

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
