"use client";

import { useEffect, useRef, useState } from "react";
import { Mail, X, Loader2, Check } from "lucide-react";
import { pronosticEmailApi } from "@/lib/api";

/**
 * Doit rester IDENTIQUE, mot pour mot, à `CONSENTEMENT` dans
 * `backend/api/routes/pronostic_email.py` : c'est cette formulation qui est
 * enregistrée avec la demande. Modifier l'un sans l'autre rendrait le
 * consentement affiché différent de celui prouvable côté serveur.
 */
const CONSENTEMENT =
  "Je souhaite recevoir par e-mail le pronostic IA de cette course. Envoi unique, " +
  "pas d'abonnement, désinscription en un clic.";

const CX = {
  gold: "#B45309", goldDeep: "#92400E", goldBg: "#FEF6E7", goldBd: "#F5DCA8",
  ink2: "#1F2937", gray500: "#4B5563", surf1: "#FFFFFF", surf5: "#F1EEE6", bd2: "#EEE9DE",
};

// Ni un mur immédiat (le visiteur n'a encore rien vu), ni un rappel trop tardif :
// le popup sort au premier des deux signaux — un vrai temps de lecture, ou un
// vrai geste de scroll dans le contenu.
const DELAI_MS = 18_000;
const SEUIL_SCROLL = 0.35; // 35% de la hauteur de page parcourue

function clefStockage(courseId: string): string {
  return `bt_pronostic_popup_${courseId}`;
}

/**
 * Popup de capture e-mail sur la fiche course, inspiré de Boturfers.fr : propose
 * d'envoyer le pronostic IA de CETTE course précise (pas la newsletter hebdo
 * générique). Non bloquant — fermable à tout moment, ne réapparaît pas une fois
 * vu/fermé/rempli pour cette course (`localStorage`, jamais re-sollicité après un
 * premier passage, y compris entre deux sessions).
 */
