"""Correctifs données côté features (audit du 2026-10-07).

- L'appariement ligne interne / copie PMU (BT_HIST_V2) accepte les copies datées
  du MÊME jour (nouvelle écriture à l'heure de Paris) comme celles de la veille
  (lignes déjà en base).
- `corde_preference` (lot v2) lit les STALLES passées réelles, pas le sens du
  virage de `historique_courses.corde`. Drapeau éteint : rien ne change.
- Météo : `pluie_24h` contient une pluie sur 1 h, exposée sous son vrai nom.
"""
import datetime as dt

import pytest

from ml import features as F


# ── Historique : les deux décalages de date ──────────────────────────────────

def test_appariement_veille_ou_meme_jour():
    assert "(i.date_course = h.date_course + 1 OR i.date_course = h.date_course)" \
        in F.HIST_SANS_COPIE_SQL
    assert "(i.date_course = h.date_course + 1 OR i.date_course = h.date_course)" \
        in F.HIST_SANS_COPIE_COURSE_SQL
    assert "(e.date_course = h.date_course - 1 OR e.date_course = h.date_course)" \
        in F.HIST_JUMEAU_LATERAL
    # Toujours une ligne interne contre une copie, à distance égale.
    for sql in (F.HIST_SANS_COPIE_SQL, F.HIST_JUMEAU_LATERAL):
        assert "distance = h.distance" in sql
    assert "h.course_id IS NULL" in F.HIST_SANS_COPIE_SQL
    assert "i.course_id IS NOT NULL" in F.HIST_SANS_COPIE_SQL


# ── Corde : stalles réelles ──────────────────────────────────────────────────

def _h(pos, corde=None, course_id=None):
    """Ligne d'historique au format de _load_course_batch_data (index 0..20)."""
    row = [None] * 21
    row[0], row[4] = pos, dt.date(2026, 9, 1)
    row[11], row[19] = corde, course_id
    return tuple(row)


def test_le_sens_du_virage_n_est_pas_une_stalle():
    assert F.stalle_passee(_h(1, "CORDE_GAUCHE")) is None
    assert F.stalle_passee(_h(1, "7")) == 7
    assert F.stalle_passee(_h(1, "0")) is None
    # Sortie interne : la stalle vient de participations.numero_corde.
    assert F.stalle_passee(_h(1, "CORDE_GAUCHE", "C1"), {"C1": 3}) == 3


def test_preference_calculee_sur_les_stalles_passees():
    hist = [_h(1, "CORDE_GAUCHE", "C1"), _h(2, "CORDE_GAUCHE", "C2"),
            _h(8, "CORDE_GAUCHE", "C3"), _h(1, "CORDE_GAUCHE", "C4")]
    stalles = {"C1": 2, "C2": 3, "C3": 4, "C4": 12}
    # Intérieur (1-4) : 3 sorties, 2 dans les 3 premiers.
    assert F.corde_preference_stalles(hist, "interieure", stalles) == pytest.approx(2 / 3)
    # Extérieur : une seule sortie → pas assez d'observations → neutre.
    assert F.corde_preference_stalles(hist, "exterieure", stalles) == 0.5


def test_sans_stalle_connue_neutre_jamais_devine():
    hist = [_h(1, "CORDE_GAUCHE"), _h(1, "CORDE_DROITE"), _h(1, "CORDE_GAUCHE")]
    assert F.corde_preference_stalles(hist, "interieure", None) == 0.5
    assert F.corde_preference_stalles(hist, "inconnu", {"x": 1}) == 0.5


def test_les_incidents_ne_comptent_pas():
    hist = [_h(99, None, "C1"), _h(99, None, "C2"), _h(99, None, "C3")]
    assert F.corde_preference_stalles(hist, "interieure",
                                      {"C1": 1, "C2": 2, "C3": 3}) == 0.5


def test_stalles_passees_chargees_seulement_en_v2():
    import inspect
    src = inspect.getsource(F._load_course_batch_data)
    assert "stalles_passees_by_cheval" in src and "if _dedup:" in src


# ── Météo ────────────────────────────────────────────────────────────────────

class _Rep:
    def __init__(self, data):
        self._d = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._d


class _Client:
    def __init__(self, data):
        self._d = data

    async def get(self, url):
        return _Rep(self._d)


@pytest.mark.asyncio
async def test_pluie_exposee_sous_son_vrai_nom():
    from scraper.sources.meteo import MeteoScraper
    m = object.__new__(MeteoScraper)
    m.api_key = "k"
    m._client = _Client({"main": {"temp": 12}, "rain": {"1h": 0.8}, "wind": {}})
    r = await m.get_meteo("CHANTILLY")
    assert r["pluie_1h"] == 0.8
    # Nom historique conservé, contenu INCHANGÉ (le modèle a appris sur 1 h).
    assert r["pluie_24h"] == 0.8
    m._client = _Client({"main": {}, "wind": {}})
    assert (await m.get_meteo("CHANTILLY"))["pluie_1h"] == 0.0
