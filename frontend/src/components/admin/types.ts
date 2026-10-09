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
    nb_courses_evaluees?: number;
    trained_at: string | null;
  };
  courses_24h: number;
  alertes_erreur: number;
}

/** Ce qu'une version a RÉELLEMENT fait pendant qu'elle servait : courses
 *  analysées attribuées au dernier snapshot pris avant le départ. */
export interface ModelEnCourse {
  n_courses: number;
  /** Part des courses où le gagnant figurait dans le top-3 prédit (0..1). */
  top3: number | null;
  top1: number | null;
  /** Brier top-3 par partant, moyenné par course — même définition qu'à l'entraînement. */
  brier: number | null;
  debut: string | null;
  fin: string | null;
}

export interface ModelVersion {
  version_id: string;
  version_num: number;
  created_at: string;
  /** Départ de la dernière course apprise. */
  train_fin: string | null;
  /** Nombre de PARTANTS d'entraînement (~9,3 par course), pas de courses :
   *  la colonne SQL porte ce nom depuis la migration 0001. */
  nb_courses_train: number;
  est_actif: boolean;
  est_rollback: boolean;
  /** Le pickle est encore sur le volume : seules les dernières versions le gardent. */
  fichier_disponible: boolean;
  // ── hold-out d'entraînement ──
  auc_roc: number | null;
  brier_score: number | null;
  precision_top3: number | null;
  walk_forward_auc: number | null;
  walk_forward_variance: number | null;
  /** AUC intra-course du modèle, et celle du classement par la cote sur les mêmes courses. */
  rank_auc: number | null;
  market_rank_auc: number | null;
  rank_delta_market: number | null;
  // ── en service ──
  en_course: ModelEnCourse | null;
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

/** Verdict calculé par le serveur (`/admin/api/scraper/status`), jamais le
 *  dernier statut brut de `scrape_log` : une source muette depuis quatre mois
 *  y restait « ok ». */
export type StatutSource =
  | "ok" | "en_retard" | "vide" | "erreur" | "au_repos" | "desactivee" | "inconnue";

export interface SourceDonnees {
  /** `scraper` écrit dans scrape_log ; `cotes` = démon hors Docker, lu dans cotes_bookmakers. */
  type: "scraper" | "cotes";
  libelle: string;
  role: string | null;
  statut: StatutSource;
  raison_arret: string | null;
  derniere_maj: string | null;
  duree_ms: number | null;
  erreur: string | null;
  /** Au-delà de ce silence (minutes), la source est en retard. null = pas de cadence. */
  retard_max_min: number | null;
  n_24h: number;
  n_ok_24h: number | null;
  n_avec_donnees_24h: number | null;
  partants_cotes_24h?: number;
}

export interface ScraperStatus {
  [source: string]: SourceDonnees;
}

export const STATUT_SOURCE_LABELS: Record<string, string> = {
  ok: "en service",
  en_retard: "en retard",
  vide: "tourne à vide",
  erreur: "en erreur",
  au_repos: "au repos",
  desactivee: "désactivée",
  inconnue: "non déclarée",
};

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
export type CaseCompte = "payants" | "essais" | "passes" | "offerts" | "gratuits";

/** Chaque compte (hors admin) est rangé dans UNE seule case : la somme des
 *  cases vaut `comptes`. `passes` : pass sans renouvellement en cours (payé une fois). */
export interface Repartition {
  comptes: number;
  payants: number;
  essais: number;
  passes: number;
  offerts: number;
  gratuits: number;
  par_formule: Record<Formule, { payants: number; essais: number; passes: number; offerts: number }>;
}

export interface CompteOffert {
  user_id: string;
  email: string;
  plan: Formule;
  jusqu_au?: string | null;
  motif?: string | null;
  created_at: string;
  last_login: string | null;
}

/** Pass sans renouvellement en cours. */
export type DureePass = "jour" | "semaine" | "mois";

export interface PassResume {
  duree: DureePass | string;
  debut: string;
  /** Fin de l'accès cumulé (pass enchaînés compris). */
  fin: string;
  statut: "en_cours" | "a_venir" | "expire" | "rembourse";
  montant_cents: number;
  achete_le: string;
  /** Pass déjà payés qui prendront le relais de celui-ci. */
  nb_a_venir: number;
  nb_total: number;
}

export interface ComptePass {
  user_id: string;
  email: string;
  jusqu_au: string;
  duree?: string | null;
  debut?: string | null;
  statut?: PassResume["statut"] | null;
  nb_a_venir?: number;
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
  passes?: ComptePass[];
  suivi: SuiviEssais;
  resume: {
    en_essai_avec_carte: number;
    en_essai_sans_carte: number;
    abonnes_payants: number;
    fin_essai_sous_3j: number;
    mrr: number;
    arr: number;
    /** Payants ayant résilié : payés jusqu'à l'échéance, hors MRR. */
    mrr_resiliations?: number;
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
  /** `pass` : pass sans renouvellement (paiement unique). */
  plan: Formule | "pass";
  montant_cents: number;
  rembourse_cents: number;
  /** Frais Stripe et net crédité — `null` quand la source est le journal interne. */
  frais_cents: number | null;
  net_cents: number | null;
  /** Premier encaissement du client, ou échéance suivante. */
  nature: "nouveau" | "renouvellement" | "changement" | "pass";
  /** Pass : durée achetée et période d'accès réellement ouverte. */
  pass_duree?: string | null;
  pass_debut?: string | null;
  pass_fin?: string | null;
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
  /** Différences au prorata réglées lors d'un changement de formule. */
  changements_cents?: number;
  par_formule: Record<Formule, number>;
  /** Passes sans renouvellement encaissés (hors formules d'abonnement). */
  passes_cents?: number;
  echecs_cents: number;
  /** Abonnements dont le prélèvement a échoué ce mois-ci (un par abonnement, pas par tentative). */
  nb_echecs: number;
  /** Parmi eux, ceux qui ont payé depuis. */
  nb_echecs_regles?: number;
  /** Tentatives Stripe refusées (réessais compris). */
  nb_tentatives_echouees?: number;
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
  pseudo?: string | null;
  plan: string;
  profil_risque: string;
  is_active: boolean;
  is_admin: boolean;
  email_verified: boolean;
  auth_method: string;
  stripe_client: boolean;
  abonnement_statut: string | null;
  /** Dernière Subscription Stripe : formule facturée, rythme, échéance. */
  abonnement?: {
    plan: string; periodicite: string; statut: string;
    periode_fin: string | null; essai_fin: string | null;
  } | null;
  /** Pass sans renouvellement le plus parlant : en cours, sinon le dernier. */
  pass?: PassResume | null;
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
    email_verified: boolean; auth_method: string; pseudo?: string | null;
    stripe_client: boolean; created_at: string; updated_at: string; last_login: string | null;
  };
  acces_offert?: { plan: string; jusqu_au: string | null; motif: string | null; depuis: string; actif: boolean } | null;
  /** Pass sans renouvellement achetés (du plus récent au plus ancien). */
  passes?: Array<{ duree: string; montant_cents: number; debut: string; fin: string; statut: string; achete_le: string }>;
  /** Défi du mois en cours. */
  defi: DefiStatsAdmin & {
    mois: string; rang: number | null; solde: number;
    plan: DefiStatsAdmin; perso: DefiStatsAdmin;
  };
  /** Tous les mois, paris gagnés/perdus seulement. */
  par_type: Array<{ type_pari: string; nb: number; points: number; net: number; nb_gagnes: number; roi: number | null }>;
  subscriptions: Array<{ sub_id: string; plan: string; periodicite: string; statut: string; periode_debut: string | null; periode_fin: string | null }>;
  nb_bets: number;
  /** Absent sur une API antérieure au parrainage. */
  parrainage?: {
    code: string | null;
    parraine_par: LienFiche | null;
    filleuls: LienFiche[];
    valides: number;
    gagne_cents: number;
  };
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
  pass_achete: "Pass sans renouvellement acheté",
  pass_retire: "Pass retiré — paiement remboursé ou contesté",
  pass_termine: "Pass arrivé à échéance",
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
  pass_achete: "ok",
  pass_retire: "alerte",
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
 *  projet (4 scrapers « ok » à zéro donnée pendant des semaines). Il reste rouge.
 *  « au_repos » (aucune course proche) et « desactivee » (coupée exprès) ne sont
 *  pas des pannes. */
export const SCRAPERS_SAINS = ["ok", "ok_avec_echecs", "au_repos", "desactivee"];
export const scraperSain = (statut: string) => SCRAPERS_SAINS.includes(statut);


/* ───────────────────────────── parrainage ───────────────────────────── */

export interface LienFiche {
  user_id: string | null;
  email: string;
  statut: StatutParrainage;
  etape_libelle: string;
  created_at: string;
  valide_at: string | null;
}

export type StatutParrainage = "en_attente" | "valide" | "refuse" | "annule";

export interface CompteParrainage {
  user_id: string | null;
  email: string | null;
  prenom: string | null;
  plan: string | null;
}

export interface LienParrainage {
  parrainage_id: string;
  created_at: string;
  parrain: CompteParrainage;
  filleul: CompteParrainage;
  statut: StatutParrainage;
  etape: string;
  etape_libelle: string;
  motif: string | null;
  motif_libelle: string | null;
  remise_filleul_at: string | null;
  valide_at: string | null;
  credit_pose_at: string | null;
  stripe_invoice_id: string | null;
  paye_filleul_cents: number;
}

export interface ParrainClassement {
  user_id: string;
  email: string | null;
  prenom: string | null;
  plan: string | null;
  code: string | null;
  filleuls: number;
  en_attente: number;
  valides: number;
  reportes: number;
  refuses: number;
  annules: number;
  gagne_cents: number;
  ca_filleuls_cents: number;
  dernier_filleul_at: string | null;
}

export interface ParrainagesData {
  resume: {
    liens_generes: number;
    parrains_actifs: number;
    filleuls: number;
    en_attente: number;
    valides: number;
    reportes: number;
    refuses: number;
    annules: number;
    taux_conversion: number | null;
    credits_parrains_cents: number;
    remises_filleuls_cents: number;
    cout_total_cents: number;
    ca_filleuls_cents: number;
    rendement: number | null;
  };
  parrains: ParrainClassement[];
  liens: LienParrainage[];
  evolution: Array<{ mois: string; inscrits: number; valides: number }>;
}
