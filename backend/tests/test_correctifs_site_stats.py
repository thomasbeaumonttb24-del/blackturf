"""Correctifs d'honnêteté des chiffres publiés (2026-10-07).

  1. Palmarès : le retour brut `total_gain` n'est plus servi seul — la mise de TOUTE
     la cohorte réglée (paris perdus compris) et le net l'accompagnent.
  2. CLV : cote au pronostic (`cote_figee`) vs dernière cote AVANT le départ, cotes
     inchangées gardées au dénominateur, non-partants exclus.
  3. vb_performance : cohorte ordonnée, non-partants exclus, réglée au rapport PMU
     officiel (`_rapport_gagnant`), course sans rapport non réglée.
  4. Favori IA : ROI None sans mise, dénominateur exact exposé.
  7. Value bets : cote de détection exposée, cote juste unifiée avec
     `services.cote_juste`.
  8. /predictions : plus de requête `recommandations` inutilisée.
"""
import inspect
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from api.routes import predictions as predictions_routes
from api.routes import stats
from services import valuebets_lecture
from services.cote_juste import cote_juste


def _src(fn) -> str:
    return " ".join(inspect.getsource(fn).lower().split())


# ── Palmarès : mise et net de la cohorte entière ─────────────────────────────

class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDB:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, *_a, **_k):
        return _FakeResult(self._rows)


def _run(profil, cid, paris, mise, gain):
    dh = datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc)
    resultat = {"paris": paris, "total_mise": mise, "total_gain": gain, "net": round(gain - mise, 2)}
    return (profil, resultat, dh + timedelta(hours=1), dh - timedelta(hours=1),
            "VINCENNES", dh, cid, 1, 1, None)


@pytest.mark.asyncio
async def test_palmares_compte_la_mise_des_courses_perdues():
    rows = [
        _run("equilibre", "01102026R1C1",
             [{"type": "simple_gagnant", "statut": "gagne", "gain": 30.0, "mise": 10.0,
               "chevaux": [{"numero": 3}]}], 10.0, 30.0),
        _run("equilibre", "01102026R1C2",
             [{"type": "simple_gagnant", "statut": "perdu", "gain": None, "mise": 10.0,
               "chevaux": [{"numero": 5}]}], 10.0, 0.0),
        _run("agressif", "01102026R1C3",
             [{"type": "simple_gagnant", "statut": "perdu", "gain": None, "mise": 10.0,
               "chevaux": [{"numero": 7}]}], 10.0, 0.0),
    ]
    data = await stats._palmares_rows(_FakeDB(rows))
    assert data["total_gain"] == 30.0
    # Ancien calcul : mise des seuls gagnants (10 €) → « bénéfice » de +20 €.
    assert data["total_mise"] == 10.0
    # Cohorte entière : 3 courses à 10 € → net nul.
    assert data["mise_cohorte"] == 30.0
    assert data["retour_cohorte"] == 30.0
    assert data["n_courses_reglees"] == 3


@pytest.mark.asyncio
async def test_palmares_public_sert_mise_engagee_et_net(client: AsyncClient):
    data = (await client.get("/api/v1/stats/palmares-public")).json()
    assert "total_mise_engagee" in data
    assert "total_net" in data
    assert "nb_courses_reglees" in data
    # Toujours pas de ROI ni d'agrégats par profil en public.
    assert "roi" not in data
    assert "profils" not in data


def test_palmares_admin_benefice_sur_la_cohorte_entiere():
    src = _src(stats.stats_palmares_gagnants)
    assert 'data["retour_cohorte"] - data["mise_cohorte"]' in src
    assert 'data["total_gain"] - data["total_mise"]' not in src


# ── Règlement au rapport officiel ────────────────────────────────────────────

def test_rapport_gagnant_lit_le_rapport_publie():
    assert stats._rapport_gagnant({"e_simple_gagnant": 4.2}) == 4.2
    assert stats._rapport_gagnant({"simple_gagnant_international": 3.1}) == 3.1
    assert stats._rapport_gagnant({}) is None
    assert stats._rapport_gagnant(None) is None
    assert stats._rapport_gagnant({"e_simple_gagnant": 0}) is None


