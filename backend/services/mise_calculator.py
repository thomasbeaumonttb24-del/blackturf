"""
MiseCalculator — Moteur de recommandation personnalisée BlackTurf.
Génère un plan de mise structuré en 3 niveaux (sécurité / rendement / coup)
selon le montant entré et le profil de risque utilisateur.
"""
from dataclasses import dataclass, field
from typing import Optional
import math


# ─────────────────────────────────────────────────────────────
# Allocations par profil (sec / rend / coup)
# ─────────────────────────────────────────────────────────────
PROFIL_ALLOCATION = {
    "conservateur": (0.60, 0.30, 0.10),
    "equilibre":    (0.30, 0.40, 0.30),
    "agressif":     (0.10, 0.30, 0.60),
}

# Montant minimum PMU par type de pari
MISE_MIN = {
    "Simple Gagnant":   1.0,
    "Simple Placé":     1.0,
    "Couplé Gagnant":   1.0,
    "Couplé Placé":     1.0,
    "2sur4":            1.0,
    "Trio":             1.0,
    "Tiercé Désordre":  1.0,
    "Tiercé Ordre":     1.0,
    "Quarté+":          1.5,
    "Quinté+ Flexi":    2.0,
}

# Multiplicateur de gain estimé (hors mise)
# Formule : rapport_net ≈ base × produit_cotes^exposant
# Ces valeurs sont conservatrices (PMU prélève 15-20%)
def _rapport_place(cote: float) -> float:
    """Cote placé PMU ≈ cote gagnant / 4 (min 1.1)."""
    return max(1.1, (cote - 1) / 4 + 1)

def _rapport_couple_gagnant(c1: float, c2: float) -> float:
    return max(2.0, c1 * c2 * 0.55)

def _rapport_couple_place(c1: float, c2: float) -> float:
    return max(1.5, c1 * c2 * 0.18)

def _rapport_2sur4(c1: float, c2: float, c3: float, c4: float) -> float:
    moy = (c1 + c2 + c3 + c4) / 4
    return max(3.0, moy ** 1.6 * 0.9)

def _rapport_trio(c1: float, c2: float, c3: float) -> float:
    return max(5.0, c1 * c2 * c3 * 0.45)

def _rapport_tierce_desordre(c1: float, c2: float, c3: float) -> float:
    return max(8.0, c1 * c2 * c3 * 0.75)

def _rapport_tierce_ordre(c1: float, c2: float, c3: float) -> float:
    return max(15.0, c1 * c2 * c3 * 2.0)

def _rapport_quarte(c1: float, c2: float, c3: float, c4: float) -> float:
    return max(20.0, c1 * c2 * c3 * c4 * 0.3)

def _rapport_quinte_flexi(pct: float) -> float:
    return max(50.0, 1200.0 * pct)


# ─────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────
@dataclass
class ChevPred:
    numero: int
    nom: str
    cote_pmu: float
    proba_top3: float
    proba_top1: float
    ev: Optional[float] = None


@dataclass
class PariRec:
    type: str
    chevaux: list[dict]       # [{"numero": 7, "nom": "..."}]
    mise: float
    gain_potentiel: float
    probabilite: float
    description: str
    ev_estime: float = 0.0
    raisons: list[str] = field(default_factory=list)   # justification complète du pari


@dataclass
class NiveauPlan:
    niveau: str               # securite | rendement | coup
    label: str
    emoji: str
    couleur: str
    montant: float
    pct: int
    paris: list[PariRec] = field(default_factory=list)


@dataclass
class MisePlan:
    montant_total: float
    montant_joue: float
    montant_reserve: float
    ev_global: float
    niveaux: list[NiveauPlan]
    resume_ia: str
    avertissement: str
    kelly_warning: bool = False
    esperance_gain: float = 0.0      # espérance de PROFIT NET en € (Σ mise×EV)
    palier: str = ""                 # micro | petit | moyen | gros
    profil: str = ""                 # conservateur | equilibre | agressif
    mode_adaptatif: str = "normal"   # prudent | normal | offensif (selon heat)
    paris_ecartes: list[dict] = field(default_factory=list)  # candidats rejetés + motif


# ─────────────────────────────────────────────────────────────
# Moteur principal
# ─────────────────────────────────────────────────────────────
NIVEAU_META = {
    "securite":  ("SÉCURITÉ",  "🟢", "#10B981"),
    "rendement": ("RENDEMENT", "🔵", "#3B82F6"),
    "surprise":  ("SURPRISES", "🟡", "#F59E0B"),
    "coup":      ("GROS LOT",  "🔴", "#EF4444"),
}

# ─────────────────────────────────────────────────────────────
# Paliers de MONTANT — changent la STRATÉGIE, pas juste le split.
#   max_bets   : plafond du nb de paris (moins de paris, plus de conviction)
#   min_stake  : mise plancher par pari (€) → tue le saupoudrage de petits 2€
#   favor_value: petite mise → viser une grosse cote PROBABLE (edge réel) au
#                lieu de saupoudrer ; on récompense le rapport élevé à valeur.
#   cap_spec   : part max du montant allouable aux paris SPÉCULATIFS (EV ≤ 0,
#                "coups" gros lot sans value avérée).
# ─────────────────────────────────────────────────────────────
MONTANT_PALIERS = [
    (10,        {"nom": "micro", "max_bets": 2, "min_stake": 2, "favor_value": True,  "cap_spec": 1.0}),
    (30,        {"nom": "petit", "max_bets": 3, "min_stake": 3, "favor_value": True,  "cap_spec": 0.6}),
    (100,       {"nom": "moyen", "max_bets": 4, "min_stake": 4, "favor_value": False, "cap_spec": 0.4}),
    (10 ** 9,   {"nom": "gros",  "max_bets": 5, "min_stake": 5, "favor_value": False, "cap_spec": 0.25}),
]


def _palier(montant: int) -> dict:
    for seuil, cfg in MONTANT_PALIERS:
        if montant < seuil:
            return cfg
    return MONTANT_PALIERS[-1][1]


