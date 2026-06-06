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


# ─────────────────────────────────────────────────────────────
# Moteur principal
# ─────────────────────────────────────────────────────────────
NIVEAU_META = {
    "securite":  ("SÉCURITÉ",  "🟢", "#10B981"),
    "rendement": ("RENDEMENT", "🔵", "#3B82F6"),
    "surprise":  ("SURPRISES", "🟡", "#F59E0B"),
    "coup":      ("GROS LOT",  "🔴", "#EF4444"),
}

# Nb de paris ciblé par niveau selon le profil (avant plafond du montant)
PROFIL_QUOTAS = {
    "conservateur": {"securite": 2, "rendement": 3, "surprise": 1, "coup": 1},
    "equilibre":    {"securite": 1, "rendement": 3, "surprise": 2, "coup": 1},
    "agressif":     {"securite": 0, "rendement": 2, "surprise": 3, "coup": 2},
}


def generer_plan(
    montant: float,
    profil: str,
    predictions: list[dict],
    course_info: dict,
    bankroll: Optional[float] = None,
) -> MisePlan:
    """Plan de mise : PORTEFEUILLE DIVERS de paris recalculé à chaque fois selon le
    montant — plusieurs Simple Gagnant, 3-4 Couplé Gagnant différents, Trios, dont
    des scénarios SURPRISE (outsider que le modèle aime > marché). Probabilités
    RÉELLES (simulation Plackett-Luce). Mise minimale 2€, arrondie à l'euro.
    """
    from ml.combo_bets import enumerate_bet_candidates

    profil = profil if profil in PROFIL_QUOTAS else "equilibre"
    montant = max(2, int(round(float(montant))))            # euro, min 2
    kelly_warn = bankroll is not None and montant > bankroll * 0.05

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

    max_bets = max(1, min(montant // 2, 8))                 # chaque pari ≥ 2€
    selected = _select_diverse(cands, max_bets, profil)
    if not selected:
        return _plan_vide(montant, profil)

    _allocate_euros(selected, montant)                      # remplit "mise" (int €)
    return _assemble_plan(selected, montant, kelly_warn)


def _select_diverse(cands: list[dict], max_bets: int, profil: str) -> list[dict]:
    """Choisit un sous-ensemble VARIÉ selon les quotas du profil, en privilégiant
    l'EV puis la proba. Au plus 3 paris d'un même type, mix de niveaux."""
    quotas = dict(PROFIL_QUOTAS[profil])
    by_niveau: dict[str, list[dict]] = {}
    for c in cands:
        by_niveau.setdefault(c["niveau"], []).append(c)
    for lst in by_niveau.values():
        lst.sort(key=lambda c: (c["ev"], c["proba_gain"]), reverse=True)

    selected: list[dict] = []
    type_count: dict[str, int] = {}

    def take(c):
        if len(selected) >= max_bets:
            return False
        if type_count.get(c["type_pari"], 0) >= 3:
            return False
        selected.append(c)
        type_count[c["type_pari"]] = type_count.get(c["type_pari"], 0) + 1
        return True

    # 1) Respecter les quotas par niveau
    for niveau in ("securite", "rendement", "surprise", "coup"):
        for c in by_niveau.get(niveau, []):
            if quotas.get(niveau, 0) <= 0:
                break
            if take(c):
                quotas[niveau] -= 1
    # 2) Compléter avec les meilleurs candidats restants (EV+) jusqu'au plafond
    rest = sorted(
        [c for c in cands if c not in selected],
        key=lambda c: (c["ev"], c["proba_gain"]), reverse=True,
    )
    for c in rest:
        if len(selected) >= max_bets:
            break
        take(c)
    return selected


def _allocate_euros(selected: list[dict], montant: int) -> None:
    """Répartit `montant` (€ entiers) : 2€ plancher par pari, le reste pondéré par
    la conviction (proba × max(EV,0)+petit socle). Total == montant exactement."""
    n = len(selected)
    # si le montant ne couvre pas 2€ par pari, on garde les meilleurs
    while n * 2 > montant and n > 1:
        selected.pop()  # déjà triés best-first par _select_diverse
        n = len(selected)

    base = 2
    reste = montant - base * n
    weights = []
    for c in selected:
        w = c["proba_gain"] * (1.0 + max(c["ev"], 0.0)) + 0.05
        weights.append(max(w, 0.01))
    total_w = sum(weights)
    extra = [int(reste * w / total_w) for w in weights] if total_w > 0 else [0] * n
    # distribuer les euros restants au(x) plus forte(s) conviction(s)
    leftover = reste - sum(extra)
    order = sorted(range(n), key=lambda i: weights[i], reverse=True)
    for k in range(leftover):
        extra[order[k % n]] += 1
    for i, c in enumerate(selected):
        c["mise"] = base + extra[i]


def _assemble_plan(selected: list[dict], montant: int, kelly_warn: bool) -> MisePlan:
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
        )
        niveaux_map.setdefault(c["niveau"], []).append(pari)
        ev_pondere += mise * c["ev"]

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

    nb_paris = len(selected)
    nb_surprise = sum(1 for c in selected if c["niveau"] == "surprise")
    resume = (
        f"{nb_paris} paris répartis sur {len(niveaux)} niveaux"
        + (f", dont {nb_surprise} scénario(s) surprise" if nb_surprise else "")
        + f". Mise totale {montant}€."
    )
    return MisePlan(
        montant_total=montant,
        montant_joue=sum(c["mise"] for c in selected),
        montant_reserve=montant - sum(c["mise"] for c in selected),
        ev_global=round(ev_pondere / montant, 3) if montant else 0.0,
        niveaux=niveaux,
        resume_ia=resume,
        avertissement="Probabilités estimées par simulation. Mises arrondies à l'euro (min 2€). Jouez avec modération.",
        kelly_warning=kelly_warn,
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
                    }
                    for p in n.paris
                ],
            }
            for n in plan.niveaux
        ],
    }
