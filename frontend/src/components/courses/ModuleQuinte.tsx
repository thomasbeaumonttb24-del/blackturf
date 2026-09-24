"use client";

import { ChevronDown, Info, Trophy } from "lucide-react";
import { IdentiteCheval } from "@/components/courses/identite-cheval";

/** Module Quinté+ du plan de mise (backend : `mise_calculator._construire_module_quinte`).
 *
 *  Son coût est PRIS SUR le montant du plan (arbitrage du 2026-09-24) : plan principal
 *  + Quinté+ = le montant saisi. Un Quinté+ joué à chaque course Quinté+ est une
 *  couverture de divertissement — aucune espérance positive n'est établie, et le
 *  composant ne doit jamais en suggérer une (pas d'EV, pas de « value »). */
export interface ModuleQuinteData {
  disponible: boolean;
  financable?: boolean | null;
  motif?: string;
  profil?: string;
  type_pari?: string;
  couverture?: string;             // « tendue » | « champ 6 chevaux » | « champ 7 chevaux »
  couverture_visee?: string;
  couverture_reduite?: boolean;
  motif_couverture?: string | null;
  nb_chevaux?: number;
  chevaux?: { numero: number; nom: string; cote?: number; rang?: number | null }[];
  nb_combinaisons?: number;
  flexi_pct?: number;
  mise_unitaire?: number;          // mise par combinaison (mise de base × Flexi)
  cout_total: number;
  montant_saisi?: number;
  montant_plan_principal?: number;
  montant_minimum?: number;
  cout_minimum?: number;
  proba_gain?: number | null;      // les 5 premiers dans la sélection
  proba_bonus?: number | null;     // retour partiel (Bonus) sans les 5
  rapport_estime?: number;
  rapport_fourchette?: { bas: number; median: number; haut: number } | null;
  gain_potentiel?: number;
  gain_fourchette?: { bas: number; haut: number } | null;
  note?: string;
}

// Mêmes jetons que le plan de mise (CourseClient) : neutres chauds + ardoise, pour
// distinguer ce bloc des niveaux Sécurité / Rendement / Coup sans le faire passer
// pour un pari « à valeur ».
const CX = {
  ink: "#111827", ink2: "#1F2937", gray600: "#4B5563", gray500: "#4B5563",
  slate: "#475569", slateBg: "#F1F5F9", slateBd: "#CBD5E1",
  emDeep: "#047857", goldDeep: "#92400E", goldBg: "#FEF6E7", goldBd: "#F5DCA8",
  surf1: "#FFFFFF", surf2: "#FAF7EF", surf3: "#F7F4EC", bd2: "#EEE9DE", bd4: "#F3EFE6",
  sg: "var(--font-space-grotesk), sans-serif",
} as const;

const pct = (p: number) => {
  const v = p * 100;
  return `${v < 1 ? v.toFixed(2) : v.toFixed(1)} %`;
};
const eur = (v: number) => `${v.toFixed(2)}€`;
const eurRond = (v: number) => `${v >= 100 ? Math.round(v) : v.toFixed(0)}€`;

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div style={{ minWidth: 0, borderRadius: 10, background: CX.surf3, padding: "8px 10px" }}>
      <div style={{ fontSize: 10, fontWeight: 600, color: CX.gray500 }}>{label}</div>
      <div style={{ marginTop: 2, fontFamily: CX.sg, fontSize: 14, fontWeight: 700, color: CX.ink2, fontVariantNumeric: "tabular-nums" }}>{value}</div>
      {sub && <div style={{ marginTop: 1, fontSize: 10, color: CX.gray500, lineHeight: 1.35 }}>{sub}</div>}
    </div>
  );
}

