/* Briques visuelles communes aux onglets de la fiche course (Synthèse,
   Partants, Marché, Plan de mise, Résultats). Une seule source pour le relief
   des cartes, le bandeau d'onglet et les titres : sinon chaque onglet dérive
   au premier ajustement. Aucune logique métier ici. */
"use client";

import { useId, type CSSProperties, type PointerEvent, type ReactNode } from "react";
import { Lock, type LucideIcon } from "lucide-react";
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

/** Jauge circulaire de la chance de victoire : l'arc est la VRAIE probabilité
 *  (25 % = un quart de tour), pas une échelle relative au favori. */
export function Anneau({ v, rang, taille }: { v: number; rang: number | undefined; taille: number }) {
  const id = useId();
  const r = taille / 2 - 4;
  const c = 2 * Math.PI * r;
  const couleurs = rang === 1 ? ["#FCD34D", "#D97706"] : rang != null && rang <= 3 ? ["#94A3B8", "#334155"] : ["#D6D3D1", "#78716C"];
  const txt = v < 0.005 ? "<1" : String(Math.round(v * 100));
  return (
    <span
      className="relative inline-flex shrink-0 items-center justify-center rounded-full bg-gradient-to-b from-white to-stone-100 shadow-[inset_0_1px_0_#fff,0_1px_1px_rgba(17,24,39,.06),0_6px_14px_-8px_rgba(17,24,39,.35)]"
      style={{ width: taille, height: taille }}
      role="img"
      aria-label={`${txt} % de chance de victoire`}
    >
      <svg width={taille} height={taille} className="absolute inset-0 -rotate-90" aria-hidden="true">
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor={couleurs[0]} />
            <stop offset="100%" stopColor={couleurs[1]} />
          </linearGradient>
        </defs>
        <circle cx={taille / 2} cy={taille / 2} r={r} fill="none" stroke="#F1EEE6" strokeWidth="4" />
        <circle
          cx={taille / 2} cy={taille / 2} r={r} fill="none" stroke={`url(#${id})`} strokeWidth="4" strokeLinecap="round"
          strokeDasharray={`${Math.max(0.02, Math.min(1, v)) * c} ${c}`}
          className="transition-[stroke-dasharray] duration-700"
        />
      </svg>
      <span className={cn("relative font-bold tabular-nums leading-none", rang === 1 ? "text-amber-700" : "text-stone-900")} style={{ ...SG, fontSize: taille >= 52 ? 14 : 13 }}>
        {txt}<span className="text-[0.75em]">%</span>
      </span>
    </span>
  );
}


/** Inclinaison 3D qui suit la souris (ordinateur seulement ; coupée en mouvement
 *  réduit). Écrit des variables CSS sur l'élément survolé — aucun rendu React. */
export function inclinerCarte(e: PointerEvent<HTMLElement>, force = 1) {
  const el = e.currentTarget;
  if (e.pointerType !== "mouse") return;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const r = el.getBoundingClientRect();
  const x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
  el.style.setProperty("--rx", `${((0.5 - y) * 6 * force).toFixed(2)}deg`);
  el.style.setProperty("--ry", `${((x - 0.5) * 7 * force).toFixed(2)}deg`);
  el.style.setProperty("--mx", `${(x * 100).toFixed(1)}%`);
  el.style.setProperty("--my", `${(y * 100).toFixed(1)}%`);
  el.style.setProperty("--lift", "-4px");
}
export function redresserCarte(e: PointerEvent<HTMLElement>) {
  const el = e.currentTarget;
  el.style.setProperty("--rx", "0deg");
  el.style.setProperty("--ry", "0deg");
  el.style.setProperty("--lift", "0px");
}

/** Classes de la carte inclinable (à combiner avec useInclinaison). */
export const INCLINABLE_CLS =
  "[transform:perspective(900px)_translateY(var(--lift,0px))_rotateX(var(--rx,0deg))_rotateY(var(--ry,0deg))] transition-[transform,box-shadow] duration-300 ease-out motion-reduce:transition-none";

/** Reflet doré qui suit la souris, à placer dans une carte `relative group/reflet`. */
export function Reflet() {
  return (
    <span aria-hidden="true" className="pointer-events-none absolute inset-0 rounded-[inherit] opacity-0 transition-opacity duration-300 group-hover/reflet:opacity-100 [background:radial-gradient(360px_circle_at_var(--mx,50%)_var(--my,50%),rgba(251,191,36,.16),transparent_50%)]" />
  );
}


/* ────────────────────────────────────────────────────────────────────────── */
/*  Vue non abonnée : mêmes cartes que l'abonné, contenu réservé masqué        */
/* ────────────────────────────────────────────────────────────────────────── */
/* Règle commune à toutes ces briques : un visiteur voit la MISE EN PAGE exacte
   de la fiche abonné (mêmes cartes, mêmes jauges, mêmes colonnes), mais jamais
   une donnée que le serveur ne lui envoie pas. Ce qui est masqué est dessiné
   en formes neutres — rien à lire sous un flou, rien dans le HTML. */

/** Destination de l'appel à l'abonnement : un visiteur crée d'abord son compte
 *  (l'essai part de là), un compte gratuit passe directement aux formules. */
export function lienAbonnement(connecte: boolean, suite?: string) {
  return connecte
    ? { href: "/tarifs", libelle: "Passer Standard — 12 €/mois" }
    : { href: `/inscription${suite ? `?suite=${encodeURIComponent(suite)}` : ""}`, libelle: "Essai gratuit 7 jours" };
}

