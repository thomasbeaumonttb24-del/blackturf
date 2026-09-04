"use client";

/**
 * « Outils d'apprentissage » — ce qui apprend, ce qui n'apprend plus, et ce qui
 * n'a jamais prouvé qu'il servait à quelque chose.
 *
 * Trois angles morts que ce bloc ferme :
 *
 *  - les dix-huit apprentissages nocturnes vivent tous DERRIÈRE le retrain, dans
 *    un seul job RQ. Quand le worker se fait OOM-killer, ils sautent en silence —
 *    vécu le 20/08/2026, quatre-vingt-treize secondes après un déploiement annoncé
 *    réussi. Ici on lit leur état PERSISTÉ : date du dernier succès, péremption
 *    au-delà de 48 h ;
 *  - un correcteur pouvait être en service SANS avoir prouvé qu'il améliorait la
 *    probabilité servie. On affiche le verdict qui décide : log-loss avec
 *    correction contre log-loss sans ;
 *  - une correction pouvait être apprise et jamais servie.
 *
 * Règle de la page, respectée ici : rien n'est affiché qui ne soit mesuré. Un
 * outil sans mesure porte « en attente » et dit pourquoi, jamais une valeur neutre
 * déguisée en résultat.
 */

import { AlertTriangle, CheckCircle2, Clock, Info, XCircle } from "lucide-react";
import { Empty, Note, Section, StatTile, num, pct, signedPct, tone } from "./kit";

export interface EtapeApprentissage {
  step: string;
  last_attempt_at?: string | null;
  last_success_at?: string | null;
  last_status?: string | null;
  last_error?: string | null;
  n_obs?: number | null;
  age_heures?: number | null;
}

export interface OutilsApprentissagePayload {
  etapes: EtapeApprentissage[];
  etapes_perimees: string[];
  seuil_perime_heures?: number;
  alerte: boolean;
  correcteur_contextuel: {
    actif: boolean;
    contrat?: string | null;
    contrat_attendu?: string | null;
    contrat_a_jour?: boolean;
    entraine_le?: string | null;
    n_exemples?: number | null;
    n_courses?: number | null;
    taux_de_base?: number | null;
    logloss_avec_correction?: number | null;
    logloss_sans_correction?: number | null;
    gain_logloss?: number | null;
    mesure_disponible: boolean;
    statut?: string | null;
  };
  modele_arrivee: {
    mesure_disponible: boolean;
    exposants?: number[] | null;
    corrige: boolean;
    gain_log_vraisemblance?: number | null;
    n_courses?: number | null;
    min_courses?: number | null;
    mis_a_jour_le?: string | null;
    pourquoi?: string;
  };
  alpha_marche: {
    mesure_disponible: boolean;
    alpha_max?: number | null;
    appris: boolean;
    alpha_en_place?: number | null;
    gain_logv?: number | null;
    gain_rang?: number | null;
    n_courses?: number | null;
    min_courses?: number | null;
    raison?: string | null;
    mis_a_jour_le?: string | null;
    pourquoi?: string;
  };
  nettete_probas?: {
    mesure_disponible: boolean;
    exposant?: number | null;
    appris: boolean;
    residuel?: number | null;
    gain_logv?: number | null;
    ecart_bande_haute_en_place?: number | null;
    ecart_bande_haute_candidat?: number | null;
    n_bande_haute?: number | null;
    n_courses?: number | null;
    min_courses?: number | null;
    raison?: string | null;
    mis_a_jour_le?: string | null;
    pourquoi?: string;
  };
  temperature: {
    temperature?: number | null;
    bornes: number[];
    ajustee_sur_mesure: boolean;
    min_courses?: number;
    mis_a_jour_le?: string | null;
    lecture: string;
  };
  plans: {
    mesure_disponible: boolean;
    n_snapshots_bruts?: number;
    n_conseils_distincts?: number;
    n_courses?: number;
    re_emissions_par_conseil?: number | null;
    lecture?: string;
  };
  gates_types: {
    mesure_disponible: boolean;
    gates: Array<{
      type: string; statut: string; facteur: number; raison?: string | null;
      roi_pct?: number | null; n_paris?: number | null; mis_a_jour_le?: string | null;
    }>;
    n_suspendus?: number;
    n_reduits?: number;
    lecture?: string;
  };
}

