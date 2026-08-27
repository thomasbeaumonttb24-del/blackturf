"use client";

/**
 * Briques d'interface du back-office.
 *
 * Règle de cette page : une section longue (historique des modèles, scrapers,
 * erreurs) se replie. L'en-tête doit rester lisible replié — il porte donc un
 * résumé chiffré, sinon replier revient à cacher l'information.
 */

import * as React from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

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

export function AdminSection({
  id, titre, sousTitre, icone, resume, action, defaut = true, ton = "neutre",
  bodyClassName, children,
}: {
  /** Clé de mémorisation de l'état plié/déplié. */
  id: string;
  titre: string;
  sousTitre?: React.ReactNode;
  icone?: React.ReactNode;
  /** Chiffres visibles même section repliée. */
  resume?: React.ReactNode;
  /** Contrôles (recherche, export…) — ne replie pas la section au clic. */
  action?: React.ReactNode;
  defaut?: boolean;
  ton?: "neutre" | "alerte" | "or";
  bodyClassName?: string;
  children: React.ReactNode;
}) {
  const [ouvert, basculer] = useOuvert(id, defaut);
  return (
    <section
      className={cn(
        "overflow-hidden rounded-2xl border bg-card shadow-sm transition-colors",
        ton === "alerte" ? "border-destructive/30" : ton === "or" ? "border-brand-gold/30" : "border-border",
      )}
    >
      <div
        className={cn(
          "flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-3 sm:px-5 sm:py-4",
          ouvert && "border-b border-border/60",
        )}
      >
        <button
          type="button"
          onClick={basculer}
          aria-expanded={ouvert}
          className="group flex min-w-0 flex-1 items-center gap-2.5 text-left"
        >
          <span
            className={cn(
              "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
              ton === "alerte" ? "bg-destructive/10 text-destructive"
                : ton === "or" ? "bg-brand-gold/10 text-brand-gold-dark"
                : "bg-muted text-muted-foreground",
            )}
          >
            {icone}
          </span>
          {/* Aucun `truncate` ici : à 390 px, « Erreurs récentes » se coupait en
              « Erreurs réc… » et son sous-titre en « Exceptions API et sc… ». Un
              en-tête qui porte le résumé d'une section repliée doit se lire en
              entier — il passe sur deux lignes plutôt que de perdre ses mots. */}
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-2">
              <span className="text-sm font-bold leading-tight sm:text-base">{titre}</span>
              <ChevronDown
                className={cn(
                  "h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200 group-hover:text-foreground",
                  ouvert && "rotate-180",
                )}
              />
            </span>
            {sousTitre && (
              <span className="mt-0.5 block text-[11px] leading-tight text-muted-foreground">
                {sousTitre}
              </span>
            )}
          </span>
        </button>
        {resume && <div className="flex shrink-0 flex-wrap items-center gap-1.5">{resume}</div>}
        {action && <div className="w-full shrink-0 sm:w-auto">{action}</div>}
      </div>
      {ouvert && <div className={cn("p-3 sm:p-5", bodyClassName)}>{children}</div>}
    </section>
  );
}

/** Pastille de résumé, lisible section repliée. */
export function Puce({
  children, ton = "neutre", titre,
}: {
  children: React.ReactNode;
  ton?: "neutre" | "ok" | "alerte" | "attention";
  titre?: string;
}) {
  return (
    <span
      title={titre}
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-semibold tabular-nums",
        ton === "ok" ? "border-emerald-200 bg-emerald-50 text-emerald-700"
          : ton === "alerte" ? "border-red-200 bg-red-50 text-red-700"
          : ton === "attention" ? "border-amber-200 bg-amber-50 text-amber-700"
          : "border-border bg-muted/50 text-muted-foreground",
      )}
    >
      {children}
    </span>
  );
}

/** Tuile de chiffre. Le ton colore la valeur, jamais tout le bloc. */
export function Tuile({
  label, valeur, sub, ton = "neutre", icone, className,
}: {
  label: React.ReactNode;
  valeur: React.ReactNode;
  sub?: React.ReactNode;
  ton?: "neutre" | "ok" | "alerte" | "attention";
  icone?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border border-border/70 bg-muted/20 p-3 transition-colors hover:border-border",
        ton === "alerte" && "border-red-200 bg-red-50/50",
        ton === "attention" && "border-amber-200 bg-amber-50/50",
        className,
      )}
    >
      <div className="flex items-center gap-1.5">
        {icone && <span className="shrink-0 text-muted-foreground">{icone}</span>}
        <span className="text-[10px] font-semibold uppercase leading-tight tracking-wide text-muted-foreground sm:text-[11px]">
          {label}
        </span>
      </div>
      <div
        className={cn(
          "mt-1 text-lg font-bold tabular-nums sm:text-xl",
          ton === "ok" && "text-emerald-700",
          ton === "alerte" && "text-destructive",
          ton === "attention" && "text-amber-700",
        )}
      >
        {valeur}
      </div>
      {sub && <div className="mt-0.5 text-[10px] text-muted-foreground sm:text-[11px]">{sub}</div>}
    </div>
  );
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
  const j = Math.floor(h / 24);
  return `il y a ${j} j`;
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
      className="mt-2 w-full rounded-lg border border-dashed border-border py-2 text-xs font-semibold text-muted-foreground transition-colors hover:border-brand-gold/50 hover:text-brand-gold-dark"
    >
      {tout ? "Réduire la liste" : `Afficher les ${total - montres} restants`}
    </button>
  );
}
