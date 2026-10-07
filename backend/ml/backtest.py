"""
backtest.py — Harness de backtest ROI bout-en-bout (Phase 4).

Rejoue des courses TERMINÉES, applique une stratégie de paris sur les prédictions
historiques, règle chaque pari contre le résultat réel, et mesure le gain réel :
ROI, profit, hit-rate, drawdown max, ventilation par type.

Objectif : PROUVER (ou réfuter) qu'une stratégie « assure du gain » sur l'historique,
au lieu d'optimiser à l'aveugle.

RÈGLE D'INTÉGRITÉ : aucun payout fabriqué. La sélection rejoue la cote PMU
disponible avant course (jamais la meilleure cote toutes sources : on ne joue
qu'au PMU, cf. correctif 2026-10-07), un Simple Gagnant gagnant est réglé au
rapport officiel (à défaut à la cote PMU FINALE), un Simple Placé UNIQUEMENT au
rapport placé officiel publié — jamais à la cote gagnant. Les paris dont on ne
peut pas déterminer le gain réel (ex. placé sans rapport placé publié) sont
ignorés, gagnants COMME perdants (sinon on n'exclurait que les gains → ROI biaisé
à la baisse), pas estimés.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import structlog

log = structlog.get_logger()


def _p_win(partant: dict, nb_partants: int) -> float:
    """
    P(victoire) d'un partant pour un value bet GAGNANT.

    Préfère proba_top1 si fournie ; sinon l'estime depuis proba_top3 (proba placé)
    et la taille du champ : P(win) ≈ proba_top3 × 3 / nb_partants. Cohérent avec la
    prod (pipeline passe proba_t1) et avec les CONFIANCE_SEUILS calibrés sur P(win).
    """
    p1 = partant.get("proba_top1")
    if p1 is not None:
        return float(p1)
    p3 = float(partant.get("proba_top3") or 0.0)
    return round(min(1.0, p3 * (3.0 / max(nb_partants, 3))), 4)


# ─────────────────────────────────────────────
# Modèles
# ─────────────────────────────────────────────
@dataclass
class Bet:
    """
    Un pari généré par une stratégie pour une course.

    - Paris simples (gagnant/placé) : réglés à `cote` (cote réelle au scrape).
    - Paris combinés (couplé/trio/tiercé/…) : réglés via les rapports PMU réels
      (`cote` ignorée). `numeros` porte la sélection.
    """
    course_id: str
    numero: int
    type: str               # "gagnant" | "place" | "Couplé Gagnant" | "Trio" | ...
    stake: float            # mise en euros
    cote: float = 0.0       # cote de règlement (paris simples uniquement)
    numeros: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.numeros:
            self.numeros = [self.numero]


@dataclass
class SettledBet:
    bet: Bet
    won: bool
    payout: float           # retour brut (0 si perdu)
    profit: float           # payout - stake


@dataclass
class BacktestResult:
    nb_courses: int = 0
    nb_bets: int = 0
    nb_wins: int = 0
    total_staked: float = 0.0
    total_returned: float = 0.0
    profit: float = 0.0
    roi: float = 0.0                  # profit / total_staked
    hit_rate: float = 0.0             # nb_wins / nb_bets
    max_drawdown: float = 0.0         # plus forte baisse de l'équity cumulée
    by_type: dict = field(default_factory=dict)
    equity_curve: list = field(default_factory=list)

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        return d


# ─────────────────────────────────────────────
# Règlement (pur)
# ─────────────────────────────────────────────
POSITION_INCIDENT = 90


def place_paid(nb_partants: int) -> int:
    """Nombre de places payées (règle PMU usuelle)."""
    if nb_partants is None:
        return 0
    if nb_partants >= 8:
        return 3
    if nb_partants >= 4:
        return 2
    return 1  # 1-3 partants : seulement le gagnant


def arrivee_order(arrivee: dict) -> list:
    """Numéros classés par position d'arrivée croissante, incidents exclus."""
    valides = [(num, pos) for num, pos in arrivee.items() if 1 <= pos < POSITION_INCIDENT]
    valides.sort(key=lambda x: x[1])
    return [num for num, _ in valides]