# ─────────────────────────────────────────────────────────────
# Profils de risque — agissent sur la SÉLECTION (quels paris) ET l'allocation.
#   cote_max     : cote max autorisée dans un pari (cape les longshots)
#   min_proba    : proba de gain minimale d'un pari retenu
#   ev_min       : seuil d'EV d'entrée (agressif accepte EV légèrement négative
#                  si edge réel / coup crédible ; conservateur exige EV franche+)
#   max_coup     : nb max de paris spéculatifs (gros lot sans value avérée)
#   bets_factor  : module le plafond de paris du palier (prudent → moins)
#   risk_pref    : tilt de l'allocation Kelly par niveau (où va l'argent)
# ─────────────────────────────────────────────────────────────
# `types`    : familles de paris AUTORISÉES pour le profil (None = toutes). C'est
#              ce qui rend chaque profil une MÉTHODE DE JEU distincte.
# `objectif` : critère de classement des candidats —
#              "proba" (gagner souvent, prudent) / "ev" (équilibre) /
#              "gain"  (gros gain pour petite mise : outsiders à valeur, risqué).
# Règle commune de PROFITABILITÉ (dans _select_conviction) : on ne retient JAMAIS un
# pari à la fois EV<0 ET sans edge (edge≤0) — sinon on donne sa mise au PMU. On parie
# donc soit du +EV, soit de la VALEUR détectée par l'IA (modèle > marché).
# `min_stake_factor` : multiplie la mise PLANCHER du palier. <1 = "petites mises
#   sur PLUSIEURS combinaisons" (équilibré/risqué saupoudrent un large spectre PMU) ;
#   =1 = mises franches concentrées (prudent).
PROFIL_CONFIG = {
    # PRUDENT — privilégie le PLACÉ : Simple Placé, Duo Placé (Couplé Placé), 2/4.
    # Mises prudentes (peu de paris, plancher franc), cotes courtes, gagner souvent.
    "conservateur": {
        "cote_max": 9.0, "min_proba": 0.20, "ev_min": -0.15, "max_coup": 0,
        "bets_factor": 0.9, "min_stake_factor": 1.0,
        "types": {"Simple Placé", "Couplé Placé", "2sur4"},
        "objectif": "proba",
        "risk_pref": {"securite": 1.5, "rendement": 1.0, "surprise": 0.4, "coup": 0.2},
    },
    # NORMAL — cotes un peu plus élevées à PROBABILITÉ réelle. PAS de Simple Placé
    # (le placé sec rapporte trop peu) : on joue le duo gagnant, le couplé placé, le
    # 2/4 et le trio. PETITES mises réparties sur PLUSIEURS combinaisons (spectre PMU).
    "equilibre": {
        "cote_max": 30.0, "min_proba": 0.04, "ev_min": -0.08, "max_coup": 2,
        "bets_factor": 1.6, "min_stake_factor": 0.55,
        "types": {"Couplé Placé", "Couplé Gagnant", "2sur4", "Trio", "Simple Gagnant"},
        "objectif": "ev",
        "risk_pref": {"securite": 0.8, "rendement": 1.2, "surprise": 1.0, "coup": 0.7},
    },
    # RISQUÉ — vise les GROSSES cotes : plusieurs chevaux en gagnant grosse cote,
    # duo gagnant, trios et jackpots désordre (Tiercé/Quarté+/Quinté+). PAS de Simple
    # Placé. Beaucoup de PETITES mises sur un large spectre de combinaisons.
    "agressif": {
        "cote_max": 90.0, "min_proba": 0.0, "ev_min": -0.25, "max_coup": 4,
        "bets_factor": 2.0, "min_stake_factor": 0.5,
        "types": {"Couplé Gagnant", "2sur4", "Trio", "Simple Gagnant",
                  "Tiercé Désordre", "Quarté+ Désordre", "Quinté+ Désordre"},
        "objectif": "gain",
        "risk_pref": {"securite": 0.3, "rendement": 0.8, "surprise": 1.5, "coup": 1.9},
    },
}


def _effective_config(profil: str, heat: float) -> dict:
    """Profil EFFECTIF = config de base MODULÉE par `heat` ∈ [-1,+1], le thermostat
    adaptatif (calibration du modèle + ROI récent réel).

    heat > 0 (modèle chaud : bien calibré + gagnant récemment) → on assouplit :
        seuil EV plus bas, cotes plus hautes autorisées, +1 coup, tilt vers le risqué.
    heat < 0 (modèle froid : mal calibré / perdant) → on durcit pour TOUS les
        profils : EV plus exigeante, cotes capées, moins de coups, repli sécurité.
    """
    base = PROFIL_CONFIG.get(profil, PROFIL_CONFIG["equilibre"])
    h = max(-1.0, min(1.0, float(heat)))
    cfg = {
        "cote_max":  max(4.0, base["cote_max"] * (1.0 + 0.30 * h)),
        "min_proba": max(0.0, base["min_proba"] * (1.0 - 0.30 * h)),
        "ev_min":    base["ev_min"] - 0.04 * h,
        "max_coup":  max(0, base["max_coup"] + (1 if h > 0.5 else 0) - (1 if h < -0.5 else 0)),
        "bets_factor": base["bets_factor"],
        "min_stake_factor": base.get("min_stake_factor", 1.0),  # <1 = plus de petites mises
        "types":     base.get("types"),          # familles de paris du profil (None = toutes)
        "objectif":  base.get("objectif", "ev"), # critère de classement des candidats
    }
    # Tilt de risque modulé : froid → renforce la sécurité, écrase surprise/coup.
    rp = {}
    for niv, w in base["risk_pref"].items():
        if niv == "securite":
            rp[niv] = w * (1.0 - 0.20 * h)
        else:
            rp[niv] = max(0.05, w * (1.0 + 0.30 * h))
    cfg["risk_pref"] = rp
    return cfg


def _mode_label(heat: float) -> str:
    if heat >= 0.33:
        return "offensif"
    if heat <= -0.33:
        return "prudent"
    return "normal"


