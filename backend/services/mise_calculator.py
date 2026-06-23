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
    "Multi":            3.0,   # mise PLATE 3€ (4→7 chevaux), Flexi dès 1.5€
    "Pick5":            1.0,
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
    sans_value: bool = False         # aucun pari à value réelle (espérance ≤ 0) → plan « plaisir », honnêteté affichée
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
        "cote_min": 0.0, "cote_max": 9.0, "rapport_min": 1.8, "rapport_max": 10.0,
        "min_proba": 0.20, "ev_min": -0.15, "max_coup": 0,
        "bets_factor": 0.9, "min_stake_factor": 1.0,
        # keep_frac : on garde les paris dont la conviction ≥ 65% du meilleur → le NB de
        # paris VARIE selon la course (1 si un placé domine, 2-3 si plusieurs comparables).
        "keep_frac": 0.65,
        # MULTIPLICATEUR ≥1.8 garanti par rapport_min 1.8 AU NIVEAU CANDIDAT (tout pari proposé
        # paie déjà ≥1.8). gain_cible_mult=0 : on N'active PAS _enforce_gain_target — son tri par
        # `prio` (kelly_f=0 pour un -EV) déprioritisait l'ANCRE placé « gagne souvent » et la
        # jetait. Sans lui, la conviction (proba) sélectionne l'ancre = le placé ≥1.8 le PLUS
        # probable → 44% de réussite (vs 28%), gain ≥1.8× toujours respecté.
        "gain_cible_mult": 0.0,
        # Multi en 6/7 = large filet qui TOMBE SOUVENT (4 premiers dans 6-7 chevaux) →
        # parfait pour le prudent. Pas de Multi 4/5 (gros lot = trop rare). var_cap 1.0 :
        # le prudent n'a aucun pari haute-variance, le plafond est donc inerte.
        "types": {"Simple Placé", "Couplé Placé", "2sur4", "Multi en 6", "Multi en 7"},
        "objectif": "proba",
        "var_cap": 1.0,
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
        "cote_min": 0.0, "cote_max": 20.0, "rapport_min": 4.0, "rapport_max": 25.0,
        # max_coup 3 : les combos/SG de favoris sont -EV (prélèvement PMU) donc classés
        # « spéculatifs » ; on en autorise jusqu'à 3 pour pouvoir COUVRIR le risque avec
        # 2 paris (ex. 2 SG cote ≥5). Bornés par la cible de gain + le nb de paris.
        "min_proba": 0.04, "ev_min": -0.45, "max_coup": 3,
        # spec_coup : un duo/SG de favoris est -EV (prélèvement PMU) mais c'est un pari
        # de COUVERTURE légitime (gain réel si ça passe), pas un don au PMU comme un
        # longshot mort. On les autorise (bornés par ev_min -0.45 + max_coup + la cible
        # de gain) → le modéré peut jouer 2 SG cote ≥5 pour couvrir, au lieu d'1 ticket.
        "spec_coup": True,
        # keep_frac 0.50 : le NB de paris VARIE (1 ticket fort, ou 2-3 de couverture si
        # leur conviction reste proche du meilleur). Plus de blocage à un nombre fixe.
        "keep_frac": 0.50,
        "bets_factor": 1.2, "min_stake_factor": 1.0,
        # GAIN VISÉ (contrat produit) : un pari gagnant ≥ ×4 du TOTAL misé (10€ → ≥40€),
        # jusqu'à ×25 (rapport_max). _enforce_gain_target taille la mise pour garantir ce
        # minimum sur CHAQUE pari proposé ; les paris dont le rapport ne peut pas atteindre
        # ×4 même à pleine mise sont écartés (→ moins de paris, mises plus franches).
        "gain_cible_mult": 4.0,
        # Multi en 5/6/7 = rapport ×2-×10 qui tombe assez souvent (cœur du modéré).
        # PAS de Simple Gagnant pour le MODÉRÉ : c'est le pari du risqué (grosse cote) et il
        # faisait collapser le modéré sur « 2 Simple Gagnant » = identique au risqué (overlap).
        # Le modéré = COMBOS de favoris (duo/trio/couplé) → identité ×4 distincte du risqué.
        "types": {"Couplé Placé", "Couplé Gagnant", "Couplé Ordre", "2sur4", "Trio",
                  "Multi en 5", "Multi en 6", "Multi en 7"},
        "objectif": "ev",
        # var_cap 0.50 : jamais plus de la moitié du budget sur un seul pari haute-variance
        # (Trio/2sur4-jackpot) → force au moins 2 tickets décorrélés. Anti « tout sur un Trio ».
        "var_cap": 0.50,
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
        "cote_min": 0.0, "cote_max": 300.0, "rapport_min": 8.0, "rapport_max": None,
        "min_proba": 0.0, "ev_min": -0.25,
        # RENTA LONG TERME : on limite les paris PUREMENT spéculatifs (sans edge) à 2 ;
        # la mise se concentre sur les gros rapports À VALEUR (edge>0 / conviction signal
        # validée). max_coup borne le nb de tickets « loterie » sans avantage mesuré.
        "max_coup": 2, "spec_coup": True,
        # keep_frac 0.38 : risqué peut étaler PLUS de paris à gros rapport SI leur
        # conviction reste dans la bande ; sinon il en garde moins. Nombre DYNAMIQUE.
        "keep_frac": 0.38,
        "bets_factor": 2.4, "min_stake_factor": 0.34,
        # GAIN VISÉ (contrat produit) : un pari gagnant ≥ ×8 du TOTAL misé (10€ → ≥80€),
        # SANS plafond (rapport_max None → vise l'infini sur les gros coups). C'est LE
        # cœur du risqué : _enforce_gain_target CONCENTRE la mise (ou cherche un rapport
        # plus élevé) jusqu'à garantir ×8 ; un pari qui ne peut pas l'atteindre est écarté.
        "gain_cible_mult": 8.0,
        # Multi en 4/5 (gros lot) + Pick5 = gros rapports assumés du profil risqué.
        "types": {"Couplé Gagnant", "Couplé Ordre", "2sur4", "Trio", "Trio Ordre",
                  "Super 4", "Simple Gagnant",
                  "Tiercé Désordre", "Quarté+ Désordre", "Quinté+ Désordre",
                  "Multi en 4", "Multi en 5", "Pick5"},
        "objectif": "gain",
        # var_cap 0.45 : le risqué reste 100% gros rapport, MAIS jamais plus de 45% du
        # budget sur un seul ticket → la mise s'étale sur ≥2 gros-rapports DÉCORRÉLÉS
        # au lieu de tout risquer sur un seul Trio (demande explicite de l'utilisateur).
        "var_cap": 0.45,
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
        # Fraction de conviction min (vs meilleur pari) pour garder un pari → pilote le
        # NOMBRE DYNAMIQUE de paris. Heat chaud → on élargit un peu la bande (plus de
        # paris quand le modèle est fiable), froid → on resserre (concentre sur le top).
        "keep_frac": max(0.30, min(0.85, base.get("keep_frac", 0.5) * (1.0 - 0.15 * h))),
        # Multiple de gain visé sur le TOTAL misé (un pari gagnant ≥ ×N du montant).
        # Contrat produit → NON modulé par le heat.
        "gain_cible_mult": base.get("gain_cible_mult", 0.0),
        # Plafond de mise sur UN pari haute-variance (fraction du montant) — garde-fou
        # anti « tout sur un Trio ». Contrat produit → NON modulé par le heat.
        "var_cap": base.get("var_cap", 1.0),
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
    respect_montant: bool = False,
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
    # Avertissement Kelly seulement si un bankroll RÉEL est renseigné (≥10€) — le défaut
    # bankroll_initiale=1.0 n'est PAS un vrai bankroll, ne pas crier dessus.
    kelly_warn = bankroll is not None and bankroll >= 10 and montant > bankroll * 0.05
    # FLAG staking_safe : cap DUR de l'exposition à une fraction du bankroll (protège la
    # ruine sur un système -EV en staking AUTO). MAIS sur le calculateur manuel le
    # MONTANT SAISI est la décision explicite de l'utilisateur → on NE le rabote PAS
    # (respect_montant=True). Sinon, avec un bankroll par défaut (1.0), tout plan
    # tombait à 2€ quel que soit le montant entré. Le cap ne reste utile que pour un
    # futur staking automatique (respect_montant=False + bankroll réel).
    if not respect_montant:
        try:
            from ml.algo_flags import FLAGS as _AF
            if _AF.staking_safe and bankroll and bankroll >= 10:
                montant = max(2, min(montant, int(bankroll * _AF.bankroll_cap_frac)))
        except Exception:
            pass
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

    selected = _select_conviction(cands, montant, palier, cfg, roi_weights, signal_mults,
                                  respect_montant=respect_montant)
    if not selected:
        # Predictions existent mais AUCUN pari ne tombe dans la tranche de rapport du
        # profil (x2 / x2-10 / >=x10) -> plan vide honnete plutot qu un pari hors-regle.
        return _plan_vide(
            montant, profil,
            resume=("Aucun pari ne correspond a ce profil sur cette course - les cotes "
                    "disponibles sont hors de la tranche visee. Essaie un autre profil ou "
                    "une autre course."),
            avert="Probabilites estimees par simulation (Plackett-Luce). Jouez avec moderation.",
        )

    # Couverture : si on a (volontairement) ≥2 paris car le top n'est pas une
    # quasi-certitude, on GARDE au moins 2 paris à l'allocation (la concentration ne doit
    # pas les ré-effondrer en 1). Sinon 1 pari concentré autorisé.
    # Cap Simple Place au nombre de PLACES PAYEES (place paie 2 places si 4-7 partants,
    # 3 si >=8 ; <4 = pas de place). On ne propose jamais plus de places qu il n y a de
    # places gagnantes possibles, et on garde les plus PROBABLES.
    _npart = sum(1 for _p in predictions if not _p.get("non_partant"))
    _places = 3 if _npart >= 8 else (2 if _npart >= 4 else 1)
    _sp = [c for c in selected if c.get("type_pari") == "Simple Placé"]
    if len(_sp) > _places:
        _keep = {id(c) for c in sorted(_sp, key=lambda c: c.get("proba_gain", 0.0), reverse=True)[:_places]}
        selected[:] = [c for c in selected if c.get("type_pari") != "Simple Placé" or id(c) in _keep]

    min_keep = 2 if (len(selected) >= 2 and not _solo_confident(selected[0])) else 1
    _allocate_kelly(selected, montant, palier, cfg, respect_montant=respect_montant,
                    min_keep=min_keep)  # remplit "mise"
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


