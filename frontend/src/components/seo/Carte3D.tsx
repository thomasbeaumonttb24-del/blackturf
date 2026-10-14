import type { ReactNode } from "react";

export interface FaitCarte {
  label: string;
  valeur: ReactNode;
}

/**
 * Carte en relief de l'en-tête : un titre court et quatre à six faits clés
 * (lieu, heure, distance…). Purement présentationnelle, rendue côté serveur.
 */
export function Carte3D({
  surtitre,
  titre,
  faits,
  pied,
}: {
  surtitre: string;
  titre: ReactNode;
  faits: FaitCarte[];
  pied?: ReactNode;
}) {
  return (
    <div className="carte-3d-scene mt-8 max-w-xl">
      <div className="carte-3d rounded-3xl p-5 text-white sm:p-6">
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-300">{surtitre}</div>
        <div className="mt-1.5 font-display text-xl font-bold leading-snug sm:text-2xl">{titre}</div>
        <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-3">
          {faits.map((f) => (
            <div key={f.label} className="min-w-0">
              <dt className="text-[10.5px] uppercase tracking-wider text-stone-400">{f.label}</dt>
              <dd className="mt-0.5 break-words font-display text-base font-semibold leading-snug tabular-nums text-white sm:text-lg">
                {f.valeur}
              </dd>
            </div>
          ))}
        </dl>
        {pied && <div className="mt-5 border-t border-white/10 pt-4 text-[12.5px] leading-relaxed text-stone-300">{pied}</div>}
      </div>
    </div>
  );
}
