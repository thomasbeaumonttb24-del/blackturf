/**
 * Briques partagées du Défi du mois (page /defi, carte de la page course, admin).
 */
import { CheckCircle2, Clock, RotateCcw, Sparkles, User, XCircle } from "lucide-react";
import type { DefiPari } from "@/lib/api";
import { cn } from "@/lib/utils";

export const DEFI_REGLES_DEFAUT = {
  capital_mensuel: 1000,
  points_min: 10,
  points_max: 100,
  min_paris_classement: 10,
  max_paris_par_course: 3,
  verrou_minutes: 2,
  recompenses: [
    { rang: 1, plan: "expert", jours: 30 },
    { rang: 2, plan: "standard", jours: 30 },
    { rang: 3, plan: "standard", jours: 30 },
  ],
};

export const TYPES_DEFI = [
  { type: "Simple Gagnant", nb: 1, aide: "Votre cheval termine 1er" },
  { type: "Simple Placé", nb: 1, aide: "Votre cheval termine dans les places payées" },
  { type: "Couplé Gagnant", nb: 2, aide: "Vos 2 chevaux font les 2 premiers, dans n'importe quel ordre" },
  { type: "Couplé Placé", nb: 2, aide: "Vos 2 chevaux sont tous les deux placés" },
] as const;

export function formatPts(v: number | null | undefined, signe = false): string {
  if (v == null) return "—";
  const n = Math.round(v * 10) / 10;
  const txt = n.toLocaleString("fr-FR", { maximumFractionDigits: 1 });
  return `${signe && n > 0 ? "+" : ""}${txt} pts`;
}

export function moisLabel(mois: string): string {
  const [a, m] = mois.split("-").map(Number);
  if (!a || !m) return mois;
  const d = new Date(Date.UTC(a, m - 1, 15));
  const txt = d.toLocaleDateString("fr-FR", { month: "long", year: "numeric", timeZone: "UTC" });
  return txt.charAt(0).toUpperCase() + txt.slice(1);
}

export function planLabel(plan: string): string {
  return plan === "expert" ? "Expert" : plan === "standard" ? "Standard" : plan;
}

/** Ce que le pari a rapporté au solde : retour − mise, ou la mise engagée en attente. */
export function netPari(p: DefiPari): number | null {
  if (p.statut === "en_attente") return null;
  return (p.points_retour ?? 0) - p.points;
}

export function StatutPari({ statut }: { statut: DefiPari["statut"] }) {
  const s = {
    gagne: { txt: "Gagné", cls: "bg-emerald-50 text-emerald-700 ring-emerald-200", Icone: CheckCircle2 },
    perd: { txt: "Perdu", cls: "bg-rose-50 text-rose-700 ring-rose-200", Icone: XCircle },
    rembourse: { txt: "Remboursé", cls: "bg-stone-100 text-stone-600 ring-stone-200", Icone: RotateCcw },
    en_attente: { txt: "En attente", cls: "bg-sky-50 text-sky-700 ring-sky-200", Icone: Clock },
  }[statut];
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset", s.cls)}>
      <s.Icone className="h-3 w-3" aria-hidden="true" />
      {s.txt}
    </span>
  );
}

export function OriginePari({ origine }: { origine: DefiPari["origine"] }) {
  return origine === "plan" ? (
    <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-800 ring-1 ring-inset ring-amber-200">
      <Sparkles className="h-3 w-3" aria-hidden="true" /> Plan BlackTurf
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 rounded-full bg-stone-100 px-2 py-0.5 text-[11px] font-semibold text-stone-700 ring-1 ring-inset ring-stone-200">
      <User className="h-3 w-3" aria-hidden="true" /> Perso
    </span>
  );
}

export function ResultatPari({ p }: { p: DefiPari }) {
  const net = netPari(p);
  if (net == null) return <span className="text-[12px] text-slate-500 tabular-nums">{p.points} pts engagés</span>;
  return (
    <span className={cn("font-display text-[14px] font-bold tabular-nums",
      net > 0 ? "text-emerald-700" : net < 0 ? "text-rose-700" : "text-slate-600")}>
      {formatPts(net, true)}
      {p.statut === "gagne" && p.rapport != null && (
        <span className="ml-1 text-[11px] font-medium text-slate-500">({p.points} × {p.rapport.toLocaleString("fr-FR")})</span>
      )}
    </span>
  );
}
