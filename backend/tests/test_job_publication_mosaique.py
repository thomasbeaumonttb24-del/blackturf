"""La tuile hebdomadaire part toute seule le dimanche — une fois, et une seule.

C'est la publication la moins rattrapable du projet : six tuiles forment une image sur
la grille du profil, et une tuile publiée ne se déplace pas. Trois défauts possibles,
tous définitifs :

  - PUBLIER DEUX FOIS LA MÊME SEMAINE. Le job repasse toutes les demi-heures le
    dimanche matin ; sa mémoire est en base (`publications_sociales`, unicité
    jour × canal) et pas en RAM, sinon un redéploiement dominical republierait.
  - PUBLIER AVANT QUE LE SAMEDI SOIT RÉGLÉ. Les rapports Multi sortent en différé et
    le rattrapage nocturne règle encore au petit matin : le total de la semaine serait
    faux, écrit sous une image qui reste six semaines en tête du profil.
  - SE TROMPER DE SEMAINE. Le `jour` porté par la ligne est le SAMEDI de fin de
    semaine, jamais le dimanche de publication.

La TUILE, elle, n'est pas décidée ici : elle vient de l'API. Deux calculs parallèles
finiraient par en nommer deux différentes, et la mosaïque se remplirait deux fois au
même endroit.
"""
from __future__ import annotations

from datetime import date

import pytest

from services import jobs

pytestmark = pytest.mark.asyncio

# Dimanche 6 septembre 2026 ; la semaine publiée finit le samedi 5.
DIMANCHE = date(2026, 9, 6)
SAMEDI = "2026-09-05"


class _Reponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _legende(pret: bool = True) -> dict:
    return {
        "pret": pret,
        "semaine": {"debut": "2026-08-30", "fin": SAMEDI, "periode": "du 30 août au 5 septembre"},
        "rang": 1, "total": 6, "cycle": 0, "tuile": "1-2",
        "image": f"https://blackturf.fr/visuels/mosaique/1-2?semaine={SAMEDI}",
        "legende": "Bilan de la semaine.",
    }


def _preparer(monkeypatch, db, *, samedi_complet: bool, envois: list,
              legende: dict | None = None, publie: bool = True, jour: date = DIMANCHE):
    import httpx

    appels: list[str] = []

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None, headers=None):
            appels.append(f"{url}?{params}")
            if "meilleurs-plans-jour" in url:
                return _Reponse({
                    "jour": SAMEDI,
                    "journee_complete": samedi_complet,
                    "nb_plans": 155,
                    "reste_a_venir": {"courses_a_venir": 0 if samedi_complet else 3,
                                      "courses_en_attente": 0,
                                      "plans_non_regles": 0 if samedi_complet else 9},
                })
            return _Reponse(legende if legende is not None else _legende())

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

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

    async def _publier(url, legende_txt, media_type=None):
        envois.append((url, legende_txt, media_type))
        return ig.ResultatPublication(publie, media_id="media-mosaique" if publie else None,
                                      raison=None if publie else "jeton absent")

    monkeypatch.setattr(ig, "publier_image", _publier)
    monkeypatch.setattr(ig, "publication_active", lambda: True)

    async def _quota():
        return 42

    monkeypatch.setattr(ig, "quota_restant", _quota)

    import services.temps_courses as tc
    monkeypatch.setattr(tc, "jour_courses", lambda: jour)
    return appels


async def _lignes(db):
    from sqlalchemy import text
    res = await db.execute(text(
        "SELECT jour, canal, media_id, publie_at, nb_tentatives, derniere_raison "
        "FROM publications_sociales ORDER BY jour"
    ))
    return res.mappings().all()


async def test_la_tuile_part_le_dimanche_pour_la_semaine_close_la_veille(db, monkeypatch):
    envois: list = []
    _preparer(monkeypatch, db, samedi_complet=True, envois=envois)

    await jobs.job_publication_mosaique()

    assert len(envois) == 1
    url, legende, media_type = envois[0]
    assert f"semaine={SAMEDI}" in url, (
        "sans la semaine dans l'URL, Meta irait chercher la tuile de la semaine courante"
    )
    assert media_type is None, "c'est une publication de FIL, pas une story"

    lignes = await _lignes(db)
    assert len(lignes) == 1
    assert lignes[0]["jour"] == SAMEDI, "la ligne porte le samedi de fin de semaine"
    assert lignes[0]["canal"] == jobs.CANAL_MOSAIQUE
    assert lignes[0]["publie_at"] is not None


