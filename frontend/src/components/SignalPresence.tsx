"use client";

/**
 * Signal de présence — alimente le compteur « en ligne » de l'administration.
 *
 * Un signal par minute, seulement quand l'onglet est visible : un onglet oublié
 * en arrière-plan n'est pas une personne sur le site. Ce qui part : un
 * identifiant aléatoire gardé dans ce navigateur et le chemin de la page, sans
 * la query string. Rien d'autre, et tout expire côté serveur en 5 minutes.
 *
 * La console d'administration n'émet rien : l'exploitant qui la regarde ne doit
 * pas se compter lui-même comme visiteur du site.
 */

import { useEffect } from "react";
import { usePathname } from "next/navigation";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const CLE = "bt.visiteur";
const INTERVALLE_MS = 60_000;

function identifiant(): string | null {
  try {
    let v = window.localStorage.getItem(CLE);
    if (!v) {
      v = typeof crypto.randomUUID === "function"
        ? crypto.randomUUID()
        : Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");
      window.localStorage.setItem(CLE, v);
    }
    return v;
  } catch {
    return null; // stockage refusé : pas de signal plutôt qu'un visiteur neuf à chaque minute
  }
}

export default function SignalPresence() {
  const chemin = usePathname();

  useEffect(() => {
    if (!chemin || chemin.startsWith("/admin")) return;
    const v = identifiant();
    if (!v) return;

    const envoyer = () => {
      if (document.visibilityState !== "visible") return;
      fetch(`${API_URL}/api/v1/presence`, {
        method: "POST",
        credentials: "include",
        keepalive: true,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ v, p: chemin }),
      }).catch(() => { /* compteur best-effort : jamais d'erreur visible */ });
    };

    envoyer();
    const minuterie = window.setInterval(envoyer, INTERVALLE_MS);
    document.addEventListener("visibilitychange", envoyer);
    return () => {
      window.clearInterval(minuterie);
      document.removeEventListener("visibilitychange", envoyer);
    };
  }, [chemin]);

  return null;
}
