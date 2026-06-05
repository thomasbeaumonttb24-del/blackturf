import Link from "next/link";
import { Check, X, Zap, ChevronRight, Calculator } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";

const FEATURES_COMPARISON = [
  { label: "Programme PMU du jour", free: true, standard: true, expert: true },
  { label: "Cotes publiques", free: true, standard: true, expert: true },
  { label: "Prédictions IA complètes", free: false, standard: true, expert: true },
  { label: "Value Bets en temps réel", free: false, standard: true, expert: true },
  { label: "Calculateur de mise personnalisé", free: false, standard: true, expert: true },
  { label: "Alertes email + push", free: false, standard: true, expert: true },
  { label: "Bankroll tracker", free: false, standard: true, expert: true },
  { label: "Historique 6 mois", free: false, standard: true, expert: true },
  { label: "Steam Money Indicator (SPI)", free: false, standard: false, expert: true },
  { label: "Assistant IA (Claude Opus)", free: false, standard: false, expert: true },
  { label: "Créateur de stratégies", free: false, standard: false, expert: true },
  { label: "Historique 18 mois", free: false, standard: false, expert: true },
  { label: "Accès API", free: false, standard: false, expert: true },
  { label: "Support prioritaire", free: false, standard: false, expert: true },
];

export default function TarifsPage() {
  return (
    <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8 py-16">
      {/* Header */}
      <div className="text-center mb-16">
        <Badge variant="gold" className="mb-4">Tarifs</Badge>
        <h1 className="text-4xl font-bold mb-4">
          Des tarifs <span className="text-gradient">simples et transparents</span>
        </h1>
        <p className="text-muted-foreground text-lg max-w-xl mx-auto">
          Commencez gratuitement. Upgradez quand vous êtes convaincu.
          Annulez à tout moment.
        </p>
        <div className="mt-4 inline-flex items-center gap-2 text-sm text-brand-gold">
          <Zap className="h-4 w-4" />
          -20% avec l&apos;abonnement annuel
        </div>
      </div>

      {/* Plans */}
      <div className="grid md:grid-cols-3 gap-6 mb-16">
        {/* Découverte */}
        <Card className="card-hover">
          <CardContent className="p-8">
            <h2 className="text-xl font-bold mb-1">Découverte</h2>
            <p className="text-xs text-muted-foreground mb-3">Gratuit pour toujours</p>
            <div className="flex items-baseline gap-1 mb-6">
              <span className="text-4xl font-extrabold">0€</span>
              <span className="text-muted-foreground">/mois</span>
            </div>
            <ul className="space-y-3 mb-8">
              {["Programme PMU du jour", "Cotes publiques", "Classement IA (limité)", "1 alerte/jour"].map((f) => (
                <li key={f} className="flex items-center gap-2 text-sm">
                  <Check className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                  {f}
                </li>
              ))}
            </ul>
            <Button variant="outline" className="w-full" asChild>
              <Link href="/inscription">Commencer gratuitement</Link>
            </Button>
          </CardContent>
        </Card>

        {/* Standard */}
        <Card className="card-hover border-brand-gold ring-2 ring-brand-gold/30 relative">
          <div className="absolute -top-4 left-1/2 -translate-x-1/2">
            <Badge variant="gold">Recommandé</Badge>
          </div>
          <CardContent className="p-8">
            <h2 className="text-xl font-bold mb-1">Standard</h2>
            <div className="flex items-baseline gap-1 mb-1">
              <span className="text-4xl font-extrabold">19€</span>
              <span className="text-muted-foreground">/mois</span>
            </div>
            <p className="text-xs text-muted-foreground mb-6">ou 182€/an (−20%)</p>
            <ul className="space-y-3 mb-8">
              {[
                { label: "Prédictions IA complètes", icon: null },
                { label: "Value Bets illimités", icon: null },
                { label: "Calculateur de mise", icon: <Calculator className="h-3 w-3" /> },
                { label: "Alertes email + push", icon: null },
                { label: "Bankroll tracker", icon: null },
                { label: "Historique 6 mois", icon: null },
              ].map((f) => (
                <li key={f.label} className="flex items-center gap-2 text-sm">
                  <Check className="h-4 w-4 text-brand-gold flex-shrink-0" />
                  {f.label}
                  {f.icon && <span className="text-brand-gold">{f.icon}</span>}
                </li>
              ))}
            </ul>
            <Button variant="brand" className="w-full" size="lg" asChild>
              <Link href="/inscription?plan=standard">
                Essayer 7 jours gratuit <ChevronRight className="h-4 w-4" />
              </Link>
            </Button>
            <p className="text-center text-xs text-muted-foreground mt-2">Sans CB requis</p>
          </CardContent>
        </Card>

        {/* Expert */}
        <Card className="card-hover">
          <CardContent className="p-8">
            <h2 className="text-xl font-bold mb-1">Expert</h2>
            <div className="flex items-baseline gap-1 mb-1">
              <span className="text-4xl font-extrabold">39€</span>
              <span className="text-muted-foreground">/mois</span>
            </div>
            <p className="text-xs text-muted-foreground mb-6">ou 374€/an (−20%)</p>
            <ul className="space-y-3 mb-8">
              {[
                "Tout Standard",
                "Steam Money Indicator",
                "Assistant IA (Claude Opus)",
                "Créateur de stratégies",
                "Historique 18 mois",
                "Accès API",
                "Support prioritaire",
              ].map((f) => (
                <li key={f} className="flex items-center gap-2 text-sm">
                  <Check className="h-4 w-4 text-brand-emerald flex-shrink-0" />
                  {f}
                </li>
              ))}
            </ul>
            <Button variant="brand-outline" className="w-full" size="lg" asChild>
              <Link href="/inscription?plan=expert">
                Essayer Expert <ChevronRight className="h-4 w-4" />
              </Link>
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* Comparison table */}
      <div className="rounded-2xl border border-border overflow-hidden mb-12">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/30">
              <th className="text-left p-4 font-semibold">Fonctionnalité</th>
              <th className="text-center p-4 font-semibold">Découverte</th>
              <th className="text-center p-4 font-semibold text-brand-gold">Standard</th>
              <th className="text-center p-4 font-semibold text-brand-emerald">Expert</th>
            </tr>
          </thead>
          <tbody>
            {FEATURES_COMPARISON.map((row, i) => (
              <tr key={row.label} className={i % 2 === 0 ? "bg-muted/10" : ""}>
                <td className="p-4">{row.label}</td>
                <td className="p-4 text-center">
                  {row.free ? <Check className="h-4 w-4 text-muted-foreground mx-auto" /> : <X className="h-4 w-4 text-muted/30 mx-auto" />}
                </td>
                <td className="p-4 text-center">
                  {row.standard ? <Check className="h-4 w-4 text-brand-gold mx-auto" /> : <X className="h-4 w-4 text-muted/30 mx-auto" />}
                </td>
                <td className="p-4 text-center">
                  {row.expert ? <Check className="h-4 w-4 text-brand-emerald mx-auto" /> : <X className="h-4 w-4 text-muted/30 mx-auto" />}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* FAQ */}
      <div className="max-w-2xl mx-auto text-center">
        <h2 className="text-2xl font-bold mb-8">Questions fréquentes</h2>
        <div className="space-y-6 text-left">
          {[
            {
              q: "Puis-je annuler à tout moment ?",
              a: "Oui, sans frais ni condition. Votre abonnement reste actif jusqu'à la fin de la période.",
            },
            {
              q: "Les prédictions sont-elles garanties ?",
              a: "Non. BlackTurf est un outil d'aide à la décision basé sur l'IA. Les performances passées ne garantissent pas les résultats futurs.",
            },
            {
              q: "Quelles sources de données utilisez-vous ?",
              a: "PMU (données officielles), Geny, Letrot, Turfoo, météo OpenWeather. 10 sources agrégées en temps réel.",
            },
            {
              q: "Comment fonctionne le modèle IA ?",
              a: "Ensemble XGBoost (50%) + LightGBM (30%) + CatBoost (20%). 80+ features par partant. Brier Score < 0.18. Walk-forward validation 6 fenêtres. Retraining automatique nightly.",
            },
            {
              q: "Qu'est-ce que le Calculateur de mise ?",
              a: "Entrez votre mise → BlackTurf génère un plan personnalisé en 3 niveaux (sécurité, rendement, coup) selon votre profil de risque et les prédictions IA du jour.",
            },
          ].map((item) => (
            <div key={item.q} className="rounded-lg border border-border p-4">
              <h3 className="font-semibold mb-2">{item.q}</h3>
              <p className="text-sm text-muted-foreground">{item.a}</p>
            </div>
          ))}
        </div>
      </div>

      {/* CTA */}
      <div className="mt-16 text-center p-8 rounded-2xl gradient-hero border border-brand-gold/20">
        <h2 className="text-2xl font-bold mb-3">Prêt à parier plus intelligemment ?</h2>
        <p className="text-muted-foreground mb-6">7 jours d&apos;essai gratuit. Sans carte bancaire.</p>
        <Button variant="brand" size="xl" asChild>
          <Link href="/inscription?plan=standard">
            Commencer l&apos;essai gratuit <ChevronRight className="h-5 w-5" />
          </Link>
        </Button>
      </div>

      {/* Disclaimer */}
      <p className="text-center text-xs text-muted-foreground mt-8">
        ⚠️ Le jeu peut créer une dépendance. Interdit aux mineurs.
        Jouez de façon responsable — joueurs-info-service.fr — 09 74 75 13 13.
      </p>
    </div>
  );
}
