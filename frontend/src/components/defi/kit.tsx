/**
 * Briques partagées du Défi du mois (page /defi, carte de la page course, admin).
 */
import { CheckCircle2, Clock, Crown, RotateCcw, Sparkles, Timer, User, XCircle } from "lucide-react";
import { DecorRayons, LaurierSvg, MedailleSvg } from "@/components/defi/illustrations";
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

/** Nombre à la française avec une espace insécable classique comme séparateur des
 *  milliers : l'espace fine (U+202F) que produit `toLocaleString` n'existe pas dans
 *  toutes les polices, et « 1 000 » s'y affichait « 1000 ». */
export function formatNombre(n: number, decimales = 1): string {
  return n.toLocaleString("fr-FR", { maximumFractionDigits: decimales }).replace(/\u202f/g, "\u00a0");
}

export function formatPts(v: number | null | undefined, signe = false): string {
  if (v == null) return "—";
  const n = Math.round(v * 10) / 10;
  const txt = formatNombre(n);
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
        <span className="ml-1 text-[11px] font-medium text-slate-500">({p.points} × {formatNombre(p.rapport, 2)})</span>
      )}
    </span>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Identité visuelle du défi : en-tête champagne à décor doré, médaille, podium
// métallique en relief, lignes de classement. Tous les modules du défi (accueil,
// résultats, course, tableau de bord, /defi) partagent ces briques pour se
// reconnaître au premier coup d'œil — dans les tons clairs du site.
// ─────────────────────────────────────────────────────────────────────────────

/** Fond de l'en-tête : champagne chaud, du crème à l'or pâle. */
export const DEFI_FOND =
  "bg-[linear-gradient(135deg,#FFFDF7_0%,#FEF6E4_42%,#FBE8C0_100%)]";

/** Carte du défi : blanc, liseré or, ombre douce et reflet intérieur. */
export const DEFI_CARTE =
  "overflow-hidden rounded-3xl bg-white ring-1 ring-amber-900/10 shadow-[inset_0_1px_0_#fff,0_1px_2px_rgba(120,53,15,.06),0_28px_56px_-40px_rgba(120,53,15,.55)]";

/** Bouton d'action principal du défi : or en relief. */
export const BOUTON_OR =
  "inline-flex min-h-[40px] items-center justify-center gap-1.5 rounded-xl bg-gradient-to-b from-amber-500 to-amber-700 px-4 text-[12.5px] font-bold text-white shadow-[inset_0_1px_0_rgba(255,255,255,.35),0_8px_18px_-10px_rgba(180,83,9,.9)] transition-[filter,transform] hover:brightness-105 active:translate-y-px";

/** Emblème : médaille or à ruban (SVG). */
export function DefiEmbleme({ taille = 40 }: { taille?: number }) {
  return <MedailleSvg taille={taille} />;
}

/** Pastille « En direct ». */
export function PastilleDirect() {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-white/90 px-2 py-0.5 text-[10.5px] font-semibold text-emerald-700 shadow-sm ring-1 ring-inset ring-emerald-200">
      <span className="relative flex h-1.5 w-1.5" aria-hidden="true">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
      </span>
      En direct
    </span>
  );
}

/** Jours restants jusqu'à la fin du mois du défi (calendrier de Paris, arrondi au jour). */
export function joursRestants(mois: string): number {
  const [a, m] = mois.split("-").map(Number);
  if (!a || !m) return 0;
  return Math.max(0, Math.ceil((Date.UTC(a, m, 1) - Date.now()) / 86_400_000));
}

/** Compte à rebours de fin de mois, en pastille. */
export function CompteRebours({ mois }: { mois: string; sombre?: boolean }) {
  const j = joursRestants(mois);
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-white/90 px-2 py-0.5 text-[10.5px] font-semibold tabular-nums text-amber-900 shadow-sm ring-1 ring-inset ring-amber-200">
      <Timer className="h-3 w-3 text-amber-600" aria-hidden="true" />
      {j <= 1 ? "Dernier jour" : `J-${j}`}
    </span>
  );
}

