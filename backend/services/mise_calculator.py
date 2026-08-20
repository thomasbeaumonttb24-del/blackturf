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

# Pénalité de mise sur l'incertitude du modèle (largeur IC proba_top1_high−low),
# appliquée en staking Kelly : discount = 1/(1 + CI_WIDTH_PENALTY × largeur).
# Ex. largeur 0.30 (grosse incertitude) → mise ×0.53 ; largeur 0.10 → ×0.77 ;
# largeur 0 (ou absente) → ×1.0 (aucun effet). Valeur POLICY, à valider Point 11.
CI_WIDTH_PENALTY = 3.0

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
#     • MODÉRÉ   : plus de risque, viser entre ×4 et ×15 → rapport ∈ [4, 15].
#     • RISQUÉ   : gros rapport, au moins ×10            → rapport_min = 10.
#   Les bandes se chevauchent volontairement : le profil module aussi probabilité,
#   type de pari et allocation. Le « pourquoi » reste justifié par le gain du ticket.
PROFIL_CONFIG = {
    # PRUDENT — privilégie le PLACÉ : Simple Placé, Duo Placé (Couplé Placé), 2/4.
    # Cote des chevaux COURTE (cote_max 9) = gain quasi assuré, MAIS on exige un
    # rapport ≥ 1.8 : on écarte le placé sec à 1.1× (argent mort).
    # Mises prudentes : peu de paris, plancher franc.
    # + SIMPLE GAGNANT « DOMINATEUR » (demande user) : quand un cheval ÉCRASE la course
    #   (proba victoire ≥ sg_min_proba) ET que sa cote tombe dans la bande (rapport
    #   1.8-4 = cote ~2-4), le gagnant sec est un pari prudent légitime — fréquence
    #   élevée, gain ≥ ×1.8. Gate sg_min_proba : jamais de SG prudent sur un cheval
    #   qui ne domine pas.
    "conservateur": {
        "cote_min": 0.0, "cote_max": 9.0, "rapport_min": 1.8, "rapport_max": 5.0,
        "min_proba": 0.20, "ev_min": -0.15, "max_coup": 0,
        "sg_min_proba": 0.34,
        "bets_factor": 0.9, "min_stake_factor": 1.0,
        # keep_frac : on garde les paris dont la conviction ≥ 65% du meilleur → le NB de
        # paris VARIE selon la course (1 si un placé domine, 2-3 si plusieurs comparables).
        "keep_frac": 0.65,
        # BANDE ×1.8–5 sur le GAIN / MISE TOTALE : comme le modéré/
        # risqué, le prudent passe désormais par l'allocation "spread" — chaque ticket GAGNANT
        # rend ≥ gain_cible_mult × le TOTAL (×1.8) et ≤ gain_cible_max × le TOTAL (×5).
        # rapport_min 1.8 garantit qu'un ticket plein budget atteint le plancher ;
        # min_proba 0.20 exclut les placés à gros rapport peu probables (le prudent reste FRÉQUENT).
        "gain_cible_mult": 1.8,
        "gain_cible_max": 5.0,
        "alloc": "spread",
        # Multi en 6/7 = large filet qui TOMBE SOUVENT (4 premiers dans 6-7 chevaux) →
        # parfait pour le prudent. Pas de Multi 4/5 (gros lot = trop rare). var_cap 1.0 :
        # le prudent n'a aucun pari haute-variance, le plafond est donc inerte.
        # Simple Gagnant autorisé UNIQUEMENT via le gate dominance (sg_min_proba).
        "types": {"Simple Placé", "Simple Gagnant", "Couplé Placé", "2sur4",
                  "Multi en 6", "Multi en 7"},
        "objectif": "proba",
        "var_cap": 1.0,
        "risk_pref": {"securite": 1.5, "rendement": 1.0, "surprise": 0.4, "coup": 0.2},
    },
    # MODÉRÉ — viser un rapport ENTRE ×4 et ×15 : duo gagnant, couplé placé, 2/4, trio
    # de favoris + SIMPLE GAGNANT à cote intéressante (cote 4-15 = rapport dans la
    # bande, demande user) + SIMPLE PLACÉ d'outsider quand son rapport tombe dans la
    # bande (placé payant ≥×4 = vrai pari modéré). Cotes chevaux capées à 20.
    # PETITES mises réparties sur PLUSIEURS combinaisons (spectre PMU).
    "equilibre": {
        # Bande de RAPPORT 4–15 : un pari à mise franche (10€) doit pouvoir rendre
        # ≥ ×4 du total → rapport ≥ 4. EV plus tolérante (-0.45) : le modéré vise le
        # GAIN (un duo/trio de favoris paie un rapport intermédiaire mais reste -EV à cause du prélèvement
        # PMU) — l'utilisateur préfère un vrai gain si ça passe à des micro-tickets +EV.
        "cote_min": 0.0, "cote_max": 20.0, "rapport_min": 4.0, "rapport_max": 15.0,
        # max_coup 3 : les combos/SG de favoris sont -EV (prélèvement PMU) donc classés
        # « spéculatifs » ; on en autorise jusqu'à 3 pour pouvoir COUVRIR le risque avec
        # 2 paris (ex. 2 SG cote ≥5). Bornés par la cible de gain + le nb de paris.
        # min_proba 0.08 (relevé de 0.04) : LIFT DU TAUX DE RÉUSSITE — un pari modéré
        # à moins de 8% de chances perd 12 fois sur 13, ça n'est plus du modéré.
        # sg_min_proba 0.11 : un SG modéré doit garder une chance réelle (~1/9).
        "min_proba": 0.08, "ev_min": -0.45, "max_coup": 3,
        "sg_min_proba": 0.11,
        # spec_coup : un duo/SG de favoris est -EV (prélèvement PMU) mais c'est un pari
        # de COUVERTURE légitime (gain réel si ça passe), pas un don au PMU comme un
        # longshot mort. On les autorise (bornés par ev_min -0.45 + max_coup + la cible
        # de gain) → le modéré peut jouer 2 SG cote ≥5 pour couvrir, au lieu d'1 ticket.
        "spec_coup": True,
        # keep_frac 0.50 : le NB de paris VARIE (1 ticket fort, ou 2-3 de couverture si
        # leur conviction reste proche du meilleur). Plus de blocage à un nombre fixe.
        "keep_frac": 0.50,
        "bets_factor": 1.2, "min_stake_factor": 1.0,
        # GAIN VISÉ (contrat produit) : un pari gagnant ≥ ×4 du TOTAL misé (10€ → ≥40€).
        # Appliqué sur TOUS les chemins d'allocation : _enforce_gain_target (Kelly) ET
        # _allocate_spread (manuel/figés) taillent la mise de CHAQUE ticket à
        # ceil(cible/rapport) ; un pari qui ne peut pas atteindre ×4 du total est écarté.
        "gain_cible_mult": 4.0,
        # Plafond de bande : chaque ticket gagnant ≤ ×15 du TOTAL misé (borne haute modéré).
        "gain_cible_max": 15.0,
        # Multi en 5/6/7 = rapports intermédiaires qui tombent assez souvent (cœur du modéré).
        # Simple Gagnant RÉTABLI mais borné à la bande : SG cote 4-15.
        # Simple Placé autorisé quand son rapport tombe dans la bande
        # (placé d'outsider payant ≥×4) — le placé sec ~×1.8 reste exclu par rapport_min.
        "types": {"Simple Gagnant", "Simple Placé", "Couplé Placé", "Couplé Gagnant",
                  "Couplé Ordre", "2sur4", "Trio",
                  "Multi en 5", "Multi en 6", "Multi en 7"},
        "objectif": "ev",
        # var_cap 0.30 : un pari haute-variance (Trio/2sur4-jackpot) ne prend JAMAIS plus de
        # 30% du budget → force ≥2 tickets décorrélés (Trio capé). Anti « tout sur un Trio ».
        "var_cap": 0.30,
        # alloc "spread" : bande de rapport PAR PARI + mise répartie en plusieurs petits
        # tickets pondérés conviction (remplace le dutching total qui collapsait sur 1 ticket).
        "alloc": "spread",
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
        "min_proba": 0.0, "ev_min": -0.25,
        # RENTA LONG TERME : on limite les paris PUREMENT spéculatifs (sans edge) à 2 ;
        # la mise se concentre sur les gros rapports À VALEUR (edge>0 / conviction signal
        # validée). max_coup borne le nb de tickets « loterie » sans avantage mesuré.
        "max_coup": 2, "spec_coup": True,
        # keep_frac 0.38 : risqué peut étaler PLUS de paris à gros rapport SI leur
        # conviction reste dans la bande ; sinon il en garde moins. Nombre DYNAMIQUE.
        "keep_frac": 0.38,
        "bets_factor": 2.4, "min_stake_factor": 0.34,
        # GAIN VISÉ (contrat produit) : un pari gagnant ≥ ×10 du TOTAL misé (10€ → ≥100€),
        # SANS plafond (rapport_max None → vise l'infini sur les gros coups). C'est LE
        # cœur du risqué, appliqué sur TOUS les chemins (_enforce_gain_target ET
        # _allocate_spread) : mise de chaque ticket = ceil(cible/rapport) — un ticket de
        # 2€ à rapport ×11 (~22€ = ×2.2 du plan) n'est PLUS un pari risqué valide.
        "gain_cible_mult": 10.0,
        # Pas de plafond de bande : le risqué vise ×10 → l'infini (gain_cible_max None).
        "gain_cible_max": None,
        # Multi en 4/5 (gros lot) + Pick5 = gros rapports assumés du profil risqué.
        "types": {"Couplé Gagnant", "Couplé Ordre", "2sur4", "Trio", "Trio Ordre",
                  "Super 4", "Simple Gagnant",
                  "Tiercé Désordre", "Quarté+ Désordre", "Quinté+ Désordre",
                  "Multi en 4", "Multi en 5", "Pick5"},
        "objectif": "gain",
        # var_cap 0.35 (resserré de 0.45) : le risqué reste 100% gros rapport, MAIS jamais
        # plus de 35% du budget sur un seul ticket → la mise s'étale sur ≥3 gros-rapports
        # DÉCORRÉLÉS (demande user : « plus de mises différentes en risqué », fini le
        # 10€ sur un seul Simple Gagnant).
        "var_cap": 0.35,
        # alloc "spread" : la bande ≥×10 s'applique PAR PARI (chaque ticket gagnant paie
        # ≥×10 SA mise) — le dutching à retour égal sur la mise TOTALE collapsait presque
        # toujours sur UN seul ticket (coef total < 10 dès le 2e pari) = l'inverse du
        # spectre large voulu pour ce profil.
        "alloc": "spread",
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
        # Bandes de RAPPORT = contrat produit (×1.8–5 / ×4–15 / ≥×10) → NON modulées par
        # le heat : le profil risqué doit TOUJOURS viser ≥×10, etc.
        "rapport_min": base.get("rapport_min", 0.0),
        "rapport_max": base.get("rapport_max"),
        "min_proba": max(0.0, base["min_proba"] * (1.0 - 0.30 * h)),
        # Gate dominance du Simple Gagnant (prudent : cheval qui écrase la course ;
        # modéré : chance réelle). Contrat produit → NON modulé par le heat.
        "sg_min_proba": base.get("sg_min_proba", 0.0),
        # Mode d'allocation en calculateur manuel : "spread" (bande par pari, plusieurs
        # petites mises) ou dutching total (défaut, prudent).
        "alloc": base.get("alloc"),
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
        # Plafond de bande (gain ≤ ×N du total). Contrat produit → NON modulé par le heat.
        "gain_cible_max": base.get("gain_cible_max"),
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
    rapport_calib: Optional[dict] = None,
    ev_band_perf: Optional[dict] = None,
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
    # Largeur de l'intervalle de confiance de proba_top1, PAR CHEVAL — sert à réduire la
    # mise Kelly (cf. _allocate_kelly.weight) quand l'incertitude du modèle est large,
    # sans toucher à combo_bets.py (la proba SIMULÉE reste inchangée, seul le STAKING en
    # tient compte). Absent → 0.0 (aucune pénalité, jamais d'incertitude inventée).
    ci_width_by_num: dict[int, float] = {}
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
        lo, hi = p.get("proba_top1_low"), p.get("proba_top1_high")
        if lo is not None and hi is not None:
            try:
                ci_width_by_num[int(p["numero"])] = max(0.0, float(hi) - float(lo))
            except (TypeError, ValueError):
                pass

    cands = enumerate_bet_candidates(preds, course_info)
    if not cands:
        return _plan_vide(montant, profil)
    if ci_width_by_num:
        for c in cands:
            c["_ci_width"] = max(
                (ci_width_by_num.get(int(h["numero"]), 0.0) for h in c.get("chevaux", [])
                 if h.get("numero") is not None), default=0.0)

    # CALIBRATION estimé→réel : recale le rapport (et donc l'EV) de chaque candidat sur le
    # rapport RÉEL appris par (profil × type), AVANT les gates de bande. Un Placé estimé
    # ×1.9 mais qui paie ×1.3 en réalité voit son rapport ramené sous la bande prudent →
    # écarté. C'est ce qui fait RESPECTER les tranches sur le réel (bilan), pas l'estimé.
    # edge (modèle vs marché) inchangé : il ne dépend pas du rapport parimutuel.
    if rapport_calib:
        try:
            from ml.signal_performance import rapport_realization_factor
            for c in cands:
                f = rapport_realization_factor(profil, c.get("type_pari"), rapport_calib)
                if f and f != 1.0:
                    c["rapport_estime"] = round(float(c["rapport_estime"]) * f, 1)
                    c["ev"] = round(float(c["proba_gain"]) * c["rapport_estime"] - 1.0, 4)
                    c["_rapport_cal_f"] = round(float(f), 3)
        except Exception:
            pass

    # CALIBRATION de la PROBABILITÉ, mesurée le 2026-08-19 sur 19 968 paris réglés :
    # le modèle annonce systématiquement plus souvent qu'il ne réalise (Simple
    # Gagnant 10,9 % annoncés → 8,9 % réels, Trio 5,3 % → 2,4 %). Comme
    # EV = proba × rapport − 1, une proba gonflée de 22 % affiche +10 % là où le
    # réel est −10 % : c'est ce qui rendait les bandes d'EV incapables de trier
    # (toutes à −8/−9 % de ROI réel) et le ROI global négatif.
    #
    # On corrige la proba AVANT l'EV et AVANT les gates, pour que tout l'aval —
    # sélection, dimensionnement, tranche de rapport — travaille sur une
    # probabilité qui tient devant les résultats.
    if rapport_calib:
        try:
            from ml.signal_performance import proba_realization_factor
            for c in cands:
                fp = proba_realization_factor(c.get("type_pari"), rapport_calib)
                if fp and fp != 1.0:
                    c["proba_gain"] = round(float(c["proba_gain"]) * fp, 4)
                    c["ev"] = round(float(c["proba_gain"]) * float(c["rapport_estime"]) - 1.0, 4)
                    c["_proba_cal_f"] = round(float(fp), 3)
        except Exception:
            pass

    # TILT PAR TRANCHE DE RAPPORT — le signal le plus solide de nos données (19 972
    # paris réglés) : le ROI réel décroît continûment avec le rapport visé. Simple
    # Gagnant ×4-8 rend -1,7 % ; le même pari au-delà de ×15 rend -15,4 %. Simple
    # Placé sous ×4 rend -7 % ; au-delà de ×4, -25 %. C'est le biais favori/outsider,
    # mesuré chez nous.
    #
    # C'est un TILT de préférence entre candidats, pas une barrière : la tranche de
    # rapport propre à chaque profil et la promesse d'un plan sur CHAQUE course
    # restent intactes.
    if rapport_calib:
        try:
            from ml.signal_performance import payout_bucket_multiplier
            for c in cands:
                c["_pb_mult"] = float(payout_bucket_multiplier(
                    c.get("type_pari"), c.get("rapport_estime"), rapport_calib))
        except Exception:
            pass

    # pool_couverture : candidats validés par les gates du profil mais écartés de la
    # sélection (conviction plus faible). Vivier des tickets de COUVERTURE.
    pool_couverture: list[dict] = []
    selected = _select_conviction(cands, montant, palier, cfg, roi_weights, signal_mults,
                                  respect_montant=respect_montant, ev_band_perf=ev_band_perf,
                                  pool_out=pool_couverture)
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

    # SIMPLE PLACÉ = JAMAIS éclaté en plusieurs tickets. Un placé paie < la mise totale
    # (≈×1.8-2.2) → si la mise est répartie sur 2-3 placés et qu'UN SEUL passe, le joueur
    # est PERDANT malgré un bon prono. On concentre sur LE placé le plus sûr (1 seul) : un
    # seul résultat positif = gain réel. Pour couvrir 2 chevaux au placé, c'est le Couplé
    # Placé (1 ticket), pas 2 Simple Placé.
    _sp = [c for c in selected if c.get("type_pari") == "Simple Placé"]
    if len(_sp) > 1:
        _keep = max(_sp, key=lambda c: c.get("proba_gain", 0.0))
        selected[:] = [c for c in selected if c.get("type_pari") != "Simple Placé" or c is _keep]

    if respect_montant:
        if cfg.get("alloc") == "spread":
            # MODÉRÉ / RISQUÉ : contrat de gain vs mise TOTALE — chaque ticket gagnant
            # rapporte ≥ gain_cible_mult × montant du plan (mise du ticket taillée à
            # ceil(cible/rapport)), diversification ≥2 tickets si possible, reliquat
            # ∝ conviction (proba×rapport, edge outsider, signal, bande d'EV).
            _min_stake_eff = max(MISE_PLANCHER,
                                 round(palier["min_stake"] * cfg.get("min_stake_factor", 1.0)))
            _allocate_spread(selected, montant, cfg, _min_stake_eff,
                             pool=pool_couverture,
                             nb_partants=(course_info or {}).get("nb_partants"))
        else:
            # PRUDENT : RESPECT STRICT DE LA TRANCHE DE COEFFICIENT (×1.8-4) SUR LA MISE
            # COMPLÈTE par DUTCHING : chaque gagnant unique rend le même total = coef ×
            # montant, coef = 1/Σ(1/rapport_i) calé dans la bande. Fonctionne bien sur les
            # petits rapports du prudent (ajouter un pari garde le coef dans la bande).
            selected = _enforce_band_dutch(selected, cfg)
            _allocate_dutch(selected, montant, cfg)
    else:
        min_keep = 2 if (len(selected) >= 2 and not _solo_confident(selected[0])) else 1
        _allocate_kelly(selected, montant, palier, cfg, respect_montant=respect_montant,
                        min_keep=min_keep)  # remplit "mise"
        # DISCIPLINE DE MISE — on ne joue pas la même somme sur une course où
        # l'argent revient et sur une course où il ne revient pas. Contrefactuel
        # mesuré sur 19 996 paris réglés : tout jouer rend −16,0 % ; concentrer sur
        # Simple Gagnant ×4-15 + Placé <×4 rend −6,1 % ; sur Simple Gagnant ×4-8
        # seul, −1,9 %. Le plan reste servi sur CHAQUE course : c'est la somme
        # engagée qui s'ajuste, le reliquat part en réserve (montant_reserve).
        #
        # Jamais appliqué quand l'utilisateur a SAISI un montant : il a demandé à
        # jouer cette somme-là, on la déploie en entier.
        _appliquer_discipline_mise(selected, montant, palier, cfg)
    ecartes = _paris_ecartes(cands, selected, cfg)
    return _assemble_plan(selected, montant, palier, kelly_warn, profil, heat,
                          facteurs_chevaux=facteurs_chevaux, ecartes=ecartes)


# Qualité mesurée d'une cellule (type × tranche de rapport), telle qu'apprise par
# `payout_bucket_multiplier` : 1.0 = tranche neutre, 0.60 = tranche qui a
# historiquement rendu le moins. On engage la mise pleine sur une cellule saine et
# on descend jusqu'à ce plancher sur les pires — sans jamais tomber à zéro, sinon
# le plan disparaîtrait.
DISCIPLINE_RATIO_PLANCHER = 0.40


def _appliquer_discipline_mise(selected: list[dict], montant: int,
                               palier: dict, cfg: dict) -> None:
    """Réduit la somme engagée quand les paris retenus tombent dans des tranches
    de rapport historiquement peu rentables. Modifie `selected` sur place."""
    if not selected:
        return
    plancher = max(MISE_PLANCHER,
                   round(palier["min_stake"] * cfg.get("min_stake_factor", 1.0)))
    for c in selected:
        avant = float(c.get("mise") or 0)
        if avant <= 0:
            continue
        # Ratio PAR PARI, sur sa propre cellule : un ticket sain ne doit pas être
        # rogné parce qu'un petit ticket annexe tombe dans une mauvaise tranche.
        # C'est aussi ce qui déplace le MÉLANGE de l'argent vers les bonnes
        # cellules, et pas seulement le total engagé.
        qualite = float(c.get("_pb_mult", 1.0) or 1.0)
        if qualite >= 1.0:
            continue
        # 0.60 (pire tranche mesurée) → 40 % de la mise ; 1.00 (neutre) → mise pleine.
        ratio = (DISCIPLINE_RATIO_PLANCHER
                 + (qualite - 0.60) * (1.0 - DISCIPLINE_RATIO_PLANCHER) / 0.40)
        ratio = max(DISCIPLINE_RATIO_PLANCHER, min(1.0, ratio))
        if ratio >= 0.995:
            continue
        c["mise"] = max(plancher, int(round(avant * ratio)))
        c["_discipline_ratio"] = round(ratio, 2)


def _dutch_coef(bets: list[dict]) -> float:
    """Coefficient DUTCHÉ d'un ensemble de paris : si un seul passe, le retour total vaut
    coef × mise complète (mise répartie pour égaliser le retour). coef = 1/Σ(1/rapport_i).
    Avec 1 pari → coef = son rapport. Plus on ajoute de paris, plus le coef BAISSE."""
    s = 0.0
    for b in bets:
        r = float(b.get("rapport_estime") or 0.0)
        if r > 0:
            s += 1.0 / r
    return (1.0 / s) if s > 0 else 0.0


def _enforce_band_dutch(selected: list[dict], cfg: dict) -> list[dict]:
    """Garde le plus grand sous-ensemble (par ordre de conviction) dont le coefficient
    DUTCHÉ reste DANS la bande du profil [rapport_min, rapport_max]. Comme ajouter un pari
    fait baisser le coef, on ajoute tant qu'on reste ≥ rapport_min (et ≤ rapport_max).
    Garantit ≥1 pari (la course reste jouée)."""
    if not selected:
        return selected
    rmin = float(cfg.get("rapport_min", 0.0) or 0.0)
    _rmax = cfg.get("rapport_max")
    rmax = float(_rmax) if _rmax is not None else None
    kept: list[dict] = []
    for c in selected:
        rt = _dutch_coef(kept + [c])
        if rt >= rmin and (rmax is None or rt <= rmax):
            kept.append(c)
    return kept or [selected[0]]


def _largest_remainder(raw: list[float], total: int) -> list[int]:
    """Arrondit des mises flottantes à l'euro en gardant la somme == total (plus forts
    restes servis en premier)."""
    floors = [int(x) for x in raw]
    rem = total - sum(floors)
    if rem > 0:
        order = sorted(range(len(raw)), key=lambda i: raw[i] - floors[i], reverse=True)
        for k in range(rem):
            floors[order[k % len(order)]] += 1
    return floors


def _allocate_dutch(selected: list[dict], montant: float, cfg: dict) -> None:
    """Dimensionne les mises par DUTCHING : chaque pari gagnant unique rend le MÊME total
    = coef × montant (coef dans la bande, garanti par _enforce_band_dutch). mise_i =
    montant / (rapport_i × Σ(1/rapport_j)). Si une mise tombe sous le plancher, on retire
    le plus petit pari (plus gros rapport) et on redutch. Total == montant exactement."""
    M = int(round(montant))
    bets = list(selected)
    while bets:
        s = sum(1.0 / float(b["rapport_estime"]) for b in bets
                if float(b.get("rapport_estime") or 0) > 0)
        if s <= 0 or len(bets) == 1:
            for b in bets:
                b["mise"] = 0
            bets[0]["mise"] = M
            break
        raw = [M / (float(b["rapport_estime"]) * s) for b in bets]
        mises = _largest_remainder(raw, M)
        if all(m >= MISE_PLANCHER for m in mises):
            for b, m in zip(bets, mises):
                b["mise"] = m
            break
        idx = min(range(len(bets)), key=lambda i: mises[i])   # plus petite mise = plus gros rapport
        bets.pop(idx)
    selected[:] = bets


# ─────────────────────────────────────────────────────────────
# TICKETS DE COUVERTURE
# ─────────────────────────────────────────────────────────────
# Le contrat produit « un ticket gagnant rend ≥ gain_cible_mult × la MISE TOTALE »
# (02/07) est arithmétiquement anti-diversification : financer N tickets exige
# Σ(1/rapport_i) ≤ 1/g. En modéré (g=4, bande ×4-15) ça plafonne à 1-3 tickets — et
# depuis la calibration des rapports et des probabilités (19/08), qui a fait baisser
# `rapport_estime` de 4 à 20 %, le besoin par ticket a monté et le plan tombait à UN
# SEUL ticket sur ~97 % des courses (mesuré : 1,55 → 1,00 pari/plan en modéré).
# Une seule chance de toucher par course = le joueur ne rejoue pas.
#
# On emploie donc le RELIQUAT — l'argent qui ne faisait sinon que grossir les mêmes
# tickets — à financer des paris D'APPOINT au plancher de mise. Décision produit du
# 2026-08-20 : ils portent EXACTEMENT le même contrat que les autres (≥ ×g de la MISE
# TOTALE), la tranche du profil se mesurant sur la mise totale SANS EXCEPTION. À 2€ de
# mise, cela impose un rapport ≥ cible/2 : peu de tickets qualifient, mais tous sont
# dans la tranche annoncée.
# Nombre de tickets de couverture visé selon le CHAMP de la course. Plus il y a de
# partants, plus l'issue est incertaine et plus il y a de combinaisons PMU réellement
# jouables : couvrir davantage y a du sens. À l'inverse, sur un champ réduit les
# combinaisons se ressemblent toutes — les multiplier n'ajoute pas de chances, ça
# ne fait que diviser la mise.
COUVERTURE_PAR_CHAMP = ((8, 2), (13, 3), (10 ** 9, 4))
# Part du budget mise de côté pour la couverture QUAND le contrat ne finance qu'un seul
# ticket. Bornée à 0.60 : le ticket principal doit garder de quoi tenir la cible de gain
# du profil, sinon on troque la promesse contre du saupoudrage.
COUVERTURE_PART_MAX = 0.60


def _couverture_max(nb_partants: Optional[int]) -> int:
    """Nb max de tickets de couverture selon le nombre de partants (None → valeur
    médiane : on n'invente pas un grand champ quand l'info manque)."""
    if not nb_partants:
        return 3
    for seuil, n in COUVERTURE_PAR_CHAMP:
        if int(nb_partants) <= seuil:
            return n
    return COUVERTURE_PAR_CHAMP[-1][1]


def _ordre_couverture(restants: list[dict]) -> list[dict]:
    """Ordre de financement de la couverture : on ALTERNE deux logiques au lieu d'en
    empiler une seule.

      • FRÉQUENCE — le pari le plus probable : il fait monter les chances de toucher.
      • GROS LOT  — le plus gros rapport : petite mise qui peut rapporter beaucoup,
        « ça élargit le champ des possibles » (demande user 2026-08-20).

    Trois tickets de couverture triés par la seule probabilité finissent par être trois
    variantes du même pari ; alterner donne un vrai éventail. Tous les candidats ont déjà
    passé les gates du profil, donc le « gros lot » reste dans la bande du profil."""
    par_freq = sorted(restants, key=lambda b: (float(b.get("proba_gain") or 0.0),
                                               float(b.get("rapport_estime") or 0.0)),
                      reverse=True)
    par_gain = sorted(restants, key=lambda b: (float(b.get("rapport_estime") or 0.0),
                                               float(b.get("proba_gain") or 0.0)),
                      reverse=True)
    ordre, vus = [], set()
    for i in range(max(len(par_freq), len(par_gain))):
        for source in (par_freq, par_gain):
            if i < len(source) and id(source[i]) not in vus:
                vus.add(id(source[i]))
                ordre.append(source[i])
    return ordre


def _chevaux_set(b: dict) -> frozenset:
    return frozenset(int(h["numero"]) for h in b.get("chevaux", [])
                     if h.get("numero") is not None)


def _couvre_deja(b: dict, deja: list[dict]) -> bool:
    """Un ticket de couverture n'a d'intérêt que s'il couvre AUTRE CHOSE que ce qui est
    déjà joué. Même règle de doublon que la sélection : même combinaison, combo du même
    type ne différant que d'un cheval, ou recouvrement ≥ 67 %."""
    hs = _chevaux_set(b)
    for s in deja:
        ss = _chevaux_set(s)
        if hs == ss:
            return True
        if s.get("type_pari") != b.get("type_pari"):
            continue
        inter = len(hs & ss)
        if len(hs) >= 3 and inter >= max(len(hs), len(ss)) - 1:
            return True
        if inter / max(len(hs | ss), 1) >= 0.67:
            return True
    return False


def _financer_couverture(kept: list[dict], selected: list[dict], reste: int,
                         montant: int, cfg: dict,
                         pool: Optional[list[dict]] = None,
                         cov_max: int = 3, cible: float = 0.0) -> int:
    """Finance des paris D'APPOINT sur le reliquat : petite mise, GROS rapport.

    Ils tiennent EXACTEMENT le même contrat que les autres tickets du plan — gagnants,
    ils rendent ≥ `cible` (= gain_cible_mult × la MISE TOTALE du plan). Décision produit
    du 2026-08-20 : la tranche du profil se mesure sur la mise totale, SANS EXCEPTION.
    Un ticket qui n'atteint pas la cible à la mise plancher n'est donc pas financé —
    mieux vaut un plan plus court qu'un ticket hors tranche.

    La contrepartie est mécanique : à 2€ de mise sur un plan de 10€, il faut un rapport
    ≥ cible/2 (×20 en modéré, ×50 en risqué). Seuls de très gros rapports qualifient,
    d'où « peu de tickets, mais tous dans la tranche ».

    Mise = MISE_PLANCHER (2€) et non le plancher du PALIER : ce dernier existe pour
    « tuer le saupoudrage », or ici la mise est minimale précisément parce que le rapport
    visé est élevé. Le plancher produit « jamais 1€ » reste respecté.

    Aucun pari inventé ni hors profil : ils sortent de `selected` ou de `pool`, deux
    listes qui ont déjà passé TOUTES les gates du profil (type autorisé, bande de
    rapport, cote, probabilité, EV) — ils étaient simplement moins convaincants."""
    if not kept:
        return reste
    mise_cov = MISE_PLANCHER
    if reste < mise_cov:
        return reste
    pris = {id(b) for b in kept}
    # D'abord les paris SÉLECTIONNÉS non financés (les plus convaincants), puis le vivier
    # des candidats validés par les gates du profil mais écartés par la bande de
    # conviction. Sans ce vivier, un plan dont la sélection tient en 1 pari (cas du
    # prudent) n'a jamais de couverture possible.
    restants = [b for b in selected if id(b) not in pris]
    if pool:
        vus = pris | {id(b) for b in restants}
        restants += [b for b in pool if id(b) not in vus]
    if not restants:
        return reste
    var_cap = float(cfg.get("var_cap", 1.0) or 1.0)
    cap_hv = max(mise_cov, int(montant * var_cap)) if var_cap < 1.0 else montant
    restants = _ordre_couverture(restants)
    ajoutes = 0
    for b in restants:
        if ajoutes >= cov_max or reste < mise_cov:
            break
        if _is_high_variance(b) and mise_cov > cap_hv:
            continue                      # plafond de variance : ticket non finançable
        # CONTRAT DE GAIN, sans exception : à la mise plancher, le ticket doit rendre
        # ≥ la cible du profil sur la MISE TOTALE du plan.
        if cible > 0 and mise_cov * float(b.get("rapport_estime") or 0.0) < cible:
            continue
        if _couvre_deja(b, kept):
            continue                      # ne couvre rien de nouveau → inutile
        # RÈGLE PRODUIT : le Simple Placé n'est JAMAIS éclaté en plusieurs tickets (il
        # paie moins que la mise totale → deux placés dont un seul passe = perdant).
        # Pour couvrir deux chevaux au placé, c'est le Couplé Placé, pas 2 Simple Placé.
        if (b.get("type_pari") == "Simple Placé"
                and any(k.get("type_pari") == "Simple Placé" for k in kept)):
            continue
        b["mise"] = mise_cov
        b["_besoin"] = mise_cov
        kept.append(b)
        reste -= mise_cov
        ajoutes += 1
    return reste


def _allocate_spread(selected: list[dict], montant: float, cfg: dict, min_stake: int,
                     pool: Optional[list[dict]] = None,
                     nb_partants: Optional[int] = None) -> None:
    """Allocation « SPREAD » (modéré/risqué, calculateur manuel & pronos figés).

    CONTRAT DE GAIN vs MISE TOTALE (demande user 2026-07-02) : chaque ticket GAGNANT
    doit rapporter ≥ gain_cible_mult × le MONTANT TOTAL du plan — 10€ en risqué →
    tout ticket gagnant rend ≥ 100€, quel que soit le type de pari. L'ancienne bande
    « par pari » (rapport ≥ ×10 de SA mise) laissait passer un ticket de 2€ sur un plan
    de 10€ qui ne rendait que ~23€ (= ×2.3 du plan).

    La mise de chaque ticket est DIMENSIONNÉE à son besoin = ceil(cible / rapport) :
    un gros rapport permet une petite mise, un rapport proche de la bande exige une
    mise franche. Un ticket qui ne peut pas atteindre la cible dans le budget restant
    n'est PAS financé (moins de tickets, mises justes). On cherche d'abord la
    DIVERSIFICATION (≥2 tickets — jamais un seul gros ticket si évitable) : financement
    par conviction, puis si ça ne donne qu'un ticket, par besoin croissant (les plus
    gros rapports d'abord = plus de tickets finançables).

    Le reliquat se répartit ∝ conviction de mise (proba×rapport, tilt edge/signal
    appris/bande d'EV — l'argent se concentre sur l'avantage MESURÉ) et ne fait
    qu'AUGMENTER les gains au-dessus de la cible. var_cap plafonne les tickets HAUTE
    VARIANCE (Trio/jackpots/Pick5) — un ticket HV dont le besoin dépasse ce plafond
    n'est pas finançable (le contrat de gain ne justifie pas de tout risquer sur un
    tout-ou-rien). Un plafond de bande HAUT (gain ≤ gain_cible_max × total) borne le reliquat
    de chaque mise → un ticket gagnant ne sort pas non plus par le HAUT de sa tranche. Somme
    des mises == montant exactement (reliquat résiduel posé sur le plus faible rapport)."""
    M = int(round(montant))
    if not selected or M <= 0:
        return
    var_cap = float(cfg.get("var_cap", 1.0) or 1.0)
    cap_hv = max(min_stake, int(M * var_cap)) if var_cap < 1.0 else M
    g = float(cfg.get("gain_cible_mult", 0.0) or 0.0)
    _gmax = cfg.get("gain_cible_max")
    gmax = float(_gmax) if _gmax else None          # None = pas de plafond de bande (risqué)

    def _w(b):
        # Conviction de MISE : espérance de retour (proba × rapport, capé ×40 anti-
        # loterie) × valeur outsider détectée (edge modèle>marché) × signal appris du
        # profil × ROI réel de la bande d'EV. C'est ce qui adapte la mise à la fiabilité.
        p = float(b.get("proba_gain") or 0.0)
        r = max(float(b.get("rapport_estime") or 1.0), 1.01)
        edge = max(float(b.get("edge") or 0.0), 0.0)
        sig = max(0.5, min(float(b.get("_sig", 1.0) or 1.0), 2.0))
        evb = float(b.get("_evb", 1.0) or 1.0)
        return max(p * min(r, 40.0), 0.05) * (1.0 + 3.0 * edge) * sig * evb

    def _cap(b):
        # Plafond de mise = variance (HV) ∩ borne HAUTE de bande (gain = rapport×mise ≤
        # gmax × total). Au-delà, le ticket sortirait par le HAUT de la tranche du profil.
        c = cap_hv if _is_high_variance(b) else M
        if gmax:
            r = max(float(b.get("rapport_estime") or 1.0), 1.01)
            c = min(c, int(gmax * M / r))
        return max(c, 0)

    if g <= 0:
        # Pas de cible de gain (défensif — les profils spread en ont toujours une) :
        # plancher + extra ∝ conviction, plafond HV.
        n = min(len(selected), max(1, M // max(min_stake, 1)))
        bets = selected[:n]
        ws = [_w(b) for b in bets]
        tw = sum(ws) or 1.0
        extra = M - min_stake * len(bets)
        add = _largest_remainder([extra * w / tw for w in ws], extra)
        for b, a in zip(bets, add):
            b["mise"] = min_stake + a
        selected[:] = bets
        return

    def _besoin(b, cible):
        r = max(float(b.get("rapport_estime") or 1.0), 1.01)
        return max(min_stake, math.ceil(cible / r))

    def _fund(order, cible, budget=None):
        kept, reste = [], (M if budget is None else int(budget))
        for b in order:
            n = _besoin(b, cible)
            if n <= reste and n <= _cap(b):
                kept.append(b)
                reste -= n
        return kept, reste

    def _best_diversified(cible, budget=None):
        """Meilleur plan pour une cible : ordre conviction, repli ordre besoin croissant
        (les plus gros rapports coûtent le moins → plus de tickets). Rend le plus fourni."""
        k1, r1 = _fund(selected, cible, budget)
        if len(k1) < 2 and len(selected) > 1:
            k2, r2 = _fund(sorted(selected, key=lambda b: (_besoin(b, cible), -_w(b))),
                           cible, budget)
            if len(k2) > len(k1):
                return k2, r2, cible
        return k1, r1, cible

    # CIBLE FIXE = g × total (demande user 2026-07-13) : on n'ABAISSE JAMAIS la cible sous
    # la bande pour forcer la diversification — un ticket rendant < ×g du total violerait la
    # tranche du profil (c'était le bug « modéré ×2 au lieu de ×4 »). Moins de tickets à bande
    # RESPECTÉE > plus de tickets hors bande.
    cible = g * M
    kept, reste, cible = _best_diversified(cible)
    # RÉSERVE DE COUVERTURE — le contrat ×g est glouton : dimensionné sur le budget
    # ENTIER il finance souvent UN seul ticket qui absorbe tout, et la course n'offre
    # alors qu'une seule chance de toucher. Quand c'est le cas, on met de côté une part
    # du budget AVANT de dimensionner le ticket principal, pour financer des paris de
    # couverture. On ne le fait PAS si le contrat finance déjà ≥2 tickets : un ticket
    # contractuel (multiplicateur du profil tenu) vaut mieux qu'un ticket de couverture.
    # QUASI-CERTITUDE : quand le modèle est vraiment sûr d'un pari, on ne dilue pas —
    # toute la mise part dessus, sans réserve ni couverture (demande user : « si confiant
    # d'un cheval jouer un seul, sinon proposer plusieurs »). Le nombre de paris est donc
    # piloté par l'ANALYSE de la course, pas par un cap fixe.
    solo = bool(selected) and _solo_confident(selected[0])
    # Le nombre de tickets de couverture suit le CHAMP de la course : 2 sur un champ
    # réduit (≤8), 3 jusqu'à 13, 4 au-delà. Un grand champ = issue plus incertaine et
    # plus de combinaisons PMU réellement jouables → couvrir davantage a du sens.
    cov_max = _couverture_max(nb_partants)
    # RÉSERVE DE COUVERTURE — systématique, pas seulement quand le contrat ne finance
    # qu'un ticket. Dimensionné sur le budget ENTIER, le contrat ×g est glouton : deux
    # tickets contractuels à 4€ et 6€ absorbent un plan de 10€ et il ne reste rien pour
    # élargir l'éventail. On met donc la part de couverture de côté AVANT de dimensionner
    # les tickets contractuels, et on la rend par paliers de 2€ tant qu'aucun ticket
    # contractuel n'entre dans le budget restant — la promesse ×g passe avant le nombre.
    if not solo and (len(selected) > 1 or pool):
        res = min(cov_max * MISE_PLANCHER, int(M * COUVERTURE_PART_MAX))
        while res >= MISE_PLANCHER:
            k2, r2, _ = _best_diversified(cible, M - res)
            if k2:
                kept, reste = k2, r2 + res
                break
            res -= MISE_PLANCHER          # le principal n'entre plus : on rend du budget
    if not kept:
        # Aucun ticket n'atteint la cible sous son plafond (ne peut arriver que via le
        # filet hors-bande) → tout le budget sur le plus convaincant NON haute-variance
        # (à défaut le plus convaincant) : c'est le gain max atteignable sur ce plan.
        pool = [b for b in selected if not _is_high_variance(b)] or list(selected)
        best = max(pool, key=_w)
        best["mise"] = M
        best["_besoin"] = M
        selected[:] = [best]
        return
    for b in kept:
        b["mise"] = _besoin(b, cible)
        b["_besoin"] = b["mise"]                       # plancher contractuel (trace)
    # COUVERTURE : le reliquat finance d'ABORD des paris SUPPLÉMENTAIRES (cf.
    # _financer_couverture) avant de grossir les tickets contractuels. Objectif =
    # augmenter le nombre de chances de toucher sur la course, pas le gain d'un ticket.
    if not solo:
        reste = _financer_couverture(kept, selected, reste, M, cfg, pool=pool,
                                     cov_max=cov_max, cible=cible)
    # Reliquat ∝ conviction — les mises ne font que MONTER (gain ≥ cible préservé). Le
    # plancher de bande (×g du total) est STRICT (dimensionnement `besoin`). Le PLAFOND de
    # bande (gain ≤ gmax×total) borne le reliquat : on ne charge pas un ticket au-delà de sa
    # tranche tant qu'un autre peut absorber. La sélection amont complète le plan avec assez
    # de tickets pour absorber la totalité. Le filet final conserve l'invariant produit
    # « montant saisi = montant joué » même sur une course atypique.
    if reste > 0:
        # Le reliquat grossit en priorité les tickets dimensionnés par la conviction ;
        # les tickets d'appoint restent au plancher (leur rapport est déjà très élevé,
        # les charger les ferait sortir par le HAUT de la tranche). Si tout est au
        # plafond, la boucle de secours plus bas absorbe le reste — l'invariant
        # « montant saisi = montant joué » prime.
        cibles = [b for b in kept if b.get("mise") != MISE_PLANCHER] or kept
        ws = [_w(b) for b in cibles]
        tw = sum(ws) or 1.0
        add = _largest_remainder([reste * w / tw for w in ws], reste)
        overflow = 0
        for b, a in zip(cibles, add):
            take = min(a, max(_cap(b) - b["mise"], 0))
            b["mise"] += take
            overflow += a - take
        guard = 0
        while overflow > 0 and guard < 10 ** 6:
            placed = False
            for b in kept:
                if b["mise"] < _cap(b):
                    b["mise"] += 1
                    overflow -= 1
                    placed = True
                    if overflow <= 0:
                        break
            guard += 1
            if not placed:
                break                       # tous au plafond de bande
        if overflow > 0:
            # Invariant absolu du calculateur manuel : aucune réserve. Ce filet ne doit
            # servir que si le catalogue ne fournit pas assez de tickets compatibles.
            pool = [b for b in kept if not _is_high_variance(b)] or kept
            tgt = min(pool, key=lambda b: float(b.get("rapport_estime") or 1.0))
            tgt["mise"] += overflow
    selected[:] = kept


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
    return (p >= 0.55
            or (p >= 0.45 and edge > 0.0)
            or (p >= 0.38 and edge > 0.02 and sig >= 1.10))


def _bet_cote_max(c: dict) -> float:
    """Cote la plus élevée parmi les chevaux d'un pari (mesure de risque du pari)."""
    cotes = [float(h.get("cote") or 0.0) for h in c.get("chevaux", [])]
    return max(cotes) if cotes else 0.0


def _select_conviction(
    cands: list[dict], montant: int, palier: dict, cfg: dict, roi_weights: dict,
    signal_mults: Optional[dict] = None, respect_montant: bool = False,
    ev_band_perf: Optional[dict] = None, pool_out: Optional[list] = None,
) -> list[dict]:
    """Sélectionne PEU de paris à FORTE conviction (EV × proba × edge × ROI passé),
    filtrés par les GATES du profil EFFECTIF (cote_max, min_proba, ev_min, max_coup).
    Profitabilité d'abord ; concentre. Le profil change donc VRAIMENT quels paris.

    `pool_out` (optionnel) reçoit TOUS les candidats ayant passé les gates du profil,
    y compris ceux écartés par la bande de conviction ou le plafond de paris. C'est le
    vivier des tickets de COUVERTURE : des paris déjà validés par la méthode du profil,
    simplement moins convaincants que le principal — jamais des paris hors profil.
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
    # Borne HAUTE effective sur le rapport d'un candidat : la bande produit porte sur
    # gain / MISE TOTALE, pas sur le rapport du ticket. Un ticket fractionné (mise < total)
    # peut donc avoir un rapport > rapport_max tout en restant dans la bande — l'allocation
    # spread le dimensionne pour que gain ≤ rapport_max × total. On ne rejette à la sélection
    # QUE si, même au plancher de mise, le gain dépasse la bande : rap > rapport_max × M / min_stake.
    rapport_max_eff = (rapport_max * montant / max(min_stake, 1)) if rapport_max is not None else None
    min_proba = cfg["min_proba"]
    ev_min = cfg["ev_min"]
    allowed_types = cfg.get("types")                         # None = toutes
    objectif = cfg.get("objectif", "ev")
    spec_ok = cfg.get("spec_coup", False)                     # profil loterie : coups -EV assumés
    SPEC_EV_FLOOR = -0.40                                     # plancher d'EV même pour un coup assumé (relevé de -0.80 : -80% = loterie pure, ruine garantie ; -40% laisse passer les vrais gros rapports à edge>0 via _is_credible_coup)
    # Gate bande d'EV (audit ROI 2026-07-02) : actif par défaut, rollback BT_EV_BAND_GATE=0.
    try:
        from ml.algo_flags import FLAGS as _AF_GATE
        _ev_gate = _AF_GATE.ev_band_gate
    except Exception:
        _ev_gate = True
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

    def evb(c):
        """Multiplicateur de conviction PAR BANDE D'EV, appris du ROI réel (zones toxiques
        EV>1.4 rétrogradées, bandes rentables promues). Neutre (1.0) sans table. Borné
        [0.5,1.6] → adapte la conviction ET la mise vers ce qui RAPPORTE, sans bannir."""
        if not ev_band_perf:
            return 1.0
        try:
            from ml.signal_performance import ev_band_multiplier
            return float(ev_band_multiplier(float(c.get("ev", 0.0) or 0.0), ev_band_perf))
        except Exception:
            return 1.0

    def conviction(c):
        """Classement selon l'OBJECTIF du profil (× ROI réel passé du type × signal ×
        ROI réel de la bande d'EV × ROI réel de la TRANCHE DE RAPPORT).

        La tranche de rapport est, de loin, le facteur le mieux étayé : le ROI réel
        y décroît continûment (Simple Gagnant −1,7 % en ×4-8 contre −15,4 % au-delà
        de ×15, sur des milliers de paris). La bande d'EV, elle, ne trie rien.
        """
        rw = (roi_w(c) * sig_factor(c) * evb(c)
              * float(c.get("_pb_mult", 1.0) or 1.0))
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
            # RAPPORT CAPÉ à ×40 dans le CLASSEMENT (pas dans le pari) : les rapports
            # parimutuels estimés ×200-600 des combos d'outsiders gonflent mécaniquement
            # le « payout » et faisaient collapser le risqué sur 5 tickets à 0-1% de
            # proba (pure loterie, zéro pari qui passe). Capé, un SG cote 14 à 8% bat un
            # duo d'outsiders à 0.2% → le risqué mixe gros rapports RÉALISTES et 1-2
            # vrais coups (quota max_coup), et regagne un taux de réussite non nul.
            payout = min(c["rapport_estime"], 40.0) * c["proba_gain"]
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
        # BANDE DE RAPPORT = séparateur produit (×1.8–5 / ×4–15 / ≥×10). Le pari doit
        # rapporter dans la fourchette du profil, sinon il appartient à un autre profil.
        rap = float(c.get("rapport_estime", 0.0) or 0.0)
        if rap < rapport_min:                                # rapport trop faible pour ce profil
            return False
        if rapport_max_eff is not None and rap > rapport_max_eff:  # même au plancher, gain hors bande haute
            return False
        if c["proba_gain"] < min_proba:                      # trop improbable
            return False
        # GATE DOMINANCE du SIMPLE GAGNANT : le gagnant sec n'entre dans un profil que si
        # le cheval a la proba de victoire requise (prudent 0.34 = domine la course ;
        # modéré 0.11 = chance réelle ; risqué 0 = pas de gate). La bande de rapport fait
        # déjà la séparation de cote (prudent ~2-4, modéré 4-10, risqué ≥10).
        if c["type_pari"] == "Simple Gagnant" and c["proba_gain"] < cfg.get("sg_min_proba", 0.0):
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
        # SIMPLE GAGNANT « DOMINATEUR » prudent : même esprit que le placé — pari de
        # FRÉQUENCE (proba ≥ sg_min_proba déjà vérifiée, cote dans la bande 1.8-4) →
        # exempté des gates d'EV stricts, MAIS jamais sur une sur-cote franche du
        # marché (ev < -0.12 = le marché paie trop peu ce favori, argent mort).
        if objectif == "proba" and c["type_pari"] == "Simple Gagnant":
            return c["ev"] >= -0.12
        # RÈGLE DE PROFITABILITÉ : jamais un pari à la fois -EV ET sans edge (= don au
        # PMU) — SAUF profil "coup" (risqué) qui assume des paris gros-lot spéculatifs,
        # bornés ensuite par max_coup + cap_spec. On exclut quand même la loterie pure
        # (EV sous le plancher SPEC_EV_FLOOR).
        if c["ev"] < 0 and c.get("edge", 0.0) <= 0:
            if not spec_ok or c["ev"] < SPEC_EV_FLOOR:
                return False
            # GATE BANDE D'EV (flag ev_band_gate, audit ROI 2026-07-02) : même le
            # profil "coup" n'engage plus un spéculatif dont la bande d'EV a un ROI
            # réel shrinké franchement négatif (multiplier ≤ 0.80, ex. bande EV<0
            # mesurée à −21% sur 7 320 paris). Le filet « chaque course jouée »
            # reste intact (fallback hors gates). Neutre sans table (evb=1.0).
            if _ev_gate and evb(c) <= 0.80:
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
    if pool_out is not None:
        pool_out[:] = ranked
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
            return r >= rapport_min and (rapport_max_eff is None or r <= rapport_max_eff)

        # Replis successifs : type+rapport+cote → type+rapport → rapport tout type →
        # type → tout. On garde la tranche du profil le plus longtemps possible.
        in_band = [c for c in cands if _in_type(c) and _in_rapport(c)
                   and cote_min <= _bet_cote_max(c) <= cote_max]
        in_band = in_band or [c for c in cands if _in_type(c) and _in_rapport(c)]
        # CHAQUE COURSE EST JOUÉE (demande user) : on PRIVILÉGIE la bande de rapport du
        # profil, mais si AUCUN pari n'y tombe on RELÂCHE par étapes plutôt que de laisser
        # le plan vide — type+cote du profil → type seul → n'importe quel pari. On garde la
        # MÉTHODE du profil le plus longtemps possible ; on ne relâche le rapport qu'en
        # dernier recours, et on le SIGNALE (note honnête, le multiplicateur visé n'est pas
        # garanti sur cette course). Aucune invention : ce sont de vrais paris PMU éligibles.
        relaxed = (
            [c for c in cands if _in_rapport(c)]
            or [c for c in cands if _in_type(c) and cote_min <= _bet_cote_max(c) <= cote_max]
            or [c for c in cands if _in_type(c)]
            or list(cands)
        )
        pool = in_band or relaxed
        if pool:
            def _fallback_score(c):
                """Meilleur compromis disponible quand toutes les gates ont échoué.

                L'ancien repli agressif prenait le rapport maximal, donc presque toujours
                la combinaison la moins probable. On conserve la promesse d'un plan sur
                chaque course, mais on minimise ce coût : probabilité prioritaire en
                prudent, rendement attendu capé en modéré/risqué, puis pondérations
                historiques atténuées (jamais nulles puisque ce chemin est un secours).
                """
                p = max(float(c.get("proba_gain", 0.0) or 0.0), 0.0)
                r = max(float(c.get("rapport_estime", 1.0) or 1.0), 1.0)
                edge = max(float(c.get("edge", 0.0) or 0.0), 0.0)
                learned = max(0.10, min(2.0, roi_w(c)))
                signal = max(0.50, min(2.0, sig_factor(c)))
                band = max(0.50, min(1.60, evb(c)))
                # Même tilt qu'en sélection normale : c'est justement sur ce chemin
                # de secours, où toutes les gates ont échoué, qu'il faut éviter de
                # retomber sur la tranche de rapport la moins rentable.
                tranche = max(0.60, min(1.40, float(c.get("_pb_mult", 1.0) or 1.0)))
                base = p if objectif == "proba" else p * min(r, 40.0)
                return base * (1.0 + 2.0 * edge) * learned * signal * band * tranche

            safe = max(pool, key=lambda c: (_fallback_score(c), c["proba_gain"]))
            safe["_roi_w"] = roi_w(safe)
            safe["_sig"] = sig_factor(safe)
            # Hors bande de rapport visée → marqué pour la note du plan.
            if not in_band:
                safe["_hors_bande"] = True
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
                # GATE DUR appris (poids 0 = type prouvé perdant / jamais gagnant) :
                # le complément manuel ne réintroduit PAS un type supprimé.
                if roi_weights.get(c["type_pari"], 1.0) <= 0.001:
                    return False
                bc = _bet_cote_max(c)
                if bc > cote_max:
                    return False
                if bc < cote_min and "Désordre" not in c["type_pari"]:
                    return False
                rap = float(c.get("rapport_estime", 0.0) or 0.0)
                if rap < rapport_min or (rapport_max_eff is not None and rap > rapport_max_eff):
                    return False
                if c["proba_gain"] < min_proba:
                    return False
                return c["ev"] >= SPEC_EV_FLOOR        # exclut la loterie pure (EV planchée)

            seen = [(frozenset(int(h["numero"]) for h in c.get("chevaux", [])), c["type_pari"])
                    for c in selected]
            # Spectre VARIÉ : max 3 tickets d'une même famille de pari dans le complément
            # (ex. 3 Simple Gagnant max → le 4e ticket sera un duo/trio, pas un 4e SG).
            _type_counts: dict[str, int] = {}
            for s in selected:
                _type_counts[_fam(s["type_pari"])] = _type_counts.get(_fam(s["type_pari"]), 0) + 1
            for c in sorted(cands, key=conviction, reverse=True):
                if len(selected) >= need_bets:
                    break
                if any(c is s for s in selected) or not _relaxed_ok(c):
                    continue
                if _type_counts.get(_fam(c["type_pari"]), 0) >= 3:
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
                _type_counts[_fam(c["type_pari"])] = _type_counts.get(_fam(c["type_pari"]), 0) + 1
    # ROI réel appris de la bande d'EV de chaque pari retenu → la MISE (Kelly) se déplace
    # vers les bandes rentables et s'allège sur les toxiques. Neutre (1.0) sans table.
    for c in selected:
        c["_evb"] = round(evb(c), 4)
    return selected


def _uncertainty_discount(ci_width) -> float:
    """discount = 1/(1 + CI_WIDTH_PENALTY × largeur IC) ∈ (0, 1]. Largeur absente/None
    → 1.0 (aucun effet, jamais d'incertitude inventée)."""
    w = float(ci_width or 0.0)
    if w <= 0:
        return 1.0
    return 1.0 / (1.0 + CI_WIDTH_PENALTY * w)


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
        # Incertitude du modèle (largeur de l'IC de proba_top1, Point 12 audit) : plus
        # l'IC est large, moins l'edge mesuré est fiable → on réduit la conviction AVANT
        # le cap anti sur-staking (donc le plafond « jamais > Kelly plein » reste garanti
        # dans tous les cas). Absent (0.0) → discount=1.0, comportement inchangé.
        unc_discount = _uncertainty_discount(c.get("_ci_width", 0.0))
        mult = min(certitude * rp.get(c["niveau"], 1.0) * c.get("_roi_w", 1.0)
                   * float(c.get("_evb", 1.0) or 1.0) * unc_discount, 2.0)
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
    # GARDE-FOU CORRÉLATION : plusieurs paris qui misent sur le MÊME cheval ne sont pas
    # diversifiés (cf. Point 12 audit) — même après le plafond de variance ci-dessus, qui
    # ne regarde que le TYPE de pari (haute variance ou non), pas le chevauchement réel de
    # chevaux entre paris différents.
    _apply_correlation_cap(selected, montant, min_stake, respect_montant=respect_montant)


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


# Part max du montant total dont le GAIN dépend d'UN SEUL cheval, tous paris
# confondus. Deux paris qui misent chacun sur le même cheval (ex. Simple Gagnant
# + Couplé Placé l'incluant) ne sont PAS diversifiés : si ce cheval déçoit ou est
# disqualifié, les deux perdent ENSEMBLE. Le nombre de paris affiché peut donc
# être un trompe-l'œil — ce plafond mesure le risque réel (par cheval), pas le
# nombre de tickets.
MAX_HORSE_EXPOSURE_FRAC = 0.70


def _apply_correlation_cap(selected: list[dict], montant: int, min_stake: int,
                           respect_montant: bool = False) -> None:
    """Plafonne l'exposition cumulée à un seul cheval à `MAX_HORSE_EXPOSURE_FRAC`
    × montant. Dernier passage (après variance cap) : transfère l'excédent des
    paris impliquant le cheval sur-exposé vers des paris qui NE LE PARTAGENT PAS
    (jamais vers un autre pari corrélé, ce qui ne ferait que déplacer le
    problème). Ne peut réduire une mise sous `min_stake`."""
    if len(selected) < 2:
        return
    ceil_amt = max(int(min_stake), int(montant * MAX_HORSE_EXPOSURE_FRAC))
    guard = 0
    while guard < 20:
        guard += 1
        exposure: dict[int, float] = {}
        for c in selected:
            for n in {int(h["numero"]) for h in c.get("chevaux", []) if h.get("numero") is not None}:
                exposure[n] = exposure.get(n, 0.0) + c.get("mise", 0)
        over = {n: e for n, e in exposure.items() if e > ceil_amt}
        if not over:
            return
        worst = max(over, key=over.get)
        involved = [c for c in selected
                   if worst in {int(h["numero"]) for h in c.get("chevaux", [])
                                if h.get("numero") is not None}]
        if len(involved) < 2:
            return  # un seul pari sur ce cheval : c'est sa taille propre, pas une corrélation
        # Réduit en priorité le pari le MOINS convaincant (proba×rapport le plus faible),
        # jamais sous le plancher (ni min_stake, ni le "_besoin" du contrat de gain — même
        # garde que _apply_variance_cap : on ne défait pas la promesse ≥ gain_cible_mult).
        involved.sort(key=lambda c: c.get("proba_gain", 0.0) * c.get("rapport_estime", 0.0))
        weakest = involved[0]
        floor_w = max(int(min_stake), int(weakest.get("_besoin", 0) or 0))
        reduce_by = min(int(weakest["mise"]) - floor_w, int(exposure[worst] - ceil_amt) + 1)
        if reduce_by <= 0:
            return
        weakest["mise"] -= reduce_by
        # Redistribue vers les paris NE PARTAGEANT AUCUN cheval avec `worst`.
        weakest_horses = {int(h["numero"]) for h in weakest.get("chevaux", [])
                          if h.get("numero") is not None}
        free = [c for c in selected if c is not weakest
               and not ({int(h["numero"]) for h in c.get("chevaux", [])
                        if h.get("numero") is not None} & weakest_horses)
               and worst not in {int(h["numero"]) for h in c.get("chevaux", [])
                                 if h.get("numero") is not None}]
        moved = reduce_by
        k = 0
        while moved > 0 and free:
            free[k % len(free)]["mise"] += 1
            moved -= 1
            k += 1
        if moved > 0 and respect_montant:
            # Aucun pari décorrélé pour absorber : le montant saisi doit rester
            # ENTIÈREMENT joué (contrat manuel) → on rend l'excédent à `weakest`
            # plutôt que de sous-jouer le montant demandé. Le plafond n'est donc
            # pas garanti dans ce cas (peu de candidats), mais jamais le contrat.
            weakest["mise"] += moved


# Pourquoi ce TYPE de pari sert ce PROFIL — pédagogie de la méthode de jeu.
_TYPE_RAISON_PROFIL = {
    # PRUDENT — placé / duo placé / 2sur4.
    ("conservateur", "Simple Placé"):  "Placé = le pari qui tombe le plus souvent — socle du profil prudent (faible variance).",
    ("conservateur", "Simple Gagnant"): "Gagnant sur un cheval qui DOMINE la course (forte proba de victoire, cote courte) — fréquence élevée, gain ~×2-5.",
    ("conservateur", "Couplé Placé"):  "Duo placé : 2 chevaux dans les 3 premiers — fréquence élevée, rapport supérieur au placé sec.",
    ("conservateur", "2sur4"):         "2sur4 : 2 des 4 choisis dans le top-4 — tolère une défaillance, parfait pour jouer prudent.",
    # NORMAL — cotes moyennes à proba, plusieurs petites combinaisons, pas de placé sec.
    ("equilibre", "Simple Gagnant"):   "Gagnant à cote intéressante (4-10) : rapport ×4-10 pour une chance réelle de victoire.",
    ("equilibre", "Simple Placé"):     "Placé d'outsider à VALEUR : rapport ×4+ pour un pari qui tombe encore souvent (top 3 suffit).",
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


def _raisons_pari(c: dict, profil: str, facteurs_chevaux: Optional[dict],
                  montant: Optional[float] = None) -> list[str]:
    """Justification COMPLÈTE d'un pari retenu : pourquoi ce type pour ce profil,
    valeur détectée, signaux appris, ROI réel passé du type, trace Kelly de la mise.
    Tout dérive de valeurs RÉELLEMENT calculées — aucune raison décorative."""
    raisons: list[str] = []
    # 0. Objectif du profil + rapport RÉEL de ce pari → justifie « pourquoi je joue ça ».
    rap = float(c.get("rapport_estime", 0.0) or 0.0)
    _obj = {
        "conservateur": f"Objectif PRUDENT : cote courte, gain fréquent — viser ×1,8 à ×5 "
                        f"de la mise totale. Ce pari rapporte ~×{rap:.1f}.",
        "equilibre":    f"Objectif MODÉRÉ : plus de cote/risque — viser ×4 à ×15 de la mise "
                        f"totale. Ce pari rapporte ~×{rap:.1f}.",
        "agressif":     f"Objectif RISQUÉ : viser gros, au moins ×10 de la mise totale. "
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
    # 5b. ROI réel appris de la BANDE D'EV de ce pari (zone toxique allégée / bande rentable renforcée).
    evb = float(c.get("_evb", 1.0) or 1.0)
    if evb >= 1.05:
        raisons.append(f"Cette bande d'EV est historiquement RENTABLE (mise renforcée ×{evb:.2f}).")
    elif evb <= 0.95:
        raisons.append(f"Cette bande d'EV a un ROI réel faible/négatif — mise allégée ×{evb:.2f} (anti zone toxique).")
    # 5 bis. Tranche de RAPPORT : le facteur le mieux étayé de tout le système
    # (le ROI réel y décroît continûment). On le dit, sinon la mise réduite paraît
    # arbitraire à l'utilisateur.
    pbm = float(c.get("_pb_mult", 1.0) or 1.0)
    if pbm >= 1.005:
        raisons.append(
            f"Cette tranche de rapport est celle qui a le mieux payé historiquement "
            f"(conviction renforcée ×{pbm:.2f}).")
    elif pbm <= 0.95:
        raisons.append(
            f"Tranche de rapport historiquement peu rentable — conviction réduite "
            f"×{pbm:.2f} (le ROI réel baisse à mesure que le rapport visé monte).")
    ratio_disc = c.get("_discipline_ratio")
    if ratio_disc and float(ratio_disc) < 1.0:
        raisons.append(
            f"Discipline de mise : sur ce type de course l'argent est historiquement "
            f"mal rendu — somme engagée ramenée à {int(float(ratio_disc)*100)} % du plan, "
            "le reste reste en réserve.")
    # 6. Contrat de gain vs mise TOTALE (allocation spread) : la mise du ticket a été
    # dimensionnée pour que, gagnant, il rende ≥ la cible du profil sur le PLAN entier.
    mise = float(c.get("mise", 0) or 0)
    if montant and mise > 0 and c.get("_besoin"):
        gain_est = mise * float(c.get("rapport_estime", 0.0) or 0.0)
        if gain_est > 0:
            raisons.append(
                f"Mise {mise:.0f}€ dimensionnée pour le plan : gain potentiel ~{gain_est:.0f}€ "
                f"= ×{gain_est / float(montant):.1f} de la mise totale ({float(montant):.0f}€)."
            )
    # 7. Trace Kelly de la mise
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
            raisons=_raisons_pari(c, profil, facteurs_chevaux, montant=montant),
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
    # Note honnête : on a dû sortir de la tranche de gain habituelle du profil pour que la
    # course soit quand même jouée (aucun pari dans la bande). Le multiplicateur visé n'est
    # pas garanti ici — on le DIT (aucune donnée inventée, ce sont de vrais paris PMU).
    if any(b.get("_hors_bande") for b in selected):
        resume += (" Note : aucun pari ne tombait dans la tranche de gain habituelle du "
                   "profil sur cette course — on a retenu le meilleur pari disponible pour "
                   "qu'elle soit quand même jouée (multiplicateur visé non garanti ici).")
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


def reprice_plan_live(plan: dict, predictions: list[dict], course_info: dict) -> dict:
    """Recalcule les GAINS potentiels d'un plan déjà figé en utilisant les cotes LIVE,
    SANS toucher à la sélection (mêmes paris, mêmes chevaux, mêmes mises). Le rapport de
    chaque pari est re-tarifé via la MÊME mécanique que la génération (enumerate, simulation
    Plackett-Luce + rapport parimutuel) → l'ordre de grandeur du gain colle au marché en
    direct jusqu'au départ. Le bilan/palmarès restent réglés aux VRAIS rapports PMU.

    Un pari de la sélection figée introuvable parmi les candidats live (combo d'outsider
    rare régénéré différemment) GARDE son gain figé — jamais d'invention, jamais de crash.

    Non-partant déclaré APRÈS le gel : un cheval de la sélection peut être scratché entre
    le gel (T-10) et le départ. Ces chevaux sont exclus des candidats live (comme dans
    `generer_plan`) ; un pari de la sélection figée qui l'inclut est marqué
    `non_partant_detecte=True` plutôt que ré-estimé sur un cheval qui ne courra plus — le
    remboursement réel se fait au règlement (`settle_pari`), ceci n'est qu'un signal
    d'affichage pour ne pas montrer un gain live trompeur. Mute et retourne `plan`."""
    if not plan or not predictions:
        return plan
    non_partants = {int(p["numero"]) for p in predictions
                    if p.get("non_partant") and p.get("numero") is not None}
    try:
        from ml.combo_bets import enumerate_bet_candidates
        # Mêmes chevaux exclus qu'à la génération : un non-partant ne doit jamais
        # réapparaître dans un candidat live (combo_bets ne le filtre pas lui-même).
        live_preds = [p for p in predictions if not p.get("non_partant")]
        cands = enumerate_bet_candidates(live_preds, course_info)
    except Exception:
        return plan
    if not cands:
        return plan
    look = {(c["type_pari"], frozenset(int(h["numero"]) for h in c.get("chevaux", []))): c
            for c in cands}

    ev_pondere = 0.0
    montant = float(plan.get("montant_total") or 0) or None
    for niv in plan.get("niveaux", []):
        m_niv = 0.0
        for p in niv.get("paris", []):
            mise = float(p.get("mise") or 0)
            m_niv += mise
            pari_horses = {int(h["numero"]) for h in p.get("chevaux", [])
                           if h.get("numero") is not None}
            if pari_horses & non_partants:
                # Cheval scratché après le gel : le gain live n'a pas de sens (le pari
                # sera remboursé au règlement). On garde le gain/EV figés pour l'affichage
                # historique du plan, mais on signale l'impact plutôt que de le masquer.
                p["non_partant_detecte"] = True
                ev_pondere += mise * float(p.get("ev_estime") or 0.0)
                niv["montant"] = round(m_niv, 2)
                continue
            key = (p.get("type"), frozenset(pari_horses))
            c = look.get(key)
            if c:
                rap = float(c["rapport_estime"])
                p["gain_potentiel"] = round(mise * rap)
                p["ev_estime"] = c["ev"]
                p["probabilite"] = c["proba_gain"]
                ev_pondere += mise * float(c["ev"])
            else:
                # pari non re-tarifable → on garde son gain figé (et son EV figée)
                ev_pondere += mise * float(p.get("ev_estime") or 0.0)
        niv["montant"] = round(m_niv, 2)
    plan["esperance_gain"] = round(ev_pondere, 2)
    if montant:
        plan["ev_global"] = round(ev_pondere / montant, 3)
    plan["gains_live_post_gel"] = True
    plan["cotes_live_utilisees"] = True
    return plan


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