/** Bouton doré d'abonnement, identique partout où un contenu est réservé. */
export function BoutonAbonnement({ connecte, suite, libelle, className, discret }: {
  connecte: boolean; suite?: string; libelle?: string; className?: string; discret?: boolean;
}) {
  const l = lienAbonnement(connecte, suite);
  return (
    <a
      href={l.href}
      className={cn(
        "inline-flex min-h-9 items-center justify-center gap-1.5 rounded-xl px-4 py-1.5 text-center text-[12.5px] leading-tight font-bold transition-[transform,filter] hover:-translate-y-0.5 hover:brightness-105 focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-700",
        discret
          ? "bg-white text-amber-800 ring-1 ring-inset ring-amber-300 shadow-[inset_0_1px_0_#fff,0_1px_2px_rgba(146,64,14,.12)]"
          : "bg-gradient-to-b from-amber-400 to-amber-500 text-stone-900 ring-1 ring-inset ring-amber-600/30 shadow-[inset_0_1px_0_rgba(255,255,255,.5),0_10px_22px_-12px_rgba(146,64,14,.8)]",
        className,
      )}
    >
      <Lock className="h-3.5 w-3.5" aria-hidden="true" />
      {libelle ?? l.libelle}
    </a>
  );
}

/** Pastille « réservé » — même gabarit que les autres pastilles. */
export function PastilleReserve({ libelle = "Réservé abonnés", className }: { libelle?: string; className?: string }) {
  return (
    <Pastille className={cn("bg-amber-50 text-amber-800 ring-amber-200", className)}>
      <Lock className="h-3 w-3" aria-hidden="true" />{libelle}
    </Pastille>
  );
}

/** Identité masquée : tapis de selle sans numéro et nom en hachures. */
export function IdentiteMasquee({ largeur = "9rem", className }: { largeur?: string; className?: string }) {
  return (
    <span className={cn("flex min-w-0 items-center gap-2", className)} aria-label="Cheval réservé aux abonnés">
      <span
        aria-hidden="true"
        className="inline-flex h-[26px] w-[30px] shrink-0 items-center justify-center rounded-md bg-slate-800 text-[12px] font-extrabold text-white/80"
      >
        ?
      </span>
      <span
        aria-hidden="true"
        className="h-3.5 min-w-0 flex-1 rounded-full"
        style={{ maxWidth: largeur, backgroundImage: "repeating-linear-gradient(115deg,#E7E1D3 0 6px,#F4EFE4 6px 12px)" }}
      />
    </span>
  );
}

/** Jauge circulaire verrouillée : même relief que `Anneau`, arc absent. */
export function AnneauVerrouille({ taille }: { taille: number }) {
  return (
    <span
      className="relative inline-flex shrink-0 items-center justify-center rounded-full bg-gradient-to-b from-white to-stone-100 shadow-[inset_0_1px_0_#fff,0_1px_1px_rgba(17,24,39,.06),0_6px_14px_-8px_rgba(17,24,39,.35)]"
      style={{ width: taille, height: taille }}
      role="img"
      aria-label="Chance de victoire réservée aux abonnés"
    >
      <svg width={taille} height={taille} className="absolute inset-0" aria-hidden="true">
        <circle cx={taille / 2} cy={taille / 2} r={taille / 2 - 4} fill="none" stroke="#EDE7DA" strokeWidth="4" strokeDasharray="3 4" />
      </svg>
      <Lock className="relative h-4 w-4 text-amber-700/80" aria-hidden="true" />
    </span>
  );
}

/** Barre de squelette (texte réservé). */
export function Squelette({ largeur = "100%", className }: { largeur?: string; className?: string }) {
  return <span aria-hidden="true" className={cn("block h-2.5 rounded-full bg-stone-200/80", className)} style={{ width: largeur }} />;
}

/** Contenu réservé : un décor flou (formes seulement, jamais la vraie donnée)
 *  sous un voile qui dit ce qu'il y a derrière et comment l'ouvrir. */
export function VoileAbonne({ decor, icone: Icone = Lock, titre, texte, action, className }: {
  decor: ReactNode;
  icone?: LucideIcon;
  titre: ReactNode;
  texte?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("relative min-h-[17rem] overflow-hidden rounded-2xl", className)}>
      <div aria-hidden="true" className="pointer-events-none select-none blur-[1.5px]">{decor}</div>
      <div className="absolute inset-0 flex items-center justify-center p-4 [background:radial-gradient(ellipse_at_center,rgba(255,255,255,.94)_0%,rgba(255,255,255,.82)_38%,rgba(255,255,255,.35)_80%)]">
        <div className="max-w-md text-center">
          <span className="mx-auto mb-2.5 inline-flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-b from-amber-50 to-amber-100 text-amber-700 ring-1 ring-inset ring-amber-200 shadow-[inset_0_1px_0_#fff,0_6px_14px_-6px_rgba(146,64,14,.45)]">
            <Icone className="h-[18px] w-[18px]" aria-hidden="true" />
          </span>
          <p className="m-0 text-[14.5px] font-bold leading-snug text-stone-900" style={SG}>{titre}</p>
          {texte && <p className="m-0 mx-auto mt-1 max-w-sm text-[12.5px] leading-5 text-stone-600">{texte}</p>}
          {action && <div className="mt-3 flex flex-wrap items-center justify-center gap-2">{action}</div>}
        </div>
      </div>
    </div>
  );
}