/** En-tête commun des modules. `droite` : pastilles, solde… */
export function DefiEntete({ surtitre, titre, sousTitre, droite, compact = false, children }: {
  surtitre?: string;
  titre: string;
  sousTitre?: React.ReactNode;
  droite?: React.ReactNode;
  compact?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <div className={cn(DEFI_FOND, "relative isolate overflow-hidden border-b border-amber-900/10", compact ? "px-4 pb-4 pt-4" : "px-5 pb-5 pt-5")}>
      <DecorRayons className="-z-10" />
      <div className="flex items-start gap-3">
        <DefiEmbleme taille={compact ? 40 : 46} />
        <div className="min-w-0 flex-1 pt-0.5">
          {surtitre && <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-amber-700">{surtitre}</div>}
          <h2 className={cn("font-display font-bold leading-tight text-slate-900", compact ? "text-[15.5px]" : "text-[18px]")}>{titre}</h2>
          {sousTitre && <p className="mt-0.5 text-[11.5px] leading-snug text-slate-600">{sousTitre}</p>}
        </div>
        {droite && <div className="flex shrink-0 flex-col items-end gap-1.5">{droite}</div>}
      </div>
      {children}
    </div>
  );
}

const TEINTES_AVATAR = [
  "from-amber-100 to-amber-300 text-amber-950",
  "from-emerald-100 to-emerald-300 text-emerald-950",
  "from-sky-100 to-sky-300 text-sky-950",
  "from-rose-100 to-rose-300 text-rose-950",
  "from-violet-100 to-violet-300 text-violet-950",
  "from-stone-100 to-stone-300 text-stone-900",
];

/** Avatar à initiales, teinte stable par pseudo. */
export function Avatar({ nom, taille = 32, className }: { nom: string; taille?: number; className?: string }) {
  let h = 0;
  for (let i = 0; i < nom.length; i++) h = (h * 31 + nom.charCodeAt(i)) >>> 0;
  const initiales = nom.replace(/[^A-Za-zÀ-ÿ0-9]/g, "").slice(0, 2).toUpperCase() || "?";
  return (
    <span
      className={cn("inline-flex shrink-0 items-center justify-center rounded-full bg-gradient-to-b font-bold shadow-[inset_0_1px_0_rgba(255,255,255,.8)] ring-2 ring-white", TEINTES_AVATAR[h % TEINTES_AVATAR.length], className)}
      style={{ width: taille, height: taille, fontSize: Math.round(taille * 0.36) }}
      aria-hidden="true"
    >
      {initiales}
    </span>
  );
}

/** Finitions métalliques des trois marches. */
const METAL: Record<1 | 2 | 3, { face: string; dessus: string; bague: string; texte: string; h: number; libelle: string }> = {
  1: { face: "from-[#FCD66B] via-[#F2B53A] to-[#C9861A]", dessus: "#FDE9A6", bague: "ring-[#F2B53A]", texte: "text-[#7A4A06]", h: 78, libelle: "1" },
  2: { face: "from-[#F1F4F8] via-[#D5DBE3] to-[#A9B3C1]", dessus: "#F8FAFC", bague: "ring-[#C3CAD4]", texte: "text-slate-600", h: 56, libelle: "2" },
  3: { face: "from-[#F7D2B0] via-[#E1A06C] to-[#B8733E]", dessus: "#FBE3CC", bague: "ring-[#E1A06C]", texte: "text-[#6B3B14]", h: 42, libelle: "3" },
};

type LignePodium = { nom: string; solde: number; moi?: boolean } | undefined;

/** Podium 2-1-3 en relief : marches métalliques or / argent / bronze, laurier au 1er. */
export function Podium({ lignes, compact = false }: { lignes: LignePodium[]; compact?: boolean }) {
  const ordre: (1 | 2 | 3)[] = [2, 1, 3];
  return (
    <ol className="mt-5 grid grid-cols-3 items-end gap-2.5 sm:gap-4" aria-label="Podium du mois">
      {ordre.map((rang) => {
        const l = lignes[rang - 1];
        const m = METAL[rang];
        const tailleAvatar = rang === 1 ? (compact ? 42 : 52) : compact ? 34 : 42;
        return (
          <li key={rang} className="flex min-w-0 flex-col items-center text-center">
            {l ? (
              <>
                <span className="relative inline-flex items-center justify-center">
                  {rang === 1 && <LaurierSvg className="absolute -bottom-2 left-1/2 w-[200%] -translate-x-1/2" />}
                  {rang === 1 && <Crown className="absolute -top-4 left-1/2 h-4 w-4 -translate-x-1/2 fill-amber-400 text-amber-600" aria-hidden="true" />}
                  <Avatar nom={l.nom} taille={tailleAvatar} className={cn("relative ring-[3px]", m.bague)} />
                </span>
                <span className={cn("mt-2 w-full truncate text-[12.5px] font-bold", l.moi ? "text-amber-800" : "text-slate-900")}>
                  {l.nom}{l.moi && <span className="font-semibold"> (vous)</span>}
                </span>
                <span className="font-display text-[13px] font-bold tabular-nums text-amber-800">{formatPts(l.solde)}</span>
              </>
            ) : (
              <>
                <span className="inline-flex items-center justify-center rounded-full border-2 border-dashed border-amber-300/80 bg-white/60 text-[14px] font-bold text-amber-400"
                  style={{ width: tailleAvatar, height: tailleAvatar }} aria-hidden="true">?</span>
                <span className="mt-2 text-[12px] font-semibold text-slate-500">À prendre</span>
                <span className="text-[13px] text-transparent" aria-hidden="true">.</span>
              </>
            )}
            {/* Marche : dessus clair en perspective + face métallique. */}
            <div className="mt-2.5 w-full" style={{ perspective: 400 }}>
              <div className="mx-1 h-2.5 rounded-t-md" style={{ background: m.dessus, transform: "rotateX(55deg)", transformOrigin: "bottom" }} />
              <div className={cn("flex w-full items-start justify-center rounded-b-lg rounded-t-sm bg-gradient-to-b pt-2 shadow-[inset_0_1px_0_rgba(255,255,255,.7),inset_0_-8px_16px_-10px_rgba(0,0,0,.25),0_10px_18px_-12px_rgba(120,53,15,.6)]", m.face)}
                style={{ height: compact ? Math.round(m.h * 0.75) : m.h }}>
                <span className={cn("font-display text-[22px] font-bold leading-none drop-shadow-[0_1px_0_rgba(255,255,255,.6)]", m.texte)}>{m.libelle}</span>
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/** Ligne de classement : rang, avatar, pseudo, solde, barre relative au leader. */
export function LigneClassement({ rang, nom, solde, nbParis, moi, max, detail }: {
  rang: number | null;
  nom: string;
  solde: number;
  nbParis: number;
  moi?: boolean;
  /** Solde du leader : la barre montre l'écart. */
  max: number;
  detail?: React.ReactNode;
}) {
  const pct = max > 0 ? Math.max(4, Math.min(100, (solde / max) * 100)) : 0;
  return (
    <li className={cn("relative flex items-center gap-3 px-4 py-3", moi && "bg-gradient-to-r from-amber-50 to-transparent")}>
      {moi && <span className="absolute inset-y-1.5 left-0 w-1 rounded-r-full bg-amber-500" aria-hidden="true" />}
      <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-stone-100 font-display text-[12.5px] font-bold tabular-nums text-slate-600 ring-1 ring-inset ring-stone-200">
        {rang ?? "–"}
      </span>
      <Avatar nom={nom} taille={32} />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate text-[13px] font-semibold text-slate-900">
            {nom}{moi && <span className="ml-1 text-[11px] font-semibold text-amber-700">(vous)</span>}
          </span>
          <span className="shrink-0 font-display text-[13.5px] font-bold tabular-nums text-slate-900">{formatPts(solde)}</span>
        </div>
        <div className="mt-1.5 flex items-center gap-2">
          <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-stone-100">
            <span className={cn("block h-full rounded-full bg-gradient-to-r", moi ? "from-amber-400 to-amber-600" : "from-stone-300 to-stone-400")} style={{ width: `${pct}%` }} />
          </span>
          <span className="shrink-0 text-[10.5px] tabular-nums text-slate-500">{detail ?? `${nbParis} paris`}</span>
        </div>
      </div>
    </li>
  );
}
