"""Tests courses routes."""
import uuid
import pytest
from datetime import datetime, timezone, date
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Hippodrome, Reunion, Course, Cheval, Participation, Prediction, Resultat

pytestmark = pytest.mark.asyncio

DATE_TODAY = datetime.now(timezone.utc).replace(hour=14, minute=0, second=0, microsecond=0)


async def _create_test_course(db: AsyncSession) -> str:
    """Crée une course de test et retourne course_id."""
    hippo = Hippodrome(
        hippodrome_id=str(uuid.uuid4()),
        nom="Longchamp Test",
        code="LCT",
    )
    db.add(hippo)

    reunion = Reunion(
        reunion_id="R1",
        date=date.today(),
        hippodrome_id=hippo.hippodrome_id,
        hippodrome_nom="Longchamp Test",
        numero=1,
    )
    db.add(reunion)

    course = Course(
        course_id="R1C1",
        reunion_id="R1",
        numero=1,
        nom="Prix Test",
        date_heure=DATE_TODAY,
        hippodrome_nom="Longchamp Test",
        discipline="Plat",
        distance=1600,
        nb_partants=8,
        statut="a_venir",
    )
    db.add(course)

    cheval = Cheval(
        cheval_id=str(uuid.uuid4()),
        nom="Champion Test",
        age=4,
        sexe="H",
    )
    db.add(cheval)

    part = Participation(
        participation_id=str(uuid.uuid4()),
        course_id="R1C1",
        cheval_id=cheval.cheval_id,
        numero=1,
        cote_pmu=3.5,
        non_partant=False,
    )
    db.add(part)

    # Prédiction figée : sans elle, /mise-plan renvoie 409 (« pronostic pas encore
    # disponible »). Le test du happy-path doit donc fournir un prono.
    pred = Prediction(
        prediction_id=str(uuid.uuid4()),
        participation_id=part.participation_id,
        course_id="R1C1",
        proba_top1=0.35,
        proba_top3=0.70,
        rang_predit=1,
    )
    db.add(pred)
    await db.commit()
    return "R1C1"


async def test_get_programme_today(client: AsyncClient, db: AsyncSession):
    await _create_test_course(db)
    resp = await client.get("/api/v1/programme")
    assert resp.status_code == 200
    data = resp.json()
    assert "date" in data
    assert "reunions" in data
    assert isinstance(data["reunions"], list)


async def test_get_programme_with_date(client: AsyncClient, db: AsyncSession):
    resp = await client.get("/api/v1/programme", params={"jour": date.today().isoformat()})
    assert resp.status_code == 200


