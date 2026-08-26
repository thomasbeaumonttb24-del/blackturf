"use client";

import { useState } from "react";

// Démo FIDÈLE au vrai plan de mise du site (page course) : profils
// Prudent / Modéré / Risqué, niveaux Sécurité / Rendement / Coup, vrais types de
// paris PMU (Simple, Couplé, 2 sur 4, Tiercé, Trio) et EV global.
// Cotes/rapports d'EXEMPLE (le vrai calculateur utilise les rapports PMU réels).

type Pari = { type: string; chevaux: string; rapport: number; proba: number };
type Niveau = { key: "securite" | "rendement" | "coup"; label: string; emoji: string; pct: number; paris: Pari[] };
type Profil = { key: string; emoji: string; label: string; ev: number; popular?: boolean; niveaux: Niveau[] };

const PROFILS: Profil[] = [
  {
    key: "prudent", emoji: "🛡️", label: "Prudent", ev: 4,
    niveaux: [
      { key: "securite", label: "Sécurité", emoji: "🛡️", pct: 0.55, paris: [
        { type: "Simple Placé", chevaux: "N°2", rapport: 1.8, proba: 0.74 },
        { type: "Couplé Placé", chevaux: "2 · 4", rapport: 4.4, proba: 0.41 },
      ] },
      { key: "rendement", label: "Rendement", emoji: "📈", pct: 0.30, paris: [
        { type: "Couplé Placé", chevaux: "2 · 5", rapport: 6.0, proba: 0.30 },
      ] },
    ],
  },
  {
    key: "modere", emoji: "⚖️", label: "Modéré", ev: 9, popular: true,
    niveaux: [
      { key: "securite", label: "Sécurité", emoji: "🛡️", pct: 0.40, paris: [
        { type: "Couplé Placé", chevaux: "2 · 4", rapport: 4.4, proba: 0.41 },
      ] },
      { key: "rendement", label: "Rendement", emoji: "📈", pct: 0.35, paris: [
        { type: "2 sur 4", chevaux: "2 · 4 · 5 · 7", rapport: 14, proba: 0.22 },
      ] },
      { key: "coup", label: "Coup", emoji: "🎯", pct: 0.15, paris: [
        { type: "Couplé Gagnant", chevaux: "2 · 4", rapport: 28, proba: 0.09 },
      ] },
    ],
  },
  {
    key: "risque", emoji: "🔥", label: "Risqué", ev: 15,
    niveaux: [
      { key: "rendement", label: "Rendement", emoji: "📈", pct: 0.45, paris: [
        { type: "Couplé Gagnant", chevaux: "2 · 4", rapport: 28, proba: 0.09 },
      ] },
      { key: "coup", label: "Coup", emoji: "🎯", pct: 0.45, paris: [
        { type: "Tiercé", chevaux: "2 · 4 · 5", rapport: 90, proba: 0.03 },
        { type: "Trio", chevaux: "2 · 4 · 5", rapport: 22, proba: 0.09 },
      ] },
    ],
  },
];

const CHIPS = [5, 10, 20, 30];
const eur = (n: number) => n.toLocaleString("fr-FR", { maximumFractionDigits: 0 });
const NIV_CLASS: Record<string, string> = { securite: "plan-securite", rendement: "plan-rendement", coup: "plan-coup" };

