import Link from "next/link";
import { titleCase, type SeoResultatLigne } from "@/lib/seo";

const MARCHES = [
  { position: 2, classe: "podium-argent", hauteur: "h-24 sm:h-28", label: "2e" },
  { position: 1, classe: "podium-or", hauteur: "h-32 sm:h-36", label: "1er" },
  { position: 3, classe: "podium-bronze", hauteur: "h-20 sm:h-24", label: "3e" },
];

/** Les trois premiers d'une arrivée officielle, en podium : 2e, 1er, 3e. */
export function Podium({ classement, href }: { classement: SeoResultatLigne[]; href: string }) {
  const parPlace = new Map(classement.map((l) => [l.position, l]));
  return (
    <Link href={href} className="group block" aria-label="Voir l'arrivée complète et les rapports">
      <ol className="grid grid-cols-3 items-end gap-2 sm:gap-3">
        {MARCHES.map((m) => {
          const l = parPlace.get(m.position);
          return (
            <li key={m.position} className="flex flex-col items-center text-center">
              <div className="mb-2 min-h-[2.75rem] px-1">
                <div className="font-display text-[13px] font-bold leading-tight text-brand-dark sm:text-sm">
                  {l ? titleCase(l.nom) : "—"}
                </div>
                {l && <div className="mt-0.5 text-[11px] tabular-nums text-brand-charcoal">n°{l.numero}</div>}
              </div>
              <div className={`podium-marche ${m.classe} ${m.hauteur} flex w-full items-start justify-center pt-3`}>
                <span className="font-display text-2xl font-bold text-brand-dark/80 sm:text-3xl">{m.label}</span>
              </div>
            </li>
          );
        })}
      </ol>
      <div className="mt-3 text-right text-xs font-medium text-brand-gold-dark group-hover:underline">
        Arrivée complète et rapports PMU →
      </div>
    </Link>
  );
}
