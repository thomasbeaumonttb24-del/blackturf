"""Une tuile de mosaïque qui ne part PAS doit se voir — et assez tôt pour la sauver.

Le 2026-09-13, `job_publication_mosaique` a été refusé six fois de suite entre 8 h et
10 h 30 (« création du conteneur refusée (400) » : Meta raccrochait pendant le rendu
de la tuile). Rien n'a alerté. La seule trace était une ligne `publications_sociales`
sans `publie_at`, un dimanche matin.

Deux garde-fous, testés ici :

  - LE RÉCAPITULATIF de 14 h 05, après le dernier passage (13 h 30) : si la semaine
    close n'est pas partie, un e-mail dit combien de tentatives, pourquoi, et ce que
    l'API attend encore. Pendant de `job_surveillance_story`.
  - L'ALERTE PRÉCOCE, au deuxième refus consécutif : il reste alors plusieurs passages
    pour corriger. Une seule fois — un message par demi-heure finirait dans un filtre.
"""
from __future__ import annotations

from datetime import date

import pytest

from services import jobs

pytestmark = pytest.mark.asyncio

# Dimanche 6 septembre 2026 ; la semaine surveillée finit le samedi 5.
DIMANCHE = date(2026, 9, 6)
SAMEDI = "2026-09-05"


class _Reponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _bilan_samedi(complet: bool) -> dict:
    return {
        "jour": SAMEDI,
        "journee_complete": complet,
        "nb_plans": 155,
        "reste_a_venir": {"courses_a_venir": 0, "courses_en_attente": 0,
                          "plans_non_regles": 0 if complet else 9},
    }


def _brancher(monkeypatch, db, alertes: list, *, samedi_complet: bool = True,
              api_muette: bool = False, jour: date = DIMANCHE):
    """Session de test, API simulée, e-mail factice, dimanche figé."""
    import httpx

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None, headers=None):
            if api_muette:
                raise httpx.ConnectError("api injoignable")
            if "meilleurs-plans-jour" in url:
                return _Reponse(_bilan_samedi(samedi_complet))
            return _Reponse({
                "pret": True, "tuile": "1-2", "rang": 1, "cycle": 0,
                "image": f"https://blackturf.fr/visuels/mosaique/1-2?semaine={SAMEDI}",
                "legende": "Bilan de la semaine.",
            })

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

    import services.alerts as al

    async def _envoyer(destinataire, sujet, html):
        alertes.append((destinataire, sujet, html))
        return True

    monkeypatch.setattr(al, "send_email", _envoyer)

    import services.temps_courses as tc
    monkeypatch.setattr(tc, "jour_courses", lambda: jour)


def _publication(monkeypatch, *, refus: list[str | None]):
    """`publier_image` factice : chaque appel consomme la réponse suivante de `refus`
    (None = publiée)."""
    import services.instagram as ig

    async def _publier(url, legende_txt, media_type=None):
        raison = refus.pop(0)
        if raison is None:
            return ig.ResultatPublication(True, media_id="media-mosaique")
        return ig.ResultatPublication(False, raison=raison)

    monkeypatch.setattr(ig, "publier_image", _publier)
    monkeypatch.setattr(ig, "publication_active", lambda: True)

    async def _quota():
        return 42

    monkeypatch.setattr(ig, "quota_restant", _quota)


async def _ligne_mosaique(db, *, publie: bool, tentatives: int = 6,
                          raison: str | None = "création du conteneur refusée (400)"):
    from sqlalchemy import text
    await db.execute(text(
        "INSERT INTO publications_sociales (publication_id, jour, canal, media_id, "
        "publie_at, derniere_tentative_at, nb_tentatives, derniere_raison) "
        "VALUES ('m-1', :j, :c, :m, :p, :p2, :n, :r)"
    ), {"j": SAMEDI, "c": jobs.CANAL_MOSAIQUE,
        "m": "media-mosaique" if publie else None,
        "p": "2026-09-06 06:00:00+00" if publie else None,
        "p2": "2026-09-06 08:30:00+00",
        "n": tentatives,
        "r": None if publie else raison})
    await db.commit()


# ── Récapitulatif de 14 h 05 ────────────────────────────────────────────────


async def test_la_surveillance_alerte_sur_une_tuile_refusee(db, monkeypatch):
    """Le cas du 2026-09-13 : une ligne, six tentatives, aucune `publie_at`."""
    alertes: list = []
    _brancher(monkeypatch, db, alertes)
    await _ligne_mosaique(db, publie=False, tentatives=6)

    await jobs.job_surveillance_mosaique()

    assert len(alertes) == 1, "une tuile manquante doit produire un message, pas rien"
    _, sujet, html = alertes[0]
    assert SAMEDI in sujet and "NON publiée" in sujet
    assert "création du conteneur refusée (400)" in html, "l'alerte doit dire POURQUOI"
    assert "<code>6</code>" in html, "et combien de fois l'envoi a été tenté"
    assert "plans_non_regles" in html, "et ce que l'API attendait encore"


async def test_la_surveillance_se_tait_quand_la_tuile_est_partie(db, monkeypatch):
    alertes: list = []
    _brancher(monkeypatch, db, alertes)
    await _ligne_mosaique(db, publie=True)

    await jobs.job_surveillance_mosaique()

    assert alertes == [], "une alerte hebdomadaire inutile finit dans un filtre"


