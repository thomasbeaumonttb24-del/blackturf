"use client";

/**
 * Kit d'interface du back-office — une seule grammaire visuelle pour toute la console.
 *
 * Avant : trois langages coexistaient. `/admin` peignait avec les jetons du thème
 * (`bg-card`, `border-border`), `/admin/algorithme` avec des gris en dur
 * (`bg-white`, `text-gray-900`) et `/admin/instagram` avec les `Card` du site
 * public. Trois pages du même outil, trois hiérarchies typographiques, et des
 * tailles de texte tirées au sort entre 9 et 13 px — dont beaucoup sous le seuil
 * de lisibilité sur téléphone.
 *
 * Ce fichier fixe l'échelle une fois pour toutes :
 *
 *   · étiquette   11 px, capitales, `tracking` ouvert, muted   — nomme un chiffre
 *   · corps       13 px                                        — plancher du contenu
 *   · secondaire  12 px                                        — méta, jamais l'essentiel
 *   · chiffre     20 px (22 dès `sm`), tabulaire               — la valeur
 *   · titre       15 px semi-gras                              — en-tête de panneau
 *
 * Rien en dessous de 11 px, et le 12 px ne porte jamais une information qu'on
 * n'a pas déjà lue ailleurs. La couleur de marque (l'or) n'est utilisée que pour
 * l'action et l'état actif ; les chiffres, eux, ne prennent une couleur que pour
 * dire un signe (vert/rouge) — jamais pour décorer.
 */

import * as React from "react";
import { ChevronDown, Info } from "lucide-react";
import { cn } from "@/lib/utils";

/* ─────────────────────────── échelle typographique ─────────────────────── */

export const T = {
  /** Nomme un chiffre ou une colonne. */
  etiquette: "text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground",
  /** Plancher du contenu lisible. */
  corps: "text-[13px] leading-relaxed",
  /** Méta : date, compte, précision. Jamais porteur seul d'une information. */
  meta: "text-xs text-muted-foreground",
  /** La valeur. */
  chiffre: "text-xl font-semibold tabular-nums tracking-tight sm:text-[22px]",
  chiffreSm: "text-base font-semibold tabular-nums tracking-tight",
  titre: "text-[15px] font-semibold tracking-tight text-foreground",
  titreSection: "text-lg font-semibold tracking-tight text-foreground sm:text-xl",
} as const;

export type Ton = "neutre" | "ok" | "attention" | "alerte" | "or";

/** Habillage d'un ton. Le fond reste très pâle : un panneau entier en rouge vif
 *  hurle aussi fort pour une alerte que pour dix. */
export const TONS: Record<Ton, { texte: string; bord: string; fond: string; pastille: string }> = {
  neutre: {
    texte: "text-foreground",
    bord: "border-border",
    fond: "bg-muted/40",
    pastille: "border-border bg-muted/60 text-muted-foreground",
  },
  ok: {
    texte: "text-emerald-700",
    bord: "border-emerald-200",
    fond: "bg-emerald-50",
    pastille: "border-emerald-200 bg-emerald-50 text-emerald-700",
  },
  attention: {
    texte: "text-amber-700",
    bord: "border-amber-200",
    fond: "bg-amber-50",
    pastille: "border-amber-200 bg-amber-50 text-amber-800",
  },
  alerte: {
    texte: "text-red-700",
    bord: "border-red-200",
    fond: "bg-red-50",
    pastille: "border-red-200 bg-red-50 text-red-700",
  },
  or: {
    texte: "text-brand-gold-dark",
    bord: "border-brand-gold/30",
    fond: "bg-brand-gold-light",
    pastille: "border-brand-gold/30 bg-brand-gold-light text-brand-gold-dark",
  },
};

/* ─────────────────────────────── formats ───────────────────────────────── */

// Espace fine insécable : règle typographique française devant % et €, et
// garantie qu'une étiquette ne se coupe jamais en « −8 » / « % » sur deux lignes.
const NB = " ";
const fr = (v: number, digits: number) =>
  new Intl.NumberFormat("fr-FR", {
    minimumFractionDigits: digits, maximumFractionDigits: digits,
  }).format(v);

