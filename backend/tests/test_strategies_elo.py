"""Le backtest des stratégies filtre sur l'ELO À LA DATE de la course rejouée,
jamais sur l'ELO d'aujourd'hui (qui intègre les résultats postérieurs)."""
from types import SimpleNamespace

from api.routes.strategies import elo_a_la_date


def test_la_photo_avant_course_fait_foi():
    assert elo_a_la_date(SimpleNamespace(elo_avant_global=1612.5)) == 1612.5


def test_sans_photo_aucun_elo_n_est_invente():
    assert elo_a_la_date(SimpleNamespace(elo_avant_global=None)) is None
    assert elo_a_la_date(SimpleNamespace()) is None
