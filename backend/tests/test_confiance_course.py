"""Le score de confiance est un accord, et ce qu'on affiche à côté est mesuré."""
from types import SimpleNamespace

from services.confiance_course import (
    FENETRE_JOURS, confiance_course, confiance_depuis_predictions, contexte_confiance, tranche,
)


def test_confiance_est_celle_du_rang_un_arrondie():
    assert confiance_course(83.96) == 84
    assert confiance_course(None) is None
    preds = [SimpleNamespace(rang_predit=2, confidence_score=99.0),
             SimpleNamespace(rang_predit=1, confidence_score=76.6)]
    assert confiance_depuis_predictions(preds) == 77
    assert confiance_depuis_predictions([]) is None


def test_tranches_couvrent_toute_l_echelle():
    assert tranche(0) == (0, 60)
    assert tranche(59.9) == (0, 60)
    assert tranche(60) == (60, 70)
    assert tranche(77) == (75, 80)
    assert tranche(85) == (85, None)
    assert tranche(100) == (85, None)
    assert tranche(None) is None


def test_contexte_ne_cite_que_du_mesure():
    table = {75: {"n": 684, "gagne_pct": 33.5}, 85: {"n": 12, "gagne_pct": 50.0}}
    ctx = contexte_confiance(77, table)
    assert ctx == {"score": 77, "tranche_min": 75, "tranche_max": 80, "n_courses": 684,
                   "n1_gagne_pct": 33.5, "fenetre_jours": FENETRE_JOURS}
    # Tranche trop mince (12 courses) : rien plutôt qu'un pourcentage sur trois cas.
    assert contexte_confiance(90, table) is None
    # Tranche absente, table vide, score absent : rien.
    assert contexte_confiance(65, table) is None
    assert contexte_confiance(77, {}) is None
    assert contexte_confiance(None, table) is None
