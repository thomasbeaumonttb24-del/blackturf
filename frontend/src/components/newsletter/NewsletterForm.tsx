"use client";

import { useState } from "react";
import { Loader2, Check, Mail } from "lucide-react";
import { api } from "@/lib/api";

/**
 * Cette formulation doit rester IDENTIQUE, mot pour mot, à la constante `CONSENTEMENT`
 * de `backend/api/routes/newsletter.py` : c'est elle qui est enregistrée avec
 * l'inscription. Prouver un consentement suppose de pouvoir dire à QUOI la personne a
 * consenti, pas seulement qu'elle a validé un formulaire. Modifier l'un sans l'autre
 * rendrait la preuve fausse.
 */
export const CONSENTEMENT =
  "Je souhaite recevoir la lettre hebdomadaire BlackTurf : le bilan chiffré de la " +
  "semaine, gains comme pertes. Un envoi par semaine, désinscription en un clic.";

export function NewsletterForm({
  source,
  variante = "clair",
  titre = "Le bilan de la semaine, chiffres réels",
  accroche = "Chaque lundi : ce que le modèle a bien vu, ce qu'il a raté, et le résultat — gains comme pertes. Un seul envoi par semaine.",
}: {
  /** Page d'origine : dit quel emplacement convertit, et lesquels ne servent à rien. */
  source: string;
  variante?: "clair" | "sombre";
  titre?: string;
  accroche?: string;
}) {
  const [email, setEmail] = useState("");
  const [etat, setEtat] = useState<"repos" | "envoi" | "envoye" | "erreur">("repos");

  const sombre = variante === "sombre";

  async function soumettre(e: React.FormEvent) {
    e.preventDefault();
    if (etat === "envoi") return;
    setEtat("envoi");
    try {
      await api.post("/newsletter/inscription", { email: email.trim(), source });
      // L'API répond la même chose que l'adresse soit connue ou non — c'est
      // volontaire (pas d'énumération d'adresses). L'écran dit donc « vérifiez votre
      // boîte », jamais « vous êtes inscrit ».
      setEtat("envoye");
    } catch {
      setEtat("erreur");
    }
  }

  if (etat === "envoye") {
    return (
      <div
        className={`rounded-2xl border p-6 ${
          sombre ? "border-white/15 bg-white/5" : "border-emerald-200 bg-emerald-50"
        }`}
      >
        <div className="flex items-start gap-3">
          <span
            className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${
              sombre ? "bg-emerald-400/20 text-emerald-300" : "bg-emerald-600 text-white"
            }`}
          >
            <Check className="h-3.5 w-3.5" aria-hidden="true" />
          </span>
          <div>
            <p className={`font-semibold ${sombre ? "text-white" : "text-emerald-900"}`}>
              Vérifiez votre boîte mail
            </p>
            <p className={`mt-1 text-sm ${sombre ? "text-white/70" : "text-emerald-800"}`}>
              Un lien de confirmation vient de partir. Tant que vous n&apos;avez pas cliqué
              dessus, aucune lettre ne vous sera envoyée.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`rounded-2xl border p-6 ${
        sombre ? "border-white/15 bg-white/5" : "border-amber-200 bg-gradient-to-br from-amber-50 to-white"
      }`}
    >
      <div className="flex items-center gap-2">
        <Mail
          className={`h-4 w-4 ${sombre ? "text-amber-300" : "text-brand-gold-deep"}`}
          aria-hidden="true"
        />
        <h2
          className={`font-display text-lg font-bold ${sombre ? "text-white" : "text-gray-900"}`}
        >
          {titre}
        </h2>
      </div>
      <p className={`mt-2 text-sm leading-relaxed ${sombre ? "text-white/70" : "text-gray-600"}`}>
        {accroche}
      </p>

      <form onSubmit={soumettre} className="mt-4 flex flex-col gap-2 sm:flex-row">
        <label htmlFor={`newsletter-email-${source}`} className="sr-only">
          Votre adresse e-mail
        </label>
        <input
          id={`newsletter-email-${source}`}
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="votre@email.fr"
          className={`w-full rounded-lg border px-3.5 py-2.5 text-sm outline-none transition-colors focus:ring-2 ${
            sombre
              ? "border-white/20 bg-white/10 text-white placeholder:text-white/40 focus:ring-amber-400/50"
              : "border-gray-300 bg-white text-gray-900 placeholder:text-gray-400 focus:ring-amber-400"
          }`}
        />
        <button
          type="submit"
          disabled={etat === "envoi"}
          className={`inline-flex shrink-0 items-center justify-center gap-2 rounded-lg px-5 py-2.5 text-sm font-bold transition-colors disabled:opacity-60 ${
            sombre
              ? "bg-amber-400 text-gray-900 hover:bg-amber-300"
              : "bg-gray-900 text-white hover:bg-gray-800"
          }`}
        >
          {etat === "envoi" ? <Loader2 className="h-4 w-4 animate-spin" /> : "Je m'inscris"}
        </button>
      </form>

      {etat === "erreur" && (
        <p className={`mt-2 text-sm ${sombre ? "text-rose-300" : "text-red-600"}`}>
          L&apos;envoi n&apos;a pas abouti. Réessayez dans un instant.
        </p>
      )}

      <p className={`mt-3 text-xs leading-relaxed ${sombre ? "text-white/50" : "text-gray-500"}`}>
        {CONSENTEMENT}
      </p>
    </div>
  );
}
