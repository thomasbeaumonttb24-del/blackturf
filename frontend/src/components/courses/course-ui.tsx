/* Briques visuelles communes aux onglets de la fiche course (Synthèse,
   Partants, Marché, Plan de mise, Résultats). Une seule source pour le relief
   des cartes, le bandeau d'onglet et les titres : sinon chaque onglet dérive
   au premier ajustement. Aucune logique métier ici. */
import type { CSSProperties, ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export const SG = { fontFamily: "var(--font-space-grotesk), sans-serif" } as const;

/** Carte en relief — même rendu que les cartes des chevaux (onglet Partants). */
export const CARTE_CLS =
  "rounded-2xl bg-white ring-1 ring-[#ECE7DC] shadow-[inset_0_1px_0_#fff,0_1px_2px_rgba(17,24,39,.05),0_12px_28px_-22px_rgba(17,24,39,.45)]";

/** Même carte, pour les blocs encore écrits en styles en ligne. */
export const CARTE_STYLE: CSSProperties = {
  borderRadius: 16,
  background: "#FFFFFF",
  border: "1px solid #ECE7DC",
  boxShadow: "inset 0 1px 0 #fff, 0 1px 2px rgba(17,24,39,.05), 0 12px 28px -22px rgba(17,24,39,.45)",
};

/** Tuile d'icône dorée en relief, en tête de carte. */
export function IconeTuile({ icone: Icone, className }: { icone: LucideIcon; className?: string }) {
  return (
    <span className={cn(
      "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-b from-amber-50 to-amber-100 text-amber-700 ring-1 ring-inset ring-amber-200 shadow-[inset_0_1px_0_#fff,0_2px_4px_-1px_rgba(146,64,14,.25)]",
      className,
    )}>
      <Icone className="h-4 w-4" aria-hidden="true" />
    </span>
  );
}

/** Titre de carte : tuile d'icône, titre, sous-titre et élément à droite. */
export function TitreCarte({ icone, titre, sousTitre, droite, as: Tag = "h3" }: {
  icone: LucideIcon;
  titre: ReactNode;
  sousTitre?: ReactNode;
  droite?: ReactNode;
  as?: "h2" | "h3";
}) {
  return (
    <div className="flex items-center gap-2.5">
      <IconeTuile icone={icone} />
      <div className="min-w-0">
        <Tag className="m-0 text-[15px] font-bold leading-tight text-stone-900" style={SG}>{titre}</Tag>
        {sousTitre && <p className="m-0 mt-0.5 text-[12px] leading-snug text-stone-500">{sousTitre}</p>}
      </div>
      {droite && <div className="ml-auto flex shrink-0 items-center gap-2">{droite}</div>}
    </div>
  );
}

/** Bandeau d'onglet : panneau teinté et plat, nettement distinct des cartes
 *  blanches en relief qui suivent. `bas` accueille une barre d'outils (tri…). */
export function BandeauOnglet({ icone: Icone, titre, sousTitre, droite, bas, id, className }: {
  icone: LucideIcon;
  titre: string;
  sousTitre?: ReactNode;
  droite?: ReactNode;
  bas?: ReactNode;
  id?: string;
  className?: string;
}) {
  return (
    <header className={cn("rounded-[20px] bg-[#F3EDE0] px-4 py-4 ring-1 ring-inset ring-[#E6DCC6] sm:px-5", className)}>
      <div className="flex flex-wrap items-start gap-x-4 gap-y-3">
        <div className="min-w-0">
          <h2 id={id} className="m-0 flex items-center gap-2 text-[18px] font-bold leading-tight tracking-tight text-stone-900" style={SG}>
            <Icone className="h-[18px] w-[18px] text-amber-700" aria-hidden="true" />{titre}
          </h2>
          {sousTitre && <p className="m-0 mt-0.5 text-[12.5px] text-stone-500">{sousTitre}</p>}
        </div>
        {droite && (
          <div className="flex w-full flex-wrap items-center justify-between gap-2 sm:ml-auto sm:w-auto sm:items-center">
            {droite}
          </div>
        )}
      </div>
      {bas && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-[#E6DCC6] pt-3">{bas}</div>
      )}
    </header>
  );
}

/** Pastille arrondie (statut, niveau, signal). */
export function Pastille({ children, className, title }: { children: ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset", className)}>
      {children}
    </span>
  );
}

/** Niveau de la course d'après la confiance du modèle sur son favori — même
 *  lecture dans tous les onglets. */
export function difficulteCourse(confGlobal: number | null) {
  if (confGlobal == null) return null;
  return confGlobal >= 70 ? { txt: "Favori clair", cls: "bg-emerald-50 text-emerald-800 ring-emerald-200" }
    : confGlobal >= 50 ? { txt: "Course ouverte", cls: "bg-amber-50 text-amber-800 ring-amber-200" }
    : { txt: "Course serrée", cls: "bg-rose-50 text-rose-800 ring-rose-200" };
}

/** Pastille « En direct » animée. */
export function PastilleDirect({ libelle = "En direct" }: { libelle?: string }) {
  return (
    <Pastille className="bg-emerald-50 text-emerald-800 ring-emerald-200">
      <span className="relative flex h-1.5 w-1.5">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60 motion-reduce:animate-none" />
        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
      </span>
      {libelle}
    </Pastille>
  );
}

/** Raccourcis vers les autres onglets, en bas de chaque onglet : sur téléphone,
 *  on enchaîne sans remonter tout en haut de la page. */
export function SuiteOnglets<K extends string>({ onglets, actif, onAller }: {
  onglets: { cle: K; label: string; icone: LucideIcon; desc: string }[];
  actif: K;
  onAller: (cle: K) => void;
}) {
  const autres = onglets.filter((o) => o.cle !== actif);
  if (autres.length === 0) return null;
  return (
    <nav aria-label="Autres sections de la course" className="pt-1">
      <p className="m-0 mb-2.5 text-[11px] font-bold uppercase tracking-[.1em] text-stone-500">Continuer</p>
      <div className={cn("grid gap-2.5 sm:grid-cols-2", autres.length >= 4 ? "lg:grid-cols-4" : "lg:grid-cols-3")}>
        {autres.map((o) => (
          <button
            key={o.cle}
            type="button"
            onClick={() => onAller(o.cle)}
            className={cn(CARTE_CLS, "group flex items-center gap-3 p-3.5 text-left transition-transform hover:-translate-y-0.5 active:scale-[.985] focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-700")}
          >
            <IconeTuile icone={o.icone} />
            <span className="min-w-0 flex-1">
              <span className="block text-[14px] font-bold text-stone-900" style={SG}>{o.label}</span>
              <span className="block text-[12px] leading-snug text-stone-500">{o.desc}</span>
            </span>
            <span aria-hidden="true" className="text-lg text-stone-300 transition-colors group-hover:text-amber-600">›</span>
          </button>
        ))}
      </div>
    </nav>
  );
}

/** Lien d'action discret vers un autre onglet (« Voir le plan de mise › »). */
export function LienOnglet({ children, onClick, className }: { children: ReactNode; onClick: () => void; className?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn("inline-flex items-center gap-1 rounded-lg bg-white px-3 py-1.5 text-[12.5px] font-semibold text-amber-800 ring-1 ring-inset ring-amber-200 shadow-[inset_0_1px_0_#fff,0_1px_2px_rgba(146,64,14,.12)] transition-colors hover:bg-amber-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-700", className)}
    >
      {children}<span aria-hidden="true">›</span>
    </button>
  );
}
