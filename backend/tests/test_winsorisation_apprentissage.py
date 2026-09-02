"""Un seul gros lot ne doit plus décider de quoi que ce soit (audit 2026-08-31).

Le défaut corrigé ici était silencieux et coûteux. Mesuré sur 81 jours et
4 039 courses rejouables : le Trio ressortait à **+51,0 % de ROI** alors qu'un
unique ticket (course 19072026R3C7, 10 € misés, 4 526 € rendus) portait **49,8 %
de tous ses gains** ; sans lui, le Trio valait −24,1 %, et winsorisé au p99 il
vaut −75,7 %. `shrunk_weight` travaillant sur des sommes BRUTES, l'état appris
publiait `Trio roi: 62,8 %` et lui donnait le poids MAXIMUM (1,6). Autrement dit
l'apprentissage poussait activement le pari qui détruisait le plus d'argent, et
seul un gate posé EN AVAL l'empêchait de sortir dans les plans.

Ces tests verrouillent les trois propriétés qui rendent ce retour impossible.
"""

import pytest

from ml import bet_plan_performance as bpp
from ml import profil_learning as pl


# ── Le plafond de winsorisation lui-même ─────────────────────────────────────

@pytest.mark.parametrize("fn", [pl.plafond_gain, bpp._plafond_winsorisation])
def test_plafond_vide_ne_borne_rien(fn):
    """Pas de données → pas de plafond. On n'invente jamais une borne."""
    assert fn([]) is None


@pytest.mark.parametrize("fn", [pl.plafond_gain, bpp._plafond_winsorisation])
def test_plafond_egale_percentile_cont_de_postgres(fn):
    """Même définition que `percentile_cont(0.99)` : interpolation linéaire.

    C'est ce qui permet de rejouer une mesure d'audit faite en SQL, à l'identique,
    depuis le code — et inversement. Sur 0..100, le p99 vaut exactement 99.
    """
    assert fn([float(i) for i in range(101)]) == pytest.approx(99.0)
    # Un seul point : le plafond est ce point (aucune interpolation possible).
    assert fn([42.0]) == 42.0


@pytest.mark.parametrize("fn", [pl.plafond_gain, bpp._plafond_winsorisation])
def test_plafond_ecrete_le_jackpot_pas_la_performance_courante(fn):
    """Cas réel reproduit : 99 tickets perdants + 1 jackpot."""
    gains = [0.0] * 99 + [4526.0]
    plafond = fn(gains)
    assert plafond < 4526.0, "le jackpot doit être écrêté"
    total_brut = sum(gains)
    total_winsor = sum(min(g, plafond) for g in gains)
    assert total_winsor < total_brut


# ── Le poids appris ne doit plus suivre le jackpot ───────────────────────────

def _agg_type(gains: list[float], mise_unitaire: float = 10.0) -> dict:
    """Reproduit un agrégat `agg["types"][t]` tel que `_accumulate` le construit,
    une fois les gains plafonnés. `decay = 1` : la récence n'est pas le sujet ici."""
    plafond = pl.plafond_gain(gains)
    mise = mise_unitaire * len(gains)
    return {
        "n": len(gains), "mise": mise, "gain": sum(gains),
        "win": sum(1 for g in gains if g > 0),
        "n_e": float(len(gains)), "mise_e": mise,
        "gain_e": sum(gains),
        "gain_w": sum(min(g, plafond) for g in gains),
        "gain_ew": sum(min(g, plafond) for g in gains),
    }


def test_le_jackpot_ne_fixe_plus_le_poids_maximum():
    """Le scénario Trio, en miniature : 199 tickets perdants et un gain énorme.

    En BRUT le type paraît très rentable et décrocherait `W_MAX`. Winsorisé, il
    est massivement perdant et doit descendre vers `W_MIN`.
    """
    gains = [0.0] * 199 + [40_000.0]          # 2 000 € misés, 40 000 € rendus
    ts = _agg_type(gains)

    roi_brut = (ts["gain"] - ts["mise"]) / ts["mise"]
    roi_winsor = (ts["gain_w"] - ts["mise"]) / ts["mise"]
    assert roi_brut > 0, "sanity : en brut ce type a l'air très rentable"
    assert roi_winsor < -0.5, "sanity : winsorisé il est massivement perdant"

    poids_brut = pl.shrunk_weight(ts["gain_e"] - ts["mise_e"], ts["mise_e"],
                                  ts["n_e"], roi_reference=-0.25)
    poids_winsor = pl.shrunk_weight(ts["gain_ew"] - ts["mise_e"], ts["mise_e"],
                                    ts["n_e"], roi_reference=-0.25)
    assert poids_brut == pl.W_MAX, "avant correction : poids maximum sur un jackpot"
    assert poids_winsor < 1.0, "après correction : le poids doit être pénalisant"
    assert poids_winsor == pytest.approx(pl.W_MIN, abs=0.2)