def test_vb_performance_regle_au_rapport_et_exclut_les_non_partants():
    src = _src(stats._compute_track_record)
    debut = src.index("# ── 5. vb performance par niveau")
    fin = src.index("# ── 6b. favori ia")
    bloc = src[debut:fin]
    assert ".order_by(" in bloc
    assert "participation.non_partant.is_(false)" in bloc
    assert "_rapport_gagnant(vb_rapports)" in bloc
    # La cote affichée ne règle plus rien.
    assert "vb_cote - 1" not in bloc
    assert "participation.cote_pmu" not in bloc


# ── CLV ─────────────────────────────────────────────────────────────────────

def test_clv_cote_au_pronostic_et_cloture_bornee_au_depart():
    src = _src(stats._compute_track_record)
    debut = src.index("clv_row = (await db.execute")
    bloc = src[debut:src.index("if clv_row and", debut)]
    assert "p.cote_figee" in bloc
    assert "h.time <= f.date_heure" in bloc
    assert "pa.non_partant = false" in bloc
    # Les cotes inchangées ne sortent plus du dénominateur.
    assert "o <> c" not in bloc
    assert "order by h.time asc" not in bloc


# ── Favori IA ───────────────────────────────────────────────────────────────

def test_favori_roi_none_sans_mise_et_denominateur_expose():
    src = _src(stats._compute_track_record)
    assert "roi_fav = round(net_fav / mise_fav * 100, 1) if mise_fav else none" in src
    assert '"nb_favoris_regles": nb_favoris_regles' in src
    assert '"favori_hasard_top1": favori_hasard_top1' in src


# ── Value bets ──────────────────────────────────────────────────────────────

def _ligne(proba, cote_figee):
    vb = SimpleNamespace(vb_id="v", course_id="c", participation_id="p", ev_max=0.21,
                         ev_pmu=0.2, niveau=3, meilleure_source="pmu", actif=True,
                         detecte_a=datetime(2026, 10, 7, 12, 5, tzinfo=timezone.utc),
                         spi_detected=False, spi_score=None)
    part = SimpleNamespace(numero=4, casaque_image_url=None, musique=None,
                           mouvement_cote_pct=None, cote_pmu=9.0, cote_reference=8.0,
                           cote_betfair_exchange=None, cote_winamax=None, cote_betclic=None,
                           cote_unibet=None, cote_bet365=None, cote_ladbrokes=None)
    cheval = SimpleNamespace(nom="TEST")
    course = SimpleNamespace(hippodrome_nom="X", date_heure=datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc),
                             numero_reunion=1, numero=2, nom="Prix", discipline="plat",
                             distance=2000, nb_partants=12, est_quinte=False, statut="programme")
    pred = SimpleNamespace(proba_top1=proba, proba_top1_low=None, proba_top1_high=None,
                           proba_top3=0.3, rang_predit=2, confidence_score=70.0,
                           cote_figee=cote_figee)
    return valuebets_lecture.ligne(vb, part, cheval, course, pred, None, None)


def test_value_bet_expose_la_cote_de_detection():
    d = _ligne(0.15, 7.5)
    assert d["cote_detection"] == 7.5
    assert d["cote_pmu"] == 9.0
    # Sérialisable par le modèle REST.
    out = predictions_routes.ValueBetOut(**d)
    assert out.cote_detection == 7.5


def test_value_bet_cote_juste_unifiee():
    assert _ligne(0.15, 7.5)["cote_juste"] == cote_juste(0.15)
    # Avant : round(1/p, 2) = 1250.0, sans plafond.
    assert _ligne(0.0008, 7.5)["cote_juste"] is None
    assert _ligne(0.002, None)["cote_juste"] == cote_juste(0.002) <= 999
    assert _ligne(0.15, None)["cote_detection"] is None


# ── /predictions : plus de requête recommandations ──────────────────────────

def test_predictions_ne_requete_plus_les_recommandations():
    src = inspect.getsource(predictions_routes)
    assert "select(Recommandation)" not in src