export function CalculatorDemo() {
  const [mise, setMise] = useState(10);
  const [profilKey, setProfilKey] = useState("modere");
  const m = Number.isFinite(mise) && mise > 0 ? mise : 0;
  const profil = PROFILS.find((p) => p.key === profilKey) ?? PROFILS[1];

  const totalWeight = profil.niveaux.reduce((sum, niveau) => sum + niveau.pct, 0);

  return (
    <div className="mt-6 rounded-xl border border-amber-200/70 bg-white/70 p-4">
      {/* Profil de risque (comme le vrai outil) */}
      <div className="grid grid-cols-3 gap-1.5 mb-3">
        {PROFILS.map((p) => (
          <button key={p.key} type="button" onClick={() => setProfilKey(p.key)}
            className={`press rounded-lg px-2 py-1.5 text-[11px] font-semibold transition-colors border ${
              profilKey === p.key ? "border-brand-gold bg-brand-gold/10 text-brand-gold-dark" : "border-gray-200 text-gray-600 hover:border-brand-gold/40"
            }`}>
            {p.emoji} {p.label}
          </button>
        ))}
      </div>

      {/* Saisie de la mise */}
      <label htmlFor="demo-mise" className="text-[11px] uppercase tracking-wider text-gray-600 font-semibold">Votre mise</label>
      <div className="mt-1.5 flex items-center gap-2">
        <div className="relative flex-1">
          <input id="demo-mise" type="number" min={1} inputMode="numeric" value={mise || ""}
            onChange={(e) => setMise(parseInt(e.target.value, 10) || 0)}
            className="num-display w-full rounded-lg border border-gray-200 bg-white pl-3 pr-7 py-2 text-lg font-bold text-gray-900 outline-none transition-colors focus:border-brand-gold focus:ring-2 focus:ring-brand-gold/20"
            aria-label="Montant de votre mise en euros" />
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-600 font-semibold">€</span>
        </div>
        <div className="flex gap-1">
          {CHIPS.map((c) => (
            <button key={c} type="button" onClick={() => setMise(c)}
              className={`press rounded-md px-2.5 py-2 text-xs font-semibold transition-colors ${
                mise === c ? "bg-brand-gold text-brand-dark" : "bg-gray-100 text-gray-600 hover:bg-amber-50"
              }`}>{c}€</button>
          ))}
        </div>
      </div>

      {/* En-tête plan : montant + EV global */}
      <div className="mt-4 flex items-center justify-between">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-gray-600 font-semibold">Plan {profil.emoji} {profil.label}</div>
          <div className="num-display text-xl font-extrabold text-brand-gold-dark">{eur(m)}€</div>
        </div>
        <div className="text-right">
          <div className="text-[10px] uppercase tracking-wider text-gray-600 font-semibold">Espérance estimée</div>
          <div className="num-display text-lg font-extrabold text-emerald-700">+{profil.ev}%</div>
        </div>
      </div>

      {/* Niveaux + paris (structure du vrai plan) */}
      <div className="mt-3 space-y-2.5">
        {profil.niveaux.map((niv) => {
          // Les poids expriment seulement la répartition relative : 100 % de la mise
          // est toujours jouée, même si un profil comporte moins de niveaux.
          const part = totalWeight > 0 ? niv.pct / totalWeight : 0;
          const montantNiv = m * part;
          const stake = niv.paris.length ? montantNiv / niv.paris.length : 0;
          return (
            <div key={niv.key} className={`rounded-lg p-3 ${NIV_CLASS[niv.key] ?? ""}`}>
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs font-bold text-gray-800">{niv.emoji} {niv.label}</span>
                <span className="text-[11px] text-gray-600 num-display">{Math.round(part * 100)}% · {eur(montantNiv)}€</span>
              </div>
              <div className="space-y-1.5">
                {niv.paris.map((p, i) => (
                  <div key={i} className="flex items-center justify-between text-xs">
                    <div className="min-w-0 flex-1">
                      <span className="font-semibold text-gray-900">{p.type}</span>
                      <span className="text-gray-600 font-mono ml-1.5">{p.chevaux}</span>
                      <span className="text-gray-600 ml-1.5">~{Math.round(p.proba * 100)}%</span>
                    </div>
                    <div className="text-right flex-shrink-0">
                      <span className="font-mono text-gray-600">{eur(stake)}€</span>
                      <span className="text-emerald-700 font-bold num-display ml-2">→ ~{eur(stake * p.rapport)}€</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-3 text-xs">
        <div className="rounded-md bg-gray-50 px-3 py-2">
          <div className="text-gray-600">Mise totale jouée</div>
          <div className="num-display font-bold text-gray-900">{eur(m)}€</div>
        </div>
      </div>

      <p className="mt-2 text-[10px] text-gray-600">
        Exemple sur une course type. Le vrai calculateur utilise les rapports PMU réels et règle vos paris à l&apos;arrivée.
      </p>
    </div>
  );
}
