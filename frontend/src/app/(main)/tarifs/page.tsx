import type { Metadata } from "next";
import { OG_IMAGE, jsonLd } from "@/lib/seo";
import Link from "next/link";
import { Check, X, Zap, ChevronRight, Calculator } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { CheckoutButton } from "@/components/billing/CheckoutButton";

export const metadata: Metadata = {
  // Le corps de la page employait déjà trente et une fois le vocabulaire de l'IA sans
  // que le titre ni la description ne le disent.
  title: "Tarifs — pronostics PMU par IA à partir de 12 €/mois",
  description:
    "Trois formules d'accès aux pronostics IA : Gratuit (programme et cotes), Standard 12 €/mois, Expert 19 €/mois. Sans engagement, 7 jours d'essai.",
  alternates: { canonical: "/tarifs" },
  openGraph: {
    title: "Tarifs BlackTurf — Gratuit, Standard, Expert",
    description: "Prédictions IA, paris de valeur et calculateur de mise. Sans engagement.",
    url: "https://blackturf.fr/tarifs",
    images: [OG_IMAGE],
  },
};

// `Product` faisait juger cette page comme une FICHE MARCHAND par Google (Search Console
// la remontait en erreur) : ce balisage attend des frais de port, une politique de retour
// et une disponibilité de stock, qui n'ont aucun sens pour un abonnement logiciel.
// `SoftwareApplication` est le type prévu pour un service en ligne facturé à l'abonnement,
// et reste éligible aux résultats enrichis.
const offersJsonLd = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: "BlackTurf — Conseiller IA paris hippiques PMU",
  description:
    "Pronostics et paris de valeur PMU par intelligence artificielle, plan de mise personnalisé.",
  applicationCategory: "SportsApplication",
  operatingSystem: "Web",
  url: "https://blackturf.fr",
  inLanguage: "fr-FR",
  author: { "@type": "Organization", name: "BlackTurf", url: "https://blackturf.fr" },
  offers: [
    { "@type": "Offer", name: "Gratuit", price: "0", priceCurrency: "EUR", url: "https://blackturf.fr/tarifs", category: "Abonnement mensuel" },
    { "@type": "Offer", name: "Standard", price: "12", priceCurrency: "EUR", url: "https://blackturf.fr/tarifs", category: "Abonnement mensuel" },
    { "@type": "Offer", name: "Expert", price: "19", priceCurrency: "EUR", url: "https://blackturf.fr/tarifs", category: "Abonnement mensuel" },
  ],
};

// Questions affichées plus bas dans la page. Elles ne sont volontairement PAS balisées en
// FAQPage : depuis le 7 mai 2026, Google ne produit plus aucun résultat enrichi à partir de
// ce type. Le balisage resterait valide, mais sans le moindre effet en recherche.
const FAQ = [
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
];


// Une cellule vaut true (✓), false (✗) ou une CHAÎNE quand la différence entre
// plans est une quantité, pas une présence : afficher ✓ partout laisserait croire
// que Standard donne un accès illimité alors qu'il est plafonné (cf. quotas
// PRONO_DAILY_LIMITS / MISE_PLAN_DAILY_LIMITS côté backend), et masquerait le
// délai de 15 min appliqué à Standard sur les paris de valeur.
type Cellule = boolean | string;

const FEATURES_COMPARISON: { label: string; free: Cellule; standard: Cellule; expert: Cellule }[] = [
  { label: "Programme PMU du jour", free: true, standard: true, expert: true },
  { label: "Cotes publiques", free: true, standard: true, expert: true },
  { label: "Prédictions IA", free: "1 course/jour", standard: "5 courses/jour", expert: "Illimité" },
  { label: "Paris de valeur", free: false, standard: "Délai 15 min", expert: "Temps réel" },
  { label: "Calculateur de mise personnalisé", free: false, standard: true, expert: true },
  { label: "Alertes e-mail + notifications", free: false, standard: true, expert: true },
  { label: "Suivi de capital", free: false, standard: true, expert: true },
  { label: "Historique 6 mois", free: false, standard: true, expert: true },
  { label: "Indicateur de mouvement de cote (SPI)", free: false, standard: false, expert: true },
  { label: "Assistant IA (Claude Opus)", free: false, standard: false, expert: true },
  { label: "Créateur de stratégies", free: false, standard: false, expert: true },
  { label: "Historique 18 mois", free: false, standard: false, expert: true },
  { label: "Accès API", free: false, standard: false, expert: true },
  { label: "Support prioritaire", free: false, standard: false, expert: true },
];