# Types simples réglés à la cote ; les autres sont des combinés réglés via rapports.
_SIMPLE_TYPES = {"gagnant", "simple gagnant", "place", "placé", "simple placé", "simple place"}
_PLACE_TYPES = {"place", "placé", "simple placé", "simple place"}
_CLES_PLACE = ("simple_place", "e_simple_place", "simple_place_international")
_CLES_GAGNANT = ("simple_gagnant", "e_simple_gagnant", "simple_gagnant_international")


def rapport_officiel_simple(rapports_detail: Optional[dict], bet_type: str,
                            numero: int) -> Optional[float]:
    """Rapport OFFICIEL (pour 1 €) du Simple Gagnant / Placé de ce cheval, lu dans
    `rapports_detail` (le PMU publie un rapport placé PAR cheval). None si absent."""
    from services.bet_settlement import _place_rapport_exact
    t = _norm_type(bet_type)
    cles = _CLES_PLACE if t in _PLACE_TYPES else _CLES_GAGNANT
    return _place_rapport_exact(rapports_detail, cles, [int(numero)])


def places_officielles(rapports_detail: Optional[dict]) -> Optional[set]:
    """Chevaux payés placés d'après le détail officiel ; None si non publié."""
    from services.bet_settlement import _places_publiees
    return _places_publiees(rapports_detail)


