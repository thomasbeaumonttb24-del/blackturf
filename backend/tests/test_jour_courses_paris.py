"""La journée de courses est celle de PARIS, jamais celle du conteneur (UTC).

Bug d'origine (2026-08-20, 00 h 11 heure de Paris) : la base ne contenait
aucune course du jour et le programme affichait « Aucune course programmée ».
Le scraper demandait au PMU le programme de la VEILLE parce que son
`date.today()`, en UTC, était encore au 19. Sur les sept jours précédents, la
première insertion d'une journée tombait systématiquement à 00 h 0x UTC, soit
02 h 0x à Paris : deux heures de site vide chaque nuit.

Ces tests sont volontairement écrits sur les MINUTES qui encadrent la bascule :
c'est la seule fenêtre où le bug existait, donc la seule qui prouve la
correction.
"""
from datetime import date, datetime, timezone

import pytest

from scraper.db_writer import _jour_de_la_course
from scraper.sources.pmu import _fmt_date_pmu
from services.temps_courses import jour_courses


class _Course:
    """Double minimal : seul `course_id` est lu par `_jour_de_la_course`."""

    def __init__(self, course_id):
        self.course_id = course_id


def test_apres_minuit_a_paris_la_journee_a_change_meme_si_utc_est_encore_hier():
    # 22 h 11 UTC = 00 h 11 à Paris (heure d'été) → on est DÉJÀ le 20.
    assert jour_courses(datetime(2026, 8, 19, 22, 11, tzinfo=timezone.utc)) == date(2026, 8, 20)


def test_avant_minuit_a_paris_la_journee_n_a_pas_change():
    # 21 h 59 UTC = 23 h 59 à Paris → toujours le 19.
    assert jour_courses(datetime(2026, 8, 19, 21, 59, tzinfo=timezone.utc)) == date(2026, 8, 19)


def test_l_heure_d_hiver_decale_d_une_heure_pas_de_deux():
    # 23 h 30 UTC en janvier = 00 h 30 à Paris (UTC+1) → le 16.
    assert jour_courses(datetime(2026, 1, 15, 23, 30, tzinfo=timezone.utc)) == date(2026, 1, 16)
    # 22 h 30 UTC en janvier = 23 h 30 à Paris → encore le 15.
    assert jour_courses(datetime(2026, 1, 15, 22, 30, tzinfo=timezone.utc)) == date(2026, 1, 15)


def test_un_datetime_naif_est_lu_comme_de_l_utc_pas_comme_de_l_heure_locale():
    """Le code appelant peut passer une horloge naïve ; on ne devine pas un
    fuseau local, on suppose UTC — c'est ce que sont toutes nos horloges serveur."""
    assert jour_courses(datetime(2026, 8, 19, 22, 11)) == date(2026, 8, 20)


def test_l_url_pmu_du_jour_suit_la_journee_parisienne(monkeypatch):
    """`_fmt_date_pmu(None)` bâtit l'URL `/programme/ddmmyyyy` : c'est elle qui
    décidait, chaque nuit, d'aller chercher la veille."""
    monkeypatch.setattr("scraper.sources.pmu.jour_courses", lambda: date(2026, 8, 20))
    assert _fmt_date_pmu(None) == "20082026"


def test_la_date_de_reunion_vient_du_course_id_pas_de_l_horloge():
    """Le backfill réécrit des journées passées : dater la réunion avec
    `date.today()` collait la date du jour à une réunion d'il y a trois mois."""
    assert _jour_de_la_course(_Course("19082026R2C3")) == date(2026, 8, 19)
    assert _jour_de_la_course(_Course("01052026R1C1")) == date(2026, 5, 1)


def test_un_course_id_sans_prefixe_date_retombe_sur_la_journee_parisienne(monkeypatch):
    monkeypatch.setattr("scraper.db_writer.jour_courses", lambda: date(2026, 8, 20))
    assert _jour_de_la_course(_Course("R2C3")) == date(2026, 8, 20)


def test_un_prefixe_numerique_mais_impossible_ne_fabrique_pas_de_date_absurde(monkeypatch):
    """8 chiffres ne font pas une date : `99999999` doit retomber sur le jour
    courant, pas lever ni inventer une réunion en l'an 9999."""
    monkeypatch.setattr("scraper.db_writer.jour_courses", lambda: date(2026, 8, 20))
    assert _jour_de_la_course(_Course("99999999R1C1")) == date(2026, 8, 20)


# ── Cache du programme : le vide ne se garde pas une heure ───────────────────


@pytest.mark.asyncio
async def test_une_journee_vide_n_est_pas_mise_en_cache_une_heure(client, monkeypatch):
    """Le 2026-08-20, le programme du jour était en base (37 courses) mais l'API
    répondait 0 : une requête faite quelques minutes plus tôt, alors que la
    journée n'était pas encore importée, avait figé le vide pour 3600 s."""
    poses: dict[str, int] = {}

    class _RedisFactice:
        async def get(self, *_a, **_k):
            return None

        async def setex(self, cle, ttl, _valeur):
            poses[cle] = ttl

    async def _get_redis():
        return _RedisFactice()

    monkeypatch.setattr("api.routes.courses.get_redis", _get_redis)

    resp = await client.get("/api/v1/programme?jour=2020-01-01")
    assert resp.status_code == 200
    assert resp.json()["nb_courses"] == 0
    assert poses == {"programme:2020-01-01": 60}, (
        "une journée vide, même très ancienne, doit rester en cache 60 s : "
        f"TTL posés = {poses}")
