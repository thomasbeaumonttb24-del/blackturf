"""Pronostic gratuit par e-mail (popup fiche course) — quota et fiabilité.

Invariants produit : UN seul envoi gratuit par adresse et par jour calendaire de
Paris, toutes courses confondues ; jamais « envoyé » annoncé pour un e-mail qui
n'est pas parti ; et un quota qui répond par un message, jamais par une erreur 500.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from api.routes import pronostic_email as pe
from db.models import Course, Hippodrome, PronosticEmailEnvoi, Reunion

pytestmark = pytest.mark.asyncio

_CHEVAUX = [{"numero": 1, "nom": "TEST", "rang": 1}]


async def _course(db, course_id: str) -> None:
    hippo = Hippodrome(hippodrome_id=str(uuid.uuid4()), nom=f"Hippodrome {course_id}",
                       code=uuid.uuid4().hex[:4])
    db.add(hippo)
    db.add(Reunion(reunion_id=f"R-{course_id}", date=date.today(),
                   hippodrome_id=hippo.hippodrome_id, hippodrome_nom="Vincennes Test",
                   numero=1))
    db.add(Course(course_id=course_id, reunion_id=f"R-{course_id}", numero=1,
                  nom="Prix Test", date_heure=datetime.now(timezone.utc) + timedelta(hours=2),
                  hippodrome_nom="Vincennes Test", discipline="Attelé", distance=2700,
                  nb_partants=8, statut="a_venir"))
    await db.commit()


def _patches(envoi_ok=True):
    return (
        patch.object(pe, "_classement_complet", AsyncMock(return_value=_CHEVAUX)),
        patch.object(pe, "_mail_html", return_value="<p>x</p>"),
        patch.object(pe, "_mail_texte", return_value="x"),
        patch.object(pe, "send_email", AsyncMock(return_value=envoi_ok)),
    )


async def _demander(client, course_id, email="visiteur@exemple.fr"):
    return await client.post(f"/api/v1/courses/{course_id}/envoyer-pronostic",
                             json={"email": email, "source": "fiche_course_popup"})


async def test_un_seul_envoi_par_jour_toutes_courses_confondues(client, db):
    await _course(db, "C-QUOTA-A")
    await _course(db, "C-QUOTA-B")
    p1, p2, p3, p4 = _patches()
    with p1, p2, p3, p4 as envoi:
        r1 = await _demander(client, "C-QUOTA-A")
        r2 = await _demander(client, "C-QUOTA-B")
    assert r1.status_code == 200 and r1.json()["ok"] is True
    assert r2.status_code == 200 and r2.json()["ok"] is False
    assert "revenez demain" in r2.json()["message"]
    assert envoi.await_count == 1


async def test_deux_envois_deja_presents_le_meme_jour_ne_font_pas_d_erreur_500(client, db):
    await _course(db, "C-DOUBLE-A")
    await _course(db, "C-DOUBLE-B")
    await _course(db, "C-DOUBLE-C")
    maintenant = datetime.now(timezone.utc)
    for cid in ("C-DOUBLE-A", "C-DOUBLE-B"):
        db.add(PronosticEmailEnvoi(email="visiteur@exemple.fr", course_id=cid,
                                   token_desinscription=uuid.uuid4().hex,
                                   envoye_at=maintenant))
    await db.commit()
    p1, p2, p3, p4 = _patches()
    with p1, p2, p3, p4 as envoi:
        r = await _demander(client, "C-DOUBLE-C")
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert envoi.await_count == 0


async def test_un_envoi_echoue_n_est_pas_annonce_et_se_reessaie(client, db):
    await _course(db, "C-ECHEC")
    p1, p2, p3, p4 = _patches(envoi_ok=False)
    with p1, p2, p3, p4:
        r1 = await _demander(client, "C-ECHEC")
    assert r1.status_code == 503

    ligne = (await db.execute(select(PronosticEmailEnvoi).where(
        PronosticEmailEnvoi.course_id == "C-ECHEC"))).scalars().one()
    assert ligne.envoye_at is None

    # L'échec ne consomme pas le quota : le nouvel essai part vraiment.
    p1, p2, p3, p4 = _patches(envoi_ok=True)
    with p1, p2, p3, p4 as envoi:
        r2 = await _demander(client, "C-ECHEC")
    assert r2.json()["ok"] is True
    assert envoi.await_count == 1
    await db.refresh(ligne)
    assert ligne.envoye_at is not None


def test_le_jour_est_celui_de_paris_et_non_d_utc():
    # 23/09 22:30 UTC = 24/09 00:30 à Paris : on est déjà le 24 pour le visiteur.
    debut = pe._debut_jour_paris(datetime(2026, 9, 23, 22, 30, tzinfo=timezone.utc))
    assert debut == datetime(2026, 9, 23, 22, 0, tzinfo=timezone.utc)
    # 23/09 21:30 UTC = 23/09 23:30 à Paris : encore le 23.
    debut = pe._debut_jour_paris(datetime(2026, 9, 23, 21, 30, tzinfo=timezone.utc))
    assert debut == datetime(2026, 9, 22, 22, 0, tzinfo=timezone.utc)
