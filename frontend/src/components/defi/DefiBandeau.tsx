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
import { Medal, X } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { peutDemarrerEssai } from "@/lib/auth";
import { defiApi } from "@/lib/api";
import { formatPts, planLabel } from "@/components/defi/kit";

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
    <div className="border-b border-amber-200 bg-gradient-to-r from-amber-50 via-white to-amber-50">
      <div className="mx-auto flex max-w-5xl items-center gap-3 px-4 py-2 text-[13px] text-slate-800">
        <Medal className="h-4 w-4 shrink-0 text-amber-700" aria-hidden />
        <p className="min-w-0 flex-1 leading-snug">
          <span className="font-semibold">Défi du mois</span>
          <span className="hidden sm:inline"> : {regles.capital_mensuel.toLocaleString("fr-FR")} points offerts pour parier sur les courses,</span>
          {" "}le 1er gagne {prix.jours} j {planLabel(prix.plan)}.
          {leader && <span className="text-slate-600"> En tête : <b className="text-slate-800">{leader.nom}</b> · {formatPts(leader.solde)}</span>}
        </p>
        <Link href="/defi" className="shrink-0 rounded-lg bg-amber-800 px-3 py-1.5 text-[12px] font-bold text-white">
          {user ? "Jouer" : "Participer"}
        </Link>
        <button onClick={fermer} className="shrink-0 text-slate-500 hover:text-slate-800" aria-label="Masquer le bandeau du défi pour ce mois">
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