def _norm_type(t: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


def bet_won(bet_type: str, numeros: list, arrivee: dict, nb_partants: Optional[int]) -> Optional[bool]:
    """
    Le pari est-il gagnant vu l'arrivée réelle ? None si type non supporté.

    numeros : sélection du parieur. order : arrivée réelle ordonnée.
    """
    order = arrivee_order(arrivee)
    if not order:
        return None
    places = place_paid(nb_partants if nb_partants is not None else len(arrivee))
    t = _norm_type(bet_type)
    sel = list(numeros)
    selset = set(sel)

    if t in ("gagnant", "simple gagnant"):
        return order[0] == sel[0]
    if t in ("place", "placé", "simple place", "simple placé"):
        return sel[0] in order[:places]
    if t == "couple gagnant":
        return selset == set(order[:2])
    if t == "couple ordre":
        return sel[:2] == order[:2]
    if t == "couple place":
        return len(selset) >= 2 and selset <= set(order[:places])
    if t in ("trio", "trio ordre"):
        return selset == set(order[:3]) if "ordre" not in t else sel[:3] == order[:3]
    if t in ("tierce", "tierce desordre"):
        return selset == set(order[:3])
    if t == "tierce ordre":
        return sel[:3] == order[:3]
    if t in ("2sur4", "deux sur quatre"):
        return len(selset & set(order[:4])) >= 2
    if t in ("quarte", "quarte desordre"):
        return selset == set(order[:4])
    if t == "quarte ordre":
        return sel[:4] == order[:4]
    if t in ("quinte", "quinte+", "quinte plus", "quinte desordre"):
        return selset == set(order[:5])
    if t == "quinte ordre":
        return sel[:5] == order[:5]
    return None  # type non géré → non réglable


# Correspondance type de pari → clés candidates dans le dict rapports PMU.
_RAPPORT_KEYS = {
    "couple gagnant": ["couple_gagnant", "e_couple_gagnant", "couple"],
    "couple place": ["couple_place", "e_couple_place"],
    "couple ordre": ["couple_ordre"],
    "trio": ["trio", "e_trio"],
    "tierce": ["tierce", "e_tierce"],
    "tierce ordre": ["tierce_ordre"],
    "2sur4": ["deux_sur_quatre", "2sur4", "e_2sur4"],
    "quarte": ["quarte", "quarte_plus", "e_quarte"],
    "quinte": ["quinte", "quinte_plus", "e_quinte"],
}


def _lookup_rapport(rapports: dict, bet_type: str) -> Optional[float]:
    """Retourne le rapport (par €1) pour ce type, ou None si introuvable."""
    if not rapports:
        return None
    norm = {_norm_type(k).replace(" ", "_"): v for k, v in rapports.items()}
    t = _norm_type(bet_type)
    base = t.replace(" desordre", "").replace(" plus", "")
    for key in _RAPPORT_KEYS.get(base, []) + [t.replace(" ", "_"), base.replace(" ", "_")]:
        if key in norm:
            try:
                return float(norm[key])
            except (ValueError, TypeError):
                return None
    return None


def settle_bet(
    bet: Bet,
    arrivee: dict,
    nb_partants: Optional[int] = None,
    rapports: Optional[dict] = None,
    rapports_detail: Optional[dict] = None,
) -> Optional[SettledBet]:
    """
    Règle un pari contre l'arrivée réelle.

    Simple (gagnant/placé) → payout = stake × rapport OFFICIEL du cheval quand
    `rapports_detail` le publie ; sinon stake × `bet.cote` (cote/rapport de
    règlement fourni par l'appelant — pour un placé, ce doit être un rapport
    PLACÉ : `run_backtest` n'y met jamais la cote gagnant).
    Combiné → payout = stake × rapport PMU réel (rapports par €1).

    Retourne None si non réglable sans estimation (type inconnu, ou combiné
    gagnant sans rapport connu) — on n'invente jamais un gain.
    """
    t = _norm_type(bet.type)
    placees = places_officielles(rapports_detail) if t in _PLACE_TYPES else None
    if placees is not None:
        # Liste officielle des placés (ex æquo, retirés compris) : elle fait foi.
        won = int(bet.numeros[0]) in placees
    else:
        won = bet_won(bet.type, bet.numeros, arrivee, nb_partants)
    if won is None:
        return None  # type non supporté

    if not won:
        return SettledBet(bet=bet, won=False, payout=0.0, profit=round(-bet.stake, 2))

    # Gagnant : déterminer le payout réel
    if t in _SIMPLE_TYPES:
        officiel = rapport_officiel_simple(rapports_detail, bet.type, bet.numeros[0])
        if officiel is not None and officiel > 0:
            payout = round(bet.stake * officiel, 2)
            return SettledBet(bet=bet, won=True, payout=payout,
                              profit=round(payout - bet.stake, 2))
        if rapports_detail and t in _PLACE_TYPES:
            return None  # détail publié mais pas ce cheval → non réglable
        if bet.cote <= 1.0:
            return None  # pas de cote réelle → non réglable
        payout = round(bet.stake * bet.cote, 2)
    else:
        rapport = _lookup_rapport(rapports, bet.type)
        if rapport is None:
            return None  # combiné gagnant sans rapport → non réglable (pas d'invention)
        payout = round(bet.stake * rapport, 2)

    return SettledBet(bet=bet, won=True, payout=payout, profit=round(payout - bet.stake, 2))


def max_drawdown(equity_curve: list) -> float:
    """
    Plus forte baisse depuis un pic sur la courbe d'équity cumulée (profit cumulé).
    Retourne une valeur >= 0 (l'ampleur de la perte depuis le sommet).
    """
    peak = 0.0
    max_dd = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        dd = peak - v
        if dd > max_dd:
            max_dd = dd
    return round(max_dd, 2)


def compute_metrics(settled: list, nb_courses: int) -> BacktestResult:
    """Agrège une liste de SettledBet (ordre chronologique) en métriques."""
    res = BacktestResult(nb_courses=nb_courses, nb_bets=len(settled))
    equity = 0.0
    for sb in settled:
        res.total_staked += sb.bet.stake
        res.total_returned += sb.payout
        res.profit += sb.profit
        if sb.won:
            res.nb_wins += 1
        equity += sb.profit
        res.equity_curve.append(round(equity, 2))

        bt = res.by_type.setdefault(
            sb.bet.type, {"nb": 0, "wins": 0, "staked": 0.0, "profit": 0.0}
        )
        bt["nb"] += 1
        bt["wins"] += 1 if sb.won else 0
        bt["staked"] += sb.bet.stake
        bt["profit"] += sb.profit

    res.total_staked = round(res.total_staked, 2)
    res.total_returned = round(res.total_returned, 2)
    res.profit = round(res.profit, 2)
    res.roi = round(res.profit / res.total_staked, 4) if res.total_staked > 0 else 0.0
    res.hit_rate = round(res.nb_wins / res.nb_bets, 4) if res.nb_bets else 0.0
    res.max_drawdown = max_drawdown(res.equity_curve)
    for bt in res.by_type.values():
        bt["staked"] = round(bt["staked"], 2)
        bt["profit"] = round(bt["profit"], 2)
        bt["roi"] = round(bt["profit"] / bt["staked"], 4) if bt["staked"] > 0 else 0.0
    return res


# ─────────────────────────────────────────────
# Stratégie value-bet (par défaut)
# ─────────────────────────────────────────────
def value_bet_strategy(
    partants: list,
    *,
    course_info: Optional[dict] = None,
    bankroll: float = 100.0,
    kelly_fraction: float = 0.25,
    ev_min: float = 0.0,
) -> list:
    """
    Pour chaque partant, détecte un value bet (EV>ev_min) et génère un pari GAGNANT
    misé au critère de Kelly fractionné, à la cote PMU (seul opérateur joué).

    CORRECTIF 2026-10-07 : la sélection prenait la MEILLEURE cote toutes sources
    (Geny, Betclic, Betfair…) alors que le pari est payé au PMU → EV gonflée,
    stratégie « rentable » sur le papier et pas au guichet.

    partants : liste de dicts {course_id, numero, proba_top3, cotes:{source:cote},
               cotes_history?: list}.
    """
    from ml.valuebets import detect_value_bet, calculer_mise_kelly

    nb_partants = (course_info or {}).get("nb_partants") or len(partants)

    bets = []
    for p in partants:
        cote_pmu = (p.get("cotes") or {}).get("pmu")
        if not cote_pmu or cote_pmu <= 1.0:
            continue
        cote_pmu = float(cote_pmu)
        # Value bet GAGNANT → P(victoire). Si absente, estimer depuis proba_top3
        # (proba placé) et la taille du champ, cohérent avec la prod (proba_t1).
        vb = detect_value_bet(
            proba_top1=_p_win(p, nb_partants),
            cote_pmu=cote_pmu,
            cotes_history=p.get("cotes_history"),
        )
        if not vb or vb["ev_max"] <= ev_min:
            continue
        stake = calculer_mise_kelly(vb["ev_max"], cote_pmu, bankroll, fraction=kelly_fraction)
        if stake <= 0:
            continue
        bets.append(Bet(
            course_id=p["course_id"], numero=p["numero"], type="gagnant",
            stake=stake, cote=cote_pmu,
            meta={"ev": vb["ev_max"], "niveau": vb["niveau"], "source": vb["meilleure_source"]},
        ))
    return bets


def portfolio_strategy(
    partants: list,
    *,
    course_info: Optional[dict] = None,
    bankroll: float = 100.0,
    profil: str = "equilibre",
    scenarios: Optional[list] = None,
) -> list:
    """
    Stratégie « portefeuille diversifié » : utilise BetPortfolioEngine pour générer
    PLUSIEURS paris variés (simples + combinés, chevaux différents) couvrant les
    scénarios alpha/beta/gamma/delta/omega, puis les convertit en paris backtestables.

    `scenarios` : sous-ensemble à retenir (ex. ["alpha","beta"]); None = tous.
    """
    from ml.portfolio import get_portfolio_engine
    from ml.valuebets import detect_value_bet, calculer_ev

    course_info = course_info or {}
    nb_partants = course_info.get("nb_partants") or len(partants)

    # Construire les prédictions au format attendu par le moteur
    predictions = []
    cote_by_num = {}
    for p in partants:
        # Cote PMU UNIQUEMENT (correctif 2026-10-07, cf. value_bet_strategy).
        cote_pmu = (p.get("cotes") or {}).get("pmu")
        if not cote_pmu or cote_pmu <= 1.0:
            continue
        cote_pmu = float(cote_pmu)
        cote_by_num[p["numero"]] = cote_pmu
        proba3 = p["proba_top3"]
        p1 = _p_win(p, nb_partants)
        vb = detect_value_bet(proba_top1=p1, cote_pmu=cote_pmu)
        predictions.append({
            "participation_id": f"{p['course_id']}-{p['numero']}",
            "numero": p["numero"],
            "nom": p.get("nom") or f"N{p['numero']}",
            "proba_top3": proba3,
            "proba_top1": p1,
            "cote_pmu": cote_pmu,
            # EV GAGNANT = P(victoire) × cote − 1 (pas la proba placé × cote gagnant).
            "ev_max": (vb["ev_max"] if vb else calculer_ev(cote_pmu, p1)),
            "niveau_vb": (vb["niveau"] if vb else 0),
        })
    if not predictions:
        return []

    engine = get_portfolio_engine()
    portfolio = engine.build_portfolio(predictions, course_info, bankroll=bankroll, profil=profil)
    if not portfolio:
        return []

    keep = set(scenarios) if scenarios else None
    bets = []
    for scen_key, scen in (portfolio.get("scenarios") or {}).items():
        if keep is not None and scen_key not in keep:
            continue
        if not scen:
            continue
        for pari in scen.get("paris", []):
            numeros = [c["numero"] for c in pari.get("chevaux", []) if c.get("numero") is not None]
            if not numeros:
                continue
            mise = float(pari.get("mise") or 0.0)
            if mise <= 0:
                continue
            # Seul le Simple GAGNANT porte la cote gagnant ; un placé sera réglé au
            # rapport placé officiel (run_backtest), jamais à la cote gagnant.
            _t = _norm_type(pari["type"])
            cote = (cote_by_num.get(numeros[0], 0.0)
                    if _t in _SIMPLE_TYPES and _t not in _PLACE_TYPES else 0.0)
            bets.append(Bet(
                course_id=partants[0]["course_id"], numero=numeros[0],
                type=pari["type"], stake=mise, cote=cote, numeros=numeros,
                meta={"scenario": scen_key, "ev": pari.get("ev"), "proba": pari.get("proba")},
            ))
    return bets


# ─────────────────────────────────────────────
# Runner DB
# ─────────────────────────────────────────────
def _arrivee_from_classement(classement: list) -> dict:
    """Construit {numero: position} depuis le classement d'un Resultat."""
    arrivee = {}
    for e in classement or []:
        num = e.get("numero")
        pos = e.get("position")
        if num is None:
            continue
        try:
            arrivee[int(num)] = int(pos) if pos is not None else POSITION_INCIDENT
        except (ValueError, TypeError):
            continue
    return arrivee


async def run_backtest(
    session,
    course_ids: list,
    strategy: Callable = value_bet_strategy,
    *,
    bankroll: float = 100.0,
    strategy_kwargs: Optional[dict] = None,
) -> BacktestResult:
    """
    Rejoue les courses fournies (déjà terminées, avec prédictions + résultat),
    applique `strategy`, règle les paris, retourne les métriques agrégées.

    Les courses sont traitées par ordre chronologique (date_heure) pour une courbe
    d'équity / drawdown cohérente.
    """
    from sqlalchemy import select, text
    from db.models import Course, Resultat

    strategy_kwargs = strategy_kwargs or {}

    # Charge + ordonne chronologiquement
    courses_r = await session.execute(
        select(Course).where(Course.course_id.in_(course_ids)).order_by(Course.date_heure)
    )
    courses = courses_r.scalars().all()

    all_settled = []
    nb_courses_joues = 0

    for course in courses:
        resultat = await session.get(Resultat, course.course_id)
        if not resultat or not resultat.classement:
            continue
        arrivee = _arrivee_from_classement(resultat.classement)
        if not arrivee:
            continue

        # Partants + cotes + proba prédite. `cote_selection` rejoue honnêtement ce
        # que le moteur connaissait avant le départ ; `cote_finale` ne sert JAMAIS à
        # sélectionner, uniquement au règlement du gain après l'arrivée.
        rows = await session.execute(text("""
            SELECT p.numero, COALESCE(pr.cote_figee, p.cote_pmu) AS cote_selection,
                   p.cote_pmu AS cote_finale, p.cote_geny, p.cote_bzh,
                   p.cote_winamax, p.cote_betclic, p.cote_unibet, p.cote_betfair_exchange,
                   pr.proba_top3, pr.proba_top1
            FROM participations p
            JOIN prediction_evaluation pr ON pr.participation_id = p.participation_id
            WHERE p.course_id = :cid AND p.non_partant = false
              AND pr.created_at IS NOT NULL
              AND pr.created_at < :course_time
              AND pr.is_replayable = true
        """), {"cid": course.course_id, "course_time": course.date_heure})
        # Places payées sur les partants RÉELS (`nb_partants` compte les déclarés).
        nb_reels = (await session.execute(text(
            "SELECT COUNT(*) FROM participations WHERE course_id = :cid AND non_partant = false"),
            {"cid": course.course_id})).scalar() or course.nb_partants
        partants = []
        for r in rows.fetchall():
            if r.proba_top3 is None:
                continue
            partants.append({
                "course_id": course.course_id,
                "numero": r.numero,
                "proba_top3": float(r.proba_top3),
                # P(victoire) stockée → value bet GAGNANT calibré (sinon estimée par _p_win)
                "proba_top1": float(r.proba_top1) if r.proba_top1 is not None else None,
                "cote_finale": float(r.cote_finale) if r.cote_finale else None,
                "cotes": {
                    "pmu": r.cote_selection, "geny": r.cote_geny, "bzh": r.cote_bzh,
                    "winamax": r.cote_winamax, "betclic": r.cote_betclic,
                    "unibet": r.cote_unibet, "betfair": r.cote_betfair_exchange,
                },
            })
        if not partants:
            continue

        bets = strategy(partants, course_info={
            "course_id": course.course_id, "nb_partants": course.nb_partants,
            "est_quinte": course.est_quinte, "est_quarte": course.est_quarte,
            "est_tierce": course.est_tierce, "discipline": course.discipline,
            "distance": course.distance, "hippodrome": course.hippodrome_nom,
        }, bankroll=bankroll, **strategy_kwargs)
        nb_courses_joues += 1
        final_by_num = {int(p["numero"]): p.get("cote_finale") for p in partants}
        rapports_detail = getattr(resultat, "rapports_detail", None) or None
        for bet in bets:
            t = _norm_type(bet.type)
            # La cote PMU figée/live historique décide si le pari aurait été pris.
            if t in _PLACE_TYPES:
                # Simple Placé : rapport placé OFFICIEL ou rien. Avant (2026-10-07)
                # il était payé à la cote GAGNANT finale (×8 au lieu de ×2) — le
                # backtest des placés était faux d'un facteur 3-4. Sans détail
                # placé publié, le pari est EXCLU (gagnant comme perdant).
                if places_officielles(rapports_detail) is None:
                    continue
                bet.cote = 0.0
            elif t in _SIMPLE_TYPES:
                # Simple Gagnant : rapport officiel si publié (settle_bet), sinon
                # cote PMU finale.
                final = final_by_num.get(int(bet.numero))
                if final and final > 1.0:
                    bet.cote = float(final)
            sb = settle_bet(bet, arrivee, nb_partants=nb_reels, rapports=resultat.rapports,
                            rapports_detail=rapports_detail)
            if sb is not None:   # None = non réglable (jamais estimé)
                all_settled.append(sb)

    return compute_metrics(all_settled, nb_courses_joues)
