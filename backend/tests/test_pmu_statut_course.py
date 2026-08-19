"""
Le statut PMU d'une course doit être LU et remonté.

Il était purement ignoré jusqu'au 2026-08-17, alors que le payload PMU l'expose
(par course ET par réunion : PROGRAMMEE / FIN_COURSE / ARRIVEE_DEFINITIVE_COMPLETE
/ COURSE_ANNULEE). Conséquence : une course annulée — qui n'aura jamais
d'ordreArrivee — n'avait aucun moyen de quitter 'a_venir'. Cf.
services/course_resolution.py.
"""
import pytest

from scraper.sources.pmu import PmuScraper, _fmt_date_pmu


def _programme_payload(statut_c1: str):
    """Extrait minimal mais RÉEL du payload /programme/{ddmmyyyy} du PMU."""
    return {
        "programme": {
            "reunions": [{
                "numOfficiel": 3,
                "numExterne": 3,
                "statut": "ANNULEE",
                "hippodrome": {"libelleLong": "HIPPODROME DE CHATEAUBRIANT"},
                "pays": {"code": "FRA"},
                "courses": [{
                    "numOrdre": 1,
                    "libelle": "PRIX SIROL",
                    "statut": statut_c1,
                    "specialite": "PLAT",
                    "distance": 2400,
                    "heureDepart": 1782201900000,
                    "participants": [],
                    "paris": [],
                    "nombreDeclaresPartants": 7,
                }],
            }]
        }
    }


async def _courses_avec_statut(monkeypatch, statut_c1: str):
    scraper = PmuScraper()
    payload = _programme_payload(statut_c1)

    async def _fake_fetch(url, max_retries=3):
        return payload

    monkeypatch.setattr(scraper, "_fetch_json", _fake_fetch)
    return await scraper.get_programme_today(target_date="23062026")


async def test_statut_pmu_annulee_remonte_dans_course_scrape(monkeypatch):
    courses = await _courses_avec_statut(monkeypatch, "COURSE_ANNULEE")
    assert len(courses) == 1
    assert courses[0].statut_pmu == "COURSE_ANNULEE"


async def test_statut_pmu_normalise_en_majuscules(monkeypatch):
    courses = await _courses_avec_statut(monkeypatch, "course_annulee")
    assert courses[0].statut_pmu == "COURSE_ANNULEE"


async def test_statut_pmu_absent_reste_none(monkeypatch):
    scraper = PmuScraper()
    payload = _programme_payload("PROGRAMMEE")
    del payload["programme"]["reunions"][0]["courses"][0]["statut"]

    async def _fake_fetch(url, max_retries=3):
        return payload

    monkeypatch.setattr(scraper, "_fetch_json", _fake_fetch)
    courses = await scraper.get_programme_today(target_date="23062026")
    assert courses[0].statut_pmu is None


# ── get_statut_course ───────────────────────────────────────────────────────

async def test_get_statut_course_lit_l_objet_course(monkeypatch):
    scraper = PmuScraper()
    vus = []

    async def _fake_fetch(url, max_retries=3):
        vus.append(url)
        return {"statut": "COURSE_ANNULEE", "libelle": "PRIX SIROL"}

    monkeypatch.setattr(scraper, "_fetch_json", _fake_fetch)
    statut = await scraper.get_statut_course("3", 1, "23062026")

    assert statut == "COURSE_ANNULEE"
    assert "/programme/23062026/R3/C1" in vus[0]


async def test_get_statut_course_payload_imbrique(monkeypatch):
    """Certaines réponses PMU enveloppent la course dans une clé `course`."""
    scraper = PmuScraper()

    async def _fake_fetch(url, max_retries=3):
        return {"course": {"statut": "ARRIVEE_DEFINITIVE_COMPLETE"}}

    monkeypatch.setattr(scraper, "_fetch_json", _fake_fetch)
    assert await scraper.get_statut_course("1", 1, "23062026") == "ARRIVEE_DEFINITIVE_COMPLETE"


async def test_get_statut_course_204_renvoie_none(monkeypatch):
    """204 / corps vide (courses hors périmètre PMU) → None, pas d'exception."""
    scraper = PmuScraper()

    async def _fake_fetch(url, max_retries=3):
        return None

    monkeypatch.setattr(scraper, "_fetch_json", _fake_fetch)
    assert await scraper.get_statut_course("5", 1, "01062026") is None


# ── _fmt_date_pmu (factorisé depuis get_rapports_definitifs) ───────────────

def test_fmt_date_pmu_prefixe_course_id():
    assert _fmt_date_pmu("23062026") == "23062026"


def test_fmt_date_pmu_epoch_ms():
    # heureDepart PMU en ms → date locale ; on vérifie juste la forme ddmmyyyy.
    out = _fmt_date_pmu(1782201900000)
    assert len(out) == 8 and out.isdigit()


def test_fmt_date_pmu_datetime():
    from datetime import datetime
    assert _fmt_date_pmu(datetime(2026, 6, 23, 8, 5)) == "23062026"


def test_fmt_date_pmu_iso_retombe_sur_aujourdhui():
    """« Aujourd'hui » = la journée de courses PARISIENNE, pas la date UTC du
    conteneur : ce test comparait à `date.today()` et passait en local (machine
    à Paris) tout en échouant dans l'image de prod (UTC) entre minuit et 2 h."""
    from services.temps_courses import jour_courses
    assert _fmt_date_pmu("2026-06-23") == jour_courses().strftime("%d%m%Y")
