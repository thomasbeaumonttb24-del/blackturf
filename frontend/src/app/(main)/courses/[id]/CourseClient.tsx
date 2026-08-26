"use client";

import { useEffect, useState, useRef, Fragment } from "react";
import { useParams } from "next/navigation";
import {
  ArrowLeft, Brain, Loader2, TrendingUp, AlertTriangle, Cloud,
  Calculator, ChevronRight, ChevronDown, Star, Zap, Info, BarChart2,
  RefreshCw, ShieldAlert, Newspaper, TrendingDown, Activity, CheckCircle2,
  MapPin, Ruler, Users, Clock, Trophy, Tag, FileText, Target, Pencil, Tv,
  HelpCircle, X, Minus, ShieldCheck, Gauge, Flame, LockKeyhole, Radio, WalletCards,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { coursesApi, predictionsApi, api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CheckoutButton } from "@/components/billing/CheckoutButton";
import { useAuth } from "@/hooks/useAuth";
import { useCotesLive } from "@/hooks/useWebSocket";
import {
  ParisDisponiblesCard, ConfrontationsCard, PoolEvolutionCard, TempsPassageCard,
  CompteurDepart, ApercuAnalyseCard, PreuvesRecentesCard, useApercuAnalyse,
} from "@/components/courses/insights";
import {
  ClassementAlgo, ClassementApercu, ClassementVerrouille, type ClassementSignal,
} from "@/components/courses/classement";
import { formatCote, formatEV, etoiles, formatDateTime, formatMontantDevise, cn } from "@/lib/utils";
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
  cote_bet365: number | null;
  cote_ladbrokes: number | null;
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
  gains_carriere_devise: string | null;   // ISO 4217 — devise locale de la réunion PMU
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
  /** Cote de marché au moment du pronostic — peut différer nettement de `cote_pmu`,
   *  qui est la cote AFFICHÉE (live avant gel, dernière connue après). */
  cote_figee?: number | null;
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
  meteo: {
    terrain_officiel: string | null;
    temperature: number | null;
    pluie_24h: number | null;
    vent_vitesse?: number | null;
    humidite?: number | null;
  } | null;
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
  prono_fige?: boolean;           // sélection figée (T-10) — paris/chevaux/mises immuables
  gains_live_post_gel?: boolean;  // gains ré-évalués sur cotes live MÊME après le gel
  roi_observe?: { roi: number; nb: number; jours: number };  // ROI RÉEL récent du profil (honnêteté vs espérance théorique)
}

// ─── Sub-components ───────────────────────────────────────────────────────────
// Badges présentationnels (ConfidenceMeter, EVBadge, ELOBadge, RunningStyleBadge,
// MusiqueDisplay, PenetroBadge, PoolBadge) extraits dans components/courses/badges.

// Profils de mise (source unique : formulaire + switch rapide dans le plan).
const PROFILS_MISE = [
  { key: "conservateur", label: "Prudent", desc: "Favorise la régularité et limite l’exposition." },
  { key: "equilibre", label: "Modéré", desc: "Équilibre la régularité et le rendement." },
  { key: "agressif", label: "Risqué", desc: "Accepte plus de variance pour viser plus haut." },
] as const;

// ─── Palette du reskin (tokens du design handoff) ─────────────────────────────
// Palette restreinte 4 familles. Or / Émeraude / Rose / Neutres chauds.
const CX = {
  // Or
  gold: "#B45309", goldDeep: "#92400E", goldMuted: "#C99A3C", goldAmber: "#D97706",
  goldGrad: "linear-gradient(135deg,#F59E0B,#D97706)", goldBg: "#FEF6E7", goldBd: "#F5DCA8", goldBd2: "#FCD34D",
  // Émeraude
  em: "#059669", emDeep: "#047857", emLight: "#10B981", emBg: "#ECFDF5", emBd: "#A7F3D0",
  // Rose (négatif)
  red: "#E11D48", redDeep: "#B91C1C", redBg: "#FEF2F2", redBd: "#FECACA",
  // Neutres chauds
  ink: "#111827", ink2: "#1F2937", gray700: "#374151", gray600: "#4B5563",
  gray500: "#6B7280", gray400: "#4B5563", muted: "#B0A88F",
  surf1: "#FFFFFF", surf2: "#FAF7EF", surf3: "#F7F4EC", surf4: "#F3F1EA", surf5: "#F1EEE6",
  bd1: "#ECE7DC", bd2: "#EEE9DE", bd3: "#E7E1D3", bd4: "#F3EFE6",
  slate: "#64748B",
  sg: "'Space Grotesk',sans-serif",
} as const;

// Fond de page (design handoff).
const CX_PAGE_BG =
  "radial-gradient(ellipse at 18% 0%,rgba(245,158,11,.06) 0%,transparent 46%)," +
  "radial-gradient(ellipse at 88% 6%,rgba(217,119,6,.04) 0%,transparent 40%)," +
  "linear-gradient(180deg,#FFFDF6 0%,#FAFAF8 38%)";

// Discipline → masque silhouette (assets détourés) + teinte discipline.
const DISCIPLINE_MASK: Record<string, { file: string; color: string }> = {
  Plat:     { file: "plat",     color: "#B45309" },
  "Attelé": { file: "attele",   color: "#0E7C66" },
  Monté:    { file: "monte",    color: "#2A5BD7" },
  Obstacle: { file: "obstacle", color: "#C1502A" },
  Haies:    { file: "obstacle", color: "#C1502A" },
  Steeple:  { file: "obstacle", color: "#A32C3E" },
  Cross:    { file: "obstacle", color: "#C1502A" },
};
function discMask(discipline: string): { url: string; color: string } {
  const k = discipline ? discipline.charAt(0).toUpperCase() + discipline.slice(1).toLowerCase() : "";
  const m = DISCIPLINE_MASK[k] ?? { file: "attele", color: "#0E7C66" };
  return { url: `/img/disciplines/${m.file}-v7.png`, color: m.color };
}

