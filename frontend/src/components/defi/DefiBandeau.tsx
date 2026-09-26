"use client";

/**
 * Bandeau d'annonce du Défi du mois, en haut de toutes les pages du site.
 *
 * Il porte le leader du moment (le classement « se voit » partout) et un lien pour
 * participer. Masquable pour le mois en cours seulement : le mois suivant, c'est un
 * nouveau défi, il revient.
 *
 * Il se tait quand le bandeau d'essai gratuit est à l'écran : deux appels à l'action
 * empilés en haut de page, c'est un de trop, et l'essai rapporte davantage.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import useSWR from "swr";
import { X } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { peutDemarrerEssai } from "@/lib/auth";
import { defiApi } from "@/lib/api";
import { DEFI_FOND, DefiEmbleme, dateLancement, formatPts, planLabel, formatNombre } from "@/components/defi/kit";
import { cn } from "@/lib/utils";

const PAGES_SANS_BANDEAU = ["/defi", "/tarifs", "/abonnement"];
// Mêmes clé et durée que EssaiGratuitBanner : on sait ainsi s'il est affiché.
const CLE_MASQUE_ESSAI = "bt_essai_banner_masque";
const MASQUE_ESSAI_MS = 3 * 24 * 3600 * 1000;

export function DefiBandeau() {
  const { user, loading } = useAuth();
  const pathname = usePathname();
  const [masque, setMasque] = useState(true);
  const [essaiMasque, setEssaiMasque] = useState(false);

  const { data: regles } = useSWR("/defi/regles", () => defiApi.regles().then((r) => r.data),
    { revalidateOnFocus: false });
  const { data: top } = useSWR(regles ? ["/defi/classement/top", 1, user?.user_id ?? ""] : null,
    () => defiApi.classement(undefined, 1).then((r) => r.data), { refreshInterval: 120_000 });

  const cle = regles ? `bt_defi_bandeau_${regles.mois}` : null;
  useEffect(() => {
    if (!cle) return;
    try {
      setMasque(localStorage.getItem(cle) === "1");
      const t = Number(localStorage.getItem(CLE_MASQUE_ESSAI) || 0);
      setEssaiMasque(Boolean(t) && Date.now() - t < MASQUE_ESSAI_MS);
    } catch {
      setMasque(false);
    }
  }, [cle]);

  if (loading || masque || !regles) return null;
  if (PAGES_SANS_BANDEAU.some((p) => pathname?.startsWith(p))) return null;
  if (peutDemarrerEssai(user) && !essaiMasque) return null;

  const fermer = () => {
    setMasque(true);
    try {
      if (cle) localStorage.setItem(cle, "1");
    } catch {
      /* masqué pour cette page seulement */
    }
  };
  const prix = regles.recompenses[0];
  const leader = top?.lignes[0];

  return (
    <div className={cn(DEFI_FOND, "border-b border-amber-900/10")}>
      <div className="mx-auto flex max-w-5xl items-center gap-3 px-4 py-2 text-[13px]">
        <DefiEmbleme taille={28} />
        <p className="min-w-0 flex-1 leading-snug text-slate-700">
          <span className="font-bold text-slate-900">Défi du mois</span>
          <span className="hidden sm:inline"> · {formatNombre(regles.capital_mensuel, 2)} points offerts pour parier sur les courses</span>
          {regles.essai
            ? <>{" "}· lancement le <span className="font-semibold text-amber-800">{dateLancement(regles.premier_mois)}</span>, essayez dès maintenant</>
            : <>{" "}· le 1<sup>er</sup> gagne <span className="font-semibold text-amber-800">{prix.jours} j {planLabel(prix.plan)}</span></>}
          {leader && <span className="hidden md:inline"> · en tête : <b className="text-slate-900">{leader.nom}</b> ({formatPts(leader.solde)})</span>}
        </p>
        <Link href="/defi" className="shrink-0 rounded-lg bg-gradient-to-b from-amber-500 to-amber-700 px-3 py-1.5 text-[12px] font-bold text-white shadow-[inset_0_1px_0_rgba(255,255,255,.35)]">
          {regles.essai ? "Essayer" : user ? "Jouer" : "Participer"}
        </Link>
        <button onClick={fermer} className="shrink-0 text-slate-400 hover:text-slate-800" aria-label="Masquer le bandeau du défi pour ce mois">
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