/** Libellés lisibles des étapes nocturnes — le nom technique ne se lit pas. */
const NOMS_ETAPES: Record<string, string> = {
  retrain: "Ré-entraînement du modèle",
  calibration_longshots: "Calibration des grosses cotes",
  isotone_top1: "Calibration de la proba de victoire",
  isotone_top3: "Calibration de la proba de placé",
  temperature: "Température de calibration",
  exposants_harville: "Modèle d'arrivée (biais de placé)",
  calibration_cote: "Calibration par tranche de cote",
  rattrapage_runs_profils: "Rattrapage des pronos non réglés",
  rattrapage_plans: "Rattrapage des plans non réglés",
  gates_segments: "Décisions par type de pari",
  performance_signaux: "ROI réel par signal",
  performance_bandes_ev: "ROI réel par bande d'EV",
  poids_profils: "Poids appris par profil",
  calibration_rapports: "Calibration des rapports",
  edge_monitor: "Surveillance de l'avantage",
  sante_features: "Santé des features",
  clv_monitor: "Valeur à la clôture (CLV)",
  poids_appris_types: "Poids appris par type de pari",
  integrite_pmu: "Intégrité des données PMU",
  nettete_probas: "Netteté des probabilités servies",
};

function nomEtape(step: string): string {
  return NOMS_ETAPES[step] ?? step.replace(/_/g, " ");
}

/** Facteur de conviction — deux décimales TOUJOURS : « ×0 » se lit comme une
 *  absence de valeur, « ×0,00 » comme une décision de ne plus jouer ce type. */
