"use client";

import { useEffect, useState, useRef } from "react";
import { useParams } from "next/navigation";
import {
  ArrowLeft, Brain, Loader2, TrendingUp, AlertTriangle, Cloud,
  Calculator, ChevronRight, Star, Zap, Info, BarChart2,
  RefreshCw, ShieldAlert, Newspaper, TrendingDown, Activity,
} from "lucide-react";
import Link from "next/link";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from "recharts";
import { CHART_PALETTE, axisTick, axisLine, tickLine, GRID, ChartTooltip } from "@/components/charts/chart-kit";
import { coursesApi, predictionsApi, api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/hooks/useAuth";
import { useCotesLive } from "@/hooks/useWebSocket";
import { formatCote, formatEV, etoiles, disciplineIcon, formatDateTime, cn } from "@/lib/utils";
import { toast } from "sonner";

// ─── Types ───────────────────────────────────────────────────────────────────
interface Partant {
  participation_id: string;
  numero: number;
  nom_cheval: string;
  age: number | null;
  sexe: string | null;
  jockey: string | null;
  entraineur: string | null;
  // Cotes multi-sources
  cote_pmu: number | null;
  cote_geny: number | null;
  cote_winamax: number | null;
  cote_betclic: number | null;
  cote_betclic_ouverture: number | null;
  cote_unibet: number | null;
  cote_betfair_exchange: number | null;
  cote_min: number | null;
  cote_max: number | null;
  nb_sources: number;
  mouvement_cote_pct: number | null;  // positif = cote baissée = signal
  // Données partant
  musique: string | null;
  non_partant: boolean;
  elo_global: number | null;
  // Équipement
  deferre: string | null;
  oeilleres: string | null;
  premier_deferre: boolean;
  premieres_oeilleres: boolean;
  // Nouvelles données
  running_style: string | null;
  changement_jockey: boolean;
  jours_depuis_derniere: number | null;
  poids_reel_pesee: number | null;
  pere: string | null;
  mere: string | null;
  pere_de_mere: string | null;
  prix_vente_yearling: number | null;
  asso_jockey_entraineur_taux: number | null;
  asso_jockey_entraineur_nb: number | null;
  jockey_suspendu: boolean;
  entraineur_suspendu: boolean;
}

interface Prediction {
  prediction_id: string;
  participation_id: string;
  numero: number;
  nom_cheval: string;
  proba_top1: number;
  proba_top3: number;
  rang_predit: number;
  confidence_score: number | null;
  cote_pmu: number | null;
  cote_juste: number | null;
  value_bet: { ev_max: number; niveau: number; meilleure_source: string } | null;
}

interface CourseData {
  course_id: string;
  nom: string | null;
  discipline: string;
  distance: number;
  hippodrome_nom: string;
  date_heure: string;
  terrain_officiel: string | null;
  nb_partants: number;
  allocation: number | null;
  niveau_course: string | null;
  est_quinte: boolean;
  est_quarte: boolean;
  est_tierce: boolean;
  statut: string;
  // Nouvelles données
  penetrometre_coef: number | null;
  penetrometre_desc: string | null;
  pool_total_eur: number | null;
  pool_gagnant_eur: number | null;
  pool_gagnant_evolution: number | null;
  avantage_couloir: string | null;
  conditions_texte: string | null;
  categorie_particularite: string | null;
  montant_offert_1er: number | null;
  nombre_declares_partants: number | null;
  meteo: { terrain_officiel: string | null; temperature: number | null; pluie_24h: number | null } | null;
  pronostics_presse: Array<{
    source: string;
    journaliste: string | null;
    selection: Array<{ rang: number; numero: number; nom: string }>;
    commentaire: string | null;
  }>;
  partants: Partant[];
}

interface PariRec {
  type: string;
  chevaux: { numero: number; nom: string }[];
  mise: number;
  gain_potentiel: number;
  probabilite: number;
  description: string;
}

interface NiveauPlan {
  niveau: string;
  label: string;
  emoji: string;
  couleur: string;
  montant: number;
  pct: number;
  paris: PariRec[];
}

interface MisePlan {
  montant_total: number;
  montant_joue: number;
  montant_reserve: number;
  ev_global: number;
  kelly_warning: boolean;
  resume_ia: string;
  avertissement: string;
  niveaux: NiveauPlan[];
}

// ─── Sub-components ───────────────────────────────────────────────────────────
function ConfidenceMeter({ score, size = "md" }: { score: number; size?: "sm" | "md" }) {
  const pct = Math.round(score * 100);
  const color = pct >= 70 ? "#10B981" : pct >= 50 ? "#F59E0B" : "#EF4444";
  return (
    <div className={cn("flex items-center gap-2", size === "sm" && "text-xs")}>
      <div className={cn("rounded-full bg-muted/50 overflow-hidden", size === "md" ? "h-2 w-24" : "h-1.5 w-16")}>
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      <span className="font-mono font-bold tabular-nums" style={{ color, fontSize: size === "sm" ? 10 : 12 }}>
        {pct}
      </span>
    </div>
  );
}

function EVBadge({ ev }: { ev: number }) {
  const pct = (ev * 100).toFixed(0);
  const positive = ev > 0;
  return (
    <span className={cn(
      "inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-bold font-mono",
      positive ? "bg-brand-emerald/15 text-brand-emerald" : "bg-brand-red/15 text-brand-red"
    )}>
      {positive ? "+" : ""}{pct}%
    </span>
  );
}

function ELOBadge({ elo }: { elo: number | null }) {
  if (!elo) return <span className="text-muted-foreground text-xs">—</span>;
  const tier = elo >= 1700 ? "#F59E0B" : elo >= 1500 ? "#3B82F6" : elo >= 1300 ? "#10B981" : "#6B7280";
  return (
    <span className="font-mono font-bold text-xs tabular-nums" style={{ color: tier }}>
      {Math.round(elo)}
    </span>
  );
}

function PlanMiseDisplay({ plan, onClose }: { plan: MisePlan; onClose: () => void }) {
  return (
    <div className="animate-slide-up">
      {/* Header résumé */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <p className="text-xs text-muted-foreground">Plan pour</p>
          <p className="text-2xl font-bold tabular-nums text-brand-gold">{plan.montant_total}€</p>
        </div>
        <div className="text-right">
          <p className="text-xs text-muted-foreground">Espérance globale estimée</p>
          <p className={cn(
            "text-xl font-bold tabular-nums",
            plan.ev_global > 0 ? "text-brand-emerald" : "text-brand-red"
          )}>
            {plan.ev_global > 0 ? "+" : ""}{(plan.ev_global * 100).toFixed(1)}%
          </p>
        </div>
      </div>

      {/* Explication espérance */}
      <details className="mb-4 rounded-lg border border-border bg-muted/20 px-3 py-2 text-xs group">
        <summary className="cursor-pointer font-semibold text-muted-foreground flex items-center gap-1.5 list-none">
          <span className="text-brand-gold">ⓘ</span> C&apos;est quoi l&apos;espérance ?
        </summary>
        <div className="mt-2 space-y-1.5 text-muted-foreground leading-relaxed">
          <p>
            L&apos;<strong>espérance</strong> = le gain (ou la perte) moyen attendu pour 1€ misé,
            si tu rejouais ce type de plan un très grand nombre de fois.
          </p>
          <p>
            <strong className="text-brand-emerald">Positif</strong> = avantage : en moyenne le plan
            rapporte. <strong className="text-brand-red">Négatif</strong> = perte moyenne.
          </p>
          <p>
            Au PMU, le pari mutuel prélève ~15 à 25% des mises : une espérance légèrement négative
            est <strong>normale</strong>. Plus elle est proche de 0% (ou positive), meilleure est la sélection.
            L&apos;analyse BlackTurf vise à la maximiser, sans jamais garantir un gain.
          </p>
        </div>
      </details>

      {/* Résumé IA */}
      <div className="rounded-lg border border-brand-gold/20 bg-brand-gold/5 p-3 mb-4 text-sm leading-relaxed">
        <p className="text-muted-foreground text-xs font-semibold mb-1">💬 Analyse BlackTurf</p>
        {plan.resume_ia}
        <p className="mt-2 text-[11px] text-muted-foreground/70">
          Mises réparties par simulation (Plackett-Luce) sur les probabilités du modèle : forme,
          cotes, ELO, terrain, distance, jockey/entraîneur et historique de chaque cheval.
        </p>
      </div>

      {/* Niveaux */}
      <div className="space-y-3">
        {plan.niveaux.map((niv) => (
          <div key={niv.niveau} className={cn(
            "rounded-lg p-3",
            niv.niveau === "securite" ? "plan-securite" :
            niv.niveau === "rendement" ? "plan-rendement" : "plan-coup"
          )}>
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span>{niv.emoji}</span>
                <span className="font-bold text-sm">{niv.label}</span>
                <Badge variant="secondary" className="text-[10px] px-1">{niv.pct}%</Badge>
              </div>
              <span className="font-mono font-bold tabular-nums" style={{ color: niv.couleur }}>
                {niv.montant.toFixed(2)}€
              </span>
            </div>
            <div className="space-y-1.5">
              {niv.paris.map((p, i) => (
                <div key={i} className="flex items-start justify-between gap-2 text-xs">
                  <div className="flex-1">
                    <span className="font-semibold">{p.type}</span>
                    <span className="text-muted-foreground ml-1">
                      {p.chevaux.map(c => `N°${c.numero}`).join(" + ")}
                    </span>
                    <span className="ml-2 text-muted-foreground/60">
                      Proba ~{(p.probabilite * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="text-right flex-shrink-0">
                    <div className="font-mono font-bold">{p.mise.toFixed(2)}€</div>
                    <div className="text-brand-emerald font-mono">→ ~{p.gain_potentiel.toFixed(0)}€</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Résumé totaux */}
      <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
        <div className="rounded bg-muted/30 p-2">
          <div className="text-muted-foreground">Misé</div>
          <div className="font-bold font-mono tabular-nums">{plan.montant_joue.toFixed(2)}€</div>
        </div>
        <div className="rounded bg-muted/30 p-2">
          <div className="text-muted-foreground">Réserve</div>
          <div className="font-bold font-mono tabular-nums text-brand-gold">{plan.montant_reserve.toFixed(2)}€</div>
        </div>
      </div>

      {plan.kelly_warning && (
        <div className="mt-3 rounded-lg border border-brand-red/30 bg-brand-red/5 p-2 text-xs text-brand-red flex gap-2">
          <AlertTriangle className="h-3 w-3 mt-0.5 flex-shrink-0" />
          {plan.avertissement}
        </div>
      )}

      <p className="mt-3 text-[10px] text-muted-foreground/60">{plan.avertissement}</p>

      <Button variant="ghost" size="sm" className="mt-2 w-full text-xs" onClick={onClose}>
        Modifier le montant
      </Button>
    </div>
  );
}

/* ─── Running style badge ────────────────────────────────────────────────── */
const RUNNING_STYLE_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  mene:      { label: "Mène",      color: "text-red-600",   bg: "bg-red-50 ring-red-200" },
  suit_tete: { label: "Suit tête", color: "text-orange-600", bg: "bg-orange-50 ring-orange-200" },
  placier:   { label: "Placier",   color: "text-blue-600",  bg: "bg-blue-50 ring-blue-200" },
  ferme:     { label: "Ferme",     color: "text-emerald-600", bg: "bg-emerald-50 ring-emerald-200" },
  irregulier:{ label: "Irrégulier", color: "text-gray-500", bg: "bg-gray-50 ring-gray-200" },
};
function RunningStyleBadge({ style }: { style: string | null }) {
  if (!style) return null;
  const cfg = RUNNING_STYLE_CONFIG[style] ?? RUNNING_STYLE_CONFIG.irregulier;
  return (
    <span className={cn("inline-flex items-center rounded-full px-1.5 py-0 text-[9px] font-semibold ring-1 uppercase tracking-wide", cfg.bg, cfg.color)}>
      {cfg.label}
    </span>
  );
}

/* ─── Pénétromètre badge ─────────────────────────────────────────────────── */
function PenetroBadge({ coef, desc }: { coef: number; desc: string }) {
  const color =
    coef < 3.0 ? "text-amber-700 bg-amber-50 ring-amber-200" :
    coef < 5.0 ? "text-green-700 bg-green-50 ring-green-200" :
    coef < 7.0 ? "text-blue-700 bg-blue-50 ring-blue-200" :
               "text-indigo-700 bg-indigo-50 ring-indigo-200";
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ring-1", color)}>
      🌿 {desc} ({coef.toFixed(1)})
    </span>
  );
}

/* ─── Pool badge ─────────────────────────────────────────────────────────── */
function PoolBadge({ poolEur }: { poolEur: number }) {
  const label =
    poolEur >= 1_000_000 ? `${(poolEur / 1_000_000).toFixed(1)}M€` :
    poolEur >= 1_000 ? `${Math.round(poolEur / 1_000)}k€` :
    `${poolEur}€`;
  return (
    <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold bg-violet-50 ring-1 ring-violet-200 text-violet-700">
      <Activity className="h-3 w-3" /> Pool {label}
    </span>
  );
}

/* ─── Cotes comparaison table ────────────────────────────────────────────── */
function ComparaisonCotes({ partants }: { partants: Partant[] }) {
  const actifs = partants.filter((p) => !p.non_partant);
  const sources = [
    { key: "cote_pmu",           label: "PMU",     accent: "text-blue-600" },
    { key: "cote_geny",          label: "Geny",    accent: "text-purple-600" },
    { key: "cote_winamax",       label: "Winamax", accent: "text-orange-600" },
    { key: "cote_betclic",       label: "Betclic", accent: "text-red-600" },
    { key: "cote_unibet",        label: "Unibet",  accent: "text-green-600" },
    { key: "cote_betfair_exchange", label: "Betfair", accent: "text-cyan-700" },
  ] as const;

  // Ne montrer que les sources qui ont ≥1 cote non-null
  const activeSources = sources.filter((s) =>
    actifs.some((p) => (p as unknown as Record<string, unknown>)[s.key] != null)
  );
  if (activeSources.length <= 1) return null;

  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-card">
      <table className="w-full text-xs min-w-[500px]">
        <thead>
          <tr className="border-b border-border/60 bg-muted/30">
            <th className="text-left px-3 py-2 font-medium text-muted-foreground">N° Cheval</th>
            {activeSources.map((s) => (
              <th key={s.key} className={cn("text-right px-3 py-2 font-bold", s.accent)}>
                {s.label}
              </th>
            ))}
            <th className="text-right px-3 py-2 font-medium text-muted-foreground">Min</th>
            <th className="text-right px-3 py-2 font-medium text-muted-foreground">Mouvement</th>
          </tr>
        </thead>
        <tbody>
          {actifs.map((p) => {
            const coteMin = p.cote_min;
            return (
              <tr key={p.participation_id} className="border-b border-border/30 hover:bg-accent/10">
                <td className="px-3 py-2 font-medium">
                  <span className="text-muted-foreground mr-1.5">{p.numero}</span>
                  {p.nom_cheval}
                </td>
                {activeSources.map((s) => {
                  const val = (p as unknown as Record<string, unknown>)[s.key] as number | null;
                  const isBest = val != null && coteMin != null && val === coteMin;
                  return (
                    <td key={s.key} className="px-3 py-2 text-right">
                      <span className={cn(
                        "font-mono font-semibold tabular-nums",
                        isBest ? "text-emerald-600" : "text-foreground",
                        !val && "text-muted-foreground/40",
                      )}>
                        {val ? val.toFixed(1) : "—"}
                      </span>
                    </td>
                  );
                })}
                <td className="px-3 py-2 text-right">
                  <span className="font-mono font-bold text-emerald-600 tabular-nums">
                    {coteMin ? coteMin.toFixed(1) : "—"}
                  </span>
                </td>
                <td className="px-3 py-2 text-right">
                  {p.mouvement_cote_pct != null ? (
                    <span className={cn(
                      "inline-flex items-center gap-0.5 font-mono font-semibold tabular-nums",
                      p.mouvement_cote_pct > 0 ? "text-emerald-600" : "text-red-500",
                    )}>
                      {p.mouvement_cote_pct > 0 ? (
                        <TrendingDown className="h-3 w-3" />
                      ) : (
                        <TrendingUp className="h-3 w-3" />
                      )}
                      {Math.abs(p.mouvement_cote_pct).toFixed(1)}%
                    </span>
                  ) : (
                    <span className="text-muted-foreground/40">—</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ─── Pronostics presse section ──────────────────────────────────────────── */
function PronosticsPresse({ pronostics }: {
  pronostics: Array<{ source: string; journaliste: string | null; selection: Array<{ rang: number; numero: number; nom: string }>; commentaire: string | null }>;
}) {
  if (!pronostics.length) return null;

  // Consensus : numéros sélectionnés par ≥ 2 experts
  const counts: Record<number, { nb: number; nom: string }> = {};
  pronostics.forEach((p) => {
    p.selection.slice(0, 4).forEach((s) => {
      if (!counts[s.numero]) counts[s.numero] = { nb: 0, nom: s.nom || "" };
      counts[s.numero].nb++;
    });
  });
  const consensus = Object.entries(counts)
    .filter(([, v]) => v.nb >= 2)
    .sort((a, b) => b[1].nb - a[1].nb)
    .slice(0, 5);

  const SOURCE_LABEL: Record<string, string> = {
    paris_turf: "Paris-Turf",
    canalturf: "CanalTurf",
    geny_expert: "Geny Expert",
  };

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Newspaper className="h-4 w-4 text-muted-foreground" />
        <h3 className="text-sm font-semibold">Pronostics presse</h3>
        <span className="text-xs text-muted-foreground">{pronostics.length} source{pronostics.length > 1 ? "s" : ""}</span>
      </div>

      {consensus.length > 0 && (
        <div className="rounded-lg bg-amber-50 border border-amber-200 px-3 py-2">
          <p className="text-[10px] font-bold text-amber-700 uppercase tracking-wide mb-1.5">
            🎯 Consensus experts
          </p>
          <div className="flex flex-wrap gap-1.5">
            {consensus.map(([num, { nb, nom }]) => (
              <span key={num} className="inline-flex items-center gap-1 rounded-full bg-white border border-amber-200 px-2 py-0.5 text-xs font-semibold text-amber-800">
                N°{num} {nom && <span className="font-normal text-amber-600">{nom}</span>}
                <span className="text-[10px] text-amber-500">×{nb}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="grid sm:grid-cols-2 gap-2">
        {pronostics.map((p, i) => (
          <div key={i} className="rounded-lg border border-border/60 bg-muted/20 p-2.5">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-wide">
                {SOURCE_LABEL[p.source] ?? p.source}
              </span>
              {p.journaliste && (
                <span className="text-[10px] text-muted-foreground">{p.journaliste}</span>
              )}
            </div>
            <div className="flex flex-wrap gap-1">
              {p.selection.slice(0, 6).map((s, j) => (
                <span key={j} className={cn(
                  "inline-flex items-center rounded px-1.5 py-0 text-[11px] font-mono font-bold",
                  j === 0 ? "bg-amber-100 text-amber-800" : "bg-muted text-muted-foreground"
                )}>
                  {s.numero}
                </span>
              ))}
            </div>
            {p.commentaire && (
              <p className="text-[10px] text-muted-foreground mt-1.5 line-clamp-2">{p.commentaire}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function MiseCalculatorWidget({
  courseId,
  userPlan,
  profil,
  predictions,
}: {
  courseId: string;
  userPlan: string | undefined;
  profil: string;
  predictions: Prediction[] | null;
}) {
  const [montant, setMontant] = useState("");
  const [plan, setPlan] = useState<MisePlan | null>(null);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  async function generate() {
    const m = parseFloat(montant);
    if (!m || m <= 0) return;
    setLoading(true);
    try {
      const res = await api.post(`/courses/${courseId}/mise-plan`, {
        montant: m,
        profil_risque: profil,
      });
      setPlan(res.data);
    } catch {
      toast.error("Erreur lors du calcul du plan");
    } finally {
      setLoading(false);
    }
  }

  if (!userPlan || userPlan === "free") {
    return (
      <div className="text-center py-6">
        <Calculator className="h-10 w-10 mx-auto mb-3 text-brand-gold opacity-60" />
        <p className="text-sm font-semibold mb-1">Calculateur de mise</p>
        <p className="text-xs text-muted-foreground mb-4">
          Entrez votre mise → BlackTurf génère votre plan de pari personnalisé.
          Disponible dès le plan Standard.
        </p>
        <Button variant="brand" size="sm" asChild>
          <Link href="/tarifs">Passer Standard — 19€/mois</Link>
        </Button>
      </div>
    );
  }

  if (!predictions) {
    return (
      <div className="text-center py-6 text-muted-foreground text-sm">
        <Brain className="h-8 w-8 mx-auto mb-2 opacity-40" />
        Lancez l&apos;analyse IA d&apos;abord pour activer le calculateur.
      </div>
    );
  }

  if (plan) return <PlanMiseDisplay plan={plan} onClose={() => setPlan(null)} />;

  return (
    <div>
      <p className="text-xs text-muted-foreground mb-3">
        Combien souhaitez-vous miser sur cette course ? BlackTurf répartit votre
        mise sur plusieurs paris selon son analyse.
      </p>
      <div className="flex gap-2">
        <div className="relative flex-1">
          <input
            ref={inputRef}
            type="number"
            min="1"
            max="10000"
            step="1"
            value={montant}
            onChange={(e) => setMontant(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && generate()}
            placeholder="10"
            className="w-full rounded-lg border border-input bg-muted/30 px-3 py-2.5 text-sm font-mono pr-8 focus:outline-none focus:ring-2 focus:ring-brand-gold/50 focus:border-brand-gold/50 transition"
          />
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground text-sm">€</span>
        </div>
        <Button
          variant="brand"
          onClick={generate}
          disabled={!montant || parseFloat(montant) <= 0 || loading}
          className="px-4 bg-brand-gold hover:bg-brand-amber text-brand-dark font-bold"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : (
            <>Générer <ChevronRight className="h-3.5 w-3.5" /></>
          )}
        </Button>
      </div>
      {/* Quick amounts */}
      <div className="flex gap-1.5 mt-2 flex-wrap">
        {[5, 10, 20, 30].map((v) => (
          <button
            key={v}
            onClick={() => setMontant(String(v))}
            className="text-[10px] px-2 py-1 rounded border border-border hover:border-brand-gold/50 hover:text-brand-gold transition-colors tabular-nums"
          >
            {v}€
          </button>
        ))}
      </div>
    </div>
  );
}

// ─── Résultats officiels (course terminée) ──────────────────────────────────────
function ResultatsSection({ resultats }: {
  resultats: {
    classement: Array<{ numero: number; nom: string; position: number; temps: number | null; reduction_km: number | null }>;
    rapports: Record<string, number> | null;
    temps_gagnant: string | null;
    commentaire: string | null;
    duree_course: number | null;
  };
}) {
  const podium = [...(resultats.classement || [])].sort((a, b) => a.position - b.position);
  const medal = (pos: number) => (pos === 1 ? "🥇" : pos === 2 ? "🥈" : pos === 3 ? "🥉" : `${pos}e`);
  const rapportLabel: Record<string, string> = {
    e_simple_gagnant: "Gagnant", e_simple_place: "Placé", e_couple_gagnant: "Couplé G.",
    e_couple_place: "Couplé P.", e_tierce: "Tiercé", e_quarte_plus: "Quarté+", e_quinte_plus: "Quinté+",
    e_2sur4: "2sur4", e_multi: "Multi",
  };

  return (
    <div className="mt-4 rounded-xl border border-brand-emerald/30 bg-brand-emerald/5 p-4">
      <h2 className="mb-3 flex items-center gap-2 text-base font-bold">
        🏁 Arrivée officielle
        {resultats.temps_gagnant && (
          <span className="text-xs font-normal text-muted-foreground">
            · Chrono gagnant {resultats.temps_gagnant}s
            {resultats.duree_course ? ` · durée ${(resultats.duree_course / 1000).toFixed(1)}s` : ""}
          </span>
        )}
      </h2>

      {/* Classement */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground border-b">
              <th className="py-1 pr-2">Pos.</th><th className="py-1 pr-2">N°</th>
              <th className="py-1 pr-2">Cheval</th><th className="py-1 pr-2 text-right">Réd. km</th>
            </tr>
          </thead>
          <tbody>
            {podium.map((c) => (
              <tr key={c.numero} className={c.position <= 3 ? "font-semibold" : ""}>
                <td className="py-1 pr-2">{medal(c.position)}</td>
                <td className="py-1 pr-2 tabular-nums">{c.numero}</td>
                <td className="py-1 pr-2">{c.nom}</td>
                <td className="py-1 pr-2 text-right tabular-nums text-muted-foreground">
                  {c.reduction_km != null ? `${c.reduction_km}` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Rapports */}
      {resultats.rapports && Object.keys(resultats.rapports).length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {Object.entries(resultats.rapports).map(([k, v]) => (
            <span key={k} className="inline-flex items-center gap-1 rounded-full bg-white px-2 py-0.5 text-xs ring-1 ring-gray-200">
              <span className="text-muted-foreground">{rapportLabel[k] ?? k}</span>
              <span className="font-semibold tabular-nums">{Number(v).toFixed(2)}€</span>
            </span>
          ))}
        </div>
      )}

      {/* Commentaire narratif post-course */}
      {resultats.commentaire && (
        <div className="mt-3 rounded-lg bg-white/60 p-3 text-sm leading-relaxed text-foreground">
          <p className="mb-1 text-xs font-semibold text-muted-foreground">📝 Analyse de course</p>
          {resultats.commentaire}
        </div>
      )}
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────
export default function CoursePage() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const [course, setCourse] = useState<CourseData | null>(null);
  const [predictions, setPredictions] = useState<Prediction[] | null>(null);
  const [loadingCourse, setLoadingCourse] = useState(true);
  const [loadingPred, setLoadingPred] = useState(false);
  const [triggeringPred, setTriggeringPred] = useState(false);
  const [cotesHisto, setCotesHisto] = useState<Array<{ time: string; [k: string]: number | string }>>([]);
  const [confront, setConfront] = useState<{
    nb_paires_avec_duel: number;
    paires: Array<{ a_numero: number; a_nom: string; b_numero: number; b_nom: string; nb_rencontres: number; a_victoires: number; b_victoires: number; ecart_moyen_longueurs: number | null; derniere_rencontre: { date: string; hippodrome: string; a_position: number; b_position: number } | null }>;
    par_cheval: Array<{ numero: number; nom: string; bilan: string; victoires: number; defaites: number; nb_adversaires_connus: number }>;
  } | null>(null);
  const [analysis, setAnalysis] = useState<{
    narrative: string;
    market_signals: Array<{ numero: number; nom: string; signal: string; detail: string; score: number }>;
    field_confidence: number;
    predictions: Array<{ numero: number; explanation: {
      facteurs_positifs: Array<{ label: string; detail: string; score: number }>;
      facteurs_negatifs: Array<{ label: string; detail: string; score: number }>;
      alertes: Array<{ label: string; detail: string }>;
      verdict: string;
      confiance_composite: number;
    }}>;
    dutch_bet?: {
      mises: Array<{ numero: number; nom: string; cote: number; mise: number; profit_si_gagne: number }>;
      profit_garanti: number; roi_garanti: number; is_profitable: boolean; note: string;
    };
    paris_multiples?: {
      simulations: number;
      scenario_arrivee: Array<{ numero: number; nom: string; proba_victoire: number; cote: number }>;
      proposals: Array<{
        niveau: string; type_pari: string;
        chevaux: Array<{ numero: number; nom: string; cote: number }>;
        proba_gain: number; proba_marche: number; rapport_estime: number;
        mise_suggeree: number; cout_total: number; nb_combinaisons: number;
        gain_potentiel: number; ev: number; esperance_gain: number; edge: number;
        texte_explication: string;
      }>;
    };
  } | null>(null);

  const [resultats, setResultats] = useState<{
    classement: Array<{ numero: number; nom: string; position: number; temps: number | null; reduction_km: number | null }>;
    rapports: Record<string, number> | null;
    temps_gagnant: string | null;
    commentaire: string | null;
    duree_course: number | null;
  } | null>(null);

  const { partants: liveCotes, connected: wsConnected } = useCotesLive(
    id,
    course?.statut === "en_cours"
  );

  useEffect(() => {
    coursesApi.course(id)
      .then((res) => setCourse(res.data))
      .catch(() => toast.error("Course introuvable"))
      .finally(() => setLoadingCourse(false));
  }, [id]);

  useEffect(() => {
    if (!user || ["free", "decouverte"].includes(user.plan)) return;
    setLoadingPred(true);
    predictionsApi.get(id, 100)
      .then((res) => setPredictions(res.data.predictions))
      .catch(() => setPredictions(null))
      .finally(() => setLoadingPred(false));
  }, [id, user]);

  // Load narrative analysis (Standard+)
  useEffect(() => {
    if (!user || ["free", "decouverte"].includes(user.plan) || !course) return;
    if (course.statut === "termine") return; // pas utile post-course
    api.get(`/courses/${id}/analyse`)
      .then((res) => setAnalysis(res.data))
      .catch(() => {}); // fail silently
  }, [id, user, course, predictions]); // refresh après prédictions

  // Load results once course is finished (arrivée + rapports + commentaire)
  useEffect(() => {
    if (!course || course.statut !== "termine") return;
    coursesApi.resultats(id)
      .then((res) => setResultats(res.data))
      .catch(() => setResultats(null));
  }, [id, course]);

  // Load cotes historique for chart
  useEffect(() => {
    if (!user || ["free", "decouverte"].includes(user.plan) || !course) return;
    api.get(`/courses/${id}/cotes-historique`)
      .then((res) => {
        // Pivot: [{time, N°1: cote, N°2: cote, ...}] — clé par vrai numéro de partant
        const pidToNum: Record<string, number> = {};
        for (const p of course.partants) pidToNum[p.participation_id] = p.numero;
        const map: Record<string, Record<string, number>> = {};
        for (const r of res.data) {
          const t = new Date(r.time).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
          if (!map[t]) map[t] = {};
          const num = pidToNum[r.participation_id];
          const key = num != null ? `N°${num}` : `N°${r.participation_id.slice(-2)}`;
          map[t][key] = r.cote;
        }
        setCotesHisto(Object.entries(map).map(([time, vals]) => ({ time, ...vals })));
      })
      .catch(() => {});
  }, [id, user, course]);

  // Confrontations directes (head-to-head) entre partants
  useEffect(() => {
    if (!course) return;
    api.get(`/courses/${id}/confrontations`)
      .then((res) => setConfront(res.data))
      .catch(() => {});
  }, [id, course]);

  async function handleTriggerPred() {
    setTriggeringPred(true);
    try {
      await predictionsApi.trigger(id, 100);
      toast.success("Analyse IA lancée — résultats dans quelques secondes.");
      setTimeout(() => {
        setLoadingPred(true);
        predictionsApi.get(id, 100)
          .then((res) => setPredictions(res.data.predictions))
          .finally(() => setLoadingPred(false));
      }, 4000);
    } catch {
      toast.error("Erreur lors du déclenchement");
    } finally {
      setTriggeringPred(false);
    }
  }

  if (loadingCourse) {
    return (
      <div className="flex justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (!course) return null;

  // Merge live cotes
  const liveCoteMap: Record<number, number | null> = {};
  if (liveCotes.length > 0) {
    for (const p of liveCotes as Array<{ numero: number; cote_pmu: number | null }>) {
      liveCoteMap[p.numero] = p.cote_pmu;
    }
  }

  const profil = user?.profil_risque || "equilibre";

  // Confidence globale = mean des top3 confidence_score
  const confGlobal = predictions
    ? predictions.slice(0, 3).reduce((s, p) => s + (p.confidence_score || 0), 0) / 3
    : null;

  // Top value bet
  const topVB = predictions?.find((p) => p.value_bet && p.value_bet.niveau >= 3);

  return (
    <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-6">
      {/* Back */}
      <Link href="/programme" className="inline-flex items-center gap-2 text-muted-foreground hover:text-foreground text-sm mb-5 transition-colors">
        <ArrowLeft className="h-4 w-4" /> Programme
      </Link>

      {/* ── HEADER ── */}
      <div className="rounded-xl border border-border bg-card/60 p-5 mb-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-2 mb-2">
              <h1 className="text-xl font-bold">{course.nom || `Course ${course.course_id.match(/R\d+C\d+$/)?.[0] ?? course.course_id}`}</h1>
              {course.est_quinte && <Badge variant="gold" className="animate-pulse-slow">⭐ Quinté+</Badge>}
              {course.est_quarte && <Badge variant="gold">Quarté+</Badge>}
              {course.est_tierce && <Badge variant="secondary">Tiercé</Badge>}
              <Badge variant={course.statut === "en_cours" ? "success" : course.statut === "termine" ? "secondary" : "warning"}>
                {course.statut === "en_cours" ? "🔴 En cours" : course.statut === "termine" ? "✓ Terminée" : "⏳ À venir"}
              </Badge>
              {wsConnected && (
                <span className="flex items-center gap-1 text-[10px] font-semibold text-brand-emerald">
                  <span className="h-1.5 w-1.5 rounded-full bg-brand-emerald animate-pulse" /> En direct
                </span>
              )}
            </div>
            <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm text-muted-foreground">
              <span className="font-semibold text-foreground">{disciplineIcon(course.discipline)} {course.discipline}</span>
              <span>📍 {course.hippodrome_nom}</span>
              <span>📏 {course.distance}m</span>
              <span>👥 {course.nb_partants} partants</span>
              <span>🕐 {formatDateTime(course.date_heure)}</span>
              {course.terrain_officiel && <span>🌿 {course.terrain_officiel}</span>}
              {course.allocation && <span>💰 {course.allocation.toLocaleString("fr-FR")}€</span>}
              {course.montant_offert_1er != null && course.montant_offert_1er > 0 && (
                <span>🏆 {course.montant_offert_1er.toLocaleString("fr-FR")}€ au gagnant</span>
              )}
              {course.categorie_particularite && (
                <span className="capitalize">🏷️ {course.categorie_particularite.toLowerCase()}</span>
              )}
              {course.meteo?.temperature && (
                <span><Cloud className="h-3 w-3 inline" /> {course.meteo.temperature}°C</span>
              )}
            </div>
            {/* Conditions de course (texte officiel PMU) */}
            {course.conditions_texte && (
              <details className="mt-2 text-xs text-muted-foreground">
                <summary className="cursor-pointer font-semibold hover:text-foreground select-none">
                  📋 Conditions de la course
                </summary>
                <p className="mt-1.5 leading-relaxed rounded-lg bg-muted/40 p-2.5">{course.conditions_texte}</p>
              </details>
            )}
            {/* Nouvelles infos enrichies */}
            {(course.penetrometre_coef || course.pool_total_eur || course.avantage_couloir) && (
              <div className="flex flex-wrap gap-2 mt-2.5">
                {course.penetrometre_coef != null && course.penetrometre_desc && (
                  <PenetroBadge coef={course.penetrometre_coef} desc={course.penetrometre_desc} />
                )}
                {course.pool_total_eur != null && course.pool_total_eur > 0 && (
                  <PoolBadge poolEur={course.pool_total_eur} />
                )}
                {course.avantage_couloir && course.avantage_couloir !== "neutre" && (
                  <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold bg-gray-100 ring-1 ring-gray-200 text-gray-700">
                    {course.avantage_couloir === "interieur" ? "⬅️ Avantage intérieur" : "➡️ Avantage extérieur"}
                  </span>
                )}
              </div>
            )}
          </div>

          {/* Confidence meter */}
          {confGlobal !== null && course.statut !== "termine" && (
            <div className="text-right">
              <p className="text-xs text-muted-foreground mb-1">Score IA</p>
              <ConfidenceMeter score={confGlobal} size="md" />
            </div>
          )}
        </div>

        {/* Résultats officiels (course terminée) */}
        {course.statut === "termine" && resultats && (
          <ResultatsSection resultats={resultats} />
        )}

        {/* Alert value bet exceptionnel */}
        {topVB && (
          <div className="mt-3 flex items-center gap-2 rounded-lg border border-brand-gold/30 bg-brand-gold/5 px-3 py-2 text-sm">
            <Zap className="h-4 w-4 text-brand-gold flex-shrink-0" />
            <span>
              <strong>Pari de valeur exceptionnel</strong> — N°{topVB.numero} {topVB.nom_cheval} ·{" "}
              {etoiles(topVB.value_bet!.niveau)} · Espérance <EVBadge ev={topVB.value_bet!.ev_max} />
            </span>
          </div>
        )}
      </div>

      <div className="grid lg:grid-cols-3 gap-6">
        {/* ── LEFT: Partants + Chart ── */}
        <div className="lg:col-span-2 space-y-5">

          {/* Tableau partants */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                Partants
                {predictions && (
                  <span className="text-xs font-normal text-muted-foreground ml-1">
                    — Proba IA · Cote juste · Espérance
                  </span>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border bg-muted/30 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                      <th className="text-left px-3 py-2.5 w-8">N°</th>
                      <th className="text-left px-3 py-2.5">Cheval</th>
                      <th className="text-left px-3 py-2.5 hidden md:table-cell">Jockey</th>
                      <th className="text-right px-3 py-2.5">ELO</th>
                      <th className="text-right px-3 py-2.5">Cote PMU</th>
                      {predictions && <th className="text-right px-3 py-2.5">Cote IA</th>}
                      {predictions && <th className="text-right px-3 py-2.5">Top-3</th>}
                      {predictions && <th className="text-right px-3 py-2.5">Espérance</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {course.partants
                      .filter((p) => !p.non_partant)
                      .map((partant) => {
                        const pred = predictions?.find(
                          (p) => p.participation_id === partant.participation_id
                        );
                        const liveCote = liveCoteMap[partant.numero];
                        const cote = liveCote ?? partant.cote_pmu;
                        const rang = pred?.rang_predit;
                        const coteMoved = liveCote && partant.cote_pmu && liveCote < partant.cote_pmu;

                        return (
                          <tr
                            key={partant.participation_id}
                            className={cn(
                              "border-b border-border/40 transition-colors hover:bg-accent/20",
                              rang === 1 && "row-top1",
                              rang === 2 && "row-top2",
                              rang === 3 && "row-top3",
                            )}
                          >
                            <td className="px-3 py-2.5 font-bold text-muted-foreground text-center">
                              {partant.numero}
                            </td>
                            <td className="px-3 py-2.5">
                              <div className="flex items-center gap-1.5 flex-wrap leading-tight">
                                <span className="font-medium">{partant.nom_cheval}</span>
                                {partant.running_style && (
                                  <RunningStyleBadge style={partant.running_style} />
                                )}
                                {partant.changement_jockey && (
                                  <span title="Changement de jockey vs dernière course" className="inline-flex items-center gap-0.5 rounded-full px-1.5 py-0 text-[9px] font-bold bg-orange-50 ring-1 ring-orange-200 text-orange-600">
                                    <RefreshCw className="h-2.5 w-2.5" /> Jockey ↗
                                  </span>
                                )}
                                {(partant.jockey_suspendu || partant.entraineur_suspendu) && (
                                  <span title={partant.jockey_suspendu ? "Jockey suspendu" : "Entraîneur suspendu"} className="inline-flex items-center gap-0.5 rounded-full px-1.5 py-0 text-[9px] font-bold bg-red-50 ring-1 ring-red-200 text-red-600">
                                    <ShieldAlert className="h-2.5 w-2.5" />
                                    {partant.jockey_suspendu ? "Jockey susp." : "Entr. susp."}
                                  </span>
                                )}
                              </div>
                              <div className="text-[10px] text-muted-foreground flex gap-1 mt-0.5 flex-wrap">
                                {partant.age && <span>{partant.age}a</span>}
                                {partant.sexe && <span>{partant.sexe}</span>}
                                {partant.premier_deferre && <span className="text-brand-gold">★ Déferré</span>}
                                {partant.premieres_oeilleres && <span className="text-brand-blue">★ Œillères</span>}
                                {partant.jours_depuis_derniere != null && (
                                  <span className={cn(
                                    partant.jours_depuis_derniere >= 14 && partant.jours_depuis_derniere <= 35
                                      ? "text-emerald-600 font-medium"
                                      : partant.jours_depuis_derniere > 60
                                      ? "text-orange-500"
                                      : "text-muted-foreground"
                                  )}>
                                    {partant.jours_depuis_derniere}j repos
                                  </span>
                                )}
                                {partant.asso_jockey_entraineur_taux != null && partant.asso_jockey_entraineur_nb != null && partant.asso_jockey_entraineur_nb >= 5 && (
                                  <span className="text-violet-600 font-medium">
                                    Duo {(partant.asso_jockey_entraineur_taux * 100).toFixed(0)}%w
                                  </span>
                                )}
                                {partant.pere && (
                                  <span className="text-muted-foreground/70">Par {partant.pere}</span>
                                )}
                              </div>
                            </td>
                            <td className="px-3 py-2.5 hidden md:table-cell text-xs">
                              <div className={cn(
                                "text-muted-foreground",
                                partant.jockey_suspendu && "line-through text-red-400"
                              )}>
                                {partant.jockey || "—"}
                              </div>
                              {partant.entraineur && (
                                <div className={cn(
                                  "text-[10px] text-muted-foreground/60 mt-0.5",
                                  partant.entraineur_suspendu && "line-through text-red-400"
                                )}>
                                  {partant.entraineur}
                                </div>
                              )}
                            </td>
                            <td className="px-3 py-2.5 text-right">
                              <ELOBadge elo={partant.elo_global} />
                            </td>
                            <td className="px-3 py-2.5 text-right">
                              <span className={cn("font-mono font-semibold", coteMoved && "text-brand-emerald")}>
                                {formatCote(cote)}
                              </span>
                              {liveCote && <span className="text-brand-emerald text-[10px] ml-1">↓</span>}
                            </td>
                            {predictions && (
                              <td className="px-3 py-2.5 text-right text-muted-foreground font-mono text-xs">
                                {pred?.cote_juste ? formatCote(pred.cote_juste) : "—"}
                              </td>
                            )}
                            {predictions && (
                              <td className="px-3 py-2.5 text-right">
                                {pred ? (
                                  <div className="flex flex-col items-end gap-0.5">
                                    <span className={cn(
                                      "font-bold font-mono tabular-nums text-xs",
                                      rang === 1 && "text-brand-gold",
                                      rang === 2 && "text-brand-blue",
                                      rang === 3 && "text-brand-emerald",
                                      (rang || 99) > 3 && "text-muted-foreground"
                                    )}>
                                      {(pred.proba_top3 * 100).toFixed(0)}%
                                    </span>
                                    <ConfidenceMeter score={pred.confidence_score || 0} size="sm" />
                                  </div>
                                ) : "—"}
                              </td>
                            )}
                            {predictions && (
                              <td className="px-3 py-2.5 text-right">
                                {pred?.value_bet ? (
                                  <div className="flex flex-col items-end gap-0.5">
                                    <EVBadge ev={pred.value_bet.ev_max} />
                                    <span className="text-[10px]">{etoiles(pred.value_bet.niveau)}</span>
                                  </div>
                                ) : "—"}
                              </td>
                            )}
                          </tr>
                        );
                      })}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          {/* Graphique cotes historique */}
          {/* ── Narrative IA ── */}
          {analysis?.narrative && (
            <div className="rounded-xl border border-violet-100 bg-gradient-to-br from-violet-50/60 to-white p-5 space-y-3">
              <div className="flex items-center gap-2">
                <Brain className="h-4 w-4 text-violet-600" />
                <h3 className="text-sm font-semibold text-gray-900">Analyse BlackTurf IA</h3>
                {analysis.field_confidence > 0 && (
                  <span className={cn(
                    "ml-auto text-[10px] font-semibold rounded-full px-2 py-0.5",
                    analysis.field_confidence >= 0.7 ? "bg-emerald-100 text-emerald-700" :
                    analysis.field_confidence >= 0.5 ? "bg-amber-100 text-amber-700" : "bg-gray-100 text-gray-600"
                  )}>
                    Confiance {Math.round(analysis.field_confidence * 100)}%
                  </span>
                )}
              </div>
              <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">{analysis.narrative}</p>

              {/* Signaux marché */}
              {analysis.market_signals?.length > 0 && (
                <div className="flex flex-wrap gap-1.5 pt-1">
                  {analysis.market_signals.map((s, i) => (
                    <span key={i} className="inline-flex items-center gap-1 rounded-full bg-amber-50 border border-amber-200 px-2 py-0.5 text-[10px] font-semibold text-amber-700">
                      {s.signal} — N°{s.numero} {s.nom}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ── Comparaison multi-bookmakers ── */}
          {course.partants.some((p) => p.cote_winamax || p.cote_betclic || p.cote_unibet || p.cote_betfair_exchange) && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 px-0.5">
                <BarChart2 className="h-4 w-4 text-muted-foreground" />
                <h3 className="text-sm font-semibold">Comparaison des cotes</h3>
                <span className="text-xs text-muted-foreground">
                  {course.partants.filter(p => !p.non_partant)[0]?.nb_sources ?? 1} sources actives
                </span>
                <span className="ml-auto text-[10px] text-emerald-600 font-medium">
                  Vert = meilleure cote disponible
                </span>
              </div>
              <ComparaisonCotes partants={course.partants} />
            </div>
          )}

          {/* ── Pronostics presse ── */}
          {course.pronostics_presse?.length > 0 && (
            <PronosticsPresse pronostics={course.pronostics_presse} />
          )}

          {cotesHisto.length > 2 && (() => {
            // Sélection des favoris (cote finale la plus basse) + labels noms
            const last = cotesHisto[cotesHisto.length - 1] || {};
            const keys = Object.keys(last)
              .filter((k) => k !== "time" && typeof last[k] === "number")
              .sort((a, b) => (last[a] as number) - (last[b] as number))
              .slice(0, 5);
            const nameByKey: Record<string, string> = {};
            for (const p of course.partants) nameByKey[`N°${p.numero}`] = `N°${p.numero} ${p.nom_cheval}`;
            return (
            <Card>
              <CardHeader className="pb-1">
                <CardTitle className="text-sm flex items-center gap-2">
                  <TrendingUp className="h-4 w-4 text-brand-gold" />
                  Évolution des cotes
                  <span className="text-xs font-normal text-muted-foreground">— favoris, 2h avant départ</span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={240}>
                  <LineChart data={cotesHisto} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                    <CartesianGrid {...GRID} />
                    <XAxis dataKey="time" tick={axisTick} axisLine={axisLine} tickLine={tickLine} minTickGap={28} />
                    <YAxis
                      tick={axisTick} axisLine={axisLine} tickLine={tickLine} reversed
                      width={38} tickFormatter={(v) => `${v}`}
                      domain={["dataMin - 2", "dataMax + 2"]}
                    />
                    <Tooltip
                      content={<ChartTooltip labelMap={nameByKey} valueFormatter={(v) => `${v.toFixed(1)}`} />}
                      cursor={{ stroke: "#E5E7EB", strokeWidth: 1 }}
                    />
                    <Legend
                      verticalAlign="bottom" height={28} iconType="circle" iconSize={8}
                      formatter={(value) => (
                        <span className="text-[11px] text-gray-500">{nameByKey[value] ?? value}</span>
                      )}
                    />
                    {keys.map((k, i) => (
                      <Line
                        key={k} type="monotone" dataKey={k} name={k}
                        strokeWidth={i === 0 ? 3 : 2}
                        stroke={CHART_PALETTE[i % CHART_PALETTE.length]}
                        dot={false}
                        activeDot={{ r: 4, strokeWidth: 2, stroke: "#fff" }}
                      />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
                <p className="mt-1 text-[10px] text-muted-foreground/70">
                  Axe inversé : une cote qui <strong>descend</strong> (ligne qui monte) = cheval de plus en plus joué.
                </p>
              </CardContent>
            </Card>
            );
          })()}

          {/* ── Confrontations directes (head-to-head) ── */}
          {confront && confront.nb_paires_avec_duel > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">
                  Confrontations directes
                  <span className="ml-2 text-xs font-normal text-muted-foreground">
                    {confront.nb_paires_avec_duel} duel{confront.nb_paires_avec_duel > 1 ? "s" : ""} entre partants
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-muted-foreground border-b">
                        <th className="py-2 font-medium">Duel</th>
                        <th className="font-medium">Bilan</th>
                        <th className="font-medium">Écart moy.</th>
                        <th className="font-medium">Dernière rencontre</th>
                      </tr>
                    </thead>
                    <tbody>
                      {confront.paires.slice(0, 15).map((p, i) => (
                        <tr key={i} className="border-b last:border-0">
                          <td className="py-2">
                            <span className="font-medium">N°{p.a_numero} {p.a_nom}</span>
                            <span className="text-muted-foreground"> vs </span>
                            <span className="font-medium">N°{p.b_numero} {p.b_nom}</span>
                          </td>
                          <td>{p.a_victoires}–{p.b_victoires}{p.nb_rencontres > 1 ? ` (${p.nb_rencontres})` : ""}</td>
                          <td>{p.ecart_moyen_longueurs != null ? `${p.ecart_moyen_longueurs} L` : "—"}</td>
                          <td className="text-muted-foreground">
                            {p.derniere_rencontre
                              ? `${p.derniere_rencontre.date} · ${p.derniere_rencontre.hippodrome} (${p.derniere_rencontre.a_position}–${p.derniere_rencontre.b_position})`
                              : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}
        </div>

        {/* ── RIGHT SIDEBAR ── */}
        <div className="space-y-4">
          {/* Analyse IA */}
          <Card className="border-border/70">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-sm">
                <Brain className="h-4 w-4 text-brand-gold" />
                Analyse IA
              </CardTitle>
            </CardHeader>
            <CardContent>
              {!user ? (
                <div className="text-center py-4">
                  <p className="text-sm text-muted-foreground mb-3">Connectez-vous pour voir les prédictions</p>
                  <Button variant="brand" size="sm" asChild>
                    <Link href={`/login?redirect=/courses/${id}`}>Connexion</Link>
                  </Button>
                </div>
              ) : ["free", "decouverte"].includes(user.plan) ? (
                <div className="text-center py-4">
                  <TrendingUp className="h-8 w-8 mx-auto mb-2 text-muted-foreground/50" />
                  <p className="text-sm text-muted-foreground mb-3">Disponible dès le plan Standard</p>
                  <Button variant="brand" size="sm" asChild>
                    <Link href="/tarifs">Passer Standard — 19€/mois</Link>
                  </Button>
                </div>
              ) : loadingPred ? (
                <div className="flex justify-center py-6">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : !predictions ? (
                <div className="text-center py-4">
                  <Brain className="h-8 w-8 mx-auto mb-2 text-muted-foreground/40" />
                  <p className="text-sm text-muted-foreground mb-3">Aucune analyse disponible</p>
                  <Button variant="brand" size="sm" onClick={handleTriggerPred} disabled={triggeringPred}>
                    {triggeringPred ? <Loader2 className="h-4 w-4 animate-spin" /> : "Lancer l'analyse IA"}
                  </Button>
                </div>
              ) : (
                <div className="space-y-3">
                  {/* Top 3 */}
                  {predictions.slice(0, 3).map((p) => (
                    <div key={p.prediction_id} className="flex items-center gap-3">
                      <div className={cn(
                        "h-8 w-8 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0",
                        p.rang_predit === 1 && "bg-brand-gold/20 text-brand-gold gold-glow",
                        p.rang_predit === 2 && "bg-brand-blue/20 text-brand-blue",
                        p.rang_predit === 3 && "bg-brand-emerald/20 text-brand-emerald",
                      )}>
                        {p.rang_predit}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <p className="text-sm font-semibold truncate">N°{p.numero} {p.nom_cheval}</p>
                          {p.value_bet && <EVBadge ev={p.value_bet.ev_max} />}
                        </div>
                        <div className="flex items-center gap-2 mt-0.5">
                          <ConfidenceMeter score={p.confidence_score || 0} size="sm" />
                          <span className="text-[10px] text-muted-foreground">
                            {(p.proba_top3 * 100).toFixed(0)}% top-3
                          </span>
                        </div>
                      </div>
                    </div>
                  ))}
                  <div className="pt-2 border-t border-border/50">
                    <p className="text-[10px] text-muted-foreground flex gap-1.5">
                      <Info className="h-3 w-3 mt-0.5 flex-shrink-0" />
                      Outil d&apos;aide à la décision. Aucune garantie.
                    </p>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Calculateur de mise */}
          <Card className="border-brand-gold/20">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-sm">
                <Calculator className="h-4 w-4 text-brand-gold" />
                Votre plan de mise
              </CardTitle>
            </CardHeader>
            <CardContent>
              <MiseCalculatorWidget
                courseId={id}
                userPlan={user?.plan}
                profil={profil}
                predictions={predictions}
              />
            </CardContent>
          </Card>

          {/* Infos course */}
          <Card className="border-border/50">
            <CardContent className="p-4 space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Discipline</span>
                <span className="font-medium">{disciplineIcon(course.discipline)} {course.discipline}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Distance</span>
                <span className="font-mono font-medium">{course.distance}m</span>
              </div>
              {course.niveau_course && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Niveau</span>
                  <span className="font-medium">{course.niveau_course}</span>
                </div>
              )}
              {course.terrain_officiel && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Terrain</span>
                  <span className="font-medium">{course.terrain_officiel}</span>
                </div>
              )}
              {course.meteo && (
                <>
                  {course.meteo.temperature !== null && (
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Température</span>
                      <span className="font-medium">{course.meteo.temperature}°C</span>
                    </div>
                  )}
                  {course.meteo.pluie_24h !== null && course.meteo.pluie_24h > 0 && (
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Pluie 24h</span>
                      <span className="font-medium text-brand-blue">{course.meteo.pluie_24h}mm</span>
                    </div>
                  )}
                </>
              )}
              {course.allocation && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Dotation</span>
                  <span className="font-mono font-medium">{course.allocation.toLocaleString("fr-FR")}€</span>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
