"""Classement complet : 1 course par jour pour un compte gratuit, 0 sans compte.

Règle de l'exploitant (2026-09-30) : « aucune faille de contournement possible
pour avoir plus d'un accès au classement algo par jour ». Chaque test ferme une
voie de contournement identifiée à l'audit.
"""
import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import fakeredis
import pytest
from sqlalchemy import select

from db.models import Cheval, Course, Hippodrome, Participation, Prediction, Reunion, User
from services import quota_classement as q

pytestmark = pytest.mark.asyncio


@pytest.fixture
def redis(monkeypatch):
    """Vrai moteur Redis en mémoire (Lua compris) : le script atomique est exécuté
    pour de bon, pas simulé."""
    r = fakeredis.FakeAsyncRedis()

    async def _get():
        return r

    monkeypatch.setattr(q, "_redis", _get)
    return r


def _user(plan="free", email="joueur@gmail.com", **kw):
    return SimpleNamespace(user_id=str(uuid.uuid4()), plan=plan, email=email, is_admin=False, **kw)


# ── Module ──────────────────────────────────────────────────────────────────

async def test_gratuit_une_course_par_jour(redis):
    u = _user()
    assert await q.consommer(u, "A") == (True, 0)
    assert await q.consommer(u, "A") == (True, 0)      # ré-ouverture : rien de consommé
    assert await q.consommer(u, "B") == (False, 0)


async def test_requetes_simultanees_une_seule_passe(redis):
    """50 courses demandées en même temps : l'ancien SCARD puis SADD les laissait
    toutes passer. Le script Lua n'en laisse passer qu'une."""
    u = _user()
    res = await asyncio.gather(*(q.consommer(u, f"C{i}") for i in range(50)))
    assert sum(1 for ok, _ in res if ok) == 1
    assert await redis.scard(q.cle(u)) == 1


async def test_redis_en_panne_refuse_le_gratuit_sert_le_payant(monkeypatch):
    async def _panne():
        raise ConnectionError("redis down")

    monkeypatch.setattr(q, "_redis", _panne)
    assert await q.consommer(_user("free"), "A") == (False, 0)
    assert await q.consommer(_user("decouverte"), "A") == (False, 0)
    assert await q.consommer(_user("standard"), "A") == (True, -1)


@pytest.mark.parametrize("alias", [
    "joueur+1@gmail.com", "JOUEUR+promo@Gmail.com", "j.o.u.e.u.r@gmail.com",
    "joueur@googlemail.com", "j.oueur+x@googlemail.com",
])
async def test_alias_d_une_meme_boite_partagent_le_quota(redis, alias):
    assert await q.consommer(_user(email="joueur@gmail.com"), "A") == (True, 0)
    assert await q.consommer(_user(email=alias), "B") == (False, 0)
    assert await q.consommer(_user(email=alias), "A") == (True, 0)


async def test_boites_distinctes_quotas_distincts(redis):
    assert (await q.consommer(_user(email="a@exemple.fr"), "A"))[0]
    assert (await q.consommer(_user(email="b@exemple.fr"), "B"))[0]
    # Hors Gmail, les points comptent : deux boîtes différentes.
    assert (await q.consommer(_user(email="a.b@exemple.fr"), "C"))[0]
    assert (await q.consommer(_user(email="ab@exemple.fr"), "D"))[0]


async def test_plan_inconnu_n_est_jamais_illimite(redis):
    u = _user(plan="plan_inattendu")
    assert await q.consommer(u, "A") == (True, 0)
    assert await q.consommer(u, "B") == (False, 0)


async def test_standard_cinq_expert_illimite(redis):
    s = _user("standard", email="s@exemple.fr")
    assert [ (await q.consommer(s, f"S{i}"))[0] for i in range(6)] == [True] * 5 + [False]
    e = _user("expert", email="e@exemple.fr")
    assert all([(await q.consommer(e, f"E{i}"))[0] for i in range(20)])


async def test_etat_ne_consomme_rien(redis):
    u = _user()
    assert (await q.etat(u))["restant"] == 1
    assert (await q.etat(u))["restant"] == 1
    await q.consommer(u, "A")
    assert await q.etat(u) == {"limite": 1, "restant": 0, "courses": ["A"]}


