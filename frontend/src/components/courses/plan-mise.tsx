"use client";

/**
 * Plan de mise d'une course : affichage du plan calculé par le moteur
 * (profils, niveaux Sécurité / Rendement / Coup, tickets). Partagé entre la
 * page course et l'accueil, qui le montre tel quel sur un exemple.
 */

import {
  AlertTriangle, ChevronDown, Flame, Gauge, Info, Loader2,
  LockKeyhole, Medal, Pencil, Radio, ShieldCheck, TrendingUp, WalletCards, Zap,
} from "lucide-react";
import { CasaqueNumero } from "@/components/courses/identite-cheval";
import { ModuleQuinte, type ModuleQuinteData } from "@/components/courses/ModuleQuinte";
import { typeDefi } from "@/components/defi/kit";
import type { DefiTypePari } from "@/lib/api";

/** Cheval d'un pari du plan.
 *  `cote` est le prix que le MOTEUR a utilisé pour construire le pari (cote figée au
 *  gel du pronostic) ; `cote_live` est le prix du marché au moment de l'affichage.
 *  Les deux peuvent différer beaucoup — dérive médiane mesurée à 30 % entre le gel et
 *  le départ — et c'est exactement ce qui rendait le plan illisible en face de
 *  l'onglet « Synthèse », qui affiche le prix live. On montre donc les DEUX. */
export interface ChevalPari {
  numero: number;
  nom: string;
  cote?: number;        // prix utilisé par le moteur
  cote_live?: number;   // prix du marché maintenant
  rang?: number;        // place au classement de l'IA
  /** Value bet détecté par l'autre outil du site sur ce cheval. Affiché seulement :
   *  il n'entre dans aucune décision du moteur de mise. */
  value_bet?: { ev_max?: number; niveau?: number } | null;
}

export interface PariRec {
  type: string;
  chevaux: ChevalPari[];
  mise: number;
  gain_potentiel: number;
  probabilite: number;
  description: string;
  raisons?: string[];          // justification complète du pari (backend)
  rapport_estime?: number;     // multiplicateur retenu au gel (gain = mise × rapport)
  rapport_live?: number;       // multiplicateur aux cotes du marché maintenant
  rapport_a_bouge?: boolean;   // écart ≥ 15 % entre les deux
  hors_tranche_live?: boolean; // le marché a fait sortir le ticket de la tranche du profil
  hors_tranche?: boolean;      // ticket de secours servi HORS de la tranche du profil (filet)
}

export interface PariEcarte {
  type: string;
  chevaux: ChevalPari[];
  probabilite: number;
  ev_estime: number;
  rapport_estime?: number;
  motif: string;
}

/** Raccord classement → plan pour les premiers du classement de l'IA : joué ou non,
 *  et si non, pourquoi. Répond à « l'IA le met 1er et le plan ne le joue pas ». */
export interface CouvertureClassement {
  numero: number;
  nom: string;
  rang: number;
  joue: boolean;
  paris?: string[];
  motif?: string;
  value_bet?: { ev_max?: number; niveau?: number } | null;
  meilleur_pari_possible?: {
    type: string;
    chevaux: ChevalPari[];
    rapport_estime?: number;
    probabilite?: number;
  };
}

export interface NiveauPlan {
  niveau: string;
  label: string;
  emoji: string;
  couleur: string;
  montant: number;
  pct: number;
  paris: PariRec[];
}

export interface MisePlan {
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
  classement?: CouvertureClassement[];  // ce que le plan fait du haut du classement
  marche_a_bouge?: boolean;             // au moins un ticket re-tarifé de ≥ 15 %
  paris_hors_tranche_live?: number;     // tickets sortis de la tranche du profil
  prono_fige?: boolean;           // sélection figée (T-10) — paris/chevaux/mises immuables
  gains_live_post_gel?: boolean;  // gains ré-évalués sur cotes live MÊME après le gel
  roi_observe?: { roi: number; nb: number; jours: number };  // ROI RÉEL récent du profil (honnêteté vs espérance théorique)
  module_quinte?: ModuleQuinteData | null; montant_quinte?: number;  // Quinté+ pris SUR le montant
}


