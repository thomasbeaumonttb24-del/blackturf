"""Lot « historique v2 » (BT_HIST_V2, audit du 2026-09-28).

Une course courue en France est écrite deux fois dans `historique_courses` : la
ligne interne (course_id, datée du jour) et sa copie PMU (course_id NULL, datée de
la VEILLE). Le lot lit une seule ligne par course, note chaque place passée sur la
taille du champ de cette course-là, et compare la stalle du jour (pas le dossard)
aux cordes passées.

Tant que le drapeau est éteint, RIEN ne doit changer : le modèle servi a été
entraîné sur les vecteurs d'avant.
"""
import datetime as dt

import pytest

from ml import features as F
from ml.algo_flags import AlgoFlags


# ── Drapeau ──────────────────────────────────────────────────────────────────
def test_drapeau_eteint_par_defaut(monkeypatch):
    monkeypatch.delenv("BT_HIST_V2", raising=False)
    assert AlgoFlags().hist_v2 is False
    assert "hist_v2" in AlgoFlags().as_dict()


def test_drapeau_force_prime(monkeypatch):
    assert F.hist_dedup_actif(True) is True
    assert F.hist_dedup_actif(False) is False


# ── SQL : éteint = requête d'avant ───────────────────────────────────────────
def test_colonnes_eteint_identiques():
    for col in F.HIST_COLONNES_COMPLETEES + ("distance", "position_arrivee"):
        assert F.hist_col(col, False) == f"h.{col}"


def test_colonnes_completees_par_la_copie():
    assert F.hist_col("ecart_longueurs", True) == "COALESCE(h.ecart_longueurs, tw.ecart_longueurs)"
    # La place et la date restent celles de la ligne interne.
    assert F.hist_col("position_arrivee", True) == "h.position_arrivee"
    assert F.hist_col("date_course", True) == "h.date_course"


def test_la_copie_est_la_veille_ou_le_jour_meme_distance():
    """Mesuré sur 379 338 lignes : décalage d'un jour, jamais zéro, pour les copies
    écrites avant le 2026-10-05 ; datées au jour de Paris depuis (jour_pmu_epoch_ms)."""
    assert "i.date_course IN (h.date_course + 1, h.date_course)" in F.HIST_SANS_COPIE_SQL
    assert "i.date_course IN (h.date_course + 1, h.date_course)" in F.HIST_SANS_COPIE_COURSE_SQL
    assert "e.date_course IN (h.date_course - 1, h.date_course)" in F.HIST_JUMEAU_LATERAL
    for sql in (F.HIST_SANS_COPIE_SQL, F.HIST_JUMEAU_LATERAL, F.HIST_SANS_COPIE_COURSE_SQL):
        assert "distance" in sql


def test_places_differentes_jamais_appariees():
    """137 paires de places différentes : prudence, on ne fusionne pas."""
    assert "h.position_arrivee IS NULL OR h.position_arrivee = i.position_arrivee" \
        in F.HIST_SANS_COPIE_SQL
    assert "e.position_arrivee IS NULL OR e.position_arrivee = h.position_arrivee" \
        in F.HIST_JUMEAU_LATERAL


def test_copie_de_la_course_calculee_sans_condition_de_place():
    assert "i.course_id = :cid" in F.HIST_SANS_COPIE_COURSE_SQL
    assert "position" not in F.HIST_SANS_COPIE_COURSE_SQL


# ── Place notée sur le champ de la sortie ────────────────────────────────────
def _h(pos, nb, jockey=None, oeil=None):
    """Ligne d'historique au format de _load_course_batch_data (index 0..20)."""
    row = [None] * 21
    row[0], row[5], row[4] = pos, nb, dt.date(2026, 9, 1)
    row[16] = jockey
    row[17] = {"oeilleres": oeil} if oeil is not None else None
    return tuple(row)


@pytest.mark.parametrize("h5,attendu", [(16, 16), (8, 8), (None, 10), (0, 10), (1, 10),
                                        ("x", 10)])
def test_champ_sortie(h5, attendu):
    assert F.champ_sortie(_h(3, h5), 10) == attendu


def test_champ_sortie_ligne_courte():
    assert F.champ_sortie((1, 2), 9) == 9


def test_jockey_historique_eteint_inchange():
    hist = [_h(5, 16, "DUPONT"), _h(1, 8, "MARTIN"), _h(2, 12, "DUPONT")]
    avant = F.traits_jockey_historique(hist, "DUPONT", 10)
    explicite = F.traits_jockey_historique(hist, "DUPONT", 10, champ_par_course=False)
    assert avant == explicite
    # Éteint : champ du jour (10) → 5ᵉ = 1 − 4/9.
    assert avant["jockey_hist_score"] == pytest.approx(
        ((1 - 4 / 9) + (1 - 1 / 9)) / 2)


def test_jockey_historique_champ_de_la_sortie():
    hist = [_h(5, 16, "DUPONT"), _h(2, 12, "DUPONT")]
    v2 = F.traits_jockey_historique(hist, "DUPONT", 10, champ_par_course=True)
    assert v2["jockey_hist_score"] == pytest.approx(((1 - 4 / 15) + (1 - 1 / 11)) / 2)


def test_oeilleres_champ_de_la_sortie():
    hist = [_h(5, 16, oeil=True), _h(2, 12, oeil=True), _h(8, 8, oeil=False)]
    eteint = F.traits_oeilleres(hist, "OEILLERES_AUSTRALIENNES", 10)
    assert eteint == F.traits_oeilleres(hist, "OEILLERES_AUSTRALIENNES", 10,
                                        champ_par_course=False)
    v2 = F.traits_oeilleres(hist, "OEILLERES_AUSTRALIENNES", 10, champ_par_course=True)
    meme = [(1 - 4 / 15), (1 - 1 / 11)]
    tous = meme + [0.0]                       # 8ᵉ sur 8
    assert v2["oeilleres_delta"] == pytest.approx(sum(meme) / 2 - sum(tous) / 3)
    assert v2["oeilleres_meme_config_nb"] == 2


def test_incident_reste_a_zero():
    """Place 99 (incident) : 0 quel que soit le champ."""
    assert F.score_position(99, F.champ_sortie(_h(99, 16), 10)) == 0.0


def test_reduction_km_en_dixiemes_corrigee_seulement_en_v2():
    assert F.hist_col("reduction_km", False) == "h.reduction_km"
    sql = F.hist_col("reduction_km", True)
    assert "COALESCE(h.reduction_km, tw.reduction_km)" in sql
    assert f"< {F.REDUCTION_KM_DIXIEMES_MAX}" in sql and "* 10" in sql
