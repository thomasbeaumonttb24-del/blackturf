/**
 * Types du back-office.
 *
 * Ils vivaient dans `app/admin/page.tsx`, au milieu de 1 500 lignes de JSX.
 * Les sortir n'est pas cosmétique : la console est désormais découpée en
 * quatre pages qui parlent des mêmes objets, et un type recopié dans quatre
 * fichiers dérive au premier changement d'API.
 */

export interface DashboardData {
  users: { total: number; nouveaux_7j: number; abonnes_actifs: number };
  modele: {
    version: number | null;
    auc_roc: number | null;
    precision_top3: number | null;
    trained_at: string | null;
  };
  courses_24h: number;
  alertes_erreur: number;
}

export interface ModelVersion {
  version_num: number;
  auc_roc: number;
  brier_score: number;
  precision_top3: number | null;
  roi_simule: number | null;
  walk_forward_auc: number | null;
  walk_forward_variance: number | null;
  /** Nombre de PARTANTS d'entraînement (~9,3 par course), pas de courses :
   *  la colonne SQL porte ce nom depuis la migration 0001. */
  nb_courses_train: number;
  est_actif: boolean;
  est_rollback: boolean;
  created_at: string;
}

export interface SystemError {
  id: number | null;
  kind: string;
  created_at: string | null;
  source: string;
  level: string;
  message: string;
  detail: string | null;
  endpoint: string | null;
  resolved: boolean;
  // Une anomalie persistante est UNE ligne qui se répète, pas N lignes :
  // `created_at` date son DÉBUT, `derniere_occurrence` son dernier écho.
  occurrences?: number;
  derniere_occurrence?: string | null;
}

export interface ScraperStatus {
  [source: string]: {
    statut: string;
    derniere_maj: string | null;
    duree_ms: number | null;
    erreur: string | null;
  };
}

export interface AbonneLigne {
  user_id: string;
  email: string;
  plan: string;
  periodicite: string;
  statut: string;
  carte_enregistree: boolean;
  acces_ouvert: boolean;
  en_essai: boolean;
  essai_fin: string | null;
  jours_essai_restants: number | null;
  periode_fin: string | null;
  montant_cents: number;
  stripe_subscription_id: string | null;
  depuis: string;
}

export interface MouvementAbo {
  event_id: string;
  type: string;
  email: string | null;
  plan: string | null;
  plan_precedent: string | null;
  montant_cents: number | null;
  essai_fin: string | null;
  pendant_essai: boolean | null;
  created_at: string;
}

export interface AbonnementsData {
  resume: {
    en_essai_avec_carte: number;
    en_essai_sans_carte: number;
    abonnes_payants: number;
    fin_essai_sous_3j: number;
    mrr: number;
    arr: number;
    essais_ouverts_30j: number;
    essais_perdus_30j: number;
    resiliations_30j: number;
    resiliations_pendant_essai_30j: number;
  };
  abonnes: AbonneLigne[];
  mouvements: MouvementAbo[];
}

export interface CompteLigne {
  user_id: string;
  email: string;
  nom: string | null;
  prenom: string | null;
  plan: string;
  profil_risque: string;
  is_active: boolean;
  is_admin: boolean;
  email_verified: boolean;
  auth_method: string;
  stripe_client: boolean;
  abonnement_statut: string | null;
  last_login: string | null;
  created_at: string;
  solde_actuel: number;
  mise_totale: number;
  gain_net: number;
  roi: number | null;
  nb_paris: number;
  nb_gagnes: number;
}

export interface UserDetail {
  user: {
    user_id: string; email: string; nom: string | null; prenom: string | null;
    plan: string; is_active: boolean; is_admin: boolean; profil_risque: string;
    bankroll_initiale: number | null; email_verified: boolean; auth_method: string;
    stripe_client: boolean; created_at: string; updated_at: string; last_login: string | null;
  };
  portefeuille: {
    capital_initial: number; solde_actuel: number; mise_totale: number; gain_net: number;
    roi: number | null; nb_paris: number; nb_gagnes: number; nb_perdus: number;
    nb_attente: number; nb_regles: number; win_rate: number | null; nb_predictions_used: number;
  };
  par_type: Array<{ type_pari: string; nb: number; mise: number; net: number; nb_gagnes: number; roi: number | null }>;
  subscriptions: Array<{ sub_id: string; plan: string; periodicite: string; statut: string; periode_debut: string | null; periode_fin: string | null }>;
  nb_bets: number;
  bets: Array<{
    entry_id: string; date: string; type_pari: string; chevaux: string | null;
    mise: number; cote: number | null; resultat: string | null; gain_perte: number | null;
    suivi_reco_ia: boolean; notes: string | null; course_code: string | null;
    hippodrome: string | null; course_date: string | null; course_statut: string | null;
  }>;
}

