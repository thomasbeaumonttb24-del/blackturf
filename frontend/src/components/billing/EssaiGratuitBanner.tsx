"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Gift, X } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { peutDemarrerEssai } from "@/lib/auth";
import { CheckoutButton } from "@/components/billing/CheckoutButton";

/**
 * Essai de 7 jours à prendre — bandeau des comptes gratuits.
 *
 * Constat du 2026-09-13 en production : 44 comptes gratuits, 2 seulement ont
 * jamais ouvert l'essai. Tous les appels existants renvoyaient vers /tarifs
 * (« Passer Standard — 12 €/mois ») : l'utilisateur lisait un prix, pas une
 * offre gratuite à laquelle il a droit. Ce bandeau dit qu'elle l'attend et ouvre
 * le paiement sécurisé en un clic.
 *
 * Masquable (3 jours) : contrairement aux bandeaux de carte manquante ou de
 * paiement en échec, rien n'est cassé ici — insister sans relâche ferait fuir.
 * La carte demandée est dite AVANT le clic : la découvrir chez Stripe est la
 * cause probable des 11 checkouts entamés puis abandonnés.
 */
const CLE_MASQUE = "bt_essai_banner_masque";
const MASQUE_MS = 3 * 24 * 3600 * 1000;
// Pages où l'offre est déjà l'objet de l'écran : le bandeau ferait doublon.
const PAGES_SANS_BANDEAU = ["/tarifs", "/abonnement", "/profil"];

export function EssaiGratuitBanner() {
  const { user, loading } = useAuth();
  const pathname = usePathname();
  // Masqué par défaut jusqu'à lecture du stockage : évite d'afficher puis retirer.
  const [masque, setMasque] = useState(true);

  useEffect(() => {
    try {
      const t = Number(localStorage.getItem(CLE_MASQUE) || 0);
      setMasque(Boolean(t) && Date.now() - t < MASQUE_MS);
    } catch {
      setMasque(false);
    }
  }, []);

  if (loading || masque || !peutDemarrerEssai(user)) return null;
  if (PAGES_SANS_BANDEAU.some((p) => pathname?.startsWith(p))) return null;

  const fermer = () => {
    setMasque(true);
    try {
      localStorage.setItem(CLE_MASQUE, String(Date.now()));
    } catch {
      /* masqué pour cette page seulement */
    }
  };

  return (
    <div className="border-b border-emerald-200 bg-gradient-to-r from-emerald-50 via-white to-amber-50">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5 text-sm text-slate-800">
        <Gift className="h-4 w-4 shrink-0 text-emerald-700" aria-hidden />
        <p className="min-w-0 flex-1">
          <span className="font-semibold">{user?.prenom ? `${user.prenom}, v` : "V"}otre essai Standard de 7 jours est offert</span>
          {" "}: pronostics complets, paris de valeur et plans de mise.{" "}
          <span className="text-slate-600">Carte demandée, 0 € prélevé avant la fin de l&apos;essai, résiliable en un clic.</span>
        </p>
        <div className="flex items-center gap-3">
          <CheckoutButton
            plan="standard"
            periodicite="monthly"
            label="Démarrer mon essai gratuit"
            size="default"
            className="h-8 px-3 text-[13px]"
          />
          <Link href="/tarifs" className="text-[13px] font-medium text-slate-600 underline underline-offset-2 hover:text-slate-900">
            Comparer
          </Link>
          <button onClick={fermer} className="text-slate-500 hover:text-slate-800" aria-label="Masquer ce rappel pendant 3 jours">
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
