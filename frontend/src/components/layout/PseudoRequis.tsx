"use client";

/**
 * Choix du pseudo, demandé au moment de parier au Défi du mois.
 *
 * Le pseudo est demandé à l'inscription depuis le 2026-09-25. Restent sans
 * pseudo : les comptes créés avant, et ceux ouverts via Google (le formulaire
 * d'inscription n'est pas passé par là). C'est lui qui s'affiche au classement :
 * le serveur refuse un pari sans pseudo.
 *
 * Décision du 2026-09-28 : pas de fenêtre bloquante sur tout le site (elle
 * empêchait un abonné de consulter ses pronostics). Le formulaire s'affiche à la
 * place du bulletin de pari, là seulement où le pseudo est indispensable.
 */

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { MedailleSvg } from "@/components/defi/illustrations";
import { useAuth } from "@/hooks/useAuth";
import { authApi } from "@/lib/api";
import { PSEUDO_AIDE, PSEUDO_RE } from "@/lib/pseudo";

export function PseudoRequis({ className }: { className?: string }) {
  const { refreshUser } = useAuth();
  const [valeur, setValeur] = useState("");
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);

  async function valider(e: React.FormEvent) {
    e.preventDefault();
    const pseudo = valeur.trim();
    if (!PSEUDO_RE.test(pseudo)) {
      setErreur(PSEUDO_AIDE);
      return;
    }
    setEnvoi(true);
    setErreur(null);
    try {
      await authApi.updateMe({ pseudo });
      await refreshUser();
    } catch (err) {
      const d = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      setErreur(typeof d === "string" ? d : "Enregistrement impossible, réessayez.");
    } finally {
      setEnvoi(false);
    }
  }

  return (
    <form onSubmit={valider} aria-labelledby="pseudo-titre" className={className}>
      <div className="flex items-center gap-3">
        <MedailleSvg taille={40} />
        <div>
          <h3 id="pseudo-titre" className="font-display text-[16px] font-bold text-slate-900">Choisissez votre pseudo pour jouer</h3>
          <p className="text-[12.5px] leading-snug text-slate-600">
            C&apos;est votre nom au classement. Votre prénom et votre e-mail ne sont jamais affichés.
          </p>
        </div>
      </div>

      <label htmlFor="pseudo-requis" className="mt-4 block text-[13px] font-semibold text-slate-800">Pseudo</label>
      <input
        id="pseudo-requis"
        value={valeur}
        onChange={(e) => { setValeur(e.target.value); setErreur(null); }}
        maxLength={20}
        autoComplete="nickname"
        placeholder="Turfiste75"
        aria-invalid={!!erreur}
        aria-describedby="pseudo-aide"
        className="mt-1.5 h-12 w-full rounded-xl border border-stone-300 bg-white px-3.5 text-base outline-none focus:border-amber-600 focus:ring-2 focus:ring-amber-200"
      />
      <p id="pseudo-aide" className={erreur ? "mt-1.5 text-[12.5px] font-medium text-rose-700" : "mt-1.5 text-[12px] text-slate-500"}>
        {erreur ?? PSEUDO_AIDE}
      </p>

      <button type="submit" disabled={envoi || valeur.trim().length < 3}
        className="mt-4 inline-flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-amber-800 text-[14px] font-bold text-white transition-opacity disabled:opacity-50">
        {envoi && <Loader2 className="h-4 w-4 animate-spin" />} Valider mon pseudo
      </button>
    </form>
  );
}
