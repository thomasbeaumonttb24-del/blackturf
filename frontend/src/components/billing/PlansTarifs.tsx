"use client";

import { useState } from "react";
import Link from "next/link";
import { Check, Crown, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CheckoutButton } from "@/components/billing/CheckoutButton";
import { MentionPaiement } from "@/components/billing/MentionPaiement";

type Periodicite = "monthly" | "annual";

// Prix affichés = prix Stripe (stripe_routes.py). L'annuel est payé en une fois ;
// on affiche son équivalent mensuel, avec le montant réellement prélevé dessous.
const PRIX = {
  standard: { monthly: "12€", annual: "9,60€", annuelTotal: "115,20 €" },
  expert: { monthly: "19€", annual: "15,20€", annuelTotal: "182,40 €" },
};

const DECOUVERTE = [
  "Programme PMU du jour",
  "Cotes en direct + évolution cheval par cheval",
  "Comparateur de 2 chevaux, duels, pronos presse",
  "Classement complet de l'algorithme : 1 course/jour",
  "Plan de mise sur cette même course",
  "Défi du mois : 30 jours Expert à gagner",
];

const STANDARD = [
  "Tout Découverte",
  "Argent engagé cheval par cheval",
  "Classement de l'algorithme : 5 courses/jour",
  "Paris de valeur (15 min de délai)",
  "Plan de mise : 5 courses/jour",
  "Alertes e-mail + notifications",
];

// Liste COMPLÈTE plutôt que « Tout Standard » : c'est la formule que la page
// pousse, elle doit se lire sans aller comparer avec la carte voisine.
const EXPERT = [
  "Classement de l'algorithme illimité",
  "Paris de valeur en temps réel",
  "Plan de mise illimité",
  "Argent pro détecté (SPI / steam)",
  "Assistant IA (Claude Opus)",
  "Créateur de stratégies + backtest 12 mois",
  "Argent engagé cheval par cheval",
  "Alertes e-mail + notifications",
  "Support prioritaire",
];

