"""La story de bilan se publie toute seule — une fois, et pas avant la fin du jour.

Deux défauts possibles, et les deux sont publics et irréversibles :

  - PUBLIER TROP TÔT. Le moment où une journée devient publiable n'a pas d'heure
    fixe : les dernières courses se courent jusqu'à 23 h 30, et le rattrapage nocturne
    règle encore au petit matin — le 2026-09-06, les 165 derniers plans du 5 n'ont été
    réglés qu'à 04 h 19. Le job repasse donc toutes les demi-heures, et c'est
    `journee_complete` qui décide, pas l'horloge.

  - PUBLIER DEUX FOIS. Un job qui repasse republie, sauf s'il se souvient. La mémoire
    est en base (`publications_sociales`, unicité jour × canal) et pas en RAM : un
    redéploiement à 5 h du matin ne doit pas republier la story du jour.
"""
from __future__ import annotations

from datetime import date

import pytest

from services import jobs

pytestmark = pytest.mark.asyncio

JOUR = date(2026, 9, 5)


class _Reponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _bilan(complete: bool, nb_plans: int = 198) -> dict:
    return {
        "jour": JOUR.isoformat(),
        "journee_complete": complete,
        "nb_plans": nb_plans,
        "reste_a_venir": {"courses_a_venir": 0 if complete else 12,
                          "courses_en_attente": 0, "plans_non_regles": 0 if complete else 40},
    }


def _preparer(monkeypatch, db, *, bilan: dict, envois: list, publie=True, media_id="media-1"):
    """Branche le job sur la session de test, une API simulée et un envoi factice."""
    import httpx

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None, headers=None):
            return _Reponse(bilan)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    # `AsyncSessionLocal` est importé DANS le job : on le remplace à la source.
    import db.database as _dbmod

    class _Session:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return db

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(_dbmod, "AsyncSessionLocal", _Session)

    import services.instagram as ig

    async def _publier(url):
        envois.append(url)
        return ig.ResultatPublication(publie, media_id=media_id if publie else None,
                                      raison=None if publie else "jeton absent")

    monkeypatch.setattr(ig, "publier_story", _publier)
    monkeypatch.setattr(ig, "publication_active", lambda: True)

    async def _quota():
        return 42

    monkeypatch.setattr(ig, "quota_restant", _quota)

    import services.temps_courses as tc
    monkeypatch.setattr(tc, "jour_courses", lambda: JOUR)


async def _lignes(db):
    from sqlalchemy import text
    res = await db.execute(text(
        "SELECT jour, canal, media_id, publie_at, nb_tentatives, derniere_raison "
        "FROM publications_sociales ORDER BY jour"
    ))
    return res.mappings().all()


async def test_rien_ne_part_tant_que_la_journee_n_est_pas_finie(db, monkeypatch):
    envois: list[str] = []
    _preparer(monkeypatch, db, bilan=_bilan(complete=False), envois=envois)

    await jobs.job_publication_story()

    assert envois == [], "une journée en cours ne se publie pas"
    assert await _lignes(db) == []


async def test_rien_ne_part_sur_une_journee_sans_aucun_plan(db, monkeypatch):
    """Journée « complète » mais vide : publier « 0 € rendu » dirait le contraire de
    ce que le visuel veut dire."""
    envois: list[str] = []
    _preparer(monkeypatch, db, bilan=_bilan(complete=True, nb_plans=0), envois=envois)

    await jobs.job_publication_story()

    assert envois == []


async def test_la_story_part_une_fois_la_journee_finie(db, monkeypatch):
    envois: list[str] = []
    _preparer(monkeypatch, db, bilan=_bilan(complete=True), envois=envois)

    await jobs.job_publication_story()

    assert len(envois) == 1
    # L'URL porte le JOUR : sans lui, Meta irait chercher le visuel du jour courant,
    # et publierait une story qui ne parle pas de la journée annoncée.
    # Et le nombre de plans VALIDÉ : le visuel refuse de se rendre s'il lit autre chose
    # (incident du 2026-09-11, story partie à « 0 € » depuis une réponse en cache).
    assert envois[0].endswith(f"/visuels/story.jpg?jour={JOUR.isoformat()}&plans=198")
    [ligne] = await _lignes(db)
    assert ligne["jour"] == JOUR.isoformat()
    assert ligne["media_id"] == "media-1"
    assert ligne["publie_at"] is not None


