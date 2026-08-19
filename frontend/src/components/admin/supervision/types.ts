/** Contrats des endpoints /admin/api/supervision/* — miroir de ml/bet_type_analytics.py. */

export interface RobustnessPoint { retires: number; roi_pct: number | null; n_restants: number }

export interface ParisReference {
  famille: string;
  a_trouver: string;
  prelevement_pct: number;
  mise_base: number;
  partants_min: number;
  frequence_offre_pct: number | null;
  quand_le_jouer: string;
}

export interface Agg {
  n_paris: number;
  n_gagnants: number;
  n_courses?: number;
  mise?: number;
  retour?: number;
  net?: number;
  net_winsorise?: number;
  roi_brut_pct?: number | null;
  roi_pct?: number | null;
  hit_rate?: number;
  gain_max?: number;
  gain_median?: number | null;
  mise_moyenne?: number;
  ic90_roi_pct?: [number, number] | null;
  n_gagnants_requis?: number;
  verdict: "rentable" | "perdant" | "neutre" | "insuffisant";
  robustesse?: RobustnessPoint[];
}

export interface TypeRow extends Agg {
  type: string;
  famille: string;
  part_mise_pct: number | null;
  contribution_net_pct: number | null;
  reference: ParisReference | null;
}

export interface FamilleRow extends Agg {
  famille: string;
  part_mise_pct: number | null;
}

export interface MatriceCell {
  profil: string;
  profil_key: string;
  type: string;
  n_paris: number;
  n_gagnants: number;
  mise: number;
  roi_pct: number | null;
}

export type SerieHebdoRow = { semaine: string; debut: string } & Record<string, number | string | null>;

export interface ParisPayload {
  fenetre_jours: number | null;
  since: string | null;
  generated_at: string;
  source: string;
  gain_cap_mise: number;
  min_gagnants_verdict: number;
  global: Agg;
  types: TypeRow[];
  familles: FamilleRow[];
  matrice_profil_type: MatriceCell[];
  types_series: string[];
  serie_hebdo: SerieHebdoRow[];
}

/** `net`/`cumul_net`/`roi_pct` = gains réels encaissés (aucun plafond).
 *  `*_winsor` = mêmes jours, gains coupés à `gain_cap_mise` × la mise. */
export interface JourRow {
  jour: string;
  mise: number;
  retour: number;
  retour_winsor: number;
  net: number;
  net_winsor: number;
  roi_pct: number | null;
  roi_winsor_pct: number | null;
  cumul_net: number;
  cumul_net_winsor: number;
  n_paris: number;
  n_gagnants: number;
  n_courses: number;
  roi_glissant_pct?: number | null;
  roi_glissant_winsor_pct?: number | null;
}

export interface RentabilitePayload {
  fenetre_jours: number | null;
  generated_at: string;
  gain_cap_mise: number;
  serie: JourRow[];
  cumul_par_profil: Record<string, Array<{ jour: string; cumul: number; cumul_winsor: number }>>;
  resume: {
    n_jours: number;
    jours_positifs: number;
    jours_positifs_winsor: number;
    taux_jours_positifs_pct: number | null;
    mise_totale: number;
    net_total: number;
    net_total_winsor: number;
    roi_pct: number | null;
    roi_winsor_pct: number | null;
    drawdown_max: number | null;
    drawdown_max_winsor: number | null;
    serie_perdante_max_jours: number | null;
    serie_perdante_max_jours_winsor: number | null;
    meilleur_jour: JourRow | null;
    pire_jour: JourRow | null;
  };
}

export interface ModelVersionRow {
  version: number;
  date: string | null;
  auc_roc: number | null;
  brier: number | null;
  precision_top3: number | null;
  roi_simule: number | null;
  courses_train: number | null;
  walk_forward_auc: number | null;
  walk_forward_variance: number | null;
  actif: boolean;
  rollback: boolean;
}

export interface AlgoEvolutionPayload {
  generated_at: string;
  versions: ModelVersionRow[];
  active: ModelVersionRow | null;
  precedente: ModelVersionRow | null;
  delta_vs_precedente: { auc_roc: number | null; brier: number | null; walk_forward_auc: number | null } | null;
  cadence_30j: Array<{ jour: string; n: number }>;
  total_versions: number;
}

export interface PulsePayload {
  server_time: string;
  courses_du_jour: { total: number; terminees: number; a_venir: number; derniere_terminee: string | null };
  conseils_du_jour: {
    emis: number; regles: number; dernier_reglement: string | null;
    age_dernier_reglement_min: number | null; net: number; mise: number;
  };
  apprentissage: {
    courses_apprises_24h: number; derniere_analyse: string | null;
    age_derniere_analyse_min: number | null;
  };
  fraicheur: {
    cotes_age_min: number | null;
    sources: Array<{ source: string; statut: string; age_min: number | null }>;
  };
}