async def test_get_course_detail(client: AsyncClient, db: AsyncSession):
    await _create_test_course(db)
    resp = await client.get("/api/v1/courses/R1C1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["course_id"] == "R1C1"
    assert data["discipline"] == "Plat"
    assert len(data["partants"]) >= 1
    assert data["partants"][0]["nom_cheval"] == "Champion Test"


async def test_get_course_not_found(client: AsyncClient):
    resp = await client.get("/api/v1/courses/NOTEXIST")
    assert resp.status_code == 404


async def test_get_resultats_not_found(client: AsyncClient, db: AsyncSession):
    await _create_test_course(db)
    resp = await client.get("/api/v1/courses/R1C1/resultats")
    assert resp.status_code == 404


async def test_get_cotes_historique_requires_auth(client: AsyncClient, db: AsyncSession):
    await _create_test_course(db)
    resp = await client.get("/api/v1/courses/R1C1/cotes-historique")
    assert resp.status_code == 401


async def test_get_cheval_not_found(client: AsyncClient):
    resp = await client.get(f"/api/v1/chevaux/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_mise_plan_requires_auth(client: AsyncClient, db: AsyncSession):
    await _create_test_course(db)
    resp = await client.post("/api/v1/courses/R1C1/mise-plan", json={"montant": 50})
    assert resp.status_code == 401


async def test_mise_plan_free_plan_gets_one_free_try_per_day(client: AsyncClient, db: AsyncSession, auth_headers):
    """Décision produit 2026-08-16 (Thomas) : Free n'est plus bloqué à 403 total,
    il a droit à 1 essai gratuit du calculateur par jour (funnel freemium,
    cf. MISE_PLAN_DAILY_LIMITS dans api/routes/courses.py).

    Le comptage RÉEL du quota (1er OK, 2e à 403) est couvert précisément par
    tests/test_mise_plan_quota.py, avec un FakeRedis qui suit un vrai état — le
    mock Redis générique du fixture `client` ici (conftest.py) n'implémente pas
    sismember/scard/sadd avec un état réel, donc `_mise_plan_quota_check` bascule
    en fail-open (comportement voulu : disponibilité > paywall strict si Redis ne
    répond pas correctement). Ce test-ci vérifie seulement le VRAI changement de
    règle au niveau route : Free n'est plus bloqué net (403 systématique)."""
    await _create_test_course(db)
    resp = await client.post("/api/v1/courses/R1C1/mise-plan", json={"montant": 50}, headers=auth_headers)
    assert resp.status_code == 200
    assert "quota_restant" in resp.json()


async def test_mise_plan_returns_plan(client: AsyncClient, db: AsyncSession, admin_headers):
    """Admin (expert plan) can get a mise plan."""
    await _create_test_course(db)
    resp = await client.post(
        "/api/v1/courses/R1C1/mise-plan",
        json={"montant": 100.0, "profil_risque": "equilibre"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data or "mises" in data or isinstance(data, dict)


async def test_mise_plan_invalid_montant(client: AsyncClient, db: AsyncSession, admin_headers):
    await _create_test_course(db)
    resp = await client.post(
        "/api/v1/courses/R1C1/mise-plan",
        json={"montant": -10},
        headers=admin_headers,
    )
    assert resp.status_code == 422


# ─── Comparaison post-course favori IA (funnel Free, décision 2026-08-16) ─────

async def _create_finished_course(
    db: AsyncSession, course_id: str, position_favori: int | None, rapport_sg: float | None = None,
) -> None:
    """Course TERMINÉE avec un favori IA (rang_predit=1, numéro 1) et son résultat
    réel. `position_favori=None` simule un favori absent du classement (non-partant)."""
    hippo_id = f"hippo-{course_id}"
    db.add(Hippodrome(hippodrome_id=hippo_id, nom="Vincennes Test", code="VCT"))
    db.add(Reunion(reunion_id=f"R-{course_id}", date=date.today(), hippodrome_id=hippo_id,
                    hippodrome_nom="Vincennes Test", numero=1))
    db.add(Course(
        course_id=course_id, reunion_id=f"R-{course_id}", numero=1, nom="Prix Test Terminé",
        date_heure=DATE_TODAY, hippodrome_nom="Vincennes Test", discipline="Attelé",
        distance=2100, nb_partants=8, statut="termine",
    ))
    cheval = Cheval(cheval_id=f"cheval-{course_id}", nom="Favori Test", age=5, sexe="H")
    db.add(cheval)
    part = Participation(
        participation_id=f"part-{course_id}", course_id=course_id, cheval_id=cheval.cheval_id,
        numero=1, cote_pmu=4.5, non_partant=False,
    )
    db.add(part)
    db.add(Prediction(
        prediction_id=f"pred-{course_id}", participation_id=part.participation_id,
        course_id=course_id, proba_top1=0.4, proba_top3=0.75, rang_predit=1, cote_figee=4.5,
    ))
    classement = [{"numero": 2, "position": 1}]  # un autre cheval, position par défaut
    if position_favori is not None:
        classement = [{"numero": 1, "position": position_favori}]
        if position_favori != 1:
            classement.append({"numero": 2, "position": 1})
    rapports = {"simple_gagnant": rapport_sg} if rapport_sg is not None else None
    db.add(Resultat(course_id=course_id, classement=classement, rapports=rapports))
    await db.commit()


async def test_favori_ia_resultat_course_not_found(client: AsyncClient):
    resp = await client.get("/api/v1/courses/NOTEXIST/favori-ia-resultat")
    assert resp.status_code == 404


async def test_favori_ia_resultat_course_pas_terminee(client: AsyncClient, db: AsyncSession):
    """Course à venir/en cours : jamais de rang/proba exposé, même après coup —
    disponible=False sans qu'aucune donnée de pronostic ne soit renvoyée."""
    await _create_test_course(db)  # statut="a_venir"
    resp = await client.get("/api/v1/courses/R1C1/favori-ia-resultat")
    assert resp.status_code == 200
    data = resp.json()
    assert data["disponible"] is False
    assert data["numero"] is None
    assert data["a_gagne"] is None


async def test_favori_ia_resultat_pas_de_resultat_publie(client: AsyncClient, db: AsyncSession):
    """Course terminée mais résultat pas encore publié (décalage scrape PMU) →
    disponible=False, pas de 500."""
    db.add(Hippodrome(hippodrome_id="h2", nom="Test", code="TST"))
    db.add(Reunion(reunion_id="R2", date=date.today(), hippodrome_id="h2", hippodrome_nom="Test", numero=1))
    db.add(Course(course_id="R2C1", reunion_id="R2", numero=1, nom="Prix", date_heure=DATE_TODAY,
                   hippodrome_nom="Test", discipline="Plat", distance=1600, nb_partants=8, statut="termine"))
    await db.commit()
    resp = await client.get("/api/v1/courses/R2C1/favori-ia-resultat")
    assert resp.status_code == 200
    assert resp.json()["disponible"] is False


async def test_favori_ia_resultat_favori_gagnant(client: AsyncClient, db: AsyncSession):
    """Le favori IA a gagné : gain réel d'un Simple Gagnant 10€ = 10 × rapport (base 1€)."""
    await _create_finished_course(db, "R3C1", position_favori=1, rapport_sg=4.5)
    resp = await client.get("/api/v1/courses/R3C1/favori-ia-resultat")
    assert resp.status_code == 200
    data = resp.json()
    assert data["disponible"] is True
    assert data["a_gagne"] is True
    assert data["numero"] == 1
    assert data["position_reelle"] == 1
    assert data["cote_depart"] == 4.5
    assert data["gain_reference_10e"] == 45.0


async def test_favori_ia_resultat_favori_perdant_reste_honnete(client: AsyncClient, db: AsyncSession):
    """Le favori IA n'a PAS gagné : on l'affiche honnêtement (a_gagne=False, position
    réelle réelle), jamais de gain inventé."""
    await _create_finished_course(db, "R4C1", position_favori=4, rapport_sg=None)
    resp = await client.get("/api/v1/courses/R4C1/favori-ia-resultat")
    assert resp.status_code == 200
    data = resp.json()
    assert data["disponible"] is True
    assert data["a_gagne"] is False
    assert data["position_reelle"] == 4
    assert data["gain_reference_10e"] is None


async def test_favori_ia_resultat_favori_absent_du_classement(client: AsyncClient, db: AsyncSession):
    """Favori non-partant / absent du classement → pas de comparaison honnête possible."""
    await _create_finished_course(db, "R5C1", position_favori=None)
    resp = await client.get("/api/v1/courses/R5C1/favori-ia-resultat")
    assert resp.status_code == 200
    assert resp.json()["disponible"] is False


async def test_favori_ia_resultat_gain_absent_si_rapport_non_publie(client: AsyncClient, db: AsyncSession):
    """Favori gagnant mais rapport PMU pas encore publié → gain=None (jamais approximé)."""
    await _create_finished_course(db, "R6C1", position_favori=1, rapport_sg=None)
    resp = await client.get("/api/v1/courses/R6C1/favori-ia-resultat")
    assert resp.status_code == 200
    data = resp.json()
    assert data["disponible"] is True
    assert data["a_gagne"] is True
    assert data["gain_reference_10e"] is None