export default function TarifsPage() {
  return (
    <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8 py-10 sm:py-16">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd(offersJsonLd) }} />
      {/* Header */}
      <div className="text-center mb-10 sm:mb-16">
        <Badge variant="gold" className="mb-4">Tarifs</Badge>
        <h1 className="text-2xl sm:text-4xl font-bold mb-3 sm:mb-4">
          Des tarifs <span className="text-gradient">simples et transparents</span>
        </h1>
        <p className="text-muted-foreground text-sm sm:text-lg max-w-xl mx-auto">
          Commencez gratuitement. Annulez à tout moment.
        </p>
        <div className="mt-4 inline-flex items-center gap-2 text-sm text-brand-gold-dark">
          <Zap className="h-4 w-4" />
          -20% avec l&apos;abonnement annuel
        </div>
      </div>

      {/* Plans */}
      <div className="grid md:grid-cols-3 gap-5 sm:gap-6 mb-12 sm:mb-16">
        {/* Découverte */}
        <Card className="card-hover">
          <CardContent className="p-6 sm:p-8">
            <h2 className="text-xl font-bold mb-1">Découverte</h2>
            <p className="text-xs text-muted-foreground mb-3">Gratuit pour toujours</p>
            <div className="flex items-baseline gap-1 mb-6">
              <span className="text-4xl font-extrabold">0€</span>
              <span className="text-muted-foreground">/mois</span>
            </div>
            <ul className="space-y-3 mb-8">
              {["Programme PMU du jour", "Cotes publiques", "Classement IA : 1 course/jour", "1 alerte par jour"].map((f) => (
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
        <Card className="card-hover relative">
          <CardContent className="p-6 sm:p-8">
            <h2 className="text-xl font-bold mb-1">Standard</h2>
            <div className="flex items-baseline gap-1 mb-1">
              <span className="text-4xl font-extrabold">12€</span>
              <span className="text-muted-foreground">/mois</span>
            </div>
            <p className="text-xs text-muted-foreground mb-6">ou 115€/an (−20%)</p>
            <ul className="space-y-3 mb-8">
              {[
                { label: "Prédictions IA : 5 courses/jour", icon: null },
                { label: "Paris de valeur illimités (délai 15 min)", icon: null },
                { label: "Calculateur de mise", icon: <Calculator className="h-3 w-3" /> },
                { label: "Alertes e-mail + notifications", icon: null },
                { label: "Suivi de capital", icon: null },
                { label: "Historique 6 mois", icon: null },
              ].map((f) => (
                <li key={f.label} className="flex items-center gap-2 text-sm">
                  <Check className="h-4 w-4 text-brand-gold-dark flex-shrink-0" />
                  {f.label}
                  {f.icon && <span className="text-brand-gold-dark">{f.icon}</span>}
                </li>
              ))}
            </ul>
            <CheckoutButton
              plan="standard"
              periodicite="monthly"
              label="Essayer 7 jours gratuit"
              variant="brand-outline"
              className="w-full"
            />
            <p className="text-center text-xs text-muted-foreground mt-2">Sans CB requis</p>
          </CardContent>
        </Card>

        {/* Expert */}
        <Card className="card-hover border-brand-emerald ring-2 ring-brand-emerald/30 relative">
          <div className="absolute -top-4 left-1/2 -translate-x-1/2">
            <Badge variant="gold">Recommandé</Badge>
          </div>
          <CardContent className="p-6 sm:p-8">
            <h2 className="text-xl font-bold mb-1">Expert</h2>
            <div className="flex items-baseline gap-1 mb-1">
              <span className="text-4xl font-extrabold">19€</span>
              <span className="text-muted-foreground">/mois</span>
            </div>
            <p className="text-xs text-muted-foreground mb-6">ou 182€/an (−20%)</p>
            <ul className="space-y-3 mb-8">
              {[
                "Tout Standard",
                "Indicateur de mouvement de cote",
                "Assistant IA (Claude Opus)",
                "Créateur de stratégies",
                "Historique 18 mois",
                "Accès API",
                "Support prioritaire",
              ].map((f) => (
                <li key={f} className="flex items-center gap-2 text-sm">
                  <Check className="h-4 w-4 text-brand-emerald-dark flex-shrink-0" />
                  {f}
                </li>
              ))}
            </ul>
            <CheckoutButton
              plan="expert"
              periodicite="monthly"
              label="Essayer 7 jours gratuit"
              variant="brand"
              className="w-full"
            />
            <p className="text-center text-xs text-muted-foreground mt-2">Sans CB requis</p>
          </CardContent>
        </Card>
      </div>

      {/* Comparison — stacked cards on mobile */}
      <div className="sm:hidden space-y-4 mb-12">
        {[
          { name: "Découverte", key: "free" as const, color: "text-muted-foreground" },
          { name: "Standard", key: "standard" as const, color: "text-brand-gold-dark" },
          { name: "Expert", key: "expert" as const, color: "text-brand-emerald-dark" },
        ].map((plan) => (
          <div key={plan.name} className="rounded-2xl border border-border p-4">
            <h3 className={`font-semibold mb-3 ${plan.color}`}>{plan.name}</h3>
            <ul className="space-y-2">
              {FEATURES_COMPARISON.filter((row) => row[plan.key]).map((row) => (
                <li key={row.label} className="flex items-center gap-2 text-sm">
                  <Check className={`h-4 w-4 flex-shrink-0 ${plan.color}`} />
                  {row.label}
                  {typeof row[plan.key] === "string" && (
                    <span className={`text-xs ${plan.color}`}>· {row[plan.key]}</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      {/* Comparison table — sm+ */}
      <div className="hidden sm:block rounded-2xl border border-border overflow-x-auto mb-12">
        <table className="w-full text-sm min-w-[520px]">
          <thead>
            <tr className="border-b border-border bg-muted/30">
              <th className="text-left p-4 font-semibold">Fonctionnalité</th>
              <th className="text-center p-4 font-semibold">Découverte</th>
              <th className="text-center p-4 font-semibold text-brand-gold-dark">Standard</th>
              <th className="text-center p-4 font-semibold text-brand-emerald-dark">Expert</th>
            </tr>
          </thead>
          <tbody>
            {FEATURES_COMPARISON.map((row, i) => (
              <tr key={row.label} className={i % 2 === 0 ? "bg-muted/10" : ""}>
                <td className="p-4">{row.label}</td>
                <td className="p-4 text-center">
                  {typeof row.free === "string"
                    ? <span className="text-muted-foreground text-xs">{row.free}</span>
                    : row.free ? <Check className="h-4 w-4 text-muted-foreground mx-auto" /> : <X className="h-4 w-4 text-muted/30 mx-auto" />}
                </td>
                <td className="p-4 text-center">
                  {typeof row.standard === "string"
                    ? <span className="text-brand-gold-dark text-xs font-medium">{row.standard}</span>
                    : row.standard ? <Check className="h-4 w-4 text-brand-gold-dark mx-auto" /> : <X className="h-4 w-4 text-muted/30 mx-auto" />}
                </td>
                <td className="p-4 text-center">
                  {typeof row.expert === "string"
                    ? <span className="text-brand-emerald-dark text-xs font-medium">{row.expert}</span>
                    : row.expert ? <Check className="h-4 w-4 text-brand-emerald-dark mx-auto" /> : <X className="h-4 w-4 text-muted/30 mx-auto" />}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* FAQ */}
      <div className="max-w-2xl mx-auto text-center">
        <h2 className="text-xl sm:text-2xl font-bold mb-6 sm:mb-8">Questions fréquentes</h2>
        <div className="space-y-6 text-left">
          {FAQ.map((item) => (
            <div key={item.q} className="rounded-lg border border-border p-4">
              <h3 className="font-semibold mb-2">{item.q}</h3>
              <p className="text-sm text-muted-foreground">{item.a}</p>
            </div>
          ))}
        </div>
      </div>

      {/* CTA */}
      <div className="mt-12 sm:mt-16 text-center p-6 sm:p-8 rounded-2xl gradient-hero border border-brand-gold/20">
        <h2 className="text-xl sm:text-2xl font-bold mb-3">Prêt à parier plus intelligemment ?</h2>
        <p className="text-muted-foreground mb-6">7 jours d&apos;essai gratuit. Carte requise, aucun prélèvement avant la fin de l&apos;essai.</p>
        <CheckoutButton
          plan="standard"
          periodicite="monthly"
          label="Commencer l'essai gratuit"
          variant="brand"
          size="xl"
          className="w-auto"
        />
      </div>

      {/* Disclaimer */}
      <p className="text-center text-xs text-muted-foreground mt-8">
        ⚠️ Le jeu peut créer une dépendance. Interdit aux mineurs.
        Jouez de façon responsable — joueurs-info-service.fr — 09 74 75 13 13.
      </p>
    </div>
  );
}