def test_un_type_regulierement_gagnant_garde_son_poids():
    """Contre-test indispensable : la winsorisation ne doit pas punir la régularité.

    Un type dont les gains sont RÉPARTIS (pas concentrés sur un ticket) ne perd
    presque rien au plafonnement — sinon la correction détruirait le signal utile
    en même temps que le bruit.
    """
    gains = [0.0] * 60 + [25.0] * 40          # 1 000 € misés, 1 000 € rendus
    ts = _agg_type(gains)
    poids_brut = pl.shrunk_weight(ts["gain_e"] - ts["mise_e"], ts["mise_e"],
                                  ts["n_e"], roi_reference=-0.25)
    poids_winsor = pl.shrunk_weight(ts["gain_ew"] - ts["mise_e"], ts["mise_e"],
                                    ts["n_e"], roi_reference=-0.25)
    assert poids_winsor == pytest.approx(poids_brut, abs=0.01)


# ── Les gates ────────────────────────────────────────────────────────────────

def _perf(**m) -> dict:
    base = {
        "n_paris": 300, "n_courses": 300, "n_plans": 300, "reliable": True,
        "roi_pct": 0.0, "roi_pct_winsor": 0.0, "prelevement_pct": 25.0,
        "edge_pct": 25.0, "edge_pct_winsor": 25.0,
        "losing_streak_attendue": None, "losing_streak_max": None,
        "delta_vs_classement_pct": None, "baseline_classement": None,
    }
    base.update(m)
    return {"segments": {"X": base}}


def test_la_gate_tranche_sur_l_avantage_winsorise_pas_le_brut():
    """Avantage brut confortable, avantage winsorisé sous le seuil → suspendu.

    C'est exactement le profil du Trio : +51 % de ROI brut, −75,7 % winsorisé.
    """
    g = bpp.evaluate_segment_gates(_perf(edge_pct=40.0, edge_pct_winsor=-54.2))["X"]
    assert g["status"] == "suspended"
    assert g["factor"] == 0.0
    assert "winsorisé" in g["reason"]
    assert g["edge_pct_brut"] == 40.0, "le brut reste publié à côté du winsorisé"


def test_avantage_positif_mais_trop_peu_de_COURSES_est_reduit_pas_actif():
    """« Mini Multi en 4 » : 228 paris, mais seulement 17 courses, ROI +332 %.

    `reliable` compte des PARIS et le même plan est ré-émis ~33 fois par course :
    un segment peut donc franchir le seuil de fiabilité sans avoir rencontré
    30 courses. On ne coupe pas (rien ne prouve qu'il soit mauvais) — on refuse
    de miser à plein.
    """
    g = bpp.evaluate_segment_gates(
        _perf(n_paris=228, n_courses=17, edge_pct=337.9, edge_pct_winsor=337.9))["X"]
    assert g["status"] == "reduced"
    assert g["factor"] == bpp.REDUCE_FACTOR
    assert "17 courses" in g["reason"]


def test_avantage_positif_sur_assez_de_courses_reste_actif():
    """Contre-test : le garde-fou ne doit pas brider un segment bien observé."""
    g = bpp.evaluate_segment_gates(
        _perf(n_paris=19001, n_courses=592, edge_pct=15.5, edge_pct_winsor=7.2))["X"]
    assert g["status"] == "active"
    assert g["factor"] == 1.0


def test_un_type_ruineux_sur_peu_de_courses_reste_SUSPENDU():
    """La régression qu'il ne faut surtout pas réintroduire.

    Passer le seuil de fiabilité en courses aurait fait remonter 8 types ruineux
    (mesuré : Multi en 4 à −100 % sur 7 courses, Pick5 −100 % sur 3, Tiercé et
    Quinté+ Désordre −100 % sur 1 course chacun), parce qu'un segment redevenu
    "observed" retombe en "active" par défaut. Le seuil de SUSPENSION reste donc
    volontairement permissif : il compte des paris.
    """
    g = bpp.evaluate_segment_gates(
        _perf(n_paris=145, n_courses=7, roi_pct=-100.0, roi_pct_winsor=-100.0,
              prelevement_pct=30.0, edge_pct=-70.0, edge_pct_winsor=-70.0))["X"]
    assert g["status"] == "suspended"
    assert g["factor"] == 0.0


def test_sous_le_seuil_de_fiabilite_rien_n_est_tranche():
    """Trop peu de paris → ni suspendu, ni réduit, ET SURTOUT PAS réactivé.

    Le segment sort du dict : `persist_segment_gates` ne l'écrit donc pas et la
    dernière décision connue continue de s'appliquer. Émettre "active" par défaut,
    comme avant, effaçait une suspension prouvée dès que l'échantillon récent
    devenait mince — le piège même qui avait fait rejeter le passage du seuil de
    fiabilité en courses distinctes.
    """
    gates = bpp.evaluate_segment_gates(
        _perf(n_paris=5, n_courses=5, reliable=False,
              edge_pct=-70.0, edge_pct_winsor=-70.0))
    assert gates == {}


def test_repli_sur_l_avantage_brut_si_la_winsorisation_manque():
    """Un segment sans `edge_pct_winsor` (données trop pauvres) ne doit pas
    échapper à la gate : on retombe sur le brut plutôt que de ne rien décider."""
    g = bpp.evaluate_segment_gates(
        _perf(edge_pct=-30.0, edge_pct_winsor=None))["X"]
    assert g["status"] == "suspended"