def generer_plan(
    montant: float,
    profil: str,
    predictions: list[dict],
    course_info: dict,
    bankroll: Optional[float] = None,
    roi_weights: Optional[dict] = None,
    heat: float = 0.0,
    signal_mults: Optional[dict] = None,
    facteurs_chevaux: Optional[dict] = None,
) -> MisePlan:
    """Plan de mise INTELLIGENT & ADAPTATIF — relie analyse, apprentissage, résultats.

    Principe : le MONTANT définit la stratégie (palier micro/petit/moyen/gros) ; le
    PROFIL (conservateur/equilibre/agressif) définit QUELS paris (gates cote/proba/EV
    + nb de coups) et OÙ va l'argent (tilt Kelly par niveau) ; le `heat` ∈ [-1,+1]
    est un THERMOSTAT adaptatif qui durcit/assouplit TOUS les profils selon la santé
    réelle du modèle (calibration brier) et le ROI récent observé.

    - Analyse : probas/edge RÉELS (simulation Plackett-Luce), EV = cote×proba−1.
    - Apprentissage : `heat` dérivé de la calibration (race_learning_log).
    - Résultats : `roi_weights` (ROI net réel par type, bankroll_entries) pondère la
      sélection ; `heat` intègre le ROI récent → après une série perdante le système
      devient prudent même en profil agressif ; après une bonne série, plus offensif.
    Aucune valeur inventée : signaux absents → neutre (poids 1.0, heat 0).
    """
    from ml.combo_bets import enumerate_bet_candidates

    profil = profil if profil in PROFIL_CONFIG else "equilibre"
    montant = max(2, int(round(float(montant))))            # euro, min 2
    kelly_warn = bankroll is not None and bankroll > 0 and montant > bankroll * 0.05
    palier = _palier(montant)
    roi_weights = roi_weights or {}
    heat = max(-1.0, min(1.0, float(heat or 0.0)))
    cfg = _effective_config(profil, heat)

    preds = []
    for p in predictions:
        if p.get("non_partant"):
            continue
        preds.append({
            "numero": p["numero"],
            "nom": p.get("nom_cheval") or p.get("nom") or f"N°{p['numero']}",
            "proba_top1": p.get("proba_top1"),
            "proba_top3": p.get("proba_top3"),
            "cote_pmu": p.get("cote_pmu"),
        })

    cands = enumerate_bet_candidates(preds, course_info)
    if not cands:
        return _plan_vide(montant, profil)

    selected = _select_conviction(cands, montant, palier, cfg, roi_weights, signal_mults)
    if not selected:
        return _plan_vide(montant, profil)

    _allocate_kelly(selected, montant, palier, cfg)         # remplit "mise" (int €)
    ecartes = _paris_ecartes(cands, selected, cfg)
    return _assemble_plan(selected, montant, palier, kelly_warn, profil, heat,
                          facteurs_chevaux=facteurs_chevaux, ecartes=ecartes)


def _is_credible_coup(c: dict) -> bool:
    """Coup crédible = outsider à VRAIE valeur : modèle > marché (edge>0) ET gros
    rapport (≥6). Justifie de jouer un pari même à EV faiblement négative."""
    return c.get("edge", 0.0) > 0 and c["rapport_estime"] >= 6.0


def _is_speculative(c: dict) -> bool:
    """Pari spéculatif = joué pour le gros lot sans value avérée (EV ≤ 0 et pas
    de coup crédible). Soumis au plafond cap_spec + quota PROFIL_MAX_COUP."""
    return c["ev"] <= 0 and not _is_credible_coup(c)


def _bet_cote_max(c: dict) -> float:
    """Cote la plus élevée parmi les chevaux d'un pari (mesure de risque du pari)."""
    cotes = [float(h.get("cote") or 0.0) for h in c.get("chevaux", [])]
    return max(cotes) if cotes else 0.0