export function PlansTarifs() {
  const [periodicite, setPeriodicite] = useState<Periodicite>("monthly");
  const annuel = periodicite === "annual";

  return (
    <div id="formules" className="scroll-mt-24 mb-12 sm:mb-16">
      {/* Un seul choix de période pour toute la page : un bouton par carte au lieu de deux. */}
      <div className="mb-8 flex justify-center">
        <div role="radiogroup" aria-label="Période de facturation" className="inline-flex rounded-full border border-border bg-muted/40 p-1 text-sm">
          {([
            { v: "monthly", label: "Mensuel" },
            { v: "annual", label: "Annuel" },
          ] as const).map((o) => (
            <button
              key={o.v}
              type="button"
              role="radio"
              aria-checked={periodicite === o.v}
              onClick={() => setPeriodicite(o.v)}
              className={`inline-flex items-center gap-1.5 rounded-full px-4 py-1.5 font-medium transition-colors ${
                periodicite === o.v ? "bg-white text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {o.label}
              {o.v === "annual" && (
                <span className="rounded-full bg-emerald-100 px-1.5 py-0.5 text-[10px] font-bold text-emerald-800">−20 %</span>
              )}
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-5 sm:gap-6 md:grid-cols-3 md:items-center">
        {/* Découverte */}
        <div className="order-3 md:order-none rounded-2xl border border-border bg-white p-6 sm:p-7">
          <h2 className="text-lg font-bold">Découverte</h2>
          <p className="text-xs text-muted-foreground">Pour découvrir, gratuit pour toujours</p>
          <div className="mt-4 mb-5 flex items-baseline gap-1">
            <span className="text-3xl font-extrabold">0€</span>
            <span className="text-muted-foreground">/mois</span>
          </div>
          <ul className="mb-6 space-y-2.5">
            {DECOUVERTE.map((f) => (
              <li key={f} className="flex items-start gap-2 text-sm">
                <Check className="mt-0.5 h-4 w-4 flex-shrink-0 text-muted-foreground" />
                {f}
              </li>
            ))}
          </ul>
          <Button variant="ghost" className="w-full" asChild>
            <Link href="/inscription">Créer mon compte gratuit</Link>
          </Button>
        </div>

        {/* Standard */}
        <div className="order-2 md:order-none rounded-2xl border border-border bg-white p-6 sm:p-7">
          <h2 className="text-lg font-bold">Standard</h2>
          <p className="text-xs text-muted-foreground">L&apos;essentiel, avec des quotas</p>
          <div className="mt-4 flex items-baseline gap-1">
            <span className="text-3xl font-extrabold">{PRIX.standard[periodicite]}</span>
            <span className="text-muted-foreground">/mois</span>
          </div>
          <p className="mb-5 h-4 text-xs text-muted-foreground">
            {annuel ? `${PRIX.standard.annuelTotal} payés en une fois` : "Sans engagement"}
          </p>
          <ul className="mb-6 space-y-2.5">
            {STANDARD.map((f) => (
              <li key={f} className="flex items-start gap-2 text-sm">
                <Check className="mt-0.5 h-4 w-4 flex-shrink-0 text-brand-gold-dark" />
                {f}
              </li>
            ))}
          </ul>
          <CheckoutButton
            plan="standard"
            periodicite={periodicite}
            label="Choisir Standard"
            variant="outline"
            size="default"
            className="w-full"
          />
        </div>

        {/* Expert — la formule mise en avant */}
        <div className="order-1 md:order-none relative rounded-3xl bg-gradient-to-br from-stone-900 via-stone-900 to-emerald-950 p-6 text-white shadow-[0_30px_60px_-25px_rgba(6,78,59,.65)] ring-2 ring-amber-400/70 sm:p-8 md:scale-[1.04]">
          <div className="absolute -top-3.5 left-1/2 -translate-x-1/2">
            <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-gradient-to-b from-amber-300 to-amber-500 px-3 py-1 text-xs font-bold text-stone-900 shadow">
              <Crown className="h-3.5 w-3.5" aria-hidden /> Recommandé
            </span>
          </div>
          <h2 className="text-xl font-bold">Expert</h2>
          <p className="text-xs text-stone-300">Tout BlackTurf, sans aucune limite</p>
          <div className="mt-4 flex items-baseline gap-1">
            <span className="text-5xl font-extrabold text-amber-300">{PRIX.expert[periodicite]}</span>
            <span className="text-stone-300">/mois</span>
          </div>
          <p className="mb-5 h-4 text-xs text-stone-300">
            {annuel
              ? `${PRIX.expert.annuelTotal} payés en une fois`
              : "Seulement 7 € de plus que Standard"}
          </p>
          <ul className="mb-7 space-y-2.5">
            {EXPERT.map((f, i) => (
              <li key={f} className="flex items-start gap-2 text-sm">
                {i < 6
                  ? <Sparkles className="mt-0.5 h-4 w-4 flex-shrink-0 text-amber-300" aria-hidden />
                  : <Check className="mt-0.5 h-4 w-4 flex-shrink-0 text-emerald-300" aria-hidden />}
                <span className={i < 6 ? "font-medium" : "text-stone-200"}>{f}</span>
              </li>
            ))}
          </ul>
          <CheckoutButton
            plan="expert"
            periodicite={periodicite}
            label="Essayer Expert 7 jours gratuit"
            variant="brand"
            size="lg"
            className="h-12 w-full text-base"
          />
          <div className="[&_p]:text-stone-300 [&_p.text-emerald-700]:text-emerald-300">
            <MentionPaiement />
          </div>
        </div>
      </div>

      {annuel && (
        <p className="mx-auto mt-6 max-w-xl text-center text-[11px] leading-snug text-muted-foreground">
          Annuel : engagement 12 mois, payé en une fois ; résiliable à tout moment pour la fin de l&apos;année.
          Rappel par e-mail un mois avant la reconduction.
        </p>
      )}
    </div>
  );
}