def test_le_jour_est_celui_de_paris():
    # 23 h 30 UTC le 30/09 = 1 h 30 à Paris le 01/10 (heure d'été).
    assert q.jour_paris(datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc)) == "2026-10-01"


# ── Routes ──────────────────────────────────────────────────────────────────

async def _course(db, course_id: str, statut: str = "a_venir") -> None:
    hippo = Hippodrome(hippodrome_id=str(uuid.uuid4()), nom=f"H {course_id}", code=uuid.uuid4().hex[:4])
    db.add(hippo)
    db.add(Reunion(reunion_id=f"RQ-{course_id}", date=date.today(),
                   hippodrome_id=hippo.hippodrome_id, hippodrome_nom="Quota Test", numero=1))
    db.add(Course(course_id=course_id, reunion_id=f"RQ-{course_id}", numero=1, nom="Prix Quota",
                  date_heure=datetime.now(timezone.utc) + timedelta(hours=3),
                  hippodrome_nom="Quota Test", discipline="Attelé", distance=2700,
                  nb_partants=3, statut=statut))
    for numero, nom, cote, proba, rang in [(7, "SECRET UN", 9.5, 0.30, 1),
                                           (3, "SECRET DEUX", 2.4, 0.25, 2),
                                           (5, "SECRET TROIS", 48.0, 0.01, 3)]:
        cid, pid = str(uuid.uuid4()), str(uuid.uuid4())
        db.add(Cheval(cheval_id=cid, nom=nom, age=5, sexe="H"))
        db.add(Participation(participation_id=pid, course_id=course_id, cheval_id=cid,
                             numero=numero, cote_pmu=cote, non_partant=False))
        db.add(Prediction(prediction_id=str(uuid.uuid4()), participation_id=pid, course_id=course_id,
                          proba_top1=proba, proba_top3=min(0.99, proba * 2), rang_predit=rang,
                          confidence_score=60.0))
    await db.commit()


def _ouvert(resp) -> bool:
    data = resp.json()
    return resp.status_code == 200 and data["verrouille"] is False and any(
        p["rang_predit"] == 1 for p in data["predictions"])


async def test_sans_compte_aucun_classement(client, db, redis):
    await _course(db, "QA1")
    r = await client.get("/api/v1/courses/QA1/predictions", params={"reveler": True})
    assert r.status_code == 401


async def test_parcours_gratuit_complet(client, db, redis, inscrire):
    await _course(db, "QB1")
    await _course(db, "QB2")
    h = await inscrire(email="parieur@gmail.com")

    # Simple consultation : verrouillé, et RIEN n'est consommé.
    r = await client.get("/api/v1/courses/QB1/predictions", headers=h)
    assert r.json()["verrouille"] is True
    assert all(p["rang_predit"] == 0 and p["proba_top1"] == 0 for p in r.json()["predictions"])
    assert (await client.get("/api/v1/quota/classement", headers=h)).json()["restant"] == 1

    # Plan de mise avant d'avoir révélé : refusé, sans consommer la course du jour.
    r = await client.post("/api/v1/courses/QB1/mise-plan", headers=h, json={"montant": 10})
    assert r.status_code == 403
    assert (await client.get("/api/v1/quota/classement", headers=h)).json()["restant"] == 1

    # Révélation explicite : ouvert, et reste ouvert.
    assert _ouvert(await client.get("/api/v1/courses/QB1/predictions", headers=h, params={"reveler": True}))
    assert _ouvert(await client.get("/api/v1/courses/QB1/predictions", headers=h))

    # Deuxième course : refusée, même en insistant.
    r = await client.get("/api/v1/courses/QB2/predictions", headers=h, params={"reveler": True})
    assert r.json()["verrouille"] is True
    assert "SECRET" not in str([p for p in r.json()["predictions"] if p["rang_predit"]])

    # Le plan de mise ne sert pas de second classement.
    r = await client.post("/api/v1/courses/QB2/mise-plan", headers=h, json={"montant": 10})
    assert r.status_code == 403