def _select_conviction(
    cands: list[dict], montant: int, palier: dict, cfg: dict, roi_weights: dict,
    signal_mults: Optional[dict] = None,
) -> list[dict]:
    """Sélectionne PEU de paris à FORTE conviction (EV × proba × edge × ROI passé),
    filtrés par les GATES du profil EFFECTIF (cote_max, min_proba, ev_min, max_coup).
    Profitabilité d'abord ; concentre. Le profil change donc VRAIMENT quels paris.
    """
    # Mise plancher EFFECTIVE : le profil peut la réduire (<1) pour saupoudrer de
    # PETITES mises sur PLUSIEURS combinaisons (équilibré/risqué), ou la garder
    # franche (prudent). Plancher PMU = 1€.
    min_stake = max(1, round(palier["min_stake"] * cfg.get("min_stake_factor", 1.0)))
    max_feasible = max(1, montant // min_stake)             # chaque pari ≥ min_stake
    base_max = max(1, round(palier["max_bets"] * cfg.get("bets_factor", 1.0)))
    max_bets = min(base_max, max_feasible, len(cands))
    max_coup = cfg["max_coup"]
    cote_max = cfg["cote_max"]
    min_proba = cfg["min_proba"]
    ev_min = cfg["ev_min"]
    allowed_types = cfg.get("types")                         # None = toutes
    objectif = cfg.get("objectif", "ev")
    # Spectre large de combinaisons : on tolère 2 paris du même type (ex. 2 trios
    # différents) quand le profil saupoudre, pour couvrir plus de combinaisons PMU.
    max_per_type = 1 if max_bets <= 3 else (3 if cfg.get("min_stake_factor", 1.0) < 0.7 else 2)

    def roi_w(c):
        return float(roi_weights.get(c["type_pari"], 1.0))

    def sig_factor(c):
        """Multiplicateur appris PAR SIGNAL × PROFIL (moyenne des chevaux du pari) :
        favorise les paris portés par des signaux historiquement gagnants POUR CE
        PROFIL (ex. premier déferré boosté en conservateur, ignoré en agressif).
        Neutre (1.0) si pas de calibration signal chargée."""
        if not signal_mults:
            return 1.0
        ms = [signal_mults.get(int(h.get("numero")), 1.0)
              for h in c.get("chevaux", []) if h.get("numero") is not None]
        return float(sum(ms) / len(ms)) if ms else 1.0

    def conviction(c):
        """Classement selon l'OBJECTIF du profil (× ROI réel passé du type × signal)."""
        rw = roi_w(c) * sig_factor(c)
        if objectif == "proba":
            # PRUDENT : gagner souvent. Proba d'abord, EV en bonus léger.
            return (c["proba_gain"] + max(c["ev"], 0.0) * 0.2) * rw
        if objectif == "gain":
            # RISQUÉ : gros gain pour petite mise. Retour attendu (rapport×proba),
            # bonus aux outsiders à VALEUR (edge>0 sur grosse cote) détectés par l'IA.
            payout = c["rapport_estime"] * c["proba_gain"]   # espérance de retour (×mise)
            bonus = 1.30 if (c.get("edge", 0.0) > 0 and c["rapport_estime"] >= 8) else 1.0
            return payout * bonus * rw
        # ÉQUILIBRE : compromis EV × proba × edge.
        base = (max(c["ev"], 0.0) * 0.6 + c["proba_gain"] * 0.5
                + max(c.get("edge", 0.0), 0.0) * 0.8)
        if palier["favor_value"] and c.get("edge", 0.0) > 0:
            base += min(c["rapport_estime"], 30.0) / 100.0
        return base * rw

    def passes_gates(c):
        if allowed_types is not None and c["type_pari"] not in allowed_types:
            return False                                     # hors méthode du profil
        if _bet_cote_max(c) > cote_max:                      # longshot hors profil
            return False
        if c["proba_gain"] < min_proba:                      # trop improbable
            return False
        # RÈGLE DE PROFITABILITÉ : jamais un pari à la fois -EV ET sans edge (= don
        # au PMU). On parie du +EV OU de la valeur détectée (modèle > marché).
        if c["ev"] < 0 and c.get("edge", 0.0) <= 0:
            return False
        # Seuil EV propre au profil (sauf coup crédible : value outsider à gros rapport).
        if c["ev"] < ev_min and not _is_credible_coup(c):
            return False
        return True

    ranked = sorted(cands, key=conviction, reverse=True)
    selected: list[dict] = []
    type_count: dict[str, int] = {}
    n_coup = 0

    for c in ranked:
        if len(selected) >= max_bets:
            break
        if not passes_gates(c):
            continue
        spec = _is_speculative(c)
        if spec and n_coup >= max_coup:
            continue
        if type_count.get(c["type_pari"], 0) >= max_per_type:
            continue
        c["_roi_w"] = roi_w(c)
        c["_sig"] = sig_factor(c)
        selected.append(c)
        type_count[c["type_pari"]] = type_count.get(c["type_pari"], 0) + 1
        if spec:
            n_coup += 1

    # Filet : aucune value qui passe les gates → 1 pari le plus SÛR (meilleure proba),
    # en restant si possible dans la méthode du profil. Sans plan vide. Aucune invention.
    if not selected:
        pool = [c for c in cands
                if (allowed_types is None or c["type_pari"] in allowed_types)
                and _bet_cote_max(c) <= cote_max]
        pool = pool or [c for c in cands if _bet_cote_max(c) <= cote_max] or cands
        safe = max(pool, key=lambda c: c["proba_gain"])
        safe["_roi_w"] = roi_w(safe)
        safe["_sig"] = sig_factor(safe)
        selected = [safe]
    return selected


def _allocate_kelly(selected: list[dict], montant: int, palier: dict, cfg: dict) -> None:
    """Dispatch `montant` (€ entiers) par fraction de KELLY réelle (ev/(cote-1))
    tiltée par le profil EFFECTIF (risk_pref) et le ROI passé. min_stake plancher ;
    plafond sur les paris spéculatifs (cap_spec). Total == montant exactement."""
    rp = cfg["risk_pref"]
    # Même plancher effectif que la sélection (petites mises multiples si profil le veut).
    min_stake = max(1, round(palier["min_stake"] * cfg.get("min_stake_factor", 1.0)))

    def weight(c):
        b = max(c["rapport_estime"] - 1.0, 0.1)
        f = max(c["ev"] / b, 0.0)                # fraction de Kelly pleine
        c["_kelly_f"] = round(f, 4)              # trace pour la justification du pari
        if f <= 0:                              # coup à upside : poids plancher
            f = 0.02
        return max(f * rp.get(c["niveau"], 1.0) * c.get("_roi_w", 1.0), 1e-3)

    weights = [weight(c) for c in selected]
    n = len(selected)

    # Sécurité : si min_stake×n dépasse le montant, garder les meilleurs poids.
    if min_stake * n > montant and n > 1:
        order = sorted(range(n), key=lambda i: weights[i], reverse=True)
        keep = max(1, montant // min_stake)
        keep_idx = set(order[:keep])
        selected[:] = [selected[i] for i in range(n) if i in keep_idx]
        weights = [weight(c) for c in selected]
        n = len(selected)

    base = min_stake * n
    reste = max(0, montant - base)
    total_w = sum(weights)
    extra = [int(reste * w / total_w) for w in weights] if total_w > 0 else [0] * n
    leftover = reste - sum(extra)
    order = sorted(range(n), key=lambda i: weights[i], reverse=True)
    for k in range(leftover):
        extra[order[k % n]] += 1
    for i, c in enumerate(selected):
        c["mise"] = min_stake + extra[i]

    _apply_spec_cap(selected, montant, palier)


def _apply_spec_cap(selected: list[dict], montant: int, palier: dict) -> None:
    """Plafonne la part totale misée sur les paris SPÉCULATIFS (EV≤0) à cap_spec ×
    montant, en transférant l'excédent vers les paris fiables (EV>0). Garde le
    plancher min_stake. Conserve le total. Best-effort (petit n)."""
    cap = palier["cap_spec"]
    if cap >= 1.0:
        return
    min_stake = palier["min_stake"]
    spec_idx = [i for i, c in enumerate(selected) if c["ev"] <= 0]
    safe_idx = [i for i, c in enumerate(selected) if c["ev"] > 0]
    if not spec_idx or not safe_idx:
        return
    max_spec = int(montant * cap)
    spec_total = sum(selected[i]["mise"] for i in spec_idx)
    if spec_total <= max_spec:
        return

    to_move = spec_total - max_spec
    # Réduire les spéculatifs (mise desc) jusqu'au plancher min_stake.
    for i in sorted(spec_idx, key=lambda i: selected[i]["mise"], reverse=True):
        if to_move <= 0:
            break
        reducible = selected[i]["mise"] - min_stake
        cut = min(reducible, to_move)
        selected[i]["mise"] -= cut
        to_move -= cut
    moved = (spec_total - max_spec) - to_move
    # Transférer l'euro coupé sur les paris fiables (mise desc).
    safe_order = sorted(safe_idx, key=lambda i: selected[i]["mise"], reverse=True)
    k = 0
    while moved > 0 and safe_order:
        selected[safe_order[k % len(safe_order)]]["mise"] += 1
        moved -= 1
        k += 1


# Pourquoi ce TYPE de pari sert ce PROFIL — pédagogie de la méthode de jeu.
_TYPE_RAISON_PROFIL = {
    # PRUDENT — placé / duo placé / 2sur4.
    ("conservateur", "Simple Placé"):  "Placé = le pari qui tombe le plus souvent — socle du profil prudent (faible variance).",
    ("conservateur", "Couplé Placé"):  "Duo placé : 2 chevaux dans les 3 premiers — fréquence élevée, rapport supérieur au placé sec.",
    ("conservateur", "2sur4"):         "2sur4 : 2 des 4 choisis dans le top-4 — tolère une défaillance, parfait pour jouer prudent.",
    # NORMAL — cotes moyennes à proba, plusieurs petites combinaisons, pas de placé sec.
    ("equilibre", "Simple Gagnant"):   "Gagnant à cote moyenne-haute : meilleure espérance (EV) détectée, vise une chance réelle.",
    ("equilibre", "Couplé Gagnant"):   "Duo gagnant : rapport rehaussé pour une proba encore solide — petite mise, bon rendement.",
    ("equilibre", "Couplé Placé"):     "Duo placé sécurisant le ticket — combiné aux paris à rendement (petite mise répartie).",
    ("equilibre", "2sur4"):            "2sur4 : large filet sur le top-4 — une des combinaisons du spectre joué en petite mise.",
    ("equilibre", "Trio"):             "Trio désordre : 3 chevaux dans l'ordre des arrivants — gros rapport pour une petite mise.",
    # RISQUÉ — grosses cotes gagnant, duo gagnant, trios, jackpots désordre.
    ("agressif", "Simple Gagnant"):    "Gagnant GROSSE cote : gain élevé visé sur un cheval que le modèle place au-dessus du marché.",
    ("agressif", "Couplé Gagnant"):    "Duo gagnant : rapport multiplié, le modèle voit ces 2 chevaux au-dessus du marché.",
    ("agressif", "2sur4"):             "2sur4 avec outsider : place une grosse cote dans le top-4 — petite mise, gros levier.",
    ("agressif", "Trio"):              "Trio : 3 chevaux dont une grosse cote — rapport énorme pour une mise minime.",
    ("agressif", "Tiercé Désordre"):   "Tiercé désordre : les 3 premiers sans l'ordre — jackpot visé en petite mise.",
    ("agressif", "Quarté+ Désordre"):  "Quarté+ désordre : 4 premiers sans l'ordre — très gros lot, mise minime assumée.",
    ("agressif", "Quinté+ Désordre"):  "Quinté+ désordre : le gros lot du jour — petite mise pour viser très haut.",
}


def _raisons_pari(c: dict, profil: str, facteurs_chevaux: Optional[dict]) -> list[str]:
    """Justification COMPLÈTE d'un pari retenu : pourquoi ce type pour ce profil,
    valeur détectée, signaux appris, ROI réel passé du type, trace Kelly de la mise.
    Tout dérive de valeurs RÉELLEMENT calculées — aucune raison décorative."""
    raisons: list[str] = []
    # 1. Pourquoi ce type pour ce profil
    r_type = _TYPE_RAISON_PROFIL.get((profil, c["type_pari"]))
    if r_type:
        raisons.append(r_type)
    # 2. Valeur modèle vs marché (edge)
    edge = float(c.get("edge", 0.0) or 0.0)
    if edge > 0.005:
        raisons.append(
            f"Valeur détectée : le modèle estime ce pari {edge*100:.1f} pt au-dessus du marché."
        )
    # 3. Facteurs réels des chevaux (issus de l'analyse par partant)
    if facteurs_chevaux:
        for h in c.get("chevaux", [])[:3]:
            fc = facteurs_chevaux.get(int(h.get("numero", -1)))
            if not fc:
                continue
            pos = [p.get("label", "") for p in fc.get("positifs", [])[:2] if p.get("label")]
            if pos:
                raisons.append(f"N°{h['numero']} {h.get('nom','')} : {' · '.join(pos)}.")
            neg = [n.get("label", "") for n in fc.get("negatifs", [])[:1] if n.get("label")]
            if neg:
                raisons.append(f"N°{h['numero']} — point de vigilance : {neg[0]}.")
    # 4. Signaux appris (profil)
    sig = float(c.get("_sig", 1.0) or 1.0)
    if sig >= 1.10:
        raisons.append(f"Signaux historiquement GAGNANTS pour ce profil (conviction ×{sig:.2f}).")
    elif sig <= 0.90:
        raisons.append(f"Signaux mitigés pour ce profil (conviction ×{sig:.2f}) — mise réduite en conséquence.")
    # 5. ROI réel passé du type de pari
    rw = float(c.get("_roi_w", 1.0) or 1.0)
    if rw >= 1.05:
        raisons.append(f"Ce type de pari a un ROI réel positif sur l'historique (poids ×{rw:.2f}).")
    elif rw <= 0.95:
        raisons.append(f"Ce type de pari a sous-performé sur l'historique (poids ×{rw:.2f}).")
    # 6. Trace Kelly de la mise
    kf = c.get("_kelly_f")
    if kf is not None:
        raisons.append(
            f"Mise {c.get('mise', 0):.0f}€ : fraction de Kelly {kf*100:.1f}% "
            f"(EV {c['ev']*100:+.0f}% / rapport {c['rapport_estime']:.1f}×), ajustée au profil."
        )
    return raisons


def _motif_rejet(c: dict, cfg: dict) -> str:
    """Motif honnête pour lequel un candidat n'a PAS été retenu par ce profil."""
    allowed = cfg.get("types")
    if allowed is not None and c["type_pari"] not in allowed:
        return "Type de pari hors méthode de ce profil."
    if _bet_cote_max(c) > cfg["cote_max"]:
        return f"Cote trop élevée pour ce profil (max {cfg['cote_max']:.0f})."
    if c["proba_gain"] < cfg["min_proba"]:
        return f"Probabilité trop faible ({c['proba_gain']*100:.0f}%) pour ce profil."
    if c["ev"] < 0 and c.get("edge", 0.0) <= 0:
        return "Espérance négative SANS valeur détectée — ce pari donnerait sa mise au PMU."
    if c["ev"] < cfg["ev_min"] and not _is_credible_coup(c):
        return f"EV insuffisante ({c['ev']*100:+.0f}%) pour le seuil du profil."
    return "Conviction inférieure aux paris retenus (place limitée par le palier de mise)."


def _paris_ecartes(cands: list[dict], selected: list[dict], cfg: dict) -> list[dict]:
    """Top candidats NON retenus + motif — transparence sur ce que l'IA écarte et pourquoi."""
    sel_keys = {(c["type_pari"], tuple(sorted(h["numero"] for h in c["chevaux"]))) for c in selected}
    out = []
    for c in sorted(cands, key=lambda x: x["proba_gain"], reverse=True):
        key = (c["type_pari"], tuple(sorted(h["numero"] for h in c["chevaux"])))
        if key in sel_keys:
            continue
        out.append({
            "type": c["type_pari"],
            "chevaux": [{"numero": h["numero"], "nom": h["nom"]} for h in c["chevaux"]],
            "probabilite": c["proba_gain"],
            "ev_estime": c["ev"],
            "motif": _motif_rejet(c, cfg),
        })
        if len(out) >= 4:
            break
    return out


def _assemble_plan(selected: list[dict], montant: int, palier: dict, kelly_warn: bool,
                   profil: str = "equilibre", heat: float = 0.0,
                   facteurs_chevaux: Optional[dict] = None,
                   ecartes: Optional[list[dict]] = None) -> MisePlan:
    """Groupe les paris choisis par niveau → MisePlan (structure attendue par le front)."""
    niveaux_map: dict[str, list[PariRec]] = {}
    ev_pondere = 0.0
    for c in selected:
        mise = c["mise"]
        gain = round(mise * c["rapport_estime"])
        pari = PariRec(
            type=c["type_pari"],
            chevaux=[{"numero": h["numero"], "nom": h["nom"]} for h in c["chevaux"]],
            mise=mise,
            gain_potentiel=gain,
            probabilite=c["proba_gain"],
            description=c["texte_explication"],
            ev_estime=c["ev"],
            raisons=_raisons_pari(c, profil, facteurs_chevaux),
        )
        niveaux_map.setdefault(c["niveau"], []).append(pari)
        ev_pondere += mise * c["ev"]            # espérance de profit net (€)

    niveaux: list[NiveauPlan] = []
    for niv in ("securite", "rendement", "surprise", "coup"):
        paris = niveaux_map.get(niv)
        if not paris:
            continue
        label, emoji, couleur = NIVEAU_META[niv]
        m_niv = sum(p.mise for p in paris)
        niveaux.append(NiveauPlan(
            niveau=niv, label=label, emoji=emoji, couleur=couleur,
            montant=m_niv, pct=round(m_niv / montant * 100), paris=paris,
        ))

    montant_joue = sum(c["mise"] for c in selected)
    nb_paris = len(selected)
    nb_val = sum(1 for c in selected if c.get("edge", 0.0) > 0)
    esp = round(ev_pondere, 2)
    mode = _mode_label(heat)
    profil_label = {"conservateur": "conservateur", "equilibre": "modéré", "agressif": "risqué"}.get(profil, profil)
    mode_txt = {
        "prudent": " · mode adaptatif PRUDENT (modèle en froid / série difficile → repli sécurité)",
        "offensif": " · mode adaptatif OFFENSIF (modèle calibré + en réussite → plus audacieux)",
        "normal": "",
    }[mode]
    resume = (
        f"Profil {profil_label} — {nb_paris} pari{'s' if nb_paris > 1 else ''} ciblé"
        f"{'s' if nb_paris > 1 else ''} (palier {palier['nom']}), mise concentrée de {montant_joue}€"
        + (f", dont {nb_val} à valeur réelle (cote probable)" if nb_val else "")
        + f". Espérance de gain {'+' if esp >= 0 else ''}{esp:.2f}€" + mode_txt + "."
    )
    return MisePlan(
        montant_total=montant,
        montant_joue=montant_joue,
        montant_reserve=montant - montant_joue,
        ev_global=round(ev_pondere / montant, 3) if montant else 0.0,
        niveaux=niveaux,
        resume_ia=resume,
        avertissement="Probabilités estimées par simulation (Plackett-Luce). Mises arrondies à l'euro. Jouez avec modération.",
        kelly_warning=kelly_warn,
        esperance_gain=esp,
        palier=palier["nom"],
        profil=profil,
        mode_adaptatif=mode,
        paris_ecartes=ecartes or [],
    )


# ─────────────────────────────────────────────────────────────
# Plans par tranche
# ─────────────────────────────────────────────────────────────
def _round2(x: float) -> float:
    return round(x * 2) / 2  # arrondi 0.50€


def _pari(type_: str, chevs: list[ChevPred], mise: float, gain: float, proba: float) -> PariRec:
    chev_list = [{"numero": c.numero, "nom": c.nom} for c in chevs]
    nums = " + ".join(f"N°{c.numero}" for c in chevs)
    desc = f"{nums} — {type_}"
    ev_est = (gain / mise - 1) * proba if mise > 0 else 0
    return PariRec(
        type=type_,
        chevaux=chev_list,
        mise=round(mise, 2),
        gain_potentiel=round(gain, 0),
        probabilite=round(proba, 3),
        description=desc,
        ev_estime=round(ev_est, 3),
    )


def _plan_micro(montant: float, chevaux: list[ChevPred], profil: str, kelly_warn: bool) -> MisePlan:
    c = chevaux[0]
    if profil == "agressif":
        gain = montant * c.cote_pmu
        p = _pari("Simple Gagnant", [c], montant, gain, c.proba_top1)
        proba = c.proba_top1
    else:
        gain = montant * _rapport_place(c.cote_pmu)
        p = _pari("Simple Placé", [c], montant, gain, c.proba_top3)
        proba = c.proba_top3

    niveau = NiveauPlan(
        niveau="securite", label="SÉCURITÉ", emoji="🟢", couleur="#10B981",
        montant=montant, pct=100, paris=[p],
    )
    ev = (gain / montant - 1) * proba - (1 - proba)
    return MisePlan(
        montant_total=montant, montant_joue=montant, montant_reserve=0,
        ev_global=round(ev, 3),
        niveaux=[niveau],
        resume_ia=_resume(chevaux, 1),
        avertissement="Mise micro — 1 pari optimisé sur le favori IA.",
        kelly_warning=kelly_warn,
    )


def _plan_simple(montant, sec, rend, coup, chevaux, is_quinte, nb_partants, kelly_warn) -> MisePlan:
    m_sec  = _round2(montant * sec)
    m_rend = _round2(montant * rend)
    m_coup = montant - m_sec - m_rend
    joue = 0.0
    niveaux = []

    # Sécurité — Simple Placé
    if m_sec >= 1.0 and chevaux:
        c = chevaux[0]
        gain = m_sec * _rapport_place(c.cote_pmu)
        niveaux.append(NiveauPlan("securite", "SÉCURITÉ", "🟢", "#10B981", m_sec, int(sec*100),
            paris=[_pari("Simple Placé", [c], m_sec, gain, c.proba_top3)]))
        joue += m_sec

    # Rendement — Couplé Gagnant
    if m_rend >= 1.0 and len(chevaux) >= 2:
        c1, c2 = chevaux[0], chevaux[1]
        gain = m_rend * _rapport_couple_gagnant(c1.cote_pmu, c2.cote_pmu)
        prob = c1.proba_top1 * c2.proba_top1 * 2
        niveaux.append(NiveauPlan("rendement", "RENDEMENT", "🔵", "#3B82F6", m_rend, int(rend*100),
            paris=[_pari("Couplé Gagnant", [c1, c2], m_rend, gain, min(prob, 0.25))]))
        joue += m_rend

    # Coup — Trio (si >2 chevaux)
    if m_coup >= 1.0 and len(chevaux) >= 3:
        c1, c2, c3 = chevaux[0], chevaux[1], chevaux[2]
        gain = m_coup * _rapport_trio(c1.cote_pmu, c2.cote_pmu, c3.cote_pmu)
        prob = c1.proba_top3 * c2.proba_top3 * c3.proba_top3
        niveaux.append(NiveauPlan("coup", "COUP", "🟡", "#F59E0B", m_coup, int(coup*100),
            paris=[_pari("Trio", [c1, c2, c3], m_coup, gain, min(prob, 0.1))]))
        joue += m_coup

    return _finaliser(montant, joue, niveaux, chevaux, kelly_warn)


def _plan_standard(montant, sec, rend, coup, chevaux, is_quinte, nb_partants, kelly_warn) -> MisePlan:
    m_sec  = _round2(montant * sec)
    m_rend = _round2(montant * rend)
    m_coup = montant - m_sec - m_rend
    joue = 0.0
    niveaux = []

    # Sécurité — Simple Placé + Couplé Placé
    paris_sec = []
    if chevaux and m_sec >= 2:
        c = chevaux[0]
        m1 = _round2(m_sec * 0.55)
        m2 = m_sec - m1
        paris_sec.append(_pari("Simple Placé", [c], m1, m1 * _rapport_place(c.cote_pmu), c.proba_top3))
        if len(chevaux) >= 2 and m2 >= 1:
            c2 = chevaux[1]
            gain2 = m2 * _rapport_couple_place(c.cote_pmu, c2.cote_pmu)
            paris_sec.append(_pari("Couplé Placé", [c, c2], m2, gain2, c.proba_top3 * c2.proba_top3))
        joue += m_sec
        niveaux.append(NiveauPlan("securite", "SÉCURITÉ", "🟢", "#10B981", m_sec, int(sec*100), paris=paris_sec))

    # Rendement — Couplé Gagnant + 2sur4
    paris_rend = []
    if len(chevaux) >= 2 and m_rend >= 2:
        c1, c2 = chevaux[0], chevaux[1]
        m1 = _round2(m_rend * 0.5)
        m2 = m_rend - m1
        gain1 = m1 * _rapport_couple_gagnant(c1.cote_pmu, c2.cote_pmu)
        paris_rend.append(_pari("Couplé Gagnant", [c1, c2], m1, gain1, c1.proba_top1 * c2.proba_top1 * 2))
        if len(chevaux) >= 4 and m2 >= 1:
            c3, c4 = chevaux[2], chevaux[3]
            gain2 = m2 * _rapport_2sur4(c1.cote_pmu, c2.cote_pmu, c3.cote_pmu, c4.cote_pmu)
            p2 = c1.proba_top3 * c2.proba_top3 * (1 - (1-c3.proba_top3)*(1-c4.proba_top3))
            paris_rend.append(_pari("2sur4", [c1, c2, c3, c4], m2, gain2, min(p2, 0.3)))
        joue += m_rend
        niveaux.append(NiveauPlan("rendement", "RENDEMENT", "🔵", "#3B82F6", m_rend, int(rend*100), paris=paris_rend))

    # Coup — Tiercé Désordre
    if len(chevaux) >= 3 and m_coup >= 1:
        c1, c2, c3 = chevaux[0], chevaux[1], chevaux[2]
        gain = m_coup * _rapport_tierce_desordre(c1.cote_pmu, c2.cote_pmu, c3.cote_pmu)
        prob = c1.proba_top3 * c2.proba_top3 * c3.proba_top3 * 6  # 6 ordres possibles
        niveaux.append(NiveauPlan("coup", "COUP", "🟡", "#F59E0B", m_coup, int(coup*100),
            paris=[_pari("Tiercé Désordre", [c1, c2, c3], m_coup, gain, min(prob, 0.2))]))
        joue += m_coup

    return _finaliser(montant, joue, niveaux, chevaux, kelly_warn)


def _plan_complet(montant, sec, rend, coup, chevaux, is_quinte, is_quarte, nb_partants, kelly_warn) -> MisePlan:
    m_sec  = _round2(montant * sec)
    m_rend = _round2(montant * rend)
    m_coup = montant - m_sec - m_rend
    joue = 0.0
    niveaux = []

    # Sécurité
    if chevaux and m_sec >= 1:
        c = chevaux[0]
        m1 = _round2(m_sec * 0.60)
        m2 = m_sec - m1
        paris_sec = [_pari("Simple Placé", [c], m1, m1 * _rapport_place(c.cote_pmu), c.proba_top3)]
        if len(chevaux) >= 2 and m2 >= 1:
            c2 = chevaux[1]
            gain2 = m2 * _rapport_couple_place(c.cote_pmu, c2.cote_pmu)
            paris_sec.append(_pari("Couplé Placé", [c, c2], m2, gain2, c.proba_top3 * c2.proba_top3))
        niveaux.append(NiveauPlan("securite", "SÉCURITÉ", "🟢", "#10B981", m_sec, int(sec*100), paris=paris_sec))
        joue += m_sec

    # Rendement
    if len(chevaux) >= 4 and m_rend >= 2:
        c1, c2, c3, c4 = chevaux[0], chevaux[1], chevaux[2], chevaux[3]
        m1 = _round2(m_rend * 0.45)
        m2 = _round2(m_rend * 0.30)
        m3 = m_rend - m1 - m2
        paris_rend = [
            _pari("Couplé Gagnant", [c1, c2], m1, m1 * _rapport_couple_gagnant(c1.cote_pmu, c2.cote_pmu), c1.proba_top1 * c2.proba_top1 * 2),
            _pari("2sur4", [c1, c2, c3, c4], m2, m2 * _rapport_2sur4(c1.cote_pmu, c2.cote_pmu, c3.cote_pmu, c4.cote_pmu), 0.22),
        ]
        if m3 >= 1:
            gain3 = m3 * _rapport_trio(c1.cote_pmu, c2.cote_pmu, c3.cote_pmu)
            paris_rend.append(_pari("Trio", [c1, c2, c3], m3, gain3, 0.08))
        niveaux.append(NiveauPlan("rendement", "RENDEMENT", "🔵", "#3B82F6", m_rend, int(rend*100), paris=paris_rend))
        joue += m_rend

    # Coup
    if len(chevaux) >= 3 and m_coup >= 1:
        paris_coup = []
        c1, c2, c3 = chevaux[0], chevaux[1], chevaux[2]
        m1 = _round2(m_coup * 0.55)
        m2 = m_coup - m1
        gain1 = m1 * _rapport_tierce_desordre(c1.cote_pmu, c2.cote_pmu, c3.cote_pmu)
        paris_coup.append(_pari("Tiercé Désordre", [c1, c2, c3], m1, gain1, 0.12))
        if is_quinte and len(chevaux) >= 5 and m2 >= 2:
            flexi = min(1.0, m2 / 10)
            gain2 = m2 * _rapport_quinte_flexi(flexi)
            paris_coup.append(_pari("Quinté+ Flexi", chevaux[:5], m2, gain2, 0.01))
        elif is_quarte and len(chevaux) >= 4 and m2 >= 1.5:
            gain2 = m2 * _rapport_quarte(c1.cote_pmu, c2.cote_pmu, c3.cote_pmu, chevaux[3].cote_pmu)
            paris_coup.append(_pari("Quarté+", chevaux[:4], m2, gain2, 0.04))
        elif m2 >= 1:
            gain2 = m2 * _rapport_tierce_ordre(c1.cote_pmu, c2.cote_pmu, c3.cote_pmu)
            paris_coup.append(_pari("Tiercé Ordre", [c1, c2, c3], m2, gain2, 0.03))
        niveaux.append(NiveauPlan("coup", "COUP", "🟡", "#F59E0B", m_coup, int(coup*100), paris=paris_coup))
        joue += m_coup

    return _finaliser(montant, joue, niveaux, chevaux, kelly_warn)


def _plan_premium(montant, sec, rend, coup, chevaux, is_quinte, is_quarte, nb_partants, kelly_warn) -> MisePlan:
    """Kelly avancé — tous types, optimisation EV."""
    # Base = plan complet, puis ajouter Quinté+ full
    plan = _plan_complet(montant * 0.85, sec, rend, coup, chevaux, is_quinte, is_quarte, nb_partants, False)
    # Reserve 15% pour pari premium
    reserve = montant - plan.montant_joue
    if is_quinte and len(chevaux) >= 5 and reserve >= 5:
        flexi = min(1.0, reserve / 50)
        gain = reserve * _rapport_quinte_flexi(flexi)
        p = _pari(f"Quinté+ Flexi {int(flexi*100)}%", chevaux[:5], reserve, gain, 0.02)
        plan.niveaux.append(NiveauPlan("coup", "JACKPOT", "⭐", "#F59E0B", reserve, 15, paris=[p]))
        plan.montant_joue += reserve
    plan.montant_total = montant
    plan.montant_reserve = montant - plan.montant_joue
    plan.kelly_warning = kelly_warn
    return plan


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def _finaliser(montant: float, joue: float, niveaux: list, chevaux: list, kelly_warn: bool) -> MisePlan:
    reserve = max(0.0, montant - joue)
    # EV global = somme(EV_pari × prob)
    ev_total = 0.0
    for niv in niveaux:
        for p in niv.paris:
            ev_total += p.ev_estime * p.probabilite
    ev_global = round(ev_total / max(1, sum(len(n.paris) for n in niveaux)), 3)

    avert = "Paris simulés sur données historiques. Aucune garantie de gain."
    if kelly_warn:
        avert = "⚠️ Mise supérieure à 5% de votre bankroll déclarée — réduisez pour protéger votre capital."

    return MisePlan(
        montant_total=montant,
        montant_joue=round(joue, 2),
        montant_reserve=round(reserve, 2),
        ev_global=ev_global,
        niveaux=niveaux,
        resume_ia=_resume(chevaux, len(niveaux)),
        avertissement=avert,
        kelly_warning=kelly_warn,
    )


def _resume(chevaux: list[ChevPred], nb_niveaux: int) -> str:
    if not chevaux:
        return "Données insuffisantes pour générer un résumé."
    top = chevaux[0]
    lines = []
    if top.ev and top.ev > 0.05:
        lines.append(f"N°{top.numero} {top.nom} est sous-évalué par le PMU (EV +{top.ev*100:.0f}%). Recommandé.")
    elif top.proba_top3 > 0.55:
        lines.append(f"N°{top.numero} {top.nom} ressort en tête (probabilité top-3 : {top.proba_top3*100:.0f}%).")
    else:
        lines.append(f"N°{top.numero} {top.nom} en tête des sélections IA.")
    if len(chevaux) >= 2:
        c2 = chevaux[1]
        lines.append(f"N°{c2.numero} {c2.nom} confirme en 2ème position ({c2.proba_top3*100:.0f}% top-3).")
    lines.append("Plan réparti en " + ("1 niveau" if nb_niveaux == 1 else f"{nb_niveaux} niveaux") + " selon votre profil.")
    return " ".join(lines)


def _plan_vide(montant: float, profil: str) -> MisePlan:
    return MisePlan(
        montant_total=montant, montant_joue=0, montant_reserve=montant,
        ev_global=0,
        niveaux=[],
        resume_ia="Prédictions non disponibles pour cette course.",
        avertissement="Lancez l'analyse IA avant de générer un plan.",
        profil=profil,
    )


# ─────────────────────────────────────────────────────────────
# Serialisation JSON-safe
# ─────────────────────────────────────────────────────────────
def plan_to_dict(plan: MisePlan) -> dict:
    return {
        "montant_total": plan.montant_total,
        "montant_joue": plan.montant_joue,
        "montant_reserve": plan.montant_reserve,
        "ev_global": plan.ev_global,
        "esperance_gain": plan.esperance_gain,
        "palier": plan.palier,
        "profil": plan.profil,
        "mode_adaptatif": plan.mode_adaptatif,
        "kelly_warning": plan.kelly_warning,
        "resume_ia": plan.resume_ia,
        "avertissement": plan.avertissement,
        "niveaux": [
            {
                "niveau": n.niveau,
                "label": n.label,
                "emoji": n.emoji,
                "couleur": n.couleur,
                "montant": n.montant,
                "pct": n.pct,
                "paris": [
                    {
                        "type": p.type,
                        "chevaux": p.chevaux,
                        "mise": p.mise,
                        "gain_potentiel": p.gain_potentiel,
                        "probabilite": p.probabilite,
                        "description": p.description,
                        "ev_estime": p.ev_estime,
                        "raisons": p.raisons,
                    }
                    for p in n.paris
                ],
            }
            for n in plan.niveaux
        ],
        "paris_ecartes": plan.paris_ecartes,
    }
