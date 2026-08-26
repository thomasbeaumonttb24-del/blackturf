"use client";

import useSWR from "swr";
import { statsApi } from "@/lib/api";

// Bandeau défilant alimenté par des PARIS RÉELS déjà réglés (endpoint public
// `/stats/palmares-public` : pronostic figé avant le départ, réglé aux rapports PMU
// officiels).
//
// Avant le 2026-08-17, ce bandeau affichait six lignes écrites en dur — des chevaux
// inventés (« PALADIN NOIR », « BOLD FIGHTER »…) avec des pourcentages inventés, et
// même un « hippodrome » qui n'en est pas un (Paris-Turf est un journal). Le format
// « ticker live » donnait à ces lignes l'apparence de données réelles, malgré le
// badge « Exemple ». Remplacé par des résultats vérifiables : chaque ligne renvoie à
// une course réelle, contrôlable sur les rapports PMU.
//
// S'il n'y a rien à montrer, le bandeau ne s'affiche pas du tout — jamais de
// remplissage fictif.

interface TickerBet {
  code: string | null;
  hippodrome: string | null;
  type_pari: string | null;
  chevaux: number[];
  mise: number;
  gain: number;
  rapport: number | null;
}

function hippoCourt(s: string | null): string {
  if (!s) return "";
  return s.replace(/^HIPPODROME\s+(DE\s+|D'|DU\s+|DES\s+|DE LA\s+)?/i, "").toUpperCase();
}

const fetcher = () =>
  statsApi.palmaresPublic().then((r) => {
    const d = r.data as { gagnants?: TickerBet[]; top_gains?: TickerBet[] };
    // Mélange derniers gagnants + plus gros gains, dédoublonné : le bandeau reste
    // varié même quand peu de courses viennent d'être réglées.
    const seen = new Set<string>();
    return [...(d.gagnants ?? []), ...(d.top_gains ?? [])].filter((b) => {
      const k = `${b.code}-${b.type_pari}-${b.gain}`;
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    }).slice(0, 12);
  });

export function LiveTicker() {
  const { data } = useSWR<TickerBet[]>("ticker-palmares", fetcher, {
    refreshInterval: 120_000,
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });

  // Aucune donnée réelle → aucun bandeau (plutôt qu'un remplissage inventé).
  if (!data || data.length === 0) return null;

  const items = [...data, ...data]; // duplication = défilement continu sans saut

  return (
    <div className="relative border-y border-gray-200 bg-amber-50/60 py-2.5 overflow-hidden select-none">
      <span className="absolute left-0 top-0 bottom-0 z-10 flex items-center gap-1.5 px-3 bg-gray-900 text-white text-[9px] font-bold uppercase tracking-wider">
        <span className="live-dot inline-block h-1.5 w-1.5 rounded-full bg-emerald-400" />
        Gains réels
      </span>
      <div className="flex items-center gap-0 ticker-track pl-28">
        {items.map((b, i) => (
          <span key={i} className="flex items-center gap-3 px-6 shrink-0">
            <span className="text-amber-700 font-bold text-[10px] tracking-wider font-mono">{hippoCourt(b.hippodrome)}</span>
            {b.code && <span className="text-gray-600 text-[10px] font-mono">{b.code}</span>}
            <span className="text-gray-800 text-xs font-semibold">{b.type_pari}</span>
            {b.chevaux?.length > 0 && (
              <span className="text-gray-600 text-[11px] font-mono">
                {b.chevaux.length === 1 ? `N°${b.chevaux[0]}` : b.chevaux.join(" · ")}
              </span>
            )}
            <span className="text-xs text-gray-600 tabular-nums">
              mise <span className="font-mono">{b.mise.toFixed(0)}€</span>
            </span>
            <span className="text-xs font-bold text-emerald-700 font-mono tabular-nums">+{b.gain.toFixed(0)}€</span>
            {b.rapport != null && (
              <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700 border border-amber-200 font-bold font-mono">
                ×{b.rapport}
              </span>
            )}
            <span className="text-gray-300 text-lg mx-2">|</span>
          </span>
        ))}
      </div>
    </div>
  );
}