function facteur(v: number): string {
  return new Intl.NumberFormat("fr-FR", {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(v);
}

function ageLisible(h?: number | null): string {
  if (h == null || !isFinite(h)) return "jamais";
  if (h < 1) return "il y a moins d'une heure";
  if (h < 48) return `il y a ${Math.round(h)} h`;
  return `il y a ${Math.round(h / 24)} j`;
}

function BadgeEtape({ e, perimee }: { e: EtapeApprentissage; perimee: boolean }) {
  if (perimee) {
    return (
      <span
        title="Aucun succès depuis plus de 48 h. Ce que cette étape produit — courbe de calibration, poids, décisions — décrit un état du monde qui n'existe plus."
        className="inline-flex items-center gap-1 whitespace-nowrap rounded-full border border-red-200 bg-red-50 px-2 py-0.5 text-[10px] font-semibold text-red-700"
      >
        <XCircle className="h-3 w-3" /> Périmé
      </span>
    );
  }
  if (e.last_status === "ok") {
    return (
      <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-700">
        <CheckCircle2 className="h-3 w-3" /> À jour
      </span>
    );
  }
  return (
    <span
      title={e.last_error ?? undefined}
      className="inline-flex items-center gap-1 whitespace-nowrap rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700"
    >
      <AlertTriangle className="h-3 w-3" /> Dernière tentative en échec
    </span>
  );
}

export default function OutilsApprentissage({
  data,
}: {
  data?: OutilsApprentissagePayload;
}) {
  if (!data) {
    return (
      <Section
        title="Outils d'apprentissage"
        desc="Ce qui apprend, ce qui n'apprend plus, et ce qui n'a pas prouvé son utilité."
      >
        <Empty>Chargement de l'état des outils…</Empty>
      </Section>
    );
  }

  const perimees = new Set(data.etapes_perimees ?? []);
  const corr = data.correcteur_contextuel;
  const arrivee = data.modele_arrivee;
  const temp = data.temperature;
  const alpha = data.alpha_marche;
  const nettete = data.nettete_probas;
  const plans = data.plans;
  const gates = data.gates_types;

  const gainCorr = corr.gain_logloss ?? null;
  const exposants = arrivee.exposants ?? [];

  return (
    <div className="space-y-4">
      {/* ── Alerte de péremption ─────────────────────────────── */}
      {data.alerte && (
        <div className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 p-3.5 text-[11px] leading-relaxed text-red-800">
          <AlertTriangle className="mt-px h-4 w-4 shrink-0" />
          <div>
            <b>
              {data.etapes_perimees.length} apprentissage
              {data.etapes_perimees.length > 1 ? "s" : ""} sans succès depuis plus de{" "}
              {data.seuil_perime_heures ?? 48} h.
            </b>{" "}
            Ils tournent tous derrière le ré-entraînement, dans un seul job : quand
            celui-ci meurt — un manque de mémoire suffit — les suivants sautent sans
            rien dire. Ce qu'ils produisent (courbes de calibration, poids, décisions
            par type de pari) décrit alors un état du monde qui n'existe plus.
            <div className="mt-1 font-mono text-[10px]">
              {data.etapes_perimees.map(nomEtape).join(" · ")}
            </div>
          </div>
        </div>
      )}

      {/* ── Les correcteurs, et ce qu'ils ont prouvé ──────────── */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <StatTile
          label="Correcteur contextuel"
          hint="Ajuste la probabilité selon la discipline, le terrain, l'hippodrome, l'heure. Il n'est mis en service que s'il fait MIEUX que ne rien corriger, sur des courses qu'il n'a pas vues."
          value={corr.actif ? "En service" : "Inactif"}
          valueClass={corr.actif ? "text-emerald-700" : "text-gray-500"}
          sub={
            corr.mesure_disponible ? (
              <>
                log-loss {corr.logloss_avec_correction?.toFixed(4)} contre{" "}
                {corr.logloss_sans_correction?.toFixed(4)} sans correction
              </>
            ) : (
              "verdict d'utilité pas encore mesuré"
            )
          }
          footer={
            corr.mesure_disponible ? (
              <span className={`text-[11px] font-semibold ${tone(gainCorr)}`}>
                {gainCorr != null && gainCorr > 0
                  ? `gain prouvé : ${gainCorr.toFixed(5)}`
                  : "aucun gain démontré — non appliqué"}
              </span>
            ) : null
          }
        />
        <StatTile
          label="Modèle d'arrivée"
          hint="Les probabilités de placé se déduisent des probabilités de victoire. Sans correction, le placé du favori est surestimé et celui des outsiders sous-estimé — tout le catalogue combiné en dépend."
          value={arrivee.corrige ? "Corrigé" : "Non corrigé"}
          valueClass={arrivee.corrige ? "text-emerald-700" : "text-gray-500"}
          sub={
            exposants.length >= 3
              ? `exposants ${exposants.slice(0, 3).map((x) => x.toFixed(2)).join(" · ")}`
              : "—"
          }
          footer={
            <span className="text-[11px] text-gray-600">
              {arrivee.mesure_disponible
                ? `mesuré sur ${num(arrivee.n_courses)} courses`
                : `en attente — ${num(arrivee.min_courses)} courses nécessaires`}
            </span>
          }
        />
        <StatTile
          label="Confiance au modèle"
          hint="La probabilité servie mélange le modèle et le marché. Ce coefficient dit quelle part revient au modèle sur un favori. Il était posé à la main ; il est désormais ajusté sur les arrivées réelles, et seulement s'il améliore la vraisemblance SANS dégrader le classement."
          value={alpha?.alpha_max != null ? alpha.alpha_max.toFixed(2) : "—"}
          valueClass={alpha?.appris ? "text-emerald-700" : "text-gray-900"}
          sub={alpha?.appris ? "ajusté sur les arrivées" : "valeur réglée à la main"}
          footer={
            <span className="text-[11px] text-gray-600">
              {alpha?.mesure_disponible
                ? (alpha.appris
                    ? `+${(alpha.gain_logv ?? 0).toFixed(4)} de vraisemblance, classement ${(alpha.gain_rang ?? 0) >= 0 ? "préservé" : "dégradé"}`
                    : (alpha.raison ?? "aucun réglage ne fait mieux"))
                : `en attente — ${num(alpha?.min_courses)} courses nécessaires`}
            </span>
          }
        />
        <StatTile
          label="Netteté des probabilités"
          hint="La probabilité servie est-elle trop concentrée sur les premiers du classement ? Cet exposant l'aplatit ou la resserre sur TOUTE la course (somme préservée, ordre inchangé). 1,00 = servie telle quelle. Il n'est retenu que s'il améliore la vraisemblance hors échantillon SANS dégrader la calibration de la queue."
          value={nettete?.exposant != null ? nettete.exposant.toFixed(2) : "1,00"}
          valueClass={nettete?.appris ? "text-emerald-700" : "text-gray-900"}
          sub={nettete?.appris ? "ajustée sur les arrivées" : "distribution servie telle quelle"}
          footer={
            <span className="text-[11px] text-gray-600">
              {nettete?.mesure_disponible
                ? (nettete.appris
                    ? `écart de la queue ${signedPct((nettete.ecart_bande_haute_en_place ?? 0) * 100)} → ${signedPct((nettete.ecart_bande_haute_candidat ?? 0) * 100)} sur ${num(nettete.n_bande_haute)} partants`
                    : (nettete.raison ?? "aucun exposant ne fait mieux"))
                : `en attente — ${num(nettete?.min_courses)} courses nécessaires`}
            </span>
          }
        />
        <StatTile
          label="Température"
          hint="Étale ou resserre les probabilités du champ. Ajustée sur mesure, elle minimise la log-vraisemblance sur les courses récentes ; sinon elle dérive vers le haut au fil des surprises."
          value={temp.temperature != null ? temp.temperature.toFixed(4) : "—"}
          sub={temp.ajustee_sur_mesure ? "ajustée sur mesure" : "cliquet par course"}
          valueClass={
            temp.temperature != null && temp.temperature > 1.5
              ? "text-red-700"
              : "text-gray-900"
          }
          footer={
            <span className="text-[11px] text-gray-600">{temp.lecture}</span>
          }
        />
        <StatTile
          label="Conseils appris"
          hint="Un conseil = une observation. Le même plan est ré-émis à chaque mouvement de cote : compter les ré-émissions ferait atteindre les seuils de fiabilité avec une seule course."
          value={plans.mesure_disponible ? num(plans.n_conseils_distincts) : "—"}
          sub={
            plans.mesure_disponible ? (
              <>
                sur {num(plans.n_courses)} courses ·{" "}
                {plans.re_emissions_par_conseil ?? "—"} ré-émissions par conseil
              </>
            ) : (
              "aucun plan réglé pour l'instant"
            )
          }
        />
      </div>

      {/* ── Journal des étapes nocturnes ──────────────────────── */}
      <Section
        title="Étapes d'apprentissage"
        desc="Date du dernier SUCCÈS de chaque étape. Un échec ne l'efface pas : c'est l'écart entre les deux qui rend une panne visible."
        right={
          <span className="text-[10px] text-gray-500">
            périmé au-delà de {data.seuil_perime_heures ?? 48} h
          </span>
        }
      >
        {data.etapes.length === 0 ? (
          <Empty>
            Aucune étape journalisée pour l'instant — le journal se remplit à la
            première nuit qui suit le déploiement.
          </Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-left text-[11px]">
              <thead className="text-gray-500">
                <tr className="border-b border-gray-100">
                  <th className="py-2 pr-3 font-semibold">Étape</th>
                  <th className="py-2 pr-3 font-semibold">Dernier succès</th>
                  <th className="py-2 pr-3 font-semibold">Observations</th>
                  <th className="py-2 font-semibold">État</th>
                </tr>
              </thead>
              <tbody>
                {data.etapes.map((e) => {
                  const perimee = perimees.has(e.step);
                  return (
                    <tr
                      key={e.step}
                      className={`border-b border-gray-50 ${perimee ? "bg-red-50/40" : ""}`}
                    >
                      <td className="py-2 pr-3 font-medium text-gray-900">
                        {nomEtape(e.step)}
                      </td>
                      <td className="py-2 pr-3 tabular-nums text-gray-700">
                        <span className="inline-flex items-center gap-1">
                          <Clock className="h-3 w-3 text-gray-400" />
                          {ageLisible(e.age_heures)}
                        </span>
                      </td>
                      <td className="py-2 pr-3 tabular-nums text-gray-700">
                        {e.n_obs != null ? num(e.n_obs) : "—"}
                      </td>
                      <td className="py-2">
                        <BadgeEtape e={e} perimee={perimee} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <Note>
          Ces étapes ne s'exécutent pas indépendamment : elles s'enchaînent derrière
          le ré-entraînement dans un même job. C'est pour ça qu'on lit leur état
          persisté plutôt que les journaux — un journal qui ne dit rien ne prouve
          rien, une date de dernier succès vieille de trois jours si.
        </Note>
      </Section>

      {/* ── Décisions automatiques par type de pari ───────────── */}
      <Section
        title="Décisions par type de pari"
        desc="Ce que l'apprentissage a suspendu, réduit, ou laissé actif — et sur quelle mesure."
        right={
          gates.mesure_disponible ? (
            <span className="text-[10px] text-gray-500">
              {num(gates.n_suspendus)} suspendu(s) · {num(gates.n_reduits)} réduit(s)
            </span>
          ) : null
        }
      >
        {!gates.mesure_disponible ? (
          <Empty>
            Aucune décision enregistrée : les types de pari tournent tous à
            conviction pleine tant que rien n'a été mesuré.
          </Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[620px] text-left text-[11px]">
              <thead className="text-gray-500">
                <tr className="border-b border-gray-100">
                  <th className="py-2 pr-3 font-semibold">Type</th>
                  <th className="py-2 pr-3 font-semibold">Décision</th>
                  <th className="py-2 pr-3 font-semibold">Conviction</th>
                  <th className="py-2 pr-3 font-semibold">ROI mesuré</th>
                  <th className="py-2 font-semibold">Pourquoi</th>
                </tr>
              </thead>
              <tbody>
                {gates.gates.map((g) => (
                  <tr key={g.type} className="border-b border-gray-50 align-top">
                    <td className="py-2 pr-3 font-medium text-gray-900">{g.type}</td>
                    <td className="py-2 pr-3">
                      <span
                        className={`inline-flex whitespace-nowrap rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
                          g.statut === "suspended"
                            ? "border-red-200 bg-red-50 text-red-700"
                            : g.statut === "reduced"
                              ? "border-amber-200 bg-amber-50 text-amber-700"
                              : "border-emerald-200 bg-emerald-50 text-emerald-700"
                        }`}
                      >
                        {g.statut === "suspended"
                          ? "Suspendu"
                          : g.statut === "reduced"
                            ? "Réduit"
                            : "Actif"}
                      </span>
                    </td>
                    <td className="py-2 pr-3 tabular-nums text-gray-700">
                      ×{facteur(g.facteur)}
                    </td>
                    <td className={`py-2 pr-3 tabular-nums ${tone(g.roi_pct ?? null)}`}>
                      {pct(g.roi_pct)}
                      {g.n_paris != null && (
                        <span className="ml-1.5 text-gray-400">
                          {" "}sur {num(g.n_paris)} paris
                        </span>
                      )}
                    </td>
                    <td className="max-w-[280px] py-2 text-[10px] leading-relaxed text-gray-600">
                      {g.raison ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {gates.lecture && <Note>{gates.lecture}</Note>}
      </Section>

      {/* ── Contrat du correcteur ─────────────────────────────── */}
      {corr.contrat && corr.contrat_a_jour === false && (
        <div className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3.5 text-[11px] leading-relaxed text-amber-800">
          <Info className="mt-px h-4 w-4 shrink-0" />
          <div>
            <b>Le correcteur contextuel a été entraîné sous un autre contrat.</b> Il
            a appris sur des exemples d'une autre nature que ceux qu'il reçoit
            aujourd'hui ; il est donc neutralisé jusqu'au prochain ré-entraînement,
            plutôt que d'appliquer une correction qui ne veut plus rien dire.
            <div className="mt-1 font-mono text-[10px]">
              trouvé : {corr.contrat} · attendu : {corr.contrat_attendu}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