async def test_le_passage_suivant_ne_republie_pas(db, monkeypatch):
    """Le job repasse toutes les demi-heures : sans mémoire, il republierait à chaque
    fois. C'est le défaut le plus coûteux du lot — une story en double sur un compte
    de marque, toutes les trente minutes jusqu'au matin."""
    envois: list[str] = []
    _preparer(monkeypatch, db, bilan=_bilan(complete=True), envois=envois)

    await jobs.job_publication_story()
    await jobs.job_publication_story()
    await jobs.job_publication_story()

    assert len(envois) == 1, f"publiée {len(envois)} fois au lieu d'une"
    assert len(await _lignes(db)) == 1


async def test_un_echec_est_journalise_et_laisse_une_seconde_chance(db, monkeypatch):
    """Un jeton expiré à 23 h doit pouvoir publier à 23 h 30. L'échec laisse donc
    `publie_at` à NULL — mais il est ÉCRIT, sinon personne ne saurait qu'il a eu
    lieu."""
    envois: list[str] = []
    _preparer(monkeypatch, db, bilan=_bilan(complete=True), envois=envois, publie=False)

    await jobs.job_publication_story()
    [ligne] = await _lignes(db)
    assert ligne["publie_at"] is None
    assert ligne["derniere_raison"] == "jeton absent"

    # Deuxième passage : l'envoi est retenté, et cette fois il réussit.
    envois2: list[str] = []
    _preparer(monkeypatch, db, bilan=_bilan(complete=True), envois=envois2, publie=True)
    await jobs.job_publication_story()

    assert len(envois2) == 1, "un échec ne doit pas condamner la journée"
    [ligne] = await _lignes(db)
    assert ligne["publie_at"] is not None
    assert ligne["nb_tentatives"] == 2


async def test_le_job_est_planifie_sur_la_nuit_et_pas_a_une_heure_fixe():
    """Une heure fixe ne peut pas convenir : la journée devient publiable entre 23 h
    et le petit matin selon les rapports en retard."""
    from tests._descripteurs_deploiement import RACINE, exiger
    source = exiger(RACINE / "backend" / "services" / "jobs.py")
    assert 'id="publication_story"' in source
    assert 'CronTrigger(hour="22,23,0-9", minute="0,30"' in source, (
        "le job doit repasser toutes les demi-heures sur la nuit"
    )


def test_l_unicite_est_portee_par_la_base():
    """La mémoire du job ne peut pas vivre dans le code : deux conteneurs, ou un
    redéploiement en pleine nuit, republieraient."""
    from tests._descripteurs_deploiement import RACINE, exiger
    migration = exiger(
        RACINE / "backend" / "db" / "migrations" / "versions" / "0046_publications_sociales.py"
    )
    assert "UNIQUE (jour, canal)" in migration


async def test_le_job_ne_revient_jamais_publier_un_jour_plus_ancien(db, monkeypatch):
    """Défaut trouvé par le test d'idempotence, pas en production : après avoir publié
    le jour J, le passage suivant sautait J (déjà publié) et publiait J−1. Une story
    d'avant-hier surgissait à 5 h du matin."""
    envois: list[str] = []
    _preparer(monkeypatch, db, bilan=_bilan(complete=True), envois=envois)

    await jobs.job_publication_story()   # publie le 05
    await jobs.job_publication_story()   # ne doit RIEN publier, surtout pas le 04

    assert envois == [f"https://blackturf.fr/visuels/story.jpg?jour={JOUR.isoformat()}"]
    jours = [l["jour"] for l in await _lignes(db)]
    assert jours == [JOUR.isoformat()], f"jours publiés : {jours}"