export const nf = new Intl.NumberFormat("fr-FR");

export function num(v: number | null | undefined): string {
  return v == null || !isFinite(v) ? "—" : nf.format(v);
}

export function eur(v: number | null | undefined, digits = 0): string {
  if (v == null || !isFinite(v)) return "—";
  return `${v < 0 ? "−" : ""}${fr(Math.abs(v), digits)}${NB}€`;
}

export function signedEur(v: number | null | undefined, digits = 0): string {
  if (v == null || !isFinite(v)) return "—";
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${fr(Math.abs(v), digits)}${NB}€`;
}

export function pct(v: number | null | undefined, digits = 1): string {
  if (v == null || !isFinite(v)) return "—";
  return `${fr(v, digits)}${NB}%`;
}

export function signedPct(v: number | null | undefined, digits = 1): string {
  if (v == null || !isFinite(v)) return "—";
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${fr(Math.abs(v), digits)}${NB}%`;
}

/** Couleur de polarité — vert au-dessus de zéro, rouge en dessous, neutre à zéro. */
export function tone(v: number | null | undefined): string {
  if (v == null || !isFinite(v) || v === 0) return "text-muted-foreground";
  return v > 0 ? "text-emerald-700" : "text-red-700";
}

/** « il y a 4 min » — ne rend rien côté serveur, la donnée n'existe qu'après fetch. */
export function depuis(iso: string | null | undefined): string {
  if (!iso) return "jamais";
  const ms = Date.now() - new Date(iso).getTime();
  if (!isFinite(ms)) return "—";
  const min = Math.floor(ms / 60000);
  if (min < 1) return "à l'instant";
  if (min < 60) return `il y a ${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `il y a ${h} h`;
  return `il y a ${Math.floor(h / 24)} j`;
}

/* ──────────────────────────── mise en page ─────────────────────────────── */

/**
 * En-tête de page. Une seule par écran, et elle répond toujours à la même
 * question dans le même ordre : où je suis, ce que ça mesure, ce que je peux y
 * faire.
 */
export function EnTetePage({
  titre, desc, actions, icone,
}: {
  titre: string;
  desc?: React.ReactNode;
  actions?: React.ReactNode;
  icone?: React.ReactNode;
}) {
  return (
    <header className="flex flex-col items-start gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="flex min-w-0 items-start gap-3">
        {/* Sur téléphone, la barre du haut affiche déjà le nom de l'écran, et il
            reste visible en défilant. Le répéter 60 px plus bas mangeait un
            tiers du premier écran pour ne rien apprendre : le titre reste dans
            le document (structure, lecteurs d'écran) mais sort du visuel. */}
        {icone && (
          <span className="mt-0.5 hidden h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-gold/10 text-brand-gold-dark lg:flex">
            {icone}
          </span>
        )}
        <div className="min-w-0">
          <h1 className={cn(T.titreSection, "font-display sr-only lg:not-sr-only")}>{titre}</h1>
          {desc && <p className={cn("max-w-2xl lg:mt-1", T.meta, "leading-relaxed")}>{desc}</p>}
        </div>
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

/** Panneau. La brique de base : un titre, une explication courte, du contenu. */
export function Panneau({
  titre, desc, icone, actions, ton = "neutre", className, bodyClassName, children, pied,
}: {
  titre?: React.ReactNode;
  desc?: React.ReactNode;
  icone?: React.ReactNode;
  actions?: React.ReactNode;
  ton?: Ton;
  className?: string;
  bodyClassName?: string;
  children: React.ReactNode;
  pied?: React.ReactNode;
}) {
  const t = TONS[ton];
  return (
    <section
      className={cn(
        "overflow-hidden rounded-2xl border bg-card shadow-sm",
        ton === "neutre" ? "border-border" : t.bord,
        className,
      )}
    >
      {(titre || actions) && (
        <header className="flex flex-col gap-2.5 border-b border-border/60 px-4 py-3.5 sm:flex-row sm:items-start sm:justify-between sm:gap-4 sm:px-5">
          <div className="flex min-w-0 items-start gap-2.5">
            {icone && (
              <span className={cn("mt-px flex h-6 w-6 shrink-0 items-center justify-center rounded-lg", t.pastille)}>
                {icone}
              </span>
            )}
            <div className="min-w-0">
              {titre && <h2 className={T.titre}>{titre}</h2>}
              {desc && <p className={cn("mt-1", T.meta, "leading-relaxed")}>{desc}</p>}
            </div>
          </div>
          {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cn("p-4 sm:p-5", bodyClassName)}>{children}</div>
      {pied && (
        <footer className={cn("border-t border-border/60 bg-muted/20 px-4 py-2.5 sm:px-5", T.meta)}>
          {pied}
        </footer>
      )}
    </section>
  );
}

/** Mémorise l'état ouvert/fermé par section, pour ne pas le reperdre à chaque visite. */
function useOuvert(cle: string, defaut: boolean) {
  const [ouvert, setOuvert] = React.useState(defaut);
  React.useEffect(() => {
    try {
      const v = window.localStorage.getItem(`bt.admin.section.${cle}`);
      if (v === "1" || v === "0") setOuvert(v === "1");
    } catch { /* stockage refusé : on garde le défaut */ }
  }, [cle]);
  const basculer = React.useCallback(() => {
    setOuvert((o) => {
      try { window.localStorage.setItem(`bt.admin.section.${cle}`, o ? "0" : "1"); } catch { /* noop */ }
      return !o;
    });
  }, [cle]);
  return [ouvert, basculer] as const;
}

/**
 * Panneau repliable.
 *
 * Règle tenue depuis la première version : l'en-tête doit rester lisible
 * REPLIÉ — il porte donc un résumé chiffré, sinon replier revient à cacher
 * l'information. Nouveauté : la zone de clic fait au moins 44 px de haut et
 * porte un chevron aligné à droite, comme n'importe quel accordéon de système ;
 * l'ancien chevron collé au titre se confondait avec la ponctuation.
 */
export function Repliable({
  id, titre, sousTitre, icone, resume, actions, defaut = true, ton = "neutre",
  bodyClassName, children,
}: {
  /** Clé de mémorisation de l'état plié/déplié. */
  id: string;
  titre: string;
  sousTitre?: React.ReactNode;
  icone?: React.ReactNode;
  /** Chiffres visibles même section repliée. */
  resume?: React.ReactNode;
  /** Contrôles (recherche, export…) — ne replient pas la section au clic. */
  actions?: React.ReactNode;
  defaut?: boolean;
  ton?: Ton;
  bodyClassName?: string;
  children: React.ReactNode;
}) {
  const [ouvert, basculer] = useOuvert(id, defaut);
  const t = TONS[ton];
  return (
    <section
      className={cn(
        "overflow-hidden rounded-2xl border bg-card shadow-sm transition-colors",
        ton === "neutre" ? "border-border" : t.bord,
      )}
    >
      <div className={cn("px-3 sm:px-5", ouvert && "border-b border-border/60")}>
        <button
          type="button"
          onClick={basculer}
          aria-expanded={ouvert}
          aria-controls={`section-${id}`}
          className="group flex min-h-[3.25rem] w-full items-center gap-3 py-2.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-card"
        >
          {icone && (
            <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border", t.pastille)}>
              {icone}
            </span>
          )}
          {/* Aucun `truncate` : à 390 px, « Erreurs récentes » se coupait en
              « Erreurs réc… ». Un en-tête qui porte le résumé d'une section
              repliée doit se lire en entier, quitte à passer sur deux lignes. */}
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-semibold leading-tight sm:text-[15px]">{titre}</span>
            {sousTitre && (
              <span className="mt-0.5 block text-xs leading-snug text-muted-foreground">{sousTitre}</span>
            )}
          </span>
          {resume && <span className="hidden shrink-0 items-center gap-1.5 sm:flex">{resume}</span>}
          <ChevronDown
            className={cn(
              "h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200 group-hover:text-foreground",
              ouvert && "rotate-180",
            )}
            aria-hidden
          />
        </button>
        {/* Sur téléphone le résumé passe sous le titre : entassé sur la même
            ligne, il repoussait le chevron hors de l'écran. */}
        {resume && <div className="flex flex-wrap items-center gap-1.5 pb-3 sm:hidden">{resume}</div>}
        {actions && <div className="pb-3">{actions}</div>}
      </div>
      {ouvert && (
        <div id={`section-${id}`} className={cn("p-3 sm:p-5", bodyClassName)}>
          {children}
        </div>
      )}
    </section>
  );
}

/* ─────────────────────────────── éléments ──────────────────────────────── */

/** Pastille de résumé, lisible section repliée. */
export function Puce({
  children, ton = "neutre", titre,
}: {
  children: React.ReactNode;
  ton?: Ton;
  titre?: string;
}) {
  return (
    <span
      title={titre}
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-semibold tabular-nums",
        TONS[ton].pastille,
      )}
    >
      {children}
    </span>
  );
}

/**
 * Tuile de chiffre.
 *
 * Le ton colore la VALEUR, jamais tout le bloc : sur une grille de six tuiles,
 * six fonds colorés ne hiérarchisent plus rien. Seule une tuile en alerte prend
 * un liseré, pour ressortir du lot.
 */
export function Tuile({
  label, valeur, sub, ton = "neutre", icone, aide, pied, className,
}: {
  label: React.ReactNode;
  valeur: React.ReactNode;
  sub?: React.ReactNode;
  ton?: Ton;
  icone?: React.ReactNode;
  /** Infobulle : ce que le chiffre mesure exactement. */
  aide?: string;
  pied?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border bg-card p-3 sm:p-3.5",
        ton === "alerte" ? "border-red-200 bg-red-50/40"
          : ton === "attention" ? "border-amber-200 bg-amber-50/40"
          : "border-border",
        className,
      )}
    >
      <div className="flex items-center gap-1.5">
        {icone && <span className="shrink-0 text-muted-foreground/70">{icone}</span>}
        {/* Pas de `truncate` : « Alertes en erreur » se coupait en
            « ALERTES EN ERRE… » à 390 px. Un libellé nomme le chiffre juste
            en dessous — il s'écrit en entier, quitte à passer sur deux lignes. */}
        <span className={cn(T.etiquette, "leading-tight")}>{label}</span>
        {aide && (
          <span title={aide} className="ml-auto shrink-0 cursor-help text-muted-foreground/40">
            <Info className="h-3.5 w-3.5" />
          </span>
        )}
      </div>
      <div className={cn("mt-1.5", T.chiffre, TONS[ton].texte)}>{valeur}</div>
      {sub && <div className="mt-0.5 text-xs leading-snug text-muted-foreground">{sub}</div>}
      {pied && <div className="mt-2">{pied}</div>}
    </div>
  );
}

/** Grille de tuiles : deux colonnes sur téléphone, jamais une seule — une tuile
 *  pleine largeur transforme six chiffres en six écrans de défilement. */
export function GrilleTuiles({
  children, colonnes = 4, className,
}: {
  children: React.ReactNode;
  colonnes?: 3 | 4 | 5 | 6;
  className?: string;
}) {
  const lg = {
    3: "lg:grid-cols-3", 4: "lg:grid-cols-4", 5: "lg:grid-cols-5", 6: "lg:grid-cols-6",
  }[colonnes];
  return (
    <div className={cn("grid grid-cols-2 gap-2.5 sm:grid-cols-3 sm:gap-3", lg, className)}>
      {children}
    </div>
  );
}

export function Vide({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-[7rem] items-center justify-center rounded-xl border border-dashed border-border px-6 py-8 text-center text-[13px] text-muted-foreground">
      {children}
    </div>
  );
}

export function Note({ children }: { children: React.ReactNode }) {
  return (
    <p className="mt-3 flex items-start gap-1.5 text-xs leading-relaxed text-muted-foreground">
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      <span>{children}</span>
    </p>
  );
}

/** Bandeau d'explication — le paragraphe qui dit comment lire ce qui suit. */
export function Encart({ ton = "neutre", icone, children }: { ton?: Ton; icone?: React.ReactNode; children: React.ReactNode }) {
  const t = TONS[ton];
  return (
    <div className={cn("flex items-start gap-2 rounded-xl border p-3 text-[13px] leading-relaxed", t.bord, t.fond, ton === "neutre" ? "text-muted-foreground" : t.texte)}>
      {icone && <span className="mt-0.5 shrink-0">{icone}</span>}
      <div className="min-w-0">{children}</div>
    </div>
  );
}

/**
 * Zone à défilement horizontal — pour un tableau qu'on ne peut pas honnêtement
 * réduire (dix colonnes de mesures qui se comparent entre elles).
 *
 * Trois choses que l'ancienne version n'avait pas : un dégradé sur le bord droit
 * qui SIGNALE qu'il reste du contenu, un `tabIndex` pour que le défilement soit
 * atteignable au clavier (WCAG 2.1.1), et une bordure qui donne au bloc un
 * début et une fin. Le débord `-mx-*` reste : coller le tableau aux marges du
 * panneau gagne 32 px de largeur utile sur téléphone.
 */
export function DefilementX({
  children, label, className, bleed = true,
}: {
  children: React.ReactNode;
  /** Ce que le tableau contient — annoncé aux lecteurs d'écran. */
  label: string;
  className?: string;
  /** Débord jusqu'aux marges du panneau. À couper quand la zone est déjà
   *  encadrée par ailleurs (fiche compte), sinon le tableau déborde du cadre. */
  bleed?: boolean;
}) {
  return (
    <div className={cn("relative", bleed && "-mx-4 sm:-mx-5", className)}>
      <div
        role="region"
        aria-label={label}
        tabIndex={0}
        className={cn(
          "overflow-x-auto overscroll-x-contain focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
          bleed && "px-4 sm:px-5",
        )}
      >
        {children}
      </div>
      <div
        aria-hidden
        className="pointer-events-none absolute inset-y-0 right-0 w-8 bg-gradient-to-l from-card to-transparent sm:hidden"
      />
    </div>
  );
}

/** En-tête de tableau — une seule définition, sinon chaque page réinvente la sienne. */
export const TH = "whitespace-nowrap px-2 py-2 text-left text-[11px] font-semibold uppercase tracking-[0.04em] text-muted-foreground";
export const TD = "px-2 py-2.5 align-middle text-[13px]";

/**
 * Le même contenu, deux fois : cartes sous `md`, tableau au-dessus.
 *
 * Un tableau à huit colonnes n'a pas de version mobile honnête — le réduire à
 * deux colonnes efface la comparaison qui justifie le tableau. On rend donc
 * l'information sous une autre FORME plutôt que la même en plus petit.
 */
export function CartesOuTableau({
  cartes, tableau,
}: {
  cartes: React.ReactNode;
  tableau: React.ReactNode;
}) {
  return (
    <>
      <div className="space-y-2 md:hidden">{cartes}</div>
      <div className="hidden md:block">{tableau}</div>
    </>
  );
}

/** Ligne clé/valeur d'une carte mobile. */
export function Champ({ label, children, className }: { label: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-baseline justify-between gap-3 text-[13px]", className)}>
      <span className="shrink-0 text-xs text-muted-foreground">{label}</span>
      <span className="min-w-0 truncate text-right font-medium tabular-nums">{children}</span>
    </div>
  );
}

/** Carte d'une liste mobile — surface, bord, respiration identiques partout. */
export function Carte({
  ton = "neutre", className, children, ...rest
}: React.HTMLAttributes<HTMLDivElement> & { ton?: Ton }) {
  return (
    <div
      className={cn(
        "rounded-xl border bg-card p-3",
        ton === "alerte" ? "border-red-200 bg-red-50/40"
          : ton === "attention" ? "border-amber-200 bg-amber-50/40"
          : ton === "ok" ? "border-emerald-200 bg-emerald-50/30"
          : "border-border",
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

/** Bascule « afficher tout / réduire » pour ne pas dérouler 40 lignes d'office. */
export function VoirPlus({
  total, montres, tout, onToggle,
}: {
  total: number;
  montres: number;
  tout: boolean;
  onToggle: () => void;
}) {
  if (total <= montres) return null;
  return (
    <button
      type="button"
      onClick={onToggle}
      className="mt-3 flex min-h-[2.75rem] w-full items-center justify-center rounded-xl border border-dashed border-border text-[13px] font-semibold text-muted-foreground transition-colors hover:border-brand-gold/50 hover:text-brand-gold-dark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {tout ? "Réduire la liste" : `Afficher les ${total - montres} restants`}
    </button>
  );
}

/**
 * Navigation par segments (sous-onglets).
 *
 * Défilement horizontal avec accrochage : six onglets ne tiennent pas sur
 * 390 px, et les tasser en 10 px les rendrait illisibles avant de les rendre
 * intouchables. Chaque segment fait 40 px de haut — la cible tactile minimale.
 */
export function Segments<K extends string>({
  items, actif, onChange, className, taille = "normal",
}: {
  items: ReadonlyArray<{ key: K; label: string; badge?: number }>;
  actif: K;
  onChange: (k: K) => void;
  className?: string;
  taille?: "normal" | "compact";
}) {
  return (
    <div
      role="tablist"
      className={cn(
        "flex snap-x gap-1 overflow-x-auto rounded-xl border border-border bg-card p-1 shadow-sm [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
        className,
      )}
    >
      {items.map((t) => {
        const on = t.key === actif;
        return (
          <button
            key={t.key}
            role="tab"
            aria-selected={on}
            onClick={() => onChange(t.key)}
            className={cn(
              "flex shrink-0 snap-start items-center gap-1.5 whitespace-nowrap rounded-lg px-3 font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              taille === "compact" ? "min-h-[2.25rem] text-xs" : "min-h-[2.5rem] text-[13px]",
              on
                ? "bg-foreground text-background"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            {t.label}
            {t.badge != null && t.badge > 0 && (
              <span
                className={cn(
                  "inline-flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-bold tabular-nums",
                  on ? "bg-background/20 text-background" : "bg-destructive/10 text-destructive",
                )}
              >
                {t.badge > 99 ? "99+" : t.badge}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/** Squelette de chargement — jamais un écran blanc, jamais un « 0 » inventé. */
export function Squelette({ lignes = 3, className }: { lignes?: number; className?: string }) {
  return (
    <div className={cn("space-y-2", className)} aria-busy="true" aria-live="polite">
      {Array.from({ length: lignes }).map((_, i) => (
        <div key={i} className="h-4 animate-pulse rounded bg-muted" style={{ width: `${100 - i * 12}%` }} />
      ))}
      <span className="sr-only">Chargement en cours</span>
    </div>
  );
}

/** Barre horizontale de polarité, pour lire un ROI sans lire le chiffre. */
export function BarrePolarite({ value, max }: { value: number | null; max: number }) {
  if (value == null || !isFinite(value) || max <= 0) {
    return <div className="h-1.5 w-full rounded-full bg-muted" />;
  }
  const frac = Math.min(Math.abs(value) / max, 1) * 50;
  return (
    <div className="relative h-1.5 w-full rounded-full bg-muted">
      <div className="absolute inset-y-0 left-1/2 w-px bg-border" />
      <div
        className="absolute inset-y-0 rounded-full"
        style={{
          left: value >= 0 ? "50%" : `${50 - frac}%`,
          width: `${frac}%`,
          background: value >= 0 ? "#059669" : "#EF4444",
        }}
      />
    </div>
  );
}

export const DIVERGING_POS = "#059669";
export const DIVERGING_NEG = "#EF4444";