/** Montants et cotes en écriture française : « 12,50 € », « 4,4 ». */
const eur2 = (v: number) => v.toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const cote1 = (v: number) => v.toLocaleString("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

// Profils de mise (source unique : formulaire + switch rapide dans le plan).
export const PROFILS_MISE = [
  // `bande` = tranche de gain visée SUR LA MISE TOTALE. Ce sont les bornes réelles
  // du moteur (backend/services/mise_calculator.py : gain_cible_mult / rapport_max),
  // pas un argument commercial : les afficher évite de choisir un profil à l'aveugle,
  // et elles doivent bouger en même temps que le backend.
  { key: "conservateur", label: "Prudent", bande: "×1,8 à ×5", desc: "Favorise la régularité et limite l’exposition." },
  { key: "equilibre", label: "Modéré", bande: "×4 à ×15", desc: "Équilibre la régularité et le rendement." },
  { key: "agressif", label: "Risqué", bande: "≥ ×10", desc: "Accepte plus de variance pour viser plus haut." },
] as const;


// ─── Palette du reskin (tokens du design handoff) ─────────────────────────────
// Palette restreinte 4 familles. Or / Émeraude / Rose / Neutres chauds.
export const CX = {
  // Or
  gold: "#B45309", goldDeep: "#92400E", goldMuted: "#C99A3C", goldAmber: "#D97706",
  goldGrad: "linear-gradient(135deg,#F59E0B,#D97706)", goldBg: "#FEF6E7", goldBd: "#F5DCA8", goldBd2: "#FCD34D",
  // Émeraude
  em: "#059669", emDeep: "#047857", emLight: "#10B981", emBg: "#ECFDF5", emBd: "#A7F3D0",
  // Rose (négatif)
  red: "#E11D48", redDeep: "#B91C1C", redBg: "#FEF2F2", redBd: "#FECACA",
  // Neutres chauds
  ink: "#111827", ink2: "#1F2937", gray700: "#374151", gray600: "#4B5563",
  gray500: "#4B5563", gray400: "#4B5563", muted: "#B0A88F",
  surf1: "#FFFFFF", surf2: "#FAF7EF", surf3: "#F7F4EC", surf4: "#F3F1EA", surf5: "#F1EEE6",
  bd1: "#ECE7DC", bd2: "#EEE9DE", bd3: "#E7E1D3", bd4: "#F3EFE6",
  slate: "#475569",
  sg: "var(--font-space-grotesk), sans-serif",
} as const;

export function PlanMiseDisplay({ plan, profil, switching, onChangeProfil, onClose, onJouerDefi }: {
  plan: MisePlan;
  profil: string;
  switching: boolean;
  onChangeProfil: (profil: string) => void;
  onClose: () => void;
  /** Envoie un ticket vers le Défi du mois (types du défi seulement). */
  onJouerDefi?: (type: DefiTypePari, chevaux: number[]) => void;
}) {
  const profilDesc = PROFILS_MISE.find((p) => p.key === profil)?.desc;
  // Teinte par niveau : Sécurité=émeraude, Rendement=or, Coup à tenter=rose.
  const nivStyle = (niveau: string) =>
    niveau === "securite" ? { bg: CX.emBg, bd: CX.emBd, color: CX.emDeep } :
    niveau === "rendement" ? { bg: CX.goldBg, bd: CX.goldBd, color: CX.goldDeep } :
    { bg: CX.redBg, bd: CX.redBd, color: CX.redDeep };
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

      {/* Header résumé — argent SEULEMENT : ce qui est disponible, ce qui part réellement
          en jeu, ce qui reste. Aucune projection de rendement (ni théorique, ni observée) :
          un « +/−x % » à côté du budget se lisait comme une promesse de gain et brouillait
          la seule question utile ici — combien je mise et sur quoi. Le rendement réel du
          service reste public et chiffré sur /track-record. */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr auto 1fr", alignItems: "start", gap: 14, borderRadius: 14, border: `1px solid ${CX.bd2}`, background: CX.surf1, padding: "14px 16px", marginBottom: 14 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 6, height: 14, marginBottom: 6, fontSize: 10.5, fontWeight: 600, color: CX.gray500 }}>
            <WalletCards className="h-3.5 w-3.5" aria-hidden="true" /> Budget
          </div>
          <div style={{ fontFamily: CX.sg, fontSize: 25, fontWeight: 700, color: CX.ink, lineHeight: 1, fontVariantNumeric: "tabular-nums" }}>{plan.montant_total}€</div>
        </div>
        <div aria-hidden="true" style={{ width: 1, height: 38, marginTop: 2, background: CX.bd3 }} />
        <div style={{ textAlign: "right" }}>
          <div style={{ height: 14, marginBottom: 6, fontSize: 10.5, fontWeight: 600, color: CX.gray500 }}>Total misé</div>
          <div style={{ fontFamily: CX.sg, fontSize: 25, fontWeight: 700, color: CX.ink, lineHeight: 1, fontVariantNumeric: "tabular-nums" }}>{eur2((plan.montant_joue + (plan.montant_quinte ?? 0)))} €</div>
          {plan.montant_reserve > 0 && (
            <div style={{ marginTop: 5, fontSize: 10.5, color: CX.gray500, fontVariantNumeric: "tabular-nums" }}>{eur2(plan.montant_reserve)} € gardés de côté</div>
          )}
        </div>
      </div>

      {/* Résumé IA */}
      <details style={{ borderRadius: 12, border: `1px solid ${CX.bd2}`, background: CX.surf2, marginBottom: 16 }}>
        <summary className="select-none" style={{ minHeight: 44, cursor: "pointer", padding: "0 12px", listStyle: "none", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, fontSize: 11.5, fontWeight: 650, color: CX.gray600 }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 7 }}><Info className="h-3.5 w-3.5" aria-hidden="true" /> Lecture de l&apos;algorithme</span>
          <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
        </summary>
        <p style={{ margin: 0, padding: "0 12px 12px 32px", fontSize: 11.5, lineHeight: 1.55, color: CX.gray600 }}>{plan.resume_ia}</p>
      </details>

      {/* Le bandeau d'alerte « Le marché a bougé depuis le calcul du plan » a été retiré :
          il ouvrait le plan sur un avertissement rouge que le lecteur ne pouvait pas
          exploiter (la sélection est figée, il n'y a rien à faire). Le mouvement des cotes
          reste visible là où il sert : sur le ticket concerné, ligne « joué à … / cote
          actuelle … », et la mention de bas de plan rappelle que les gains suivent le
          marché jusqu'au départ. */}

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
                {eur2(niv.montant)} €
              </span>
            </div>
            <div style={{ display: "flex", flexDirection: "column" }}>
              {niv.paris.map((p, i) => (
                <div key={i} style={{ padding: "13px 14px", borderTop: i ? `1px solid ${CX.bd4}` : "none" }}>
                  <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) auto", alignItems: "start", gap: 12 }}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 12.5, fontWeight: 700, color: CX.ink2 }}>{p.type}</div>
                      <div style={{ marginTop: 4, display: "flex", flexWrap: "wrap", alignItems: "center", gap: 4, fontFamily: CX.sg, fontSize: 15, fontWeight: 650, color: CX.ink }}>{p.chevaux.map((c, i) => <span key={c.numero} className="inline-flex items-center gap-1">{i > 0 && "+"}<CasaqueNumero numero={c.numero} /></span>)}</div>
                      {/* Prix utilisé par le moteur vs prix du marché — affiché
                          UNIQUEMENT quand les deux divergent. Le reste du temps la ligne
                          n'apprendrait rien et alourdirait la page ; quand ils divergent,
                          la taire revient à laisser deux cotes se contredire d'un onglet
                          à l'autre sans explication. La casaque est déjà sur la ligne du
                          dessus : ici le numéro seul, une ligne par cheval, texte qui peut
                          passer à la ligne (sur mobile le `nowrap` + casaque débordait). */}
                      {p.chevaux.some(c => c.cote != null && c.cote_live != null
                        && Math.abs(c.cote_live / c.cote - 1) >= 0.1) && (
                        <div style={{ marginTop: 5, display: "flex", flexDirection: "column", gap: 2 }}>
                          {p.chevaux.map((c) => (
                            c.cote != null && c.cote_live != null
                              && Math.abs(c.cote_live / c.cote - 1) >= 0.1 ? (
                              <span key={c.numero} style={{ fontSize: 10.5, lineHeight: 1.4, color: CX.gray500, fontVariantNumeric: "tabular-nums", overflowWrap: "anywhere" }}>
                                <span style={{ fontWeight: 700, color: CX.ink2 }}>n°{c.numero}</span>
                                {" "}joué à {cote1(c.cote)} · cote actuelle {cote1(c.cote_live)}
                              </span>
                            ) : null
                          ))}
                        </div>
                      )}
                      <div style={{ marginTop: 3, fontSize: 10.5, color: CX.gray500 }}>Probabilité estimée {(p.probabilite * 100).toFixed(0)}%</div>
                      {/* Ticket servi hors de la tranche du profil : le filet « chaque course
                          est jouée » n'a rien trouvé dans la bande de gain. Le dire SUR le
                          ticket, pas seulement dans la note de bas de plan — sinon la promesse
                          « ≥ ×10 » affichée en tête du profil paraît trahie sans explication. */}
                      {p.hors_tranche && (
                        <div style={{ marginTop: 5, display: "inline-flex", alignItems: "center", gap: 4, borderRadius: 6, border: `1px solid ${CX.goldBd}`, background: CX.goldBg, padding: "2px 7px", fontSize: 10, fontWeight: 650, color: CX.goldDeep }}>
                          Hors tranche du profil — seul pari jouable ici
                        </div>
                      )}
                    </div>
                    <div style={{ textAlign: "right", flexShrink: 0 }}>
                      <div style={{ fontSize: 10, fontWeight: 600, color: CX.gray500 }}>Mise</div>
                      <div style={{ marginTop: 2, fontFamily: CX.sg, fontSize: 15, fontWeight: 700, color: CX.ink2, fontVariantNumeric: "tabular-nums" }}>{eur2(p.mise)} €</div>
                      {/* Un seul chiffre de gain par ticket : ce que ce pari rapporte s'il
                          passe. Le multiplicateur re-tarifé (×10 → ×4) doublait la ligne
                          sans rien apprendre de plus. */}
                      <div style={{ marginTop: 6, fontSize: 10, fontWeight: 600, color: CX.gray500 }}>Si gagnant</div>
                      <div style={{ marginTop: 2, fontFamily: CX.sg, fontSize: 15, fontWeight: 700, color: CX.emDeep, fontVariantNumeric: "tabular-nums" }}>~{p.gain_potentiel.toFixed(0)}€</div>
                    </div>
                  </div>
                  {onJouerDefi && typeDefi(p.type) && (
                    <button
                      type="button"
                      onClick={() => onJouerDefi(typeDefi(p.type) as DefiTypePari, p.chevaux.map((c) => c.numero))}
                      style={{ marginTop: 8, minHeight: 32, display: "inline-flex", alignItems: "center", gap: 5, borderRadius: 8, border: `1px solid ${CX.goldBd}`, background: CX.goldBg, padding: "4px 10px", fontSize: 11, fontWeight: 650, color: CX.goldDeep, cursor: "pointer" }}
                    >
                      <Medal className="h-3.5 w-3.5" aria-hidden="true" /> Jouer ce pari au Défi du mois
                    </button>
                  )}
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
        {plan.module_quinte && <ModuleQuinte module={plan.module_quinte} montantTotal={plan.montant_total} />}
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

      {/* Le pavé « Total joué / Gain projeté » a été retiré : le total est remonté dans
          l'en-tête (« Total misé ») et le « gain projeté » — une espérance nette, donc
          presque toujours un montant NÉGATIF de quelques centimes — se lisait comme une
          perte annoncée sur un plan qu'on demande à l'utilisateur de jouer. */}

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
                    {e.type}{" "}
                    <span style={{ fontWeight: 400, color: CX.gray400 }}>
                      {e.chevaux.map(c => `N°${c.numero}${c.rang != null ? ` (${c.rang}${c.rang === 1 ? "er" : "e"} IA)` : ""}`).join(" + ")}
                    </span>
                  </span>
                  <span style={{ color: CX.gray400, fontFamily: CX.sg, flexShrink: 0 }}>
                    {e.rapport_estime ? `×${cote1(e.rapport_estime)} · ` : ""}{(e.probabilite * 100).toFixed(0)}%
                  </span>
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

      {/* Plus d'enregistrement dans un « capital » : les paris qu'on veut suivre
          se jouent au Défi du mois, en points, ticket par ticket (bouton de chaque
          ticket). Le plan, lui, reste en euros : c'est l'estimation de ce que
          donneraient ces mises jouées pour de vrai chez un opérateur. */}
      {onJouerDefi && (
        <div style={{ marginTop: 12, display: "flex", alignItems: "flex-start", gap: 8, borderRadius: 12, border: `1px solid ${CX.goldBd}`, background: CX.goldBg, padding: "10px 12px", fontSize: 11.5, lineHeight: 1.45, color: CX.goldDeep }}>
          <Medal className="h-4 w-4 flex-shrink-0" style={{ marginTop: 1 }} aria-hidden="true" />
          <span>Jouez ces tickets au <b>Défi du mois</b> avec vos points : bouton « Jouer ce pari au Défi du mois » sous chaque ticket.</span>
        </div>
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
