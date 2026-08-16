"""Tests du job hebdomadaire « meilleur value bet de la semaine » (funnel Free,
décision produit 2026-08-16, Thomas).

Couvre la sélection (EV le plus haut parmi les value bets ★★★+ RÉELLEMENT
gagnants, avec rapport PMU publié — jamais de gain inventé) et l'envoi
(Free/Découverte seulement, rien envoyé si aucun candidat honnête).
"""
import uuid
import pytest
from datetime import datetime, timedelta, timezone, date
from unittest.mock import AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Hippodrome, Reunion, Course, Cheval, Participation,
    Prediction, ValueBet, Resultat, User,
)
from services.alerts import _best_value_bet_last_week, send_weekly_best_value_bet
from api.routes.auth import _hash

pytestmark = pytest.mark.asyncio

NOW = datetime.now(timezone.utc)


async def _seed_value_bet(
    db: AsyncSession,
    course_id: str,
    *,
    niveau: int = 3,
    ev: float = 0.15,
    numero_gagnant: int = 1,  # numéro qui gagne réellement la course
    numero_vb: int = 1,       # numéro sur lequel porte le value bet
    days_ago: float = 2,
    detecte_avant_depart: bool = True,
    rapport_sg: float | None = 5.0,
    statut: str = "termine",
) -> None:
    hippo_id = f"h-{course_id}"
    hippo_nom = f"Test Hippo {course_id}"
    db.add(Hippodrome(hippodrome_id=hippo_id, nom=hippo_nom, code=course_id[:3]))
    db.add(Reunion(reunion_id=f"R-{course_id}", date=date.today(), hippodrome_id=hippo_id,
                    hippodrome_nom=hippo_nom, numero=1))
    date_heure = NOW - timedelta(days=days_ago)
    db.add(Course(
        course_id=course_id, reunion_id=f"R-{course_id}", numero=1, nom="Prix Test",
        date_heure=date_heure, hippodrome_nom=hippo_nom, discipline="Plat",
        distance=1800, nb_partants=8, statut=statut,
    ))
    cheval = Cheval(cheval_id=f"cheval-{course_id}", nom=f"Cheval {course_id}", age=4, sexe="H")
    db.add(cheval)
    part = Participation(
        participation_id=f"part-{course_id}", course_id=course_id, cheval_id=cheval.cheval_id,
        numero=numero_vb, cote_pmu=6.0, non_partant=False,
    )
    db.add(part)
    pred = Prediction(
        prediction_id=f"pred-{course_id}", participation_id=part.participation_id,
        course_id=course_id, proba_top1=0.3, proba_top3=0.6, rang_predit=1, cote_figee=6.0,
    )
    db.add(pred)
    detecte_a = date_heure - timedelta(minutes=30) if detecte_avant_depart else date_heure + timedelta(minutes=5)
    vb = ValueBet(
        vb_id=f"vb-{course_id}", prediction_id=pred.prediction_id, course_id=course_id,
        participation_id=part.participation_id, ev_max=ev, meilleure_source="pmu",
        niveau=niveau, actif=True, detecte_a=detecte_a,
    )
    db.add(vb)
    classement = [{"numero": numero_gagnant, "position": 1}]
    if numero_gagnant != numero_vb:
        classement.append({"numero": numero_vb, "position": 3})
    rapports = {"simple_gagnant": rapport_sg} if rapport_sg is not None else None
    db.add(Resultat(course_id=course_id, classement=classement, rapports=rapports))
    await db.commit()


async def _make_user(db: AsyncSession, plan: str, *, push: bool = False) -> User:
    u = User(
        user_id=str(uuid.uuid4()),
        email=f"{plan}_{uuid.uuid4().hex[:6]}@blackturf.fr",
        hashed_password=_hash("Passw0rd!"),
        plan=plan,
        is_active=True,
        push_subscription={"endpoint": "https://push.test/x"} if push else None,
    )
    db.add(u)
    await db.commit()
    return u


# ─────────────────────────────────────────────
# Sélection du meilleur value bet
# ─────────────────────────────────────────────
async def test_selectionne_le_plus_haut_ev_parmi_les_gagnants(db: AsyncSession):
    await _seed_value_bet(db, "V1", ev=0.10, rapport_sg=4.0)
    await _seed_value_bet(db, "V2", ev=0.35, rapport_sg=8.0)
    best = await _best_value_bet_last_week(db)
    assert best is not None
    assert best["course_id"] == "V2"
    assert best["ev"] == 0.35
    assert best["gain_reference_10e"] == 80.0  # 10 × rapport 8.0


async def test_ignore_les_value_bets_perdants(db: AsyncSession):
    """Un value bet dont le cheval N'A PAS gagné n'est jamais candidat, même à EV élevé."""
    await _seed_value_bet(db, "V3", ev=0.50, numero_gagnant=2, numero_vb=1, rapport_sg=9.0)
    best = await _best_value_bet_last_week(db)
    assert best is None


async def test_ignore_si_rapport_pmu_non_publie(db: AsyncSession):
    """Gagnant mais rapport PMU pas encore publié → jamais de gain approximé, candidat exclu."""
    await _seed_value_bet(db, "V4", ev=0.40, rapport_sg=None)
    best = await _best_value_bet_last_week(db)
    assert best is None


