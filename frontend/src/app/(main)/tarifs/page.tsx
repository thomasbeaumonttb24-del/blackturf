import type { Metadata } from "next";
import { OG_IMAGE, jsonLd } from "@/lib/seo";
import Link from "next/link";
import { Check, X, Zap, ChevronRight, Gift } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { PlansTarifs } from "@/components/billing/PlansTarifs";
import { PassesTarifs } from "@/components/billing/PassesTarifs";

export const metadata: Metadata = {
  // Le corps de la page employait déjà trente et une fois le vocabulaire de l'IA sans
  // que le titre ni la description ne le disent.
  title: "Tarifs — pronostics PMU par IA, pass dès 5 € ou 12 €/mois",
  description:
    "Trois formules d'accès aux pronostics IA : Gratuit (programme et cotes), Standard 12 €/mois, Expert 19 €/mois, ou pass sans abonnement dès 5 € (jour, semaine, mois).",
  alternates: { canonical: "/tarifs" },
  openGraph: {
    // ALIGNÉ SUR LE <title>, et ce n'est pas cosmétique : `og:title` est l'une des
    // sources dont Google se sert pour fabriquer le lien de titre en résultat. Deux
    // formulations sans rapport — « Tarifs BlackTurf — Gratuit, Standard, Expert »
    // contre « Tarifs — pronostics PMU par IA à partir de 12 €/mois » — le laissent
    // trancher seul, et il peut retenir celle qui ne dit ni le prix ni l'IA.
    title: "Tarifs — pronostics PMU par IA, pass dès 5 € ou 12 €/mois",
    description: "Gratuit, Standard 12 €/mois, Expert 19 €/mois, ou pass sans abonnement dès 5 € (jour, semaine, mois).",
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
    { "@type": "Offer", name: "Standard annuel", price: "115.20", priceCurrency: "EUR", url: "https://blackturf.fr/tarifs", category: "Abonnement annuel" },
    { "@type": "Offer", name: "Expert annuel", price: "182.40", priceCurrency: "EUR", url: "https://blackturf.fr/tarifs", category: "Abonnement annuel" },
    { "@type": "Offer", name: "Pass Jour", price: "5", priceCurrency: "EUR", url: "https://blackturf.fr/tarifs", category: "Paiement unique" },
    { "@type": "Offer", name: "Pass Semaine", price: "12", priceCurrency: "EUR", url: "https://blackturf.fr/tarifs", category: "Paiement unique" },
    { "@type": "Offer", name: "Pass Mois", price: "24", priceCurrency: "EUR", url: "https://blackturf.fr/tarifs", category: "Paiement unique" },
  ],
};