# ── Surveillance : une story qui ne part PAS doit se voir ─────────────────────
#
# Le 2026-09-09, un seul plan sur 212 est resté `partial` (rapport d'un pool
# international non reconnu au règlement). `journee_complete` n'est jamais devenu
# vrai, la story n'est jamais partie — et RIEN ne l'a signalé : les passages du job
# écrivaient « pas encore » toutes les demi-heures dans un log que personne ne lit la
# nuit. L'absence de publication n'était un événement pour personne.


def _surveillance(monkeypatch, db, alertes: list):
    """Branche le job de surveillance : session de test, e-mail factice, API muette."""
    import db.database as _dbmod

    class _Session:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return db

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(_dbmod, "AsyncSessionLocal", _Session)

    import services.alerts as al

    async def _envoyer(destinataire, sujet, html):
        alertes.append((destinataire, sujet, html))
        return True

    monkeypatch.setattr(al, "send_email", _envoyer)

    import services.temps_courses as tc
    monkeypatch.setattr(tc, "jour_courses", lambda: JOUR)


async def _ligne_publication(db, jour: str, *, publie: bool):
    from sqlalchemy import text
    await db.execute(text(
        "INSERT INTO publications_sociales (publication_id, jour, canal, media_id, "
        "publie_at, derniere_tentative_at, nb_tentatives, derniere_raison) "
        "VALUES ('p-1', :j, :c, :m, :p, :p2, 1, :r)"
    ), {"j": jour, "c": jobs.CANAL_STORY,
        "m": "media-1" if publie else None,
        "p": "2026-09-05 02:30:00+00" if publie else None,
        "p2": "2026-09-05 02:30:00+00",
        "r": None if publie else "journee jamais complete"})
    await db.commit()


async def test_la_surveillance_alerte_quand_la_story_de_la_veille_n_est_pas_partie(
        db, monkeypatch):
    alertes: list = []
    _surveillance(monkeypatch, db, alertes)

    await jobs.job_surveillance_story()

    assert len(alertes) == 1, "une story manquante doit produire un message, pas rien"
    _, sujet, _ = alertes[0]
    assert "2026-09-04" in sujet and "NON publiée" in sujet


async def test_la_surveillance_se_tait_quand_la_story_est_partie(db, monkeypatch):
    alertes: list = []
    _surveillance(monkeypatch, db, alertes)
    await _ligne_publication(db, "2026-09-04", publie=True)

    await jobs.job_surveillance_story()

    assert alertes == [], "une alerte quotidienne inutile finit dans un filtre"


async def test_la_surveillance_alerte_aussi_sur_un_envoi_echoue(db, monkeypatch):
    """Une ligne existe mais `publie_at` est NULL (jeton expiré, quota…) : c'est une
    story absente d'Instagram, donc une alerte."""
    alertes: list = []
    _surveillance(monkeypatch, db, alertes)
    await _ligne_publication(db, "2026-09-04", publie=False)

    await jobs.job_surveillance_story()

    assert len(alertes) == 1
    assert "journee jamais complete" in alertes[0][2]


async def test_la_surveillance_ne_publie_rien_elle_meme(db, monkeypatch):
    """Elle alerte, elle ne rattrape pas : une story de la veille publiée en pleine
    journée ne dit plus rien de juste, et republier est une décision de l'exploitant."""
    from tests._descripteurs_deploiement import RACINE, exiger
    source = exiger(RACINE / "backend" / "services" / "jobs.py")
    debut = source.index("async def job_surveillance_story")
    fin = source.index("async def job_publication_mosaique")
    corps = source[debut:fin]
    assert "publier_story" not in corps and "publier_image" not in corps


def test_la_surveillance_est_planifiee_apres_la_fenetre_de_publication():
    from tests._descripteurs_deploiement import RACINE, exiger
    source = exiger(RACINE / "backend" / "services" / "jobs.py")
    assert 'id="surveillance_story"' in source
    assert "CronTrigger(hour=10, minute=5" in source, (
        "la surveillance doit passer APRÈS le dernier essai de publication (09:30)"
    )
