"""Tableau de bord abonnements (2026-09-14).

1. **Personnes en ligne.** Aucune mesure n'existait : `last_login_at` date une
   connexion (la session vit 7 jours), pas une visite, et un anonyme n'y figure
   jamais. Chaque onglet visible envoie désormais un signal par minute.
2. **Répartition des comptes.** L'écran comptait des LIGNES d'abonnement, et ne
   montrait nulle part les comptes Expert offerts à la main (amis, tests).
"""
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

import services.presence as presence
from db.models import Subscription, User

pytestmark = pytest.mark.asyncio


class RedisEnMemoire:
    """Juste ce que `services/presence` utilise d'un client Redis."""

    def __init__(self):
        self.zset: dict[str, float] = {}
        self.kv: dict[str, str] = {}

    def pipeline(self):
        redis = self
        ops = []

        class Pipe:
            def zadd(self, _cle, mapping):
                ops.append(lambda: redis.zset.update(mapping))

            def zremrangebyscore(self, _cle, mini, maxi):
                ops.append(lambda: redis._purge(mini, maxi))

            def set(self, cle, valeur, ex=None):
                ops.append(lambda: redis.kv.__setitem__(cle, valeur))

            async def execute(self):
                for op in ops:
                    op()

        return Pipe()

    def _purge(self, mini, maxi):
        for m in [m for m, s in self.zset.items() if mini <= s <= maxi]:
            del self.zset[m]

    async def zremrangebyscore(self, _cle, mini, maxi):
        self._purge(mini, maxi)

    async def zrangebyscore(self, _cle, mini, _maxi):
        return [m for m, s in sorted(self.zset.items(), key=lambda x: x[1]) if s >= mini]

    async def mget(self, cles):
        return [self.kv.get(c) for c in cles]


@pytest.fixture
def redis_presence(monkeypatch):
    faux = RedisEnMemoire()

    async def _get():
        return faux

    monkeypatch.setattr(presence, "get_redis", _get)
    return faux


# ─────────────────────────────────────────────
# 1. Présence
# ─────────────────────────────────────────────
async def test_un_compte_connecte_compte_une_fois_quel_que_soit_le_nombre_donglets(redis_presence):
    await presence.signaler("onglet-aaaa-1111", "user-1", "/programme")
    await presence.signaler("onglet-bbbb-2222", "user-1", "/course/42")
    await presence.signaler("anonyme-cccc-3333", None, "/")

    photo = await presence.en_ligne()
    assert len(photo["visiteurs"]) == 2
    connecte = next(v for v in photo["visiteurs"] if v["user_id"] == "user-1")
    assert connecte["chemin"] == "/course/42", "la page affichée est la dernière signalée"


async def test_un_visiteur_silencieux_depuis_5_min_nest_plus_en_ligne(redis_presence):
    await presence.signaler("anonyme-dddd-4444", None, "/")
    redis_presence.zset["a:anonyme-dddd-4444"] = time.time() - presence.FENETRE_S - 1

    assert (await presence.en_ligne())["visiteurs"] == []


async def test_redis_en_panne_rend_inconnu_et_jamais_zero(monkeypatch):
    async def _panne():
        raise ConnectionError("redis down")

    monkeypatch.setattr(presence, "get_redis", _panne)
    await presence.signaler("anonyme-eeee-5555", None, "/")   # ne lève pas
    assert await presence.en_ligne() is None


async def test_la_route_ne_garde_pas_la_query_string(client: AsyncClient, redis_presence):
    """Un lien de réinitialisation porte son jeton dans l'URL."""
    resp = await client.post("/api/v1/presence",
                             json={"v": "anonyme-ffff-6666", "p": "/reset?token=secret"})
    assert resp.status_code == 204
    assert all("secret" not in v for v in redis_presence.kv.values())


async def test_la_route_ignore_un_identifiant_invalide(client: AsyncClient, redis_presence):
    resp = await client.post("/api/v1/presence", json={"v": "<script>xx</script>", "p": "/"})
    assert resp.status_code in (204, 422)
    assert redis_presence.zset == {}


async def test_un_jeton_invalide_compte_comme_anonyme_sans_401(client: AsyncClient, redis_presence):
    resp = await client.post("/api/v1/presence", json={"v": "anonyme-gggg-7777", "p": "/"},
                             headers={"Authorization": "Bearer pas-un-jwt"})
    assert resp.status_code == 204
    assert list(redis_presence.zset) == ["a:anonyme-gggg-7777"]


async def test_en_ligne_reserve_admin(client: AsyncClient, auth_headers):
    assert (await client.get("/admin/api/en-ligne", headers=auth_headers)).status_code == 403


async def test_en_ligne_nomme_les_comptes_connectes(client: AsyncClient, admin_headers, db,
                                                  redis_presence):
    ami = User(user_id=str(uuid.uuid4()), email="ami@blackturf.fr", plan="expert")
    db.add(ami)
    await db.commit()
    await presence.signaler("onglet-hhhh-8888", ami.user_id, "/programme")
    await presence.signaler("anonyme-iiii-9999", None, "/programme")
    await presence.signaler("anonyme-jjjj-0000", None, "/")

    data = (await client.get("/admin/api/en-ligne", headers=admin_headers)).json()
    assert data["disponible"] is True
    assert (data["total"], data["connectes"], data["anonymes"]) == (3, 1, 2)
    assert data["comptes"][0]["email"] == "ami@blackturf.fr"
    assert data["pages"][0] == {"chemin": "/programme", "n": 2}


# ─────────────────────────────────────────────
# 2. Répartition des comptes
# ─────────────────────────────────────────────
def _abo(user_id: str, plan: str, essai_fin=None) -> Subscription:
    debut = datetime.now(timezone.utc)
    return Subscription(sub_id=str(uuid.uuid4()), user_id=user_id,
                        stripe_subscription_id=f"sub_{uuid.uuid4().hex[:10]}", plan=plan,
                        periodicite="monthly", periode_debut=debut,
                        periode_fin=debut + timedelta(days=30), statut="active",
                        essai_fin=essai_fin)


async def test_chaque_compte_tombe_dans_une_seule_case(client: AsyncClient, admin_headers, db):
    def compte(email, plan):
        return User(user_id=str(uuid.uuid4()), email=email, plan=plan)

    payant = compte("payant@x.fr", "expert")
    essai = compte("essai@x.fr", "standard")
    ami = compte("ami@x.fr", "expert")
    gratuit = compte("gratuit@x.fr", "free")
    db.add_all([payant, essai, ami, gratuit])
    db.add_all([
        _abo(payant.user_id, "expert"),
        _abo(essai.user_id, "standard",
             essai_fin=datetime.now(timezone.utc) + timedelta(days=4)),
    ])
    await db.commit()

    data = (await client.get("/admin/api/abonnements", headers=admin_headers)).json()
    r = data["repartition"]
    # Le compte admin des fixtures n'est compté nulle part.
    assert (r["comptes"], r["payants"], r["essais"], r["offerts"], r["gratuits"]) == (4, 1, 1, 1, 1)
    assert r["payants"] + r["essais"] + r["offerts"] + r["gratuits"] == r["comptes"]
    assert r["par_formule"]["expert"] == {"payants": 1, "essais": 0, "offerts": 1}
    assert r["par_formule"]["standard"] == {"payants": 0, "essais": 1, "offerts": 0}
    assert [o["email"] for o in data["offerts"]] == ["ami@x.fr"]