# Paris à HAUTE VARIANCE : proba de gain faible, gros rapport, tout-ou-rien. Y mettre
# tout le budget = jouer à la loterie. Le var_cap du profil plafonne leur mise UNITAIRE.
_HIGH_VAR_TYPES = {
    "Trio", "Trio Ordre", "Tiercé Désordre", "Tiercé Ordre",
    "Quarté+ Désordre", "Quinté+ Désordre", "Super 4", "Pick5",
}


def _fam(type_pari: str) -> str:
    """Famille normalisée d'un type de pari : « Mini Multi en 7 » → « Multi en 7 »
    (même méthode de jeu, label différent selon le nb de partants). Sert aux gates de
    profil (qui listent « Multi en N ») et à la classification variance."""
    return type_pari.replace("Mini Multi", "Multi") if type_pari else type_pari


def _is_high_variance(c: dict) -> bool:
    """Le pari est-il tout-ou-rien à faible proba ? Trio/jackpots/Pick5 toujours ;
    Multi en 4/5 = gros lot (haute variance) ; Multi en 6/7 = filet large (NON)."""
    t = _fam(c.get("type_pari", ""))
    if t in _HIGH_VAR_TYPES:
        return True
    if t.startswith("Multi en "):
        try:
            return int(t.rsplit(" ", 1)[-1]) <= 5
        except (ValueError, IndexError):
            return False
    return False


