"""
MiseCalculator — Moteur de recommandation personnalisée BlackTurf.
Génère un plan de mise structuré en 3 niveaux (sécurité / rendement / coup)
selon le montant entré et le profil de risque utilisateur.
"""
from dataclasses import dataclass, field
from typing import Optional
import math


# Mise PLANCHER par pari joué (€) — règle produit : jamais moins de 2€ sur un
# pari (un pari à 1€ ne vaut pas le coup, surtout sur le profil risqué). C'est le
# plancher EFFECTIF du moteur, indépendant des minima PMU ci-dessous.
MISE_PLANCHER = 2

# Montant minimum PMU par type de pari (référence réglementaire ; le moteur
# applique MISE_PLANCHER=2€ par-dessus).
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
# `cote_min`/`cote_max` : bornes sur la cote des CHEVAUX d'un pari (garde-fou — ex.
#   le prudent ne touche pas un cheval à cote 30). Ce N'EST PLUS le séparateur principal.
# `rapport_min`/`rapport_max` : bornes sur le RAPPORT (multiplicateur de gain) du PARI
#   lui-même. C'EST le séparateur produit demandé, en cohérence avec l'analyse :
#     • PRUDENT  : gain quasi assuré, viser ~×2          → rapport_min ≈ 1.8.
#     • MODÉRÉ   : plus de risque, viser entre ×2 et ×10 → rapport ∈ [2, 10].
#     • RISQUÉ   : gros rapport, au moins ×10            → rapport_min = 10.
#   Un même pari ne peut donc PAS tomber dans deux profils : ses bandes de rapport
#   sont contiguës. Le « pourquoi » de chaque pari est ainsi justifié par son rapport.
PROFIL_CONFIG = {
    # PRUDENT — privilégie le PLACÉ : Simple Placé, Duo Placé (Couplé Placé), 2/4.
    # Cote des chevaux COURTE (cote_max 9) = gain quasi assuré, MAIS on exige un
    # rapport ≥ ~1.8 (viser ×2) : on écarte le placé sec à 1.1× (argent mort).
    # Mises prudentes : peu de paris, plancher franc.
    "conservateur": {
        "cote_min": 0.0, "cote_max": 9.0, "rapport_min": 1.8, "rapport_max": None,
        "min_proba": 0.20, "ev_min": -0.15, "max_coup": 0,
        "bets_factor": 0.9, "min_stake_factor": 1.0,
        # GAIN VISÉ : un pari gagnant doit rapporter ≥ ×1.5 du TOTAL misé (prudent =
        # gain modeste mais réel ; on évite le placé sec qui rend à peine la mise).
        "gain_cible_mult": 1.5,
        "types": {"Simple Placé", "Couplé Placé", "2sur4"},
        "objectif": "proba",
        "risk_pref": {"securite": 1.5, "rendement": 1.0, "surprise": 0.4, "coup": 0.2},
    },
    # MODÉRÉ — viser un rapport ENTRE ×2 et ×10 : duo gagnant, couplé placé, 2/4, trio
    # de favoris. PAS de Simple Placé (le placé sec rapporte trop peu, < ×2). Cotes
    # chevaux capées à 15. PETITES mises réparties sur PLUSIEURS combinaisons (spectre PMU).
    "equilibre": {
        # Bande de RAPPORT 3–12 : un pari à mise franche (10€) doit pouvoir rendre
        # ≥ ×3 du total → rapport ≥ 3. EV plus tolérante (-0.45) : le modéré vise le
        # GAIN (un duo/trio de favoris paie ×3–×10 mais reste -EV à cause du prélèvement
        # PMU) — l'utilisateur préfère un vrai gain si ça passe à des micro-tickets +EV.
        "cote_min": 0.0, "cote_max": 15.0, "rapport_min": 3.0, "rapport_max": 12.0,
        # max_coup 3 : les combos/SG de favoris sont -EV (prélèvement PMU) donc classés
        # « spéculatifs » ; on en autorise jusqu'à 3 pour pouvoir COUVRIR le risque avec
        # 2 paris (ex. 2 SG cote ≥5). Bornés par la cible de gain + le nb de paris.
        "min_proba": 0.04, "ev_min": -0.45, "max_coup": 3,
        # spec_coup : un duo/SG de favoris est -EV (prélèvement PMU) mais c'est un pari
        # de COUVERTURE légitime (gain réel si ça passe), pas un don au PMU comme un
        # longshot mort. On les autorise (bornés par ev_min -0.45 + max_coup + la cible
        # de gain) → le modéré peut jouer 2 SG cote ≥5 pour couvrir, au lieu d'1 ticket.
        "spec_coup": True,
        # CONCENTRÉ mais FLEXIBLE : 1 à 3 paris à mise FRANCHE (plus de saupoudrage de
        # SG à 2€). Le moteur peut COUVRIR le risque avec 2 paris différents (ex. 2
        # Simple Gagnant 5€ à cote ≥5, ou 1 couplé + 1 SG) plutôt qu'un seul ticket.
        "bets_factor": 1.2, "min_stake_factor": 1.0, "max_per_type": 3,
        # GAIN VISÉ : un pari gagnant ≥ ×2.5 du TOTAL misé (10€ → ≥25€). Assez bas pour
        # autoriser 2 paris de couverture (2×5€ cote 5 = ×2.5 chacun), assez haut pour
        # rester un VRAI gain (plus de micro-tickets dilués). Le moteur garde autant de
        # paris que possible atteignant la cible, par conviction (couverture + profit).
        "gain_cible_mult": 2.5,
        "types": {"Couplé Placé", "Couplé Gagnant", "Couplé Ordre", "2sur4", "Trio", "Simple Gagnant"},
        "objectif": "ev",
        "risk_pref": {"securite": 0.8, "rendement": 1.2, "surprise": 1.0, "coup": 0.7},
    },
    # RISQUÉ — vise les GROS RAPPORTS (PLANCHER ×10) : gagnant grosse cote, duo gagnant
    # d'outsiders, trios et jackpots désordre (Tiercé/Quarté+/Quinté+). PAS de Simple
    # Placé. Le séparateur est le RAPPORT (≥10), pas la cote du cheval : un duo de deux
    # chevaux à cote moyenne qui paie ×15 est bien un pari risqué. Beaucoup de PETITES
    # mises sur un large spectre de combinaisons à fort rapport.
    # `max_per_type` : nb max de paris d'un MÊME type. Le risqué l'ouvre à 5 pour
    # proposer un large éventail (« 4 duo gagnant », « 5 trio », « 2 simple gagnant
    # grosse cote ») au lieu d'1-2 paris pauvres.
    # `spec_coup`: le risqué ASSUME des paris GROS-LOT spéculatifs (EV<0 même sans
    # edge) — c'est un profil loterie par nature. On ne les rejette donc PAS sur la
    # règle de profitabilité ; le garde-fou est le NOMBRE (max_coup) + la PART du
    # budget (cap_spec) + un plancher d'EV (SPEC_EV_FLOOR) qui exclut la loterie pure.
    "agressif": {
        "cote_min": 0.0, "cote_max": 300.0, "rapport_min": 10.0, "rapport_max": None,
        "min_proba": 0.0, "ev_min": -0.25, "max_coup": 5,
        "spec_coup": True,
        # DIVERSITÉ : max 2 paris d'un même type → fini « que des Trios ». Le moteur
        # privilégie le DUO GAGNANT (cf bonus dans conviction) puis varie les types.
        "bets_factor": 2.4, "min_stake_factor": 0.34, "max_per_type": 2,
        # GAIN VISÉ ≥ ×3 du total (plancher ; le risqué dépasse largement via les gros
        # rapports — R10C8 : Couplé Gagnant ×644). Petites mises, grosses cotes.
        "gain_cible_mult": 3.0,
        "types": {"Couplé Gagnant", "Couplé Ordre", "2sur4", "Trio", "Trio Ordre",
                  "Super 4", "Simple Gagnant",
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
        "cote_min":  max(0.0, base.get("cote_min", 0.0) * (1.0 - 0.20 * h)),
        "cote_max":  max(4.0, base["cote_max"] * (1.0 + 0.30 * h)),
        # Bandes de RAPPORT = contrat produit (×2 / ×2–×10 / ≥×10) → NON modulées par
        # le heat : le profil risqué doit TOUJOURS viser ≥×10, etc.
        "rapport_min": base.get("rapport_min", 0.0),
        "rapport_max": base.get("rapport_max"),
        "min_proba": max(0.0, base["min_proba"] * (1.0 - 0.30 * h)),
        "ev_min":    base["ev_min"] - 0.04 * h,
        "max_coup":  max(0, base["max_coup"] + (1 if h > 0.5 else 0) - (1 if h < -0.5 else 0)),
        "bets_factor": base["bets_factor"],
        "min_stake_factor": base.get("min_stake_factor", 1.0),  # <1 = plus de petites mises
        "types":     base.get("types"),          # familles de paris du profil (None = toutes)
        "objectif":  base.get("objectif", "ev"), # critère de classement des candidats
        "max_per_type": base.get("max_per_type"),  # plafond paris d'un même type (None = auto)
        "spec_coup": base.get("spec_coup", False), # autorise les coups gros-lot spéculatifs
        # Multiple de gain visé sur le TOTAL misé (un pari gagnant ≥ ×N du montant).
        # Contrat produit → NON modulé par le heat.
        "gain_cible_mult": base.get("gain_cible_mult", 0.0),
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
    # Mise plancher EFFECTIVE : le profil peut réduire l'EXTRA réparti (<1) pour
    # saupoudrer de PETITES mises sur PLUSIEURS combinaisons (équilibré/risqué), ou
    # rester franc (prudent), mais le PLANCHER reste MISE_PLANCHER=2€ par pari
    # (= max(2, plancher du palier × facteur profil)). Jamais 1€ (règle produit).
    min_stake = max(MISE_PLANCHER, round(palier["min_stake"] * cfg.get("min_stake_factor", 1.0)))
    max_feasible = max(1, montant // min_stake)             # chaque pari ≥ min_stake
    base_max = max(1, round(palier["max_bets"] * cfg.get("bets_factor", 1.0)))
    max_bets = min(base_max, max_feasible, len(cands))
    max_coup = cfg["max_coup"]
    cote_min = cfg.get("cote_min", 0.0)
    cote_max = cfg["cote_max"]
    rapport_min = cfg.get("rapport_min", 0.0)               # bande de rapport du profil
    rapport_max = cfg.get("rapport_max")                    # None = pas de plafond
    min_proba = cfg["min_proba"]
    ev_min = cfg["ev_min"]
    allowed_types = cfg.get("types")                         # None = toutes
    objectif = cfg.get("objectif", "ev")
    spec_ok = cfg.get("spec_coup", False)                     # profil loterie : coups -EV assumés
    SPEC_EV_FLOOR = -0.80                                     # plancher d'EV même pour un coup assumé
    # Spectre large de combinaisons : on tolère plusieurs paris du même type (ex. 5
    # trios différents) quand le profil saupoudre, pour couvrir plus de combinaisons PMU.
    # Le profil peut fixer son propre plafond (`max_per_type`) ; sinon auto selon palier.
    max_per_type = cfg.get("max_per_type")
    if max_per_type is None:
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
            # PRIVILÉGIE LE DUO GAGNANT (demande user) : un couplé gagnant/ordre à gros
            # rapport est préféré aux Trios à conviction comparable (anti « que des Trios »).
            if c["type_pari"] in ("Couplé Gagnant", "Couplé Ordre"):
                bonus *= 1.35
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
        bet_cote = _bet_cote_max(c)
        if bet_cote > cote_max:                              # longshot hors profil
            return False
        # Garde-fou cote PLANCHER du cheval (rarement utilisé désormais ; le séparateur
        # est le rapport). Exempté pour les jackpots désordre.
        if bet_cote < cote_min and "Désordre" not in c["type_pari"]:
            return False
        # BANDE DE RAPPORT = séparateur produit (×2 / ×2–×10 / ≥×10). Le pari doit
        # rapporter dans la fourchette du profil, sinon il appartient à un autre profil.
        rap = float(c.get("rapport_estime", 0.0) or 0.0)
        if rap < rapport_min:                                # rapport trop faible pour ce profil
            return False
        if rapport_max is not None and rap > rapport_max:    # rapport trop élevé → profil plus risqué
            return False
        if c["proba_gain"] < min_proba:                      # trop improbable
            return False
        # RÈGLE DE PROFITABILITÉ : jamais un pari à la fois -EV ET sans edge (= don au
        # PMU) — SAUF profil "coup" (risqué) qui assume des paris gros-lot spéculatifs,
        # bornés ensuite par max_coup + cap_spec. On exclut quand même la loterie pure
        # (EV sous le plancher SPEC_EV_FLOOR).
        if c["ev"] < 0 and c.get("edge", 0.0) <= 0:
            if not spec_ok or c["ev"] < SPEC_EV_FLOOR:
                return False
        # Seuil EV propre au profil (exempté : coup crédible à valeur, ou coup spéculatif
        # assumé au-dessus du plancher pour le profil risqué).
        if c["ev"] < ev_min and not _is_credible_coup(c):
            if not (spec_ok and c["ev"] >= SPEC_EV_FLOOR):
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
        def _in_type(c):
            return allowed_types is None or c["type_pari"] in allowed_types

        def _in_rapport(c):
            r = float(c.get("rapport_estime", 0.0) or 0.0)
            return r >= rapport_min and (rapport_max is None or r <= rapport_max)

        # Replis successifs : type+rapport+cote → type+rapport → type → tout. On garde
        # la bande de rapport du profil le plus longtemps possible (contrat ×2/×10).
        pool = [c for c in cands if _in_type(c) and _in_rapport(c)
                and cote_min <= _bet_cote_max(c) <= cote_max]
        pool = pool or [c for c in cands if _in_type(c) and _in_rapport(c)] \
            or [c for c in cands if _in_type(c)] or cands
        # Risqué (objectif gain) : viser le plus gros RAPPORT du repli ; prudent/modéré : le plus sûr.
        if objectif == "gain":
            safe = max(pool, key=lambda c: c["rapport_estime"])
        else:
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
    # Même plancher effectif que la sélection — jamais sous MISE_PLANCHER=2€ par pari.
    min_stake = max(MISE_PLANCHER, round(palier["min_stake"] * cfg.get("min_stake_factor", 1.0)))

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

    _apply_spec_cap(selected, montant, palier, min_stake)
    _enforce_gain_target(selected, montant, cfg, min_stake)


def _enforce_gain_target(selected: list[dict], montant: int, cfg: dict,
                         min_stake: int) -> None:
    """CONCENTRE la mise pour qu'un pari GAGNANT rapporte ≥ `gain_cible_mult` × le
    montant TOTAL misé (demande user : 10€ → ≥30€ pour le modéré). Pour chaque pari,
    la mise nécessaire = ceil(cible / rapport). On finance, par ordre de conviction,
    autant de paris que possible à ce niveau ; ceux qui ne peuvent PAS atteindre la
    cible dans le budget restant sont écartés (→ moins de paris, mises plus franches).
    Le reliquat va aux paris gardés (priorité conviction). Respecte la réserve laissée
    par le plafond spéculatif (on ne dépense pas plus que ce qui était déjà joué)."""
    g = float(cfg.get("gain_cible_mult", 0.0) or 0.0)
    if g <= 0 or not selected:
        return
    # Le contrat de GAIN (un pari gagnant ≥ ×g du total) prime sur la réserve
    # spéculative : on concentre TOUT le montant vers la cible (sinon une réserve de
    # 40% au palier "petit" tuerait la concentration et le ×3 ne serait jamais atteint).
    budget = int(montant)
    if budget <= 0:
        return
    cible = g * montant

    def prio(c):
        return (max(float(c.get("_kelly_f", 0.0) or 0.0), 1e-3)
                * float(c.get("_roi_w", 1.0) or 1.0) * float(c.get("_sig", 1.0) or 1.0)
                * (0.5 + float(c.get("proba_gain", 0.0) or 0.0)))

    def besoin(c):
        rap = max(float(c.get("rapport_estime", 1.0) or 1.0), 1.01)
        return max(min_stake, math.ceil(cible / rap))

    # COUVERTURE DU RISQUE : on finance d'abord les paris les MOINS chers à amener à la
    # cible (rapport le plus élevé) → on en case PLUSIEURS quand c'est possible (ex. 2
    # Simple Gagnant cote ≥5 à 5€ plutôt qu'un seul gros ticket), à conviction égale on
    # garde le mieux classé. Sinon un seul pari fort qui atteint la cible.
    ordered = sorted(selected, key=lambda c: (besoin(c), -prio(c)))
    kept: list[dict] = []
    reste = budget
    for c in ordered:
        need = besoin(c)
        if need <= reste:
            c["mise"] = need
            kept.append(c)
            reste -= need
    if not kept:
        # Aucun pari n'atteint la cible dans le budget → concentrer le budget sur le
        # pari au plus gros rapport (meilleure chance d'approcher la cible).
        best = max(selected, key=lambda c: float(c.get("rapport_estime", 0.0) or 0.0))
        best["mise"] = budget
        selected[:] = [best]
        return
    # Reliquat → aux paris gardés par priorité (total dépensé == budget initial).
    kept_prio = sorted(kept, key=prio, reverse=True)
    k = 0
    while reste > 0 and kept_prio:
        kept_prio[k % len(kept_prio)]["mise"] += 1
        reste -= 1
        k += 1
    selected[:] = kept


def _apply_spec_cap(selected: list[dict], montant: int, palier: dict,
                    min_stake: Optional[int] = None) -> None:
    """Plafonne la part totale misée sur les paris SPÉCULATIFS (EV≤0) à cap_spec ×
    montant. L'excédent va aux paris fiables (EV>0) s'il y en a, SINON il reste en
    RÉSERVE (non joué) — un profil 100% spéculatif (risqué sans value) ne mise donc
    jamais plus que cap_spec du budget. Plancher = le min_stake EFFECTIF (pas le
    plancher brut du palier : sinon mise<plancher ⇒ reducible négatif ⇒ surmise)."""
    cap = palier["cap_spec"]
    if cap >= 1.0:
        return
    if min_stake is None:
        min_stake = palier["min_stake"]
    spec_idx = [i for i, c in enumerate(selected) if c["ev"] <= 0]
    safe_idx = [i for i, c in enumerate(selected) if c["ev"] > 0]
    if not spec_idx:
        return
    max_spec = int(montant * cap)
    spec_total = sum(selected[i]["mise"] for i in spec_idx)
    if spec_total <= max_spec:
        return

    to_move = spec_total - max_spec
    # Réduire les spéculatifs (mise desc) jusqu'au plancher EFFECTIF (reducible ≥ 0).
    for i in sorted(spec_idx, key=lambda i: selected[i]["mise"], reverse=True):
        if to_move <= 0:
            break
        reducible = max(0, selected[i]["mise"] - min_stake)
        cut = min(reducible, to_move)
        selected[i]["mise"] -= cut
        to_move -= cut
    moved = (spec_total - max_spec) - to_move      # € réellement libérés
    if not safe_idx:
        return    # aucun pari fiable → l'excédent reste en RÉSERVE (montant_joue < montant)
    # Transférer l'euro coupé sur les paris fiables (mise desc). Conserve le total.
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
    ("equilibre", "Couplé Ordre"):     "Duo à l'ordre (champ réduit) : 1er + 2e dans l'ordre exact — rapport rehaussé.",
    # RISQUÉ — grosses cotes gagnant, duo gagnant, trios, jackpots désordre.
    ("agressif", "Simple Gagnant"):    "Gagnant GROSSE cote : gain élevé visé sur un cheval que le modèle place au-dessus du marché.",
    ("agressif", "Couplé Gagnant"):    "Duo gagnant : rapport multiplié, le modèle voit ces 2 chevaux au-dessus du marché.",
    ("agressif", "Couplé Ordre"):      "Duo à l'ORDRE exact : rapport bien plus gros qu'en désordre — petite mise, gros levier.",
    ("agressif", "Trio Ordre"):        "Trio à l'ORDRE exact (champ réduit) : très gros rapport pour une mise minime.",
    ("agressif", "Super 4"):           "Super 4 : les 4 premiers dans l'ordre exact — jackpot, mise minime assumée.",
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
    # 0. Objectif du profil + rapport RÉEL de ce pari → justifie « pourquoi je joue ça ».
    rap = float(c.get("rapport_estime", 0.0) or 0.0)
    _obj = {
        "conservateur": f"Objectif PRUDENT : cote courte, gain quasi assuré — viser ~×2. "
                        f"Ce pari rapporte ~×{rap:.1f}.",
        "equilibre":    f"Objectif MODÉRÉ : plus de cote/risque — viser entre ×2 et ×10. "
                        f"Ce pari rapporte ~×{rap:.1f}.",
        "agressif":     f"Objectif RISQUÉ : viser gros, au moins ×10. "
                        f"Ce pari rapporte ~×{rap:.1f}.",
    }.get(profil)
    if _obj:
        raisons.append(_obj)
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
    if _bet_cote_max(c) < cfg.get("cote_min", 0.0) and "Désordre" not in c["type_pari"]:
        return f"Cote trop courte pour le profil risqué (min {cfg['cote_min']:.0f}) — gardée pour le modéré."
    rap = float(c.get("rapport_estime", 0.0) or 0.0)
    rmin = cfg.get("rapport_min", 0.0)
    rmax = cfg.get("rapport_max")
    if rap < rmin:
        return f"Rapport trop faible (~×{rap:.1f}) pour l'objectif du profil (viser ≥ ×{rmin:.1f})."
    if rmax is not None and rap > rmax:
        return f"Rapport trop élevé (~×{rap:.1f}) pour ce profil (max ×{rmax:.0f}) — réservé au profil risqué."
    if c["proba_gain"] < cfg["min_proba"]:
        return f"Probabilité trop faible ({c['proba_gain']*100:.0f}%) pour ce profil."
    spec_ok = cfg.get("spec_coup", False)
    if c["ev"] < 0 and c.get("edge", 0.0) <= 0:
        if not spec_ok:
            return "Espérance négative SANS valeur détectée — ce pari donnerait sa mise au PMU."
        if c["ev"] < -0.80:
            return "Coup trop improbable (espérance sous le plancher) même pour le profil risqué."
    if c["ev"] < cfg["ev_min"] and not _is_credible_coup(c) and not spec_ok:
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


# NOTE : l'ancien moteur de plan (_plan_micro/simple/standard/complet/premium) a été
# supprimé — code mort (aucun appelant ; generer_plan passe par enumerate_bet_candidates
# + _select_conviction + _allocate_kelly). Il portait des probas combinées fausses
# (p1·p2·2, produits indépendants) et des rapports magiques non calibrés.


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
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
