"use client";

/**
 * Briques partagées de la supervision IA.
 *
 * Règle de cette page : rien n'est affiché qui ne soit mesuré. Une valeur
 * absente s'affiche « — », jamais 0 ; un segment sous le seuil de fiabilité
 * porte un badge « échantillon insuffisant » et son chiffre reste grisé.
 */

import * as React from "react";
import { Info } from "lucide-react";

// ─── formats ─────────────────────────────────────────────────
export const nf = new Intl.NumberFormat("fr-FR");

export function eur(v: number | null | undefined, digits = 0): string {
  if (v == null || !isFinite(v)) return "—";
  return `${v < 0 ? "−" : ""}${new Intl.NumberFormat("fr-FR", {
    minimumFractionDigits: digits, maximumFractionDigits: digits,
  }).format(Math.abs(v))} €`;
}

export function signedEur(v: number | null | undefined, digits = 0): string {
  if (v == null || !isFinite(v)) return "—";
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${new Intl.NumberFormat("fr-FR", {
    minimumFractionDigits: digits, maximumFractionDigits: digits,
  }).format(Math.abs(v))} €`;
}

export function pct(v: number | null | undefined, digits = 1): string {
  if (v == null || !isFinite(v)) return "—";
  return `${nfd(v, digits)} %`;
}

export function signedPct(v: number | null | undefined, digits = 1): string {
  if (v == null || !isFinite(v)) return "—";
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${nfd(Math.abs(v), digits)} %`;
}

function nfd(v: number, digits: number) {
  return new Intl.NumberFormat("fr-FR", {
    minimumFractionDigits: digits, maximumFractionDigits: digits,
  }).format(v);
}

export function num(v: number | null | undefined): string {
  return v == null || !isFinite(v) ? "—" : nf.format(v);
}

/** Couleur de polarité — vert au-dessus de zéro, rouge en dessous, gris à zéro. */
export function tone(v: number | null | undefined): string {
  if (v == null || !isFinite(v) || v === 0) return "text-gray-500";
  return v > 0 ? "text-emerald-600" : "text-red-600";
}

export const DIVERGING_POS = "#059669";
export const DIVERGING_NEG = "#EF4444";

// ─── verdict ─────────────────────────────────────────────────
const VERDICTS: Record<string, { label: string; cls: string; aide: string }> = {
  rentable: {
    label: "Rentable",
    cls: "bg-emerald-50 text-emerald-700 border-emerald-200",
    aide: "Assez de gagnants ET intervalle de confiance entièrement au-dessus de 0.",
  },
  perdant: {
    label: "Perdant",
    cls: "bg-red-50 text-red-700 border-red-200",
    aide: "Assez de gagnants ET intervalle de confiance entièrement en dessous de 0.",
  },
  neutre: {
    label: "Non tranché",
    cls: "bg-gray-100 text-gray-600 border-gray-200",
    aide: "Assez de gagnants, mais l'intervalle de confiance contient encore 0.",
  },
  insuffisant: {
    label: "Échantillon insuffisant",
    cls: "bg-amber-50 text-amber-700 border-amber-200",
    aide: "Moins de 150 paris gagnants : aucun verdict ne serait honnête à cette échelle.",
  },
};

export function VerdictBadge({ verdict, className = "" }: { verdict?: string; className?: string }) {
  const v = VERDICTS[verdict ?? "insuffisant"] ?? VERDICTS.insuffisant;
  return (
    <span
      title={v.aide}
      className={`inline-flex items-center whitespace-nowrap rounded-full border px-2 py-0.5 text-[10px] font-semibold ${v.cls} ${className}`}
    >
      {v.label}
    </span>
  );
}

// ─── tuiles ──────────────────────────────────────────────────
export function StatTile({
  label, value, sub, hint, valueClass = "text-gray-900", icon, footer,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  hint?: string;
  valueClass?: string;
  icon?: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-gray-100 bg-white p-3.5 shadow-sm sm:p-4">
      <div className="flex items-center gap-1.5">
        {icon}
        <span className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">
          {label}
        </span>
        {hint && (
          <span title={hint} className="cursor-help text-gray-300">
            <Info className="h-3 w-3" />
          </span>
        )}
      </div>
      <div className={`mt-1.5 text-xl font-bold tabular-nums sm:text-2xl ${valueClass}`}>
        {value}
      </div>
      {sub && <div className="mt-0.5 text-[11px] text-gray-500">{sub}</div>}
      {footer && <div className="mt-2">{footer}</div>}
    </div>
  );
}

export function Section({
  title, desc, right, children, className = "",
}: {
  title: React.ReactNode;
  desc?: React.ReactNode;
  right?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-xl border border-gray-100 bg-white shadow-sm ${className}`}>
      <header className="flex flex-wrap items-start justify-between gap-2 border-b border-gray-50 px-4 py-3">
        <div className="min-w-0">
          <h3 className="text-sm font-bold text-gray-900">{title}</h3>
          {desc && <p className="mt-0.5 text-[11px] leading-relaxed text-gray-500">{desc}</p>}
        </div>
        {right && <div className="shrink-0">{right}</div>}
      </header>
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-40 items-center justify-center rounded-lg border border-dashed border-gray-200 px-6 text-center text-xs text-gray-400">
      {children}
    </div>
  );
}

export function Note({ children }: { children: React.ReactNode }) {
  return (
    <p className="mt-3 flex items-start gap-1.5 text-[10px] leading-relaxed text-gray-400">
      <Info className="mt-px h-3 w-3 shrink-0" />
      <span>{children}</span>
    </p>
  );
}

/** Barre horizontale de polarité, pour lire un ROI sans lire le chiffre. */
export function PolarityBar({ value, max }: { value: number | null; max: number }) {
  if (value == null || !isFinite(value) || max <= 0) {
    return <div className="h-1.5 w-full rounded-full bg-gray-100" />;
  }
  const frac = Math.min(Math.abs(value) / max, 1) * 50;
  return (
    <div className="relative h-1.5 w-full rounded-full bg-gray-100">
      <div className="absolute inset-y-0 left-1/2 w-px bg-gray-300" />
      <div
        className="absolute inset-y-0 rounded-full"
        style={{
          left: value >= 0 ? "50%" : `${50 - frac}%`,
          width: `${frac}%`,
          background: value >= 0 ? DIVERGING_POS : DIVERGING_NEG,
        }}
      />
    </div>
  );
}
