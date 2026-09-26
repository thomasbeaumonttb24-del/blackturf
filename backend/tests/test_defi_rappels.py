"""Défi du mois : alertes de classement (1re place, podium) et rappels quotidiens."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from db.models import AlerteLog, DefiPari, User
from services import defi, defi_rappels
from tests.test_defi import _arrivee, _course, _user



@pytest.fixture(autouse=True)
def _cache_classement_vide(monkeypatch):
    # Hors tests du mois d'essai : le défi est réputé lancé depuis longtemps.
    monkeypatch.setattr(defi, "PREMIER_MOIS", "2000-01")
    defi.invalider_classement()
    yield
    defi.invalider_classement()


async def _paris(db, user, n, *, mois, engage_at, gagnant=False):
    for i in range(n):
        db.add(DefiPari(user_id=user.user_id, mois=mois, course_id=f"{uuid.uuid4().hex[:8]}",
                        type_pari="Simple Gagnant", chevaux=[1], points=10, origine="perso",
                        engage_at=engage_at, statut="gagne" if gagnant else "perd",
                        rapport=3.0 if gagnant else None,
                        points_retour=30.0 if gagnant else 0.0))
    await db.commit()


async def _alertes(db, user, type_alerte):
    return (await db.execute(select(AlerteLog).where(
        AlerteLog.user_id == user.user_id, AlerteLog.type_alerte == type_alerte))).scalars().all()


# ─── Alertes de classement ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_prise_et_perte_de_la_1re_place_apres_reglement(db):
    maintenant = datetime.now(timezone.utc)
    mois = defi.mois_courant()
    leader = await _user(db, email="leader@x.fr", pseudo="Leader")
    chasseur = await _user(db, email="chasseur@x.fr", pseudo="Chasseur")
    await _paris(db, leader, 10, mois=mois, engage_at=maintenant, gagnant=True)   # 1200
    await _paris(db, chasseur, 10, mois=mois, engage_at=maintenant)               # 900
    course = await _course(db)
    await defi.engager_pari(db, chasseur, "C1", "Simple Gagnant", [3], 100)
    await _arrivee(db, course)  # 3 gagne à 4,2 : 800 + 420 = 1220

    assert await defi.regler_course(db, "C1") == 1

    [prise] = await _alertes(db, chasseur, defi_rappels.TYPE_RANG)
    assert prise.payload["titre"] == "Défi : vous prenez la 1re place !"
    assert "20 pts d'avance sur Leader" in prise.payload["description"]
    assert prise.payload["lien"] == "/defi"
    [perte] = await _alertes(db, leader, defi_rappels.TYPE_RANG)
    assert perte.payload["titre"] == "Défi : vous avez perdu la 1re place"
    assert "Chasseur passe devant" in perte.payload["description"]


@pytest.mark.asyncio
async def test_pas_de_rafale_d_alertes_de_rang(db):
    mois = defi.mois_courant()
    maintenant = datetime.now(timezone.utc)
    a = await _user(db, email="a@x.fr")
    b = await _user(db, email="b@x.fr")
    await _paris(db, a, 10, mois=mois, engage_at=maintenant, gagnant=True)
    await _paris(db, b, 10, mois=mois, engage_at=maintenant)
    avant = [{"user_id": b.user_id, "rang": 1}, {"user_id": a.user_id, "rang": 2}]
    assert await defi_rappels.notifier_rangs(db, mois, avant) == 2
    # Même bascule juste après : rien de plus, les deux viennent d'être prévenus.
    assert await defi_rappels.notifier_rangs(db, mois, avant) == 0


@pytest.mark.asyncio
async def test_alerte_de_rang_respecte_la_preference(db):
    mois = defi.mois_courant()
    maintenant = datetime.now(timezone.utc)
    a = await _user(db, email="a@x.fr", push_subscription={"prefs": {"resultats_suivis": False}})
    b = await _user(db, email="b@x.fr")
    await _paris(db, a, 10, mois=mois, engage_at=maintenant, gagnant=True)
    await _paris(db, b, 10, mois=mois, engage_at=maintenant)
    avant = [{"user_id": b.user_id, "rang": 1}, {"user_id": a.user_id, "rang": 2}]
    assert await defi_rappels.notifier_rangs(db, mois, avant) == 1
    assert await _alertes(db, a, defi_rappels.TYPE_RANG) == []


def _l(uid, rang, solde, nom=None):
    return {"user_id": uid, "rang": rang, "solde": solde, "nom": nom or uid}


def test_seuils_du_podium():
    lignes = [_l("a", 1, 1500), _l("b", 2, 1400), _l("c", 3, 1300), _l("d", 4, 1250)]
    assert defi_rappels.message_rang(5, 3, lignes[2], lignes)[0] == "Défi : vous montez sur le podium (3e)"
    sortie = defi_rappels.message_rang(3, 4, lignes[3], lignes)
    assert sortie == ("Défi : vous sortez du podium", "Vous êtes 4e, à 50 pts de la 3e place.")
    # Une place gagnée sans franchir de seuil ne dérange personne.
    assert defi_rappels.message_rang(7, 5, _l("e", 5, 1200), lignes) is None
    assert defi_rappels.message_rang(3, 2, lignes[1], lignes) is None


def test_format_des_points():
    assert defi.formater_points(1234.5) == "1 234,5 pts"
    assert defi.formater_points(20.0) == "20 pts"


# ─── Rappels quotidiens ─────────────────────────────────────────────────────

SEPT = "2026-09"


@pytest.mark.asyncio
async def test_rappel_paris_manquants_une_seule_fois_par_palier(db):
    u = await _user(db, email="u@x.fr")
    now = datetime(2026, 9, 25, 9, tzinfo=timezone.utc)  # 6 jours restants
    await _paris(db, u, 3, mois=SEPT, engage_at=now - timedelta(days=1))

    assert await defi_rappels.envoyer_rappels(db, now) == 1
    [r] = await _alertes(db, u, defi_rappels.TYPE_RAPPEL)
    assert r.payload["titre"] == "Défi : encore 7 paris pour être classé"
    assert r.payload["cle"] == "2026-09:classement:J10"
    assert await defi_rappels.envoyer_rappels(db, now + timedelta(days=1)) == 0
    # Palier suivant à 3 jours de la fin.
    assert await defi_rappels.envoyer_rappels(db, datetime(2026, 9, 28, 9, tzinfo=timezone.utc)) == 1


@pytest.mark.asyncio
async def test_rappel_derniere_ligne_droite_donne_l_ecart(db):
    premier = await _user(db, email="p@x.fr", pseudo="Premier")
    second = await _user(db, email="s@x.fr")
    now = datetime(2026, 9, 29, 9, tzinfo=timezone.utc)
    await _paris(db, premier, 10, mois=SEPT, engage_at=now, gagnant=True)
    await _paris(db, second, 10, mois=SEPT, engage_at=now)

    assert await defi_rappels.envoyer_rappels(db, now) == 2
    [r] = await _alertes(db, second, defi_rappels.TYPE_RAPPEL)
    assert r.payload["titre"] == "Défi : plus que 2 jours"
    assert r.payload["description"] == "Vous êtes 2e, à 300 pts de la 1re place."


@pytest.mark.asyncio
async def test_rappel_nouvelle_cagnotte_en_debut_de_mois(db):
    ancien = await _user(db, email="ancien@x.fr")
    deja_reparti = await _user(db, email="reparti@x.fr")
    admin = await _user(db, email="admin@x.fr", is_admin=True)
    fin_sept = datetime(2026, 9, 20, 9, tzinfo=timezone.utc)
    now = datetime(2026, 10, 2, 9, tzinfo=timezone.utc)
    await _paris(db, ancien, 10, mois=SEPT, engage_at=fin_sept, gagnant=True)
    for u in (deja_reparti, admin):
        await _paris(db, u, 10, mois=SEPT, engage_at=fin_sept)
    await _paris(db, deja_reparti, 1, mois="2026-10", engage_at=now)

    assert await defi_rappels.envoyer_rappels(db, now) == 1
    [r] = await _alertes(db, ancien, defi_rappels.TYPE_RAPPEL)
    assert r.payload["titre"] == "Défi : 1 000 pts tout neufs vous attendent"
    assert r.payload["description"].startswith("Vous avez fini 1er en septembre.")


@pytest.mark.asyncio
async def test_relance_d_un_joueur_inactif_et_preference_respectee(db):
    inactif = await _user(db, email="i@x.fr")
    muet = await _user(db, email="m@x.fr", push_subscription={"prefs": {"alertes_systeme": False}})
    now = datetime(2026, 9, 18, 9, tzinfo=timezone.utc)
    for u in (inactif, muet):
        await _paris(db, u, 10, mois=SEPT, engage_at=now - timedelta(days=9))

    assert await defi_rappels.envoyer_rappels(db, now) == 1
    [r] = await _alertes(db, inactif, defi_rappels.TYPE_RAPPEL)
    assert r.payload["titre"] == "Défi : il vous reste 900 pts"
    assert await _alertes(db, muet, defi_rappels.TYPE_RAPPEL) == []


@pytest.mark.asyncio
async def test_api_notification_porte_le_lien_du_defi(client, db, auth_headers):
    me = (await db.execute(select(User).where(User.email == "test@blackturf.fr"))).scalars().one()
    db.add(AlerteLog(user_id=me.user_id, type_alerte="defi_rappel", canal="in-app", envoye=True,
                     payload={"titre": "Défi : x", "description": "y", "lien": "/defi"}))
    db.add(AlerteLog(user_id=me.user_id, type_alerte="defi_rang", canal="in-app", envoye=True,
                     payload={"titre": "Défi : z", "description": "", "lien": "https://evil.example"}))
    await db.commit()
    items = (await client.get("/api/v1/notifications", headers=auth_headers)).json()["items"]
    par_type = {i["type_alerte"]: i for i in items}
    assert (par_type["defi_rappel"]["lien"], par_type["defi_rappel"]["categorie"]) == ("/defi", "systeme")
    assert (par_type["defi_rang"]["lien"], par_type["defi_rang"]["categorie"]) == (None, "resultat")


# ─── Mois d'essai (avant le lancement officiel) ─────────────────────────────

@pytest.mark.asyncio
async def test_mois_d_essai_sans_recompense_ni_rappel_puis_annonce_du_lancement(db, monkeypatch):
    monkeypatch.setattr(defi, "PREMIER_MOIS", "2026-10")
    testeur = await _user(db, email="testeur@x.fr")
    await _paris(db, testeur, 3, mois=SEPT, engage_at=datetime(2026, 9, 26, 9, tzinfo=timezone.utc))
    await _paris(db, testeur, 7, mois=SEPT, engage_at=datetime(2026, 9, 27, 9, tzinfo=timezone.utc),
                 gagnant=True)

    # Septembre = essai : aucun rappel quotidien, aucune récompense possible.
    assert await defi_rappels.envoyer_rappels(db, datetime(2026, 9, 28, 9, tzinfo=timezone.utc)) == 0
    with pytest.raises(defi.DefiErreur, match="Mois d'essai"):
        await defi.attribuer_recompense(db, SEPT, 1, now=datetime(2026, 10, 2, tzinfo=timezone.utc))

    # 1er octobre : les joueurs de l'essai apprennent que le vrai défi commence.
    assert await defi_rappels.envoyer_rappels(db, datetime(2026, 10, 1, 9, tzinfo=timezone.utc)) == 1
    [r] = await _alertes(db, testeur, defi_rappels.TYPE_RAPPEL)
    assert r.payload["titre"] == "Le Défi du mois est lancé : les récompenses sont en jeu"


@pytest.mark.asyncio
async def test_api_signale_le_mois_d_essai(client, monkeypatch):
    monkeypatch.setattr(defi, "PREMIER_MOIS", "2999-01")
    r = (await client.get("/api/v1/defi/regles")).json()
    assert (r["essai"], r["premier_mois"]) == (True, "2999-01")
    assert (await client.get("/api/v1/defi/classement")).json()["essai"] is True
    monkeypatch.setattr(defi, "PREMIER_MOIS", "2000-01")
    assert (await client.get("/api/v1/defi/regles")).json()["essai"] is False
