"use client";

import { useEffect, useRef } from "react";
import { AVIS } from "@/lib/social";

const SCRIPT = "https://widget.trustpilot.com/bootstrap/v5/tp.widget.bootstrap.min.js";

declare global {
  interface Window {
    Trustpilot?: { loadFromElement: (el: HTMLElement, force?: boolean) => void };
  }
}

/**
 * Widget officiel Trustpilot « Review Collector » (code TrustBox généré dans
 * Trustpilot Business). Le script de Trustpilot remplace le lien par son bouton
 * « Évaluez-nous sur ★ Trustpilot ». Script bloqué (bloqueur de pub, CSP) : le lien
 * reste, et mène au même formulaire.
 *
 * Next ne recharge pas la page entre deux rubriques : le script n'est chargé qu'une
 * fois, et `loadFromElement` redessine le widget à chaque montage du pied de page.
 */
export function TrustpilotAvis() {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.Trustpilot) {
      window.Trustpilot.loadFromElement(el, true);
      return;
    }
    if (document.querySelector(`script[src="${SCRIPT}"]`)) return;
    const s = document.createElement("script");
    s.src = SCRIPT;
    s.async = true;
    document.head.appendChild(s);
  }, []);

  const tp = AVIS.trustpilot;
  return (
    <div
      ref={ref}
      className="trustpilot-widget w-[260px]"
      data-locale="fr-FR"
      data-template-id={tp.templateId}
      data-businessunit-id={tp.businessUnitId}
      data-style-height="52px"
      data-style-width="100%"
      data-token={tp.token}
    >
      <a
        href={tp.ecrire}
        target="_blank"
        rel="noopener"
        className="inline-flex h-[52px] w-full items-center justify-center gap-2 rounded-lg border border-[#00B67A] bg-white text-sm text-[#191919]"
      >
        Évaluez-nous sur
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/img/logos/trustpilot.svg" alt="Trustpilot" className="h-5 w-auto" />
      </a>
    </div>
  );
}
