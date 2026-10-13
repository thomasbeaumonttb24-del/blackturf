"""Palmarès public : jamais plus d'un calcul à la fois (incident 2026-10-13).

07:06-07:09 UTC : la clé `stats:palmares-public`, supprimée à chaque fin de course,
était recalculée par chaque visiteur arrivé pendant le calcul — trois
`_palmares_rows` concurrents de 107-113 s, l'API en 504 pour tous.

Contrat verrouillé ici :
  1. copie périmée → servie tout de suite, UN recalcul en fond ;
  2. aucune copie → N requêtes simultanées = UN seul calcul ;
  3. la fin de course efface la fraîcheur, jamais la copie.
"""
import asyncio
import inspect
import json

import pytest

from api.routes import stats as stats_mod
from api.routes.stats import (
    PALMARES_PUBLIC_CACHE_KEY, _cache_get_swr, stats_palmares_public,
)
from tests.test_track_record_cache import FauxRedis



@pytest.fixture
def calculs(monkeypatch):
    """Remplace le calcul lourd par un calcul lent compté."""
    compteur = {"n": 0}

    async def faux_calcul(_db):
        compteur["n"] += 1
        await asyncio.sleep(0.2)
        return {"nb_paris_gagnes": compteur["n"]}

    monkeypatch.setattr(stats_mod, "_compute_palmares_public", faux_calcul)
    return compteur


@pytest.mark.asyncio
async def test_copie_perimee_servie_et_un_seul_recalcul(monkeypatch, calculs):
    r = FauxRedis()
    r.store[PALMARES_PUBLIC_CACHE_KEY] = json.dumps({"nb_paris_gagnes": 0})  # pas de :fresh

    async def faux_get_redis():
        return r
    monkeypatch.setattr("db.redis_client.get_redis", faux_get_redis)

    class FauxSession:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *a):
            return False
    monkeypatch.setattr("db.database.AsyncSessionLocal", FauxSession)

    reponses = await asyncio.gather(*[stats_palmares_public(db=None, redis=r) for _ in range(5)])
    assert all(x == {"nb_paris_gagnes": 0} for x in reponses)   # copie servie, sans attendre
    await asyncio.sleep(0.4)                                    # le recalcul de fond se termine
    assert calculs["n"] == 1
    assert await _cache_get_swr(r, PALMARES_PUBLIC_CACHE_KEY) == ({"nb_paris_gagnes": 1}, True)


@pytest.mark.asyncio
async def test_sans_copie_requetes_simultanees_un_seul_calcul(calculs):
    r = FauxRedis()
    reponses = await asyncio.gather(*[stats_palmares_public(db=None, redis=r) for _ in range(4)])
    assert calculs["n"] == 1
    assert all(x == {"nb_paris_gagnes": 1} for x in reponses)
    assert f"{PALMARES_PUBLIC_CACHE_KEY}:lock" not in r.store   # verrou relâché


@pytest.mark.asyncio
async def test_copie_fraiche_aucun_calcul(calculs):
    r = FauxRedis()
    r.store[PALMARES_PUBLIC_CACHE_KEY] = json.dumps({"nb_paris_gagnes": 9})
    r.store[f"{PALMARES_PUBLIC_CACHE_KEY}:fresh"] = "1"
    assert await stats_palmares_public(db=None, redis=r) == {"nb_paris_gagnes": 9}
    assert calculs["n"] == 0


def test_fin_de_course_efface_la_fraicheur_pas_la_copie():
    from ml import pipeline
    src = inspect.getsource(pipeline._invalidate_stats_caches)
    assert '"stats:palmares-public:fresh"' in src
    assert '"stats:palmares-public",' not in src
