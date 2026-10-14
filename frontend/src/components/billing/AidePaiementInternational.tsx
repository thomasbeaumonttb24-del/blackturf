"use client";

import { useEffect, useState } from "react";
import { Globe } from "lucide-react";
import { regionPaiement, type RegionPaiement } from "@/lib/regionPaiement";

/**
 * Aide au paiement pour les visiteurs hors de France / d'Europe (cf. lib/regionPaiement).
 *
 * Stripe ne dit au client que « carte refusée » : sans explication, un acheteur
 * marocain réessaie la même carte puis abandonne (25 refus pour 2 ventes au
 * 2026-10-14). Le blocage vient presque toujours de SA banque — paiements
 * internationaux désactivés, dotation e-commerce non activée ou épuisée, carte
 * nationale — et se lève en quelques minutes dans l'appli bancaire.
 *
 * Rien n'est rendu en France, outre-mer et Europe, ni au rendu serveur : la
 * région se lit dans le navigateur, après hydratation.
 */

const CONSEILS: Record<RegionPaiement, { titre: string; points: string[] }> = {
  maroc: {
    titre: "Vous payez avec une carte marocaine ?",
    points: [
      "Activez la dotation « e-commerce / paiements internationaux » de votre carte dans l'appli de votre banque (ou auprès de votre conseiller) : sans elle, la banque refuse tout site étranger.",
      "Vérifiez que le plafond de paiement en ligne à l'international couvre le montant en euros.",
      "Le paiement se fait en euros : la conversion en dirhams est faite par votre banque.",
    ],
  },
  maghreb: {
    titre: "Vous payez depuis l'Algérie ou la Tunisie ?",
    points: [
      "Une carte nationale (CIB, Edahabia, carte en dinars) n'est pas acceptée sur un site étranger : il faut une carte Visa ou Mastercard internationale, en devises.",
      "Vérifiez auprès de votre banque que les paiements en ligne à l'étranger sont autorisés et que votre allocation couvre le montant en euros.",
    ],
  },
  afrique: {
    titre: "Vous payez depuis l'Afrique ?",
    points: [
      "Il faut une carte Visa ou Mastercard utilisable à l'international : activez les paiements en ligne à l'étranger dans l'appli de votre banque.",
      "Pas de carte bancaire ? Certains opérateurs de mobile money proposent une carte Visa virtuelle rechargeable : rechargez-la d'au moins le montant à payer, frais compris.",
    ],
  },
  international: {
    titre: "Vous payez avec une carte émise hors d'Europe ?",
    points: [
      "Autorisez les paiements en ligne à l'étranger dans l'appli de votre banque : le paiement est en euros, sur un site français.",
    ],
  },
};

type Props = {
  /** Version courte (une ligne), pour les bandeaux. */
  compact?: boolean;
  className?: string;
};

export function AidePaiementInternational({ compact = false, className }: Props) {
  const [region, setRegion] = useState<RegionPaiement | null>(null);
  useEffect(() => setRegion(regionPaiement()), []);
  if (!region) return null;

  const { titre, points } = CONSEILS[region];
  const contact = (
    <>
      Toujours refusé ? Écrivez à{" "}
      <a href="mailto:contact@blackturf.fr" className="underline">contact@blackturf.fr</a>
      , on trouve une solution.
    </>
  );

  if (compact) {
    return (
      <p className={className}>
        <span className="font-semibold">{titre}</span> {points[0]} {contact}
      </p>
    );
  }

  return (
    <div
      className={
        className ??
        "mx-auto mt-6 max-w-2xl rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-left text-sm text-amber-950"
      }
    >
      <p className="flex items-center gap-2 font-semibold">
        <Globe className="h-4 w-4 shrink-0" aria-hidden /> {titre}
      </p>
      <ul className="mt-1.5 list-disc space-y-1 pl-5 text-xs leading-relaxed">
        {points.map((p) => <li key={p}>{p}</li>)}
      </ul>
      <p className="mt-1.5 text-xs">{contact}</p>
    </div>
  );
}
