"""
algo_flags.py — Feature flags pour les corrections d'edge (audit 2026-06-14).

Cause racine corrigée (voir memory blackturf-edge-rootcause / tasks audit) :
le système montrait +150% in-sample mais -52% out-of-sample à cause de fuites
(leakage), d'un edge qui n'était que le marché re-encodé, et d'un staking non gardé.

DEPUIS 2026-07-02 : les corrections anti-leakage sont ACTIVES PAR DÉFAUT.
Elles étaient restées désactivées en prod (jamais mises dans le .env) → le système
continuait d'apprendre sur des données fuitées et un ROI illusoire. Le ROI réel est
la priorité produit : les corrections sont donc le comportement NORMAL du code.
Chaque flag reste désactivable individuellement via env (rollback ciblé) :
    BT_DEVIG_GATES=0        # exemple : désactive le dé-vig des gates value bet

Restent OPT-IN (expérimentaux / dépendances externes) :
    BT_TEMP_FIT=1           # fit 1-D de température sur NLL held-out
    BT_RANKER_BLEND=1       # nécessite un modèle entraîné AVEC LGBMRanker

Usage :
    from ml.algo_flags import FLAGS
    if FLAGS.devig_gates:
        ...  # chemin corrigé (défaut)
    else:
        ...  # comportement historique (rollback)

Valeurs acceptées comme "vrai" : 1, true, yes, on (insensible à la casse).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class AlgoFlags:
    # ── Anti-leakage (modèle / calibration) — ACTIFS PAR DÉFAUT ──────────────
    # Entraînement uniquement sur features figées AVANT le départ
    # (fm.computed_at < c.date_heure), comme meta_learner. Réduit la fuite des
    # features backfillées post-course.
    train_prerace_only: bool = field(default_factory=lambda: _env_bool("BT_TRAIN_PRERACE_ONLY", True))
    # Split train/test/OOF/walk-forward PAR COURSE (course_id), pas par cheval.
    # Évite la fuite des frères de course.
    group_split: bool = field(default_factory=lambda: _env_bool("BT_GROUP_SPLIT", True))
    # cote_calibration n'apprend que sur prédictions pré-départ non-backfill.
    calib_guard: bool = field(default_factory=lambda: _env_bool("BT_CALIB_GUARD", True))

    # ── Sélection value bets — ACTIF PAR DÉFAUT ──────────────────────────────
    # Dé-vig le marché (normalise 1/cote sur le champ) avant les gates/EV.
    devig_gates: bool = field(default_factory=lambda: _env_bool("BT_DEVIG_GATES", True))

    # ── Staking — ACTIF PAR DÉFAUT (staking AUTO uniquement, le calculateur ──
    # manuel/pronos figés passent par respect_montant qui prime) ─────────────
    # Kelly shrinké par l'edge OOS + cap bankroll dur + désactive le dump
    # "gain target" qui jette Kelly.
    staking_safe: bool = field(default_factory=lambda: _env_bool("BT_STAKING_SAFE", True))
    # Fraction de Kelly appliquée quand staking_safe est actif (shrink global
    # tant que l'edge OOS n'est pas prouvé positif). 0.10 = très prudent.
    kelly_oos_shrink: float = field(default_factory=lambda: _env_float("BT_KELLY_OOS_SHRINK", 0.10))
    # Cap dur de l'exposition par course en fraction du bankroll.
    bankroll_cap_frac: float = field(default_factory=lambda: _env_float("BT_BANKROLL_CAP_FRAC", 0.03))

    # ── Gate de déploiement — ACTIFS PAR DÉFAUT ──────────────────────────────
    # Refuse de promouvoir un modèle/poids si le ROI held-out < 0 ou edge_ok faux.
    roi_deploy_gate: bool = field(default_factory=lambda: _env_bool("BT_ROI_DEPLOY_GATE", True))
    # Poids de paris appris depuis profil_run_log OOS réel, pas le backtest in-sample.
    oos_weights: bool = field(default_factory=lambda: _env_bool("BT_OOS_WEIGHTS", True))

    # ── Batch 2 : boucle auto-apprenante honnête — ACTIFS PAR DÉFAUT ─────────
    # Calibrations (isotonic top1/top3, longshot, cote) fittées sur la proba RAW
    # modèle (colonnes proba_*_raw, migration 0024) au lieu de la proba déjà
    # calibrée → casse la boucle fermée qui chasse son propre résidu. NÉCESSITE
    # d'avoir appliqué la migration 0024 (présente) ET predict_course écrit les raw.
    calib_on_raw: bool = field(default_factory=lambda: _env_bool("BT_CALIB_ON_RAW", True))
    # Empile une seule correction favori-longshot : si actif, on NE ré-applique
    # PAS longshot_calibration après le blend marché (le blend + isotonic suffisent)
    # → fin du triple-comptage qui écrasait l'edge quand le modèle a raison.
    collapse_longshot: bool = field(default_factory=lambda: _env_bool("BT_COLLAPSE_LONGSHOT", True))
    # combo_bets : EV neutralisée pour les paris non-Simple (l'EV trj/p_market vs
    # p_model était mécaniquement positive dès que modèle>marché). Dimensionnés à plat.
    combo_ev_none: bool = field(default_factory=lambda: _env_bool("BT_COMBO_EV_NONE", True))
    # CAP MODÈLE/MARCHÉ DANS LES COMBOS (audit ROI 2026-07-02) : les probas chevaux
    # qui alimentent la simulation Plackett-Luce des combinés sont capées à
    # 1.55 × la proba marché dé-viguée (même seuil que le gate value bet) sur les
    # cotes ≥ 4. Mesuré : conviction modèle >1.1× le marché → ROI −42.9% (pire que
    # base −19.7%) ; les combos d'outsiders héritaient de probas sur-évaluées que
    # le gate 1.55 ne filtrait qu'en Simple Gagnant.
    combo_market_cap: bool = field(default_factory=lambda: _env_bool("BT_COMBO_MARKET_CAP", True))
    # GATE D'ÉMISSION PAR BANDE D'EV (audit ROI 2026-07-02) : une bande d'EV au ROI
    # réel shrinké NÉGATIF (multiplier < 1.0, K=60) ne produit PLUS de value bet
    # (émission refusée, pas juste rétrogradée) et les paris spéculatifs -EV des
    # plans y sont écartés. Mesuré sur 12 432 paris : bandes 0.10-0.35 = ROI +1.7/+2.7%,
    # bande <0 = −21%, bande >0.60 = −21% → on n'émet que là où l'algo GAGNE.
    ev_band_gate: bool = field(default_factory=lambda: _env_bool("BT_EV_BAND_GATE", True))
    # Temperature ajustée par fit 1-D sur NLL held-out au lieu du ratchet asymétrique.
    temp_fit: bool = field(default_factory=lambda: _env_bool("BT_TEMP_FIT"))
    # ── Calibration isotone CENTRÉE (CIR) — ACTIF PAR DÉFAUT (2026-08-31) ────
    # L'isotone classique est une fonction EN ESCALIER : la courbe prod avait 62
    # points pour 31 `y` distincts, tout x ∈ [0.0363, 0.0470] tombant sur 0.042435.
    # Deux chevaux d'une même course à 25 % d'écart de proba modèle ressortaient
    # donc avec la MÊME proba calibrée, donc la même « cote juste ». Mesuré sur
    # 7 jours : 10.99 probas distinctes en brut pour 11.06 partants → 6.70 après
    # calibration, 96 % des courses avec au moins un doublon.
    # CIR (Oron & Flournoy 2017) réduit chaque palier à son centroïde et interpole
    # entre centres → courbe strictement croissante. Mesuré sur held-out groupé par
    # course (612 courses) : logloss 0.29825 → 0.28823, Brier 0.08181 → 0.08102,
    # ECE 0.03449 → 0.02572, discrimination 68.9 % → 99.6 % des partants.
    # À noter : l'isotone classique faisait PIRE que pas de calibration du tout
    # (logloss brut 0.28856). Rollback ciblé : BT_CIR_CALIBRATION=0.
    cir_calibration: bool = field(default_factory=lambda: _env_bool("BT_CIR_CALIBRATION", True))
    # ── Ranking (précision du classement affiché) ────────────────────────────
    # Mélange un score LGBMRanker (lambdarank, groupé par course) dans l'ORDRE
    # d'arrivée prédit (rang_predit) UNIQUEMENT — n'affecte PAS les probas/EV
    # (calibrées). Validé offline : +~0.8pt top1 / 3118 courses holdout (non sig
    # p~0.11), neutre top3/ndcg. Réversible. Nécessite un modèle entraîné AVEC ranker.
    ranker_blend: bool = field(default_factory=lambda: _env_bool("BT_RANKER_BLEND"))
    ranker_blend_weight: float = field(default_factory=lambda: _env_float("BT_RANKER_BLEND_WEIGHT", 1.0))
    # ── Gate marché (diagnostic 2026-08-20) ──────────────────────────────────
    # Refuse la promotion d'un modèle dont le CLASSEMENT intra-course ne bat pas
    # un simple `ORDER BY cote_pmu` sur le même hold-out (cf. ml/ranking_metrics).
    #
    # DÉFAUT ON depuis le 2026-09-01. Il était OFF pour une raison explicite —
    # « AUCUN modèle actuel ne passe ce gate : 0,7340 contre 0,7351 pour la cote ;
    # l'activer gèlerait le modèle indéfiniment » — et cette raison a disparu.
    #
    # Depuis la bascule sur la fenêtre de 12 mois (v520, 2026-08-25), l'avantage sur
    # le marché est positif sur HUIT versions consécutives :
    #   v520 +0.0198  v521 +0.0197  v522 +0.0200  v523 +0.0199
    #   v524 +0.0192  v525 +0.0201  v526 +0.0188  v527 +0.0190
    # Minimum 0.0188, contre une marge de 0.0. Activer n'aurait bloqué AUCUNE de ces
    # huit nuits : c'est une protection pure, sans effet sur le régime actuel.
    #
    # Ce qu'elle empêche est le seul scénario qui compte : un modèle qui repasserait
    # sous la cote sans que rien ne l'arrête. Les 513 versions d'avant v520 l'ont fait
    # sans qu'aucune alerte se déclenche, parce que le gate ne confrontait le
    # challenger qu'au champion précédent, jamais au marché.
    #
    # ⚠ Si le delta redevenait durablement négatif, ce gate FIGERAIT le modèle (blocage
    # de 48 jours de l'audit 2026-08-16). Le rapport nocturne remonte le delta chaque
    # nuit : c'est lui qui doit alerter avant que le gel ne s'installe. Repli immédiat
    # sans redéploiement : BT_MARKET_GATE=0 dans l'environnement.
    market_gate: bool = field(default_factory=lambda: _env_bool("BT_MARKET_GATE", True))
    # Marge exigée quand le gate est actif. 0.0 = il suffit d'égaler la cote.
    market_gate_margin: float = field(default_factory=lambda: _env_float("BT_MARKET_GATE_MARGIN", 0.0))

    def as_dict(self) -> dict:
        return {
            "train_prerace_only": self.train_prerace_only,
            "group_split": self.group_split,
            "calib_guard": self.calib_guard,
            "devig_gates": self.devig_gates,
            "staking_safe": self.staking_safe,
            "kelly_oos_shrink": self.kelly_oos_shrink,
            "bankroll_cap_frac": self.bankroll_cap_frac,
            "roi_deploy_gate": self.roi_deploy_gate,
            "oos_weights": self.oos_weights,
            "calib_on_raw": self.calib_on_raw,
            "collapse_longshot": self.collapse_longshot,
            "combo_ev_none": self.combo_ev_none,
            "ev_band_gate": self.ev_band_gate,
            "combo_market_cap": self.combo_market_cap,
            "temp_fit": self.temp_fit,
            "cir_calibration": self.cir_calibration,
            "ranker_blend": self.ranker_blend,
            "ranker_blend_weight": self.ranker_blend_weight,
            "market_gate": self.market_gate,
            "market_gate_margin": self.market_gate_margin,
        }


FLAGS = AlgoFlags()


def devig_field(cotes: list[float]) -> float:
    """Overround (somme des probas implicites) d'un champ de cotes décimales.

    Fonction PURE, testable. Permet de dé-vigger une proba implicite :
        p_fair = (1/cote) / devig_field(toutes_les_cotes_du_champ)
    Retourne 1.0 si pas de cotes valides (→ neutre, pas de division parasite).
    """
    implied = [1.0 / c for c in cotes if c and c > 1.0]
    s = sum(implied)
    return s if s > 0 else 1.0
