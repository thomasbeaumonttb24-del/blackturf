"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";

export function BoutonCopier({ texte }: { texte: string }) {
  const [copie, setCopie] = useState(false);

  async function copier() {
    try {
      await navigator.clipboard.writeText(texte);
      setCopie(true);
      setTimeout(() => setCopie(false), 2000);
    } catch {
      // Presse-papiers refusé (page non sécurisée, permission navigateur) : le texte
      // reste sélectionnable à la main juste au-dessus, on ne bloque rien.
      setCopie(false);
    }
  }

  return (
    <button
      type="button"
      onClick={copier}
      className="inline-flex items-center justify-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm font-semibold text-gray-900 transition-colors hover:bg-gray-50"
    >
      {copie ? (
        <>
          <Check className="h-4 w-4 text-emerald-700" aria-hidden="true" /> Légende copiée
        </>
      ) : (
        <>
          <Copy className="h-4 w-4" aria-hidden="true" /> Copier la légende
        </>
      )}
    </button>
  );
}
