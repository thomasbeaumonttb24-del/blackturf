"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Trophy, X } from "lucide-react";

// Anciennement une capture d'e-mail qui ENVOYAIT le classement complet sans
// compte (fermé le 2026-09-30, cf. backend/api/routes/pronostic_email.py) :
// le popup oriente désormais vers le compte gratuit — 1 classement complet par
// jour, révélé sur la fiche (services/quota_classement.py).

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

// Un seul déclenchement de popup par jour, tous hippodromes confondus : sans ce
// verrou, la clef par course laissait le popup ressortir sur CHAQUE nouvelle
// fiche ouverte le même jour (vu/fermé sur la course A n'empêchait rien sur la
// course B). La date est celle du fuseau local du visiteur — un « jour » au
// sens calendaire vécu, pas un TTL glissant de 24 h.
const CLE_JOUR = "bt_pronostic_popup_jour";

function aujourdHui(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function memoriser(courseId: string) {
  try {
    localStorage.setItem(clefStockage(courseId), String(Date.now()));
    localStorage.setItem(CLE_JOUR, aujourdHui());
  } catch {
    // pas grave : au pire le popup peut réapparaître à la prochaine visite
  }
}

/**
 * Popup de capture e-mail sur la fiche course, inspiré de Boturfers.fr : propose
 * d'envoyer le pronostic IA de CETTE course précise (pas la newsletter hebdo
 * générique). Non bloquant — fermable à tout moment, ne réapparaît pas une fois
 * vu/fermé/rempli pour cette course (`localStorage`, jamais re-sollicité après un
 * premier passage, y compris entre deux sessions) NI pour une autre course déjà
 * proposée le même jour (verrou quotidien global, cf. `CLE_JOUR`).
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
  const declenche = useRef(false);

  useEffect(() => {
    if (!actif) return;
    let deja = false;
    try {
      deja =
        Boolean(localStorage.getItem(clefStockage(courseId))) ||
        localStorage.getItem(CLE_JOUR) === aujourdHui();
    } catch {
      // stockage indisponible (navigation privée…) : on retombe sur le déclenchement normal
    }
    if (deja) return;

    const declencher = () => {
      if (declenche.current) return;
      declenche.current = true;
      // Verrou posé dès l'AFFICHAGE, pas seulement à la fermeture : un visiteur qui
      // voyait le popup puis passait à une autre course sans le fermer (lien,
      // retour arrière) le revoyait sur chaque fiche ouverte dans la journée.
      memoriser(courseId);
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

  function fermer() {
    memoriser(courseId);
    setVisible(false);
  }

  if (!visible) return null;

  const lienInscription = `/inscription?suite=${encodeURIComponent(`/courses/${courseId}`)}`;

  return (
    <div
      className="fixed z-[55] w-[calc(100%-24px)] sm:w-[360px]"
      style={{ left: 12, right: 12, bottom: 12, margin: "0 auto", maxWidth: 360, animation: "cxFadeUp .25s ease both" }}
      role="dialog"
      aria-label="Pronostic complet gratuit avec un compte"
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
            <Trophy className="h-3.5 w-3.5" aria-hidden="true" />
          </span>
          <div className="min-w-0 flex-1">
            <p style={{ margin: 0, fontSize: 14, fontWeight: 700, color: CX.ink2 }}>
              Le pronostic complet de cette course, gratuitement ?
            </p>
            <p style={{ margin: "3px 0 0", fontSize: 12.5, color: CX.gray500, lineHeight: 1.5 }}>
              Créez votre compte gratuit : chaque jour, vous révélez le classement complet de
              l&apos;algorithme sur la course de votre choix{hippodromeNom ? `, celle de ${hippodromeNom} comprise` : ""}.
            </p>
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
          <Link
            href={lienInscription}
            onClick={() => memoriser(courseId)}
            className="flex w-full items-center justify-center rounded-lg px-3.5 py-2.5 text-sm font-bold text-white transition-colors"
            style={{ background: CX.ink2 }}
          >
            Créer mon compte gratuit
          </Link>
          <p style={{ margin: "8px 0 0", fontSize: 11, lineHeight: 1.5, color: CX.gray500, textAlign: "center" }}>
            30 secondes, sans carte bancaire. 1 classement complet par jour.
          </p>
        </div>
      </div>
    </div>
  );
}
