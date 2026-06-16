"use client";

import { useEffect, useState, useRef, Fragment } from "react";
import { useParams } from "next/navigation";
import {
  ArrowLeft, Brain, Loader2, TrendingUp, AlertTriangle, Cloud,
  Calculator, ChevronRight, ChevronDown, Star, Zap, Info, BarChart2,
  RefreshCw, ShieldAlert, Newspaper, TrendingDown, Activity, CheckCircle2,
  MapPin, Ruler, Users, Clock, Trophy, Tag, FileText, Target, Pencil,
} from "lucide-react";
import Link from "next/link";
import { coursesApi, predictionsApi, api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/hooks/useAuth";
import { useCotesLive } from "@/hooks/useWebSocket";
import { formatCote, formatEV, etoiles, formatDateTime, cn } from "@/lib/utils";
import { toast } from "sonner";
import {
  ConfidenceMeter, EVBadge, ELOBadge, RunningStyleBadge, MusiqueDisplay,
  PenetroBadge, PoolBadge,
} from "@/components/courses/badges";

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
  handicap_poids: number | null;
  poids_prevu: number | null;
  numero_corde: number | null;
  gains_carriere: number | null;
  nb_victoires: number | null;
  nb_courses: number | null;
  pere: string | null;
  mere: string | null;
  pere_de_mere: string | null;
  prix_vente_yearling: number | null;
  asso_jockey_entraineur_taux: number | null;
  asso_jockey_entraineur_nb: number | null;
  jockey_suspendu: boolean;
  entraineur_suspendu: boolean;
  analyse?: {
    forme: { taux_top3: number | null; recent_win_rate: number | null; forme_5: number | null; regularite: number | null; tendance: number | null; momentum: number | null };
    contexte: { pref_distance: number | null; pref_terrain: number | null; pref_hippodrome: number | null; nb_distance: number | null; nb_terrain: number | null; nb_hippodrome: number | null; corde_pref: number | null };
    elo: { trend_30j: number | null; pct_rank: number | null; discipline: number | null };
    marche: { spi: number | null; steam: number | null; valeur_latente: number | null; decote: number | null; tendance_force: number | null; mouvement_30min: number | null };
    vitesse: { vitesse_theorique: number | null; stamina: number | null; indice_valeur: number | null };
    jockey_stats: { taux_victoire: number | null; taux_place: number | null; roi: number | null; victoires_saison: number | null; courses_saison: number | null; montes_30j: number | null } | null;
    entraineur_stats: { taux_victoire: number | null; taux_place: number | null; roi: number | null; victoires_saison: number | null; courses_saison: number | null } | null;
    points: { txt: string; type: string }[];
  } | null;
}

interface Prediction {
  prediction_id: string;
  participation_id: string;
  numero: number;
  nom_cheval: string;
  proba_top1: number;
  proba_top3: number;
  proba_top1_low: number | null;
  proba_top1_high: number | null;
  rang_predit: number;
  confidence_score: number | null;
  cote_pmu: number | null;
  cote_juste: number | null;
  value_bet: { ev_max: number; niveau: number; meilleure_source: string } | null;
}

interface CourseData {
  course_id: string;
  nom: string | null;
  numero_reunion: number | null;  // n° réunion public (PMU numExterne)
  numero: number;                 // n° de la course dans la réunion (C)
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
  prono_fige?: boolean;        // pronostic figé (T-10 min) — ne change plus
  prono_fige_a?: string | null;
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
  raisons?: string[];          // justification complète du pari (backend)
}

interface PariEcarte {
  type: string;
  chevaux: { numero: number; nom: string }[];
  probabilite: number;
  ev_estime: number;
  motif: string;
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
  esperance_gain?: number;   // espérance de profit net en €
  palier?: string;           // micro | petit | moyen | gros
  profil?: string;           // conservateur | equilibre | agressif
  mode_adaptatif?: string;   // prudent | normal | offensif
  kelly_warning: boolean;
  resume_ia: string;
  avertissement: string;
  niveaux: NiveauPlan[];
  paris_ecartes?: PariEcarte[];   // candidats rejetés + motif (transparence)
}

// ─── Sub-components ───────────────────────────────────────────────────────────
// Badges présentationnels (ConfidenceMeter, EVBadge, ELOBadge, RunningStyleBadge,
// MusiqueDisplay, PenetroBadge, PoolBadge) extraits dans components/courses/badges.

// Profils de mise (source unique : formulaire + switch rapide dans le plan).
const PROFILS_MISE = [
  { key: "conservateur", label: "Prudent", emoji: "🛡️", desc: "Priorité au placé : gains plus petits mais plus fréquents." },
  { key: "equilibre", label: "Modéré", emoji: "⚖️", desc: "Équilibre entre sécurité et rendement." },
  { key: "agressif", label: "Risqué", emoji: "🔥", desc: "Vise les gros gains : plus rare, plus payant." },
] as const;

