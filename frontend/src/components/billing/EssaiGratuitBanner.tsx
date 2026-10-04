"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Gift, X, Zap } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { peutDebloquer, peutProfiterRemise } from "@/lib/auth";
import { Button } from "@/components/ui/button";

/**
 * Bandeau des comptes gratuits : tout BlackTurf dès 5 €, sans abonnement.
 *
 * Nom historique : il portait l'essai de 7 jours (constat du 2026-09-13 :
 * 44 comptes gratuits, 2 essais ouverts). L'essai est supprimé pour les
 * nouveaux clients depuis 2026-10 ; il annonce désormais les pass (Jour 5 €,
 * Semaine 12 €, Mois 24 €), paiement unique sans renouvellement. Nom et export
 * conservés pour ne pas casser les imports.
 *
 * Masquable (3 jours) : contrairement aux bandeaux de carte manquante ou de
 * paiement en échec, rien n'est cassé ici — insister sans relâche ferait fuir.
 */
// Clé inchangée : DefiBandeau la lit pour savoir si ce bandeau est à l'écran.
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

  // Filleul : 5 € de remise qui l'attendent sur son abonnement — même bandeau, autre offre.
  const remise = peutProfiterRemise(user);
  if (loading || masque || !(remise || peutDebloquer(user))) return null;
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
        {remise
          ? <Gift className="h-4 w-4 shrink-0 text-emerald-700" aria-hidden />
          : <Zap className="h-4 w-4 shrink-0 text-emerald-700" aria-hidden />}
        {remise ? (
          <p className="min-w-[14rem] flex-1">
            <span className="font-semibold">{user?.prenom ? `${user.prenom}, v` : "V"}os 5 € de parrainage vous attendent</span>
            {" "}: remboursés dès votre premier abonnement ou Pass Semaine/Mois.{" "}
            <span className="text-slate-600">Sans engagement, résiliable en un clic.</span>
          </p>
        ) : (
          <p className="min-w-[14rem] flex-1">
            <span className="font-semibold">Débloquez tout BlackTurf dès 5 € — sans abonnement</span>
            {" "}: pronostics complets, paris de valeur et plans de mise.{" "}
            <span className="text-slate-600">Pass Jour, Semaine ou Mois, paiement unique, l&apos;accès se coupe seul à la fin.</span>
          </p>
        )}
        <div className="flex items-center gap-3">
          <Button variant="brand" size="default" className="h-8 px-3 text-[13px]" asChild>
            <Link href={remise ? "/tarifs#formules" : "/tarifs#passes"}>{remise ? "Choisir ma formule (5 € remboursés)" : "Voir les formules"}</Link>
          </Button>
          <button onClick={fermer} className="text-slate-500 hover:text-slate-800" aria-label="Masquer ce rappel pendant 3 jours">
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
