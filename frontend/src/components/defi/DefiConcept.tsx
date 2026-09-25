/**
 * Le Défi du mois expliqué en 4 étapes. Partagé par l'accueil, la page /defi et
 * l'onglet Défi des courses : une seule formulation partout.
 */
import { Coins, Crown, Flag, Target } from "lucide-react";
import { cn } from "@/lib/utils";
import { planLabel, formatNombre } from "@/components/defi/kit";

type Props = {
  capital?: number;
  pointsMin?: number;
  pointsMax?: number;
  prix?: { jours: number; plan: string };
  /** « ligne » : les 4 étapes en une frise compacte (onglet Défi d'une course). */
  variante?: "cartes" | "ligne";
  className?: string;
};

export function etapesDefi({ capital = 1000, pointsMin = 10, pointsMax = 100,
  prix = { jours: 30, plan: "expert" } }: Omit<Props, "variante" | "className"> = {}) {
  return [
    { icone: Coins, court: `${formatNombre(capital, 2)} pts offerts`,
      titre: `${formatNombre(capital, 2)} points offerts`,
      texte: "Chaque 1er du mois, tout compte, même gratuit, reçoit sa cagnotte. Aucun argent réel n'est en jeu." },
    { icone: Target, court: "Pariez avant le départ",
      titre: "Pariez avant le départ",
      texte: `Vos chevaux ou ceux du plan de mise : ${pointsMin} à ${pointsMax} points par pari, verrouillé au départ.` },
    { icone: Flag, court: "Points × rapport PMU",
      titre: "Gagnez au rapport officiel",
      texte: "Pari gagnant = points misés × rapport PMU officiel. Le classement bouge après chaque arrivée." },
    { icone: Crown, court: `${prix.jours} j ${planLabel(prix.plan)} au 1er`,
      titre: `${prix.jours} jours ${planLabel(prix.plan)} au 1er`,
      texte: "Le meilleur solde du mois remporte l'abonnement. Les 2e et 3e gagnent un mois Standard." },
  ];
}

export function DefiConcept({ variante = "cartes", className, ...regles }: Props) {
  const etapes = etapesDefi(regles);

  if (variante === "ligne") {
    return (
      <ol className={cn("grid grid-cols-2 overflow-hidden rounded-2xl bg-white ring-1 ring-inset ring-[#ECE7DC] sm:grid-cols-4", className)}>
        {etapes.map((e, i) => (
          <li key={e.titre} className={cn("flex items-center gap-2.5 px-3 py-3",
            i % 2 === 1 && "border-l border-stone-100", i >= 2 && "border-t border-stone-100 sm:border-t-0", i >= 1 && "sm:border-l")}>
            <span className="relative inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-gradient-to-b from-amber-50 to-amber-100 text-amber-700 ring-1 ring-inset ring-amber-200">
              <e.icone className="h-4 w-4" aria-hidden="true" />
              <span className="absolute -right-1.5 -top-1.5 inline-flex h-4 w-4 items-center justify-center rounded-full bg-gradient-to-b from-amber-500 to-amber-700 text-[9px] font-bold text-white">{i + 1}</span>
            </span>
            <span className="text-[12px] font-semibold leading-tight text-slate-800">{e.court}</span>
          </li>
        ))}
      </ol>
    );
  }

  return (
    <ol className={cn("relative grid gap-3 sm:grid-cols-2 lg:grid-cols-4", className)}>
      {etapes.map((e, i) => (
        <li key={e.titre}
          className="group relative flex flex-col rounded-2xl bg-white p-4 ring-1 ring-inset ring-[#ECE7DC] shadow-[0_1px_2px_rgba(17,24,39,.04),0_18px_36px_-30px_rgba(17,24,39,.5)] transition-transform hover:-translate-y-0.5">
          <div className="flex items-center justify-between">
            <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-b from-amber-50 to-amber-100 text-amber-700 ring-1 ring-inset ring-amber-200">
              <e.icone className="h-5 w-5" aria-hidden="true" />
            </span>
            <span className="font-display text-[28px] font-bold leading-none text-stone-200 transition-colors group-hover:text-amber-200">0{i + 1}</span>
          </div>
          <h3 className="mt-3 text-[14.5px] font-bold text-slate-900">{e.titre}</h3>
          <p className="mt-1 text-[12.5px] leading-relaxed text-slate-600">{e.texte}</p>
        </li>
      ))}
    </ol>
  );
}