def _solo_confident(c: dict) -> bool:
    """Le modèle est-il assez SÛR de ce pari pour y mettre toute la mise (1 seul pari) ?
    Sinon on diversifie sur ≥2 paris pour couvrir le risque. Quasi-certitude =
    forte probabilité de gain, OU proba correcte + VRAIE valeur (edge>0) + signal validé.
    Un Simple Gagnant à ~20% (relativement le meilleur mais absolument incertain) ne
    passe PAS → couverture par un 2e pari."""
    p = float(c.get("proba_gain", 0.0) or 0.0)
    edge = float(c.get("edge", 0.0) or 0.0)
    sig = float(c.get("_sig", 1.0) or 1.0)
    return (p >= 0.42
            or (p >= 0.32 and edge > 0.0)
            or (p >= 0.26 and edge > 0.02 and sig >= 1.10))


def _bet_cote_max(c: dict) -> float:
    """Cote la plus élevée parmi les chevaux d'un pari (mesure de risque du pari)."""
    cotes = [float(h.get("cote") or 0.0) for h in c.get("chevaux", [])]
    return max(cotes) if cotes else 0.0


def _select_conviction(
    cands: list[dict], montant: int, palier: dict, cfg: dict, roi_weights: dict,
    signal_mults: Optional[dict] = None, respect_montant: bool = False,
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
    SPEC_EV_FLOOR = -0.40                                     # plancher d'EV même pour un coup assumé (relevé de -0.80 : -80% = loterie pure, ruine garantie ; -40% laisse passer les vrais gros rapports à edge>0 via _is_credible_coup)
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
            # PRUDENT : MAX de victoires DANS la contrainte ≥1.8× (le rapport_min 1.8 garantit
            # déjà le multiplicateur ; on ne touche PAS aux gains). On classe par PROBA de placé
            # quasi-PURE → parmi les placés qui paient ≥1.8, on prend le PLUS susceptible de
            # tomber (le mieux placé par le modèle). Backtest : 44% de réussite vs 28% (l'ancien
            # rw distordait vers un placé moins probable). rw module à peine (0.85..1.15).
            return (c["proba_gain"] + max(c["ev"], 0.0) * 0.15) * (0.85 + 0.15 * min(rw, 2.0)) * (1.5 if c.get("_anchor") else 1.0)
        if objectif == "gain":
            # RISQUÉ : gros gain pour petite mise, MAIS orienté RENTA → on pondère
            # fortement l'EDGE (modèle > marché) : un gros rapport À VALEUR rapporte sur
            # le long terme, un gros rapport sans edge = loterie. Retour attendu × valeur.
            payout = c["rapport_estime"] * c["proba_gain"]   # espérance de retour (×mise)
            edge = max(c.get("edge", 0.0), 0.0)
            value = 1.0 + 3.0 * edge                          # +edge → conviction ↑↑ (ROI long terme)
            bonus = 1.30 if (edge > 0 and c["rapport_estime"] >= 8) else 1.0
            # PRIVILÉGIE LE DUO GAGNANT (demande user) : un couplé gagnant/ordre à gros
            # rapport est préféré aux Trios à conviction comparable (anti « que des Trios »).
            if c["type_pari"] in ("Couplé Gagnant", "Couplé Ordre"):
                bonus *= 1.35
            return payout * value * bonus * rw
        # ÉQUILIBRE = MESURÉ : la PROBA prime (gagner assez souvent), l'EV/edge en
        # appui. On PÉNALISE la haute variance (Trio/2sur4/jackpots) → le modéré
        # privilégie duo gagnant / simple gagnant cote moyenne / couplé, et ne tombe
        # PAS sur 2 Trios à ~10% (ça, c'est le profil risqué). Bonus valeur réduit pour
        # ne plus faire remonter les « surprises » à gros rapport au-dessus du mesuré.
        base = (c["proba_gain"] * 1.0 + max(c["ev"], 0.0) * 0.5
                + max(c.get("edge", 0.0), 0.0) * 0.6)
        if c["type_pari"] in ("Trio", "Trio Ordre", "2sur4", "Tiercé Désordre"):
            base *= 0.72                                  # haute variance → après duo/SG/couplé
        if palier["favor_value"] and c.get("edge", 0.0) > 0:
            base += min(c["rapport_estime"], 10.0) / 400.0
        return base * rw

    def passes_gates(c):
        if allowed_types is not None and _fam(c["type_pari"]) not in allowed_types:
            return False                                     # hors méthode du profil
        # GATE DUR appris : un type au poids ~0 = bucket (type×contexte) PROUVÉ perdant
        # (ROI réel ≤ seuil sur n suffisant, cf. profil_learning.suppressed) → on ne le
        # propose plus du tout pour ce profil dans ce contexte. Couper > sous-pondérer.
        if roi_weights.get(c["type_pari"], 1.0) <= 0.001:
            return False
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
        # ANCRE PLACÉ PRUDENT (≥1.8×) : le placé le plus sûr qui paie ≥1.8 est -EV (marge PMU)
        # mais c'est le pari « gagne souvent DANS le multiplicateur » voulu. Le multiplicateur
        # est DÉJÀ respecté (rapport_min 1.8 vérifié ci-dessus) → on exempte juste des gates de
        # profitabilité (le but assumé = fréquence de victoire à multiplicateur garanti).
        if c.get("_anchor"):
            return True
        # PRUDENT = FREQUENCE de victoire, PAS l EV : un Simple/Couple Place sur un cheval
        # SUR est -EV par la marge PMU, mais c est LE pari prudent (gagne souvent dans le
        # multiplicateur >=1.8 deja verifie ci-dessus). On l exempte des gates de
        # profitabilite, sinon le moteur ne garde que les places d OUTSIDERS a EV+ (= peu
        # probables = l inverse du prudent). Classe ensuite par proba (objectif "proba").
        if objectif == "proba" and "Placé" in c["type_pari"]:
            return True
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

    # NOMBRE DE PARIS DYNAMIQUE — piloté par la course, pas un cap fixe :
    # on garde les paris dont la CONVICTION reste ≥ keep_frac × le meilleur. Une course
    # avec un pari qui domine (forte certitude) → 1-2 paris ; une course ouverte où
    # plusieurs paris se valent → davantage. Bornes : budget (max_feasible) + plafond de
    # sécurité (dyn_ceil) + dédoublonnage (pas de quasi-doublons) + quota de tickets
    # purement spéculatifs (max_coup) pour la renta long terme.
    ranked = [c for c in sorted(cands, key=conviction, reverse=True) if passes_gates(c)]
    keep_frac = float(cfg.get("keep_frac", 0.5))
    dyn_ceil = int(cfg.get("dyn_ceil", 8))
    selected: list[dict] = []
    seen_sets: list[tuple[frozenset, str]] = []
    n_coup = 0

    if ranked:
        best_conv = max(conviction(ranked[0]), 1e-9)
        for c in ranked:
            if len(selected) >= max_feasible or len(selected) >= dyn_ceil:
                break
            # BANDE de conviction : dès qu'un pari décroche trop du meilleur, on s'arrête
            # → le nombre s'ADAPTE à la dispersion des convictions de la course.
            if conviction(c) < keep_frac * best_conv:
                break
            hs = frozenset(int(h["numero"]) for h in c.get("chevaux", []))
            # Dédup : même combinaison déjà prise, OU combo de MÊME type qui ne diffère
            # que d'1 cheval (ex. Trio 6-4-8 vs 6-4-3 : corrélés, pas une vraie
            # couverture → un seul), OU fort recouvrement (≥67%).
            def _dup(s, t):
                if hs == s:
                    return True
                if t != c["type_pari"]:
                    return False
                inter = len(hs & s)
                if len(hs) >= 3 and inter >= max(len(hs), len(s)) - 1:
                    return True                          # combos qui ne diffèrent que d'1 cheval
                return inter / max(len(hs | s), 1) >= 0.67
            if any(_dup(s, t) for s, t in seen_sets):
                continue
            # Placé prudent = SUR (gagne souvent), -EV par marge PMU mais PAS speculatif :
            # ne pas le compter dans le quota de coups (sinon max_coup=0 le rejette).
            spec = _is_speculative(c) and not (objectif == "proba" and "Placé" in c["type_pari"])
            if spec and n_coup >= max_coup:          # quota de tickets sans edge (renta)
                continue
            c["_roi_w"] = roi_w(c)
            c["_sig"] = sig_factor(c)
            selected.append(c)
            seen_sets.append((hs, c["type_pari"]))
            if spec:
                n_coup += 1

    # COUVERTURE DU RISQUE — « si tu es SÛR d'1 seul pari go, sinon varie » : si la bande
    # n'a retenu qu'1 pari ET que ce pari n'est PAS une quasi-certitude, on ajoute un 2e
    # pari PMU DIFFÉRENT (autre cheval/type) pour ne pas tout risquer sur un seul. Pris
    # parmi les candidats qui passent déjà les gates du profil (ranked).
    if len(selected) == 1 and not _solo_confident(selected[0]) and max_feasible >= 2:
        sel_hs = frozenset(int(h["numero"]) for h in selected[0].get("chevaux", []))
        sel_type = selected[0]["type_pari"]
        for c in ranked:
            if c is selected[0]:
                continue
            hs2 = frozenset(int(h["numero"]) for h in c.get("chevaux", []))
            if hs2 == sel_hs:
                continue
            # éviter un quasi-doublon du 1er (combos ne différant que d'1 cheval)
            if (c["type_pari"] == sel_type and len(hs2) >= 3
                    and len(hs2 & sel_hs) >= max(len(hs2), len(sel_hs)) - 1):
                continue
            if (_is_speculative(c) and not (objectif == "proba" and "Placé" in c["type_pari"])) and n_coup >= max_coup:
                continue
            c["_roi_w"] = roi_w(c)
            c["_sig"] = sig_factor(c)
            selected.append(c)
            break

    # Filet : aucune value qui passe les gates → 1 pari le plus SÛR (meilleure proba),
    # en restant si possible dans la méthode du profil. Sans plan vide. Aucune invention.
    if not selected:
        def _in_type(c):
            return allowed_types is None or _fam(c["type_pari"]) in allowed_types

        def _in_rapport(c):
            r = float(c.get("rapport_estime", 0.0) or 0.0)
            return r >= rapport_min and (rapport_max is None or r <= rapport_max)

        # Replis successifs : type+rapport+cote → type+rapport → type → tout. On garde
        # la bande de rapport du profil le plus longtemps possible (contrat ×2/×10).
        pool = [c for c in cands if _in_type(c) and _in_rapport(c)
                and cote_min <= _bet_cote_max(c) <= cote_max]
        pool = pool or [c for c in cands if _in_type(c) and _in_rapport(c)]
        # Filet : on RESTE dans la bande de rapport du profil (regle produit x2/x2-10/>=x10).
        # On relache seulement la borne de COTE du cheval, JAMAIS le rapport. Aucun pari en
        # bande -> plan laisse VIDE (gere en amont) plutot qu un pari hors-tranche.
        if pool:
            if objectif == "gain":
                safe = max(pool, key=lambda c: c["rapport_estime"])
            else:
                safe = max(pool, key=lambda c: c["proba_gain"])
            safe["_roi_w"] = roi_w(safe)
            safe["_sig"] = sig_factor(safe)
            selected = [safe]

    # ── DÉPLOIEMENT INTÉGRAL (calculateur MANUEL, respect_montant) ──────────────
    # L'utilisateur a SAISI un montant et choisi un profil : il veut qu'il soit JOUÉ EN
    # ENTIER, réparti sur PLUSIEURS paris (pas tout sur un seul ticket, pas de réserve
    # fantôme). Le var_cap plafonne chaque pari haute-variance à var_cap×montant ;
    # absorber tout le budget exige donc ≥ ceil(montant/plafond) paris distincts. Or la
    # sélection peut se réduire à 1 SEUL pari quand les gates de RENTA (poids ROI appris
    # « gate-dur », ev_min) répriment presque tous les candidats → on tombe sur le filet.
    # Ici (flux MANUEL uniquement) on complète depuis un pool ÉLARGI : on garde l'identité
    # PRODUIT du profil (type autorisé + bande de rapport + cote + proba + plancher EV de
    # loterie) mais on n'exige plus le ROI passé ni le seuil EV de renta — déployer la mise
    # CHOISIE sur l'éventail de paris éligibles du profil EST le comportement attendu (un
    # agressif veut plusieurs gros rapports, pas un Simple Placé unique). Le staking AUTO
    # (respect_montant=False) conserve au contraire toute sa discipline de renta + réserve.
    if respect_montant and selected and len(cands) > len(selected):
        var_cap = float(cfg.get("var_cap", 1.0) or 1.0)
        plafond = max(min_stake, int(montant * var_cap)) if var_cap < 1.0 else montant
        need_bets = min(max_feasible, len(cands), max(1, -(-montant // max(plafond, 1))))
        if len(selected) < need_bets:
            def _relaxed_ok(c):
                if allowed_types is not None and _fam(c["type_pari"]) not in allowed_types:
                    return False
                bc = _bet_cote_max(c)
                if bc > cote_max:
                    return False
                if bc < cote_min and "Désordre" not in c["type_pari"]:
                    return False
                rap = float(c.get("rapport_estime", 0.0) or 0.0)
                if rap < rapport_min or (rapport_max is not None and rap > rapport_max):
                    return False
                if c["proba_gain"] < min_proba:
                    return False
                return c["ev"] >= SPEC_EV_FLOOR        # exclut la loterie pure (EV planchée)

            seen = [(frozenset(int(h["numero"]) for h in c.get("chevaux", [])), c["type_pari"])
                    for c in selected]
            for c in sorted(cands, key=conviction, reverse=True):
                if len(selected) >= need_bets:
                    break
                if any(c is s for s in selected) or not _relaxed_ok(c):
                    continue
                hs = frozenset(int(h["numero"]) for h in c.get("chevaux", []))
                dup = False
                for s, t in seen:
                    if hs == s:
                        dup = True
                        break
                    if t != c["type_pari"]:
                        continue
                    inter = len(hs & s)
                    if len(hs) >= 3 and inter >= max(len(hs), len(s)) - 1:
                        dup = True
                        break
                    if inter / max(len(hs | s), 1) >= 0.67:
                        dup = True
                        break
                if dup:
                    continue
                c["_roi_w"] = roi_w(c)
                c["_sig"] = sig_factor(c)
                selected.append(c)
                seen.append((hs, c["type_pari"]))
    return selected


def _allocate_kelly(selected: list[dict], montant: int, palier: dict, cfg: dict,
                    respect_montant: bool = False, min_keep: int = 1) -> None:
    """Dispatch `montant` (€ entiers) par fraction de KELLY réelle (ev/(cote-1))
    tiltée par le profil EFFECTIF (risk_pref) et le ROI passé. min_stake plancher ;
    plafond sur les paris spéculatifs (cap_spec). Total == montant exactement."""
    rp = cfg["risk_pref"]
    # Même plancher effectif que la sélection — jamais sous MISE_PLANCHER=2€ par pari.
    min_stake = max(MISE_PLANCHER, round(palier["min_stake"] * cfg.get("min_stake_factor", 1.0)))

    # Demi-Kelly : croissance du capital quasi-optimale à long terme, variance bien
    # moindre que le Kelly plein (qui sur-mise et ruine sur une série de pertes).
    KELLY_FRACTION = 0.5

    def weight(c):
        b = max(c["rapport_estime"] - 1.0, 0.1)
        f_full = max(c["ev"] / b, 0.0)          # fraction de Kelly PLEINE sur l'edge réel
        c["_kelly_f"] = round(f_full, 4)        # trace pour la justification du pari
        f = f_full * KELLY_FRACTION
        if f <= 0:                              # pas d'edge mesuré → mise minimale
            f = 0.012
        edge = max(c.get("edge", 0.0), 0.0)
        sig = float(c.get("_sig", 1.0) or 1.0)
        # CERTITUDE × CONVICTION : plus l'edge (modèle > marché) et le signal HISTORIQUE
        # validé sont forts, plus on engage → la mise se concentre sur l'avantage MESURÉ
        # (le moteur « réfléchit » combien risquer selon sa confiance). Renta long terme.
        certitude = (1.0 + 3.0 * edge) * (0.7 + 0.3 * min(sig, 2.0))
        # CAP anti sur-staking : le tilt de conviction (certitude×risk_pref×roi_w) est borné
        # à 2.0 → la demi-Kelly tiltée ne dépasse JAMAIS le Kelly PLEIN (0.5×2.0). Sans ce cap
        # le produit montait ~8× = bien au-dessus de Kelly plein = ruine sur série de pertes,
        # surtout edge surestimé (cf. audit edge : edge réel non prouvé).
        mult = min(certitude * rp.get(c["niveau"], 1.0) * c.get("_roi_w", 1.0), 2.0)
        return max(f * mult, 1e-3)

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

    # MONTANT SAISI = TOUT JOUÉ (respect_montant) : l'user a choisi sa mise, il veut qu'elle
    # soit JOUÉE EN ENTIER (pas de réserve). Le cap spéculatif (réserve sur paris -EV) ne vaut
    # QUE pour l'auto-staking (protège la bankroll). En manuel, on le SAUTE → 10€ saisi = 10€ joués.
    if not respect_montant:
        _apply_spec_cap(selected, montant, palier, min_stake)
    # FLAG staking_safe : en staking AUTO on NE force PAS le "gain target" (qui concentre
    # le budget vers la cible = plus de variance ; à éviter sur un système -EV, cf. audit
    # edge). MAIS sur le calculateur MANUEL (respect_montant) l'utilisateur a saisi un
    # montant et attend qu'il soit JOUÉ (pas une réserve de 60%) et un gain visé (≥×2.5
    # modéré) → on force le gain target. respect_montant prime sur staking_safe ici.
    try:
        from ml.algo_flags import FLAGS as _AF
        _skip_gain_target = _AF.staking_safe and not respect_montant
    except Exception:
        _skip_gain_target = False
    if not _skip_gain_target:
        _enforce_gain_target(selected, montant, cfg, min_stake, min_keep=min_keep)
    # GARDE-FOU FINAL anti « tout sur un Trio » : plafonne la mise de chaque pari
    # haute-variance à var_cap × montant, transfère l'excédent vers les paris plus
    # sûrs (ou d'autres gros-rapports décorrélés), sinon le laisse en réserve. Dernier
    # passage → ne peut pas être défait par la concentration du gain target.
    _apply_variance_cap(selected, montant, cfg, min_stake, respect_montant=respect_montant)


def _enforce_gain_target(selected: list[dict], montant: int, cfg: dict,
                         min_stake: int, min_keep: int = 1) -> None:
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

    # PRIORITÉ CONVICTION (corrigé) : on finance d'abord les paris à la PLUS FORTE conviction
    # (prio = kelly_f×roi_w×sig×proba), puis à conviction égale les moins chers à amener à la
    # cible. L'ancien tri (besoin d'abord) finançait les plus GROS rapports = les moins
    # probables = biais longshot destructeur d'EV. On garde le contrat (chaque pari gardé
    # atteint la cible) mais on engage le budget sur les paris les plus crédibles d'abord.
    ordered = sorted(selected, key=lambda c: (-prio(c), besoin(c)))
    kept: list[dict] = []
    reste = budget
    for c in ordered:
        need = besoin(c)
        if need <= reste:
            c["mise"] = need
            kept.append(c)
            reste -= need

    # CONTRAT DE GAIN PRIORITAIRE : chaque pari gardé atteint déjà la cible (besoin ≤ budget).
    # Si AUCUN pari ne peut l'atteindre même à plein budget, on concentre le budget sur UN
    # seul pari (mise franche) — mais sur le MEILLEUR pari par CONVICTION (prio), PAS sur le
    # plus gros rapport. L'ancien max(rapport) choisissait par construction le pari le moins
    # probable / le plus -EV du lot (biais longshot destructeur d'espérance, cf. audit edge).
    # On vise le gain via le pari le plus crédible, quitte à un multiple cible non atteint.
    if not kept:
        best = max(selected, key=prio)
        best["mise"] = budget
        best["_besoin"] = budget
        selected[:] = [best]
        return

    # Mémorise la mise PLANCHER de chaque pari gardé (celle qui garantit la cible ×g) → le
    # garde-fou variance final ne descendra JAMAIS en dessous (sinon le contrat serait rompu).
    for c in kept:
        c["_besoin"] = besoin(c)

    # DIVERSIFICATION (min_keep) : l'utilisateur veut PLUSIEURS paris en modere/risque
    # SAUF quasi-certitude (min_keep=1). Le contrat de gain ci-dessus concentre parfois sur
    # < min_keep paris (la cible x g exige presque tout le budget sur UN seul pari). On
    # retablit alors la couverture : on ajoute les meilleurs paris restants AU PLANCHER (ils
    # n'atteignent pas seuls la cible = diversification assumee), finances depuis le reliquat
    # puis, si epuise, en rognant le plus gros pari garde (jamais sous le plancher).
    if min_keep > len(kept):
        kept_ids = {id(c) for c in kept}
        for c in ordered:
            if len(kept) >= min_keep:
                break
            if id(c) in kept_ids:
                continue
            if reste >= min_stake:
                c["mise"] = min_stake
                c["_besoin"] = min_stake
                kept.append(c); kept_ids.add(id(c)); reste -= min_stake
            else:
                donor = max(kept, key=lambda x: x["mise"])
                if donor["mise"] - min_stake >= min_stake:
                    donor["mise"] -= min_stake
                    donor["_besoin"] = max(min_stake, int(donor.get("_besoin", min_stake)) - min_stake)
                    c["mise"] = min_stake
                    c["_besoin"] = min_stake
                    kept.append(c); kept_ids.add(id(c))
                else:
                    break

    # Reliquat → aux paris gardés par priorité (total dépensé == budget initial). Ne déplace
    # PAS un pari sous son besoin ; le reliquat ne fait qu'AUGMENTER les mises (gain ↑).
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


def _apply_variance_cap(selected: list[dict], montant: int, cfg: dict,
                        min_stake: int, respect_montant: bool = False) -> None:
    """Plafonne la mise de CHAQUE pari haute-variance (Trio/jackpot/Pick5/Multi 4-5) à
    `var_cap` × montant. L'excédent est transféré EN PRIORITÉ vers les paris plus sûrs
    (baisse réelle de la variance), à défaut vers les autres gros-rapports DÉCORRÉLÉS
    sous leur plafond, et en dernier recours laissé en RÉSERVE (non joué).

    C'est le correctif direct du bug « profil risqué = toute la mise sur un Trio » :
    même si le moteur de gain concentre tout sur un seul ticket tout-ou-rien, ce passage
    final le ramène à ≤ var_cap et étale le reste."""
    cap = float(cfg.get("var_cap", 1.0) or 1.0)
    if cap >= 1.0 or not selected:
        return
    ceil_amt = max(int(min_stake), int(montant * cap))
    hv = [c for c in selected if _is_high_variance(c)]
    if not hv:
        return
    moved = 0
    for c in hv:
        # Le plafond ne peut PAS descendre sous la mise PLANCHER du contrat de gain
        # (_besoin) : sinon un pari sizé pour garantir ×g serait raboté et le gain minimum
        # promis ne tiendrait plus. On ne rabote donc que l'excédent AU-DESSUS du besoin.
        floor_c = max(ceil_amt, int(c.get("_besoin", 0) or 0))
        if c["mise"] > floor_c:
            moved += c["mise"] - floor_c
            c["mise"] = floor_c
    if moved <= 0:
        return
    # 1) Vers les paris NON haute-variance (réduit vraiment le risque global).
    safe = sorted((c for c in selected if not _is_high_variance(c)),
                  key=lambda c: c["mise"])
    k = 0
    while moved > 0 and safe:
        safe[k % len(safe)]["mise"] += 1
        moved -= 1
        k += 1
    # 2) Sinon, répartir sur les autres gros-rapports encore sous leur plafond.
    if moved > 0:
        k = 0
        guard = 0
        slack = [c for c in hv if c["mise"] < ceil_amt]
        while moved > 0 and slack and guard < 10 ** 7:
            c = slack[k % len(slack)]
            if c["mise"] < ceil_amt:
                c["mise"] += 1
                moved -= 1
            k += 1
            guard += 1
            if all(c["mise"] >= ceil_amt for c in slack):
                break
    # 3) Reliquat éventuel.
    #    - Staking AUTO : → réserve (montant_joue < montant), assumé : mieux qu'un ticket
    #      loterie surdimensionné. _assemble_plan recalcule montant_joue depuis les mises.
    #    - Calculateur MANUEL (respect_montant) : PAS de réserve fantôme — l'utilisateur a
    #      saisi un montant et veut qu'il soit joué EN ENTIER. Quand il n'existe pas assez
    #      de paris décorrélés pour étaler sous le plafond, on déploie le reliquat sur les
    #      paris (priorité aux MOINS variants, puis mise la plus faible), quitte à dépasser
    #      le var_cap : mieux vaut une légère sur-mise répartie qu'un montant non joué.
    if moved > 0 and respect_montant and selected:
        order = sorted(selected, key=lambda c: (_is_high_variance(c), c["mise"]))
        k = 0
        while moved > 0:
            order[k % len(order)]["mise"] += 1
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
    if not r_type:
        fam = _fam(c["type_pari"])
        if fam.startswith("Multi en "):
            try:
                _n = int(fam.rsplit(" ", 1)[-1])
            except (ValueError, IndexError):
                _n = 0
            r_type = (
                f"Multi en {_n} : trouver les 4 premiers (désordre) parmi {_n} chevaux, "
                + ("large filet qui tombe SOUVENT — gagner régulièrement." if _n >= 6
                   else "champ serré à GROS rapport — gros lot pour une mise plate.")
            )
        elif fam == "Pick5":
            r_type = ("Pick5 : les 5 premiers dans le désordre (mise 1€, sans bonus) — "
                      "gros lot accessible, deux fois moins cher que le Quinté+.")
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
        # L arrondi ENTIER du gain ne doit jamais faire tomber le multiplicateur AFFICHE
        # sous la tranche du profil (ex. place x1.8 a 3e = 5.4 -> arrondi 5 -> x1.67 affiche).
        _rmin = PROFIL_CONFIG.get(profil, PROFIL_CONFIG["equilibre"]).get("rapport_min", 0.0) or 0.0
        if mise > 0 and _rmin > 0 and gain < math.ceil(mise * _rmin):
            gain = math.ceil(mise * _rmin)
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
    # HONNÊTETÉ (#3) : « sans value » = le modèle ne voit AUCUN edge (proba modèle > marché)
    # sur la course → nb_val == 0. On se base sur l'EDGE, pas sur l'espérance € : l'EV des
    # combinés est neutralisée à 0 (flag combo_ev_none, pool combiné non observable) donc un
    # plan risqué combo-only a toujours esp≈0 — l'inclure sur-flaggerait à tort le risqué.
    # Le prono reste affiché sur TOUTES les courses ; quand le marché est efficace, on le DIT.
    sans_value = (nb_val == 0)
    if sans_value:
        resume = (
            f"⚠️ Pas de value réelle détectée sur cette course "
            f"(espérance {'+' if esp >= 0 else ''}{esp:.2f}€) — le marché est efficace ici. "
            f"Plan {profil_label} pour le jeu plaisir : {nb_paris} pari{'s' if nb_paris > 1 else ''} "
            f"de {montant_joue}€, joue petit et avec modération" + mode_txt + "."
        )
    else:
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
        sans_value=sans_value,
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
def _plan_vide(montant: float, profil: str,
               resume: str = "Prédictions non disponibles pour cette course.",
               avert: str = "Lancez l'analyse IA avant de générer un plan.") -> MisePlan:
    return MisePlan(
        montant_total=montant, montant_joue=0, montant_reserve=montant,
        ev_global=0,
        niveaux=[],
        resume_ia=resume,
        avertissement=avert,
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
        "sans_value": plan.sans_value,
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