export function PronosticEmailPopup({
  courseId,
  hippodromeNom,
  actif = true,
}: {
  courseId: string;
  hippodromeNom?: string;
  /** false = ne jamais déclencher (compte connecté, course déjà courue…). */
  actif?: boolean;
}) {
  const [visible, setVisible] = useState(false);
  const [email, setEmail] = useState("");
  const [etat, setEtat] = useState<"repos" | "envoi" | "envoye" | "indisponible" | "erreur">("repos");
  const declenche = useRef(false);

  useEffect(() => {
    if (!actif) return;
    let deja = false;
    try {
      deja = Boolean(localStorage.getItem(clefStockage(courseId)));
    } catch {
      // stockage indisponible (navigation privée…) : on retombe sur le déclenchement normal
    }
    if (deja) return;

    const declencher = () => {
      if (declenche.current) return;
      declenche.current = true;
      setVisible(true);
    };

    const timer = window.setTimeout(declencher, DELAI_MS);

    const onScroll = () => {
      const h = document.documentElement;
      const parcouru = h.scrollHeight > h.clientHeight
        ? h.scrollTop / (h.scrollHeight - h.clientHeight)
        : 0;
      if (parcouru >= SEUIL_SCROLL) declencher();
    };
    window.addEventListener("scroll", onScroll, { passive: true });

    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("scroll", onScroll);
    };
  }, [courseId, actif]);

  function memoriser() {
    try {
      localStorage.setItem(clefStockage(courseId), String(Date.now()));
    } catch {
      // pas grave : au pire le popup peut réapparaître à la prochaine visite
    }
  }

  function fermer() {
    memoriser();
    setVisible(false);
  }

  async function soumettre(e: React.FormEvent) {
    e.preventDefault();
    if (etat === "envoi") return;
    setEtat("envoi");
    try {
      const res = await pronosticEmailApi.envoyer(courseId, email.trim(), "fiche_course_popup");
      memoriser();
      setEtat(res.data.ok ? "envoye" : "indisponible");
    } catch {
      setEtat("erreur");
    }
  }

  if (!visible) return null;

  return (
    <div
      className="fixed z-[55] w-[calc(100%-24px)] sm:w-[360px]"
      style={{ left: 12, right: 12, bottom: 12, margin: "0 auto", maxWidth: 360, animation: "cxFadeUp .25s ease both" }}
      role="dialog"
      aria-label="Pronostic gratuit pour cette course"
    >
      <div
        className="rounded-2xl overflow-hidden"
        style={{ background: CX.surf1, border: `1px solid ${CX.bd2}`, boxShadow: "0 20px 45px -15px rgba(0,0,0,.28)" }}
      >
        <div className="flex items-start gap-2.5 px-4 pt-4">
          <span
            className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full"
            style={{ background: CX.goldBg, color: CX.goldDeep }}
          >
            <Mail className="h-3.5 w-3.5" aria-hidden="true" />
          </span>
          <div className="min-w-0 flex-1">
            <p style={{ margin: 0, fontSize: 14, fontWeight: 700, color: CX.ink2 }}>
              Un pronostic gratuit pour cette course, ça vous tente ?
            </p>
            {etat !== "envoye" && etat !== "indisponible" && (
              <p style={{ margin: "3px 0 0", fontSize: 12.5, color: CX.gray500, lineHeight: 1.5 }}>
                On vous envoie le classement IA{hippodromeNom ? ` de ${hippodromeNom}` : ""} par e-mail — pour
                cette course précisément, pas une lettre hebdo.
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={fermer}
            aria-label="Fermer"
            className="shrink-0 inline-flex items-center justify-center"
            style={{ width: 26, height: 26, borderRadius: 999, border: "none", background: CX.surf5, color: CX.gray500, cursor: "pointer" }}
          >
            <X className="h-[13px] w-[13px]" />
          </button>
        </div>

        <div className="px-4 pb-4 pt-3">
          {etat === "envoye" && (
            <div className="flex items-start gap-2">
              <span
                className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full"
                style={{ background: "#ECFDF5", color: "#059669" }}
              >
                <Check className="h-3 w-3" aria-hidden="true" />
              </span>
              <p style={{ margin: 0, fontSize: 13, color: CX.ink2 }}>
                Envoyé ! Regardez votre boîte mail.
              </p>
            </div>
          )}

          {etat === "indisponible" && (
            <p style={{ margin: 0, fontSize: 13, color: CX.gray500 }}>
              Le pronostic de cette course n&apos;est pas encore prêt — réessayez un peu avant le départ.
            </p>
          )}

          {(etat === "repos" || etat === "envoi" || etat === "erreur") && (
            <form onSubmit={soumettre} className="flex flex-col gap-2">
              <label htmlFor={`pronostic-email-${courseId}`} className="sr-only">
                Votre adresse e-mail
              </label>
              <div className="flex gap-2">
                <input
                  id={`pronostic-email-${courseId}`}
                  type="email"
                  required
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="votre@email.fr"
                  className="w-full rounded-lg border px-3 py-2 text-sm outline-none transition-colors focus:ring-2"
                  style={{ borderColor: "#D1D5DB", color: CX.ink2 }}
                />
                <button
                  type="submit"
                  disabled={etat === "envoi"}
                  className="shrink-0 inline-flex items-center justify-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-bold text-white transition-colors disabled:opacity-60"
                  style={{ background: CX.ink2 }}
                >
                  {etat === "envoi" ? <Loader2 className="h-4 w-4 animate-spin" /> : "Recevoir"}
                </button>
              </div>
              {etat === "erreur" && (
                <p style={{ margin: 0, fontSize: 12.5, color: "#B91C1C" }}>
                  L&apos;envoi n&apos;a pas abouti. Réessayez dans un instant.
                </p>
              )}
              <p style={{ margin: 0, fontSize: 11, lineHeight: 1.5, color: CX.gray500 }}>{CONSENTEMENT}</p>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
