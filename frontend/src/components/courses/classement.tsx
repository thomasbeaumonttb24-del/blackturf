"use client";

/**
 * Classement de l'algorithme — la table centrale de la fiche course.
 *
 * Règle de fond : **rien d'affiché ici n'est décoratif ou reconstitué côté
 * client**. Chaque colonne vient d'un champ renvoyé par l'API et disparaît quand
 * ce champ est absent :
 *
 *   rang, probabilités, intervalle, cote figée, cote juste  → /predictions
 *   cote marché (live si dispo, sinon cote figée du prono)  → /courses/{id}/cotes-live
 *   signaux (atout / réserve / vigilance)                   → /courses/{id}/analyse
 *   position réelle                                          → /courses/{id}/resultats
 *
 * Aucun repli « plausible » : pas de cote juste recalculée à la volée, pas de
 * signal générique quand l'analyse n'en donne pas.
 */

import { HelpCircle, Lock, TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";

export interface ClassementPrediction {
  prediction_id: string;
  numero: number;
  nom_cheval: string;
  proba_top1: number;
  proba_top3: number;
  proba_top1_low: number | null;
  proba_top1_high: number | null;
  rang_predit: number;
  confidence_score: number | null;
  cote_pmu: number | null;
  cote_juste: number | null;
  value_bet: { ev_max: number; niveau: number; meilleure_source: string } | null;
}

export interface ClassementSignal {
  label: string;
  detail: string;
  sens: "positif" | "negatif" | "neutre";
  score: number;
}

const pct = (x: number) => `${Math.round(x * 100)} %`;
const cote = (x: number) => x.toLocaleString("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

/** Retire les puces / emojis en tête de libellé renvoyés par l'analyse. */
const nettoie = (s: string) => s.replace(/^[^A-Za-zÀ-ÿ0-9]+/, "").trim();

const SENS = {
  positif: { fg: "text-emerald-700", bg: "bg-emerald-50", ring: "ring-emerald-100", fleche: "▲" },
  negatif: { fg: "text-rose-700", bg: "bg-rose-50", ring: "ring-rose-100", fleche: "▼" },
  neutre: { fg: "text-amber-800", bg: "bg-amber-50", ring: "ring-amber-100", fleche: "●" },
} as const;

function BadgeValeur({ ev, niveau }: { ev: number; niveau: number }) {
  return (
    <span
      title={`Espérance ${ev > 0 ? "+" : ""}${Math.round(ev * 100)} % — niveau ${niveau}/4 détecté par le modèle`}
      className="inline-flex shrink-0 items-center gap-1 rounded-md bg-emerald-50 px-1.5 py-0.5 text-[10px] font-bold tabular-nums text-emerald-700 ring-1 ring-emerald-200"
    >
      <TrendingUp className="h-3 w-3" aria-hidden="true" />
      {ev > 0 ? "+" : ""}{Math.round(ev * 100)} %
    </span>
  );
}

export function ClassementAlgo({
  predictions,
  signauxParNumero,
  positionsReelles,
  coteLive,
  nonPartants,
  onLegende,
}: {
  predictions: ClassementPrediction[];
  /** numero → signaux réellement produits par l'analyse (jamais inventés). */
  signauxParNumero: Record<number, ClassementSignal[]>;
  /** numero → position à l'arrivée, une fois la course courue. */
  positionsReelles?: Record<number, number>;
  /** numero → cote de marché la plus fraîche connue. */
  coteLive?: Record<number, number | null>;
  nonPartants?: Set<number>;
  onLegende: () => void;
}) {
  const lignes = [...predictions].sort((a, b) => a.rang_predit - b.rang_predit);
  const aCoteJuste = lignes.some((p) => p.cote_juste != null);

  return (
    <section className="overflow-hidden rounded-2xl border border-stone-200 bg-white">
      <header className="flex flex-wrap items-center gap-2 border-b border-stone-100 px-4 py-3.5 sm:px-5">
        <h3 className="font-display text-[15px] font-bold text-slate-900">Le classement de l&apos;algorithme</h3>
        <span className="text-[11px] text-muted-foreground">
          {lignes.length} chevaux notés · triés par probabilité de victoire
        </span>
        <button
          type="button"
          onClick={onLegende}
          className="ml-auto inline-flex items-center gap-1 rounded-full border border-stone-200 bg-white px-2.5 py-1 text-[11px] font-semibold text-slate-500 transition-colors hover:border-amber-300 hover:text-amber-800"
        >
          <HelpCircle className="h-3 w-3" aria-hidden="true" /> Comment lire
        </button>
      </header>

      {/* En-tête de colonnes — masqué sur mobile, où chaque ligne se lit en bloc */}
      <div
        className={cn(
          "hidden items-center gap-3 border-b border-stone-100 bg-stone-50/70 px-5 py-2 text-[10px] font-semibold uppercase tracking-wider text-stone-400 sm:grid",
          aCoteJuste ? "grid-cols-[28px_minmax(0,1fr)_64px_64px_120px_52px]" : "grid-cols-[28px_minmax(0,1fr)_64px_120px_52px]",
        )}
      >
        <span className="text-center">#</span>
        <span>Cheval</span>
        <span className="text-right">Cote</span>
        {aCoteJuste && <span className="text-right" title="Cote à partir de laquelle le pari devient rentable selon le modèle">Cote juste</span>}
        <span className="text-right">Probabilité de victoire</span>
        <span className="text-right" title="Probabilité de terminer dans les trois premiers">Top-3</span>
      </div>

      <ol className="max-h-[32rem] divide-y divide-stone-100 overflow-y-auto">
        {lignes.map((p) => {
          const fav = p.rang_predit === 1;
          const podium = p.rang_predit <= 3;
          const signaux = (signauxParNumero[p.numero] ?? []).filter((s) => nettoie(s.label)).slice(0, 3);
          const position = positionsReelles?.[p.numero];
          const marche = coteLive?.[p.numero] ?? p.cote_pmu;
          const absent = nonPartants?.has(p.numero);

          return (
            <li
              key={p.prediction_id}
              className={cn(
                "px-4 py-3 transition-colors hover:bg-stone-50/70 sm:px-5",
                fav && "bg-amber-50/40",
                absent && "opacity-55",
              )}
            >
              <div
                className={cn(
                  "grid items-center gap-3",
                  "grid-cols-[28px_minmax(0,1fr)_auto]",
                  aCoteJuste
                    ? "sm:grid-cols-[28px_minmax(0,1fr)_64px_64px_120px_52px]"
                    : "sm:grid-cols-[28px_minmax(0,1fr)_64px_120px_52px]",
                )}
              >
                {/* Rang du modèle */}
                <span
                  className={cn(
                    "flex h-7 w-7 items-center justify-center rounded-lg font-display text-[13px] font-bold tabular-nums ring-1",
                    fav ? "bg-amber-100 text-amber-900 ring-amber-200"
                      : podium ? "bg-stone-100 text-slate-700 ring-stone-200"
                      : "bg-white text-stone-400 ring-stone-200",
                  )}
                >
                  {p.rang_predit}
                </span>

                {/* Cheval + signaux réels */}
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="truncate text-[13.5px] font-semibold text-slate-900">
                      <span className="font-mono text-[11px] font-normal text-muted-foreground">N°{p.numero}</span>{" "}
                      {p.nom_cheval}
                    </span>
                    {p.value_bet && <BadgeValeur ev={p.value_bet.ev_max} niveau={p.value_bet.niveau} />}
                    {absent && (
                      <span className="rounded-md bg-stone-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-500">Non-partant</span>
                    )}
                    {position != null && (
                      <span
                        className={cn(
                          "rounded-md px-1.5 py-0.5 text-[10px] font-bold tabular-nums ring-1",
                          position === 1 ? "bg-amber-100 text-amber-900 ring-amber-200"
                            : position <= 3 ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
                            : "bg-stone-100 text-slate-500 ring-stone-200",
                        )}
                        title="Position réelle à l'arrivée"
                      >
                        {position}{position === 1 ? "er" : "e"} à l&apos;arrivée
                      </span>
                    )}
                  </div>

                  {signaux.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {signaux.map((s, i) => {
                        const st = SENS[s.sens] ?? SENS.neutre;
                        return (
                          <span
                            key={i}
                            title={s.detail || undefined}
                            className={cn("inline-flex cursor-help items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold ring-1", st.bg, st.fg, st.ring)}
                          >
                            <span aria-hidden="true">{st.fleche}</span> {nettoie(s.label)}
                          </span>
                        );
                      })}
                    </div>
                  )}

                  {/* Chiffres repliés sous le nom sur mobile */}
                  <div className="mt-1.5 flex items-center gap-3 text-[11px] tabular-nums text-muted-foreground sm:hidden">
                    {marche != null && <span>Cote {cote(marche)}</span>}
                    {p.cote_juste != null && <span>Juste {cote(p.cote_juste)}</span>}
                    <span>Top-3 {pct(p.proba_top3)}</span>
                  </div>
                </div>

                {/* Cote de marché */}
                <span className="hidden text-right font-display text-[13px] font-semibold tabular-nums text-slate-900 sm:block">
                  {marche != null ? cote(marche) : "—"}
                </span>

                {/* Cote juste du modèle */}
                {aCoteJuste && (
                  <span
                    className={cn(
                      "hidden text-right font-display text-[13px] tabular-nums sm:block",
                      p.value_bet && !absent ? "font-bold text-emerald-700" : "text-slate-500",
                    )}
                    title={
                      p.cote_juste != null && marche != null
                        ? marche > p.cote_juste
                          ? `Cote juste du modèle : ${cote(p.cote_juste)}. Le marché paie ${cote(marche)}${p.value_bet ? " — écart retenu comme pari de valeur." : ", écart jugé insuffisant par le modèle."}`
                          : `Cote juste du modèle : ${cote(p.cote_juste)}. Le marché paie moins (${cote(marche)}) : le prix ne couvre pas le risque.`
                        : undefined
                    }
                  >
                    {p.cote_juste != null ? cote(p.cote_juste) : "—"}
                  </span>
                )}

                {/* Probabilité de victoire : barre + valeur, sur la même colonne */}
                <div className="col-span-3 mt-2 sm:col-span-1 sm:mt-0">
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-stone-100">
                      <div
                        className={cn("h-full rounded-full", fav ? "bg-amber-500" : podium ? "bg-slate-400" : "bg-stone-300")}
                        style={{ width: `${Math.max(2, Math.min(100, p.proba_top1 * 100))}%` }}
                      />
                    </div>
                    <span className="w-10 shrink-0 text-right font-display text-[13px] font-bold tabular-nums text-slate-900">
                      {pct(p.proba_top1)}
                    </span>
                  </div>
                  {p.proba_top1_low != null && p.proba_top1_high != null && (
                    <p className="mt-0.5 text-right text-[10px] tabular-nums text-stone-400">
                      fourchette {Math.round(p.proba_top1_low * 100)}–{Math.round(p.proba_top1_high * 100)} %
                    </p>
                  )}
                </div>

                {/* Top-3 */}
                <span className="hidden text-right text-[13px] tabular-nums text-slate-600 sm:block">
                  {pct(p.proba_top3)}
                </span>
              </div>
            </li>
          );
        })}
      </ol>

      <footer className="border-t border-stone-100 bg-stone-50/50 px-4 py-3 sm:px-5">
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10.5px] text-muted-foreground">
          <span><span className="text-emerald-700">▲</span> atout</span>
          <span><span className="text-rose-700">▼</span> réserve</span>
          <span><span className="text-amber-700">●</span> à surveiller</span>
          {aCoteJuste && <span><span className="font-semibold text-emerald-700">cote juste en vert</span> : pari de valeur retenu par le modèle</span>}
        </div>
        <p className="mt-1.5 text-[10.5px] leading-4 text-muted-foreground">
          Probabilités issues du modèle à 80+ critères (forme, ELO, association jockey/entraîneur, distance,
          terrain, marché). Aide à la décision — aucune garantie de gain.
        </p>
      </footer>
    </section>
  );
}

/** État verrouillé, affiché à la place de la table selon le plan de l'abonné. */
export function ClassementVerrouille({ titre, texte, action }: { titre: string; texte: string; action: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-stone-200 bg-white p-6 text-center">
      <span className="mx-auto mb-3 inline-flex h-10 w-10 items-center justify-center rounded-xl bg-amber-50 text-amber-800 ring-1 ring-amber-200">
        <Lock className="h-4 w-4" aria-hidden="true" />
      </span>
      <h3 className="font-display text-[15px] font-bold text-slate-900">{titre}</h3>
      <p className="mx-auto mt-1.5 max-w-md text-[13px] leading-6 text-muted-foreground">{texte}</p>
      <div className="mt-4">{action}</div>
    </section>
  );
}
