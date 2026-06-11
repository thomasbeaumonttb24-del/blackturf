"use client";

import { useState } from "react";

// Démo illustrative du calculateur de mise. Cotes d'EXEMPLE (clairement taguées) :
// le vrai calculateur (page course) utilise les cotes PMU réelles. Aucune donnée inventée
// présentée comme réelle — c'est une simulation pédagogique de la répartition.
const PLANS = [
  { key: "plan-securite",  label: "Sécurité",  pct: 0.5, cote: 1.8, color: "#059669" },
  { key: "plan-rendement", label: "Rendement", pct: 0.3, cote: 3.2, color: "#2563EB" },
  { key: "plan-coup",      label: "Coup",      pct: 0.2, cote: 8.0, color: "#D97706" },
];
const CHIPS = [20, 50, 100, 200];
const eur = (n: number) => n.toLocaleString("fr-FR", { maximumFractionDigits: 0 });
const cote = (n: number) => n.toLocaleString("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

export function CalculatorDemo() {
  const [mise, setMise] = useState(50);
  const m = Number.isFinite(mise) && mise > 0 ? mise : 0;

  const lines = PLANS.map((p) => {
    const stake = m * p.pct;
    return { ...p, stake, gainNet: stake * (p.cote - 1) };
  });
  const totalGain = lines.reduce((s, l) => s + l.gainNet, 0);

  return (
    <div className="mt-6 rounded-xl border border-amber-200/70 bg-white/70 p-4">
      {/* Saisie de la mise */}
      <label htmlFor="demo-mise" className="text-[11px] uppercase tracking-wider text-gray-400 font-semibold">
        Votre mise
      </label>
      <div className="mt-1.5 flex items-center gap-2">
        <div className="relative flex-1">
          <input
            id="demo-mise"
            type="number"
            min={1}
            inputMode="numeric"
            value={mise || ""}
            onChange={(e) => setMise(parseInt(e.target.value, 10) || 0)}
            className="num-display w-full rounded-lg border border-gray-200 bg-white pl-3 pr-7 py-2 text-lg font-bold text-gray-900 outline-none transition-colors focus:border-brand-gold focus:ring-2 focus:ring-brand-gold/20"
            aria-label="Montant de votre mise en euros"
          />
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 font-semibold">€</span>
        </div>
        <div className="flex gap-1">
          {CHIPS.map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => setMise(c)}
              className={`press rounded-md px-2.5 py-2 text-xs font-semibold transition-colors ${
                mise === c ? "bg-brand-gold text-white" : "bg-gray-100 text-gray-600 hover:bg-amber-50"
              }`}
            >
              {c}€
            </button>
          ))}
        </div>
      </div>

      {/* Plan de mise calculé en direct */}
      <div className="mt-3 space-y-2">
        {lines.map((l) => (
          <div key={l.key} className="flex items-center justify-between rounded-md bg-gray-50 py-2 pl-3 pr-3 text-xs">
            <div className="w-24">
              <div className="font-semibold text-gray-800">{l.label}</div>
              <div className="text-[10px] text-gray-400">cote {cote(l.cote)}</div>
            </div>
            <span className="text-gray-500">
              mise <span className="font-mono text-gray-700">{eur(l.stake)}€</span>
            </span>
            <span className="num-display font-bold tabular-nums text-gray-900">
              +{eur(l.gainNet)}€
            </span>
          </div>
        ))}
      </div>

      {/* Total */}
      <div className="mt-3 pt-3 border-t border-gray-100 flex items-center justify-between">
        <span className="text-xs text-gray-500">Gain net potentiel total</span>
        <span className="num-display text-base font-extrabold text-emerald-600">+{eur(totalGain)}€</span>
      </div>

      <p className="mt-2 text-[10px] text-gray-400">
        Simulation — cotes d&apos;exemple. Le vrai calculateur utilise les cotes PMU réelles de chaque course.
      </p>
    </div>
  );
}
