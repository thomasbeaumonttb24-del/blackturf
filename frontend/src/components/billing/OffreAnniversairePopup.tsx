"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Cake, Check, Copy, X } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { euros, useOffreAnniversaire } from "@/lib/offreAnniversaire";

/**
 * Fenêtre de l'offre anniversaire : montrée UNE fois par compte, aux seuls
 * comptes éligibles (inscrits avant l'offre, sans abonnement) — l'API ne
 * renvoie le code qu'à eux. Pas sur /tarifs, où le bandeau fait le même travail.
 */
const CLE_VUE = "bt_offre_anniv_vue_";

export function OffreAnniversairePopup() {
  const { user } = useAuth();
  const { offre } = useOffreAnniversaire(user);
  const pathname = usePathname();
  const [ouvert, setOuvert] = useState(false);
  const [copie, setCopie] = useState(false);

  useEffect(() => {
    if (!offre || !user || pathname?.startsWith("/tarifs")) return;
    try {
      if (localStorage.getItem(CLE_VUE + user.user_id)) return;
    } catch {
      /* stockage indisponible : on montre quand même */
    }
    setOuvert(true);
  }, [offre, user, pathname]);

  useEffect(() => {
    if (!ouvert) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && fermer();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (!ouvert || !offre || !user) return null;

  function fermer() {
    setOuvert(false);
    try {
      localStorage.setItem(CLE_VUE + user!.user_id, String(Date.now()));
    } catch {
      /* masquée pour cette page seulement */
    }
  }

  async function copier() {
    try {
      await navigator.clipboard.writeText(offre!.code);
      setCopie(true);
      setTimeout(() => setCopie(false), 2000);
    } catch {
      /* le code reste lisible à l'écran */
    }
  }

  return (
    <div
      className="fixed inset-0 z-[90] flex items-end justify-center bg-stone-950/60 p-4 backdrop-blur-sm sm:items-center"
      onClick={fermer}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="offre-anniv-titre"
        className="relative w-full max-w-md overflow-hidden rounded-3xl bg-gradient-to-br from-stone-900 via-stone-900 to-emerald-950 p-6 text-white shadow-2xl ring-2 ring-amber-400/70 sm:p-7"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="absolute -right-16 -top-16 h-48 w-48 rounded-full bg-amber-400/20 blur-3xl" aria-hidden />
        <button
          type="button"
          onClick={fermer}
          aria-label="Fermer"
          className="absolute right-3 top-3 rounded-full p-1.5 text-stone-400 hover:bg-white/10 hover:text-white"
        >
          <X className="h-5 w-5" />
        </button>

        <p className="relative inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-300">
          <Cake className="h-3.5 w-3.5" aria-hidden /> Offre exceptionnelle
        </p>
        <h2 id="offre-anniv-titre" className="relative mt-2 font-display text-2xl font-semibold leading-tight">
          BlackTurf fête son anniversaire, <span className="text-amber-300">et c&apos;est vous qu&apos;on remercie</span>.
        </h2>
        <p className="relative mt-3 text-sm leading-relaxed text-stone-300">
          Vous faites partie de nos premiers inscrits : −{offre.pourcent} % sur votre premier mois d&apos;abonnement mensuel,
          jusqu&apos;au {offre.fin_texte}.
        </p>

        <div className="relative mt-5 rounded-2xl border-2 border-dashed border-amber-400/70 bg-amber-300/10 p-4 text-center">
          <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-amber-200">Votre code</p>
          <div className="mt-1 flex items-center justify-center gap-2">
            <span className="font-mono text-2xl font-bold tracking-widest text-white">{offre.code}</span>
            <button
              type="button"
              onClick={copier}
              aria-label="Copier le code"
              className="rounded-lg p-1.5 text-amber-200 hover:bg-white/10"
            >
              {copie ? <Check className="h-4 w-4 text-emerald-300" /> : <Copy className="h-4 w-4" />}
            </button>
          </div>
        </div>

        <div className="relative mt-4 grid grid-cols-2 gap-3 text-center">
          {(["standard", "expert"] as const).map((plan) => (
            <div key={plan} className="rounded-2xl bg-white/[0.06] p-3 ring-1 ring-white/15">
              <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-stone-400">{plan === "expert" ? "Expert" : "Standard"}</p>
              <p className="mt-1 text-xs text-stone-400 line-through">{euros(offre.prix[plan].avant)}</p>
              <p className="font-display text-2xl font-semibold text-amber-300">{euros(offre.prix[plan].apres)}</p>
              <p className="text-[11px] text-stone-300">le 1<sup>er</sup> mois</p>
            </div>
          ))}
        </div>

        <Link
          href={`/tarifs?code=${encodeURIComponent(offre.code)}#formules`}
          onClick={fermer}
          className="relative mt-5 flex w-full items-center justify-center rounded-xl bg-gradient-to-b from-amber-300 to-amber-500 px-5 py-3 text-sm font-bold text-stone-900 shadow-[0_8px_20px_-8px_rgba(245,158,11,.8)] transition-transform hover:-translate-y-0.5"
        >
          J&apos;en profite
        </Link>
        <p className="relative mt-3 text-center text-[11px] leading-snug text-stone-400">
          Remise sur le premier paiement uniquement, puis prix habituel. Résiliable à tout moment.
        </p>
      </div>
    </div>
  );
}
