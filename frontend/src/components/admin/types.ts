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

export type Formule = "standard" | "expert";
export type CaseCompte = "payants" | "essais" | "offerts" | "gratuits";

/** Chaque compte (hors admin) est rangé dans UNE seule case : la somme des
 *  quatre vaut `comptes`. */
export interface Repartition {
  comptes: number;
  payants: number;
  essais: number;
  offerts: number;
  gratuits: number;
  par_formule: Record<Formule, { payants: number; essais: number; offerts: number }>;
}

export interface CompteOffert {
  user_id: string;
  email: string;
  plan: Formule;
  created_at: string;
  last_login: string | null;
}

export interface EnLigneData {
  disponible: boolean;
  fenetre_min: number;
  total: number | null;
  connectes: number | null;
  anonymes: number | null;
  comptes: Array<{
    user_id: string; email: string; plan: string; is_admin: boolean;
    chemin: string | null; vu_il_y_a_s: number | null;
  }>;
  pages: Array<{ chemin: string; n: number }>;
}

/** Issue d'un parcours d'abonnement — une seule par compte, cf. `admin._suivi_essais`. */
export type IssueSuivi =
  | "impaye"
  | "impaye_perdu"
  | "resiliation_programmee"
  | "en_essai"
  | "converti"
  | "resilie_pendant_essai"
  | "resilie_apres_paiement"
  | "essai_perdu_sans_carte";

export interface ParcoursAbo {
  user_id: string;
  email: string;
  formule: string;
  plan_compte: string;
  issue: IssueSuivi;
  statut: string;
  date_issue: string | null;
  debut: string | null;
  essai_fin: string | null;
  a_eu_essai: boolean;
  essai_refuse: boolean;
  /** Date de fin d'accès (à venir pour une résiliation programmée, passée sinon). */
  fin_acces: string | null;
  resiliation_le: string | null;
  resiliation_pendant_essai: boolean;
  a_paye: boolean;
  impaye_regularise: boolean;
  montant_cents: number | null;
  echecs_paiement: number;
  /** Relances faites par nous (J+3, J+7) — 2 au maximum. */
  relances_faites: number;
  derniere_tentative: string | null;
  prochaine_relance: string | null;
  relances_terminees: boolean;
  inscrit_le: string | null;
  derniere_connexion: string | null;
}

export interface CheckoutAbandonne {
  user_id: string;
  email: string;
  plan: string;
  inscrit_le: string | null;
  derniere_connexion: string | null;
}

export interface SuiviEssais {
  resume: Record<IssueSuivi, number> & {
    checkouts_abandonnes: number;
    essais_ouverts: number;
    essais_termines: number;
    essais_convertis: number;
    taux_conversion_essai: number | null;
    repasses_gratuits: number;
  };
  comptes: ParcoursAbo[];
  checkouts_abandonnes: CheckoutAbandonne[];
}

