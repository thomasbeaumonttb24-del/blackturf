"use client";

/**
 * Choix du pseudo, obligatoire pour tout compte connecté qui n'en a pas.
 *
 * Le pseudo est demandé à l'inscription depuis le 2026-09-25. Restent sans
 * pseudo : les comptes créés avant, et ceux ouverts via Google (le formulaire
 * d'inscription n'est pas passé par là). C'est lui qui s'affiche au classement
 * du Défi du mois : sans lui, le joueur apparaîtrait sous un alias anonyme et ne
 * pourrait pas jouer (le serveur refuse un pari sans pseudo).
 *
 * Fenêtre bloquante, sans croix : la seule autre issue est la déconnexion.
 */

import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { MedailleSvg } from "@/components/defi/illustrations";
import { useAuth } from "@/hooks/useAuth";
import { authApi } from "@/lib/api";
import { PSEUDO_AIDE, PSEUDO_RE } from "@/lib/pseudo";

export function PseudoRequis() {
  const { user, loading, refreshUser, logout } = useAuth();
  const [valeur, setValeur] = useState("");
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);
  const champ = useRef<HTMLInputElement>(null);
  const ouvert = !loading && !!user && !user.pseudo;

  useEffect(() => {
    if (!ouvert) return;
    champ.current?.focus();
    const avant = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = avant; };
  }, [ouvert]);

  if (!ouvert) return null;

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
    <div className="fixed inset-0 z-[90] flex items-end justify-center bg-slate-950/60 p-0 backdrop-blur-sm sm:items-center sm:p-4"
      role="dialog" aria-modal="true" aria-labelledby="pseudo-titre">
      <form onSubmit={valider}
        className="w-full max-w-md rounded-t-3xl bg-white p-6 shadow-2xl ring-1 ring-black/5 sm:rounded-3xl sm:p-7">
        <MedailleSvg taille={48} />
        <h2 id="pseudo-titre" className="mt-4 font-display text-[20px] font-bold text-slate-900">Choisissez votre pseudo</h2>
        <p className="mt-1.5 text-[13.5px] leading-relaxed text-slate-600">
          C&apos;est votre nom public au classement du <b className="text-slate-800">Défi du mois</b> et dans la Communauté.
          Votre prénom et votre adresse e-mail ne sont jamais affichés.
        </p>

        <label htmlFor="pseudo-requis" className="mt-5 block text-[13px] font-semibold text-slate-800">Pseudo</label>
        <input
          ref={champ}
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
          className="mt-5 inline-flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-amber-800 text-[14px] font-bold text-white transition-opacity disabled:opacity-50">
          {envoi && <Loader2 className="h-4 w-4 animate-spin" />} Valider mon pseudo
        </button>
        <button type="button" onClick={logout}
          className="mt-2 h-10 w-full text-[12.5px] font-medium text-slate-500 hover:text-slate-800">
          Se déconnecter
        </button>
      </form>
    </div>
  );
}