export interface PalmaresNet {
  n: number;
  n_courses?: number;
  total_gain?: number;
  total_benefice?: number;
  profils?: Array<{
    profil: string; label: string; nb_courses: number; mise_totale?: number;
    gain_total?: number; gain_net: number; roi: number | null; paris_gagnes: number;
    taux_courses_beneficiaires: number | null;
  }>;
  updated_at?: string;
}

/** Libellés du journal. Doit rester aligné sur `services/abonnements.LIBELLES`. */
export const MOUVEMENT_LABELS: Record<string, string> = {
  essai_ouvert: "Essai ouvert",
  essai_sans_carte: "Essai sans carte",
  carte_ajoutee: "Carte enregistrée",
  abonnement_actif: "Abonnement actif",
  changement_plan: "Changement de formule",
  essai_bientot_fini: "Essai bientôt fini",
  essai_termine_sans_carte: "Essai perdu (sans carte)",
  resiliation_demandee: "Résiliation demandée",
  resilie: "Résilié",
  paiement_echoue: "Paiement échoué — accès coupé",
  paiement_recu: "Paiement encaissé — accès rétabli",
  essai_refuse_carte_reutilisee: "Essai refusé — carte d'un autre compte",
  carte_refusee_autre_compte: "Abonnement refusé — carte d'un autre compte",
  // Statuts Stripe bruts : `_handle_subscription_updated` les journalise tels quels
  // quand le changement ne correspond à aucun mouvement métier nommé.
  past_due: "Impayé — accès coupé, relances Stripe en cours",
  unpaid: "Impayé définitif — relances Stripe épuisées",
  canceled: "Abonnement clos chez Stripe",
  incomplete: "Paiement jamais finalisé",
  incomplete_expired: "Paiement abandonné — abonnement expiré",
  paused: "Abonnement suspendu",
};

export const MOUVEMENT_TONS: Record<string, "ok" | "attention" | "alerte" | "neutre"> = {
  carte_ajoutee: "ok",
  abonnement_actif: "ok",
  paiement_recu: "ok",
  essai_ouvert: "neutre",
  changement_plan: "neutre",
  canceled: "neutre",
  incomplete_expired: "neutre",
  essai_sans_carte: "attention",
  essai_bientot_fini: "attention",
  essai_refuse_carte_reutilisee: "attention",
  incomplete: "attention",
  paused: "attention",
  essai_termine_sans_carte: "alerte",
  resiliation_demandee: "alerte",
  resilie: "alerte",
  paiement_echoue: "alerte",
  carte_refusee_autre_compte: "alerte",
  past_due: "alerte",
  unpaid: "alerte",
};

/** Mouvements qui coupent l'accès ou font perdre un client : remontés hors du journal.
 *  `past_due` et `unpaid` en font partie : quand les relances Stripe s'épuisent,
 *  l'abonnement bascule en impayé sans qu'aucune facture n'échoue au même instant. */
export const MOUVEMENTS_ECHEC = new Set([
  "paiement_echoue",
  "past_due",
  "unpaid",
  "essai_termine_sans_carte",
  "essai_refuse_carte_reutilisee",
  "carte_refusee_autre_compte",
]);

export const PROFIL_NET_LABELS: Record<string, string> = {
  conservateur: "Prudent",
  equilibre: "Modéré",
  agressif: "Risqué",
};

/** « ok_avec_echecs » (échecs comptés, sous le seuil d'anomalie) reste sain.
 *  Liste EXPLICITE et jamais un préfixe « ok » : `sante_scrapers()` produit aussi
 *  `ok_but_empty` — que des succès, aucune donnée — et c'est le cas trompeur du
 *  projet (4 scrapers « ok » à zéro donnée pendant des semaines). Il reste rouge. */
export const SCRAPERS_SAINS = ["ok", "ok_avec_echecs"];
export const scraperSain = (statut: string) => SCRAPERS_SAINS.includes(statut);