async def test_alias_d_inscription_ne_donnent_pas_un_second_classement(client, db, redis, inscrire):
    """Deux verrous : (1) depuis le 2026-10-04 l'inscription d'un alias d'une boîte
    déjà inscrite est refusée ; (2) un alias créé AVANT cette règle partage
    toujours le quota de la boîte d'origine."""
    import uuid
    from api.routes.auth import _hash
    await _course(db, "QC1")
    await _course(db, "QC2")
    h1 = await inscrire(email="malin@gmail.com")
    r = await client.post("/api/v1/auth/register", json={
        "email": "malin+bis@gmail.com", "password": "TestPassword123!", "pseudo": "malinbis"})
    assert r.status_code == 400
    # Alias hérité (créé avant la règle) : on le pose en base et on s'y connecte.
    db.add(User(user_id=str(uuid.uuid4()), email="malin+bis@gmail.com", hashed_password=_hash("TestPassword123!"),
                plan="free", email_verified=True, pseudo="malinbis"))
    await db.commit()
    login = await client.post("/api/v1/auth/login", data={"username": "malin+bis@gmail.com",
                                                          "password": "TestPassword123!"})
    h2 = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert _ouvert(await client.get("/api/v1/courses/QC1/predictions", headers=h1, params={"reveler": True}))
    r = await client.get("/api/v1/courses/QC2/predictions", headers=h2, params={"reveler": True})
    assert r.json()["verrouille"] is True


async def test_adresse_non_confirmee_n_ouvre_rien(client, db, redis, inscrire):
    await _course(db, "QD1")
    h = await inscrire(email="pasconfirme@exemple.fr")
    u = (await db.execute(select(User).where(User.email == "pasconfirme@exemple.fr"))).scalar_one()
    u.email_verified = False
    u.created_at = datetime.now(timezone.utc)
    await db.commit()
    r = await client.get("/api/v1/courses/QD1/predictions", headers=h, params={"reveler": True})
    assert r.status_code in (401, 403) or r.json()["verrouille"] is True


async def test_envoi_par_email_ferme_pour_une_course_a_venir(client, db, redis):
    await _course(db, "QE1")
    r = await client.post("/api/v1/courses/QE1/envoyer-pronostic",
                          json={"email": "visiteur@exemple.fr", "source": "fiche_course_popup"})
    assert r.status_code == 200 and r.json()["ok"] is False
    assert "compte" in r.json()["message"]


async def test_scenario_exploitant_fermer_la_page_puis_revenir(client, db, redis, inscrire):
    """Scénario demandé par l'exploitant le 2026-09-30 :
    compte gratuit → révèle la course A → ferme la page (nouvelle session,
    nouveau jeton) → revient sur A : toujours visible → va sur B : verrouillé,
    par toutes les portes (consultation, `reveler`, plan de mise, 2e compte alias).
    """
    await _course(db, "QS-A")
    await _course(db, "QS-B")
    h = await inscrire(email="scenario@exemple.fr", password="TestPassword123!")

    assert _ouvert(await client.get("/api/v1/courses/QS-A/predictions", headers=h, params={"reveler": True}))

    # « Ferme la page » : nouvelle connexion, nouveau jeton, aucun état navigateur.
    login = await client.post("/api/v1/auth/login",
                              data={"username": "scenario@exemple.fr", "password": "TestPassword123!"})
    h2 = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # Retour sur A : la course débloquée reste visible (sans redemander).
    assert _ouvert(await client.get("/api/v1/courses/QS-A/predictions", headers=h2))
    r = await client.post("/api/v1/courses/QS-A/mise-plan", headers=h2, json={"montant": 10})
    assert r.status_code != 403

    # Course B : verrouillée, par toutes les portes.
    for params in ({}, {"reveler": True}, {"reveler": "1"}, {"reveler": "true", "bankroll": 0}):
        r = await client.get("/api/v1/courses/QS-B/predictions", headers=h2, params=params)
        assert r.status_code == 200 and r.json()["verrouille"] is True, params
        assert all(p["rang_predit"] == 0 and p["proba_top1"] == 0 and p["cote_juste"] is None
                   for p in r.json()["predictions"])
    assert (await client.post("/api/v1/courses/QS-B/mise-plan", headers=h2, json={"montant": 10})).status_code == 403
    etat = (await client.get("/api/v1/quota/classement", headers=h2)).json()
    assert etat == {"limite": 1, "restant": 0, "courses": ["QS-A"]}

    # Aperçu public de B : aucun nom du haut du classement, ni indice qui le nomme.
    ap = (await client.get("/api/v1/courses/QS-B/apercu")).json()
    assert ap["accord_marche"] is None and ap["bande_cote"] is None
    assert "SECRET UN" not in str(ap)