export function ModuleQuinte({ module, montantTotal }: { module: ModuleQuinteData; montantTotal: number }) {
  const titre = (
    <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
      <span style={{ width: 28, height: 28, borderRadius: 9, display: "inline-flex", alignItems: "center", justifyContent: "center", flexShrink: 0, color: CX.slate, background: "rgba(255,255,255,.75)", border: "1px solid rgba(255,255,255,.9)" }}>
        <Trophy className="h-4 w-4" aria-hidden="true" />
      </span>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontWeight: 700, fontSize: 12.5, color: CX.ink2 }}>
          Quinté+{module.disponible && module.couverture ? ` · ${module.couverture}` : ""}
        </div>
        <div style={{ fontSize: 10.5, color: CX.gray500 }}>
          {module.disponible
            ? `${Math.round((module.cout_total / (montantTotal || 1)) * 100)}% du budget · pris sur le montant`
            : module.financable === false ? "Non finançable avec ce montant" : "Indisponible sur cette course"}
        </div>
      </div>
    </div>
  );

  // ── Non finançable / indisponible : le dire, chiffres à l'appui ──────────────
  if (!module.disponible) {
    return (
      <section aria-label="Quinté+" style={{ borderRadius: 15, overflow: "hidden", background: CX.surf1, border: `1px solid ${CX.slateBd}` }}>
        <div style={{ padding: "12px 14px", background: CX.slateBg }}>{titre}</div>
        <p style={{ margin: 0, padding: "11px 14px", fontSize: 11.5, lineHeight: 1.5, color: CX.gray600 }}>
          {module.motif || "Aucun ticket Quinté+ n'a pu être construit pour cette course."}
        </p>
        {module.financable === false && module.montant_minimum != null && (
          <p style={{ margin: 0, padding: "0 14px 12px", fontSize: 10.5, color: CX.gray500 }}>
            Montant minimum pour ajouter un Quinté+ : <strong style={{ color: CX.ink2 }}>{module.montant_minimum}€</strong>
            {module.cout_minimum != null && <> (ticket à {eur(module.cout_minimum)} + plan principal)</>}.
          </p>
        )}
      </section>
    );
  }

  const chevaux = module.chevaux ?? [];
  const gf = module.gain_fourchette;
  const rf = module.rapport_fourchette;
  const principal = module.montant_plan_principal ?? montantTotal - module.cout_total;
  const tendu = (module.nb_combinaisons ?? 1) <= 1;

  return (
    <section aria-label="Quinté+" style={{ borderRadius: 15, overflow: "hidden", background: CX.surf1, border: `1px solid ${CX.slateBd}`, boxShadow: "0 1px 2px rgba(17,24,39,.025)" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, padding: "12px 14px", borderBottom: `1px solid ${CX.bd4}`, background: CX.slateBg }}>
        {titre}
        <span style={{ fontFamily: CX.sg, fontWeight: 700, fontSize: 14, color: CX.slate, fontVariantNumeric: "tabular-nums", flexShrink: 0 }}>
          {eur(module.cout_total)}
        </span>
      </div>

      <div style={{ padding: "13px 14px", display: "flex", flexDirection: "column", gap: 11 }}>
        {/* Sélection : numéro + casaque + nom, dans l'ordre du classement de l'IA. */}
        <div>
          <div style={{ fontSize: 10.5, fontWeight: 600, color: CX.gray500, marginBottom: 6 }}>
            {tendu ? "Les 5 chevaux joués" : `${chevaux.length} chevaux · toutes les combinaisons de 5`}
          </div>
          <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(190px,1fr))", gap: 6 }}>
            {chevaux.map((c) => (
              <li key={c.numero} style={{ minWidth: 0, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6, borderRadius: 9, border: `1px solid ${CX.bd2}`, padding: "5px 8px", fontSize: 12, color: CX.ink2 }}>
                <span style={{ minWidth: 0, overflow: "hidden" }}><IdentiteCheval numero={c.numero} nom={c.nom} /></span>
                {c.rang != null && (
                  <span style={{ flexShrink: 0, fontSize: 10, color: CX.gray500, fontVariantNumeric: "tabular-nums" }}>
                    {c.rang}{c.rang === 1 ? "er" : "e"} IA
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>

        {/* Ticket : ce qui est réellement acheté au guichet. */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 6 }}>
          <Stat label="Formule" value={tendu ? "Tendu" : `Champ ${module.nb_chevaux ?? chevaux.length}`}
            sub={`${module.nb_combinaisons ?? 1} combinaison${(module.nb_combinaisons ?? 1) > 1 ? "s" : ""}`} />
          <Stat label="Flexi" value={tendu ? "Sans" : module.flexi_pct != null ? `${module.flexi_pct} %` : "—"}
            sub={module.mise_unitaire != null
              ? (tendu ? `mise de base ${eur(module.mise_unitaire)}` : `${eur(module.mise_unitaire)} par combinaison`)
              : undefined} />
          <Stat label="Chance de toucher les 5" value={module.proba_gain != null ? pct(module.proba_gain) : "—"}
            sub={module.proba_bonus != null ? `+ ${pct(module.proba_bonus)} de retour partiel (Bonus)` : undefined} />
          <Stat label="Si les 5 arrivent"
            value={gf ? (Math.round(gf.bas) === Math.round(gf.haut) ? `~${eurRond(gf.bas)}` : `${eurRond(gf.bas)} à ${eurRond(gf.haut)}`)
              : module.gain_potentiel != null ? `~${eurRond(module.gain_potentiel)}` : "—"}
            sub={rf ? (rf.bas === rf.haut ? `rapport estimé ×${rf.median.toFixed(0)} pour 1 €`
              : `rapport estimé ×${rf.bas.toFixed(0)} à ×${rf.haut.toFixed(0)} (médian ×${rf.median.toFixed(0)})`)
              : module.rapport_estime != null ? `rapport estimé ×${module.rapport_estime.toFixed(0)} pour 1 €` : undefined} />
        </div>

        {/* Partage du montant : l'égalité doit se lire, pas se deviner. */}
        <div style={{ fontSize: 11, lineHeight: 1.45, color: CX.gray600, fontVariantNumeric: "tabular-nums" }}>
          Pris sur votre montant : plan principal {eur(principal)} + Quinté+ {eur(module.cout_total)} = <strong style={{ color: CX.ink2 }}>{eur(principal + module.cout_total)}</strong>
        </div>

        {module.motif_couverture && (
          <div style={{ fontSize: 10.5, lineHeight: 1.45, color: CX.goldDeep, borderRadius: 8, border: `1px solid ${CX.goldBd}`, background: CX.goldBg, padding: "6px 9px" }}>
            {module.motif_couverture}
          </div>
        )}

        {/* Honnêteté : ni EV, ni promesse. Replié pour ne pas écraser le ticket. */}
        <details style={{ borderRadius: 9, background: CX.surf2 }}>
          <summary className="select-none" style={{ minHeight: 36, cursor: "pointer", padding: "0 10px", listStyle: "none", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, fontSize: 10.5, fontWeight: 650, color: CX.gray600 }}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}><Info className="h-3.5 w-3.5" aria-hidden="true" /> Un ticket de divertissement, pas un pari à valeur</span>
            <ChevronDown className="h-3 w-3" aria-hidden="true" />
          </summary>
          <ul style={{ margin: 0, padding: "0 10px 10px 28px", listStyle: "disc", display: "flex", flexDirection: "column", gap: 3, fontSize: 10.5, lineHeight: 1.5, color: CX.gray600 }}>
            <li>{module.note || "Aucune espérance de gain positive n'est établie pour un Quinté+ joué systématiquement."}</li>
            <li>Le rapport est estimé à partir des cotes : le rapport réel dépend des mises de tous les parieurs et peut sortir de la fourchette.</li>
            <li>La chance de toucher vient du classement de l&apos;IA ; elle n&apos;a pas encore été vérifiée sur les arrivées des Quinté+ passés.</li>
            <li>Ce ticket n&apos;est pas ajouté par « Enregistrer ce plan » : notez-le à part si vous le jouez.</li>
          </ul>
        </details>
      </div>
    </section>
  );
}