async def test_la_surveillance_alerte_sans_ligne_quand_le_samedi_est_regle(db, monkeypatch):
    """Aucune tentative alors que le samedi est réglé : le job n'est jamais allé jusqu'à
    Meta (légende pas prête, scheduler arrêté…). C'est une tuile absente."""
    alertes: list = []
    _brancher(monkeypatch, db, alertes, samedi_complet=True)

    await jobs.job_surveillance_mosaique()

    assert len(alertes) == 1
    assert "Aucune tentative" in alertes[0][2]


async def test_la_surveillance_ne_double_pas_l_alerte_d_un_samedi_jamais_regle(
        db, monkeypatch):
    """Samedi jamais réglé : la story du samedi n'est pas partie non plus et
    `job_surveillance_story` l'a signalé à 10 h 05. Deux messages pour une cause
    unique apprennent à ignorer le second."""
    alertes: list = []
    _brancher(monkeypatch, db, alertes, samedi_complet=False)

    await jobs.job_surveillance_mosaique()

    assert alertes == []


async def test_la_surveillance_alerte_quand_l_api_ne_repond_pas(db, monkeypatch):
    """On ne sait pas si le samedi est réglé : dans le doute, on prévient."""
    alertes: list = []
    _brancher(monkeypatch, db, alertes, api_muette=True)

    await jobs.job_surveillance_mosaique()

    assert len(alertes) == 1


async def test_la_surveillance_vise_la_meme_semaine_que_la_publication(db, monkeypatch):
    """Un samedi, la semaine close est celle d'avant : la surveillance et la
    publication partagent le même calcul, sinon l'une regarderait une autre ligne."""
    alertes: list = []
    _brancher(monkeypatch, db, alertes, jour=date(2026, 9, 12))  # un samedi
    await _ligne_mosaique(db, publie=True)  # ligne du 05

    await jobs.job_surveillance_mosaique()

    assert alertes == []


def test_la_surveillance_ne_publie_rien_elle_meme():
    """Elle alerte, elle ne rattrape pas : une tuile publiée ne se déplace plus sur la
    grille, republier hors fenêtre est une décision de l'exploitant."""
    from tests._descripteurs_deploiement import RACINE, exiger
    source = exiger(RACINE / "backend" / "services" / "jobs.py")
    debut = source.index("async def job_surveillance_mosaique")
    fin = source.index("\nasync def ", debut + 1)
    corps = source[debut:fin]
    assert "publier_image" not in corps and "publier_story" not in corps


def test_la_surveillance_est_planifiee_apres_le_dernier_passage():
    """`hour="8-13", minute="0,30"` tire encore à 13 h 30 : surveiller avant,
    c'est alerter sur une tuile qui peut encore partir."""
    from tests._descripteurs_deploiement import RACINE, exiger
    source = exiger(RACINE / "backend" / "services" / "jobs.py")
    assert 'id="surveillance_mosaique"' in source
    assert 'hour="8-13", minute="0,30"' in source, (
        "si la fenêtre de publication change, l'heure de surveillance doit suivre"
    )
    assert ('CronTrigger(day_of_week="sun", hour=14, minute=5, timezone="Europe/Paris")'
            in source)


# ── Alerte précoce : deuxième refus consécutif ──────────────────────────────


async def test_premier_refus_pas_d_alerte_deuxieme_refus_alerte(db, monkeypatch):
    alertes: list = []
    _brancher(monkeypatch, db, alertes)
    _publication(monkeypatch, refus=["création du conteneur refusée (400)",
                                     "création du conteneur refusée (400)"])

    await jobs.job_publication_mosaique()
    assert alertes == [], "un refus isolé de Meta se rattrape souvent au passage suivant"

    await jobs.job_publication_mosaique()
    assert len(alertes) == 1, "au deuxième refus, il reste le temps de corriger"
    _, sujet, html = alertes[0]
    assert SAMEDI in sujet and "2 fois" in sujet
    assert "création du conteneur refusée (400)" in html


async def test_l_alerte_precoce_ne_part_qu_une_fois(db, monkeypatch):
    """Six refus le 13/09 : un message par demi-heure jusqu'à 13 h 30 aurait appris à
    les ignorer. Le récapitulatif de 14 h 05 prend le relais."""
    alertes: list = []
    _brancher(monkeypatch, db, alertes)
    _publication(monkeypatch, refus=["refus"] * 5)

    for _ in range(5):
        await jobs.job_publication_mosaique()

    assert len(alertes) == 1


async def test_pas_d_alerte_precoce_si_le_deuxieme_passage_publie(db, monkeypatch):
    alertes: list = []
    _brancher(monkeypatch, db, alertes)
    _publication(monkeypatch, refus=["création du conteneur refusée (400)", None])

    await jobs.job_publication_mosaique()
    await jobs.job_publication_mosaique()

    assert alertes == []


async def test_pas_d_alerte_precoce_sur_une_raison_vide(db, monkeypatch):
    """Sans raison, l'alerte ne dirait rien d'exploitable : le récapitulatif suffit."""
    alertes: list = []
    _brancher(monkeypatch, db, alertes)
    _publication(monkeypatch, refus=["", ""])

    await jobs.job_publication_mosaique()
    await jobs.job_publication_mosaique()

    assert alertes == []


async def test_les_attentes_n_ecrivent_rien_et_n_alertent_pas(db, monkeypatch):
    """Samedi pas encore réglé à 8 h, 8 h 30… : ce n'est pas un refus, et le compteur
    d'échecs ne doit pas avancer."""
    alertes: list = []
    _brancher(monkeypatch, db, alertes, samedi_complet=False)
    _publication(monkeypatch, refus=[])

    for _ in range(3):
        await jobs.job_publication_mosaique()

    assert alertes == []
