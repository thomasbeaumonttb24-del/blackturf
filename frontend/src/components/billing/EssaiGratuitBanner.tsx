"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Gift, X } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { peutDemarrerEssai, peutProfiterRemise } from "@/lib/auth";
import { Button } from "@/components/ui/button";

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

  // Filleul : pas d'essai, mais 5 € de remise qui l'attendent — même bandeau, autre offre.
  const remise = peutProfiterRemise(user);
  if (loading || masque || !(remise || peutDemarrerEssai(user))) return null;
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
        {remise ? (
          <p className="min-w-0 flex-1">
            <span className="font-semibold">{user?.prenom ? `${user.prenom}, v` : "V"}os 5 € de parrainage vous attendent</span>
            {" "}: déduits automatiquement de votre premier abonnement.{" "}
            <span className="text-slate-600">Sans engagement, résiliable en un clic.</span>
          </p>
        ) : (
          <p className="min-w-0 flex-1">
            <span className="font-semibold">{user?.prenom ? `${user.prenom}, v` : "V"}otre essai de 7 jours est offert</span>
            {" "}: Standard ou Expert, pronostics complets, paris de valeur et plans de mise.{" "}
            <span className="text-slate-600">Carte demandée, 0 € prélevé avant la fin de l&apos;essai, résiliable en un clic.</span>
          </p>
        )}
        <div className="flex items-center gap-3">
          {/* Renvoie au choix de la formule : le bouton ouvrait directement Standard
              en un clic, sans laisser choisir Expert. */}
          <Button variant="brand" size="default" className="h-8 px-3 text-[13px]" asChild>
            <Link href="/tarifs#formules">{remise ? "Choisir ma formule (−5 €)" : "Choisir mon essai gratuit"}</Link>
          </Button>
          <button onClick={fermer} className="text-slate-500 hover:text-slate-800" aria-label="Masquer ce rappel pendant 3 jours">
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