export interface AbonnementsData {
  repartition: Repartition;
  offerts: CompteOffert[];
  suivi: SuiviEssais;
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

export interface PaiementRecu {
  date: string;
  email: string | null;
  plan: Formule;
  montant_cents: number;
  rembourse_cents: number;
  /** Frais Stripe et net crédité — `null` quand la source est le journal interne. */
  frais_cents: number | null;
  net_cents: number | null;
  /** Premier encaissement du client, ou échéance suivante. */
  nature: "nouveau" | "renouvellement";
  motif: string | null;
  charge_id: string | null;
  /** Reçu Stripe officiel du paiement. */
  recu_url: string | null;
  facture_id: string | null;
  source: "stripe" | "journal";
}

export interface MoisRevenu {
  mois: string; // AAAA-MM, fuseau Europe/Paris
  /** Débits réussis, bruts. */
  encaisse_cents: number;
  rembourse_cents: number;
  /** Chiffre d'affaires encaissé = brut − remboursements. */
  ca_cents: number;
  frais_cents: number;
  net_cents: number;
  /** Virements arrivés sur le compte bancaire ce mois-là. */
  verse_cents: number;
  nb_remboursements: number;
  frais_connus: boolean;
  nb_paiements: number;
  nouveaux_cents: number;
  renouvellements_cents: number;
  par_formule: Record<Formule, number>;
  echecs_cents: number;
  nb_echecs: number;
  nb_clients: number;
  panier_moyen_cents: number | null;
  cumul_cents: number;
  paiements: PaiementRecu[];
}

export type NatureEcheance = "renouvellement" | "premier_prelevement" | "fin_acces" | "impaye";

export interface Echeance {
  user_id: string;
  email: string;
  plan: Formule;
  periodicite: string;
  statut: string;
  nature: NatureEcheance;
  date: string | null;
  jours_restants: number | null;
  montant_cents: number;
  stripe_subscription_id: string | null;
}

export interface EcartRapprochement {
  date: string;
  email: string | null;
  montant_cents: number;
  charge_id?: string | null;
}

export interface RevenusData {
  fuseau: string;
  source: { type: "stripe" | "journal"; lu_le: string | null; erreur: string | null };
  rapprochement: {
    verifie: boolean;
    absents_du_journal: EcartRapprochement[];
    absents_de_stripe: EcartRapprochement[];
  };
  mois: MoisRevenu[];
  totaux: {
    periode_cents: number;
    brut_cents: number;
    rembourse_cents: number;
    frais_cents: number;
    net_cents: number;
    verse_cents: number;
    mois_courant_cents: number;
    mois_precedent_cents: number | null;
    variation_pct: number | null;
    reste_a_encaisser_mois_cents: number;
    atterrissage_mois_cents: number;
    moyenne_mensuelle_cents: number;
    nb_paiements: number;
    echecs_cents: number;
  };
  prevision: Array<{ mois: string; prevu_cents: number }>;
  echeancier: Echeance[];
  computed_at: string;
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
  /** Défi du mois en cours (points, pas d'euros). */
  defi_mois: string;
  defi_solde: number;
  defi_rang: number | null;
  defi_points_nets: number;
  defi_points_mises: number;
  defi_nb_en_attente: number;
  defi_dernier_pari_at: string | null;
  roi: number | null;
  nb_paris: number;
  nb_gagnes: number;
}

export interface UserDetail {
  user: {
    user_id: string; email: string; nom: string | null; prenom: string | null;
    plan: string; is_active: boolean; is_admin: boolean; profil_risque: string;
    email_verified: boolean; auth_method: string;
    stripe_client: boolean; created_at: string; updated_at: string; last_login: string | null;
  };
  /** Défi du mois en cours. */
  defi: DefiStatsAdmin & {
    mois: string; rang: number | null; solde: number;
    plan: DefiStatsAdmin; perso: DefiStatsAdmin;
  };
  /** Tous les mois, paris gagnés/perdus seulement. */
  par_type: Array<{ type_pari: string; nb: number; points: number; net: number; nb_gagnes: number; roi: number | null }>;
  subscriptions: Array<{ sub_id: string; plan: string; periodicite: string; statut: string; periode_debut: string | null; periode_fin: string | null }>;
  nb_bets: number;
  /** Paris du Défi du mois, tous les mois, du plus récent au plus ancien. */
  bets: Array<{
    pari_id: string; mois: string; engage_at: string; type_pari: string; chevaux: number[];
    points: number; origine: "plan" | "perso"; statut: "en_attente" | "gagne" | "perd" | "rembourse";
    rapport: number | null; points_retour: number | null; course_id: string;
    course_code: string | null; hippodrome: string | null; course_date: string | null;
  }>;
}

export interface DefiStatsAdmin {
  nb_paris: number; nb_gagnes: number; nb_en_attente: number; points_nets: number; roi: number | null;
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
  resiliation_annulee: "Résiliation annulée — abonnement repris",
  resilie: "Résilié",
  paiement_echoue: "Paiement échoué — accès coupé",
  paiement_recu: "Paiement encaissé — accès rétabli",
  relance_paiement: "Relance du prélèvement",
  impaye_perdu: "Impayé après 2 relances — compte perdu",
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
  resiliation_annulee: "ok",
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
  relance_paiement: "attention",
  impaye_perdu: "alerte",
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
  "impaye_perdu",
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