async def test_ignore_les_courses_de_plus_de_7_jours(db: AsyncSession):
    await _seed_value_bet(db, "V5", ev=0.40, days_ago=10, rapport_sg=6.0)
    best = await _best_value_bet_last_week(db)
    assert best is None


async def test_ignore_niveau_insuffisant(db: AsyncSession):
    await _seed_value_bet(db, "V6", ev=0.40, niveau=2, rapport_sg=6.0)
    best = await _best_value_bet_last_week(db)
    assert best is None


async def test_garde_anti_backfill_value_bet_detecte_apres_le_depart(db: AsyncSession):
    """Value bet détecté APRÈS le départ = reconstruit a posteriori sur un résultat
    déjà connu (in-sample) → exclu, même principe que le backtest ROI (stats.py)."""
    await _seed_value_bet(db, "V7", ev=0.40, detecte_avant_depart=False, rapport_sg=6.0)
    best = await _best_value_bet_last_week(db)
    assert best is None


# ─────────────────────────────────────────────
# Envoi (email + push, ciblage Free/Découverte)
# ─────────────────────────────────────────────
async def test_aucun_candidat_ne_rien_envoyer(db: AsyncSession, monkeypatch):
    """Honnêteté avant tout : si aucun value bet ★★★+ n'a gagné la semaine, on
    n'invente pas d'exemple — le job ne fait rien."""
    mock_email = AsyncMock(return_value=True)
    monkeypatch.setattr("services.alerts.send_email", mock_email)
    await _make_user(db, "free")

    await send_weekly_best_value_bet(db)

    mock_email.assert_not_called()


async def test_envoie_uniquement_aux_comptes_free_et_decouverte(db: AsyncSession, monkeypatch):
    await _seed_value_bet(db, "V8", ev=0.30, rapport_sg=5.0)
    mock_email = AsyncMock(return_value=True)
    monkeypatch.setattr("services.alerts.send_email", mock_email)

    free_user = await _make_user(db, "free")
    decouverte_user = await _make_user(db, "decouverte")
    standard_user = await _make_user(db, "standard")
    expert_user = await _make_user(db, "expert")

    await send_weekly_best_value_bet(db)

    sent_to = {call.kwargs["to"] for call in mock_email.await_args_list}
    assert free_user.email in sent_to
    assert decouverte_user.email in sent_to
    assert standard_user.email not in sent_to
    assert expert_user.email not in sent_to


async def test_envoie_le_push_si_utilisateur_abonne(db: AsyncSession, monkeypatch):
    await _seed_value_bet(db, "V9", ev=0.30, rapport_sg=5.0)
    monkeypatch.setattr("services.alerts.send_email", AsyncMock(return_value=True))
    mock_push = AsyncMock(return_value=True)
    monkeypatch.setattr("services.alerts.send_web_push", mock_push)

    await _make_user(db, "free", push=True)
    await _make_user(db, "free", push=False)

    await send_weekly_best_value_bet(db)

    assert mock_push.await_count == 1  # seulement l'utilisateur avec push_subscription


# ─────────────────────────────────────────────
# Wrapper de job planifié (services/jobs.py)
# ─────────────────────────────────────────────
async def test_job_weekly_best_value_bet_ne_leve_jamais(monkeypatch):
    """Comportement standard des jobs planifiés de ce projet (cf. test_jobs_drift_check.py) :
    une erreur inattendue ne doit jamais faire tomber APScheduler."""
    from contextlib import asynccontextmanager
    import db.database as dbmod
    from services import jobs

    @asynccontextmanager
    async def _boom_session():
        raise ConnectionError("db down")
        yield  # pragma: no cover — rend la fonction générateur, jamais atteint

    monkeypatch.setattr(dbmod, "AsyncSessionLocal", _boom_session)

    await jobs.job_weekly_best_value_bet()  # ne doit pas lever


async def test_job_weekly_best_value_bet_appelle_send_weekly(monkeypatch):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    import db.database as dbmod
    from services import jobs

    @asynccontextmanager
    async def _fake_session():
        yield SimpleNamespace()

    monkeypatch.setattr(dbmod, "AsyncSessionLocal", _fake_session)
    mock_send = AsyncMock()
    monkeypatch.setattr("services.alerts.send_weekly_best_value_bet", mock_send)

    await jobs.job_weekly_best_value_bet()

    mock_send.assert_awaited_once()


async def test_weekly_best_value_bet_est_enregistre_dans_le_scheduler():
    """Le job doit être ajouté au scheduler avec le bon déclencheur (lundi 09:00
    Paris) — vérifié sans jamais démarrer le scheduler (pas d'effet de bord
    partagé entre tests)."""
    from unittest.mock import MagicMock
    from services import jobs

    fake_scheduler = MagicMock()
    fake_scheduler.get_jobs.return_value = []
    orig_get_scheduler = jobs.get_scheduler
    jobs.get_scheduler = lambda: fake_scheduler
    try:
        jobs.start_scheduler()
    finally:
        jobs.get_scheduler = orig_get_scheduler

    job_ids = [c.kwargs.get("id") for c in fake_scheduler.add_job.call_args_list]
    assert "weekly_best_value_bet" in job_ids
    weekly_call = next(c for c in fake_scheduler.add_job.call_args_list if c.kwargs.get("id") == "weekly_best_value_bet")
    assert weekly_call.args[0] is jobs.job_weekly_best_value_bet
