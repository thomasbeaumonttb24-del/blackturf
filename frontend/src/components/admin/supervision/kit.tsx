"use client";

/**
 * Briques de la supervision IA.
 *
 * Ce fichier ne définit plus sa propre apparence : il ADAPTE le kit commun de
 * l'administration (`components/admin/ui.tsx`) aux noms qu'emploient les six
 * onglets. Avant la refonte il peignait ses propres surfaces — `bg-white`,
 * `text-gray-900`, `border-gray-100` — pendant que le back-office peignait les
 * siennes avec les jetons du thème. Deux pages du même outil, deux blancs
 * légèrement différents, deux gris de texte, deux échelles de titres.
 *
 * Règle de la page, inchangée : rien n'est affiché qui ne soit mesuré. Une
 * valeur absente s'affiche « — », jamais 0 ; un segment sous le seuil de
 * fiabilité porte un badge « échantillon insuffisant » et son chiffre reste
 * grisé.
 */

import * as React from "react";
import { cn } from "@/lib/utils";
import {
  BarrePolarite, Note as NoteUI, Panneau, Tuile, Vide,
  eur, nf, num, pct, signedEur, signedPct, tone,
} from "../ui";

export { eur, nf, num, pct, signedEur, signedPct, tone };
export { DIVERGING_NEG, DIVERGING_POS } from "../ui";

// ─── verdict ─────────────────────────────────────────────────
const VERDICTS: Record<string, { label: string; cls: string; aide: string }> = {
  rentable: {
    label: "Rentable",
    cls: "border-emerald-200 bg-emerald-50 text-emerald-700",
    aide: "Assez de gagnants ET intervalle de confiance entièrement au-dessus de 0.",
  },
  perdant: {
    label: "Perdant",
    cls: "border-red-200 bg-red-50 text-red-700",
    aide: "Assez de gagnants ET intervalle de confiance entièrement en dessous de 0.",
  },
  neutre: {
    label: "Non tranché",
    cls: "border-border bg-muted text-muted-foreground",
    aide: "Assez de gagnants, mais l'intervalle de confiance contient encore 0.",
  },
  insuffisant: {
    label: "Échantillon insuffisant",
    cls: "border-amber-200 bg-amber-50 text-amber-800",
    aide: "Moins de 150 paris gagnants : aucun verdict ne serait honnête à cette échelle.",
  },
};

export function VerdictBadge({ verdict, className = "" }: { verdict?: string; className?: string }) {
  const v = VERDICTS[verdict ?? "insuffisant"] ?? VERDICTS.insuffisant;
  return (
    <span
      title={v.aide}
      className={cn(
        "inline-flex items-center whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-semibold",
        v.cls,
        className,
      )}
    >
      {v.label}
    </span>
  );
}

// ─── adaptateurs ─────────────────────────────────────────────

/** Tuile de chiffre. `valueClass` reste accepté : plusieurs onglets colorent la
 *  valeur eux-mêmes selon un seuil métier, pas selon un simple signe. */
export function StatTile({
  label, value, sub, hint, valueClass, icon, footer,
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
    <Tuile
      label={label}
      valeur={<span className={valueClass}>{value}</span>}
      sub={sub}
      aide={hint}
      icone={icon}
      pied={footer}
    />
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
    <Panneau titre={title} desc={desc} actions={right} className={className}>
      {children}
    </Panneau>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <Vide>{children}</Vide>;
}

export function Note({ children }: { children: React.ReactNode }) {
  return <NoteUI>{children}</NoteUI>;
}

/** Barre horizontale de polarité, pour lire un ROI sans lire le chiffre. */
export function PolarityBar({ value, max }: { value: number | null; max: number }) {
  return <BarrePolarite value={value} max={max} />;
}