function PlanMiseDisplay({ plan, profil, switching, onChangeProfil, onClose, onSave }: {
  plan: MisePlan;
  profil: string;
  switching: boolean;
  onChangeProfil: (profil: string) => void;
  onClose: () => void;
  onSave: () => Promise<number>;
}) {
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  const handleSave = async () => {
    setSaveState("saving");
    try {
      await onSave();
      setSaveState("saved");
    } catch {
      setSaveState("idle");
    }
  };
  const profilDesc = PROFILS_MISE.find((p) => p.key === profil)?.desc;
  return (
    <div className="animate-slide-up">
      {/* Switch profil rapide — même mise, recalcul instantané (sans repasser par le formulaire) */}
      <div className="mb-4">
        <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-1.5">Profil de risque</p>
        <div className="grid grid-cols-3 gap-1 rounded-lg bg-muted/40 p-1">
          {PROFILS_MISE.map((p) => {
            const active = profil === p.key;
            return (
              <button
                key={p.key}
                onClick={() => !active && onChangeProfil(p.key)}
                disabled={switching}
                className={cn(
                  "relative flex items-center justify-center gap-1 rounded-md py-1.5 text-[11px] font-semibold transition-all disabled:cursor-wait",
                  active
                    ? "bg-brand-gold text-brand-dark shadow-sm"
                    : "text-muted-foreground hover:text-foreground hover:bg-background/60"
                )}
              >
                {switching && active
                  ? <Loader2 className="h-3 w-3 animate-spin" />
                  : <span>{p.emoji}</span>}
                {p.label}
              </button>
            );
          })}
        </div>
        {profilDesc && (
          <p className="mt-1 text-[10px] text-muted-foreground/70">{profilDesc} · même mise conservée.</p>
        )}
      </div>

      {/* Header résumé */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <button
            onClick={onClose}
            className="group inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-brand-gold transition-colors"
          >
            Plan pour <Pencil className="h-3 w-3 opacity-0 group-hover:opacity-100 transition-opacity" />
          </button>
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
                <div key={i} className="text-xs">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
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
                  {p.raisons && p.raisons.length > 0 && (
                    <details className="mt-1 ml-1">
                      <summary className="cursor-pointer text-[11px] text-brand-gold/90 font-semibold list-none select-none">
                        Pourquoi ce pari ? ▾
                      </summary>
                      <ul className="mt-1 space-y-0.5 rounded bg-muted/30 p-2 text-[11px] text-muted-foreground leading-relaxed">
                        {p.raisons.map((r, j) => (
                          <li key={j} className="flex gap-1.5">
                            <span className="text-brand-gold flex-shrink-0">·</span>
                            <span className="min-w-0">{r}</span>
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Paris écartés — transparence : ce que l'IA refuse et POURQUOI */}
      {plan.paris_ecartes && plan.paris_ecartes.length > 0 && (
        <details className="mt-4 rounded-lg border border-border bg-muted/20 px-3 py-2 text-xs">
          <summary className="cursor-pointer font-semibold text-muted-foreground list-none select-none">
            Paris écartés par l&apos;algorithme ({plan.paris_ecartes.length}) ▾
          </summary>
          <div className="mt-2 space-y-2">
            {plan.paris_ecartes.map((e, i) => (
              <div key={i} className="rounded bg-background/60 border border-border/60 p-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold">
                    {e.type}{" "}
                    <span className="text-muted-foreground font-normal">
                      {e.chevaux.map(c => `N°${c.numero}`).join(" + ")}
                    </span>
                  </span>
                  <span className="text-muted-foreground/70 font-mono tabular-nums flex-shrink-0">
                    {(e.probabilite * 100).toFixed(0)}%
                  </span>
                </div>
                <p className="mt-0.5 text-brand-red/90">{e.motif}</p>
              </div>
            ))}
          </div>
        </details>
      )}

      {/* Résumé totaux */}
      <div className="mt-4 grid grid-cols-3 gap-2 text-xs">
        <div className="rounded bg-muted/30 p-2">
          <div className="text-muted-foreground">Misé</div>
          <div className="font-bold font-mono tabular-nums">{plan.montant_joue.toFixed(2)}€</div>
        </div>
        <div className="rounded bg-muted/30 p-2">
          <div className="text-muted-foreground">Réserve</div>
          <div className="font-bold font-mono tabular-nums text-brand-gold">{plan.montant_reserve.toFixed(2)}€</div>
        </div>
        {typeof plan.esperance_gain === "number" && (
          <div className="rounded bg-muted/30 p-2">
            <div className="text-muted-foreground">Espérance gain</div>
            <div className={cn(
              "font-bold font-mono tabular-nums",
              plan.esperance_gain >= 0 ? "text-brand-emerald" : "text-brand-red"
            )}>
              {plan.esperance_gain >= 0 ? "+" : ""}{plan.esperance_gain.toFixed(2)}€
            </div>
          </div>
        )}
      </div>

      {plan.kelly_warning && (
        <div className="mt-3 rounded-lg border border-brand-red/30 bg-brand-red/5 p-2 text-xs text-brand-red flex gap-2">
          <AlertTriangle className="h-3 w-3 mt-0.5 flex-shrink-0" />
          {plan.avertissement}
        </div>
      )}

      <p className="mt-3 text-[10px] text-muted-foreground/60">{plan.avertissement}</p>

      {saveState === "saved" ? (
        <div className="mt-3 flex items-center justify-center gap-2 rounded-lg border border-brand-emerald/30 bg-brand-emerald/5 py-2.5 text-sm font-semibold text-brand-emerald">
          <CheckCircle2 className="h-4 w-4" /> Paris enregistrés dans votre capital
        </div>
      ) : (
        <Button
          variant="brand"
          className="mt-3 w-full bg-brand-gold hover:bg-brand-amber text-brand-dark font-bold"
          onClick={handleSave}
          disabled={saveState === "saving"}
        >
          {saveState === "saving"
            ? <Loader2 className="h-4 w-4 animate-spin" />
            : <>Valider et enregistrer dans mon capital</>}
        </Button>
      )}
      <p className="mt-1.5 text-center text-[10px] text-muted-foreground/60">
        Les gains/pertes seront calculés automatiquement à la fin de la course (vrais rapports PMU).
      </p>

      <Button variant="ghost" size="sm" className="mt-1 w-full text-xs" onClick={onClose}>
        Modifier le montant
      </Button>
    </div>
  );
}

/* ─── Running style badge ────────────────────────────────────────────────── */
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
            Consensus experts
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
  statut,
}: {
  courseId: string;
  userPlan: string | undefined;
  profil: string;
  predictions: Prediction[] | null;
  statut?: string;
}) {
  const [montant, setMontant] = useState("");
  const [plan, setPlan] = useState<MisePlan | null>(null);
  const [loading, setLoading] = useState(false);
  const [profilChoisi, setProfilChoisi] = useState(profil || "equilibre");
  const inputRef = useRef<HTMLInputElement>(null);

  async function generate(profilOverride?: string) {
    const m = parseFloat(montant);
    if (!m || m <= 0) return;
    const prof = profilOverride ?? profilChoisi;
    setLoading(true);
    try {
      const res = await api.post(`/courses/${courseId}/mise-plan`, {
        montant: m,
        profil_risque: prof,
      });
      setPlan(res.data);
    } catch {
      toast.error("Erreur lors du calcul du plan");
    } finally {
      setLoading(false);
    }
  }

  // Switch de profil depuis le plan affiché : garde la même mise, recalcule
  // instantanément sans repasser par le formulaire (le plan reste visible).
  async function switchProfil(p: string) {
    if (p === profilChoisi || loading) return;
    setProfilChoisi(p);
    await generate(p);
  }

  async function saveBets(): Promise<number> {
    const m = parseFloat(montant);
    try {
      const res = await api.post(`/courses/${courseId}/enregistrer-paris`, {
        montant: m, profil_risque: profilChoisi,
      });
      const n = res.data?.enregistres ?? 0;
      toast.success(`${n} pari${n > 1 ? "s" : ""} enregistré${n > 1 ? "s" : ""} dans votre capital`);
      return n;
    } catch {
      toast.error("Erreur lors de l'enregistrement");
      throw new Error("save_failed");
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
        {statut === "termine"
          ? "Course non analysée par l'IA — calculateur indisponible."
          : "Lancez l'analyse d'abord pour activer le calculateur."}
      </div>
    );
  }

  if (plan) return (
    <PlanMiseDisplay
      plan={plan}
      profil={profilChoisi}
      switching={loading}
      onChangeProfil={switchProfil}
      onClose={() => setPlan(null)}
      onSave={saveBets}
    />
  );

  return (
    <div>
      <p className="text-xs text-muted-foreground mb-3">
        Combien souhaitez-vous miser sur cette course ? BlackTurf répartit votre
        mise sur plusieurs paris selon son analyse.
      </p>
      {/* Profil de risque — change quels paris ET la répartition */}
      <div className="mb-3">
        <p className="text-[10px] text-muted-foreground mb-1.5">Profil de risque</p>
        <div className="grid grid-cols-3 gap-1.5">
          {PROFILS_MISE.map((p) => (
            <button
              key={p.key}
              onClick={() => setProfilChoisi(p.key)}
              className={cn(
                "text-[11px] px-2 py-1.5 rounded border font-semibold transition-colors",
                profilChoisi === p.key
                  ? "border-brand-gold bg-brand-gold/10 text-brand-gold"
                  : "border-border text-muted-foreground hover:border-brand-gold/40"
              )}
            >
              {p.emoji} {p.label}
            </button>
          ))}
        </div>
      </div>
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
          onClick={() => generate()}
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
// Badge custom par type de pari (monogramme coloré — pas les logos PMU, qui sont
// des marques déposées). Couvre toutes les clés de rapports réellement publiées.
const RAPPORT_META: Record<string, { label: string; abbr: string; color: string; ordre: number }> = {
  e_simple_gagnant:            { label: "Simple Gagnant", abbr: "SG", color: "#059669", ordre: 1 },
  simple_gagnant_international: { label: "Simple Gagnant (int.)", abbr: "SG", color: "#059669", ordre: 2 },
  e_simple_place:              { label: "Simple Placé", abbr: "SP", color: "#0EA5E9", ordre: 3 },
  simple_place_international:   { label: "Simple Placé (int.)", abbr: "SP", color: "#0EA5E9", ordre: 4 },
  e_couple_gagnant:            { label: "Couplé Gagnant", abbr: "CG", color: "#7C3AED", ordre: 5 },
  e_couple_place:              { label: "Couplé Placé", abbr: "CP", color: "#8B5CF6", ordre: 6 },
  e_couple_ordre:              { label: "Couplé Ordre", abbr: "CO", color: "#6D28D9", ordre: 7 },
  couple_ordre_international:   { label: "Couplé Ordre (int.)", abbr: "CO", color: "#6D28D9", ordre: 8 },
  e_deux_sur_quatre:           { label: "2 sur 4", abbr: "2/4", color: "#F59E0B", ordre: 9 },
  e_super_quatre:              { label: "Super 4", abbr: "S4", color: "#F59E0B", ordre: 10 },
  e_trio:                      { label: "Trio", abbr: "TRI", color: "#EA580C", ordre: 11 },
  e_trio_ordre:                { label: "Trio Ordre", abbr: "TRO", color: "#C2410C", ordre: 12 },
  e_tierce:                    { label: "Tiercé", abbr: "TIE", color: "#DC2626", ordre: 13 },
  e_quarte_plus:               { label: "Quarté+", abbr: "Q4", color: "#DB2777", ordre: 14 },
  e_quinte_plus:               { label: "Quinté+", abbr: "Q5", color: "#BE185D", ordre: 15 },
  e_multi:                     { label: "Multi", abbr: "MUL", color: "#0891B2", ordre: 16 },
  e_mini_multi:                { label: "Mini Multi", abbr: "mM", color: "#06B6D4", ordre: 17 },
  e_pick5:                     { label: "Pick 5", abbr: "P5", color: "#4F46E5", ordre: 18 },
  eb5:                         { label: "Pick 5 Bonus", abbr: "B5", color: "#6366F1", ordre: 19 },
};

function _rapportAbbr(key: string): string {
  return key.replace(/^e_/, "").split("_").map((w) => w[0]?.toUpperCase() ?? "").join("").slice(0, 3) || "•";
}

function ResultatsSection({ resultats, partants }: {
  resultats: {
    classement: Array<{ numero: number; nom: string; position: number; temps: number | null; reduction_km: number | null }>;
    rapports: Record<string, number> | null;
    rapports_detail: Record<string, Array<{ combinaison: string | null; rapport: number }>> | null;
    temps_gagnant: string | null;
    commentaire: string | null;
    duree_course: number | null;
  };
  partants: Partant[];
}) {
  const podium = [...(resultats.classement || [])].sort((a, b) => a.position - b.position);
  const coteByNum: Record<number, number | null> = {};
  for (const p of partants) coteByNum[p.numero] = p.cote_pmu ?? null;

  const hasRedKm = podium.some((c) => c.reduction_km != null);
  const hasTemps = podium.some((c) => c.temps != null);
  const tempsGagnant = podium[0]?.temps ?? null;
  // 214.82 (s) -> 3'34"82 ; réduction km 76.0 (s/km) -> 1'16"0
  const fmtChrono = (sec: number) => {
    const m = Math.floor(sec / 60), rest = sec - m * 60, si = Math.floor(rest);
    const cc = Math.round((rest - si) * 100);
    return `${m}'${String(si).padStart(2, "0")}"${String(cc).padStart(2, "0")}`;
  };
  const fmtRedKm = (rk: number) => {
    const m = Math.floor(rk / 60), rest = rk - m * 60, si = Math.floor(rest);
    const d = Math.round((rest - si) * 10);
    return `${m}'${String(si).padStart(2, "0")}"${d}`;
  };
  // Écart au vainqueur (réel, depuis le temps) : ~0.17s = 1 longueur (trot/plat).
  const fmtEcart = (c: { position: number; temps: number | null }) => {
    if (c.position === 1) return "—";
    if (c.temps == null || tempsGagnant == null) return "";
    const d = c.temps - tempsGagnant;
    if (d <= 0) return "";
    const longueurs = d / 0.17;
    return longueurs < 10 ? `+${longueurs.toFixed(1)} long.` : `+${d.toFixed(1)}s`;
  };
  const rowTint = (pos: number) =>
    pos === 1 ? "bg-amber-50/80" : pos === 2 ? "bg-slate-100/70" : pos === 3 ? "bg-orange-50/70" : "";
  const medalBox = (pos: number) =>
    pos === 1 ? "bg-amber-100 text-amber-700" : pos === 2 ? "bg-slate-200 text-slate-600"
    : pos === 3 ? "bg-orange-100 text-orange-700" : "bg-muted text-muted-foreground";

  const rapportsTries = resultats.rapports
    ? Object.entries(resultats.rapports)
        .filter(([, v]) => v != null)
        .sort((a, b) => (RAPPORT_META[a[0]]?.ordre ?? 99) - (RAPPORT_META[b[0]]?.ordre ?? 99))
    : [];

  return (
    <div className="mt-4 overflow-hidden rounded-xl border border-brand-emerald/30 bg-gradient-to-br from-brand-emerald/[0.07] to-transparent">
      <div className="flex flex-wrap items-center gap-2 border-b border-brand-emerald/20 px-4 py-3">
        <h2 className="flex items-center gap-2 text-base font-bold">Arrivée officielle</h2>
        {(tempsGagnant != null || resultats.temps_gagnant) && (
          <span className="text-xs text-muted-foreground">
            Chrono {tempsGagnant != null ? fmtChrono(tempsGagnant) : resultats.temps_gagnant}
            {podium[0]?.reduction_km != null ? ` · réd. ${fmtRedKm(podium[0].reduction_km)}/km` : ""}
          </span>
        )}
      </div>

      {/* Classement */}
      <div className="overflow-x-auto px-2 py-2">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wide text-muted-foreground">
              <th className="px-2 py-1.5 font-medium">Pos.</th>
              <th className="px-2 py-1.5 font-medium">N°</th>
              <th className="px-2 py-1.5 font-medium">Cheval</th>
              {hasTemps && <th className="px-2 py-1.5 text-right font-medium">Écart</th>}
              <th className="px-2 py-1.5 text-right font-medium">Cote finale</th>
              <th className="px-2 py-1.5 text-right font-medium">{hasRedKm ? "Réd. km" : "Temps"}</th>
            </tr>
          </thead>
          <tbody>
            {podium.map((c) => {
              const cote = coteByNum[c.numero];
              const temps = c.reduction_km != null ? fmtRedKm(c.reduction_km)
                : c.temps != null ? fmtChrono(c.temps) : "—";
              return (
                <tr key={c.numero} className={cn("rounded-lg", rowTint(c.position), c.position <= 3 && "font-semibold")}>
                  <td className="px-2 py-2">
                    <span className={cn("inline-flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold tabular-nums", medalBox(c.position))}>
                      {c.position}
                    </span>
                  </td>
                  <td className="px-2 py-2 tabular-nums">{c.numero}</td>
                  <td className="px-2 py-2">{c.nom}</td>
                  {hasTemps && (
                    <td className="px-2 py-2 text-right font-mono tabular-nums text-muted-foreground">
                      {fmtEcart(c)}
                    </td>
                  )}
                  <td className="px-2 py-2 text-right font-mono tabular-nums">
                    {cote != null ? cote.toFixed(1) : "—"}
                  </td>
                  <td className="px-2 py-2 text-right font-mono tabular-nums text-muted-foreground">
                    {temps}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {(() => {
          const nbRunners = partants.filter((p) => !p.non_partant).length;
          // Arrivée manifestement tronquée (peu de classés vs partants) → on le dit.
          if (nbRunners >= 6 && podium.length > 0 && podium.length <= 4 && podium.length < nbRunners) {
            return (
              <p className="px-2 pt-1 text-[11px] text-amber-600">
                ⚠️ Arrivée partielle — seuls les {podium.length} premiers ont été publiés par la source (sur {nbRunners} partants).
              </p>
            );
          }
          return null;
        })()}
      </div>

      {/* Rapports PMU — détail RÉEL complet publié (par cheval / par combinaison) */}
      {(() => {
        // Formate une combinaison : "8" → "N°8" ; "10-14" → "N°10 + N°14".
        // (Noms de chevaux retirés : trop d'info, débordait des blocs — numéros seuls.)
        const fmtCombo = (combo: string | null): string => {
          if (!combo) return "";
          const parts = combo.split(/[-/]/).map((s) => s.trim()).filter(Boolean);
          return parts.map((n) => `N°${n}`).join(" + ");
        };
        const detail = resultats.rapports_detail;
        const detailTypes = detail
          ? Object.entries(detail)
              .filter(([, arr]) => Array.isArray(arr) && arr.length > 0)
              .sort((a, b) => (RAPPORT_META[a[0]]?.ordre ?? 99) - (RAPPORT_META[b[0]]?.ordre ?? 99))
          : [];

        if (detailTypes.length > 0) {
          return (
            <div className="border-t border-brand-emerald/20 px-4 py-3">
              <p className="mb-2.5 text-xs font-semibold text-muted-foreground">Rapports PMU officiels · gains pour 1&nbsp;€ misé</p>
              <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                {detailTypes.map(([k, arr]) => {
                  const meta = RAPPORT_META[k];
                  const abbr = meta?.abbr ?? _rapportAbbr(k);
                  const color = meta?.color ?? "#6B7280";
                  const label = meta?.label ?? k.replace(/^e_/, "").replace(/_/g, " ");
                  // Placé / Gagnant : 1 ligne par cheval. Combos : on limite l'affichage.
                  const isPlaceOrWin = k.includes("simple");
                  const rows = isPlaceOrWin ? arr : arr.slice(0, 6);
                  return (
                    <div key={k} className="rounded-lg border border-border bg-white p-2.5">
                      <div className="mb-1.5 flex items-center gap-2">
                        <span className="flex h-5 min-w-[1.6rem] items-center justify-center rounded px-1 text-[10px] font-bold text-white" style={{ background: color }}>{abbr}</span>
                        <span className="text-xs font-semibold capitalize">{label}</span>
                      </div>
                      <div className="space-y-0.5">
                        {rows.map((r, i) => (
                          <div key={i} className="flex items-baseline justify-between gap-2 text-xs">
                            <span className="truncate text-muted-foreground">{fmtCombo(r.combinaison) || "—"}</span>
                            <span className="font-bold tabular-nums text-brand-emerald whitespace-nowrap">{r.rapport.toFixed(2)} €</span>
                          </div>
                        ))}
                        {!isPlaceOrWin && arr.length > rows.length && (
                          <p className="text-[10px] text-muted-foreground/60">+ {arr.length - rows.length} autres combinaisons gagnantes</p>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        }
        // Fallback : agrégat (résultats anciens sans détail re-scrapé)
        if (rapportsTries.length > 0) {
          return (
            <div className="border-t border-brand-emerald/20 px-4 py-3">
              <p className="mb-2 text-xs font-semibold text-muted-foreground">Rapports PMU · gains pour 1&nbsp;€ misé</p>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
                {rapportsTries.map(([k, v]) => {
                  const meta = RAPPORT_META[k];
                  const abbr = meta?.abbr ?? _rapportAbbr(k);
                  const color = meta?.color ?? "#6B7280";
                  const label = meta?.label ?? k.replace(/^e_/, "").replace(/_/g, " ");
                  return (
                    <div key={k} className="flex items-center gap-2 rounded-lg border border-border bg-white px-2 py-1.5">
                      <span className="flex h-6 min-w-[1.75rem] flex-shrink-0 items-center justify-center rounded px-1 text-[10px] font-bold tracking-tight text-white" style={{ background: color }}>{abbr}</span>
                      <span className="flex-1 truncate text-xs text-muted-foreground capitalize">{label}</span>
                      <span className="font-bold tabular-nums text-brand-emerald">{Number(v).toFixed(2)} €</span>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        }
        return null;
      })()}

      {/* Commentaire narratif post-course */}
      {resultats.commentaire && (
        <div className="border-t border-brand-emerald/20 px-4 py-3 text-sm leading-relaxed text-foreground">
          <p className="mb-1 text-xs font-semibold text-muted-foreground">Analyse de course</p>
          {resultats.commentaire}
        </div>
      )}
    </div>
  );
}

// ─── Bilan du pronostic (course terminée) ──────────────────────────────────────
// Compare le pronostic FIGÉ avant la course à l'arrivée réelle. Aucune donnée
// recalculée : on lit les Prediction stockées (immuables) + le classement officiel.
function PronosticVerdictSection({ predictions, classement }: {
  predictions: Prediction[];
  classement: Array<{ numero: number; nom: string; position: number }>;
}) {
  const posByNum = new Map<number, number>();
  for (const c of classement) posByNum.set(c.numero, c.position);

  const iaRanked = [...predictions].sort((a, b) => a.rang_predit - b.rang_predit);
  const picks = iaRanked.slice(0, 5);
  const favoriIA = iaRanked[0];

  const gagnant = classement.find((c) => c.position === 1);
  const rangIAduGagnant = gagnant
    ? predictions.find((p) => p.numero === gagnant.numero)?.rang_predit ?? null
    : null;

  const favPos = favoriIA ? posByNum.get(favoriIA.numero) ?? null : null;
  const favGagne = favPos === 1;
  const favPlace = favPos != null && favPos <= 3;
  const gagnantDansTop3IA = rangIAduGagnant != null && rangIAduGagnant <= 3;

  // Verdict global, du meilleur au moins bon
  const verdict = favGagne
    ? { emoji: "🎯", label: "Gagnant trouvé — favori vainqueur", cls: "border-emerald-300 bg-emerald-50 text-emerald-800" }
    : favPlace
    ? { emoji: "✅", label: `Favori placé (${favPos}${favPos === 1 ? "er" : "e"})`, cls: "border-amber-300 bg-amber-50 text-amber-800" }
    : gagnantDansTop3IA
    ? { emoji: "➕", label: `Vainqueur dans le top 3 IA (classé #${rangIAduGagnant})`, cls: "border-blue-300 bg-blue-50 text-blue-800" }
    : { emoji: "❌", label: "Pronostic manqué", cls: "border-rose-300 bg-rose-50 text-rose-800" };

  const pickVerdict = (pos: number | null | undefined) => {
    if (pos == null) return { icon: "⚪", txt: "NP", cls: "text-muted-foreground" };
    if (pos === 1) return { icon: "🥇", txt: "1er", cls: "text-emerald-600 font-semibold" };
    if (pos <= 3) return { icon: "✅", txt: `${pos}e`, cls: "text-amber-600 font-semibold" };
    return { icon: "❌", txt: `${pos}e`, cls: "text-muted-foreground" };
  };

  return (
    <div className="mt-4 rounded-xl border border-brand-blue/30 bg-brand-blue/5 p-4">
      <h2 className="mb-3 flex items-center gap-2 text-base font-bold">
        Bilan du pronostic
        <span className="text-xs font-normal text-muted-foreground">
          · pronostic figé avant la course
        </span>
      </h2>

      <div className={cn("mb-3 inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm font-semibold", verdict.cls)}>
        {verdict.label}
      </div>

      {gagnant && (
        <p className="mb-3 text-sm text-muted-foreground">
          Vainqueur : <span className="font-semibold text-foreground">N°{gagnant.numero} {gagnant.nom}</span>
          {rangIAduGagnant != null
            ? <> — l&apos;algorithme le classait <span className="font-semibold text-foreground">#{rangIAduGagnant}</span></>
            : <> — non pronostiqué par l&apos;algorithme</>}
        </p>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground border-b">
              <th className="py-1 pr-2">Pronostic</th>
              <th className="py-1 pr-2">N°</th>
              <th className="py-1 pr-2">Cheval</th>
              <th className="py-1 pr-2 text-right">Proba top-3</th>
              <th className="py-1 pr-2 text-right">Arrivée réelle</th>
            </tr>
          </thead>
          <tbody>
            {picks.map((p) => {
              const pos = posByNum.get(p.numero);
              const pv = pickVerdict(pos);
              return (
                <tr key={p.participation_id} className="border-b border-border/40">
                  <td className="py-1 pr-2 font-bold tabular-nums">#{p.rang_predit}</td>
                  <td className="py-1 pr-2 tabular-nums">{p.numero}</td>
                  <td className="py-1 pr-2">{p.nom_cheval}</td>
                  <td className="py-1 pr-2 text-right tabular-nums text-muted-foreground">
                    {(p.proba_top3 * 100).toFixed(0)}%
                  </td>
                  <td className={cn("py-1 pr-2 text-right tabular-nums", pv.cls)}>
                    {pv.icon} {pv.txt}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Bilan du plan de mise 20€ (course terminée) ───────────────────────────────
// Rejoue le plan de mise (20€) sur les pronostics réels et le règle contre le
// résultat officiel (rapports PMU réels). Indique si le pari serait passé + le gain.
interface BilanData {
  paris: Array<{ type: string; niveau: string; chevaux: { numero: number; nom: string }[]; mise: number; gagne: boolean; statut: "gagne" | "perdu" | "en_attente"; rapport_reel: number | null; gain: number | null; note: string | null }>;
  nb_paris: number; nb_gagnes: number; nb_en_attente: number; total_mise: number; total_gain: number; net: number; roi: number; en_attente: boolean; provisoire: boolean;
}
interface BilanProfil {
  profil: "conservateur" | "equilibre" | "agressif";
  profil_label: string;
  mode_adaptatif: string;
  esperance_gain: number;
  bilan: BilanData;
  verdict: "gagnant" | "perdant" | "en_attente";
  source?: "fige" | "simulation";   // "fige" = plan réellement figé avant départ (= palmarès)
  fige_le?: string | null;          // horodatage du gel pré-course
  regle_le?: string | null;         // horodatage du règlement post-arrivée
}
interface BilanResp {
  montant: number;
  source?: "fige" | "simulation";
  bilan: BilanData;
  bilans_profils?: BilanProfil[];
  comparaison: { predicted_top3: number[]; predicted_top5?: number[]; actual_top3: number[]; actual_top5?: number[]; gagnant_reel: number | null; rang_predit_gagnant: number | null; overlap_top3: number; modele_a_vu_gagnant: boolean };
  verdict: "gagnant" | "perdant" | "en_attente";
}

/* Confrontations directes : table d'affichage retirée (l'historique des duels
   reste calculé côté backend — features `conf_*` — et nourrit le modèle et la
   narrative, mais n'est plus montré tel quel à l'utilisateur). */

/* Tableau de détail d'un bilan (paris réglés d'un profil) */
function BilanDetail({ bilan }: { bilan: BilanData }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-muted-foreground border-b">
            <th className="py-1 pr-2">Pari</th>
            <th className="py-1 pr-2">Chevaux</th>
            <th className="py-1 pr-2 text-right">Mise</th>
            <th className="py-1 pr-2 text-right">Résultat</th>
          </tr>
        </thead>
        <tbody>
          {bilan.paris.map((p, i) => (
            <tr key={i} className="border-b border-border/40">
              <td className="py-1 pr-2 font-medium">{p.type}</td>
              <td className="py-1 pr-2 text-muted-foreground">{p.chevaux.map((c) => `N°${c.numero}`).join(" + ")}</td>
              <td className="py-1 pr-2 text-right tabular-nums">{p.mise.toFixed(0)}€</td>
              <td className="py-1 pr-2 text-right tabular-nums">
                {p.statut === "gagne"
                  ? <span className="text-emerald-600 font-semibold">✓ +{(p.gain ?? 0).toFixed(2)}€</span>
                  : p.statut === "en_attente"
                  ? <span className="text-amber-600 font-semibold" title="Rapport PMU pas encore publié">Gagné · rapport en attente</span>
                  : <span className="text-muted-foreground">✗ perdu</span>}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t font-semibold">
            <td className="py-1.5 pr-2" colSpan={2}>Total ({bilan.nb_gagnes}/{bilan.nb_paris} gagné{bilan.nb_gagnes > 1 ? "s" : ""})</td>
            <td className="py-1.5 pr-2 text-right tabular-nums">{bilan.total_mise.toFixed(0)}€</td>
            <td className={cn("py-1.5 pr-2 text-right tabular-nums", bilan.total_gain > 0 ? "text-emerald-600" : "text-muted-foreground")}>
              {bilan.total_gain.toFixed(2)}€
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

const PROFIL_TAB_META: Record<string, { emoji: string; label: string }> = {
  conservateur: { emoji: "🛡️", label: "Prudent" },
  equilibre: { emoji: "⚖️", label: "Modéré" },
  agressif: { emoji: "🔥", label: "Risqué" },
};

function BilanMiseSection({ courseId }: { courseId: string }) {
  const [data, setData] = useState<BilanResp | null>(null);
  const [state, setState] = useState<"loading" | "ok" | "error">("loading");
  const [sel, setSel] = useState<"conservateur" | "equilibre" | "agressif">("equilibre");

  useEffect(() => {
    let alive = true;
    api.get(`/courses/${courseId}/bilan-pronostic?montant=10`)
      .then((r) => { if (alive) { setData(r.data); setState("ok"); } })
      .catch(() => { if (alive) setState("error"); });
    return () => { alive = false; };
  }, [courseId]);

  if (state !== "ok" || !data) return null;
  const { comparaison: cmp } = data;

  // Bilans par profil (fallback : bilan unique legacy mappé sur "modéré")
  const profils: BilanProfil[] = data.bilans_profils && data.bilans_profils.length
    ? data.bilans_profils
    : [{ profil: "equilibre", profil_label: "Modéré", mode_adaptatif: "normal", esperance_gain: 0, bilan: data.bilan, verdict: data.verdict, source: data.source }];
  const cur = profils.find((b) => b.profil === sel) ?? profils[0];
  const bilan = cur.bilan;

  const vCfg = cur.verdict === "gagnant"
    ? { label: "Plan gagnant", cls: "border-emerald-300 bg-emerald-50 text-emerald-800" }
    : cur.verdict === "perdant"
    ? { label: "Plan perdant", cls: "border-rose-300 bg-rose-50 text-rose-800" }
    : { label: `En attente de ${bilan.nb_en_attente} rapport${bilan.nb_en_attente > 1 ? "s" : ""} PMU`, cls: "border-amber-300 bg-amber-50 text-amber-800" };

  return (
    <div className="mt-4 rounded-xl border border-brand-gold/30 bg-brand-gold/5 p-4">
      <h2 className="mb-1 flex flex-wrap items-center gap-2 text-base font-bold">
        Bilan du plan de mise — {data.montant}€
        <span className="text-xs font-normal text-muted-foreground">
          {cur.source === "fige"
            ? "· plan figé AVANT le départ, réglé sur l'arrivée réelle (par profil)"
            : "· simulation rétrospective sur l'arrivée réelle, par profil"}
        </span>
        {cur.source === "fige" && (
          <span
            title={cur.fige_le ? `Plan figé le ${new Date(cur.fige_le).toLocaleString("fr-FR")}, avant le départ — identique au palmarès` : "Plan figé avant le départ — identique au palmarès"}
            className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-semibold bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200"
          >
            ✓ Figé avant départ
          </span>
        )}
      </h2>

      {/* Onglets profils — chaque profil = méthode de jeu différente */}
      {profils.length > 1 && (
        <div className="my-3 grid grid-cols-3 gap-1.5">
          {profils.map((b) => {
            const meta = PROFIL_TAB_META[b.profil] ?? { emoji: "•", label: b.profil_label };
            const net = b.bilan.net;
            return (
              <button
                key={b.profil}
                onClick={() => setSel(b.profil)}
                className={cn(
                  "rounded-lg border px-2 py-1.5 text-left transition-colors",
                  sel === b.profil ? "border-brand-gold bg-brand-gold/10" : "border-border hover:border-brand-gold/40"
                )}
              >
                <div className="text-[11px] font-semibold">{meta.emoji} {meta.label}</div>
                <div className={cn("text-xs font-mono font-bold tabular-nums",
                  b.verdict === "en_attente" ? "text-amber-600" : net >= 0 ? "text-emerald-600" : "text-rose-600")}>
                  {b.verdict === "en_attente" ? "⏳" : `${net >= 0 ? "+" : ""}${net.toFixed(0)}€`}
                </div>
              </button>
            );
          })}
        </div>
      )}

      {/* Verdict + net du profil sélectionné */}
      <div className="my-3 flex flex-wrap items-center gap-3">
        <div className={cn("inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm font-semibold", vCfg.cls)}>
          {vCfg.label}
        </div>
        <div className="text-sm">
          <span className="text-muted-foreground">Résultat net{bilan.provisoire ? " (provisoire)" : ""} :</span>{" "}
          <span className={cn("font-bold tabular-nums", bilan.net >= 0 ? "text-emerald-600" : "text-rose-600")}>
            {bilan.net >= 0 ? "+" : ""}{bilan.net.toFixed(2)}€
          </span>
          <span className="text-muted-foreground"> · ROI </span>
          <span className={cn("font-bold tabular-nums", bilan.roi >= 0 ? "text-emerald-600" : "text-rose-600")}>
            {bilan.roi >= 0 ? "+" : ""}{bilan.roi}%
          </span>
        </div>
      </div>

      {/* Comparaison prono vs réel — top-5 (couvre 2sur4 / Quarté / Quinté) */}
      {(() => {
        const predN = cmp.predicted_top5 ?? cmp.predicted_top3;
        const realN = cmp.actual_top5 ?? cmp.actual_top3;
        const realSet = new Set(realN);
        const predSet = new Set(predN);
        const overlap5 = predN.filter((n) => realSet.has(n)).length;
        return (
          <>
            <div className="mb-2 grid gap-2 sm:grid-cols-2 text-xs">
              <div className="rounded-lg bg-white/70 ring-1 ring-border/60 p-2.5">
                <p className="mb-1.5 font-semibold text-muted-foreground">Top-{predN.length} pronostiqué (modèle)</p>
                <div className="flex flex-wrap gap-1.5">
                  {predN.map((n, i) => {
                    const hit = realSet.has(n);
                    return (
                      <span key={n} className={cn("inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-bold ring-1 tabular-nums",
                        hit ? "bg-emerald-50 ring-emerald-300 text-emerald-700" : "bg-blue-50 ring-blue-200 text-blue-700")}>
                        <span className="text-[9px] font-normal text-muted-foreground">{i + 1}</span>N°{n}
                      </span>
                    );
                  })}
                </div>
              </div>
              <div className="rounded-lg bg-white/70 ring-1 ring-border/60 p-2.5">
                <p className="mb-1.5 font-semibold text-muted-foreground">Arrivée réelle (top-{realN.length})</p>
                <div className="flex flex-wrap gap-1.5">
                  {realN.map((n, i) => {
                    const winner = i === 0;
                    const seen = predSet.has(n);
                    return (
                      <span key={n} className={cn("inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-bold ring-1 tabular-nums",
                        winner ? "bg-amber-100 ring-amber-400 text-amber-800"
                          : seen ? "bg-emerald-50 ring-emerald-300 text-emerald-700"
                          : "bg-gray-50 ring-gray-200 text-gray-600")}>
                        <span className="text-[9px] font-normal text-muted-foreground">{i + 1}.</span>N°{n}
                      </span>
                    );
                  })}
                </div>
              </div>
            </div>
            {/* Légende + bilan modèle */}
            <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-muted-foreground">
              <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm bg-amber-300 ring-1 ring-amber-400" />Vainqueur</span>
              <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm bg-emerald-200 ring-1 ring-emerald-300" />Trouvé par le modèle</span>
              {cmp.gagnant_reel != null && (
                <span className="text-muted-foreground">
                  · Vainqueur N°{cmp.gagnant_reel}{" "}
                  {cmp.modele_a_vu_gagnant
                    ? <span className="text-emerald-700 font-medium">vu (rang {cmp.rang_predit_gagnant})</span>
                    : <span className="text-rose-700 font-medium">manqué{cmp.rang_predit_gagnant ? ` (rang ${cmp.rang_predit_gagnant})` : ""}</span>}
                  {" · "}<span className="font-medium text-gray-700">{overlap5}/5</span> chevaux trouvés
                </span>
              )}
            </div>
          </>
        );
      })()}

      {/* Détail des paris du profil sélectionné */}
      <BilanDetail bilan={bilan} />

      <p className="mt-2 text-[10px] text-muted-foreground/70">
        {cur.source === "fige"
          ? "Ce plan a été RÉELLEMENT figé avant le départ (un par profil : Prudent = placé fréquent · Modéré = équilibré · Risqué = gros gains), puis réglé aux rapports PMU définitifs réels — c'est le même prono que celui compté au palmarès. Jouez responsable."
          : "Aucun plan figé pour ce profil sur cette course (antérieure au gel automatique) : simulation rétrospective de la méthode, réglée aux rapports PMU réels. Jouez responsable."}
      </p>
    </div>
  );
}

// ─── Marché des cotes (live) ────────────────────────────────────────────────────
// Affiché uniquement avant/pendant la course. Poll les cotes PMU toutes les 5 s.
// Une carte par cheval : cote actuelle + variation + graphe individuel d'évolution.
function Sparkline({ data, color }: { data: number[]; color: string }) {
  if (data.length < 2) return <div className="h-11" />;
  const min = Math.min(...data), max = Math.max(...data);
  const rng = max - min || 1;
  const pts = data
    .map((v, i) => `${(i / (data.length - 1)) * 100},${27 - ((v - min) / rng) * 25}`)
    .join(" ");
  const area = `0,28 ${pts} 100,28`;
  const lastY = 27 - ((data[data.length - 1] - min) / rng) * 25;
  return (
    <svg viewBox="0 0 100 28" preserveAspectRatio="none" className="h-11 w-full">
      <polygon points={area} fill={color} fillOpacity={0.1} />
      <polyline points={pts} fill="none" stroke={color} strokeWidth={1.5}
        vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={100} cy={lastY} r={2} fill={color} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function MarcheCotes({ courseId, partants, statut }: { courseId: string; partants: Partant[]; statut: string }) {
  const [chartData, setChartData] = useState<Array<Record<string, number | string>>>([]);
  const isLive = statut !== "termine";

  useEffect(() => {
    let alive = true;
    const pidToNum: Record<string, number> = {};
    for (const p of partants) pidToNum[p.participation_id] = p.numero;

    // 1) Base : historique des cotes déjà enregistrées (granularité scraper)
    api.get(`/courses/${courseId}/cotes-historique`)
      .then((res) => {
        if (!alive) return;
        const map: Record<string, Record<string, number>> = {};
        for (const r of res.data) {
          const t = new Date(r.time).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
          const num = pidToNum[r.participation_id];
          if (num == null) continue;
          (map[t] ||= {})[`N°${num}`] = r.cote;
        }
        const base = Object.entries(map).map(([time, vals]) => ({ time, ...vals }));
        setChartData((prev) => (prev.length > base.length ? prev : base));
      })
      .catch(() => {});

    // 2) Live : cotes PMU en direct toutes les 5 s, append en continu
    const poll = () => {
      api.get(`/courses/${courseId}/cotes-live`)
        .then((res) => {
          if (!alive) return;
          const cotes: Array<{ numero: number; cote: number }> = res.data?.cotes ?? [];
          if (!cotes.length) return;
          const label = new Date(res.data.time).toLocaleTimeString("fr-FR", {
            hour: "2-digit", minute: "2-digit", second: "2-digit",
          });
          setChartData((prev) => {
            const lastPt = prev[prev.length - 1] || {};
            const point: Record<string, number | string> = { time: label };
            // report les dernières cotes connues (lignes continues)
            for (const k of Object.keys(lastPt)) if (k !== "time") point[k] = lastPt[k];
            for (const c of cotes) point[`N°${c.numero}`] = c.cote;
            // éviter un doublon strict (même seconde)
            if (lastPt.time === label) {
              const copy = prev.slice(0, -1);
              return [...copy, point];
            }
            const next = [...prev, point];
            return next.length > 200 ? next.slice(next.length - 200) : next;
          });
        })
        .catch(() => {});
    };

    let iv: ReturnType<typeof setInterval> | undefined;
    if (isLive) {
      poll();
      iv = setInterval(poll, 5000);
    }
    return () => { alive = false; if (iv) clearInterval(iv); };
  }, [courseId, partants, isLive]);

  if (chartData.length < 2) return null;

  // Séries de cote par numéro (chevaux ayant une cote publiée)
  const seriesByNum: Record<number, number[]> = {};
  const last = chartData[chartData.length - 1];
  for (const k of Object.keys(last)) {
    if (k === "time" || typeof last[k] !== "number") continue;
    const num = parseInt(k.replace("N°", ""), 10);
    seriesByNum[num] = chartData.map((d) => d[k]).filter((v): v is number => typeof v === "number");
  }

  // TOUS les partants — ceux sans cote publiée affichés en "non publiée" (pas d'invention)
  const runners = partants.map((p) => {
    const series = seriesByNum[p.numero];
    if (series && series.length >= 2) {
      const open = series[0];
      const cur = series[series.length - 1];
      return {
        num: p.numero, nom: p.nom_cheval, hasData: true, series, open, cur,
        delta: open ? (cur - open) / open : 0, lo: Math.min(...series), hi: Math.max(...series),
      };
    }
    return { num: p.numero, nom: p.nom_cheval, hasData: false, series: [] as number[], open: 0, cur: 0, delta: 0, lo: 0, hi: 0 };
  }).sort((a, b) => {
    if (a.hasData !== b.hasData) return a.hasData ? -1 : 1;
    return a.hasData ? a.cur - b.cur : a.num - b.num;
  });

  const nbSansCote = runners.filter((r) => !r.hasData).length;
  const colorFor = (delta: number) => (delta < -0.001 ? "#10B981" : delta > 0.001 ? "#EF4444" : "#9CA3AF");

  return (
    <Card>
      <CardHeader className="pb-1">
        <CardTitle className="text-sm flex items-center gap-2">
          <TrendingUp className="h-4 w-4 text-brand-gold" />
          Marché des cotes
          {isLive ? (
            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-600">
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
              </span>
              EN DIRECT
            </span>
          ) : (
            <span className="text-xs font-normal text-muted-foreground">— final</span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {/* Une carte par cheval — graphe individuel d'évolution de la cote */}
        <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
          {runners.map((r) => {
            if (!r.hasData) {
              return (
                <div key={r.num} className="rounded-xl border border-dashed border-border bg-muted/20 p-3">
                  <div className="flex items-center gap-2">
                    <span className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-lg bg-gray-300 text-xs font-bold text-white tabular-nums">{r.num}</span>
                    <p className="truncate text-sm font-semibold text-muted-foreground">{r.nom}</p>
                  </div>
                  <div className="mt-3 flex h-11 items-center justify-center text-[11px] text-muted-foreground/60">
                    Cote non publiée par le PMU
                  </div>
                </div>
              );
            }
            const c = colorFor(r.delta);
            const up = r.delta > 0.001;
            const flat = Math.abs(r.delta) <= 0.001;
            return (
              <div key={r.num} className="rounded-xl border border-border bg-white p-3 shadow-sm transition-shadow hover:shadow-md">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-lg bg-gray-900 text-xs font-bold text-white tabular-nums">{r.num}</span>
                    <p className="truncate text-sm font-semibold">{r.nom}</p>
                  </div>
                  <div className="flex-shrink-0 text-right">
                    <p className="text-lg font-bold leading-none tabular-nums">{r.cur.toFixed(1)}</p>
                    <p className="mt-0.5 text-[11px] font-bold tabular-nums" style={{ color: c }}>
                      {flat ? "—" : `${up ? "▲" : "▼"} ${Math.abs(r.delta * 100).toFixed(0)}%`}
                    </p>
                  </div>
                </div>
                <div className="mt-2">
                  <Sparkline data={r.series} color={c} />
                </div>
                <div className="mt-1 flex items-center justify-between text-[10px] text-muted-foreground/80">
                  <span>Ouv. <span className="tabular-nums font-medium">{r.open.toFixed(1)}</span></span>
                  <span className="tabular-nums">{r.lo.toFixed(1)} – {r.hi.toFixed(1)}</span>
                </div>
              </div>
            );
          })}
        </div>

        <p className="mt-3 text-[10px] text-muted-foreground/70">
          <span className="font-semibold text-emerald-600">▼ vert</span> = cote en baisse (cheval de plus en plus joué) ·
          <span className="font-semibold text-rose-500"> ▲ rouge</span> = cote qui monte (délaissé).
          {isLive && " Cotes PMU en direct — rafraîchies toutes les 5 s."}
          {nbSansCote > 0 && ` ${nbSansCote} partant${nbSansCote > 1 ? "s" : ""} sans cote publiée par le PMU.`}
        </p>
      </CardContent>
    </Card>
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
  const [expandedPartant, setExpandedPartant] = useState<string | null>(null);
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
    coverage_jackpot?: Array<{
      niveau: string; type_pari: string; couverture: string;
      chevaux: Array<{ numero: number; nom: string; cote: number }>;
      proba_gain: number; nb_combinaisons: number; flexi_pct: number;
      mise_unitaire: number; cout_total: number; rapport_estime: number;
      gain_potentiel: number; ev: number; edge: number; texte_explication: string;
    }>;
    coup_a_tenter?: {
      niveau: string; type_pari: string;
      chevaux: Array<{ numero: number; nom: string; cote: number }>;
      proba_gain: number; rapport_estime: number; ev: number; edge: number;
      texte_explication: string;
    } | null;
    chevaux_a_eviter?: Array<{
      numero: number; nom: string; cote: number | null; raisons: string[];
      justification?: string; verdict?: string | null;
      proba_victoire?: number; proba_top3?: number; proba_marche?: number; edge?: number;
      facteurs_negatifs?: Array<{ label: string; detail: string; categorie?: string }>;
    }>;
    detection_outsider?: {
      score: number; course_a_outsider: boolean;
      candidats: Array<{
        numero: number; nom: string; cote: number;
        proba_modele: number; proba_marche: number; proba_top3?: number;
        edge: number; ratio_valeur?: number; verdict?: string | null;
        raisons: string[]; justification?: string; points_vigilance?: string[];
        facteurs_positifs?: Array<{ label: string; detail: string; categorie?: string }>;
      }>;
      signaux: string[];
      taux_surprises_historique: number | null;
    };
  } | null>(null);

  const [resultats, setResultats] = useState<{
    classement: Array<{ numero: number; nom: string; position: number; temps: number | null; reduction_km: number | null }>;
    rapports: Record<string, number> | null;
    rapports_detail: Record<string, Array<{ combinaison: string | null; rapport: number }>> | null;
    temps_gagnant: string | null;
    commentaire: string | null;
    duree_course: number | null;
  } | null>(null);

  const { partants: liveCotes, connected: wsConnected } = useCotesLive(
    id,
    course?.statut === "en_cours"
  );

  // Cotes LIVE par HTTP (même source que le widget « Marché des cotes EN DIRECT »),
  // pollées dès « à venir » (le WS n'est branché qu'« en cours » → la table restait
  // sur la cote stockée périmée). Garantit : table = marché = estimatif, tout corrélé.
  const [liveCoteHttp, setLiveCoteHttp] = useState<Record<number, number>>({});
  useEffect(() => {
    if (!course || !["a_venir", "en_cours"].includes(course.statut)) return;
    let alive = true;
    const poll = () =>
      api.get(`/courses/${id}/cotes-live`)
        .then((res) => {
          if (!alive) return;
          const cotes: Array<{ numero: number; cote: number }> = res.data?.cotes ?? [];
          if (!cotes.length) return;
          const m: Record<number, number> = {};
          for (const c of cotes) m[c.numero] = c.cote;
          setLiveCoteHttp(m);
        })
        .catch(() => {});
    poll();
    const iv = setInterval(poll, 5000);
    return () => { alive = false; clearInterval(iv); };
  }, [id, course?.statut]);

  // Chargement + rafraîchissement auto du statut. Sans poll, une fiche ouverte
  // en "À venir"/"En cours" ne passait JAMAIS à "Terminée" sans recharger (fetch
  // unique) → l'arrivée ne s'affichait pas pour un onglet resté ouvert.
  const courseLoadedRef = useRef(false);
  useEffect(() => {
    courseLoadedRef.current = false;
    let cancelled = false;
    let iv: ReturnType<typeof setInterval> | null = null;
    const load = () =>
      coursesApi.course(id)
        .then((res) => {
          if (cancelled) return;
          courseLoadedRef.current = true;
          setCourse(res.data);
          if (res.data.statut === "termine" && iv) { clearInterval(iv); iv = null; }
        })
        .catch(() => { if (!cancelled && !courseLoadedRef.current) toast.error("Course introuvable"); })
        .finally(() => { if (!cancelled) setLoadingCourse(false); });
    load();
    iv = setInterval(load, 60000); // s'arrête dès que la course est terminée
    return () => { cancelled = true; if (iv) clearInterval(iv); };
  }, [id]);

  useEffect(() => {
    if (!user || ["free", "decouverte"].includes(user.plan)) return;
    setLoadingPred(true);
    predictionsApi.get(id, 100)
      .then((res) => setPredictions(res.data.predictions))
      .catch(() => setPredictions(null))
      .finally(() => setLoadingPred(false));
  }, [id, user]);

  // Load narrative analysis (Standard+) — aussi post-course (facteurs par cheval
  // = transparence "le modèle analyse bien plus que la cote").
  useEffect(() => {
    if (!user || ["free", "decouverte"].includes(user.plan) || !course) return;
    api.get(`/courses/${id}/analyse`)
      .then((res) => setAnalysis(res.data))
      .catch(() => {}); // fail silently
  }, [id, user, course, predictions]); // refresh après prédictions

  // Résultats (arrivée + rapports + commentaire). La course passe "Terminée"
  // AVANT que le PMU ne publie l'arrivée (5–10 min de décalage de scrape) : un
  // fetch unique tombait en 404 → l'arrivée n'apparaissait JAMAIS sans recharger.
  // On réessaie donc tant que la course est terminée et l'arrivée absente.
  useEffect(() => {
    if (!course || course.statut !== "termine" || resultats) return;
    let cancelled = false;
    let iv: ReturnType<typeof setInterval> | null = null;
    const load = () =>
      coursesApi.resultats(id)
        .then((res) => {
          if (cancelled) return;
          setResultats(res.data);
          if (iv) { clearInterval(iv); iv = null; }
        })
        .catch(() => {}); // arrivée pas encore publiée → on retentera
    load();
    iv = setInterval(load, 30000); // stoppé dès que l'arrivée est récupérée
    return () => { cancelled = true; if (iv) clearInterval(iv); };
  }, [id, course, resultats]);


  async function handleTriggerPred() {
    setTriggeringPred(true);
    try {
      await predictionsApi.trigger(id, 100);
      toast.success("Analyse algorithme lancée — résultats dans quelques secondes.");
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

  // Merge live cotes : HTTP (fiable, = widget Marché) PRIME sur le WS.
  const liveCoteMap: Record<number, number | null> = {};
  if (liveCotes.length > 0) {
    for (const p of liveCotes as Array<{ numero: number; cote_pmu: number | null }>) {
      liveCoteMap[p.numero] = p.cote_pmu;
    }
  }
  for (const [num, cote] of Object.entries(liveCoteHttp)) {
    liveCoteMap[Number(num)] = cote;
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
              {(() => {
                const m = course.course_id.match(/R(\d+)C(\d+)$/);
                const r = course.numero_reunion ?? (m ? Number(m[1]) : null);
                const c = course.numero ?? (m ? Number(m[2]) : null);
                return r && c ? (
                  <span className="inline-flex items-center rounded-md bg-foreground px-2.5 py-1 font-mono text-sm font-bold tracking-tight text-background tabular-nums">
                    R{r}<span className="opacity-50 mx-0.5">·</span>C{c}
                  </span>
                ) : null;
              })()}
              <h1 className="text-xl font-bold">{course.nom || `Course ${course.course_id.match(/R\d+C\d+$/)?.[0] ?? course.course_id}`}</h1>
              {course.est_quinte && <Badge variant="gold" className="animate-pulse-slow">Quinté+</Badge>}
              {course.est_quarte && <Badge variant="gold">Quarté+</Badge>}
              {course.est_tierce && <Badge variant="secondary">Tiercé</Badge>}
              <Badge variant={course.statut === "en_cours" ? "success" : course.statut === "termine" ? "secondary" : "warning"}>
                {course.statut === "en_cours" ? "En cours" : course.statut === "termine" ? "Terminée" : "À venir"}
              </Badge>
              {course.statut === "a_venir" && course.prono_fige && (
                <Badge variant="secondary" title="À moins de 10 min du départ, le pronostic est figé. Les cotes affichées continuent d'évoluer.">
                  Pronostic figé
                </Badge>
              )}
              {wsConnected && (
                <span className="flex items-center gap-1 text-[10px] font-semibold text-brand-emerald">
                  <span className="h-1.5 w-1.5 rounded-full bg-brand-emerald animate-pulse" /> En direct
                </span>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm text-muted-foreground">
              <span className="font-semibold text-foreground">{course.discipline}</span>
              <span className="inline-flex items-center gap-1.5"><MapPin className="h-3.5 w-3.5 text-muted-foreground/60" /> {course.hippodrome_nom}</span>
              <span className="inline-flex items-center gap-1.5"><Ruler className="h-3.5 w-3.5 text-muted-foreground/60" /> {course.distance} m</span>
              <span className="inline-flex items-center gap-1.5"><Users className="h-3.5 w-3.5 text-muted-foreground/60" /> {course.nb_partants} partants</span>
              <span className="inline-flex items-center gap-1.5"><Clock className="h-3.5 w-3.5 text-muted-foreground/60" /> {formatDateTime(course.date_heure)}</span>
              {course.terrain_officiel && <span className="inline-flex items-center gap-1.5"><Activity className="h-3.5 w-3.5 text-muted-foreground/60" /> {course.terrain_officiel}</span>}
              {/* allocation stockée en centimes → euros */}
              {course.allocation ? (
                <span className="inline-flex items-center gap-1.5"><Trophy className="h-3.5 w-3.5 text-muted-foreground/60" /> {Math.round(course.allocation / 100).toLocaleString("fr-FR")} € d&apos;allocation</span>
              ) : null}
              {course.montant_offert_1er != null && course.montant_offert_1er > 0 && (
                <span className="inline-flex items-center gap-1.5"><Trophy className="h-3.5 w-3.5 text-brand-gold" /> {course.montant_offert_1er.toLocaleString("fr-FR")} € au gagnant</span>
              )}
              {course.categorie_particularite && (
                <span className="inline-flex items-center gap-1.5 capitalize"><Tag className="h-3.5 w-3.5 text-muted-foreground/60" /> {course.categorie_particularite.replace(/_/g, " ").toLowerCase()}</span>
              )}
              {course.meteo?.temperature && (
                <span className="inline-flex items-center gap-1.5"><Cloud className="h-3.5 w-3.5 text-muted-foreground/60" /> {course.meteo.temperature}°C</span>
              )}
            </div>
            {/* Conditions de course (texte officiel PMU) */}
            {course.conditions_texte && (
              <details className="mt-2 text-xs text-muted-foreground">
                <summary className="cursor-pointer font-semibold hover:text-foreground select-none inline-flex items-center gap-1.5">
                  <FileText className="h-3.5 w-3.5" /> Conditions de la course
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
                    Avantage {course.avantage_couloir === "interieur" ? "intérieur" : "extérieur"}
                  </span>
                )}
              </div>
            )}
          </div>

        </div>

        {/* ── STAT HERO : chiffres clés en avant (look "salle de marché") ── */}
        {course.statut !== "termine" && predictions && predictions.length > 0 && (() => {
          const fav = predictions.find((p) => p.rang_predit === 1) ?? predictions[0];
          const favCote = liveCoteMap[fav.numero] ?? fav.cote_pmu;
          return (
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-2.5 sm:gap-3 mt-4 pt-4 border-t border-border/60">
              {/* Favori */}
              <div className="rounded-xl border border-brand-gold/30 bg-gradient-to-br from-brand-gold/[0.08] to-transparent p-3">
                <p className="text-overline text-muted-foreground">Favori</p>
                <p className="mt-0.5 text-[13px] font-bold truncate">N°{fav.numero} {fav.nom_cheval}</p>
                <div className="mt-1 flex items-baseline gap-1.5">
                  <span className="text-2xl font-bold tabular-nums text-brand-gold leading-none">{Math.round(fav.proba_top1 * 100)}%</span>
                  <span className="text-[11px] text-muted-foreground">victoire</span>
                </div>
                {favCote ? <p className="text-[11px] text-muted-foreground mt-0.5">cote {formatCote(favCote)}</p> : null}
              </div>
              {/* Meilleure valeur détectée */}
              <div className={cn("rounded-xl border p-3",
                topVB ? "border-brand-emerald/30 bg-gradient-to-br from-brand-emerald/[0.08] to-transparent"
                      : "border-border bg-muted/20")}>
                <p className="text-overline text-muted-foreground">Pari de valeur</p>
                {topVB ? (
                  <>
                    <p className="mt-0.5 text-[13px] font-bold truncate">N°{topVB.numero} {topVB.nom_cheval}</p>
                    <div className="mt-1 flex items-baseline gap-1.5">
                      <span className="text-2xl font-bold tabular-nums text-brand-emerald leading-none">
                        +{Math.round(topVB.value_bet!.ev_max * 100)}%
                      </span>
                      <span className="text-[11px] text-muted-foreground">espérance</span>
                    </div>
                    <p className="text-[11px] text-muted-foreground mt-0.5">{etoiles(topVB.value_bet!.niveau)}</p>
                  </>
                ) : (
                  <p className="mt-2 text-xs text-muted-foreground">Aucune valeur franche sur cette course.</p>
                )}
              </div>
              {/* Score de confiance IA */}
              <div className="rounded-xl border border-border bg-muted/20 p-3">
                <p className="text-overline text-muted-foreground">Confiance algo</p>
                {confGlobal !== null ? (
                  <>
                    <div className="mt-0.5 flex items-baseline gap-1.5">
                      <span className={cn("text-2xl font-bold tabular-nums leading-none",
                        confGlobal >= 70 ? "text-brand-emerald" : confGlobal >= 50 ? "text-brand-gold" : "text-brand-red")}>
                        {Math.round(confGlobal)}
                      </span>
                      <span className="text-[11px] text-muted-foreground">/ 100</span>
                    </div>
                    <div className="mt-2"><ConfidenceMeter score={confGlobal} size="sm" /></div>
                  </>
                ) : <p className="mt-2 text-xs text-muted-foreground">—</p>}
              </div>
              {/* Champ */}
              <div className="rounded-xl border border-border bg-muted/20 p-3">
                <p className="text-overline text-muted-foreground">Le champ</p>
                <div className="mt-0.5 flex items-baseline gap-1.5">
                  <span className="text-2xl font-bold tabular-nums leading-none">{course.nb_partants}</span>
                  <span className="text-[11px] text-muted-foreground">partants</span>
                </div>
                <p className="text-[11px] text-muted-foreground mt-0.5">
                  {course.nb_partants >= 14 ? "champ ouvert" : course.nb_partants >= 10 ? "champ moyen" : "petit champ"}
                </p>
              </div>
            </div>
          );
        })()}

        {/* Résultats officiels (course terminée) */}
        {course.statut === "termine" && resultats && (
          <ResultatsSection resultats={resultats} partants={course.partants} />
        )}

        {/* Bilan du pronostic vs arrivée (course terminée) */}
        {course.statut === "termine" && resultats && predictions && predictions.length > 0 && (
          <PronosticVerdictSection predictions={predictions} classement={resultats.classement} />
        )}

        {/* Bilan du plan de mise 20€ rejoué sur l'arrivée réelle (course terminée) */}
        {course.statut === "termine" && resultats && predictions && predictions.length > 0 && (
          <BilanMiseSection courseId={id} />
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
                <span className="text-xs font-normal text-muted-foreground/70 ml-1">
                  — cliquez une ligne pour le détail
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full table-auto md:table-fixed text-sm">
                  <thead>
                    <tr className="border-b border-border bg-muted/40 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                      <th className="text-center px-2 py-2 w-8">N°</th>
                      <th className="text-left px-2 sm:px-3 py-2">Cheval</th>
                      <th className="text-left px-3 py-2 hidden md:table-cell w-28">Jockey</th>
                      <th className="text-right px-2 py-2 hidden sm:table-cell w-12">ELO</th>
                      <th className="text-right px-2 sm:px-3 py-2 w-14">Cote</th>
                      {predictions && <th className="text-right px-3 py-2 hidden sm:table-cell w-14">Algo</th>}
                      {predictions && <th className="text-right px-2 sm:px-3 py-2 w-14">Proba</th>}
                      {predictions && <th className="text-right px-2 sm:px-3 py-2 w-14">Valeur</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {[...course.partants]
                      // Non-partants conservés mais relégués en bas (indiqués, hors prono).
                      .sort((a, b) => Number(!!a.non_partant) - Number(!!b.non_partant))
                      .map((partant) => {
                        const pred = predictions?.find(
                          (p) => p.participation_id === partant.participation_id
                        );
                        const liveCote = liveCoteMap[partant.numero];
                        const cote = liveCote ?? partant.cote_pmu;
                        const rang = pred?.rang_predit;
                        const coteMoved = liveCote && partant.cote_pmu && liveCote < partant.cote_pmu;

                        const isExp = expandedPartant === partant.participation_id;
                        return (
                          <Fragment key={partant.participation_id}>
                          <tr
                            onClick={() => setExpandedPartant(isExp ? null : partant.participation_id)}
                            className={cn(
                              "cursor-pointer border-b border-border/40 align-top transition-colors hover:bg-accent/20",
                              rang === 1 && "row-top1",
                              rang === 2 && "row-top2",
                              rang === 3 && "row-top3",
                              isExp && "bg-accent/20",
                              partant.non_partant && "opacity-50 bg-muted/30",
                            )}
                          >
                            <td className="px-2 py-2.5 font-bold text-foreground/70 text-center tabular-nums">
                              {partant.numero}
                            </td>
                            <td className="px-2 sm:px-3 py-3 align-top">
                              {/* Ligne 1 — nom + style + alertes */}
                              <div className="flex items-center gap-x-2 gap-y-1 flex-wrap leading-tight">
                                <span className={cn("font-bold text-[15px] text-foreground break-words", partant.non_partant && "line-through text-muted-foreground")}>{partant.nom_cheval}</span>
                                {partant.non_partant && (
                                  <span title="Cheval déclaré non-partant — retiré du pronostic" className="inline-flex items-center gap-0.5 rounded px-1.5 py-0 text-[9px] font-bold bg-zinc-200 ring-1 ring-zinc-400 text-zinc-700 uppercase">
                                    Non partant
                                  </span>
                                )}
                                {partant.running_style && !partant.non_partant && (
                                  <RunningStyleBadge style={partant.running_style} />
                                )}
                                {partant.changement_jockey && (
                                  <span title="Changement de jockey vs dernière course" className="inline-flex items-center gap-0.5 rounded px-1.5 py-0 text-[9px] font-bold bg-orange-100 ring-1 ring-orange-300 text-orange-700">
                                    <RefreshCw className="h-2.5 w-2.5" /> Jockey
                                  </span>
                                )}
                                {(partant.jockey_suspendu || partant.entraineur_suspendu) && (
                                  <span title={partant.jockey_suspendu ? "Jockey suspendu" : "Entraîneur suspendu"} className="inline-flex items-center gap-0.5 rounded px-1.5 py-0 text-[9px] font-bold bg-red-100 ring-1 ring-red-300 text-red-700">
                                    <ShieldAlert className="h-2.5 w-2.5" />
                                    {partant.jockey_suspendu ? "J. susp." : "E. susp."}
                                  </span>
                                )}
                              </div>

                              {/* Ligne 2 — méta colorée, contrastée */}
                              <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] font-medium leading-tight">
                                {partant.age != null && <span className="text-foreground/70">{partant.age}a</span>}
                                {partant.sexe && <span className="text-foreground/70">{partant.sexe}</span>}
                                {partant.jours_depuis_derniere != null && (
                                  <span className={cn(
                                    partant.jours_depuis_derniere >= 14 && partant.jours_depuis_derniere <= 35
                                      ? "text-emerald-600"
                                      : partant.jours_depuis_derniere > 60
                                      ? "text-orange-600"
                                      : "text-foreground/70"
                                  )}>
                                    {partant.jours_depuis_derniere}j repos
                                  </span>
                                )}
                                {partant.premier_deferre && <span className="text-amber-600 font-semibold">★ Déferré</span>}
                                {partant.premieres_oeilleres && <span className="text-blue-600 font-semibold">★ Œillères</span>}
                                {partant.asso_jockey_entraineur_taux != null && partant.asso_jockey_entraineur_nb != null && partant.asso_jockey_entraineur_nb >= 5 && (
                                  <span className="text-violet-600 font-semibold">Duo {(partant.asso_jockey_entraineur_taux * 100).toFixed(0)}%</span>
                                )}
                              </div>

                              {/* Musique colorée */}
                              {partant.musique && (
                                <div className="mt-1.5 flex items-center gap-1.5">
                                  <span className="text-[9px] font-semibold uppercase tracking-wide text-muted-foreground">Mus.</span>
                                  <MusiqueDisplay musique={partant.musique} />
                                </div>
                              )}

                              {/* Toggle détail */}
                              <div className="mt-1.5 inline-flex items-center gap-1 text-[11px] font-medium text-brand-gold">
                                <ChevronDown className={cn("h-3 w-3 transition-transform", isExp && "rotate-180")} />
                                {isExp ? "Masquer" : "Détails"}
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
                            <td className="px-3 py-2.5 text-right hidden sm:table-cell">
                              <ELOBadge elo={partant.elo_global} />
                            </td>
                            <td className="px-2 sm:px-3 py-2.5 text-right">
                              {partant.non_partant ? (
                                <span className="font-mono text-xs text-muted-foreground">NP</span>
                              ) : (
                                <>
                                  <span className={cn("font-mono font-semibold", coteMoved && "text-brand-emerald")}>
                                    {formatCote(cote)}
                                  </span>
                                  {liveCote && <span className="text-brand-emerald text-[10px] ml-1">↓</span>}
                                </>
                              )}
                            </td>
                            {predictions && (
                              <td className="px-3 py-2.5 text-right text-muted-foreground font-mono text-xs hidden sm:table-cell">
                                {pred?.cote_juste ? formatCote(pred.cote_juste) : "—"}
                              </td>
                            )}
                            {predictions && (
                              <td className="px-2 sm:px-3 py-2.5 text-right">
                                {pred ? (
                                  <div className="flex flex-col items-end leading-tight">
                                    <span className={cn(
                                      "font-bold tabular-nums text-sm",
                                      rang === 1 ? "text-brand-gold" : "text-foreground",
                                    )}>
                                      {(pred.proba_top1 * 100).toFixed(0)}%
                                    </span>
                                    <span className="text-[10px] text-muted-foreground tabular-nums">
                                      {(pred.proba_top3 * 100).toFixed(0)}% top-3
                                    </span>
                                  </div>
                                ) : <span className="text-muted-foreground">—</span>}
                              </td>
                            )}
                            {predictions && (
                              <td className="px-2 sm:px-3 py-2.5 text-right">
                                {(() => {
                                  if (!pred) return <span className="text-muted-foreground">—</span>;
                                  if (pred.value_bet) return (
                                    <div className="flex flex-col items-end gap-0.5">
                                      <EVBadge ev={pred.value_bet.ev_max} />
                                      <span className="text-[10px]">{etoiles(pred.value_bet.niveau)}</span>
                                    </div>
                                  );
                                  // Espérance pour TOUS : cote × proba victoire − 1 (gain moyen pour 1€).
                                  if (cote && cote > 1 && pred.proba_top1 > 0) {
                                    const ev = cote * pred.proba_top1 - 1;
                                    return (
                                      <span className={cn("text-xs font-mono font-semibold tabular-nums",
                                        ev >= 0.05 ? "text-brand-emerald" : ev >= -0.2 ? "text-muted-foreground" : "text-muted-foreground/50")}>
                                        {ev >= 0 ? "+" : ""}{(ev * 100).toFixed(0)}%
                                      </span>
                                    );
                                  }
                                  return <span className="text-muted-foreground">—</span>;
                                })()}
                              </td>
                            )}
                          </tr>
                          {isExp && (
                            <tr className="bg-muted/20">
                              <td colSpan={predictions ? 8 : 5} className="px-3 pb-3 pt-1">
                                {(() => {
                                  const HEAD = "mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground";
                                  const CARD = "rounded-xl border border-border bg-white p-3 shadow-sm";
                                  const elo = partant.elo_global;
                                  const eloColor = elo == null ? "#9CA3AF" : elo >= 1700 ? "#F59E0B" : elo >= 1500 ? "#3B82F6" : elo >= 1300 ? "#10B981" : "#6B7280";
                                  const mv = partant.mouvement_cote_pct;  // >0 = cote baissée = argent venu = signal +
                                  const sexeLbl = partant.sexe ? ({ M: "Mâle", H: "Hongre", F: "Femelle" } as Record<string, string>)[partant.sexe] ?? partant.sexe : null;
                                  const a = partant.analyse;
                                  const pct = (v: number | null | undefined) => (v == null ? null : Math.round(v * 100));
                                  const js = a?.jockey_stats, es = a?.entraineur_stats;
                                  return (
                                <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
                                  {/* Musique */}
                                  <div className={cn(CARD, "sm:col-span-2 lg:col-span-3")}>
                                    <p className={HEAD}><Activity className="h-3 w-3 text-violet-500" /> Musique — forme récente</p>
                                    <MusiqueDisplay musique={partant.musique} />
                                  </div>

                                  {/* Points clés (le pourquoi) */}
                                  {a?.points && a.points.length > 0 && (
                                    <div className={cn(CARD, "sm:col-span-2 lg:col-span-3 border-brand-gold/30 bg-brand-gold/[0.04]")}>
                                      <p className={HEAD}><Target className="h-3 w-3 text-brand-gold" /> Points clés de l&apos;analyse</p>
                                      <div className="flex flex-wrap gap-1.5">
                                        {a.points.map((pt, i) => (
                                          <span key={i} className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1",
                                            pt.type === "+" ? "bg-emerald-50 text-emerald-700 ring-emerald-200" : "bg-rose-50 text-rose-700 ring-rose-200")}>
                                            {pt.type === "+" ? "▲" : "▼"} {pt.txt}
                                          </span>
                                        ))}
                                      </div>
                                    </div>
                                  )}

                                  {/* Forme chiffrée */}
                                  {a && (pct(a.forme.taux_top3) != null || pct(a.forme.recent_win_rate) != null) && (
                                    <div className={CARD}>
                                      <p className={HEAD}><Activity className="h-3 w-3 text-emerald-500" /> Forme</p>
                                      {pct(a.forme.taux_top3) != null && <p className="text-sm">Dans les 3 : <span className="font-bold tabular-nums">{pct(a.forme.taux_top3)}%</span></p>}
                                      {pct(a.forme.recent_win_rate) != null && <p className="text-xs text-muted-foreground">Victoires récentes : {pct(a.forme.recent_win_rate)}%</p>}
                                      {pct(a.forme.regularite) != null && <p className="text-xs text-muted-foreground">Régularité : {pct(a.forme.regularite)}%</p>}
                                      {a.forme.tendance != null && Math.abs(a.forme.tendance) > 0.05 && (
                                        <p className={cn("text-xs font-medium", a.forme.tendance > 0 ? "text-emerald-600" : "text-rose-600")}>
                                          {a.forme.tendance > 0 ? "▲ en progression" : "▼ en baisse"}
                                        </p>
                                      )}
                                    </div>
                                  )}

                                  {/* Préférences contexte (distance / terrain / hippodrome) */}
                                  {a && (pct(a.contexte.pref_distance) != null || pct(a.contexte.pref_terrain) != null || pct(a.contexte.pref_hippodrome) != null) && (
                                    <div className={CARD}>
                                      <p className={HEAD}><MapPin className="h-3 w-3 text-blue-500" /> À l&apos;aise sur…</p>
                                      {[
                                        ["Distance", a.contexte.pref_distance, a.contexte.nb_distance],
                                        ["Terrain", a.contexte.pref_terrain, a.contexte.nb_terrain],
                                        ["Hippodrome", a.contexte.pref_hippodrome, a.contexte.nb_hippodrome],
                                      ].map(([lbl, v, nb]) => {
                                        const p2 = pct(v as number | null);
                                        if (p2 == null) return null;
                                        const good = p2 >= 60;
                                        return (
                                          <p key={lbl as string} className="text-xs flex items-center gap-1.5">
                                            <span className={good ? "text-emerald-600" : "text-muted-foreground"}>{good ? "✓" : "•"}</span>
                                            <span className="text-muted-foreground">{lbl as string}</span>
                                            <span className="font-semibold tabular-nums ml-auto">{p2}%</span>
                                            {nb != null && (nb as number) > 0 && <span className="text-muted-foreground/60">({nb as number}c)</span>}
                                          </p>
                                        );
                                      })}
                                    </div>
                                  )}

                                  {/* Niveau & forme (ELO) */}
                                  {(elo != null || partant.age != null || partant.running_style || partant.jours_depuis_derniere != null) && (
                                    <div className={CARD}>
                                      <p className={HEAD}><BarChart2 className="h-3 w-3 text-emerald-500" /> Niveau & forme</p>
                                      {elo != null && (
                                        <p className="text-sm flex items-baseline gap-1.5">
                                          <span className="text-muted-foreground text-xs">ELO</span>
                                          <span className="font-bold tabular-nums" style={{ color: eloColor }}>{Math.round(elo)}</span>
                                        </p>
                                      )}
                                      <p className="text-xs text-muted-foreground">
                                        {partant.age != null ? `${partant.age} ans` : ""}{sexeLbl ? ` · ${sexeLbl}` : ""}
                                        {partant.jours_depuis_derniere != null ? ` · ${partant.jours_depuis_derniere}j de repos` : ""}
                                      </p>
                                      {partant.running_style && <div className="mt-1.5"><RunningStyleBadge style={partant.running_style} /></div>}
                                    </div>
                                  )}

                                  {/* Marché — cote + mouvement + fourchette */}
                                  {partant.cote_pmu != null && (
                                    <div className={CARD}>
                                      <p className={HEAD}><TrendingUp className="h-3 w-3 text-amber-500" /> Marché</p>
                                      <p className="text-sm flex items-center gap-2">
                                        <span className="font-bold tabular-nums">{partant.cote_pmu.toFixed(1)}</span>
                                        {mv != null && Math.abs(mv) >= 1 && (
                                          <span className={cn("inline-flex items-center gap-0.5 text-[11px] font-semibold", mv > 0 ? "text-emerald-600" : "text-rose-600")}>
                                            {mv > 0 ? <TrendingDown className="h-3 w-3" /> : <TrendingUp className="h-3 w-3" />}
                                            {mv > 0 ? "−" : "+"}{Math.abs(mv).toFixed(0)}%
                                            <span className="text-muted-foreground font-normal">{mv > 0 ? "joué" : "délaissé"}</span>
                                          </span>
                                        )}
                                      </p>
                                      {partant.cote_min != null && partant.cote_max != null && partant.cote_min !== partant.cote_max && (
                                        <p className="text-xs text-muted-foreground tabular-nums">Fourchette {partant.cote_min.toFixed(1)}–{partant.cote_max.toFixed(1)}{partant.nb_sources ? ` · ${partant.nb_sources} sources` : ""}</p>
                                      )}
                                      {/* Signaux marché avancés (argent pro) */}
                                      {a && (
                                        <div className="mt-1 flex flex-wrap gap-1">
                                          {a.marche.spi != null && a.marche.spi >= 0.15 && <span className="rounded bg-violet-100 px-1.5 py-0.5 text-[10px] font-semibold text-violet-700">SPI {Math.round(a.marche.spi * 100)}% — argent pro</span>}
                                          {a.marche.valeur_latente != null && a.marche.valeur_latente >= 0.2 && <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700">Sous-coté (valeur)</span>}
                                          {a.marche.steam != null && a.marche.steam >= 0.2 && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700">Steam move</span>}
                                          {a.marche.decote != null && a.marche.decote >= 0.2 && <span className="rounded bg-blue-100 px-1.5 py-0.5 text-[10px] font-semibold text-blue-700">Décote détectée</span>}
                                        </div>
                                      )}
                                    </div>
                                  )}

                                  {/* Jockey / Entraîneur */}
                                  <div className={CARD}>
                                    <p className={HEAD}><Users className="h-3 w-3 text-blue-500" /> Jockey / Entraîneur</p>
                                    <p className="text-sm font-medium leading-snug">
                                      {partant.jockey || "—"}
                                      {partant.changement_jockey && <span className="ml-1.5 rounded bg-amber-100 px-1 py-0.5 text-[9px] font-bold text-amber-700 align-middle">CHANGEMENT</span>}
                                      {partant.jockey_suspendu && <span className="ml-1.5 rounded bg-rose-100 px-1 py-0.5 text-[9px] font-bold text-rose-700 align-middle">SUSPENDU</span>}
                                    </p>
                                    <p className="text-xs text-muted-foreground">Entraîneur : {partant.entraineur || "—"}{partant.entraineur_suspendu && <span className="ml-1 text-[9px] font-bold text-rose-600">(suspendu)</span>}</p>
                                    {js && (pct(js.taux_victoire) != null) && (
                                      <p className="mt-1 text-[11px] text-muted-foreground">Jockey saison : <span className="font-semibold text-foreground">{pct(js.taux_victoire)}%</span> V · {pct(js.taux_place)}% P{js.victoires_saison != null ? ` · ${js.victoires_saison}/${js.courses_saison}` : ""}{js.roi != null ? ` · ROI ${js.roi >= 0 ? "+" : ""}${Math.round(js.roi * 100)}%` : ""}</p>
                                    )}
                                    {es && (pct(es.taux_victoire) != null) && (
                                      <p className="text-[11px] text-muted-foreground">Entraîneur saison : <span className="font-semibold text-foreground">{pct(es.taux_victoire)}%</span> V · {pct(es.taux_place)}% P{es.roi != null ? ` · ROI ${es.roi >= 0 ? "+" : ""}${Math.round(es.roi * 100)}%` : ""}</p>
                                    )}
                                    {partant.asso_jockey_entraineur_taux != null && partant.asso_jockey_entraineur_nb != null && partant.asso_jockey_entraineur_nb >= 3 && (
                                      <p className="mt-1 text-[11px] text-violet-600">🤝 Duo : {(partant.asso_jockey_entraineur_taux * 100).toFixed(0)}% sur {partant.asso_jockey_entraineur_nb} courses</p>
                                    )}
                                  </div>

                                  {/* Carrière */}
                                  {partant.nb_courses ? (
                                    <div className={CARD}>
                                      <p className={HEAD}><Trophy className="h-3 w-3 text-amber-500" /> Carrière</p>
                                      <p className="text-sm">
                                        <span className="font-bold tabular-nums">{partant.nb_victoires ?? 0}</span> victoire{(partant.nb_victoires ?? 0) > 1 ? "s" : ""}
                                        <span className="text-muted-foreground"> sur </span>
                                        <span className="font-medium tabular-nums">{partant.nb_courses}</span> courses
                                      </p>
                                      <div className="mt-1 flex items-center gap-2">
                                        <div className="h-1.5 flex-1 rounded-full bg-muted/40 overflow-hidden">
                                          <div className="h-full rounded-full bg-emerald-500" style={{ width: `${Math.min(100, Math.round((partant.nb_victoires ?? 0) / partant.nb_courses * 100))}%` }} />
                                        </div>
                                        <span className="text-xs text-muted-foreground tabular-nums">{Math.round((partant.nb_victoires ?? 0) / partant.nb_courses * 100)}%</span>
                                      </div>
                                    </div>
                                  ) : null}

                                  {/* Équipement */}
                                  <div className={CARD}>
                                    <p className={HEAD}><Zap className="h-3 w-3 text-orange-500" /> Équipement</p>
                                    <p className="text-sm">Déferré : <span className="font-medium capitalize">{(partant.deferre || "Non").replace(/_/g, " ").toLowerCase()}</span>{partant.premier_deferre && <span className="ml-1 text-[10px] font-semibold text-brand-gold">1ʳᵉ fois ★</span>}</p>
                                    <p className="text-sm">Œillères : <span className="font-medium capitalize">{(partant.oeilleres || "Non").replace(/_/g, " ").replace(/oeilleres?/i, "").trim().toLowerCase() || "sans"}</span>{partant.premieres_oeilleres && <span className="ml-1 text-[10px] font-semibold text-brand-blue">1ʳᵉ fois ★</span>}</p>
                                  </div>

                                  {/* Poids / Départ */}
                                  {(partant.handicap_poids || partant.poids_prevu || partant.numero_corde || partant.poids_reel_pesee) && (
                                    <div className={CARD}>
                                      <p className={HEAD}><Ruler className="h-3 w-3 text-slate-500" /> Poids / Départ</p>
                                      {(partant.handicap_poids ?? partant.poids_prevu) != null && (
                                        <p className="text-sm">Poids : <span className="font-medium tabular-nums">{(partant.handicap_poids ?? partant.poids_prevu)} kg</span></p>
                                      )}
                                      {partant.poids_reel_pesee != null && (
                                        <p className="text-xs text-muted-foreground">Pesée réelle : {partant.poids_reel_pesee} kg</p>
                                      )}
                                      {partant.numero_corde != null && (
                                        <p className="text-sm">Corde : <span className="font-medium tabular-nums">{partant.numero_corde}</span></p>
                                      )}
                                    </div>
                                  )}

                                  {/* Origines */}
                                  {(partant.pere || partant.mere) && (
                                    <div className={CARD}>
                                      <p className={HEAD}><Tag className="h-3 w-3 text-pink-500" /> Origines</p>
                                      {partant.pere && <p className="text-xs">Père : <span className="font-medium">{partant.pere}</span></p>}
                                      {partant.mere && <p className="text-xs">Mère : <span className="font-medium">{partant.mere}</span></p>}
                                      {partant.pere_de_mere && <p className="text-xs text-muted-foreground">Père de mère : {partant.pere_de_mere}</p>}
                                    </div>
                                  )}
                                </div>
                                  );
                                })()}
                              </td>
                            </tr>
                          )}
                          </Fragment>
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
                <h3 className="text-sm font-semibold text-gray-900">Analyse BlackTurf</h3>
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

              {/* Chevaux à surveiller (signaux marché / argent pro) */}
              {analysis.market_signals?.length > 0 && (
                <div className="pt-1">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">👁️ Chevaux à surveiller</p>
                  <div className="flex flex-wrap gap-1.5">
                    {analysis.market_signals.map((s, i) => (
                      <span key={i} className="inline-flex items-center gap-1 rounded-full bg-amber-50 border border-amber-200 px-2 py-0.5 text-[10px] font-semibold text-amber-700">
                        N°{s.numero} {s.nom} — {s.signal}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              <p className="text-[10px] text-muted-foreground/70 pt-1">
                Synthèse de l&apos;analyse. Les paris à jouer (selon ton montant et ton profil) sont dans le plan de mise ci-contre.
              </p>
            </div>
          )}

          {/* ── Course à outsider (champ ouvert + grosses cotes à valeur détectée) ── */}
          {analysis?.detection_outsider?.course_a_outsider && (
            <div className="rounded-xl border border-violet-200 bg-violet-50/60 p-4 space-y-2">
              <div className="flex items-center gap-2">
                <Zap className="h-4 w-4 text-violet-600" />
                <h3 className="text-sm font-bold text-violet-800">Course à outsider détectée</h3>
                <span className="ml-auto text-[10px] font-bold rounded-full bg-violet-100 text-violet-700 px-2 py-0.5">
                  Score {Math.round(analysis.detection_outsider.score * 100)}/100
                </span>
              </div>
              {analysis.detection_outsider.signaux.length > 0 && (
                <ul className="text-xs text-violet-900/80 space-y-0.5">
                  {analysis.detection_outsider.signaux.map((s, i) => (
                    <li key={i} className="flex gap-1.5"><span>·</span><span>{s}</span></li>
                  ))}
                </ul>
              )}
              <div className="grid gap-2 sm:grid-cols-2">
                {analysis.detection_outsider.candidats.map((c) => (
                  <div key={c.numero} className="rounded-lg bg-white/80 border border-violet-200/70 p-2.5 space-y-1.5">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-bold">N°{c.numero} {c.nom}</span>
                      <span className="font-mono text-xs font-bold text-violet-700">cote {c.cote}</span>
                    </div>
                    {/* Chiffres clés : valeur modèle vs marché */}
                    <div className="flex flex-wrap gap-1 text-[10px]">
                      <span className="rounded bg-violet-100 text-violet-800 px-1.5 py-0.5 font-medium">
                        Modèle {Math.round(c.proba_modele * 100)}% · Marché {Math.round(c.proba_marche * 100)}%
                      </span>
                      {c.ratio_valeur != null && (
                        <span className="rounded bg-emerald-100 text-emerald-800 px-1.5 py-0.5 font-bold">
                          ×{c.ratio_valeur} valeur
                        </span>
                      )}
                      {c.verdict && (
                        <span className="rounded bg-gray-100 text-gray-700 px-1.5 py-0.5">{c.verdict}</span>
                      )}
                    </div>
                    {c.justification && (
                      <p className="text-[11px] text-gray-700 leading-relaxed">{c.justification}</p>
                    )}
                    {/* Facteurs qui appuient le choix */}
                    {c.facteurs_positifs && c.facteurs_positifs.length > 0 && (
                      <ul className="space-y-0.5">
                        {c.facteurs_positifs.slice(0, 4).map((f, i) => (
                          <li key={i} className="text-[10px] text-emerald-800 flex gap-1">
                            <span className="flex-shrink-0">✓</span>
                            <span><b>{f.label}</b>{f.detail ? ` — ${f.detail}` : ""}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                    {/* Points de vigilance (honnêteté : un outsider garde des risques) */}
                    {c.points_vigilance && c.points_vigilance.length > 0 && (
                      <ul className="space-y-0.5">
                        {c.points_vigilance.map((v, i) => (
                          <li key={i} className="text-[10px] text-amber-700 flex gap-1">
                            <span className="flex-shrink-0">⚠</span><span>{v}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                ))}
              </div>
              <p className="text-[10px] text-violet-900/60">
                Détection : ouverture du marché + écart modèle/marché + taux de surprises réel sur ce type de course.
                Grosse cote = risque élevé ; réservé aux profils offensifs.
              </p>
            </div>
          )}

          {/* ── Chevaux à éviter (surcotés par le public / facteurs défavorables) ── */}
          {analysis?.chevaux_a_eviter && analysis.chevaux_a_eviter.length > 0 && (
            <div className="rounded-xl border border-red-200 bg-red-50/50 p-4 space-y-2">
              <div className="flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-red-500" />
                <h3 className="text-sm font-bold text-red-700">Chevaux à éviter</h3>
              </div>
              <div className="space-y-2">
                {analysis.chevaux_a_eviter.map((c) => (
                  <div key={c.numero} className="rounded-lg bg-white/80 border border-red-200/70 p-2.5 space-y-1.5">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-bold">N°{c.numero} {c.nom}</span>
                      <span className="font-mono text-xs text-gray-500">cote {c.cote}</span>
                    </div>
                    {/* Chiffres clés : le modèle sous le marché */}
                    <div className="flex flex-wrap gap-1 text-[10px]">
                      {c.proba_victoire != null && c.proba_marche != null && (
                        <span className="rounded bg-red-100 text-red-800 px-1.5 py-0.5 font-medium">
                          Modèle {Math.round(c.proba_victoire * 100)}% · Marché {Math.round(c.proba_marche * 100)}%
                        </span>
                      )}
                      {c.verdict && (
                        <span className="rounded bg-gray-100 text-gray-700 px-1.5 py-0.5">{c.verdict}</span>
                      )}
                    </div>
                    {c.justification && (
                      <p className="text-[11px] text-gray-700 leading-relaxed font-medium">{c.justification}</p>
                    )}
                    <ul className="space-y-0.5">
                      {c.raisons.map((r, i) => (
                        <li key={i} className="text-[11px] text-gray-600 leading-relaxed flex gap-1.5">
                          <span className="text-red-400 flex-shrink-0">·</span><span>{r}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
              <p className="text-[10px] text-red-900/50">
                Basé sur l&apos;écart modèle/marché et les facteurs réels — pas une garantie de défaite, un avertissement de valeur.
              </p>
            </div>
          )}

          {/* ── Comparaison multi-bookmakers (repliable — désencombre) ── */}
          {course.partants.some((p) => p.cote_winamax || p.cote_betclic || p.cote_unibet || p.cote_betfair_exchange) && (
            <details className="group rounded-xl border border-border bg-card/40">
              <summary className="cursor-pointer list-none flex items-center gap-2 px-4 py-3 select-none">
                <BarChart2 className="h-4 w-4 text-muted-foreground" />
                <h3 className="text-sm font-semibold">Comparaison des cotes</h3>
                <span className="text-xs text-muted-foreground hidden sm:inline">
                  {course.partants.filter(p => !p.non_partant)[0]?.nb_sources ?? 1} sources
                </span>
                <ChevronDown className="ml-auto h-4 w-4 text-muted-foreground transition-transform group-open:rotate-180" />
              </summary>
              <div className="px-2 pb-3">
                <p className="px-2 pb-2 text-[10px] text-emerald-600 font-medium">Vert = meilleure cote disponible</p>
                <ComparaisonCotes partants={course.partants} />
              </div>
            </details>
          )}

          {/* ── Pronostics presse ── */}
          {course.pronostics_presse?.length > 0 && (
            <PronosticsPresse pronostics={course.pronostics_presse} />
          )}

          {course.statut !== "termine" && (
            <MarcheCotes courseId={id} partants={course.partants} statut={course.statut} />
          )}

        </div>

        {/* ── RIGHT SIDEBAR ── */}
        <div className="space-y-4">
          {/* Analyse algorithme */}
          <Card className="border-border/70">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-sm">
                <Brain className="h-4 w-4 text-brand-gold" />
                Analyse algorithme
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
                course.statut === "termine" ? (
                  <div className="text-center py-4">
                    <Brain className="h-8 w-8 mx-auto mb-2 text-muted-foreground/40" />
                    <p className="text-sm font-medium text-muted-foreground">Course non analysée par l&apos;algorithme</p>
                    <p className="text-xs text-muted-foreground/70 mt-1">
                      Cette course (souvent étrangère) n&apos;a pas été couverte par le modèle.
                    </p>
                  </div>
                ) : (
                  <div className="text-center py-4">
                    <Brain className="h-8 w-8 mx-auto mb-2 text-muted-foreground/40" />
                    <p className="text-sm text-muted-foreground mb-3">Aucune analyse disponible</p>
                    <Button variant="brand" size="sm" onClick={handleTriggerPred} disabled={triggeringPred}>
                      {triggeringPred ? <Loader2 className="h-4 w-4 animate-spin" /> : "Lancer l'analyse"}
                    </Button>
                  </div>
                )
              ) : (
                <div className="space-y-3">
                  <div className="flex items-baseline justify-between">
                    <p className="text-[11px] font-medium text-muted-foreground">
                      Classement algorithme — {predictions.length} partant{predictions.length > 1 ? "s" : ""}
                    </p>
                    <div className="flex items-center gap-2 text-[9px] uppercase tracking-wide text-muted-foreground/70">
                      <span>Gagnant</span><span>·</span><span>Top-3</span>
                    </div>
                  </div>
                  {/* Classement complet (scroll si beaucoup de partants) */}
                  <div className="space-y-1.5 max-h-[28rem] overflow-y-auto pr-1 -mr-1">
                    {[...predictions].sort((a, b) => a.rang_predit - b.rang_predit).map((p) => (
                      <div key={p.prediction_id} className="flex items-center gap-2.5 rounded-lg px-1.5 py-1.5 hover:bg-muted/40 transition-colors">
                        <div className={cn(
                          "h-6 w-6 rounded-md flex items-center justify-center text-[11px] font-bold flex-shrink-0 tabular-nums",
                          p.rang_predit === 1 ? "bg-brand-gold/15 text-brand-gold ring-1 ring-brand-gold/30" :
                          p.rang_predit <= 3 ? "bg-foreground/5 text-foreground ring-1 ring-border" :
                          "bg-transparent text-muted-foreground/60",
                        )}>
                          {p.rang_predit}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-1.5">
                            <p className="text-sm font-medium truncate">N°{p.numero} {p.nom_cheval}</p>
                            {p.value_bet && <EVBadge ev={p.value_bet.ev_max} />}
                          </div>
                          {p.proba_top1_low != null && p.proba_top1_high != null && (
                            <span className="text-[9px] text-muted-foreground/60 tabular-nums">
                              intervalle {(p.proba_top1_low * 100).toFixed(0)}–{(p.proba_top1_high * 100).toFixed(0)}%
                            </span>
                          )}
                          {/* Facteurs clés RÉELS (forme, ELO, J/E…) — montre que l'IA pèse bien plus que la cote */}
                          {(() => {
                            const fac = analysis?.predictions?.find((ap) => ap.numero === p.numero)?.explanation?.facteurs_positifs ?? [];
                            const labels = fac.slice(0, 3).map((f) => f.label.replace(/^[^A-Za-zÀ-ÿ0-9]+/, "").trim()).filter(Boolean);
                            if (!labels.length) return null;
                            return (
                              <div className="mt-1 flex flex-wrap gap-1">
                                {labels.map((l, i) => (
                                  <span key={i} className="inline-block rounded bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200/70 px-1.5 py-0.5 text-[9px] font-medium leading-none">
                                    {l}
                                  </span>
                                ))}
                              </div>
                            );
                          })()}
                        </div>
                        {/* Deux chiffres clairs alignés : victoire (gras) + placé */}
                        <div className="flex items-center gap-3 flex-shrink-0 text-right">
                          <div className="w-10">
                            <div className="text-sm font-bold tabular-nums text-foreground">{(p.proba_top1 * 100).toFixed(0)}%</div>
                          </div>
                          <div className="w-10">
                            <div className="text-xs font-medium tabular-nums text-muted-foreground">{(p.proba_top3 * 100).toFixed(0)}%</div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className="pt-2 border-t border-border/50 space-y-1">
                    <p className="text-[10px] text-muted-foreground flex gap-1.5">
                      <Info className="h-3 w-3 mt-0.5 flex-shrink-0" />
                      <span><strong className="text-foreground">Gagnant</strong> = probabilité de victoire · <strong className="text-foreground">Top-3</strong> = probabilité d&apos;être dans les 3 premiers. Probabilités calibrées sur résultats réels.</span>
                    </p>
                    <p className="text-[10px] text-muted-foreground/70 pl-[18px]">
                      Le modèle combine <strong className="text-foreground">80+ critères</strong> (forme, ELO, jockey/entraîneur, distance, terrain, descente de catégorie…) — la cote n&apos;est qu&apos;un facteur parmi d&apos;autres (~19% du poids). Aide à la décision — aucune garantie de gain.
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
                statut={course.statut}
              />
            </CardContent>
          </Card>

          {/* Infos course */}
          <Card className="border-border/50">
            <CardContent className="p-4 space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Discipline</span>
                <span className="font-medium">{course.discipline}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Distance</span>
                <span className="font-mono font-medium">{course.distance}m</span>
              </div>
              {course.niveau_course && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Niveau</span>
                  <span className="font-medium">{course.niveau_course.replace(/_/g, " ")}</span>
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
                  <span className="font-mono font-medium">{Math.round(course.allocation / 100).toLocaleString("fr-FR")} €</span>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
