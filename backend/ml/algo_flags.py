"""
algo_flags.py — Feature flags pour les corrections d'edge (audit 2026-06-14).

Toutes les corrections RISQUÉES de l'algo (qui changent les probas, la sélection
des value bets, le staking ou le modèle déployé) sont gardées par un flag ici,
DÉSACTIVÉ PAR DÉFAUT. Rien ne change en prod tant qu'un flag n'est pas mis à true
via variable d'environnement → déploiement en shadow/canary sans risque.

Cause racine corrigée (voir memory blackturf-edge-rootcause / tasks audit) :
le système montrait +150% in-sample mais -52% out-of-sample à cause de fuites
(leakage), d'un edge qui n'était que le marché re-encodé, et d'un staking non gardé.

Usage :
    from ml.algo_flags import FLAGS
    if FLAGS.devig_gates:
        ...  # nouveau chemin corrigé
    else:
        ...  # comportement historique inchangé

Activation (exemple, à mettre dans l'env du backend) :
    BT_DEVIG_GATES=1
    BT_TRAIN_PRERACE_ONLY=1
    BT_CALIB_GUARD=1
    BT_GROUP_SPLIT=1
    BT_STAKING_SAFE=1
    BT_ROI_DEPLOY_GATE=1

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
    # ── Anti-leakage (modèle / calibration) ──────────────────────────────────
    # Entraînement uniquement sur features figées AVANT le départ
    # (fm.computed_at < c.date_heure), comme meta_learner. Réduit la fuite des
    # features backfillées post-course. Change le set d'entraînement → flag.
    train_prerace_only: bool = field(default_factory=lambda: _env_bool("BT_TRAIN_PRERACE_ONLY"))
    # Split train/test/OOF/walk-forward PAR COURSE (course_id), pas par cheval.
    # Évite la fuite des frères de course. Change le modèle déployé → flag.
    group_split: bool = field(default_factory=lambda: _env_bool("BT_GROUP_SPLIT"))
    # cote_calibration n'apprend que sur prédictions pré-départ non-backfill.
    calib_guard: bool = field(default_factory=lambda: _env_bool("BT_CALIB_GUARD"))

    # ── Sélection value bets ─────────────────────────────────────────────────
    # Dé-vig le marché (normalise 1/cote sur le champ) avant les gates/EV.
    # Change quels paris sont recommandés → flag.
    devig_gates: bool = field(default_factory=lambda: _env_bool("BT_DEVIG_GATES"))

    # ── Staking ──────────────────────────────────────────────────────────────
    # Kelly shrinké par l'edge OOS + cap bankroll dur + désactive le dump
    # "gain target" qui jette Kelly. Change les mises → flag.
    staking_safe: bool = field(default_factory=lambda: _env_bool("BT_STAKING_SAFE"))
    # Fraction de Kelly appliquée quand staking_safe est actif (shrink global
    # tant que l'edge OOS n'est pas prouvé positif). 0.10 = très prudent.
    kelly_oos_shrink: float = field(default_factory=lambda: _env_float("BT_KELLY_OOS_SHRINK", 0.10))
    # Cap dur de l'exposition par course en fraction du bankroll.
    bankroll_cap_frac: float = field(default_factory=lambda: _env_float("BT_BANKROLL_CAP_FRAC", 0.03))

    # ── Gate de déploiement ──────────────────────────────────────────────────
    # Refuse de promouvoir un modèle/poids si le ROI held-out < 0 ou edge_ok faux.
    roi_deploy_gate: bool = field(default_factory=lambda: _env_bool("BT_ROI_DEPLOY_GATE"))
    # Poids de paris appris depuis profil_run_log OOS réel, pas le backtest in-sample.
    oos_weights: bool = field(default_factory=lambda: _env_bool("BT_OOS_WEIGHTS"))

    # ── Batch 2 : boucle auto-apprenante honnête ─────────────────────────────
    # Calibrations (isotonic top1/top3, longshot, cote) fittées sur la proba RAW
    # modèle (colonnes proba_*_raw, migration 0024) au lieu de la proba déjà
    # calibrée → casse la boucle fermée qui chasse son propre résidu. NÉCESSITE
    # d'avoir appliqué la migration 0024 ET predict_course écrit alors les raw.
    calib_on_raw: bool = field(default_factory=lambda: _env_bool("BT_CALIB_ON_RAW"))
    # Empile une seule correction favori-longshot : si actif, on NE ré-applique
    # PAS longshot_calibration après le blend marché (le blend + isotonic suffisent)
    # → fin du triple-comptage qui écrasait l'edge quand le modèle a raison.
    collapse_longshot: bool = field(default_factory=lambda: _env_bool("BT_COLLAPSE_LONGSHOT"))
    # combo_bets : EV=None pour les paris non-Simple (l'EV trj/p_market vs p_model
    # était mécaniquement positive dès que modèle>marché). Dimensionnés à plat.
    combo_ev_none: bool = field(default_factory=lambda: _env_bool("BT_COMBO_EV_NONE"))
    # Temperature ajustée par fit 1-D sur NLL held-out au lieu du ratchet asymétrique.
    temp_fit: bool = field(default_factory=lambda: _env_bool("BT_TEMP_FIT"))
    # ── Ranking (précision du classement affiché) ────────────────────────────
    # Mélange un score LGBMRanker (lambdarank, groupé par course) dans l'ORDRE
    # d'arrivée prédit (rang_predit) UNIQUEMENT — n'affecte PAS les probas/EV
    # (calibrées). Validé offline : +~0.8pt top1 / 3118 courses holdout (non sig
    # p~0.11), neutre top3/ndcg. Réversible. Nécessite un modèle entraîné AVEC ranker.
    ranker_blend: bool = field(default_factory=lambda: _env_bool("BT_RANKER_BLEND"))
    ranker_blend_weight: float = field(default_factory=lambda: _env_float("BT_RANKER_BLEND_WEIGHT", 1.0))

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
            "temp_fit": self.temp_fit,
            "ranker_blend": self.ranker_blend,
            "ranker_blend_weight": self.ranker_blend_weight,
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