// Feuille de style injectée (keyframes + responsive du .dc.html).
const CX_STYLE = `
@keyframes cxDotPulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.45;transform:scale(1.4)}}
@keyframes cxFadeUp{from{opacity:0;transform:translateY(18px)}to{opacity:1;transform:none}}
@keyframes cxBarGrow{from{transform:scaleX(0)}to{transform:scaleX(1)}}
.cx-badges>span{white-space:nowrap}
.cx-meta>span{white-space:nowrap}
.cx-fade{animation:cxFadeUp .5s cubic-bezier(.16,1,.3,1) both}
.cx-plan button:focus-visible,.cx-plan input:focus-visible,.cx-plan summary:focus-visible{outline:2px solid #B45309 !important;outline-offset:2px}
.cx-plan button:disabled{cursor:not-allowed !important}
.cx-plan details>summary svg{transition:transform .2s ease}
.cx-plan details[open]>summary svg:last-child{transform:rotate(180deg)}
@media (max-width:840px){ .cx-main{grid-template-columns:1fr !important} .cx-sticky-mise{position:static !important;top:auto !important} }
@media (max-width:600px){
  .cx-wrap{padding:16px 13px 72px !important}
  .cx-hero{padding:20px 17px !important;border-radius:20px !important}
  .cx-h1{font-size:23px !important}
  .cx-hbtn{width:100% !important;justify-content:center !important;margin-top:4px}
  .cx-prow{grid-template-columns:36px 1fr 48px 54px 20px !important;gap:8px !important}
  .cx-algo{display:none !important}
  .cx-2col{grid-template-columns:1fr !important}
  .cx-hide-m{display:none !important}
}
@media (prefers-reduced-motion:reduce){*{animation:none !important}}
`;

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
  const evColor = plan.ev_global > 0 ? CX.em : CX.red;
  // Teinte par niveau : Sécurité=émeraude, Rendement=or, Coup à tenter=rose.
  const nivStyle = (niveau: string) =>
    niveau === "securite" ? { bg: CX.emBg, bd: CX.emBd, color: CX.emDeep } :
    niveau === "rendement" ? { bg: CX.goldBg, bd: CX.goldBd, color: CX.goldDeep } :
    { bg: CX.redBg, bd: CX.redBd, color: CX.redDeep };
  const cell = { borderRadius: 12, border: `1px solid ${CX.bd2}`, background: CX.surf1, padding: "11px 12px" } as const;
  return (
    <div className="cx-plan" style={{ animation: "cxFadeUp .4s cubic-bezier(.16,1,.3,1) both", color: CX.ink2 }}>
      {/* Switch profil rapide — même mise, recalcul instantané */}
      <div role="tablist" aria-label="Profil de risque" style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 4, borderRadius: 13, background: CX.surf4, padding: 4, marginBottom: 8 }}>
        {PROFILS_MISE.map((p) => {
          const active = profil === p.key;
          const Icon = p.key === "conservateur" ? ShieldCheck : p.key === "equilibre" ? Gauge : Flame;
          return (
            <button
              key={p.key}
              role="tab"
              aria-selected={active}
              onClick={() => !active && onChangeProfil(p.key)}
              disabled={switching}
              style={{ minHeight: 44, display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6, border: active ? `1px solid ${CX.goldBd}` : "1px solid transparent", borderRadius: 10, padding: "8px 6px", fontSize: 12, fontWeight: active ? 700 : 600, cursor: switching ? "wait" : "pointer", transition: "background-color .2s, border-color .2s, color .2s, box-shadow .2s", background: active ? CX.surf1 : "transparent", color: active ? CX.goldDeep : CX.gray500, boxShadow: active ? "0 1px 3px rgba(17,24,39,.08)" : "none" }}
            >
              {switching && active ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Icon className="h-3.5 w-3.5" aria-hidden="true" />}
              {p.label}
            </button>
          );
        })}
      </div>
      {profilDesc && (
        <p style={{ margin: "0 2px 18px", fontSize: 11.5, lineHeight: 1.45, color: CX.gray500 }}>{profilDesc}</p>
      )}

      {/* Header résumé */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 12 }}>
        <div style={{ borderRadius: 14, border: `1px solid ${CX.bd2}`, background: CX.surf1, padding: "13px 14px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 5, fontSize: 10.5, fontWeight: 600, color: CX.gray500 }}>
            <WalletCards className="h-3.5 w-3.5" aria-hidden="true" /> Budget
          </div>
          <div style={{ fontFamily: CX.sg, fontSize: 25, fontWeight: 700, color: CX.ink, lineHeight: 1, fontVariantNumeric: "tabular-nums" }}>{plan.montant_total}€</div>
        </div>
        <div style={{ borderRadius: 14, border: `1px solid ${CX.bd2}`, background: CX.surf1, padding: "13px 14px", textAlign: "right" }}>
          <div style={{ marginBottom: 5, fontSize: 10.5, fontWeight: 600, color: CX.gray500 }} title="Projection calculée à partir des rapports estimés.">Rendement estimé</div>
          <div style={{ fontFamily: CX.sg, fontSize: 20, fontWeight: 700, color: evColor, lineHeight: 1, fontVariantNumeric: "tabular-nums" }}>
            {plan.ev_global > 0 ? "+" : ""}{(plan.ev_global * 100).toFixed(1)}%
          </div>
        </div>
      </div>

      {/* Rendement RÉEL observé — honnêteté (2026-07-13) : l'espérance ci-dessus est
          théorique (rapports estimés) et ressort ~0/+2% ; le rendement réel de ce profil
          est négatif (prélèvement PMU ~15-25%). On l'affiche sans détour. */}
      {plan.roi_observe && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, borderRadius: 12, border: `1px solid ${plan.roi_observe.roi >= 0 ? CX.emBd : CX.redBd}`, background: plan.roi_observe.roi >= 0 ? CX.emBg : CX.redBg, padding: "10px 12px", marginBottom: 12, fontSize: 11.5, lineHeight: 1.4, color: CX.gray600 }}>
          <span style={{ fontFamily: CX.sg, fontWeight: 700, fontSize: 16, color: plan.roi_observe.roi >= 0 ? CX.emDeep : CX.redDeep, flexShrink: 0, fontVariantNumeric: "tabular-nums" }}>
            {plan.roi_observe.roi > 0 ? "+" : ""}{(plan.roi_observe.roi * 100).toFixed(0)}%
          </span>
          <span>
            <b>Rendement réel observé</b> sur {plan.roi_observe.nb} plans · {plan.roi_observe.jours}&nbsp;j
            <span style={{ display: "block", marginTop: 1, fontSize: 10.5, color: CX.gray500 }}>Aucune garantie de gain.</span>
          </span>
        </div>
      )}

      {/* Résumé IA */}
      <details style={{ borderRadius: 12, border: `1px solid ${CX.bd2}`, background: CX.surf2, marginBottom: 16 }}>
        <summary className="select-none" style={{ minHeight: 44, cursor: "pointer", padding: "0 12px", listStyle: "none", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, fontSize: 11.5, fontWeight: 650, color: CX.gray600 }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 7 }}><Info className="h-3.5 w-3.5" aria-hidden="true" /> Lecture de l&apos;algorithme</span>
          <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
        </summary>
        <p style={{ margin: 0, padding: "0 12px 12px 32px", fontSize: 11.5, lineHeight: 1.55, color: CX.gray600 }}>{plan.resume_ia}</p>
      </details>

      {/* Niveaux */}
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {plan.niveaux.map((niv) => {
          const ns = nivStyle(niv.niveau);
          const NiveauIcon = niv.niveau === "securite" ? ShieldCheck : niv.niveau === "rendement" ? TrendingUp : Zap;
          return (
          <section key={niv.niveau} aria-label={niv.label} style={{ borderRadius: 15, overflow: "hidden", background: CX.surf1, border: `1px solid ${ns.bd}`, boxShadow: "0 1px 2px rgba(17,24,39,.025)" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 14px", borderBottom: `1px solid ${CX.bd4}`, background: ns.bg }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ width: 28, height: 28, borderRadius: 9, display: "inline-flex", alignItems: "center", justifyContent: "center", color: ns.color, background: "rgba(255,255,255,.75)", border: "1px solid rgba(255,255,255,.9)" }}><NiveauIcon className="h-4 w-4" aria-hidden="true" /></span>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 12.5, color: CX.ink2 }}>{niv.label}</div>
                  <div style={{ fontSize: 10.5, color: CX.gray500 }}>{niv.pct}% du budget</div>
                </div>
              </div>
              <span style={{ fontFamily: CX.sg, fontWeight: 700, fontSize: 14, color: ns.color, fontVariantNumeric: "tabular-nums" }}>
                {niv.montant.toFixed(2)}€
              </span>
            </div>
            <div style={{ display: "flex", flexDirection: "column" }}>
              {niv.paris.map((p, i) => (
                <div key={i} style={{ padding: "13px 14px", borderTop: i ? `1px solid ${CX.bd4}` : "none" }}>
                  <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) auto", alignItems: "start", gap: 12 }}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 12.5, fontWeight: 700, color: CX.ink2 }}>{p.type}</div>
                      <div style={{ marginTop: 2, fontFamily: CX.sg, fontSize: 15, fontWeight: 650, color: CX.ink }}>{p.chevaux.map(c => `N°${c.numero}`).join(" + ")}</div>
                      <div style={{ marginTop: 3, fontSize: 10.5, color: CX.gray500 }}>Probabilité estimée {(p.probabilite * 100).toFixed(0)}%</div>
                    </div>
                    <div style={{ textAlign: "right", flexShrink: 0 }}>
                      <div style={{ fontFamily: CX.sg, fontSize: 14, fontWeight: 700, color: CX.ink2, fontVariantNumeric: "tabular-nums" }}>{p.mise.toFixed(2)}€</div>
                      <div style={{ marginTop: 3, fontSize: 10.5, fontWeight: 650, color: CX.emDeep }}>Gain estimé ~{p.gain_potentiel.toFixed(0)}€</div>
                    </div>
                  </div>
                  {p.raisons && p.raisons.length > 0 && (
                    <details style={{ marginTop: 8 }}>
                      <summary style={{ minHeight: 32, cursor: "pointer", fontSize: 10.5, color: CX.goldDeep, fontWeight: 650, listStyle: "none", display: "inline-flex", alignItems: "center", gap: 4 }} className="select-none">
                        Voir les raisons <ChevronDown className="h-3 w-3" aria-hidden="true" />
                      </summary>
                      <ul style={{ margin: "2px 0 0", padding: "9px 10px", listStyle: "none", borderRadius: 9, background: CX.surf3, fontSize: 11, color: CX.gray600, lineHeight: 1.5 }}>
                        {p.raisons.map((r, j) => (
                          <li key={j} style={{ display: "flex", gap: 6 }}>
                            <span style={{ color: CX.gold, flexShrink: 0 }}>—</span>
                            <span style={{ minWidth: 0 }}>{r}</span>
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </div>
              ))}
            </div>
          </section>
          );
        })}
      </div>

      {/* Note « champ réduit » — modéré/risqué visent PLUSIEURS petites mises ; s'ils
          tombent à 1 ticket, c'est que la course n'offre qu'un pari dans leur bande de
          gain (petit champ). On l'explique pour ne pas donner l'impression d'un plan
          bâclé. Exclu du prudent, qui joue volontairement UN seul placé sûr (design). */}
      {profil !== "conservateur" && plan.niveaux.reduce((n, niv) => n + niv.paris.length, 0) === 1 && (
        <details style={{ marginTop: 10, borderRadius: 10, background: CX.surf3 }}>
          <summary className="select-none" style={{ minHeight: 40, cursor: "pointer", padding: "0 11px", listStyle: "none", display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: 10.5, fontWeight: 600, color: CX.gray500 }}>
            Pourquoi un seul pari ? <ChevronDown className="h-3 w-3" aria-hidden="true" />
          </summary>
          <p style={{ margin: 0, padding: "0 11px 10px", fontSize: 10.5, color: CX.gray500, lineHeight: 1.5 }}>Cette course n&apos;offre qu&apos;un pari dans la bande de gain du profil. Une course avec plus de partants permettra un plan plus étalé.</p>
        </details>
      )}

      {/* Résumé totaux */}
      <div style={{ display: "grid", gridTemplateColumns: typeof plan.esperance_gain === "number" ? "repeat(2,1fr)" : "1fr", gap: 8, marginTop: 14 }}>
        <div style={cell}>
          <div style={{ fontSize: 10.5, color: CX.gray500 }}>Total joué</div>
          <div style={{ marginTop: 3, fontFamily: CX.sg, fontWeight: 700, fontSize: 14, color: CX.ink2, fontVariantNumeric: "tabular-nums" }}>{plan.montant_joue.toFixed(2)}€</div>
        </div>
        {typeof plan.esperance_gain === "number" && (
          <div style={cell}>
            <div style={{ fontSize: 10.5, color: CX.gray500 }}>Gain projeté</div>
            <div style={{ marginTop: 3, fontFamily: CX.sg, fontWeight: 700, fontSize: 14, color: plan.esperance_gain >= 0 ? CX.emDeep : CX.redDeep, fontVariantNumeric: "tabular-nums" }}>
              {plan.esperance_gain >= 0 ? "+" : ""}{plan.esperance_gain.toFixed(2)}€
            </div>
          </div>
        )}
      </div>

      {/* Paris écartés — transparence : ce que l'IA refuse et POURQUOI */}
      {plan.paris_ecartes && plan.paris_ecartes.length > 0 && (
        <details style={{ marginTop: 10, borderRadius: 12, border: `1px solid ${CX.bd2}`, background: CX.surf2 }}>
          <summary className="select-none" style={{ minHeight: 44, cursor: "pointer", padding: "0 12px", fontSize: 11.5, fontWeight: 600, color: CX.gray600, listStyle: "none", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
            <span>Paris non retenus <span style={{ marginLeft: 4, color: CX.gray400 }}>({plan.paris_ecartes.length})</span></span><ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
          </summary>
          <div style={{ padding: "0 12px 10px", display: "flex", flexDirection: "column", gap: 7 }}>
            {plan.paris_ecartes.map((e, i) => (
              <div key={i} style={{ borderRadius: 9, background: CX.surf1, border: `1px solid ${CX.bd2}`, padding: "9px 10px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8, fontSize: 11.5 }}>
                  <span style={{ fontWeight: 600, color: CX.ink2 }}>
                    {e.type} <span style={{ fontWeight: 400, color: CX.gray400 }}>{e.chevaux.map(c => `N°${c.numero}`).join(" + ")}</span>
                  </span>
                  <span style={{ color: CX.gray400, fontFamily: CX.sg, flexShrink: 0 }}>{(e.probabilite * 100).toFixed(0)}%</span>
                </div>
                <p style={{ margin: "4px 0 0", fontSize: 10.5, lineHeight: 1.4, color: CX.gray500 }}>{e.motif}</p>
              </div>
            ))}
          </div>
        </details>
      )}

      <p style={{ margin: "12px 2px 0", fontSize: 10.5, color: CX.gray500, display: "flex", alignItems: "center", gap: 7, lineHeight: 1.4 }}>
        {plan.prono_fige ? <LockKeyhole className="h-3.5 w-3.5 flex-shrink-0" style={{ color: CX.emDeep }} aria-hidden="true" /> : <Radio className="h-3.5 w-3.5 flex-shrink-0" style={{ color: CX.emDeep }} aria-hidden="true" />}
        {plan.prono_fige
          ? "Sélection figée · gains actualisés jusqu’au départ"
          : "Cotes en direct · gains actualisés automatiquement"}
      </p>

      {plan.kelly_warning ? (
        <div role="alert" style={{ marginTop: 12, borderRadius: 11, border: `1px solid ${CX.redBd}`, background: CX.redBg, padding: "10px 11px", fontSize: 11, lineHeight: 1.45, color: CX.redDeep, display: "flex", gap: 8 }}>
          <AlertTriangle className="h-3.5 w-3.5 mt-0.5 flex-shrink-0" />
          {plan.avertissement}
        </div>
      ) : (
        <details style={{ marginTop: 6 }}>
          <summary className="select-none" style={{ minHeight: 36, cursor: "pointer", listStyle: "none", display: "inline-flex", alignItems: "center", gap: 5, fontSize: 10.5, color: CX.gray500 }}>Conditions du plan <ChevronDown className="h-3 w-3" aria-hidden="true" /></summary>
          <p style={{ margin: "0 0 6px", fontSize: 10.5, lineHeight: 1.45, color: CX.gray500 }}>{plan.avertissement}</p>
        </details>
      )}

      {saveState === "saved" ? (
        <div role="status" style={{ minHeight: 48, marginTop: 12, display: "flex", alignItems: "center", justifyContent: "center", gap: 8, borderRadius: 12, border: `1px solid ${CX.emBd}`, background: CX.emBg, padding: "10px 12px", fontSize: 12.5, fontWeight: 650, color: CX.emDeep }}>
          <CheckCircle2 className="h-4 w-4" /> Paris enregistrés dans votre capital
        </div>
      ) : (
        <button
          onClick={handleSave}
          disabled={saveState === "saving"}
          style={{ width: "100%", minHeight: 48, marginTop: 12, border: `1px solid ${CX.goldDeep}`, cursor: saveState === "saving" ? "wait" : "pointer", background: CX.goldDeep, color: "#FFFFFF", fontWeight: 700, fontSize: 12.5, padding: "12px 14px", borderRadius: 12, boxShadow: "0 5px 14px -9px rgba(146,64,14,.65)", display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 8, opacity: saveState === "saving" ? 0.65 : 1, transition: "background-color .2s, opacity .2s, box-shadow .2s" }}
        >
          {saveState === "saving" ? <><Loader2 className="h-4 w-4 animate-spin" /> Enregistrement…</> : "Enregistrer ce plan"}
        </button>
      )}
      <p style={{ margin: "8px 0 0", textAlign: "center", fontSize: 10, lineHeight: 1.4, color: CX.gray400 }}>
        Calcul final selon les rapports PMU officiels.
      </p>

      <button onClick={onClose} style={{ width: "100%", minHeight: 44, marginTop: 2, border: "none", background: "none", cursor: "pointer", fontSize: 11.5, fontWeight: 600, color: CX.gray500, display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
        <Pencil className="h-3.5 w-3.5" aria-hidden="true" /> Modifier le montant
      </button>
    </div>
  );
}

/* ─── Running style badge ────────────────────────────────────────────────── */
/* ─── Cotes comparaison table ────────────────────────────────────────────── */
function ComparaisonCotes({ partants }: { partants: Partant[] }) {
  const actifs = partants.filter((p) => !p.non_partant);
  // Design handoff : labels de sources en gris uniforme.
  const sources = [
    { key: "cote_pmu",           label: "PMU",     accent: "text-muted-foreground" },
    { key: "cote_geny",          label: "Geny",    accent: "text-muted-foreground" },
    { key: "cote_winamax",       label: "Winamax", accent: "text-muted-foreground" },
    { key: "cote_betclic",       label: "Betclic", accent: "text-muted-foreground" },
    { key: "cote_unibet",        label: "Unibet",  accent: "text-muted-foreground" },
    { key: "cote_bet365",        label: "Bet365",  accent: "text-muted-foreground" },
    { key: "cote_ladbrokes",     label: "Ladbrokes", accent: "text-muted-foreground" },
    { key: "cote_betfair_exchange", label: "Betfair", accent: "text-muted-foreground" },
  ] as const;

  // Ne montrer que les sources qui ont ≥1 cote non-null
  const activeSources = sources.filter((s) =>
    actifs.some((p) => (p as unknown as Record<string, unknown>)[s.key] != null)
  );
  if (activeSources.length <= 1) return null;

  const HEAD_CELL = { padding: "9px 8px", fontSize: 10, fontWeight: 700, textTransform: "uppercase" as const, textAlign: "right" as const, color: CX.gray400, background: CX.surf2 };
  const nbCols = activeSources.length;

  return (
    <div style={{ overflowX: "auto", borderTop: `1px solid ${CX.bd4}` }}>
      <div style={{ display: "grid", gridTemplateColumns: `1.6fr repeat(${nbCols},1fr) 0.8fr`, gap: 0, minWidth: 640 }}>
        {/* En-tête */}
        <div style={{ padding: "9px 14px", fontSize: 10, fontWeight: 700, textTransform: "uppercase", color: CX.gray400, background: CX.surf2 }}>Cheval</div>
        {activeSources.map((s) => (
          <div key={s.key} style={HEAD_CELL}>{s.label}</div>
        ))}
        <div style={{ ...HEAD_CELL, padding: "9px 12px" }}>Mvt</div>
        {/* Rangées */}
        {actifs.map((p) => {
          const coteMin = p.cote_min;
          const mv = p.mouvement_cote_pct;
          return (
            <Fragment key={p.participation_id}>
              <div style={{ padding: "9px 14px", fontSize: 12.5, color: CX.ink2, borderTop: `1px solid ${CX.bd4}` }}>
                <span style={{ color: CX.gray400, marginRight: 5 }}>{p.numero}</span>{p.nom_cheval}
              </div>
              {activeSources.map((s) => {
                const val = (p as unknown as Record<string, unknown>)[s.key] as number | null;
                const isBest = val != null && coteMin != null && val === coteMin;
                return (
                  <div key={s.key} style={{ padding: "9px 8px", fontFamily: CX.sg, fontSize: 12.5, fontWeight: isBest ? 700 : 500, textAlign: "right", color: isBest ? CX.em : val == null ? CX.muted : CX.ink2, borderTop: `1px solid ${CX.bd4}` }}>
                    {val ? val.toFixed(1) : "—"}
                  </div>
                );
              })}
              <div style={{ padding: "9px 12px", fontFamily: CX.sg, fontSize: 12, fontWeight: 600, textAlign: "right", color: mv == null ? CX.muted : mv > 0 ? CX.em : CX.red, borderTop: `1px solid ${CX.bd4}` }}>
                {mv != null ? `${mv > 0 ? "▼" : "▲"} ${Math.abs(mv).toFixed(1)}%` : "—"}
              </div>
            </Fragment>
          );
        })}
      </div>
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
    equidia: "Equidia",
  };

  return (
    <details className="group" style={{ borderRadius: 20, border: `1px solid ${CX.bd1}`, background: CX.surf1, overflow: "hidden" }}>
      <summary className="cursor-pointer select-none" style={{ display: "flex", alignItems: "center", gap: 8, padding: "15px 18px", listStyle: "none" }}>
        <Newspaper className="h-4 w-4" style={{ color: CX.gray500 }} />
        <h3 style={{ margin: 0, fontFamily: CX.sg, fontSize: 15, fontWeight: 700, color: CX.ink2 }}>Pronostics presse</h3>
        <span style={{ fontSize: 11.5, color: CX.gray400 }}>{pronostics.length} source{pronostics.length > 1 ? "s" : ""}</span>
        <ChevronDown className="ml-auto transition-transform group-open:rotate-180 h-4 w-4" style={{ color: CX.gray400 }} />
      </summary>
      <div style={{ padding: "14px 18px", borderTop: `1px solid ${CX.bd4}` }}>

      {consensus.length > 0 && (
        <div style={{ borderRadius: 12, background: CX.goldBg, border: `1px solid ${CX.goldBd}`, padding: "10px 13px", marginBottom: 12 }}>
          <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".05em", color: CX.gold, marginBottom: 7 }}>
            Consensus experts
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {consensus.map(([num, { nb, nom }]) => (
              <span key={num} style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11.5, fontWeight: 600, color: CX.goldDeep, background: "#FFFFFF", border: `1px solid ${CX.goldBd}`, borderRadius: 999, padding: "3px 9px" }}>
                N°{num} {nom && <span style={{ fontWeight: 400, color: CX.gold }}>{nom}</span>}
                <span style={{ fontSize: 10, color: CX.gold }}>×{nb}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="cx-2col" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 9 }}>
        {pronostics.map((p, i) => (
          <div key={i} style={{ borderRadius: 11, border: `1px solid ${CX.bd2}`, background: CX.surf2, padding: "10px 12px" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
              <span style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".04em", color: CX.gray500 }}>
                {SOURCE_LABEL[p.source] ?? p.source}
              </span>
              {p.journaliste && (
                <span style={{ fontSize: 10, color: CX.gray400 }}>{p.journaliste}</span>
              )}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {p.selection.slice(0, 6).map((s, j) => (
                <span key={j} style={{ fontFamily: CX.sg, fontSize: 11, fontWeight: 700, borderRadius: 5, padding: "1px 6px", color: j === 0 ? CX.goldDeep : CX.gray500, background: j === 0 ? "#FDE9C4" : CX.surf5 }}>
                  {s.numero}
                </span>
              ))}
            </div>
            {p.commentaire && (
              <p className="line-clamp-2" style={{ margin: "7px 0 0", fontSize: 11, lineHeight: 1.4, color: CX.gray400 }}>{p.commentaire}</p>
            )}
          </div>
        ))}
      </div>
      </div>
    </details>
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
  // Essai gratuit Free/Découverte (1/jour, backend commit 4ef13d6) : on garde
  // le quota restant renvoyé par l'API pour informer AVANT le clic, et un
  // état dédié pour le 403 "quota atteint" (message clair + CTA /tarifs, pas
  // un simple toast qu'on rate en scrollant).
  const isFreeTier = userPlan === "free" || userPlan === "decouverte";
  const [quotaRestant, setQuotaRestant] = useState<number | null>(null);
  const [quotaExceeded, setQuotaExceeded] = useState(false);
  const [quotaMessage, setQuotaMessage] = useState<string | null>(null);

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
      if (typeof res.data?.quota_restant === "number") setQuotaRestant(res.data.quota_restant);
    } catch (e: unknown) {
      const response = (e as { response?: { data?: { detail?: unknown }; status?: number } })?.response;
      // Le `detail` FastAPI n'est pas TOUJOURS une string (422 de validation Pydantic
      // = liste d'objets) : ne jamais le rendre tel quel dans un composant texte
      // (cause connue du crash React #31 ailleurs dans le projet).
      const detailRaw = response?.data?.detail;
      const detail = typeof detailRaw === "string" ? detailRaw : undefined;
      if (response?.status === 403 && isFreeTier) {
        // Quota d'essai gratuit épuisé aujourd'hui — état dédié, pas un toast qui
        // disparaît : on affiche le message backend (déjà une phrase propre) + CTA.
        setQuotaExceeded(true);
        setQuotaMessage(detail || "Essai gratuit utilisé aujourd'hui — passez à Standard pour un accès illimité.");
        setQuotaRestant(0);
      } else {
        toast.error(detail || "Erreur lors du calcul du plan");
      }
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
    // Suivi de capital = fonctionnalité Standard+ (backend 403 sur /enregistrer-paris
    // pour free/decouverte, cf. courses.py:1112). L'essai gratuit du calculateur laisse
    // VOIR le plan, mais pas le SUIVRE — message honnête plutôt qu'un 403 générique.
    if (isFreeTier) {
      toast.error("Le suivi de capital est réservé aux abonnés Standard et Expert.");
      throw new Error("save_requires_subscription");
    }
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

  // RAFRAÎCHISSEMENT LIVE des gains estimés : tant qu'un plan est affiché et que la course
  // n'est PAS terminée, on recalcule le plan en silence toutes les ~15 s → les gains
  // potentiels suivent les cotes EN DIRECT du marché (sinon l'utilisateur voit un gain figé
  // au moment du clic, trompeur quand la cote bouge). On NE stoppe PLUS au gel T-10 : après
  // le gel la SÉLECTION reste figée (backend) mais les GAINS sont ré-évalués sur les cotes
  // live jusqu'au départ (gains_live_post_gel). Seule la fin de course arrête le refresh.
  useEffect(() => {
    if (!plan || statut === "termine") return;
    const m = parseFloat(montant);
    if (!m || m <= 0) return;
    let cancelled = false;
    const id = setInterval(async () => {
      try {
        const res = await api.post(`/courses/${courseId}/mise-plan`, {
          montant: m,
          profil_risque: profilChoisi,
        });
        if (!cancelled) setPlan(res.data);
      } catch {
        /* refresh silencieux : on garde le dernier plan en cas d'échec transitoire */
      }
    }, 15000);
    return () => { cancelled = true; clearInterval(id); };
  }, [plan, montant, profilChoisi, statut, courseId]);

  // Pas connecté : impossible d'appeler l'API (pas de user_id pour le quota) →
  // CTA connexion plutôt qu'un message "Passer Standard" trompeur pour un visiteur
  // qui n'a même pas encore de compte gratuit.
  if (!userPlan) {
    return (
      <div style={{ textAlign: "center", padding: "24px 0" }}>
        <Calculator className="h-10 w-10 mx-auto mb-3" style={{ color: CX.gold, opacity: 0.6 }} />
        <p style={{ fontSize: 14, fontWeight: 600, marginBottom: 4, color: CX.ink2 }}>Calculateur de mise</p>
        <p style={{ fontSize: 12, color: CX.gray400, marginBottom: 16 }}>
          Entrez votre mise → BlackTurf génère votre plan de pari personnalisé.
        </p>
        <Button variant="brand" size="sm" asChild>
          <Link href={`/login?redirect=/courses/${courseId}`}>Se connecter</Link>
        </Button>
      </div>
    );
  }

  // Essai gratuit Free/Découverte épuisé pour aujourd'hui (403 backend) : message
  // clair + CTA abonnement, pas un simple toast qu'on rate en scrollant plus bas.
  if (quotaExceeded) {
    return (
      <div style={{ textAlign: "center", padding: "24px 0" }}>
        <Calculator className="h-10 w-10 mx-auto mb-3" style={{ color: CX.gold, opacity: 0.6 }} />
        <p style={{ fontSize: 14, fontWeight: 600, marginBottom: 4, color: CX.ink2 }}>Essai gratuit utilisé aujourd&apos;hui</p>
        <p style={{ fontSize: 12, color: CX.gray400, marginBottom: 16 }}>
          {quotaMessage || "Revenez demain pour un nouvel essai gratuit, ou passez à Standard pour un accès illimité au calculateur."}
        </p>
        <CheckoutButton
          plan="standard"
          periodicite="monthly"
          label="Passer Standard — 12€/mois"
          variant="brand"
          className="w-auto"
        />
      </div>
    );
  }

  // Standard+/Expert : le calculateur suppose l'analyse IA déjà lancée (predictions
  // chargées côté page). Free/Découverte n'a JAMAIS `predictions` chargé (paywall du
  // classement, cf. useEffect plus haut qui skip le fetch pour ces plans) — ce n'est
  // PAS un signal d'absence de pronostic pour eux : on les laisse tenter l'appel,
  // le backend renvoie un message clair (409) si le pronostic n'est pas encore prêt.
  if (!isFreeTier && !predictions) {
    return (
      <div style={{ textAlign: "center", padding: "24px 0", color: CX.gray400, fontSize: 13 }}>
        <Brain className="h-8 w-8 mx-auto mb-2" style={{ opacity: 0.4 }} />
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
    <div className="cx-plan">
      {isFreeTier && (
        <p style={{ margin: "0 0 10px", fontSize: 11.5, fontWeight: 600, color: CX.gold, background: CX.goldBg, border: `1px solid ${CX.goldBd}`, borderRadius: 9, padding: "7px 10px" }}>
          {quotaRestant === null
            ? "Essai gratuit — 1 calcul par jour avec votre plan Découverte."
            : quotaRestant > 0
              ? `Essai gratuit — encore ${quotaRestant} aujourd'hui.`
              : "Dernier essai gratuit du jour utilisé."}
        </p>
      )}
      <p style={{ margin: "0 0 16px", fontSize: 12, lineHeight: 1.5, color: CX.gray500 }}>
        Définissez votre budget et votre niveau de risque.
      </p>
      {/* Profil de risque — change quels paris ET la répartition */}
      <div style={{ fontSize: 10.5, fontWeight: 650, color: CX.gray500, marginBottom: 7 }}>Profil de risque</div>
      <div role="tablist" aria-label="Profil de risque" style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 4, borderRadius: 13, background: CX.surf4, padding: 4, marginBottom: 16 }}>
        {PROFILS_MISE.map((p) => {
          const active = profilChoisi === p.key;
          const Icon = p.key === "conservateur" ? ShieldCheck : p.key === "equilibre" ? Gauge : Flame;
          return (
            <button
              key={p.key}
              role="tab"
              aria-selected={active}
              onClick={() => setProfilChoisi(p.key)}
              style={{ minHeight: 44, border: active ? `1px solid ${CX.goldBd}` : "1px solid transparent", background: active ? CX.surf1 : "transparent", color: active ? CX.goldDeep : CX.gray500, borderRadius: 10, padding: "8px 5px", fontSize: 11.5, fontWeight: active ? 700 : 600, cursor: "pointer", transition: "background-color .2s, border-color .2s, color .2s, box-shadow .2s", boxShadow: active ? "0 1px 3px rgba(17,24,39,.08)" : "none", display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6 }}
            >
              <Icon className="h-3.5 w-3.5" aria-hidden="true" /> {p.label}
            </button>
          );
        })}
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <div style={{ position: "relative", flex: 1 }}>
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
            aria-label="Montant du budget"
            style={{ width: "100%", minHeight: 48, border: `1px solid ${CX.bd3}`, borderRadius: 12, background: CX.surf1, padding: "11px 30px 11px 13px", fontSize: 14, fontFamily: CX.sg, fontWeight: 700, color: CX.ink2, outline: "none" }}
          />
          <span style={{ position: "absolute", right: 12, top: "50%", transform: "translateY(-50%)", color: CX.gray400, fontSize: 14 }}>€</span>
        </div>
        <button
          onClick={() => generate()}
          disabled={!montant || parseFloat(montant) <= 0 || loading}
          style={{ minHeight: 48, display: "inline-flex", alignItems: "center", gap: 6, border: `1px solid ${CX.goldDeep}`, cursor: loading ? "wait" : "pointer", background: CX.goldDeep, color: "#FFFFFF", fontWeight: 700, fontSize: 12.5, padding: "0 16px", borderRadius: 12, boxShadow: "0 5px 14px -9px rgba(146,64,14,.65)", opacity: !montant || parseFloat(montant) <= 0 || loading ? 0.55 : 1 }}
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : (
            <>Générer <ChevronRight className="h-3.5 w-3.5" /></>
          )}
        </button>
      </div>
      {/* Quick amounts */}
      <div aria-label="Montants suggérés" style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 6, marginTop: 8 }}>
        {[5, 10, 20, 30].map((v) => (
          <button
            key={v}
            onClick={() => setMontant(String(v))}
            style={{ minHeight: 40, fontSize: 11, fontFamily: CX.sg, fontWeight: 650, padding: "7px 8px", borderRadius: 9, border: `1px solid ${CX.bd3}`, background: CX.surf1, color: CX.gray600, cursor: "pointer", transition: "background-color .2s, border-color .2s" }}
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
// Design handoff : badges rapports PMU en slate uniforme (#64748B),
// sauf Quinté+ / Quarté+ en or (jackpots mis en avant).
const RAPPORT_META: Record<string, { label: string; abbr: string; color: string; ordre: number }> = {
  e_simple_gagnant:            { label: "Simple Gagnant", abbr: "SG", color: "#059669", ordre: 1 },
  simple_gagnant:               { label: "Simple Gagnant", abbr: "SG", color: "#059669", ordre: 1 },
  simple_gagnant_international: { label: "Simple Gagnant (int.)", abbr: "SG", color: "#059669", ordre: 2 },
  e_simple_place:              { label: "Simple Placé", abbr: "SP", color: "#0EA5E9", ordre: 3 },
  simple_place:                 { label: "Simple Placé", abbr: "SP", color: "#0EA5E9", ordre: 3 },
  simple_place_international:   { label: "Simple Placé (int.)", abbr: "SP", color: "#0EA5E9", ordre: 4 },
  e_couple_gagnant:            { label: "Couplé Gagnant", abbr: "CG", color: "#7C3AED", ordre: 5 },
  couple_gagnant:               { label: "Couplé Gagnant", abbr: "CG", color: "#7C3AED", ordre: 5 },
  e_couple_place:              { label: "Couplé Placé", abbr: "CP", color: "#8B5CF6", ordre: 6 },
  couple_place:                 { label: "Couplé Placé", abbr: "CP", color: "#8B5CF6", ordre: 6 },
  e_couple_ordre:              { label: "Couplé Ordre", abbr: "CO", color: "#6D28D9", ordre: 7 },
  couple_ordre:                 { label: "Couplé Ordre", abbr: "CO", color: "#6D28D9", ordre: 7 },
  couple_ordre_international:   { label: "Couplé Ordre (int.)", abbr: "CO", color: "#6D28D9", ordre: 8 },
  e_deux_sur_quatre:           { label: "2 sur 4", abbr: "2/4", color: "#F59E0B", ordre: 9 },
  deux_sur_quatre:              { label: "2 sur 4", abbr: "2/4", color: "#F59E0B", ordre: 9 },
  e_super_quatre:              { label: "Super 4", abbr: "S4", color: "#F59E0B", ordre: 10 },
  super_quatre:                 { label: "Super 4", abbr: "S4", color: "#F59E0B", ordre: 10 },
  e_trio:                      { label: "Trio", abbr: "TRI", color: "#EA580C", ordre: 11 },
  trio:                         { label: "Trio", abbr: "TRI", color: "#EA580C", ordre: 11 },
  e_trio_ordre:                { label: "Trio Ordre", abbr: "TRO", color: "#C2410C", ordre: 12 },
  trio_ordre:                   { label: "Trio Ordre", abbr: "TRO", color: "#C2410C", ordre: 12 },
  e_tierce:                    { label: "Tiercé", abbr: "TIE", color: "#DC2626", ordre: 13 },
  tierce:                       { label: "Tiercé", abbr: "TIE", color: "#DC2626", ordre: 13 },
  tierce_ordre:                 { label: "Tiercé Ordre", abbr: "TIE", color: "#B91C1C", ordre: 13 },
  e_quarte_plus:               { label: "Quarté+", abbr: "Q4", color: "#B45309", ordre: 14 },
  quarte_plus:                  { label: "Quarté+", abbr: "Q4", color: "#B45309", ordre: 14 },
  e_quinte_plus:               { label: "Quinté+", abbr: "Q5", color: "#B45309", ordre: 15 },
  quinte_plus:                  { label: "Quinté+", abbr: "Q5", color: "#B45309", ordre: 15 },
  e_multi:                     { label: "Multi", abbr: "MUL", color: "#0891B2", ordre: 16 },
  multi:                        { label: "Multi", abbr: "MUL", color: "#0891B2", ordre: 16 },
  e_mini_multi:                { label: "Mini Multi", abbr: "mM", color: "#06B6D4", ordre: 17 },
  mini_multi:                   { label: "Mini Multi", abbr: "mM", color: "#06B6D4", ordre: 17 },
  e_pick5:                     { label: "Pick 5", abbr: "P5", color: "#4F46E5", ordre: 18 },
  pick5:                        { label: "Pick 5", abbr: "P5", color: "#4F46E5", ordre: 18 },
  eb5:                         { label: "Pick 5 Bonus", abbr: "B5", color: "#6366F1", ordre: 19 },
  b5:                           { label: "Pick 5 Bonus", abbr: "B5", color: "#6366F1", ordre: 19 },
};

function _rapportAbbr(key: string): string {
  return key.replace(/^e_/, "").split("_").map((w) => w[0]?.toUpperCase() ?? "").join("").slice(0, 3) || "•";
}

function ResultatsSection({ resultats, partants }: {
  resultats: {
    classement: Array<{ numero: number; nom: string; position: number | null; temps: number | null; reduction_km: number | null; incident?: string | null; disqualifie?: boolean }>;
    rapports: Record<string, number> | null;
    rapports_detail: Record<string, Array<{ combinaison: string | null; rapport: number; libelle?: string | null }>> | null;
    temps_gagnant: string | null;
    commentaire: string | null;
    duree_course: number | null;
  };
  partants: Partant[];
}) {
  // Classés (position réelle) triés ; disqualifiés/distancés (position absente +
  // incident PMU) listés à part, EN FIN d'arrivée comme sur la feuille officielle.
  const classement = resultats.classement || [];
  const podium = classement
    .filter((c) => c.position != null)
    .sort((a, b) => (a.position as number) - (b.position as number));
  const disqualifies = classement.filter((c) => c.position == null && (c.disqualifie || c.incident));
  // Libellé FR de l'incident (varie selon le type de course : trot = allure/poteau,
  // galop/obstacle = tombé/distancé/arrêté…). Repli générique pour codes inconnus.
  const fmtIncident = (code: string | null | undefined): string => {
    if (!code) return "Disqualifié";
    const map: Record<string, string> = {
      DISQUALIFIE_POUR_ALLURE_IRREGULIERE: "Disqualifié — allure irrégulière",
      DISQUALIFIE_POUR_PARCOURS_IRREGULIER: "Disqualifié — parcours irrégulier",
      DISQUALIFIE_POTEAU_GALOP: "Disqualifié — galop au poteau",
      ARRETE: "Arrêté",
      TOMBE: "Tombé",
      DISTANCE: "Distancé",
      DEROBE: "Dérobé",
      RESTE_AU_POTEAU: "Resté au poteau",
    };
    if (map[code]) return map[code];
    const txt = code.replace(/_/g, " ").toLowerCase();
    return txt.charAt(0).toUpperCase() + txt.slice(1);
  };
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
    <div className="cx-fade" style={{ borderRadius: 20, border: "1px solid rgba(16,185,129,.3)", overflow: "hidden", background: "linear-gradient(180deg,rgba(16,185,129,.06),#FFFFFF 40%)" }}>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10, padding: "16px 20px", borderBottom: "1px solid rgba(16,185,129,.18)" }}>
        <h2 style={{ margin: 0, fontFamily: CX.sg, fontSize: 17, fontWeight: 700, color: CX.ink2 }}>Arrivée officielle</h2>
        {(tempsGagnant != null || resultats.temps_gagnant) && (
          <span style={{ fontSize: 12, color: CX.gray500 }}>
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
              {hasTemps && <th className="px-2 py-1.5 text-right font-medium hidden sm:table-cell">Écart</th>}
              <th className="px-2 py-1.5 text-right font-medium">Cote</th>
              <th className="px-2 py-1.5 text-right font-medium hidden sm:table-cell">{hasRedKm ? "Réd. km" : "Temps"}</th>
            </tr>
          </thead>
          <tbody>
            {podium.map((c) => {
              const pos = c.position as number;
              const cote = coteByNum[c.numero];
              const temps = c.reduction_km != null ? fmtRedKm(c.reduction_km)
                : c.temps != null ? fmtChrono(c.temps) : "—";
              return (
                <tr key={c.numero} className={cn("rounded-lg", rowTint(pos), pos <= 3 && "font-semibold")}>
                  <td className="px-2 py-2">
                    <span className={cn("inline-flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold tabular-nums", medalBox(pos))}>
                      {pos}
                    </span>
                  </td>
                  <td className="px-2 py-2 tabular-nums">{c.numero}</td>
                  <td className="px-2 py-2">{c.nom}</td>
                  {hasTemps && (
                    <td className="px-2 py-2 text-right font-mono tabular-nums text-muted-foreground hidden sm:table-cell">
                      {fmtEcart({ position: pos, temps: c.temps })}
                    </td>
                  )}
                  <td className="px-2 py-2 text-right font-mono tabular-nums">
                    {cote != null ? cote.toFixed(1) : "—"}
                  </td>
                  <td className="px-2 py-2 text-right font-mono tabular-nums text-muted-foreground hidden sm:table-cell">
                    {temps}
                  </td>
                </tr>
              );
            })}
            {/* Disqualifiés / distancés — en fin d'arrivée, avec le motif PMU. */}
            {disqualifies.map((c) => {
              const cote = coteByNum[c.numero];
              return (
                <tr key={`dsq-${c.numero}`} className="text-muted-foreground">
                  <td className="px-2 py-2">
                    <span className="inline-flex h-6 min-w-[1.6rem] items-center justify-center rounded px-1 text-[10px] font-bold text-white" style={{ background: "#DC2626" }} title={fmtIncident(c.incident)}>
                      DSQ
                    </span>
                  </td>
                  <td className="px-2 py-2 tabular-nums">{c.numero}</td>
                  <td className="px-2 py-2">
                    <span className="line-through decoration-rose-400/60">{c.nom}</span>
                    <span className="ml-2 align-middle text-[11px] font-medium text-rose-700">{fmtIncident(c.incident)}</span>
                  </td>
                  {hasTemps && <td className="px-2 py-2 hidden sm:table-cell" />}
                  <td className="px-2 py-2 text-right font-mono tabular-nums">
                    {cote != null ? cote.toFixed(1) : "—"}
                  </td>
                  <td className="px-2 py-2 text-right font-mono tabular-nums hidden sm:table-cell">—</td>
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
              <p className="px-2 pt-1 text-[11px] text-amber-700">
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
                  // Multi/Mini Multi : 1 entrée par formule « en 4/5/6/7 » (même combinaison),
                  // on affiche le libellé « en N » à côté de chaque rapport.
                  const isMulti = k === "e_multi" || k === "e_mini_multi";
                  const rows = isPlaceOrWin ? arr : arr.slice(0, 6);
                  // « e-Mini Multi en 4 » → « en 4 » (juste la formule, le type est déjà en titre).
                  const fmtMulti = (lib: string | null | undefined): string => {
                    const m = (lib || "").match(/en\s+\d+/i);
                    return m ? m[0].toLowerCase() : "";
                  };
                  return (
                    <div key={k} className="rounded-lg border border-border bg-white p-2.5">
                      <div className="mb-1.5 flex items-center gap-2">
                        <span className="flex h-5 min-w-[1.6rem] items-center justify-center rounded px-1 text-[10px] font-bold text-white" style={{ background: color }}>{abbr}</span>
                        <span className="text-xs font-semibold capitalize">{label}</span>
                      </div>
                      <div className="space-y-0.5">
                        {rows.map((r, i) => (
                          <div key={i} className="flex items-baseline justify-between gap-2 text-xs">
                            <span className="truncate text-muted-foreground">
                              {isMulti
                                ? <>{fmtMulti(r.libelle) && <span className="font-semibold text-foreground">{fmtMulti(r.libelle)}</span>}{fmtMulti(r.libelle) ? " · " : ""}{fmtCombo(r.combinaison)}</>
                                : (fmtCombo(r.combinaison) || "—")}
                            </span>
                            <span className="font-bold tabular-nums text-brand-emerald-dark whitespace-nowrap">{r.rapport.toFixed(2)} €</span>
                          </div>
                        ))}
                        {!isPlaceOrWin && arr.length > rows.length && (
                          <p className="text-[10px] text-muted-foreground">+ {arr.length - rows.length} autres combinaisons gagnantes</p>
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
                      <span className="font-bold tabular-nums text-brand-emerald-dark">{Number(v).toFixed(2)} €</span>
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
// Présentation : verdict d'abord, trois chiffres ensuite, table en dernier — et
// jamais un émoji en guise d'icône (rendu dépendant de la police, impossible à
// mettre aux couleurs du site).
function PronosticVerdictSection({ predictions, classement }: {
  predictions: Prediction[];
  classement: Array<{ numero: number; nom: string; position: number | null }>;
}) {
  const posByNum = new Map<number, number | null>();
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
  // Combien des cinq chevaux retenus par le modèle ont réellement fini dans les cinq.
  const dansTop5 = picks.filter((p) => {
    const pos = posByNum.get(p.numero);
    return pos != null && pos <= 5;
  }).length;

  const ord = (n: number) => (n === 1 ? "1ᵉʳ" : `${n}ᵉ`);

  // Verdict global, du meilleur au moins bon.
  const verdict = favGagne
    ? { label: "Gagnant trouvé — le favori du modèle a gagné", cls: "bg-emerald-600 text-white", Icone: Trophy }
    : favPlace
    ? { label: `Favori du modèle placé ${ord(favPos!)}`, cls: "bg-emerald-600 text-white", Icone: CheckCircle2 }
    : gagnantDansTop3IA
    ? { label: `Vainqueur dans le top 3 du modèle (classé ${ord(rangIAduGagnant!)})`, cls: "bg-amber-500 text-brand-dark", Icone: CheckCircle2 }
    : { label: "Pronostic manqué", cls: "bg-stone-700 text-white", Icone: X };

  const pickVerdict = (pos: number | null | undefined) => {
    if (pos == null) return { Icone: Minus, txt: "non classé", cls: "bg-stone-100 text-stone-600 ring-stone-200", ligne: "" };
    if (pos === 1) return { Icone: Trophy, txt: "1ᵉʳ", cls: "bg-amber-100 text-amber-900 ring-amber-300", ligne: "bg-amber-50/50" };
    if (pos <= 3) return { Icone: CheckCircle2, txt: ord(pos), cls: "bg-emerald-50 text-emerald-700 ring-emerald-200", ligne: "bg-emerald-50/40" };
    return { Icone: X, txt: ord(pos), cls: "bg-stone-100 text-stone-600 ring-stone-200", ligne: "" };
  };

  const maxP3 = Math.max(...picks.map((p) => p.proba_top3 || 0), 0.01);

  return (
    <div className="cx-fade" style={{ borderRadius: 20, border: `1px solid ${CX.bd1}`, background: CX.surf1, padding: "20px 20px 22px" }}>
      <header className="mb-4 flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div>
          <h2 className="font-display text-[17px] font-bold leading-tight text-slate-900">Bilan du pronostic</h2>
          <p className="mt-1 text-[12.5px] text-stone-600">
            Le classement du modèle, tel qu&apos;il était figé avant le départ, face à l&apos;arrivée officielle.
          </p>
        </div>
        <span className="inline-flex flex-shrink-0 items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-semibold text-emerald-700 ring-1 ring-emerald-200">
          <LockKeyhole className="h-3 w-3" aria-hidden="true" /> Figé avant le départ
        </span>
      </header>

      <div className="overflow-hidden rounded-xl border border-stone-200 bg-white">
        <div className="flex flex-wrap items-center gap-2 border-b border-stone-100 bg-stone-50/70 px-3 py-2 sm:px-4">
          <span className={cn("inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[12px] font-semibold", verdict.cls)}>
            <verdict.Icone className="h-3.5 w-3.5" aria-hidden="true" />
            {verdict.label}
          </span>
          {gagnant && (
            <span className="text-[12px] text-stone-600">
              vainqueur <span className="font-semibold text-slate-900">N°{gagnant.numero} {gagnant.nom}</span>
              {rangIAduGagnant != null
                ? <> · classé {ord(rangIAduGagnant)} par le modèle</>
                : <> · absent du classement du modèle</>}
            </span>
          )}
        </div>

        <div className="grid grid-cols-3 divide-x divide-stone-100">
          <div className="px-3 py-2.5 sm:px-4">
            <div className="text-[10.5px] font-semibold uppercase tracking-[0.09em] text-stone-600">Favori du modèle</div>
            <div className={cn(
              "mt-1 font-display text-[22px] font-bold leading-none tabular-nums",
              favGagne ? "text-amber-700" : favPlace ? "text-emerald-700" : "text-slate-900",
            )}>
              {favPos != null ? ord(favPos) : "—"}
            </div>
            <div className="mt-1 hidden truncate text-[11px] text-stone-600 sm:block">
              {favPos == null
                ? "non classé à l'arrivée"
                : favoriIA ? `N°${favoriIA.numero} ${favoriIA.nom_cheval}` : ""}
            </div>
          </div>
          <div className="px-3 py-2.5 sm:px-4">
            <div className="text-[10.5px] font-semibold uppercase tracking-[0.09em] text-stone-600">Rang du gagnant</div>
            <div className={cn(
              "mt-1 font-display text-[22px] font-bold leading-none tabular-nums",
              gagnantDansTop3IA ? "text-emerald-700" : "text-slate-900",
            )}>
              {rangIAduGagnant != null ? ord(rangIAduGagnant) : "—"}
            </div>
            <div className="mt-1 hidden text-[11px] text-stone-600 sm:block">dans le classement du modèle</div>
          </div>
          <div className="px-3 py-2.5 sm:px-4">
            <div className="text-[10.5px] font-semibold uppercase tracking-[0.09em] text-stone-600">Top 5 du modèle</div>
            <div className="mt-1 font-display text-[22px] font-bold leading-none tabular-nums text-slate-900">
              {dansTop5}<span className="text-[13px] font-normal text-stone-600">/{picks.length}</span>
            </div>
            <div className="mt-1 hidden text-[11px] text-stone-600 sm:block">dans les cinq premiers</div>
          </div>
        </div>
      </div>

      <div className="mt-4 overflow-hidden rounded-xl border border-stone-200 bg-white">
        <div className="hidden grid-cols-[30px_minmax(0,1fr)_120px_92px] items-center gap-3 border-b border-stone-100 bg-stone-50/70 px-3 py-2 text-[10px] font-semibold uppercase tracking-wider text-stone-600 sm:grid">
          <span className="text-center">#</span>
          <span>Cheval</span>
          <span className="text-right" title="Probabilité de terminer dans les trois premiers">Proba top-3</span>
          <span className="text-right">Arrivée</span>
        </div>
        {picks.map((p) => {
          const pos = posByNum.get(p.numero);
          const pv = pickVerdict(pos);
          return (
            <div
              key={p.participation_id}
              className={cn(
                "grid grid-cols-[30px_minmax(0,1fr)_92px] items-center gap-3 border-b border-stone-100 px-3 py-2.5 last:border-b-0 sm:grid-cols-[30px_minmax(0,1fr)_120px_92px]",
                pv.ligne,
              )}
            >
              <span className={cn(
                "flex h-7 w-7 items-center justify-center rounded-lg font-display text-[13px] font-bold tabular-nums ring-1",
                p.rang_predit === 1 ? "bg-amber-100 text-amber-900 ring-amber-200"
                  : p.rang_predit <= 3 ? "bg-stone-100 text-slate-700 ring-stone-200"
                  : "bg-white text-stone-600 ring-stone-200",
              )}>
                {p.rang_predit}
              </span>

              <div className="min-w-0">
                {/* Le NUMÉRO domine le nom : c'est lui qu'on coche sur un ticket,
                    qu'annonce le commentaire de course et qu'on retrouve dans
                    l'arrivée officielle. */}
                <span className="flex items-baseline gap-1.5 truncate">
                  <span className="font-display text-[15px] font-bold tabular-nums text-slate-900">N°{p.numero}</span>
                  <span className="truncate text-[13px] text-stone-600">{p.nom_cheval}</span>
                </span>
                <div className="mt-1 flex items-center gap-2 sm:hidden">
                  <div className="h-1.5 w-16 overflow-hidden rounded-full bg-stone-100">
                    <div className="h-full rounded-full bg-stone-300" style={{ width: `${Math.max(2, ((p.proba_top3 || 0) / maxP3) * 100)}%` }} />
                  </div>
                  <span className="text-[11px] tabular-nums text-muted-foreground">
                    top-3 {Math.round((p.proba_top3 || 0) * 100)} %
                  </span>
                </div>
              </div>

              <div className="hidden items-center gap-2 sm:flex">
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-stone-100">
                  <div className="h-full rounded-full bg-stone-300" style={{ width: `${Math.max(2, ((p.proba_top3 || 0) / maxP3) * 100)}%` }} />
                </div>
                <span className="w-10 shrink-0 text-right font-display text-[13px] font-bold tabular-nums text-slate-900">
                  {Math.round((p.proba_top3 || 0) * 100)} %
                </span>
              </div>

              <span className="justify-self-end">
                <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-1 text-[11.5px] font-semibold tabular-nums ring-1", pv.cls)}>
                  <pv.Icone className="h-3 w-3" aria-hidden="true" />
                  {pv.txt}
                </span>
              </span>
            </div>
          );
        })}
      </div>

      <p className="mt-2.5 text-[11px] leading-4 text-stone-600">
        Le rang vient d&apos;un modèle d&apos;ordonnancement dédié : il ne suit pas toujours l&apos;ordre
        des probabilités affichées.
      </p>
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

/* ─── Bilan du plan : pièces d'affichage ─────────────────────────────────────
   Le bloc est la vitrine post-course : un visiteur doit comprendre en un coup
   d'œil ce que le plan a misé, ce qu'il a rapporté, et si le modèle avait vu
   l'arrivée. D'où la hiérarchie : verdict → 4 chiffres → confrontation
   modèle/arrivée alignée par rang → détail des paris → CTA.
   Aucune information n'est portée par la seule couleur (règle a11y) : chaque
   état porte aussi une icône et un mot. */

/** Montant en euros, écriture française (virgule décimale). Le reste du site
 *  affichait « -10.00€ » : un point décimal dans un montant, ça se lit deux fois. */
const eur = (v: number, d = 2) =>
  `${v.toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d })}€`;

const PROFIL_TAB_META: Record<string, { icone: typeof ShieldCheck; label: string; sous: string }> = {
  conservateur: { icone: ShieldCheck, label: "Prudent", sous: "peu de paris" },
  equilibre: { icone: Gauge, label: "Modéré", sous: "équilibré" },
  agressif: { icone: Flame, label: "Risqué", sous: "gros rapports" },
};

/** Un chiffre du bandeau de résultat. Libellé discret au-dessus, valeur en
 *  chiffres tabulaires : les colonnes restent alignées d'un profil à l'autre. */
function BilanKpi({ libelle, valeur, ton = "neutre", aide }: {
  libelle: string;
  valeur: string;
  ton?: "neutre" | "positif" | "negatif" | "attente";
  aide?: string;
}) {
  const couleur =
    ton === "positif" ? "text-emerald-700"
    : ton === "negatif" ? "text-rose-700"
    : ton === "attente" ? "text-amber-700"
    : "text-slate-900";
  return (
    <div className="px-3 py-2.5 sm:px-4">
      <div className="text-[10.5px] font-semibold uppercase tracking-[0.09em] text-stone-600">{libelle}</div>
      <div className={cn("mt-1 font-display text-[22px] font-bold leading-none tabular-nums sm:text-2xl", couleur)}>
        {valeur}
      </div>
      {aide && <div className="mt-1 text-[11px] leading-tight text-stone-600">{aide}</div>}
    </div>
  );
}

/** Statut d'un pari : icône + mot + montant. Jamais la couleur seule. */
function StatutPari({ statut, gain }: { statut: "gagne" | "perdu" | "en_attente"; gain: number | null }) {
  if (statut === "gagne") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-[12px] font-semibold text-emerald-700 ring-1 ring-emerald-200">
        <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
        <span className="tabular-nums">+{eur(gain ?? 0)}</span>
      </span>
    );
  }
  if (statut === "en_attente") {
    return (
      <span
        title="Rapport PMU pas encore publié"
        className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2.5 py-1 text-[12px] font-semibold text-amber-700 ring-1 ring-amber-200"
      >
        <Clock className="h-3.5 w-3.5" aria-hidden="true" />
        Gagné · rapport en attente
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-stone-100 px-2.5 py-1 text-[12px] font-medium text-stone-600 ring-1 ring-stone-200">
      <X className="h-3.5 w-3.5" aria-hidden="true" />
      Perdu
    </span>
  );
}

/* Détail des paris réglés d'un profil. Table réelle (lisible au lecteur
   d'écran), qui défile dans son propre conteneur sur mobile. */
function BilanDetail({ bilan }: { bilan: BilanData }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-stone-200 bg-white">
      <table className="w-full min-w-[460px] border-collapse text-[13px]">
        <caption className="sr-only">Détail des paris du plan et de leur règlement</caption>
        <thead>
          <tr className="bg-stone-50 text-left text-[10.5px] uppercase tracking-[0.08em] text-stone-600">
            <th scope="col" className="px-3 py-2 font-semibold">Pari</th>
            <th scope="col" className="px-3 py-2 font-semibold">Chevaux</th>
            <th scope="col" className="px-3 py-2 text-right font-semibold">Mise</th>
            <th scope="col" className="px-3 py-2 text-right font-semibold">Résultat</th>
          </tr>
        </thead>
        <tbody>
          {bilan.paris.map((p, i) => (
            <tr
              key={i}
              className={cn(
                "border-t border-stone-100",
                p.statut === "gagne" && "bg-emerald-50/40",
              )}
            >
              <td className="px-3 py-2.5 font-medium text-slate-900">{p.type}</td>
              <td className="px-3 py-2.5 font-mono text-[12px] text-stone-600">
                {p.chevaux.map((c) => `N°${c.numero}`).join(" + ")}
              </td>
              <td className="px-3 py-2.5 text-right tabular-nums text-stone-600">{eur(p.mise, 0)}</td>
              <td className="px-3 py-2.5 text-right">
                <StatutPari statut={p.statut} gain={p.gain} />
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-stone-200 bg-stone-50/80">
            <td className="px-3 py-2.5 font-semibold text-slate-900" colSpan={2}>
              Total — {bilan.nb_gagnes} pari{bilan.nb_gagnes > 1 ? "s" : ""} gagné{bilan.nb_gagnes > 1 ? "s" : ""} sur {bilan.nb_paris}
            </td>
            <td className="px-3 py-2.5 text-right font-semibold tabular-nums text-slate-900">
              {eur(bilan.total_mise, 0)}
            </td>
            <td className={cn(
              "px-3 py-2.5 text-right font-display font-bold tabular-nums",
              bilan.total_gain > 0 ? "text-emerald-700" : "text-stone-600",
            )}>
              {eur(bilan.total_gain)}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

/** Confrontation modèle / arrivée, ALIGNÉE PAR RANG.
 *  L'ancienne version affichait deux nuages de pastilles + une légende de
 *  couleurs : il fallait décoder avant de comprendre. Ici chaque ligne répond à
 *  « à ce rang, le modèle disait X, la course a donné Y ». */
function ConfrontationRangs({ predN, realN, gagnant, rangGagnant, modeleAVuGagnant }: {
  predN: number[];
  realN: number[];
  gagnant: number | null;
  rangGagnant: number | null;
  modeleAVuGagnant: boolean;
}) {
  const realSet = new Set(realN);
  const predSet = new Set(predN);
  const lignes = Array.from({ length: Math.max(predN.length, realN.length) }, (_, i) => ({
    rang: i + 1,
    pred: predN[i] ?? null,
    reel: realN[i] ?? null,
  }));
  const trouves = predN.filter((n) => realSet.has(n)).length;

  return (
    <section aria-label="Comparaison du pronostic et de l'arrivée">
      <header className="mb-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <h3 className="font-display text-[13.5px] font-bold text-slate-900">Le modèle face à l&apos;arrivée</h3>
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1" aria-hidden="true">
            {predN.map((n, i) => (
              <span
                key={i}
                className={cn(
                  "h-2 w-2 rounded-full",
                  realSet.has(n) ? "bg-emerald-500" : "bg-stone-200",
                )}
              />
            ))}
          </span>
          <span className="text-[12px] font-semibold tabular-nums text-stone-600">
            {trouves}/{predN.length} chevaux trouvés
          </span>
        </div>
      </header>

      <div className="overflow-hidden rounded-xl border border-stone-200 bg-white">
        <div className="grid grid-cols-[2.5rem_1fr_1fr] gap-2 border-b border-stone-100 bg-stone-50 px-3 py-2 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-stone-600">
          <span>Rang</span>
          <span><span className="sm:hidden">Modèle</span><span className="hidden sm:inline">Pronostic du modèle</span></span>
          <span><span className="sm:hidden">Arrivée</span><span className="hidden sm:inline">Arrivée réelle</span></span>
        </div>
        {lignes.map(({ rang, pred, reel }) => {
          const predHit = pred != null && realSet.has(pred);
          const reelVu = reel != null && predSet.has(reel);
          const reelGagnant = rang === 1;
          return (
            <div
              key={rang}
              className="grid grid-cols-[2.5rem_1fr_1fr] items-center gap-2 border-b border-stone-100 px-3 py-2 last:border-b-0"
            >
              <span className="font-display text-[13px] font-bold tabular-nums text-stone-300">{rang}</span>

              <span className="flex items-center gap-1.5">
                {pred != null ? (
                  <>
                    <span className={cn(
                      "inline-flex items-center rounded-lg px-2 py-1 font-display text-[13px] font-bold tabular-nums ring-1",
                      predHit ? "bg-emerald-50 text-emerald-700 ring-emerald-200" : "bg-stone-50 text-stone-600 ring-stone-200",
                    )}>
                      N°{pred}
                    </span>
                    {predHit && (
                      <span className="inline-flex items-center gap-0.5 text-[11px] font-medium text-emerald-700">
                        <CheckCircle2 className="h-3 w-3" aria-hidden="true" />
                        <span className="hidden sm:inline">dans l&apos;arrivée</span>
                      </span>
                    )}
                  </>
                ) : (
                  <span className="text-[12px] text-stone-300">—</span>
                )}
              </span>

              <span className="flex items-center gap-1.5">
                {reel != null ? (
                  <>
                    <span className={cn(
                      "inline-flex items-center rounded-lg px-2 py-1 font-display text-[13px] font-bold tabular-nums ring-1",
                      reelGagnant ? "bg-amber-100 text-amber-800 ring-amber-300"
                        : reelVu ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
                        : "bg-stone-50 text-stone-600 ring-stone-200",
                    )}>
                      N°{reel}
                    </span>
                    {reelGagnant && (
                      <span className="inline-flex items-center gap-0.5 text-[11px] font-semibold text-amber-700">
                        <Trophy className="h-3 w-3" aria-hidden="true" />
                        <span className="hidden sm:inline">vainqueur</span>
                      </span>
                    )}
                  </>
                ) : (
                  <span className="text-[12px] text-stone-300">—</span>
                )}
              </span>
            </div>
          );
        })}
      </div>

      {gagnant != null && (
        <p className="mt-2 text-[12px] text-stone-600">
          Vainqueur <span className="font-semibold text-slate-900">N°{gagnant}</span> —{" "}
          {modeleAVuGagnant ? (
            <span className="font-medium text-emerald-700">
              trouvé : le modèle le classait {rangGagnant === 1 ? "1ᵉʳ" : `${rangGagnant}ᵉ`}
            </span>
          ) : (
            <span className="font-medium text-rose-700">
              manqué{rangGagnant ? ` : le modèle le classait ${rangGagnant === 1 ? "1ᵉʳ" : `${rangGagnant}ᵉ`}` : ""}
            </span>
          )}
        </p>
      )}
    </section>
  );
}

// `paywall` = visiteur anonyme ou plan Découverte/Free : le bilan lui est montré
// (course terminée ⇒ rien d'exploitable ne fuite) et se termine par un CTA — c'est
// exactement « ce que vous auriez fait en suivant les plans de mise du site ».
function BilanMiseSection({ courseId, paywall = false }: { courseId: string; paywall?: boolean }) {
  const [data, setData] = useState<BilanResp | null>(null);
  const [state, setState] = useState<"loading" | "ok" | "error">("loading");
  const [sel, setSel] = useState<"conservateur" | "equilibre" | "agressif">("equilibre");

  useEffect(() => {
    let alive = true;
    let iv: ReturnType<typeof setInterval> | null = null;
    // Le composant est désormais monté sur TOUTE course terminée (plus seulement
    // quand des prédictions sont chargées côté client) : une course sans pronostic
    // enregistré renverrait 404 à l'infini. On borne donc les échecs consécutifs.
    let echecs = 0;
    const load = () =>
      api.get(`/courses/${courseId}/bilan-pronostic?montant=10`, { tolere401: true })
        .then((r) => {
          if (!alive) return;
          const d = r.data as BilanResp;
          echecs = 0;
          setData(d);
          setState("ok");
          // On NE stoppe le polling QUE lorsque TOUT est réglé. Tant qu'un pari attend
          // son rapport PMU (Multi/Mini Multi publiés en différé après l'arrivée), on
          // continue de re-fetch → le bilan se met à jour DÈS que le rapport arrive,
          // sans rechargement manuel (avant : on s'arrêtait au 1er succès et le
          // « en attente » restait figé même une fois le rapport publié).
          const pending = (d.bilans_profils ?? []).some(
            (b) => b?.verdict === "en_attente" || b?.bilan?.en_attente,
          ) || (!d.bilans_profils && (d.verdict === "en_attente" || d.bilan?.en_attente));
          if (!pending && iv) { clearInterval(iv); iv = null; } // tout réglé → stop
        })
        .catch(() => {
          // 404 = arrivee PMU pas encore publiee (course juste terminee) → on
          // retentera. On ne fige pas en "error" pour laisser le retry afficher
          // le bilan des qu'il est disponible.
          if (!alive) return;
          setState((prev) => (prev === "ok" ? prev : "loading"));
          // Course sans pronostic / sans rapport publiable : au bout de ~5 min on
          // arrête, inutile de marteler l'API (l'endpoint est public maintenant).
          if (++echecs >= 20 && iv) { clearInterval(iv); iv = null; }
        });
    load();
    iv = setInterval(load, 15000); // re-fetch jusqu'à ce que tous les rapports soient publiés
    return () => { alive = false; if (iv) clearInterval(iv); };
  }, [courseId]);

  if (state !== "ok" || !data) return null;
  const { comparaison: cmp } = data;

  // Bilans par profil (fallback : bilan unique legacy mappé sur "modéré")
  const profils: BilanProfil[] = data.bilans_profils && data.bilans_profils.length
    ? data.bilans_profils
    : [{ profil: "equilibre", profil_label: "Modéré", mode_adaptatif: "normal", esperance_gain: 0, bilan: data.bilan, verdict: data.verdict, source: data.source }];
  const cur = profils.find((b) => b.profil === sel) ?? profils[0];
  const bilan = cur.bilan;
  const attente = cur.verdict === "en_attente";

  const vCfg = cur.verdict === "gagnant"
    ? { label: "Plan gagnant", cls: "bg-emerald-600 text-white", Icone: CheckCircle2 }
    : cur.verdict === "perdant"
    ? { label: "Plan perdant", cls: "bg-stone-700 text-white", Icone: X }
    : { label: `En attente de ${bilan.nb_en_attente} rapport${bilan.nb_en_attente > 1 ? "s" : ""} PMU`, cls: "bg-amber-500 text-brand-dark", Icone: Clock };

  const predN = cmp.predicted_top5 ?? cmp.predicted_top3;
  const realN = cmp.actual_top5 ?? cmp.actual_top3;

  return (
    <div
      className="cx-fade"
      style={{ borderRadius: 20, border: "1px solid rgba(245,158,11,.3)", background: "linear-gradient(180deg,#FFFBF0,#FFFFFF 40%)", padding: "20px 20px 22px" }}
    >
      {/* ── En-tête : ce qu'on regarde, et la garantie d'intégrité ────────── */}
      <header className="mb-5 flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <h2 className="font-display text-[17px] font-bold leading-tight text-slate-900">
            Bilan du plan de mise
            <span className="ml-2 rounded-full bg-stone-900 px-2.5 py-0.5 align-middle text-[11px] font-semibold text-white tabular-nums">
              {data.montant}€
            </span>
          </h2>
          <p className="mt-1 text-[12.5px] leading-snug text-stone-600">
            {cur.source === "fige"
              ? "Plan figé avant le départ, réglé aux rapports PMU réels."
              : "Simulation rétrospective sur l'arrivée réelle, réglée aux rapports PMU."}
          </p>
        </div>
        {cur.source === "fige" && (
          <span
            title={cur.fige_le ? `Plan figé le ${new Date(cur.fige_le).toLocaleString("fr-FR", { timeZone: "Europe/Paris" })}, avant le départ — identique au palmarès` : "Plan figé avant le départ — identique au palmarès"}
            className="inline-flex flex-shrink-0 items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-semibold text-emerald-700 ring-1 ring-emerald-200"
          >
            <LockKeyhole className="h-3 w-3" aria-hidden="true" />
            Figé avant le départ
          </span>
        )}
      </header>

      {/* ── Profils : trois méthodes de jeu, trois résultats ──────────────── */}
      {profils.length > 1 && (
        <div className="mb-4">
          <div className="mb-1.5 text-[10.5px] font-semibold uppercase tracking-[0.09em] text-stone-600">
            Profil de risque
          </div>
          <div role="tablist" aria-label="Profil de risque" className="grid grid-cols-3 gap-2">
            {profils.map((b) => {
              const meta = PROFIL_TAB_META[b.profil] ?? { icone: Gauge, label: b.profil_label, sous: "" };
              const Icone = meta.icone;
              const net = b.bilan.net;
              const actif = sel === b.profil;
              return (
                <button
                  key={b.profil}
                  role="tab"
                  aria-selected={actif}
                  onClick={() => setSel(b.profil)}
                  className={cn(
                    "min-h-[62px] rounded-xl border px-2.5 py-2 text-left transition-colors",
                    actif
                      ? "border-amber-400 bg-amber-50 shadow-[0_1px_3px_rgba(17,24,39,.08)]"
                      : "border-stone-200 bg-white hover:border-amber-300",
                  )}
                >
                  <span className={cn(
                    "flex items-center gap-1.5 text-[11.5px] font-semibold",
                    actif ? "text-amber-900" : "text-stone-600",
                  )}>
                    <Icone className="h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
                    {meta.label}
                  </span>
                  <span className={cn(
                    "mt-1 block font-display text-[15px] font-bold tabular-nums",
                    b.verdict === "en_attente" ? "text-amber-700" : net >= 0 ? "text-emerald-700" : "text-rose-700",
                  )}>
                    {b.verdict === "en_attente" ? "en attente" : `${net >= 0 ? "+" : ""}${eur(net, 0)}`}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Le résultat, en quatre chiffres ───────────────────────────────── */}
      <div className="mb-5 overflow-hidden rounded-xl border border-stone-200 bg-white">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-stone-100 bg-stone-50/70 px-3 py-2 sm:px-4">
          <span className={cn("inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[12px] font-semibold", vCfg.cls)}>
            <vCfg.Icone className="h-3.5 w-3.5" aria-hidden="true" />
            {vCfg.label}
          </span>
          <span className="text-[11.5px] text-stone-600">
            profil <span className="font-semibold text-stone-700">{cur.profil_label}</span>
            {bilan.provisoire ? " · résultat provisoire" : ""}
          </span>
        </div>
        <div className="grid grid-cols-2 divide-x divide-stone-100 sm:grid-cols-4">
          <BilanKpi libelle="Misé" valeur={eur(bilan.total_mise, 0)} />
          <BilanKpi
            libelle="Récupéré"
            valeur={eur(bilan.total_gain)}
            ton={bilan.total_gain > 0 ? "positif" : "neutre"}
            aide={`${bilan.nb_gagnes} gagné${bilan.nb_gagnes > 1 ? "s" : ""} sur ${bilan.nb_paris} pari${bilan.nb_paris > 1 ? "s" : ""}`}
          />
          <BilanKpi
            libelle="Résultat net"
            valeur={`${bilan.net >= 0 ? "+" : ""}${eur(bilan.net)}`}
            ton={attente ? "attente" : bilan.net >= 0 ? "positif" : "negatif"}
          />
          <BilanKpi
            libelle="ROI"
            valeur={`${bilan.roi >= 0 ? "+" : ""}${bilan.roi}%`}
            ton={attente ? "attente" : bilan.roi >= 0 ? "positif" : "negatif"}
            aide="rapporté à la mise"
          />
        </div>
      </div>

      {/* ── Le modèle face à l'arrivée ────────────────────────────────────── */}
      <div className="mb-5">
        <ConfrontationRangs
          predN={predN}
          realN={realN}
          gagnant={cmp.gagnant_reel}
          rangGagnant={cmp.rang_predit_gagnant}
          modeleAVuGagnant={cmp.modele_a_vu_gagnant}
        />
      </div>

      {/* ── Détail des paris du profil sélectionné ────────────────────────── */}
      <h3 className="mb-2 font-display text-[13.5px] font-bold text-slate-900">
        Les paris de ce plan
      </h3>
      <BilanDetail bilan={bilan} />

      <p className="mt-2.5 text-[11px] leading-relaxed text-stone-600">
        {cur.source === "fige"
          ? "Plan figé avant le départ, réglé aux rapports PMU réels. Jouez responsable."
          : "Simulation rétrospective réglée aux rapports PMU réels. Jouez responsable."}
      </p>

      {/* ── CTA non abonné ───────────────────────────────────────────────────
          Ce que le visiteur vient de lire, c'est le plan qu'il n'a PAS pu suivre.
          On le dit tel quel, avec le meilleur profil du jour — gagnant OU perdant :
          jamais de gain promis, la course sert d'exemple, pas d'argument de rendement. */}
      {paywall && (() => {
        const regles = profils.filter((b) => b.verdict !== "en_attente");
        const best = regles.length
          ? regles.reduce((a, b) => (b.bilan.net > a.bilan.net ? b : a))
          : null;
        return (
          <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50/60 p-4">
            <p className="text-[13.5px] font-semibold text-amber-900">
              Ce plan ne vous a pas été montré avant le départ.
            </p>
            <p className="mt-1.5 text-[12.5px] leading-relaxed text-amber-900">
              {best && best.bilan.net > 0 ? (
                <>
                  Sur cette course, le profil <strong>{best.profil_label}</strong> ressort à{" "}
                  <strong className="tabular-nums text-emerald-700">+{eur(best.bilan.net)}</strong>{" "}
                  pour {data.montant}€ misés. Une course ne fait pas un rendement — le détail
                  course par course est dans le palmarès public.
                </>
              ) : best ? (
                <>
                  Sur cette course, le meilleur profil (<strong>{best.profil_label}</strong>) finit à{" "}
                  <strong className="tabular-nums text-rose-700">{eur(best.bilan.net)}</strong>{" "}
                  pour {data.montant}€ misés. On affiche les plans perdants comme les gagnants :
                  c&apos;est le même bilan que celui du palmarès public.
                </>
              ) : (
                <>
                  Le règlement de ce plan attend encore des rapports PMU. Les bilans complets,
                  course par course, sont dans le palmarès public.
                </>
              )}
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <CheckoutButton
                plan="standard"
                periodicite="monthly"
                label="Recevoir les plans avant le départ — 12€/mois"
                variant="brand"
                size="default"
                className="w-auto"
              />
              <Link
                href="/track-record"
                className="text-[12.5px] font-medium text-stone-600 underline underline-offset-2 hover:text-amber-700"
              >
                Voir le palmarès complet
              </Link>
            </div>
          </div>
        );
      })()}
    </div>
  );
}

// ─── Marché des cotes (live) ────────────────────────────────────────────────────
// Affiché uniquement avant/pendant la course. Poll les cotes PMU toutes les 5 s.
// Une carte par cheval : cote actuelle + variation + graphe individuel d'évolution.

/* ─── Détail d'un partant (réutilisé : ligne dépliée desktop + carte mobile) ─── */

/** Équipement des pieds, en français lisible. Les valeurs viennent du PMU en
 *  constantes tronquées à 30 caractères ; on les traduit, et toute valeur
 *  inconnue retombe sur un nettoyage générique plutôt que sur du charabia. */
const LIBELLE_DEFERRE: Record<string, string> = {
  DEFERRE_ANTERIEURS_POSTERIEURS: "Déferré des 4 pieds",
  DEFERRE_ANTERIEURS: "Déferré des antérieurs",
  DEFERRE_POSTERIEURS: "Déferré des postérieurs",
  PROTEGE_ANTERIEURS_DEFERRRE_PO: "Protégé devant · déferré derrière",
  DEFERRE_ANTERIEURS_PROTEGE_POS: "Déferré devant · protégé derrière",
  PROTEGE_ANTERIEURS: "Protégé des antérieurs",
  PROTEGE_POSTERIEURS: "Protégé des postérieurs",
  PROTEGE_ANTERIEURS_POSTERIEURS: "Protégé des 4 pieds",
  REFERRE_ANTERIEURS_POSTERIEURS: "Referré des 4 pieds",
};
const LIBELLE_OEILLERES: Record<string, string> = {
  SANS_OEILLERES: "Sans",
  OEILLERES_CLASSIQUE: "Classiques",
  OEILLERES_AUSTRALIENNES: "Australiennes",
};
const libelleEquipement = (v: string | null | undefined, table: Record<string, string>, defaut: string) => {
  if (!v) return defaut;
  const cle = v.toUpperCase();
  return table[cle] ?? cle.replace(/_/g, " ").toLowerCase().replace(/^./, (c) => c.toUpperCase());
};

function PartantDetail({ partant, eloChamp }: { partant: Partant; eloChamp?: { min: number; max: number; moy: number } | null }) {
  const SUBCARD = { borderRadius: 12, border: `1px solid ${CX.bd1}`, background: "#FFFFFF", padding: "12px 14px" } as const;
  // Même graisse d'intitulé que partout ailleurs (bilans, classement) : à 9,5 px
  // les titres de carte se lisaient comme du bruit gris.
  const HEAD_ST = { fontSize: 10.5, fontWeight: 700, textTransform: "uppercase" as const, letterSpacing: ".09em", color: CX.gray400, marginBottom: 9 };
  const Head = ({ children }: { children: React.ReactNode }) => <div style={HEAD_ST}>{children}</div>;
  const label = { fontSize: 11, color: CX.gray400 } as const;
  const val = { color: CX.gray700 } as const;
  const elo = partant.elo_global;
  const eloColor = elo == null ? CX.gray400 : elo >= 1650 ? CX.gold : CX.ink2;
  const mv = partant.mouvement_cote_pct;  // >0 = cote baissée = argent venu = signal +
  const sexeLbl = partant.sexe ? ({ M: "Mâle", H: "Hongre", F: "Femelle" } as Record<string, string>)[partant.sexe] ?? partant.sexe : null;
  const a = partant.analyse;
  const pct = (v: number | null | undefined) => (v == null ? null : Math.round(v * 100));
  const js = a?.jockey_stats, es = a?.entraineur_stats;
  const chipStyle = (type: string) =>
    type === "+" ? { fg: CX.emDeep, bg: CX.emBg, bd: CX.emBd, arrow: "▲" } :
    type === "-" ? { fg: CX.redDeep, bg: CX.redBg, bd: CX.redBd, arrow: "▼" } :
    { fg: CX.gold, bg: CX.goldBg, bd: CX.goldBd, arrow: "●" };
  return (
    <div>
      {/* Points clés (le pourquoi) — chips en tête */}
      {a?.points && a.points.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, margin: "0 0 12px" }}>
          {a.points.map((pt, i) => {
            const cs = chipStyle(pt.type);
            return (
              <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11, fontWeight: 600, borderRadius: 999, padding: "3px 10px", color: cs.fg, background: cs.bg, border: `1px solid ${cs.bd}` }}>
                {cs.arrow} {pt.txt}
              </span>
            );
          })}
        </div>
      )}

      {/* Musique — forme récente */}
      {partant.musique && (
        <div style={{ ...SUBCARD, marginBottom: 10 }}>
          <Head>Musique — forme récente</Head>
          <MusiqueDisplay musique={partant.musique} />
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(178px,1fr))", gap: 10 }}>
      {/* Forme chiffrée */}
      {a && (pct(a.forme.taux_top3) != null || pct(a.forme.recent_win_rate) != null) && (
        <div style={SUBCARD}>
          <Head>Forme</Head>
          {pct(a.forme.taux_top3) != null && (
            <>
              <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
                <span style={label}>Dans les 3</span>
                <span style={{ fontFamily: CX.sg, fontWeight: 700, fontSize: 14, color: CX.ink2 }}>{pct(a.forme.taux_top3)}%</span>
              </div>
              <div style={{ margin: "6px 0 8px", height: 6, borderRadius: 999, background: CX.surf5, overflow: "hidden" }}>
                <div style={{ height: "100%", borderRadius: 999, background: CX.emLight, width: `${Math.min(100, pct(a.forme.taux_top3)!)}%` }} />
              </div>
            </>
          )}
          {pct(a.forme.recent_win_rate) != null && <div style={{ ...label, display: "flex", justifyContent: "space-between" }}><span>Victoires récentes</span><span style={val}>{pct(a.forme.recent_win_rate)}%</span></div>}
          {pct(a.forme.regularite) != null && <div style={{ ...label, display: "flex", justifyContent: "space-between", marginTop: 2 }}><span>Régularité</span><span style={val}>{pct(a.forme.regularite)}%</span></div>}
          {a.forme.tendance != null && Math.abs(a.forme.tendance) > 0.05 && (
            <div style={{ fontSize: 11, fontWeight: 600, color: a.forme.tendance > 0 ? CX.em : CX.red, marginTop: 5 }}>
              {a.forme.tendance > 0 ? "▲ en progression" : "▼ en baisse"}
            </div>
          )}
        </div>
      )}

      {/* Préférences contexte (distance / terrain / hippodrome) */}
      {a && (pct(a.contexte.pref_distance) != null || pct(a.contexte.pref_terrain) != null || pct(a.contexte.pref_hippodrome) != null) && (
        <div style={SUBCARD}>
          <Head>À l&apos;aise sur…</Head>
          {[
            ["Distance", a.contexte.pref_distance, a.contexte.nb_distance],
            ["Terrain", a.contexte.pref_terrain, a.contexte.nb_terrain],
            ["Hippodrome", a.contexte.pref_hippodrome, a.contexte.nb_hippodrome],
          ].map(([lbl, v, nb]) => {
            const p2 = pct(v as number | null);
            if (p2 == null) return null;
            const good = p2 >= 60;
            return (
              <div key={lbl as string} style={{ marginBottom: 6 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11 }}>
                  <span style={{ color: CX.gray400 }}>{lbl as string}</span>
                  {nb != null && (nb as number) > 0 && <span style={{ color: "#C9C2AE", fontSize: 10 }}>{nb as number}c</span>}
                  <span style={{ marginLeft: "auto", fontWeight: 600, fontFamily: CX.sg, color: good ? CX.em : CX.gray700 }}>{p2}%</span>
                </div>
                <div style={{ marginTop: 3, height: 5, borderRadius: 999, background: CX.surf5, overflow: "hidden" }}>
                  <div style={{ height: "100%", borderRadius: 999, background: good ? CX.emLight : "#D1D5DB", width: `${Math.min(100, p2)}%` }} />
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Niveau & forme (ELO) */}
      {(elo != null || partant.age != null || partant.running_style || partant.jours_depuis_derniere != null) && (
        <div style={SUBCARD}>
          <Head>Niveau &amp; forme</Head>
          {elo != null && (
            <>
              <div style={{ display: "flex", alignItems: "baseline", gap: 7 }}>
                <span style={label}>ELO</span>
                <span style={{ fontFamily: CX.sg, fontWeight: 700, fontSize: 20, color: eloColor, lineHeight: 1 }}>{Math.round(elo)}</span>
                {eloChamp && (
                  <span style={{ fontSize: 11, color: elo >= eloChamp.moy ? CX.em : CX.gray400, marginLeft: "auto", fontWeight: 600 }}>
                    {elo >= eloChamp.moy ? "au-dessus" : "en dessous"} du champ
                  </span>
                )}
              </div>
              {/* Un ELO nu ne dit rien : la barre le situe entre le plus faible et
                  le plus fort du lot, et le trait marque la moyenne du champ. */}
              {eloChamp && eloChamp.max > eloChamp.min && (
                <div style={{ position: "relative", marginTop: 7, height: 6, borderRadius: 999, background: CX.surf5, overflow: "visible" }}>
                  <div style={{ height: "100%", borderRadius: 999, background: elo >= eloChamp.moy ? CX.emLight : "#D6D3D1", width: `${Math.max(3, Math.min(100, ((elo - eloChamp.min) / (eloChamp.max - eloChamp.min)) * 100))}%` }} />
                  <span
                    title={`Moyenne du champ : ${Math.round(eloChamp.moy)}`}
                    style={{ position: "absolute", top: -2, bottom: -2, width: 2, borderRadius: 2, background: CX.gray400, left: `${Math.max(0, Math.min(100, ((eloChamp.moy - eloChamp.min) / (eloChamp.max - eloChamp.min)) * 100))}%` }}
                  />
                </div>
              )}
              {eloChamp && (
                <div style={{ fontSize: 10.5, color: CX.gray400, marginTop: 4 }}>
                  champ : {Math.round(eloChamp.min)} → {Math.round(eloChamp.max)} · moyenne {Math.round(eloChamp.moy)}
                </div>
              )}
            </>
          )}
          {a?.elo?.trend_30j != null && Math.abs(a.elo.trend_30j) >= 2 && (
            <div style={{ fontSize: 11, marginTop: 4, fontWeight: 600, color: a.elo.trend_30j > 0 ? CX.em : CX.red }}>
              {a.elo.trend_30j > 0 ? "▲ en hausse" : "▼ en baisse"} <span style={{ fontWeight: 400, color: CX.gray400 }}>30j</span>
            </div>
          )}
          {a?.vitesse?.stamina != null && Math.abs(a.vitesse.stamina) >= 0.25 && (
            <div style={{ fontSize: 11, color: CX.gray400, marginTop: 4 }}>
              {a.vitesse.stamina > 0 ? "Tient bien la distance" : "Plus à l'aise sur la vitesse"}
            </div>
          )}
          <div style={{ fontSize: 11, color: CX.gray400, marginTop: 4 }}>
            {partant.age != null ? `${partant.age} ans` : ""}{sexeLbl ? ` · ${sexeLbl}` : ""}
            {partant.jours_depuis_derniere != null ? ` · ${partant.jours_depuis_derniere}j de repos` : ""}
          </div>
          {partant.running_style && <div style={{ marginTop: 6 }}><RunningStyleBadge style={partant.running_style} /></div>}
        </div>
      )}

      {/* Marché — cote + mouvement + fourchette */}
      {partant.cote_pmu != null && (
        <div style={SUBCARD}>
          <Head>Marché</Head>
          <div style={{ fontFamily: CX.sg, fontWeight: 700, fontSize: 16, color: CX.ink2 }}>
            {partant.cote_pmu.toFixed(1)}
            {mv != null && Math.abs(mv) >= 1 && (
              <span style={{ fontSize: 11, fontWeight: 600, marginLeft: 5, color: mv > 0 ? CX.em : CX.red }}>
                {mv > 0 ? "−" : "+"}{Math.abs(mv).toFixed(0)}% {mv > 0 ? "joué" : "délaissé"}
              </span>
            )}
          </div>
          {partant.cote_min != null && partant.cote_max != null && partant.cote_min !== partant.cote_max && (
            <div style={{ fontSize: 11, color: CX.gray400, marginTop: 4 }}>Fourchette {partant.cote_min.toFixed(1)}–{partant.cote_max.toFixed(1)}{partant.nb_sources ? ` · ${partant.nb_sources} sources` : ""}</div>
          )}
          {/* Comparaison Betfair Exchange (marché efficient) — détecte sur/sous-cote PMU */}
          {partant.cote_betfair_exchange != null && partant.cote_pmu != null && partant.cote_betfair_exchange > 1 && (() => {
            const gap = (partant.cote_pmu! - partant.cote_betfair_exchange!) / partant.cote_betfair_exchange!;
            const valFlag = gap >= 0.08, sev = gap <= -0.08;
            return (
              <div style={{ fontSize: 11, color: CX.gray400, marginTop: 2 }}>
                Betfair {partant.cote_betfair_exchange!.toFixed(1)}
                {(valFlag || sev) && (
                  <span style={{ marginLeft: 4, fontWeight: 600, color: valFlag ? CX.em : CX.red }}>
                    · PMU {gap > 0 ? "+" : "−"}{Math.abs(gap * 100).toFixed(0)}% {valFlag ? "(valeur)" : "(sévère)"}
                  </span>
                )}
              </div>
            );
          })()}
          {/* Signaux marché avancés (argent pro) */}
          {a && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 6 }}>
              {a.marche.spi != null && a.marche.spi >= 0.15 && <span style={{ fontSize: 9.5, fontWeight: 700, borderRadius: 5, padding: "2px 6px", color: CX.gold, background: CX.goldBg }}>SPI {Math.round(a.marche.spi * 100)}% — argent pro</span>}
              {a.marche.valeur_latente != null && a.marche.valeur_latente >= 0.2 && <span style={{ fontSize: 9.5, fontWeight: 700, borderRadius: 5, padding: "2px 6px", color: CX.emDeep, background: CX.emBg }}>Sous-coté (valeur)</span>}
              {a.marche.steam != null && a.marche.steam >= 0.2 && <span style={{ fontSize: 9.5, fontWeight: 700, borderRadius: 5, padding: "2px 6px", color: CX.gold, background: CX.goldBg }}>Steam move</span>}
              {a.marche.decote != null && a.marche.decote >= 0.2 && <span style={{ fontSize: 9.5, fontWeight: 700, borderRadius: 5, padding: "2px 6px", color: CX.gold, background: CX.goldBg }}>Décote détectée</span>}
            </div>
          )}
        </div>
      )}

      {/* Jockey / Entraîneur */}
      <div style={SUBCARD}>
        <Head>Jockey / Entraîneur</Head>
        <div style={{ fontSize: 13, fontWeight: 600, color: CX.ink2 }}>
          {partant.jockey || "—"}
          {partant.changement_jockey && <span style={{ marginLeft: 6, borderRadius: 4, background: CX.goldBg, padding: "1px 5px", fontSize: 9, fontWeight: 700, color: CX.gold, verticalAlign: "middle" }}>CHANGEMENT</span>}
          {partant.jockey_suspendu && <span style={{ marginLeft: 6, borderRadius: 4, background: CX.redBg, padding: "1px 5px", fontSize: 9, fontWeight: 700, color: CX.redDeep, verticalAlign: "middle" }}>SUSPENDU</span>}
        </div>
        <div style={{ fontSize: 11, color: CX.gray400, marginTop: 1 }}>Entraîneur : {partant.entraineur || "—"}{partant.entraineur_suspendu && <span style={{ marginLeft: 4, fontSize: 9, fontWeight: 700, color: CX.red }}>(suspendu)</span>}</div>
        {js && (pct(js.taux_victoire) != null) && (
          <div style={{ fontSize: 11, color: CX.gray600, marginTop: 5 }}>Jockey saison : <b style={{ color: CX.gray700 }}>{pct(js.taux_victoire)}%</b> V · {pct(js.taux_place)}% P{js.victoires_saison != null ? ` · ${js.victoires_saison}/${js.courses_saison}` : ""}{js.roi != null ? ` · ROI ${js.roi >= 0 ? "+" : ""}${Math.round(js.roi * 100)}%` : ""}</div>
        )}
        {es && (pct(es.taux_victoire) != null) && (
          <div style={{ fontSize: 11, color: CX.gray600, marginTop: 2 }}>Entraîneur saison : <b style={{ color: CX.gray700 }}>{pct(es.taux_victoire)}%</b> V{es.roi != null ? ` · ROI ${es.roi >= 0 ? "+" : ""}${Math.round(es.roi * 100)}%` : ""}</div>
        )}
        {partant.asso_jockey_entraineur_taux != null && partant.asso_jockey_entraineur_nb != null && partant.asso_jockey_entraineur_nb >= 3 && (
          <div style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 10.5, fontWeight: 700, color: CX.goldDeep, background: CX.goldBg, border: `1px solid ${CX.goldBd}`, borderRadius: 999, padding: "2px 8px", marginTop: 7 }}>
            <Users className="h-3 w-3" aria-hidden="true" /> Duo gagnant {(partant.asso_jockey_entraineur_taux * 100).toFixed(0)}% sur {partant.asso_jockey_entraineur_nb} courses
          </div>
        )}
      </div>

      {/* Carrière */}
      {partant.nb_courses ? (
        <div style={SUBCARD}>
          <Head>Carrière</Head>
          <div style={{ fontSize: 13, color: CX.ink2 }}>
            <b style={{ fontFamily: CX.sg }}>{partant.nb_victoires ?? 0}</b> victoire{(partant.nb_victoires ?? 0) > 1 ? "s" : ""} <span style={{ color: CX.gray400 }}>sur</span> <b style={{ fontFamily: CX.sg }}>{partant.nb_courses}</b> courses
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
            <div style={{ flex: 1, height: 6, borderRadius: 999, background: CX.surf5, overflow: "hidden" }}>
              <div style={{ height: "100%", borderRadius: 999, background: CX.emLight, width: `${Math.min(100, Math.round((partant.nb_victoires ?? 0) / partant.nb_courses * 100))}%` }} />
            </div>
            <span style={{ fontSize: 11, color: CX.gray400, fontFamily: CX.sg }}>{Math.round((partant.nb_victoires ?? 0) / partant.nb_courses * 100)}%</span>
          </div>
          {/* Le PMU renvoie les gains dans la devise LOCALE de la réunion (pesos à
              San Isidro, HKD à Sha Tin…). Sans devise connue on n'affiche rien :
              mieux vaut pas de chiffre qu'un montant dans une unité inventée. */}
          {partant.gains_carriere != null && partant.gains_carriere > 0 && partant.gains_carriere_devise && (
            <div style={{ fontSize: 11, color: CX.gray400, marginTop: 6 }}>
              Gains carrière : <b style={{ color: CX.gray700 }}>{formatMontantDevise(partant.gains_carriere, partant.gains_carriere_devise)}</b>
            </div>
          )}
        </div>
      ) : null}

      {/* Conditions de course — équipement, poids, corde. Trois demi-cartes
          laissaient des trous dans la grille ; un seul bloc se lit d'un coup. */}
      <div style={SUBCARD}>
        <Head>Conditions de course</Head>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: "7px 12px" }}>
          <div>
            <div style={{ fontSize: 10.5, color: CX.gray400 }}>Déferré</div>
            <div style={{ fontSize: 12.5, fontWeight: 600, color: CX.gray700 }}>
              {libelleEquipement(partant.deferre, LIBELLE_DEFERRE, "Non déferré")}
              {partant.premier_deferre && <span style={{ color: CX.gold, fontSize: 10 }}> · 1ʳᵉ fois</span>}
            </div>
          </div>
          <div>
            <div style={{ fontSize: 10.5, color: CX.gray400 }}>Œillères</div>
            <div style={{ fontSize: 12.5, fontWeight: 600, color: CX.gray700 }}>
              {libelleEquipement(partant.oeilleres, LIBELLE_OEILLERES, "Sans")}
              {partant.premieres_oeilleres && <span style={{ color: CX.gold, fontSize: 10 }}> · 1ʳᵉ fois</span>}
            </div>
          </div>
          {(partant.handicap_poids ?? partant.poids_prevu) != null && (
            <div>
              <div style={{ fontSize: 10.5, color: CX.gray400 }}>Poids</div>
              <div style={{ fontFamily: CX.sg, fontSize: 12.5, fontWeight: 700, color: CX.gray700 }}>
                {partant.handicap_poids ?? partant.poids_prevu} kg
                {partant.poids_reel_pesee != null && (
                  <span style={{ fontFamily: "inherit", fontWeight: 400, fontSize: 10.5, color: CX.gray400 }}> · pesée {partant.poids_reel_pesee}</span>
                )}
              </div>
            </div>
          )}
          {partant.numero_corde != null && (
            <div>
              <div style={{ fontSize: 10.5, color: CX.gray400 }}>Corde</div>
              <div style={{ fontFamily: CX.sg, fontSize: 12.5, fontWeight: 700, color: CX.gray700 }}>{partant.numero_corde}</div>
            </div>
          )}
        </div>
      </div>
      </div>
    </div>
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
    api.get(`/courses/${courseId}/cotes-historique`, { tolere401: true })
      .then((res) => {
        if (!alive) return;
        const map: Record<string, Record<string, number>> = {};
        for (const r of res.data) {
          const t = new Date(r.time).toLocaleTimeString("fr-FR", { timeZone: "Europe/Paris", hour: "2-digit", minute: "2-digit" });
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
      api.get(`/courses/${courseId}/cotes-live`, { tolere401: true })
        .then((res) => {
          if (!alive) return;
          const cotes: Array<{ numero: number; cote: number }> = res.data?.cotes ?? [];
          if (!cotes.length) return;
          const label = new Date(res.data.time).toLocaleTimeString("fr-FR", { timeZone: "Europe/Paris", hour: "2-digit", minute: "2-digit", second: "2-digit",
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
  const colorFor = (delta: number) => (delta < -0.001 ? "#10B981" : delta > 0.001 ? "#EF4444" : "#4B5563");

  return (
    <div style={{ borderRadius: 20, border: `1px solid ${CX.bd1}`, background: CX.surf1, padding: "18px 20px", boxShadow: "0 1px 2px rgba(0,0,0,.03)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
        <TrendingUp className="h-4 w-4" style={{ color: CX.goldAmber }} />
        <h3 style={{ margin: 0, fontFamily: CX.sg, fontSize: 15, fontWeight: 700, color: CX.ink2 }}>Marché des cotes</h3>
        {isLive ? (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 10, fontWeight: 700, color: CX.em, background: CX.emBg, border: `1px solid ${CX.emBd}`, borderRadius: 999, padding: "2px 9px" }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: CX.emLight, animation: "cxDotPulse 1.3s ease-in-out infinite" }} />EN DIRECT
          </span>
        ) : (
          <span style={{ fontSize: 12, color: CX.gray400 }}>— final</span>
        )}
      </div>
      {/* Gradients partagés des aires de sparkline */}
      <svg width="0" height="0" style={{ position: "absolute", pointerEvents: "none" }}><defs>
        <linearGradient id="mkg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#10B981" stopOpacity=".26" /><stop offset="1" stopColor="#10B981" stopOpacity="0" /></linearGradient>
        <linearGradient id="mkr" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#E11D48" stopOpacity=".22" /><stop offset="1" stopColor="#E11D48" stopOpacity="0" /></linearGradient>
        <linearGradient id="mkn" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#4B5563" stopOpacity=".18" /><stop offset="1" stopColor="#4B5563" stopOpacity="0" /></linearGradient>
      </defs></svg>
      {/* Une carte par cheval — graphe individuel d'évolution de la cote */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(158px,1fr))", gap: 10 }}>
        {runners.map((r, idx) => {
          if (!r.hasData) {
            return (
              <div key={r.num} style={{ borderRadius: 14, border: `1px dashed ${CX.bd3}`, background: CX.surf2, padding: "11px 13px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                  <span style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 22, height: 22, borderRadius: 7, background: "#D1D5DB", color: "#FFFFFF", fontFamily: CX.sg, fontWeight: 700, fontSize: 11, flexShrink: 0 }}>{r.num}</span>
                  <span style={{ flex: 1, fontSize: 12.5, fontWeight: 600, color: CX.gray400, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{r.nom}</span>
                </div>
                <div style={{ marginTop: 12, height: 34, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10.5, color: CX.muted }}>
                  Cote non publiée
                </div>
              </div>
            );
          }
          const deltaColor = colorFor(r.delta);
          const up = r.delta > 0.001;
          const flat = Math.abs(r.delta) <= 0.001;
          const fillId = flat ? "mkn" : up ? "mkr" : "mkg";
          const deltaBg = flat ? CX.surf5 : up ? CX.redBg : CX.emBg;
          const isFav = idx === 0;
          // Sparkline sur viewBox 0 0 100 40 (aire dégradée + polyline + point final)
          const mn = Math.min(...r.series), mx = Math.max(...r.series), rng = mx - mn || 1;
          const pts = r.series.map((v, i) => `${(i / (r.series.length - 1)) * 100},${36 - ((v - mn) / rng) * 32}`).join(" ");
          const area = `0,40 ${pts} 100,40`;
          const dotY = 36 - ((r.cur - mn) / rng) * 32;
          return (
            <div key={r.num} className="hover:-translate-y-0.5" style={{ position: "relative", overflow: "hidden", borderRadius: 14, border: `1px solid ${isFav ? CX.goldBd : CX.bd1}`, background: isFav ? "#FFFCF4" : "#FFFFFF", padding: "11px 13px 0", boxShadow: "0 1px 2px rgba(0,0,0,.03)", transition: "transform .18s,box-shadow .18s" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                <span style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 22, height: 22, borderRadius: 7, background: isFav ? CX.gold : CX.ink, color: "#FFFFFF", fontFamily: CX.sg, fontWeight: 700, fontSize: 11, flexShrink: 0 }}>{r.num}</span>
                <span style={{ flex: 1, fontSize: 12.5, fontWeight: 600, color: CX.gray700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{r.nom}</span>
              </div>
              <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginTop: 9 }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 5 }}>
                  <span style={{ fontFamily: CX.sg, fontWeight: 700, fontSize: 23, color: CX.ink2, lineHeight: 1 }}>{r.cur.toFixed(1)}</span>
                  <span style={{ fontSize: 10, color: CX.gray400 }}>cote</span>
                </div>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 2, fontSize: 10.5, fontWeight: 700, color: deltaColor, background: deltaBg, borderRadius: 999, padding: "2px 8px" }}>
                  {flat ? "—" : `${up ? "▲" : "▼"} ${Math.abs(r.delta * 100).toFixed(0)}%`}
                </span>
              </div>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 3, fontSize: 10, color: CX.muted, position: "relative", zIndex: 1 }}>
                <span>Ouv. {r.open.toFixed(1)}</span><span>{r.lo.toFixed(1)}–{r.hi.toFixed(1)}</span>
              </div>
              <svg viewBox="0 0 100 40" preserveAspectRatio="none" style={{ display: "block", width: "100%", height: 34, marginTop: 2 }}>
                <polygon points={area} fill={`url(#${fillId})`} />
                <polyline points={pts} fill="none" stroke={deltaColor} strokeWidth={2} vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round" />
                <circle cx={100} cy={dotY} r={2.6} fill={deltaColor} vectorEffect="non-scaling-stroke" />
              </svg>
            </div>
          );
        })}
      </div>

      <p style={{ margin: "12px 0 0", fontSize: 11, color: CX.gray400, lineHeight: 1.5 }}>
        <span style={{ color: CX.em, fontWeight: 700 }}>▼ vert</span> = cote en baisse (de plus en plus joué) · <span style={{ color: CX.red, fontWeight: 700 }}>▲ rouge</span> = délaissé.
        {isLive && " Cotes PMU rafraîchies toutes les 5 s."}
        {nbSansCote > 0 && ` ${nbSansCote} partant${nbSansCote > 1 ? "s" : ""} sans cote publiée.`}
      </p>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────
/**
 * `initialCourse` vient du composant serveur (page.tsx). Il fait que le PREMIER rendu —
 * celui qui part dans le HTML, donc celui que lit Googlebot — contient déjà le nom de la
 * course, l'hippodrome, les partants et leurs cotes. Auparavant tout arrivait par un
 * useEffect : le robot ne recevait qu'un squelette, et aucune des ~250 fiches course
 * publiées chaque jour ne pouvait ranker.
 */
export default function CoursePage({ initialCourse = null }: { initialCourse?: CourseData | null }) {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const [course, setCourse] = useState<CourseData | null>(initialCourse);
  const [predictions, setPredictions] = useState<Prediction[] | null>(null);
  // Métadonnées du calcul renvoyées par /predictions : sans elles, le tableau met
  // face à face une cote juste calculée à un instant T et une cote de marché d'un
  // autre instant, sans jamais le dire au lecteur.
  const [predMeta, setPredMeta] = useState<{ calcule_a: string | null; cotes_figees: boolean }>(
    { calcule_a: null, cotes_figees: false });
  const [loadingCourse, setLoadingCourse] = useState(!initialCourse);
  const [loadingPred, setLoadingPred] = useState(false);
  const [triggeringPred, setTriggeringPred] = useState(false);
  const [expandedPartant, setExpandedPartant] = useState<string | null>(null);
  const [showGlossaire, setShowGlossaire] = useState(false);
  // Onglet affiché. Null = on suit le statut de la course (résultats si courue,
  // synthèse sinon) ; dès que le visiteur choisit, son choix prime.
  type Onglet = "synthese" | "partants" | "marche" | "plan" | "resultats";
  const [onglet, setOnglet] = useState<Onglet | null>(null);
  useEffect(() => {
    const lire = () => {
      const h = window.location.hash.replace("#", "");
      if (["synthese", "partants", "marche", "plan", "resultats"].includes(h)) setOnglet(h as Onglet);
    };
    lire();
    window.addEventListener("hashchange", lire);
    return () => window.removeEventListener("hashchange", lire);
  }, []);
  const [analysis, setAnalysis] = useState<{
    narrative: string;
    market_signals: Array<{ numero: number; nom: string; signal: string; detail: string; score: number }>;
    field_confidence: number;
    predictions: Array<{ numero: number; explanation: {
      facteurs_positifs: Array<{ label: string; detail: string; score: number }>;
      facteurs_negatifs: Array<{ label: string; detail: string; score: number }>;
      alertes: Array<{ label: string; detail: string }>;
      signaux?: Array<{ label: string; detail: string; sens: "positif" | "negatif" | "neutre"; categorie?: string; score: number }>;
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
    classement: Array<{ numero: number; nom: string; position: number | null; temps: number | null; reduction_km: number | null; incident?: string | null; disqualifie?: boolean }>;
    rapports: Record<string, number> | null;
    rapports_detail: Record<string, Array<{ combinaison: string | null; rapport: number; libelle?: string | null }>> | null;
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
    if (!user) return;   // endpoint réservé : inutile de marteler un 401
    if (!course || !["a_venir", "en_cours"].includes(course.statut)) return;
    let alive = true;
    const poll = () =>
      api.get(`/courses/${id}/cotes-live`, { tolere401: true })
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
    // `course` est recréé à chaque poll de statut (60 s) : le lister relancerait
    // l'intervalle en boucle. Seul `course.statut` change utilement.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, user, course?.statut]);

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

  // Aperçu public : chargé UNIQUEMENT quand la page n'a pas les prédictions
  // (visiteur, plan Découverte, ou course non analysée). Un abonné qui lit déjà
  // le classement complet n'a aucune raison de déclencher cet appel.
  const { data: apercu } = useApercuAnalyse(predictions && predictions.length ? null : id);

  useEffect(() => {
    if (!user || ["free", "decouverte"].includes(user.plan)) return;
    setLoadingPred(true);
    predictionsApi.get(id, 100)
      .then((res) => {
        setPredictions(res.data.predictions);
        setPredMeta({
          calcule_a: res.data.calcule_a ?? null,
          cotes_figees: Boolean(res.data.cotes_figees),
        });
      })
      .catch(() => setPredictions(null))
      .finally(() => setLoadingPred(false));
  }, [id, user]);

  // Load narrative analysis (Standard+) — aussi post-course (facteurs par cheval
  // = transparence "le modèle analyse bien plus que la cote").
  useEffect(() => {
    if (!user || ["free", "decouverte"].includes(user.plan) || !course) return;
    api.get(`/courses/${id}/analyse`, { tolere401: true })
      .then((res) => setAnalysis(res.data))
      .catch(() => {}); // fail silently
    // Deps volontairement SANS l'objet `course` : il est recréé par le poll
    // statut (60 s) → un refetch /analyse par minute, quota 500/j épuisé en
    // une journée d'onglet ouvert → 429 permanent et sections Analyse /
    // Outsiders / signaux vides (constaté 2026-07-03). On ne re-fetch que sur
    // changement d'état de la course ou à l'arrivée des prédictions.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, user, course?.statut, predictions]); // refresh après prédictions

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
          .then((res) => {
            setPredictions(res.data.predictions);
            setPredMeta({
              calcule_a: res.data.calcule_a ?? null,
              cotes_figees: Boolean(res.data.cotes_figees),
            });
          })
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

  const disc = discMask(course.discipline);
  const statutMeta = course.statut === "en_cours"
    ? { label: "En cours", fg: CX.emDeep, bg: CX.emBg, bd: CX.emBd, dot: CX.emLight }
    : course.statut === "termine"
    ? { label: "Terminée", fg: CX.gray500, bg: CX.surf5, bd: CX.bd3, dot: CX.gray400 }
    : { label: "À venir", fg: CX.gold, bg: CX.goldBg, bd: CX.goldBd, dot: "#F59E0B" };

  // Onglets : « Résultats » n'apparaît qu'une fois l'arrivée disponible, et
  // devient l'onglet par défaut — quand la course est courue, c'est ce que le
  // visiteur vient voir.
  const ONGLETS = [
    { cle: "synthese" as const, label: "Synthèse", icone: Sparkles, pastille: null as number | null },
    { cle: "partants" as const, label: "Partants", icone: Users, pastille: course.nb_partants },
    { cle: "marche" as const, label: "Marché", icone: TrendingUp, pastille: null as number | null },
    { cle: "plan" as const, label: "Plan de mise", icone: Calculator, pastille: null as number | null },
    ...(course.statut === "termine"
      ? [{ cle: "resultats" as const, label: "Résultats", icone: Trophy, pastille: null as number | null }]
      : []),
  ];
  const ongletParDefaut = course.statut === "termine" ? "resultats" : "synthese";
  const ongletActif = ONGLETS.some((o) => o.cle === onglet) ? onglet! : ongletParDefaut;


  return (
    <div style={{ minHeight: "100vh", background: CX_PAGE_BG }}>
      <style dangerouslySetInnerHTML={{ __html: CX_STYLE }} />
      <div className="cx-wrap" style={{ maxWidth: 1120, margin: "0 auto", padding: "22px 20px 90px" }}>
      {/* Back */}
      <Link href="/programme" className="inline-flex items-center gap-2 text-sm font-medium mb-4 transition-colors hover:opacity-70" style={{ color: CX.gray500, textDecoration: "none" }}>
        <ArrowLeft className="h-4 w-4" /> Programme
      </Link>

      {/* ── EN-TÊTE DE COURSE ────────────────────────────────────────────────
          Version allégée : identité de la course, état, temps restant, accès au
          direct. Le détail technique (pénétromètre, pluie, dotation, conditions
          officielles) vit dans la fiche technique de l'onglet Synthèse — l'avoir
          en en-tête noyait l'essentiel sous huit pastilles grises. */}
      <header className="cx-fade relative mb-5 overflow-hidden rounded-3xl border border-amber-500/15 bg-gradient-to-b from-[#FFFBF0] to-white p-5 shadow-[0_1px_3px_rgba(0,0,0,.04),0_16px_44px_-26px_rgba(180,83,9,.18)] sm:p-7">
        <span
          aria-hidden="true"
          className="pointer-events-none absolute bottom-4 right-6 hidden h-20 w-40 opacity-[0.09] sm:block"
          style={{
            background: disc.color,
            WebkitMask: `url(${disc.url}) right bottom/contain no-repeat`,
            mask: `url(${disc.url}) right bottom/contain no-repeat`,
          }}
        />

        <div className="relative flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            {/* Identité : réunion/course, label du pari phare, état */}
            <div className="mb-3 flex flex-wrap items-center gap-2">
              {(() => {
                const m = course.course_id.match(/R(\d+)C(\d+)$/);
                const r = course.numero_reunion ?? (m ? Number(m[1]) : null);
                const c = course.numero ?? (m ? Number(m[2]) : null);
                return r && c ? (
                  <span className="rounded-lg bg-slate-900 px-2.5 py-1 font-display text-[13px] font-bold tracking-tight text-white">
                    R{r}<span className="mx-0.5 opacity-45">·</span>C{c}
                  </span>
                ) : null;
              })()}
              {course.est_quinte && (
                <span className="rounded-full border border-amber-300 bg-gradient-to-br from-amber-100 to-amber-200 px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide text-amber-800">Quinté+</span>
              )}
              {course.est_quarte && !course.est_quinte && (
                <span className="rounded-full border border-amber-300 bg-gradient-to-br from-amber-100 to-amber-200 px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide text-amber-800">Quarté+</span>
              )}
              {course.est_tierce && !course.est_quarte && !course.est_quinte && (
                <span className="rounded-full border border-stone-200 bg-stone-100 px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide text-slate-600">Tiercé</span>
              )}
              <span
                className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide"
                style={{ color: statutMeta.fg, background: statutMeta.bg, border: `1px solid ${statutMeta.bd}` }}
              >
                {course.statut !== "termine" && (
                  <span className="h-1.5 w-1.5 rounded-full" style={{ background: statutMeta.dot, animation: "cxDotPulse 1.8s ease-in-out infinite" }} />
                )}
                {statutMeta.label}
              </span>
              <CompteurDepart dateHeure={course.date_heure} statut={course.statut} />
              {course.statut === "a_venir" && course.prono_fige && (
                <span
                  title="À moins de 10 minutes du départ, la sélection est figée : elle ne peut plus changer. Les cotes, elles, continuent de bouger."
                  className="inline-flex cursor-help items-center gap-1.5 rounded-full border border-stone-200 bg-stone-50 px-2.5 py-1 text-[11px] font-semibold text-slate-600"
                >
                  <LockKeyhole className="h-3 w-3" aria-hidden="true" />
                  Pronostic figé
                  {course.prono_fige_a && (
                    <span className="font-normal tabular-nums text-slate-600">
                      à {new Date(course.prono_fige_a).toLocaleTimeString("fr-FR", { timeZone: "Europe/Paris", hour: "2-digit", minute: "2-digit" })}
                    </span>
                  )}
                </span>
              )}
              {wsConnected && (
                <span className="inline-flex items-center gap-1.5 text-[11px] font-bold text-emerald-700">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" style={{ animation: "cxDotPulse 1.4s ease-in-out infinite" }} />
                  Cotes en direct
                </span>
              )}
            </div>

            <h1 className="cx-h1 font-display text-[26px] font-bold leading-[1.1] tracking-tight text-slate-800 sm:text-[30px]">
              {course.nom || `Course ${course.course_id.match(/R\d+C\d+$/)?.[0] ?? course.course_id}`}
            </h1>

            {/* Une seule ligne de contexte : ce qu'on lit avant de parier */}
            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[13.5px] text-slate-600">
              <span className="inline-flex items-center gap-2">
                <span
                  className="inline-block h-[22px] w-[36px]"
                  style={{ background: disc.color, WebkitMask: `url(${disc.url}) center/contain no-repeat`, mask: `url(${disc.url}) center/contain no-repeat` }}
                  aria-hidden="true"
                />
                <span className="font-semibold" style={{ color: disc.color }}>{course.discipline}</span>
              </span>
              <span className="text-stone-300" aria-hidden="true">|</span>
              <span>{course.hippodrome_nom}</span>
              <span className="text-stone-300" aria-hidden="true">|</span>
              <span className="tabular-nums">{course.distance} m</span>
              <span className="text-stone-300" aria-hidden="true">|</span>
              <span className="tabular-nums">{course.nb_partants} partants</span>
              <span className="text-stone-300" aria-hidden="true">|</span>
              <span className="inline-flex items-center gap-1.5">
                <Clock className="h-3.5 w-3.5 text-stone-600" aria-hidden="true" /> {formatDateTime(course.date_heure)}
              </span>
              {course.allocation ? (
                <>
                  <span className="text-stone-300" aria-hidden="true">|</span>
                  <span className="inline-flex items-center gap-1.5">
                    <Trophy className="h-3.5 w-3.5 text-amber-700" aria-hidden="true" />
                    <span className="tabular-nums">{Math.round(course.allocation / 100).toLocaleString("fr-FR")} €</span>
                  </span>
                </>
              ) : null}
            </div>
          </div>

          {/* ── ACCÈS AU DIRECT (Equidia — la vidéo n'est pas chez nous) ── */}
          {(() => {
            const m = course.course_id.match(/R(\d+)C(\d+)$/);
            const r = course.numero_reunion ?? (m ? Number(m[1]) : null);
            const c = course.numero ?? (m ? Number(m[2]) : null);
            const d = course.course_id.slice(0, 8); // course_id = DDMMYYYY + RxCx
            const live = course.statut === "en_cours";
            const iso = /^\d{8}$/.test(d) ? `${d.slice(4, 8)}-${d.slice(2, 4)}-${d.slice(0, 2)}` : null;
            const url = r && c && iso
              ? `https://www.equidia.fr/courses/${iso}/R${r}/C${c}`
              : "https://www.equidia.fr/direct";
            return (
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                title="Regarder la course sur Equidia (ouvre un nouvel onglet)"
                className={cn(
                  "cx-hbtn inline-flex shrink-0 items-center gap-2 rounded-xl px-4 py-2.5 text-[13px] font-semibold transition-colors",
                  live
                    ? "bg-rose-600 text-white hover:bg-rose-700"
                    : "border border-stone-200 bg-white text-slate-700 hover:border-amber-300 hover:text-amber-800",
                )}
              >
                {live && <span className="h-2 w-2 rounded-full bg-white" style={{ animation: "cxDotPulse 1.2s ease-in-out infinite" }} />}
                <Tv className="h-4 w-4" aria-hidden="true" />
                {live ? "Direct" : "Voir la course"}
              </a>
            );
          })()}
        </div>
      </header>

      {/* ── NAVIGATION PAR ONGLETS ─────────────────────────────────────────────
          La fiche porte plus d'information qu'un écran ne peut en absorber :
          80 critères par cheval, le marché, le plan de mise, l'arrivée. Tout
          empiler sur une colonne unique donnait une page qu'on parcourt sans la
          lire. Un sujet par onglet ; le reste est à un clic, pas à trois écrans
          de défilement. */}
      <nav aria-label="Sections de la course" className="cx-tabs sticky top-14 z-20 -mx-5 mb-6 flex gap-1 overflow-x-auto scroll-px-5 border-b border-stone-200/70 bg-[#FFFDF6]/95 px-5 py-2 backdrop-blur [scrollbar-width:none] sm:top-16 [&::-webkit-scrollbar]:hidden">
        {ONGLETS.map((o) => {
          const actif = o.cle === ongletActif;
          return (
            <button
              key={o.cle}
              type="button"
              onClick={() => {
                setOnglet(o.cle);
                // replaceState : changer d'onglet ne doit pas empiler une entrée
                // d'historique par clic, mais l'URL doit rester partageable.
                if (typeof window !== "undefined") window.history.replaceState(null, "", `#${o.cle}`);
              }}
              aria-current={actif ? "page" : undefined}
              className={`relative shrink-0 whitespace-nowrap rounded-lg px-3 py-2 text-[13px] font-semibold transition-colors sm:px-4 sm:text-[13.5px] ${
                actif ? "bg-white text-slate-900 shadow-[0_1px_3px_rgba(0,0,0,.10)]" : "text-slate-600 hover:bg-white/60 hover:text-slate-700"
              }`}
            >
              <span className="inline-flex items-center gap-2">
                <o.icone className={`h-3.5 w-3.5 ${actif ? "text-amber-700" : "text-slate-600"}`} aria-hidden="true" />
                {o.label}
                {o.pastille != null && (
                  <span className={`rounded-full px-1.5 py-px text-[10px] font-bold tabular-nums ${actif ? "bg-amber-100 text-amber-900" : "bg-stone-100 text-slate-600"}`}>
                    {o.pastille}
                  </span>
                )}
              </span>
            </button>
          );
        })}
      </nav>

      <div key={ongletActif} className="cx-fade" style={{ display: "flex", flexDirection: "column", gap: 20 }}>

        {/* ═══ SYNTHÈSE — ce qu'il faut retenir, dans l'ordre de lecture ═══ */}
        {ongletActif === "synthese" && (
          <>
            {(!predictions || predictions.length === 0) && (
              <ApercuAnalyseCard
                apercu={apercu}
                statut={course.statut}
                partants={course.partants}
                nbPartants={course.nb_partants}
                connecte={Boolean(user)}
                abonne={Boolean(user && !["free", "decouverte"].includes(user.plan))}
              />
            )}
            {/* Preuve concrète : ce que le modèle a dit sur les dernières courses
                COURUES. Un prospect ne peut pas juger un pourcentage global ; il
                peut ouvrir six courses réelles et vérifier. Réservé à ceux qui
                n'ont pas déjà le classement — un abonné n'a rien à se prouver. */}
            {(!predictions || predictions.length === 0) && <PreuvesRecentesCard />}
        {/* ── 4 STAT CARDS ── */}
        {predictions && predictions.length > 0 && (() => {
          const fav = predictions.find((p) => p.rang_predit === 1) ?? predictions[0];
          const favCote = liveCoteMap[fav.numero] ?? fav.cote_pmu;
          return (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))", gap: 12, marginBottom: 16 }}>
              {/* Favori algo */}
              <div className="cx-fade" style={{ position: "relative", overflow: "hidden", borderRadius: 18, border: "1px solid rgba(245,158,11,.28)", background: "linear-gradient(135deg,rgba(245,158,11,.09),transparent 70%)", padding: "16px 18px", animationDelay: ".04s" }}>
                <div style={{ fontSize: 10.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".1em", color: CX.gold }}>Favori algo</div>
                <div style={{ fontSize: 14, fontWeight: 700, color: CX.ink2, marginTop: 5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>N°{fav.numero} {fav.nom_cheval}</div>
                <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginTop: 6 }}>
                  <span style={{ fontFamily: CX.sg, fontSize: 27, fontWeight: 700, color: CX.gold, lineHeight: 1 }}>{Math.round(fav.proba_top1 * 100)}%</span>
                  <span style={{ fontSize: 11, color: CX.gray400 }}>victoire{favCote ? ` · cote ${formatCote(favCote)}` : ""}</span>
                </div>
              </div>
              {/* Pari de valeur */}
              <div className="cx-fade" style={{ position: "relative", overflow: "hidden", borderRadius: 18, border: topVB ? "1px solid rgba(16,185,129,.28)" : `1px solid ${CX.bd1}`, background: topVB ? "linear-gradient(135deg,rgba(16,185,129,.09),transparent 70%)" : CX.surf1, padding: "16px 18px", animationDelay: ".08s" }}>
                <div style={{ fontSize: 10.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".1em", color: topVB ? CX.emDeep : CX.gray400 }}>Pari de valeur</div>
                {topVB ? (
                  <>
                    <div style={{ fontSize: 14, fontWeight: 700, color: CX.ink2, marginTop: 5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>N°{topVB.numero} {topVB.nom_cheval}</div>
                    <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginTop: 6 }}>
                      <span style={{ fontFamily: CX.sg, fontSize: 27, fontWeight: 700, color: CX.em, lineHeight: 1 }}>+{Math.round(topVB.value_bet!.ev_max * 100)}%</span>
                      <span style={{ fontSize: 11, color: CX.gray400 }}>espérance · {etoiles(topVB.value_bet!.niveau)}</span>
                    </div>
                  </>
                ) : (
                  <p style={{ marginTop: 8, fontSize: 12, color: CX.gray400 }}>Aucune valeur franche sur cette course.</p>
                )}
              </div>
              {/* Confiance algo */}
              <div className="cx-fade" style={{ borderRadius: 18, border: `1px solid ${CX.bd1}`, background: CX.surf1, padding: "16px 18px", animationDelay: ".12s" }}>
                <div style={{ fontSize: 10.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".1em", color: CX.gray400 }}>Confiance algo</div>
                {confGlobal !== null ? (
                  <>
                    <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginTop: 5 }}>
                      <span style={{ fontFamily: CX.sg, fontSize: 27, fontWeight: 700, color: CX.em, lineHeight: 1 }}>{Math.round(confGlobal)}</span>
                      <span style={{ fontSize: 11, color: CX.gray400 }}>/ 100</span>
                    </div>
                    <div style={{ marginTop: 9, height: 6, borderRadius: 999, background: CX.surf5, overflow: "hidden" }}>
                      <div style={{ height: "100%", width: `${Math.max(0, Math.min(100, Math.round(confGlobal)))}%`, borderRadius: 999, background: "linear-gradient(90deg,#F59E0B,#059669)", transformOrigin: "left", animation: "cxBarGrow .7s cubic-bezier(.16,1,.3,1) .3s both" }} />
                    </div>
                  </>
                ) : <p style={{ marginTop: 8, fontSize: 12, color: CX.gray400 }}>—</p>}
              </div>
              {/* Le champ */}
              <div className="cx-fade" style={{ borderRadius: 18, border: `1px solid ${CX.bd1}`, background: CX.surf1, padding: "16px 18px", animationDelay: ".16s" }}>
                <div style={{ fontSize: 10.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".1em", color: CX.gray400 }}>Le champ</div>
                <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginTop: 5 }}>
                  <span style={{ fontFamily: CX.sg, fontSize: 27, fontWeight: 700, color: CX.ink2, lineHeight: 1 }}>{course.nb_partants}</span>
                  <span style={{ fontSize: 11, color: CX.gray400 }}>partants</span>
                </div>
                <div style={{ fontSize: 11, color: CX.gray400, marginTop: 7 }}>
                  {course.nb_partants >= 14 ? "champ ouvert" : course.nb_partants >= 10 ? "champ moyen" : "petit champ"}
                </div>
              </div>
            </div>
          );
        })()}

        {/* Alerte pari de valeur (bandeau or) */}
        {topVB && (
          <div style={{ display: "flex", alignItems: "center", gap: 9, borderRadius: 14, border: "1px solid rgba(245,158,11,.32)", background: "linear-gradient(135deg,#FFFBF0,#FEF3E2)", padding: "11px 16px", marginBottom: 20, fontSize: 13, color: CX.gray600 }}>
            <Zap className="h-4 w-4 flex-shrink-0" style={{ color: CX.gold }} />
            <span>
              <b style={{ color: CX.goldDeep }}>Pari de valeur exceptionnel</b> — N°{topVB.numero} {topVB.nom_cheval} · {etoiles(topVB.value_bet!.niveau)} · espérance <b style={{ color: CX.em }}>+{Math.round(topVB.value_bet!.ev_max * 100)}%</b> détectée par l&apos;algorithme.
            </span>
          </div>
        )}

          {/* ── Classement de l'algorithme ────────────────────────────────────
              Table extraite dans components/courses/classement.tsx : elle vit
              maintenant en pleine largeur, et chaque colonne correspond à un
              champ réellement renvoyé par l'API (aucune valeur reconstituée). */}
          {/* Visiteur anonyme : c'est le plus gros du trafic (référencement).
              Lui cacher la table, c'est lui demander de payer pour un produit
              qu'il n'a jamais vu — il reçoit donc le même aperçu. */}
          {!user && apercu?.disponible && (
            <ClassementApercu apercu={apercu} connecte={false} onLegende={() => setShowGlossaire(true)} />
          )}

          {user && (["free", "decouverte"].includes(user.plan) ? (
            // Découverte / Free : au lieu d'un cadenas muet, la table réelle avec
            // ses vraies colonnes — probabilités visibles, identités masquées,
            // bas de classement offert. Il faut voir ce qu'on achète.
            apercu?.disponible ? (
              <ClassementApercu apercu={apercu} connecte onLegende={() => setShowGlossaire(true)} />
            ) : (
              <ClassementVerrouille
                titre="Le classement de l'algorithme"
                texte="Probabilité de victoire et de place pour chaque partant, cote juste, signaux retenus contre le cheval comme en sa faveur. Inclus dès la formule Standard."
                action={
                  <Button variant="brand" size="sm" asChild>
                    <Link href="/tarifs">Passer Standard — 12€/mois</Link>
                  </Button>
                }
              />
            )
          ) : loadingPred ? (
            <div className="flex justify-center rounded-2xl border border-stone-200 bg-white py-10">
              <Loader2 className="h-5 w-5 animate-spin text-stone-600" />
            </div>
          ) : !predictions || predictions.length === 0 ? (
            <ClassementVerrouille
              titre={course.statut === "termine" ? "Course non analysée" : "Analyse pas encore lancée"}
              texte={
                course.statut === "termine"
                  ? "Cette course — souvent une réunion étrangère — n'a pas été couverte par le modèle. Nous préférons le dire plutôt que d'afficher un classement vide."
                  : "Le modèle n'a pas encore produit de classement pour cette course."
              }
              action={
                course.statut === "termine" ? null : (
                  <Button variant="brand" size="sm" onClick={handleTriggerPred} disabled={triggeringPred}>
                    {triggeringPred ? <Loader2 className="h-4 w-4 animate-spin" /> : "Lancer l'analyse"}
                  </Button>
                )
              }
            />
          ) : (
            <ClassementAlgo
              predictions={predictions}
              signauxParNumero={(() => {
                // Signaux STRICTEMENT issus de l'analyse : si le backend n'en
                // renvoie pas pour un cheval, la ligne n'en affiche aucun.
                const map: Record<number, ClassementSignal[]> = {};
                for (const ap of analysis?.predictions ?? []) {
                  const sig = ap.explanation?.signaux;
                  if (sig && sig.length) {
                    map[ap.numero] = sig.map((s) => ({
                      label: s.label, detail: s.detail, sens: s.sens, score: s.score,
                    }));
                    continue;
                  }
                  // Repli pour une analyse mise en cache avant l'ajout des signaux :
                  // on reprend facteurs positifs ET négatifs, jamais les seuls positifs.
                  const pos = (ap.explanation?.facteurs_positifs ?? []).map((f) => ({
                    label: f.label, detail: f.detail, sens: "positif" as const, score: f.score,
                  }));
                  const neg = (ap.explanation?.facteurs_negatifs ?? []).map((f) => ({
                    label: f.label, detail: f.detail, sens: "negatif" as const, score: f.score,
                  }));
                  const melange = [...pos, ...neg].sort((a, b) => Math.abs(b.score) - Math.abs(a.score));
                  if (melange.length) map[ap.numero] = melange;
                }
                return map;
              })()}
              positionsReelles={(() => {
                const map: Record<number, number> = {};
                for (const c of resultats?.classement ?? []) {
                  if (c.position != null) map[c.numero] = c.position;
                }
                return map;
              })()}
              coteLive={liveCoteMap}
              nonPartants={new Set(course.partants.filter((p) => p.non_partant).map((p) => p.numero))}
              nonClasses={new Set(
                (resultats?.classement ?? [])
                  .filter((c) => c.position == null)
                  .map((c) => c.numero),
              )}
              calculeA={predMeta.calcule_a}
              cotesFigees={predMeta.cotes_figees}
              onLegende={() => setShowGlossaire(true)}
            />
          ))}

          {/* ── Modale LÉGENDE : explique les signaux sans encombrer la carte ── */}
          {showGlossaire && (
            <div
              className="fixed inset-0 z-[60] flex items-end sm:items-center justify-center p-0 sm:p-4"
              style={{ background: "rgba(17,24,39,.5)", backdropFilter: "blur(3px)", animation: "cxFadeUp .2s ease both" }}
              onClick={() => setShowGlossaire(false)}
            >
              <div
                className="w-full overflow-y-auto rounded-t-2xl sm:rounded-[20px]"
                style={{ maxWidth: 440, maxHeight: "82vh", background: "#FFFFFF", boxShadow: "0 30px 70px -20px rgba(0,0,0,.45)" }}
                onClick={(e) => e.stopPropagation()}
              >
                {/* En-tête collant */}
                <div className="sticky top-0 z-10 flex items-center gap-2 px-4 py-3" style={{ borderBottom: `1px solid ${CX.bd2}`, background: "rgba(255,255,255,.96)", backdropFilter: "blur(6px)" }}>
                  <Brain className="h-4 w-4" style={{ color: CX.gold }} />
                  <h3 style={{ margin: 0, fontFamily: CX.sg, fontSize: 15, fontWeight: 700, color: CX.ink2 }}>Comment lire l&apos;analyse</h3>
                  <button
                    type="button"
                    onClick={() => setShowGlossaire(false)}
                    aria-label="Fermer"
                    className="ml-auto inline-flex items-center justify-center"
                    style={{ width: 28, height: 28, borderRadius: 999, border: "none", background: CX.surf5, color: CX.gray500, cursor: "pointer" }}
                  >
                    <X className="h-[15px] w-[15px]" />
                  </button>
                </div>

                <div className="px-4 py-3 space-y-4 text-[13px] leading-relaxed">
                  {/* Les chiffres */}
                  <section className="space-y-1.5">
                    <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Les chiffres</p>
                    <div className="flex items-baseline gap-2">
                      <span className="text-sm font-bold tabular-nums">54%</span>
                      <span className="text-muted-foreground"><strong className="text-foreground">Gagnant</strong> — probabilité de victoire estimée.</span>
                    </div>
                    <div className="flex items-baseline gap-2">
                      <span className="text-sm font-medium tabular-nums text-muted-foreground">77%</span>
                      <span className="text-muted-foreground"><strong className="text-foreground">Top-3</strong> — probabilité de finir dans les 3 premiers.</span>
                    </div>
                    <div className="flex items-center gap-2 pt-0.5">
                      <span className="h-1 w-10 rounded-full bg-brand-gold flex-shrink-0" />
                      <span className="text-muted-foreground">La barre dorée = niveau de conviction du modèle (sa proba de victoire).</span>
                    </div>
                  </section>

                  {/* Les pastilles */}
                  <section className="space-y-1.5">
                    <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Les pastilles</p>
                    <div className="flex items-start gap-2">
                      <span className="mt-0.5 inline-flex items-center rounded bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200/70 px-1.5 py-0.5 text-[10px] font-medium"><span className="text-[8px] mr-0.5">▲</span> atout</span>
                      <span className="text-muted-foreground">Un point fort en faveur du cheval.</span>
                    </div>
                    <div className="flex items-start gap-2">
                      <span className="mt-0.5 inline-flex items-center rounded bg-rose-50 text-rose-700 ring-1 ring-rose-200/70 px-1.5 py-0.5 text-[10px] font-medium"><span className="text-[8px] mr-0.5">▼</span> réserve</span>
                      <span className="text-muted-foreground">Un point faible qui pèse contre lui.</span>
                    </div>
                    <div className="flex items-start gap-2">
                      <span className="mt-0.5 inline-flex items-center rounded bg-amber-50 text-amber-700 ring-1 ring-amber-200/70 px-1.5 py-0.5 text-[10px] font-medium"><span className="text-[8px] mr-0.5">●</span> à surveiller</span>
                      <span className="text-muted-foreground">Une incertitude à garder en tête (ni bon ni mauvais).</span>
                    </div>
                  </section>

                  {/* Glossaire COMPLET — chaque signal expliqué (indispensable sur mobile,
                      pas de survol). Sections dépliables (<details> natif, zéro lib). */}
                  <section className="space-y-1.5">
                    <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Tous les signaux expliqués</p>
                    {([
                      ["Cote & marché", [
                        ["pos", "Valeur (sous-coté)", "Le modèle lui donne plus de chances que ne le suggère sa cote — cote généreuse."],
                        ["neg", "Coté trop court", "Sa cote surévalue sa vraie chance : on le paierait trop cher."],
                        ["pos", "Afflux de mises", "Le volume de paris sur lui monte fortement — l'argent arrive."],
                        ["pos", "Steam / SPI", "Cote en forte baisse depuis l'ouverture — signe d'argent averti."],
                        ["pos", "Gap PMU/Betfair", "Coté plus généreux au PMU que sur le marché de référence."],
                      ]],
                      ["Forme", [
                        ["pos", "Forme excellente", "Très bonnes performances sur ses 5 dernières courses."],
                        ["neg", "Forme basse", "Résultats récents décevants."],
                        ["pos", "En progression", "Tendance qui monte course après course."],
                        ["neg", "En régression", "Niveau en baisse sur ses dernières sorties."],
                        ["pos", "Fraîcheur idéale", "Temps de repos optimal : revient frais et affûté."],
                        ["amber", "Longue absence", "Beaucoup de jours sans courir — condition à confirmer."],
                        ["amber", "Attention rebond", "Sort d'une course exceptionnelle — risque de contre-performance."],
                      ]],
                      ["Niveau & rivaux", [
                        ["pos", "Supérieur au champ", "Niveau (ELO) au-dessus de la moyenne des concurrents du jour."],
                        ["neg", "Inférieur au champ", "Niveau sous la moyenne des adversaires."],
                        ["pos", "Cote ELO en hausse", "Son niveau progresse nettement ces derniers temps."],
                        ["pos", "Ascendant sur ses rivaux", "A déjà battu en course des concurrents présents aujourd'hui."],
                        ["neg", "Dominé en confrontation", "Souvent battu par des rivaux engagés aujourd'hui."],
                      ]],
                      ["Conditions de course", [
                        ["pos", "Descente de catégorie", "Course moins relevée que d'habitude — adversité plus faible."],
                        ["neg", "Montée de catégorie", "Course plus relevée/dotée qu'à son habitude — adversaires plus forts."],
                        ["pos", "Terrain idéal", "Réussit bien sur ce type de sol."],
                        ["neg", "Terrain défavorable", "Performances faibles sur ce type de sol."],
                        ["pos", "Allègement", "Porte moins de poids que lors de ses dernières sorties."],
                        ["neg", "Surcharge de poids", "Porte plus lourd que d'habitude — handicap réel."],
                        ["pos", "Corde / Position favorable", "Numéro de départ historiquement avantageux ici."],
                        ["neg", "Conflit de rythme", "Plusieurs chevaux de tête : bataille de vitesse probable."],
                        ["neg", "Gros déplacement", "Court très loin de ses hippodromes habituels — voyage exigeant."],
                        ["pos", "Vitesse de référence", "Chronos récents au-dessus du niveau type de la distance."],
                        ["pos", "Pedigree adapté", "La lignée de son père réussit à cette distance / ce terrain."],
                      ]],
                      ["Jockey & écurie", [
                        ["pos", "Jockey en forme", "Jockey avec un bon taux de réussite ces derniers jours."],
                        ["pos", "Écurie en réussite", "Entraîneur en pleine réussite en ce moment."],
                        ["pos", "Duo efficace", "Association jockey × entraîneur performante sur la durée."],
                        ["amber", "Changement de jockey", "Jockey différent de la dernière course — signal ambigu."],
                        ["pos", "Premiers défers / œillères", "Première mise au fer ou changement d'œillères — souvent une amélioration."],
                      ]],
                      ["Décision placé", [
                        ["pos", "Régulier au podium", "Beaucoup de podiums en carrière — valeur sûre pour le placé."],
                        ["pos", "Profil placé", "Bien plus solide au placé qu'au gagnant : à jouer placé/combiné placé."],
                        ["pos", "Valeur sûre placé", "Très haute probabilité de finir dans les 3 — base fiable."],
                      ]],
                      ["Vigilance", [
                        ["amber", "Chances limitées", "Classé loin par le modèle — chance secondaire."],
                        ["amber", "Inédit", "N'a jamais couru — aucune référence, pari à l'aveugle."],
                        ["amber", "Peu d'expérience", "Très peu de courses — marge de progression mais incertitude."],
                      ]],
                    ] as Array<[string, Array<[string, string, string]>]>).map(([fam, items], fi) => (
                      <details key={fam} open={fi === 0} className="group rounded-lg border border-border/60 overflow-hidden">
                        <summary className="flex items-center gap-2 cursor-pointer select-none px-3 py-2 text-[12px] font-medium hover:bg-muted/40 transition-colors list-none">
                          <ChevronRight className="h-3.5 w-3.5 text-muted-foreground transition-transform group-open:rotate-90" />
                          {fam}
                        </summary>
                        <div className="px-3 pb-2.5 pt-0.5 space-y-2 border-t border-border/40">
                          {items.map(([sens, label, def]) => (
                            <div key={label} className="flex gap-2">
                              <span className={cn(
                                "mt-1 text-[8px] leading-none flex-shrink-0",
                                sens === "pos" ? "text-emerald-700" : sens === "neg" ? "text-rose-700" : "text-amber-700",
                              )}>
                                {sens === "pos" ? "▲" : sens === "neg" ? "▼" : "●"}
                              </span>
                              <p className="text-[12px] text-muted-foreground leading-snug">
                                <strong className="text-foreground font-medium">{label}</strong> — {def}
                              </p>
                            </div>
                          ))}
                        </div>
                      </details>
                    ))}
                  </section>

                  <p className="flex items-start gap-1.5 rounded-lg bg-muted/50 px-2.5 py-2 text-[12px] text-muted-foreground">
                    <Info className="h-3.5 w-3.5 mt-0.5 flex-shrink-0 text-brand-gold-dark" />
                    <span>Sur ordinateur, le survol d&apos;une pastille donne aussi le détail chiffré propre à ce cheval. Un signal qui contredirait le classement du modèle n&apos;est jamais affiché.</span>
                  </p>
                  <p className="text-[11px] text-muted-foreground text-center pb-1">
                    Modèle à 80+ critères. Aide à la décision, aucune garantie de gain.
                  </p>
                </div>
              </div>
            </div>
          )}
          {/* Graphique cotes historique */}
          {/* ── Narrative IA (Analyse BlackTurf) ── */}
          {analysis?.narrative && (
            <div style={{ borderRadius: 20, border: `1px solid ${CX.bd1}`, background: CX.surf1, padding: "18px 20px", boxShadow: "0 1px 2px rgba(0,0,0,.03)" }}>
              <div className="flex items-center gap-2" style={{ marginBottom: 12 }}>
                <Brain className="h-[17px] w-[17px]" style={{ color: CX.gold }} />
                <h3 style={{ margin: 0, fontFamily: CX.sg, fontSize: 15, fontWeight: 700, color: CX.ink2 }}>Analyse BlackTurf</h3>
                {analysis.field_confidence > 0 && (
                  <span style={{ marginLeft: "auto", fontSize: 10.5, fontWeight: 700, color: CX.gold, background: CX.goldBg, borderRadius: 999, padding: "2px 9px" }}>
                    Confiance {Math.round(analysis.field_confidence * 100)}%
                  </span>
                )}
              </div>
              {(() => {
                // Présentation structurée : chaque ligne « Label : contenu » devient une
                // entrée avec icône + label coloré. Ligne d'en-tête course (redondante,
                // déjà affichée plus haut) ignorée. Si l'analyse est en prose libre (Claude),
                // repli sur un simple paragraphe.
                const META: Record<string, { Icon: typeof Brain; cls: string }> = {
                  "Lecture": { Icon: Activity, cls: "text-violet-700" },
                  "Favori IA": { Icon: Star, cls: "text-brand-gold-dark" },
                  "Atouts": { Icon: CheckCircle2, cls: "text-emerald-700" },
                  "Également en vue": { Icon: Users, cls: "text-blue-700" },
                  "Outsiders à valeur": { Icon: TrendingUp, cls: "text-emerald-700" },
                  "Conclusion": { Icon: Target, cls: "text-violet-700" },
                  "À surveiller": { Icon: AlertTriangle, cls: "text-amber-700" },
                };
                const lines = analysis.narrative.split("\n").map((l) => l.trim()).filter(Boolean);
                const rows = lines
                  .map((line) => {
                    const m = line.match(/^([^:—]+?)\s*[:—]\s*(.+)$/);
                    if (!m) return null;
                    const label = m[1].trim();
                    const meta = META[label];
                    if (!meta) return null;
                    return { label, rest: m[2].trim(), meta };
                  })
                  .filter(Boolean) as { label: string; rest: string; meta: { Icon: typeof Brain; cls: string } }[];
                if (!rows.length) {
                  return <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">{analysis.narrative}</p>;
                }
                // Résumé : Favori IA + Conclusion visibles d'emblée ; le reste (Lecture,
                // Atouts, Également en vue, Outsiders à valeur, À surveiller) replié —
                // désencombre la carte, texte détaillé toujours accessible en 1 clic.
                const resumeRows = rows.filter((r) => r.label === "Favori IA" || r.label === "Conclusion");
                const detailRows = rows.filter((r) => r.label !== "Favori IA" && r.label !== "Conclusion");
                const Row = ({ label, rest }: { label: string; rest: string }) => {
                  const concl = label === "Conclusion";
                  return (
                    <div className="flex gap-2.5" style={concl ? { marginTop: 4, borderRadius: 12, background: "rgba(245,158,11,.05)", padding: "9px 11px" } : { padding: "1px 0" }}>
                      <span style={{ width: 6, height: 6, borderRadius: "50%", background: CX.goldMuted, marginTop: 8, flexShrink: 0 }} />
                      <p className="text-[13.5px] leading-relaxed" style={{ color: CX.gray600 }}>
                        <span style={{ fontWeight: 700, color: CX.ink2 }}>{label}</span> {rest}
                      </p>
                    </div>
                  );
                };
                return (
                  <div className="flex flex-col" style={{ gap: 10 }}>
                    {resumeRows.map((r, i) => <Row key={i} {...r} />)}
                    {detailRows.length > 0 && (
                      <details className="group">
                        <summary className="select-none flex items-center gap-1.5" style={{ cursor: "pointer", fontSize: 11.5, fontWeight: 600, color: CX.gold, listStyle: "none", padding: "2px 0" }}>
                          Voir l&apos;analyse complète
                          <ChevronDown className="h-3 w-3 transition-transform group-open:rotate-180" />
                        </summary>
                        <div className="flex flex-col" style={{ gap: 10, marginTop: 8 }}>
                          {detailRows.map((r, i) => <Row key={i} {...r} />)}
                        </div>
                      </details>
                    )}
                  </div>
                );
              })()}

              {/* Chevaux à surveiller (signaux marché / argent pro) */}
              {analysis.market_signals?.length > 0 && (
                <div style={{ marginTop: 12, paddingTop: 11, borderTop: `1px solid ${CX.bd2}` }}>
                  <p style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".06em", color: CX.gray400, marginBottom: 7 }}>👁️ Chevaux à surveiller</p>
                  <div className="flex flex-wrap gap-1.5">
                    {analysis.market_signals.map((s, i) => (
                      <span key={i} style={{ fontSize: 11, fontWeight: 600, color: CX.gold, background: CX.goldBg, border: `1px solid ${CX.goldBd}`, borderRadius: 999, padding: "3px 10px" }}>
                        N°{s.numero} {s.nom} — {s.signal}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              <p className="pt-1" style={{ fontSize: 10, color: CX.gray400 }}>
                Les paris à jouer sont dans le plan de mise.
              </p>
            </div>
          )}
          {/* ── Course à outsider (carte or/crème) ── */}
          {analysis?.detection_outsider?.course_a_outsider && (
            <div style={{ borderRadius: 20, border: "1px solid rgba(245,158,11,.22)", background: "linear-gradient(180deg,#FFFBF0,#FFFFFF 60%)", padding: "18px 20px" }}>
              <div className="flex items-center gap-2" style={{ marginBottom: 10 }}>
                <Zap className="h-4 w-4" style={{ color: CX.gold }} />
                <h3 style={{ margin: 0, fontFamily: CX.sg, fontSize: 15, fontWeight: 700, color: CX.goldDeep }}>Course à outsider détectée</h3>
                <span style={{ marginLeft: "auto", fontSize: 10, fontWeight: 700, color: CX.gold, background: CX.goldBg, borderRadius: 999, padding: "2px 9px" }}>
                  Score {Math.round(analysis.detection_outsider.score * 100)}/100
                </span>
              </div>
              {analysis.detection_outsider.signaux.length > 0 && (
                <ul style={{ margin: "0 0 12px", padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 4 }}>
                  {analysis.detection_outsider.signaux.map((s, i) => (
                    <li key={i} style={{ fontSize: 12, color: CX.gray500 }}>· {s}</li>
                  ))}
                </ul>
              )}
              <div className="cx-2col" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                {analysis.detection_outsider.candidats.map((c) => {
                  const hasDetail = !!(c.justification || (c.facteurs_positifs && c.facteurs_positifs.length > 0) || (c.points_vigilance && c.points_vigilance.length > 0));
                  return (
                  <div key={c.numero} style={{ borderRadius: 12, border: `1px solid ${CX.bd1}`, background: "rgba(255,255,255,.75)", padding: "13px 14px" }} className="space-y-1.5">
                    <div className="flex items-center justify-between">
                      <span style={{ fontSize: 13.5, fontWeight: 700, color: CX.ink2 }}>N°{c.numero} {c.nom}</span>
                      <span style={{ fontFamily: CX.sg, fontSize: 12, fontWeight: 700, color: CX.gray500 }}>cote {c.cote}</span>
                    </div>
                    {/* Chiffres clés : valeur modèle vs marché */}
                    <div className="flex flex-wrap gap-1 text-[10px]">
                      <span style={{ fontSize: 10, fontWeight: 600, color: CX.gray500, background: CX.surf5, borderRadius: 5, padding: "2px 7px" }}>
                        Modèle {Math.round(c.proba_modele * 100)}% · Marché {Math.round(c.proba_marche * 100)}%
                      </span>
                      {c.ratio_valeur != null && (
                        <span style={{ fontSize: 10, fontWeight: 700, color: CX.emDeep, background: CX.emBg, borderRadius: 5, padding: "2px 7px" }}>
                          ×{c.ratio_valeur} valeur
                        </span>
                      )}
                      {c.verdict && (
                        <span style={{ fontSize: 10, fontWeight: 600, color: CX.gray500, background: CX.surf5, borderRadius: 5, padding: "2px 7px" }}>{c.verdict}</span>
                      )}
                    </div>
                    {hasDetail && (
                      <details className="group" style={{ marginTop: 2 }}>
                        <summary className="select-none flex items-center gap-1" style={{ cursor: "pointer", fontSize: 10.5, fontWeight: 600, color: CX.gold, listStyle: "none" }}>
                          Voir le détail
                          <ChevronDown className="h-3 w-3 transition-transform group-open:rotate-180" />
                        </summary>
                        <div style={{ marginTop: 6 }} className="space-y-1.5">
                          {c.justification && (
                            <p style={{ margin: 0, fontSize: 11.5, lineHeight: 1.5, color: CX.gray600 }}>{c.justification}</p>
                          )}
                          {/* Facteurs qui appuient le choix */}
                          {c.facteurs_positifs && c.facteurs_positifs.length > 0 && (
                            <ul className="space-y-0.5">
                              {c.facteurs_positifs.slice(0, 4).map((f, i) => (
                                <li key={i} className="text-[10.5px] text-emerald-800 flex gap-1">
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
                                <li key={i} className="text-[10.5px] text-amber-700 flex gap-1">
                                  <span className="flex-shrink-0">⚠</span><span>{v}</span>
                                </li>
                              ))}
                            </ul>
                          )}
                        </div>
                      </details>
                    )}
                  </div>
                  );
                })}
              </div>
              <p style={{ margin: "11px 0 0", fontSize: 10.5, color: CX.muted }}>
                Grosse cote = risque élevé, réservé aux profils offensifs.
              </p>
            </div>
          )}

          {/* Infos course */}
          <div style={{ borderRadius: 20, border: `1px solid ${CX.bd1}`, background: CX.surf1, padding: "18px 20px", boxShadow: "0 1px 2px rgba(0,0,0,.03)" }}>
            <h3 style={{ margin: "0 0 12px", fontFamily: CX.sg, fontSize: 14, fontWeight: 700, color: CX.ink2 }}>Infos course</h3>
            <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
              {(() => {
                const rows: Array<{ label: string; val: string }> = [
                  { label: "Discipline", val: course.discipline },
                  { label: "Distance", val: `${course.distance} m` },
                ];
                const niveau = course.niveau_course?.replace(/_/g, " ").trim();
                const niveauUtile = niveau && !(course.nom && niveau.toUpperCase().includes(course.nom.toUpperCase()));
                if (niveauUtile) rows.push({ label: "Niveau", val: niveau! });
                if (course.terrain_officiel) rows.push({ label: "Terrain", val: course.terrain_officiel });
                if (course.penetrometre_coef != null || course.penetrometre_desc) {
                  const pen = [course.penetrometre_desc, course.penetrometre_coef != null ? `${course.penetrometre_coef}` : null]
                    .filter(Boolean).join(" · ");
                  rows.push({ label: "Pénétromètre", val: pen });
                }
                if (course.meteo?.temperature != null) rows.push({ label: "Température", val: `${course.meteo.temperature.toFixed(1).replace(".", ",")} °C` });
                if (course.meteo?.vent_vitesse != null && course.meteo.vent_vitesse > 0) rows.push({ label: "Vent", val: `${Math.round(course.meteo.vent_vitesse)} km/h` });
                if (course.meteo?.humidite != null) rows.push({ label: "Humidité", val: `${Math.round(course.meteo.humidite)} %` });
                if (course.meteo?.pluie_24h != null && course.meteo.pluie_24h > 0) rows.push({ label: "Pluie 24h", val: `${course.meteo.pluie_24h} mm` });
                if (course.allocation) rows.push({ label: "Dotation", val: `${Math.round(course.allocation / 100).toLocaleString("fr-FR")} €` });
                if (course.categorie_particularite) rows.push({ label: "Départ", val: course.categorie_particularite.replace(/_/g, " ").toLowerCase().replace(/^./, (ch) => ch.toUpperCase()) });
                if (course.pool_total_eur != null && course.pool_total_eur > 0) rows.push({ label: "Masse des enjeux", val: `${course.pool_total_eur.toLocaleString("fr-FR")} €` });
                if (course.pool_gagnant_eur != null && course.pool_gagnant_eur > 0) {
                  const evo = course.pool_gagnant_evolution;
                  rows.push({
                    label: "dont Simple Gagnant",
                    val: `${course.pool_gagnant_eur.toLocaleString("fr-FR")} €${evo != null && Math.abs(evo) >= 1 ? ` (${evo > 0 ? "+" : ""}${Math.round(evo)} %)` : ""}`,
                  });
                }
                if (course.avantage_couloir && course.avantage_couloir !== "neutre") rows.push({ label: "Avantage de couloir", val: course.avantage_couloir.replace(/_/g, " ") });
                if (course.montant_offert_1er != null && course.montant_offert_1er > 0) rows.push({ label: "Au vainqueur", val: `${Math.round(course.montant_offert_1er).toLocaleString("fr-FR")} €` });
                if (course.nombre_declares_partants != null) rows.push({ label: "Déclarés partants", val: String(course.nombre_declares_partants) });
                rows.push({ label: "Heure", val: formatDateTime(course.date_heure) });
                return rows.map((r) => (
                  <div key={r.label} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: 13 }}>
                    <span style={{ color: CX.gray400 }}>{r.label}</span>
                    <span style={{ fontWeight: 600, color: CX.gray700 }}>{r.val}</span>
                  </div>
                ));
              })()}
            </div>
            {course.conditions_texte && (
              <details style={{ marginTop: 14 }}>
                <summary style={{ cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 600, color: CX.gray500 }}>
                  <FileText className="h-3.5 w-3.5" aria-hidden="true" /> Conditions officielles de la course
                </summary>
                <p style={{ margin: "9px 0 0", fontSize: 12.5, lineHeight: 1.55, color: CX.gray500, background: CX.surf3, border: `1px solid ${CX.bd1}`, borderRadius: 12, padding: "10px 12px" }}>
                  {course.conditions_texte}
                </p>
              </details>
            )}
          </div>
          </>
        )}

        {/* ═══ PARTANTS — le champ en détail ═══ */}
        {ongletActif === "partants" && (() => {
          const probaMaxCourse = Math.max(...(predictions ?? []).map((p) => p.proba_top1 || 0), 0.01);
          // Échelle ELO DU LOT : un ELO de 960 ne dit rien dans l'absolu, il dit
          // tout comparé aux autres partants de la même course.
          const elos = course.partants
            .filter((p) => !p.non_partant && p.elo_global != null)
            .map((p) => p.elo_global as number)
            .sort((a, b) => a - b);
          // Bornes de la barre : on écarte l'extrême de chaque bout dès 6 chevaux.
          // Un seul cheval à 2 500 contre un champ à 1 400 tassait tout le monde
          // sur le premier tiers de la jauge.
          const eloChamp = elos.length >= 3
            ? {
                min: elos.length >= 6 ? elos[1] : elos[0],
                max: elos.length >= 6 ? elos[elos.length - 2] : elos[elos.length - 1],
                moy: elos.reduce((a, b) => a + b, 0) / elos.length,
              }
            : null;
          return (
          <>
          {/* Tableau partants */}
          <div style={{ borderRadius: 20, border: `1px solid ${CX.bd1}`, background: CX.surf1, overflow: "hidden", boxShadow: "0 1px 2px rgba(0,0,0,.03)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "15px 18px 12px" }}>
              <h2 style={{ margin: 0, fontFamily: CX.sg, fontSize: 16, fontWeight: 700, color: CX.ink2 }}>Partants</h2>
              <span className="hidden sm:inline" style={{ fontSize: 12, color: CX.gray400 }}>
                — cliquez une ligne pour le détail
              </span>
            </div>
            {/* ── En-tête colonnes (grille design) ── */}
            <div className="cx-prow" style={{ display: "grid", gridTemplateColumns: (predictions && predictions.length > 0 ? "44px 1fr 58px 68px 72px 24px" : "44px 1fr 58px 24px"), gap: 12, alignItems: "center", padding: "0 18px 8px", fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".05em", color: CX.muted }}>
              <span style={{ textAlign: "center" }}>N°</span>
              <span>Cheval</span>
              <span style={{ textAlign: "right" }} title="Cote du marché — live tant que la course n'est pas partie">Cote</span>
              {predictions && predictions.length > 0 && (
                <>
                  <span className="cx-algo" style={{ textAlign: "right" }} title="Cote juste : cote à partir de laquelle le pari devient rentable selon le modèle (1/probabilité)">Cote juste</span>
                  <span style={{ textAlign: "right" }} title="Probabilité de victoire calculée par le modèle ; en dessous, probabilité de finir dans les trois premiers">Victoire</span>
                </>
              )}
              <span />
            </div>
            <div style={{ display: "flex", flexDirection: "column" }}>
              {/* Toutes les barres de probabilité partagent la MÊME échelle (le
                  favori du modèle = barre pleine) : sinon deux lignes de longueur
                  identique porteraient des probabilités différentes. */}
              {[...course.partants]
                // Non-partants conservés mais relégués en bas (indiqués, hors prono).
                .sort((a, b) => Number(!!a.non_partant) - Number(!!b.non_partant))
                .map((partant) => {
                  const pred = predictions?.find((p) => p.participation_id === partant.participation_id);
                  const liveCote = liveCoteMap[partant.numero];
                  const cote = liveCote ?? partant.cote_pmu;
                  const rang = pred?.rang_predit;
                  const coteMoved = !!(liveCote && partant.cote_pmu && liveCote < partant.cote_pmu);
                  const isExp = expandedPartant === partant.participation_id;
                  const np = !!partant.non_partant;
                  // Espérance pour TOUS : cote × proba victoire − 1 (gain moyen pour 1€).
                  const evAll = !pred?.value_bet && pred && cote && cote > 1 && pred.proba_top1 > 0 ? cote * pred.proba_top1 - 1 : null;
                  const reposCol = partant.jours_depuis_derniere == null ? CX.gray400
                    : partant.jours_depuis_derniere >= 14 && partant.jours_depuis_derniere <= 35 ? CX.em
                    : partant.jours_depuis_derniere > 60 ? "#C2410C" : CX.gray400;
                  return (
                    <div key={partant.participation_id} style={{ borderTop: `1px solid ${CX.bd4}`, opacity: np ? 0.55 : 1 }}>
                      <div
                        onClick={() => setExpandedPartant(isExp ? null : partant.participation_id)}
                        className="cx-prow"
                        style={{ display: "grid", gridTemplateColumns: (predictions && predictions.length > 0 ? "44px 1fr 58px 68px 72px 24px" : "44px 1fr 58px 24px"), gap: 12, alignItems: "center", padding: "12px 18px", cursor: "pointer", transition: "background .15s", background: isExp ? CX.surf2 : "transparent" }}
                      >
                        {/* N° + badge rang */}
                        <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
                          {rang != null && rang <= 3 && (
                            <span style={{ fontFamily: CX.sg, fontSize: 10, fontWeight: 800, color: rang === 1 ? CX.gold : CX.gray400, lineHeight: 1, marginBottom: 3 }}>#{rang}</span>
                          )}
                          <span style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 30, height: 30, borderRadius: 9, fontFamily: CX.sg, fontWeight: 700, fontSize: 14, background: rang === 1 ? CX.goldBg : CX.surf3, color: rang === 1 ? CX.goldDeep : CX.gray700, border: `1px solid ${rang === 1 ? CX.goldBd : CX.bd1}` }}>
                            {partant.numero}
                          </span>
                        </div>

                        {/* Cheval : nom + badges + méta */}
                        <div style={{ minWidth: 0 }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                            <span style={{ fontWeight: 700, fontSize: 14.5, color: np ? CX.gray400 : CX.ink2, textDecoration: np ? "line-through" : "none" }}>{partant.nom_cheval}</span>
                            {np && (
                              <span title="Cheval déclaré non-partant — retiré du pronostic" style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", color: "#71717A", background: "#E4E4E7", border: "1px solid #C4C4CC", borderRadius: 5, padding: "1px 5px" }}>Non partant</span>
                            )}
                            {partant.running_style && !np && <RunningStyleBadge style={partant.running_style} />}
                            {partant.changement_jockey && (
                              <span title="Changement de jockey vs dernière course" style={{ display: "inline-flex", alignItems: "center", gap: 2, fontSize: 9, fontWeight: 700, color: "#C2410C", background: "#FFF7ED", border: "1px solid #FED7AA", borderRadius: 5, padding: "1px 5px" }}>⟳ Jockey</span>
                            )}
                            {(partant.jockey_suspendu || partant.entraineur_suspendu) && (
                              <span title={partant.jockey_suspendu ? "Jockey suspendu" : "Entraîneur suspendu"} style={{ fontSize: 9, fontWeight: 700, color: CX.redDeep, background: CX.redBg, border: `1px solid ${CX.redBd}`, borderRadius: 5, padding: "1px 5px" }}>
                                {partant.jockey_suspendu ? "J. susp." : "E. susp."}
                              </span>
                            )}
                            {pred?.value_bet && (
                              <span style={{ display: "inline-flex", alignItems: "center", gap: 3, fontSize: 9, fontWeight: 700, color: CX.emDeep, background: CX.emBg, border: `1px solid ${CX.emBd}`, borderRadius: 999, padding: "1px 7px" }}>
                                ★ +{Math.round(pred.value_bet.ev_max * 100)}%
                              </span>
                            )}
                            {evAll != null && evAll >= 0.05 && (
                              <span style={{ fontSize: 9, fontWeight: 700, color: CX.emDeep, borderRadius: 999, padding: "1px 2px" }}>+{Math.round(evAll * 100)}%</span>
                            )}
                          </div>
                          <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", marginTop: 3, fontSize: 11.5, color: CX.gray400 }}>
                            {partant.jockey && (
                              <span style={{ textDecoration: partant.jockey_suspendu ? "line-through" : "none" }}>{partant.jockey}</span>
                            )}
                            {partant.entraineur && (
                              <span className="cx-hide-m" style={{ color: "#C9C2AE", textDecoration: partant.entraineur_suspendu ? "line-through" : "none" }}>· {partant.entraineur}</span>
                            )}
                            {partant.age != null && <><span style={{ color: "#E5E1D5" }}>·</span><span>{partant.age}a{partant.sexe ? ` ${partant.sexe}` : ""}</span></>}
                            {partant.jours_depuis_derniere != null && (
                              <><span style={{ color: "#E5E1D5" }}>·</span><span style={{ color: reposCol, fontWeight: reposCol === CX.gray400 ? 400 : 600 }}>{partant.jours_depuis_derniere}j repos</span></>
                            )}
                            {partant.premier_deferre && <span style={{ color: CX.gold, fontWeight: 600 }}>· ★ Déferré</span>}
                            {partant.premieres_oeilleres && <span className="cx-hide-m" style={{ color: CX.gold, fontWeight: 600 }}>· ★ Œillères</span>}
                            {partant.asso_jockey_entraineur_taux != null && partant.asso_jockey_entraineur_nb != null && partant.asso_jockey_entraineur_nb >= 5 && (
                              <span className="cx-hide-m" style={{ color: CX.gold, fontWeight: 600 }}>· Duo {(partant.asso_jockey_entraineur_taux * 100).toFixed(0)}%</span>
                            )}
                            {partant.musique && (
                              <><span className="cx-hide-m" style={{ color: "#E5E1D5" }}>·</span><span className="cx-hide-m" style={{ fontFamily: CX.sg, letterSpacing: ".02em", color: CX.muted }}>{partant.musique}</span></>
                            )}
                          </div>
                        </div>

                        {/* Cote */}
                        <div style={{ textAlign: "right" }}>
                          {np ? (
                            <span style={{ fontFamily: CX.sg, fontSize: 12, color: CX.gray400 }}>NP</span>
                          ) : (
                            <span style={{ fontFamily: CX.sg, fontWeight: 700, fontSize: 15, color: coteMoved ? CX.em : CX.ink2 }}>
                              {formatCote(cote)}
                              {liveCote != null && <span style={{ color: CX.em, fontSize: 11 }}> ↓</span>}
                            </span>
                          )}
                        </div>

                        {/* Algo + proba : colonnes masquées tant qu'aucune prédiction
                            n'est chargée — deux colonnes de tirets n'apprennent rien. */}
                        {predictions && predictions.length > 0 && (() => {
                          const cj = pred?.cote_juste ?? null;
                          // Le marché paie-t-il plus (écart en notre faveur) ou moins que
                          // le prix « juste » du modèle ? C'est toute la lecture de la colonne.
                          const ecart = cj && cote && cote > 1 ? (cote - cj) / cj : null;
                          const favorable = ecart != null && ecart >= 0.08;
                          const cher = ecart != null && ecart <= -0.08;
                          return (
                            <div
                              className="cx-algo"
                              style={{ textAlign: "right", fontFamily: CX.sg, fontSize: 12.5, fontWeight: favorable ? 700 : 400, color: favorable ? CX.emDeep : cher ? CX.gray400 : CX.gray600 }}
                              title={
                                cj == null ? undefined
                                : favorable ? `Cote juste ${formatCote(cj)} — le marché paie ${formatCote(cote!)}, soit ${Math.round(ecart! * 100)} % de plus`
                                : cher ? `Cote juste ${formatCote(cj)} — le marché paie moins (${formatCote(cote!)}) : le prix ne couvre pas le risque`
                                : `Cote juste ${formatCote(cj)} — le marché est au prix`
                              }
                            >
                              {cj ? formatCote(cj) : "—"}
                            </div>
                          );
                        })()}

                        {predictions && predictions.length > 0 && (
                        <div style={{ textAlign: "right" }}>
                          {pred ? (
                            <>
                              <div style={{ fontFamily: CX.sg, fontWeight: 700, fontSize: 15, color: rang === 1 ? CX.gold : CX.ink2 }}>
                                {pred.proba_top1 < 0.005 ? "< 1" : (pred.proba_top1 * 100).toFixed(0)}%
                              </div>
                              <div style={{ height: 4, borderRadius: 999, background: CX.surf5, overflow: "hidden", margin: "3px 0 2px" }}>
                                <div style={{ height: "100%", borderRadius: 999, background: rang === 1 ? CX.goldAmber : rang != null && rang <= 3 ? CX.slate : "#D6D3D1", width: `${Math.max(3, Math.min(100, (pred.proba_top1 / Math.max(probaMaxCourse, 0.01)) * 100))}%` }} />
                              </div>
                              <div style={{ fontSize: 10, color: CX.gray400 }} title="Probabilité de finir dans les trois premiers">
                                top-3 {(pred.proba_top3 * 100).toFixed(0)}%
                              </div>
                            </>
                          ) : (
                            <span style={{ color: CX.gray400 }}>—</span>
                          )}
                        </div>
                        )}

                        {/* Chevron */}
                        <ChevronDown style={{ height: 14, width: 14, flexShrink: 0, color: "#D1D5DB", transform: isExp ? "rotate(180deg)" : "none", transition: "transform .2s" }} />
                      </div>

                      {/* Détail déplié */}
                      {isExp && (
                        <div style={{ padding: "2px 18px 16px 18px", background: CX.surf2 }}>
                          <PartantDetail partant={partant} eloChamp={eloChamp} />
                        </div>
                      )}
                    </div>
                  );
                })}
            </div>
          </div>
            <ConfrontationsCard courseId={id} />
          {/* ── Pronostics presse ── */}
          {course.pronostics_presse?.length > 0 && (
            <PronosticsPresse pronostics={course.pronostics_presse} />
          )}
          </>
          );
        })()}

        {/* ═══ MARCHÉ — les cotes, l'argent, les formules jouables ═══ */}
        {ongletActif === "marche" && (
          <>
          {course.statut !== "termine" && (
            <MarcheCotes courseId={id} partants={course.partants} statut={course.statut} />
          )}

          {/* ── Comparaison multi-bookmakers — ouverte : c'est le contenu principal de l'onglet Marché ── */}
          {course.partants.some((p) => p.cote_geny || p.cote_winamax || p.cote_betclic || p.cote_unibet || p.cote_bet365 || p.cote_ladbrokes || p.cote_betfair_exchange) && (
            <details className="group" open style={{ borderRadius: 20, border: `1px solid ${CX.bd1}`, background: CX.surf1, overflow: "hidden" }}>
              <summary className="cursor-pointer select-none" style={{ display: "flex", alignItems: "center", gap: 8, padding: "15px 18px", listStyle: "none" }}>
                <BarChart2 className="h-4 w-4" style={{ color: CX.gray500 }} />
                <h3 style={{ margin: 0, fontFamily: CX.sg, fontSize: 15, fontWeight: 700, color: CX.ink2 }}>Comparaison des cotes</h3>
                <span style={{ fontSize: 11.5, color: CX.gray400 }}>
                  {(() => {
                    // Même logique que ComparaisonCotes : sources avec ≥ 1 cote publiée.
                    const keys = ["cote_pmu", "cote_geny", "cote_winamax", "cote_betclic", "cote_unibet", "cote_bet365", "cote_ladbrokes", "cote_betfair_exchange"] as const;
                    const actifs = course.partants.filter((p) => !p.non_partant);
                    const nb = keys.filter((k) => actifs.some((p) => p[k] != null)).length;
                    return nb;
                  })()} sources · vert = meilleure cote
                </span>
                <ChevronDown className="ml-auto transition-transform group-open:rotate-180 h-4 w-4" style={{ color: CX.gray400 }} />
              </summary>
              <ComparaisonCotes partants={course.partants} />
            </details>
          )}
            <ParisDisponiblesCard courseId={id} />
            <PoolEvolutionCard courseId={id} poolTotalEur={course.pool_total_eur} />
          </>
        )}

        {/* ═══ PLAN DE MISE — pleine largeur, c'est l'outil, pas un encart ═══ */}
        {ongletActif === "plan" && (
          <div className="cx-plan-wide">
          {/* Calculateur de mise — pleine largeur dans son onglet */}
          <div>
          <div style={{ borderRadius: 22, border: `1px solid ${CX.bd3}`, background: CX.surf2, overflow: "hidden", boxShadow: "0 14px 32px -24px rgba(17,24,39,.28)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "20px 22px 16px" }}>
              <span style={{ width: 34, height: 34, borderRadius: 11, display: "inline-flex", alignItems: "center", justifyContent: "center", color: CX.goldDeep, background: CX.goldBg, border: `1px solid ${CX.goldBd}` }}>
                <Calculator className="h-4 w-4" aria-hidden="true" />
              </span>
              <div>
                <h3 style={{ margin: 0, fontFamily: CX.sg, fontSize: 15, fontWeight: 700, color: CX.ink2 }}>Votre plan de mise</h3>
                <p style={{ margin: "2px 0 0", fontSize: 10.5, color: CX.gray500 }}>Plan personnalisé pour cette course</p>
              </div>
            </div>
            <div style={{ padding: "0 22px 22px" }}>
              <MiseCalculatorWidget
                courseId={id}
                userPlan={user?.plan}
                profil={profil}
                predictions={predictions}
                statut={course.statut}
              />
            </div>
          </div>
          </div>
          </div>
        )}

        {/* ═══ RÉSULTATS ═══ */}
        {ongletActif === "resultats" && (
          <>
                {resultats && (
                  <ResultatsSection resultats={resultats} partants={course.partants} />
                )}
                {resultats && predictions && predictions.length > 0 && (
                  <PronosticVerdictSection predictions={predictions} classement={resultats.classement} />
                )}
                {/* Le teaser « favori de l'IA » (funnel Free, 16/08) a été retiré le
                    20/08 : le bilan du plan ci-dessous, désormais visible par tous,
                    dit la même chose en mieux (3 profils, paris réels, rapports PMU)
                    et portait un second CTA redondant. */}
                {/* Bilan du plan — montré À TOUS, y compris visiteur anonyme et
                    plan Découverte (décision 2026-08-19) : la course est terminée,
                    donc aucun pronostic exploitable n'est révélé, et c'est la seule
                    façon pour un non-abonné de voir ce que les plans de mise du site
                    auraient donné. La condition portait sur `predictions`, jamais
                    chargées pour ces plans → le bloc leur était invisible. Le
                    composant s'auto-masque si le bilan n'est pas disponible. */}
                <BilanMiseSection
                  courseId={id}
                  paywall={!user || ["free", "decouverte"].includes(user.plan)}
                />
                {!resultats && (
                  <div style={{ borderRadius: 20, border: `1px solid ${CX.bd1}`, background: CX.surf1, padding: "24px 20px", textAlign: "center", color: CX.gray500, fontSize: 13 }}>
                    <Loader2 className="h-5 w-5 animate-spin mx-auto mb-2" style={{ color: CX.gray400 }} />
                    Arrivée officielle en cours de publication…
                  </div>
                )}
            {resultats && <TempsPassageCard courseId={id} />}
          </>
        )}
      </div>

      </div>
    </div>
  );
}