async def test_rien_ne_part_tant_que_le_samedi_n_est_pas_regle(db, monkeypatch):
    envois: list = []
    _preparer(monkeypatch, db, samedi_complet=False, envois=envois)

    await jobs.job_publication_mosaique()

    assert envois == [], "un total de semaine incomplet est un total faux"
    assert await _lignes(db) == []


async def test_le_second_passage_de_la_matinee_ne_republie_pas(db, monkeypatch):
    """Le job repasse toutes les demi-heures : la mémoire est en base."""
    envois: list = []
    _preparer(monkeypatch, db, samedi_complet=True, envois=envois)

    await jobs.job_publication_mosaique()
    await jobs.job_publication_mosaique()
    await jobs.job_publication_mosaique()

    assert len(envois) == 1, f"une seule publication par semaine, reçu : {len(envois)}"
    assert len(await _lignes(db)) == 1


async def test_un_echec_laisse_une_trace_et_se_rejoue(db, monkeypatch):
    """Un échec sans trace se répète en silence — et personne ne saurait pourquoi."""
    envois: list = []
    _preparer(monkeypatch, db, samedi_complet=True, envois=envois, publie=False)

    await jobs.job_publication_mosaique()

    lignes = await _lignes(db)
    assert len(lignes) == 1
    assert lignes[0]["publie_at"] is None
    assert lignes[0]["derniere_raison"] == "jeton absent"

    # Passage suivant : l'échec n'interdit pas de réessayer.
    await jobs.job_publication_mosaique()
    assert len(envois) == 2
    assert (await _lignes(db))[0]["nb_tentatives"] == 2


async def test_rien_ne_part_si_la_legende_n_est_pas_prete(db, monkeypatch):
    envois: list = []
    _preparer(monkeypatch, db, samedi_complet=True, envois=envois,
              legende={"pret": False, "attente": "bilan indisponible"})

    await jobs.job_publication_mosaique()

    assert envois == []
    assert await _lignes(db) == []


async def test_un_samedi_publie_la_semaine_d_avant(db, monkeypatch):
    """Le job ne doit pas prendre le samedi du jour même : la semaine court encore."""
    envois: list = []
    _preparer(monkeypatch, db, samedi_complet=True, envois=envois,
              jour=date(2026, 9, 12))  # un samedi

    await jobs.job_publication_mosaique()

    lignes = await _lignes(db)
    assert len(lignes) == 1
    assert lignes[0]["jour"] == "2026-09-05", (
        f"la semaine close est celle du samedi précédent, reçu : {lignes[0]['jour']}"
    )


def test_le_job_est_planifie_le_dimanche_matin_et_repasse():
    """Une heure fixe le dimanche publierait un total faux une semaine sur deux : le
    rattrapage nocturne règle encore les derniers plans du samedi au petit matin."""
    from tests._descripteurs_deploiement import RACINE, exiger
    source = exiger(RACINE / "backend" / "services" / "jobs.py")
    assert 'id="publication_mosaique"' in source
    assert 'day_of_week="sun"' in source, "la tuile ne part que le dimanche"
    assert 'hour="8-13", minute="0,30"' in source, (
        "le job doit repasser toutes les demi-heures jusqu'à ce que le samedi soit réglé"
    )


def test_la_tuile_n_est_pas_choisie_par_le_job():
    """Deux calculs parallèles de la tuile finiraient par en nommer deux différentes,
    et la mosaïque se remplirait deux fois au même endroit. Le job lit `image` tel
    quel ; il ne construit jamais d'URL de tuile."""
    from tests._descripteurs_deploiement import RACINE, exiger
    source = exiger(RACINE / "backend" / "services" / "jobs.py")
    debut = source.index("async def job_publication_mosaique")
    corps = source[debut:source.index("async def job_renouveler_jetons", debut)]
    import re
    urls = re.findall(r"/visuels/mosaique/[^\"'}\s]*", corps)
    assert urls == ["/visuels/mosaique/legendes.json"], (
        "la seule URL de mosaïque que le job compose est celle de la légende ; "
        f"l'URL de la tuile doit venir de l'API. Trouvé : {urls}"
    )
    assert 'legende["image"]' in corps