// Questions affichées plus bas dans la page. Elles ne sont volontairement PAS balisées en
// FAQPage : depuis le 7 mai 2026, Google ne produit plus aucun résultat enrichi à partir de
// ce type. Le balisage resterait valide, mais sans le moindre effet en recherche.
const FAQ = [
  {
    q: "Comment fonctionne le parrainage ?",
    a: "Partagez votre lien personnel (Profil → Parrainage). Votre ami a 5 € de remise sur son premier abonnement, et dès qu'il a payé, 5 € sont déduits de votre prochaine mensualité. 4 amis abonnés dans le mois suffisent pour un mois Expert offert, 3 pour un mois Standard ; au-delà, vos crédits sont reportés au mois suivant.",
  },
  {
    q: "Puis-je annuler à tout moment ?",
    a: "Oui, sans frais ni condition. Votre abonnement reste actif jusqu'à la fin de la période.",
  },
  {
    q: "Comment fonctionnent les pass sans abonnement ?",
    a: "Pass Jour (5 €, 24 h), Pass Semaine (12 €, 7 jours) ou Pass Mois (24 €, 30 jours) : accès Expert complet, payé une fois. Aucun renouvellement : l'accès s'arrête seul à l'échéance et rien d'autre n'est prélevé. Un pass pris pendant qu'un autre court s'ajoute à la suite. L'accès étant immédiat, il n'ouvre ni droit de rétractation ni remboursement.",
  },
  {
    q: "Comment découvrir BlackTurf avant de m'engager ?",
    a: "Le compte gratuit montre le classement complet d'une course par jour. Pour tout voir sans abonnement, le Pass Jour à 5 € ouvre tout BlackTurf pendant 24 h.",
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
// Chaque ligne correspond à un contrôle d'accès RÉEL du backend : cotes-live et
// cotes-historique = compte connecté ; /enjeux = require_pro ; SPI, assistant et
// stratégies = Expert ; comparateur, confrontations et pronos presse = publics.
// Classement Découverte : 1 course à venir par jour, choisie par le bouton
// « Révéler » de la fiche (services/quota_classement.py) ; son plan de mise
// s'ouvre sur cette même course. Sans compte : aucun classement avant l'arrivée.
// Pas d'« Accès API » ni d'« Historique N mois » : rien ne les implémente.
type Cellule = boolean | string;

const FEATURES_COMPARISON: { groupe: string; lignes: { label: string; free: Cellule; standard: Cellule; expert: Cellule }[] }[] = [
  {
    groupe: "Courses & marché",
    lignes: [
      { label: "Programme PMU du jour + fiches partants", free: true, standard: true, expert: true },
      { label: "Cotes en direct + évolution cheval par cheval", free: true, standard: true, expert: true },
      { label: "Comparaison des cotes entre bookmakers", free: true, standard: true, expert: true },
      { label: "Argent engagé cheval par cheval", free: false, standard: true, expert: true },
      { label: "Argent pro détecté (SPI / steam)", free: false, standard: false, expert: true },
    ],
  },
  {
    groupe: "Analyse des chevaux",
    lignes: [
      { label: "Comparateur de 2 chevaux", free: true, standard: true, expert: true },
      { label: "Duels (confrontations directes)", free: true, standard: true, expert: true },
      { label: "Pronostics presse", free: true, standard: true, expert: true },
    ],
  },
  {
    groupe: "Algorithme BlackTurf",
    lignes: [
      { label: "Classement de l'algorithme (probabilités, cote juste, signaux)", free: "1 course/jour", standard: "5 courses/jour", expert: "Illimité" },
      { label: "Paris de valeur", free: false, standard: "Délai 15 min", expert: "Temps réel" },
      { label: "Plan de mise personnalisé", free: "Même course", standard: "5 courses/jour", expert: "Illimité" },
      { label: "Assistant IA (Claude Opus)", free: false, standard: false, expert: true },
      { label: "Créateur de stratégies + backtest 12 mois", free: false, standard: false, expert: true },
    ],
  },
  {
    groupe: "Défi et alertes",
    lignes: [
      { label: "Défi du mois (concours en points)", free: true, standard: true, expert: true },
      { label: "Alertes paris de valeur (e-mail + notifications)", free: false, standard: true, expert: true },
      { label: "Support prioritaire", free: false, standard: false, expert: true },
    ],
  },
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
          Commencez gratuitement. Abonnement résiliable à tout moment, ou pass sans abonnement dès 5 €.
        </p>
        <div className="mt-4 inline-flex items-center gap-2 text-sm text-brand-gold-dark">
          <Zap className="h-4 w-4" />
          -20% avec l&apos;abonnement annuel
        </div>
      </div>

      {/* Plans — un sélecteur mensuel/annuel, un seul bouton par formule */}
      <PlansTarifs />

      {/* Pass sans renouvellement : paiement unique, accès coupé à l'échéance. */}
      <PassesTarifs />

      {/* Parrainage : l'argument « abonnement gratuit » dit là où l'on regarde le prix. */}
      <section className="relative mb-12 overflow-hidden rounded-3xl bg-gradient-to-br from-stone-900 via-stone-900 to-stone-800 p-6 text-white shadow-[0_30px_60px_-30px_rgba(28,25,23,.7)] ring-1 ring-white/10 sm:p-8">
        <span className="tr-shine" aria-hidden />
        <div className="absolute -right-16 -top-16 h-56 w-56 rounded-full bg-amber-400/20 blur-3xl" aria-hidden />
        <div className="relative grid gap-6 md:grid-cols-[1fr_auto] md:items-center">
          <div>
            <p className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-300">
              <Gift className="h-3.5 w-3.5" aria-hidden /> Parrainage
            </p>
            <h2 className="mt-2 font-display text-2xl font-semibold leading-tight tracking-tight sm:text-3xl">
              Invitez vos amis, <span className="text-amber-300">ne payez plus votre abonnement</span>.
            </h2>
            <p className="mt-3 max-w-xl text-sm leading-relaxed text-stone-300">
              Chaque ami qui s&apos;abonne avec votre lien a 5 € de remise, et vous 5 € de moins sur votre
              prochaine mensualité, automatiquement. Sans limite d&apos;amis : au-delà du mois offert, vos
              crédits passent au mois suivant.
            </p>
            <Link
              href="/profil#parrainage"
              rel="nofollow"
              className="mt-5 inline-flex items-center gap-1.5 rounded-xl bg-gradient-to-b from-amber-300 to-amber-500 px-5 py-2.5 text-sm font-semibold text-stone-900 shadow-[0_8px_20px_-8px_rgba(245,158,11,.8),inset_0_1px_0_rgba(255,255,255,.5)] transition-transform hover:-translate-y-0.5"
            >
              Obtenir mon lien de parrainage <ChevronRight className="h-4 w-4" aria-hidden />
            </Link>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {[
              { formule: "Expert", prix: "19 €", amis: 4 },
              { formule: "Standard", prix: "12 €", amis: 3 },
            ].map((f) => (
              <div key={f.formule} className="rounded-2xl bg-white/[0.06] p-4 text-center ring-1 ring-white/15">
                <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-stone-400">{f.formule} · {f.prix}</p>
                <p className="mt-1 font-display text-4xl font-semibold text-amber-300">{f.amis}</p>
                <p className="text-xs text-stone-300">amis abonnés</p>
                <p className="mt-1 text-xs font-semibold text-emerald-300">= 1 mois offert</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Comparatif détaillé — une carte par formule sur mobile (Expert d'abord) */}
      <h2 className="text-xl sm:text-2xl font-bold text-center mb-6">Le détail des formules</h2>
      <div className="sm:hidden space-y-4 mb-12">
        {[
          { name: "Expert", key: "expert" as const, color: "text-brand-emerald-dark" },
          { name: "Standard", key: "standard" as const, color: "text-brand-gold-dark" },
          { name: "Découverte", key: "free" as const, color: "text-muted-foreground" },
        ].map((plan) => (
          <div key={plan.name} className={`rounded-2xl border p-4 ${plan.key === "expert" ? "border-brand-emerald ring-2 ring-brand-emerald/20" : "border-border"}`}>
            <h3 className={`font-semibold mb-3 ${plan.color}`}>{plan.name}</h3>
            <ul className="space-y-2">
              {FEATURES_COMPARISON.flatMap((g) => g.lignes).filter((row) => row[plan.key]).map((row) => (
                <li key={row.label} className="flex items-start gap-2 text-sm">
                  <Check className={`mt-0.5 h-4 w-4 flex-shrink-0 ${plan.color}`} />
                  <span>
                    {row.label}
                    {typeof row[plan.key] === "string" && (
                      <span className={`text-xs ${plan.color}`}> · {row[plan.key]}</span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      {/* Comparatif détaillé — tableau groupé, sm+ */}
      <div className="hidden sm:block rounded-2xl border border-border overflow-x-auto mb-12">
        <table className="w-full text-sm min-w-[560px]">
          <thead>
            <tr className="border-b border-border bg-muted/30">
              <th className="text-left p-4 font-semibold">Fonctionnalité</th>
              <th className="text-center p-4 font-semibold w-[17%]">Découverte</th>
              <th className="text-center p-4 font-semibold w-[17%] text-brand-gold-dark">Standard</th>
              <th className="text-center p-4 font-semibold w-[17%] text-brand-emerald-dark bg-brand-emerald/10">Expert</th>
            </tr>
          </thead>
          {FEATURES_COMPARISON.map((g) => (
            <tbody key={g.groupe}>
              <tr className="border-t border-border bg-muted/40">
                <th colSpan={4} className="px-4 py-2 text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{g.groupe}</th>
              </tr>
              {g.lignes.map((row) => (
                <tr key={row.label} className="border-t border-border/60">
                  <td className="px-4 py-3">{row.label}</td>
                  <td className="px-4 py-3 text-center">
                    {typeof row.free === "string"
                      ? <span className="text-muted-foreground text-xs">{row.free}</span>
                      : row.free ? <Check className="h-4 w-4 text-muted-foreground mx-auto" /> : <X className="h-4 w-4 text-muted-foreground/30 mx-auto" />}
                  </td>
                  <td className="px-4 py-3 text-center">
                    {typeof row.standard === "string"
                      ? <span className="text-brand-gold-dark text-xs font-medium">{row.standard}</span>
                      : row.standard ? <Check className="h-4 w-4 text-brand-gold-dark mx-auto" /> : <X className="h-4 w-4 text-muted-foreground/30 mx-auto" />}
                  </td>
                  <td className="px-4 py-3 text-center bg-brand-emerald/5">
                    {typeof row.expert === "string"
                      ? <span className="text-brand-emerald-dark text-xs font-semibold">{row.expert}</span>
                      : row.expert ? <Check className="h-4 w-4 text-brand-emerald-dark mx-auto" /> : <X className="h-4 w-4 text-muted-foreground/30 mx-auto" />}
                  </td>
                </tr>
              ))}
            </tbody>
          ))}
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
        <p className="text-muted-foreground mb-6">Abonnement dès 12 €/mois, ou tout BlackTurf pendant 24 h pour 5 €, sans abonnement.</p>
        {/* Ce bouton ouvrait directement Standard : on renvoie au choix des formules. */}
        <Button variant="brand" size="xl" asChild>
          <Link href="#formules">Choisir ma formule</Link>
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
