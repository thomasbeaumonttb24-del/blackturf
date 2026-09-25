/**
 * Le Défi du mois expliqué en 4 étapes. Partagé par l'accueil, la page /defi,
 * le programme et l'onglet Défi des courses : une seule formulation partout.
 */
import { Coins, Crown, Flag, Target } from "lucide-react";
import { cn } from "@/lib/utils";
import { planLabel } from "@/components/defi/kit";

type Props = {
  capital?: number;
  pointsMin?: number;
  pointsMax?: number;
  prix?: { jours: number; plan: string };
  /** « ligne » : les 4 étapes en une rangée compacte (programme, course). */
  variante?: "cartes" | "ligne";
  className?: string;
};

export function etapesDefi({ capital = 1000, pointsMin = 10, pointsMax = 100,
  prix = { jours: 30, plan: "expert" } }: Omit<Props, "variante" | "className"> = {}) {
  return [
    { icone: Coins, titre: `${capital.toLocaleString("fr-FR")} points offerts`,
      texte: "Chaque 1er du mois, tout compte (même gratuit) reçoit sa cagnotte de points. Aucun argent réel." },
    { icone: Target, titre: "Pariez avant le départ",
      texte: `Choisissez vos chevaux (ou ceux du plan de mise) et misez de ${pointsMin} à ${pointsMax} points par pari.` },
    { icone: Flag, titre: "Gagnez au rapport officiel",
      texte: "Pari gagnant = points misés × rapport PMU à l'arrivée. Le classement bouge après chaque course." },
    { icone: Crown, titre: `${prix.jours} jours ${planLabel(prix.plan)} au 1er`,
      texte: "Le meilleur solde du mois remporte l'abonnement, les 2e et 3e un mois Standard." },
  ];
}

export function DefiConcept({ variante = "cartes", className, ...regles }: Props) {
  const etapes = etapesDefi(regles);
  if (variante === "ligne") {
    return (
      <ol className={cn("grid grid-cols-2 gap-2 sm:grid-cols-4", className)}>
        {etapes.map((e, i) => (
          <li key={e.titre} className="flex items-start gap-2 rounded-xl bg-white/80 px-3 py-2.5 ring-1 ring-inset ring-[#E6DCC6]">
            <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-amber-100 text-[11px] font-bold text-amber-800">{i + 1}</span>
            <span className="text-[12px] font-semibold leading-snug text-slate-800">{e.titre}</span>
          </li>
        ))}
      </ol>
    );
  }
  return (
    <ol className={cn("grid gap-3 sm:grid-cols-2 lg:grid-cols-4", className)}>
      {etapes.map((e, i) => (
        <li key={e.titre} className="relative rounded-2xl bg-white p-4 ring-1 ring-inset ring-[#ECE7DC] shadow-[0_1px_2px_rgba(17,24,39,.04)]">
          <div className="flex items-center gap-2">
            <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-b from-amber-50 to-amber-100 text-amber-700 ring-1 ring-inset ring-amber-200">
              <e.icone className="h-4 w-4" aria-hidden="true" />
            </span>
            <span className="text-[11px] font-bold uppercase tracking-wider text-amber-700">Étape {i + 1}</span>
          </div>
          <h3 className="mt-2.5 text-[14px] font-bold text-slate-900">{e.titre}</h3>
          <p className="mt-1 text-[12.5px] leading-relaxed text-slate-600">{e.texte}</p>
        </li>
      ))}
    </ol>
  );
}
