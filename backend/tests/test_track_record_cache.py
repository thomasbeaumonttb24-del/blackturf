"""
Régression : la page Palmarès restait bloquée sur son skeleton (2026-08-18).

`/stats/track-record` coûte ~29 s à froid en prod, le client axios abandonne à 15 s
et `refreshInterval: 60_000` relance en boucle → chaque tentative expirait, donc
skeleton perpétuel pendant TOUTE la fenêtre de cache froid.

`job_warm_caches` ne rattrapait rien : tant que le cache était chaud, l'endpoint
renvoyait tôt SANS réécrire la clé, le TTL n'était donc jamais prolongé et
l'expiration tombait à une heure décorrélée du cron /30 min.

Contrat désormais garanti : tant qu'une version antérieure existe en Redis, aucune
requête utilisateur ne déclenche le calcul lourd dans son chemin.
"""
import asyncio
import json

import pytest

from api.routes import stats as stats_mod
from api.routes.stats import (
    TRACK_RECORD_CACHE_KEY,
    _cache_get_swr,
    _cache_set_swr,
    refresh_track_record_cache,
    track_record,
)

pytestmark = pytest.mark.asyncio


class FauxRedis:
    """Redis minimal en mémoire : get/setex/exists/set(nx)/delete."""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.ttl: dict[str, int] = {}

    async def get(self, key):
        return self.store.get(key)

    async def setex(self, key, ttl, value):
        self.store[key] = value
        self.ttl[key] = ttl
        return True

    async def exists(self, key):
        return 1 if key in self.store else 0

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = value
        if ex:
            self.ttl[key] = ex
        return True

    async def delete(self, key):
        return 1 if self.store.pop(key, None) is not None else 0

    def expirer_fraicheur(self):
        """Simule l'expiration du drapeau de fraîcheur, la charge utile restant là."""
        self.store.pop(f"{TRACK_RECORD_CACHE_KEY}:fresh", None)


# ─────────────────────────────────────────────
# Helpers de cache
# ─────────────────────────────────────────────
async def test_swr_absent_renvoie_none_et_non_frais():
    assert await _cache_get_swr(FauxRedis(), "vide") == (None, False)


async def test_swr_ecrit_puis_relit_frais():
    r = FauxRedis()
    await _cache_set_swr(r, "k", {"a": 1}, fresh_ttl=3600)
    assert await _cache_get_swr(r, "k") == ({"a": 1}, True)


async def test_swr_conserve_la_charge_utile_bien_apres_la_fraicheur():
    """Le cœur du correctif : la conservation (24 h) doit survivre très largement à
    la fraîcheur (1 h), sinon il n'y a plus rien à servir pendant le recalcul."""
    r = FauxRedis()
    await _cache_set_swr(r, "k", {"a": 1}, fresh_ttl=3600)
    assert r.ttl["k"] > r.ttl["k:fresh"]
    assert r.ttl["k"] >= 86400


async def test_swr_perime_renvoie_la_charge_utile_et_non_frais():
    r = FauxRedis()
    await _cache_set_swr(r, "k", {"a": 1}, fresh_ttl=3600)
    r.store.pop("k:fresh")
    assert await _cache_get_swr(r, "k") == ({"a": 1}, False)


# ─────────────────────────────────────────────
# Endpoint : le calcul lourd ne doit jamais bloquer l'utilisateur
# ─────────────────────────────────────────────
async def test_cache_frais_ne_declenche_aucun_calcul(monkeypatch):
    r = FauxRedis()
    await _cache_set_swr(r, TRACK_RECORD_CACHE_KEY, {"precision": 60}, fresh_ttl=3600)

    async def _interdit(_db):
        raise AssertionError("le calcul lourd ne doit pas être appelé sur cache frais")

    monkeypatch.setattr(stats_mod, "_compute_track_record", _interdit)
    assert await track_record(db=None, redis=r) == {"precision": 60}


async def test_cache_perime_repond_immediatement_sans_calcul_inline(monkeypatch):
    """LA régression : cache périmé → on sert l'ancienne version tout de suite.
    Avant, l'utilisateur attendait 29 s pour un client qui coupe à 15 s."""
    r = FauxRedis()
    await _cache_set_swr(r, TRACK_RECORD_CACHE_KEY, {"precision": 60}, fresh_ttl=3600)
    r.expirer_fraicheur()

    async def _interdit(_db):
        raise AssertionError("calcul lourd exécuté dans le chemin de la requête")

    rafraichi = asyncio.Event()

    async def _faux_refresh():
        rafraichi.set()
        return True

    monkeypatch.setattr(stats_mod, "_compute_track_record", _interdit)
    monkeypatch.setattr(stats_mod, "refresh_track_record_cache", _faux_refresh)

    assert await track_record(db=None, redis=r) == {"precision": 60}

    # ...et le recalcul est bien programmé en arrière-plan
    await asyncio.wait_for(rafraichi.wait(), timeout=2)


async def test_cache_totalement_vide_calcule_et_ecrit(monkeypatch):
    """Seul cas où l'on paie le calcul : Redis n'a aucune version (démarrage à froid)."""
    r = FauxRedis()

    async def _calcul(_db):
        return {"precision": 42}

    monkeypatch.setattr(stats_mod, "_compute_track_record", _calcul)
    assert await track_record(db=None, redis=r) == {"precision": 42}

    assert json.loads(r.store[TRACK_RECORD_CACHE_KEY]) == {"precision": 42}
    assert f"{TRACK_RECORD_CACHE_KEY}:fresh" in r.store


# ─────────────────────────────────────────────
# Verrou de recalcul
# ─────────────────────────────────────────────
async def test_refresh_verrouille_les_recalculs_concurrents(monkeypatch):
    """Le calcul martèle la base ~29 s : deux requêtes périmées simultanées ne
    doivent pas lancer deux recalculs."""
    r = FauxRedis()
    r.store[f"{TRACK_RECORD_CACHE_KEY}:lock"] = "1"   # un recalcul est déjà en cours

    async def _get_redis():
        return r

    monkeypatch.setattr("db.redis_client.get_redis", _get_redis)

    async def _interdit(_db):
        raise AssertionError("recalcul concurrent malgré le verrou")

    monkeypatch.setattr(stats_mod, "_compute_track_record", _interdit)
    assert await refresh_track_record_cache() is False


# ── Honnêteté de la période mesurée ──────────────────────────────────────────
async def test_le_track_record_expose_depuis_quand_il_mesure():
    """Le read-model ne retient que la cohorte rejouable (snapshots pré-course,
    démarrés le 18/08/2026) : sans cette date, la page publique affiche un taux
    sans dire qu'il ne porte que sur quelques jours — c'est ce qui a fait passer
    « 33,3 % sur 9 courses » pour un track record.

    Vérification sur la SOURCE : `_compute_track_record` est écrit en SQL
    PostgreSQL (FILTER, date_trunc) que le SQLite des tests ne sait pas exécuter.
    """
    import inspect
    source = inspect.getsource(stats_mod._compute_track_record)
    assert '"mesure_depuis": mesure_depuis' in source, (
        "la période mesurée doit voyager avec les taux, pas être déduite par le front")
    assert "MIN(c.date_heure)" in source and "p.is_replayable = true" in source, (
        "la date doit venir de la cohorte RÉELLEMENT mesurée, pas de la première "
        "course connue")
