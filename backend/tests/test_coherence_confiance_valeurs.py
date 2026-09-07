"""Cohérence programme ↔ fiche course ↔ /value-bets.

Deux écarts constatés en prod le 2026-09-07 sur la course 07092026R5C7 :
  - confiance 84/100 sur le programme, 80/100 sur la fiche (le front faisait la
    moyenne des trois premiers, le serveur donnait celle du n°1) ;
  - paris de valeur recalculés à la cote du moment sur la fiche, lus dans la
    table du cycle sur /value-bets : un cheval pouvait être sur l'une et pas sur
    l'autre, ou pas au même niveau.

Ces tests posent les invariants : un seul chiffre de confiance, servi par le
serveur aux trois surfaces ; un seul pari de valeur par cheval, celui du cycle,
visible aux mêmes conditions partout.
"""
import uuid
from datetime import datetime, timedelta, timezone, date

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Hippodrome, Reunion, Course, Cheval, Participation, Prediction, ValueBet, User,
)

pytestmark = pytest.mark.asyncio


async def _seed(db: AsyncSession, course_id: str, *, dans: timedelta,
                confiances=(83.96, 79.25, 77.33), vb_niveau=3, vb_detecte_il_y_a=timedelta(hours=1)):
    """Une course à `dans` d'ici, 3 chevaux notés, un pari de valeur stocké sur le n°2.

    Les confiances reproduisent la course de la capture : n°1 à 83,96 (→ 84),
    moyenne des trois à 80,18 (→ 80). Si un jour les deux définitions
    redonnaient le même entier, le test ne prouverait plus rien.
    """
    hippo = Hippodrome(hippodrome_id=str(uuid.uuid4()), nom=f"Hippo {course_id}", code=uuid.uuid4().hex[:8])
    db.add(hippo)
    reunion_id = f"RE{course_id}"
    db.add(Reunion(reunion_id=reunion_id, date=date.today(), hippodrome_id=hippo.hippodrome_id,
                   hippodrome_nom=hippo.nom, numero=5))
    db.add(Course(course_id=course_id, reunion_id=reunion_id, numero=7, nom="Handicap",
                  date_heure=datetime.now(timezone.utc) + dans, hippodrome_nom=hippo.nom,
                  discipline="Plat", distance=1750, nb_partants=3, statut="a_venir"))
    pids = []
    for i, conf in enumerate(confiances, start=1):
        cheval = Cheval(cheval_id=str(uuid.uuid4()), nom=f"Cheval {i} {course_id}", age=5, sexe="H")
        db.add(cheval)
        part = Participation(participation_id=str(uuid.uuid4()), course_id=course_id,
                             cheval_id=cheval.cheval_id, numero=i, cote_pmu=4.0 + i, non_partant=False)
        db.add(part)
        await db.flush()
        pred = Prediction(prediction_id=str(uuid.uuid4()), participation_id=part.participation_id,
                          course_id=course_id, proba_top1=0.30 - 0.05 * i, proba_top3=0.6,
                          rang_predit=i, confidence_score=conf, cote_figee=4.0 + i)
        db.add(pred)
        pids.append((part.participation_id, pred.prediction_id))
    part2, pred2 = pids[1]
    db.add(ValueBet(vb_id=str(uuid.uuid4()), prediction_id=pred2, course_id=course_id,
                    participation_id=part2, ev_pmu=0.25, ev_max=0.25, meilleure_source="pmu",
                    niveau=vb_niveau, spi_detected=False, actif=True,
                    detecte_a=datetime.now(timezone.utc) - vb_detecte_il_y_a))
    await db.commit()
    return part2


async def _standard_headers(db: AsyncSession, inscrire) -> dict:
    email = f"std_{uuid.uuid4().hex[:6]}@blackturf.fr"
    headers = await inscrire(email=email, password="TestPass12!")
    await db.execute(update(User).where(User.email == email).values(plan="standard"))
    await db.commit()
    return headers


# ── Confiance ─────────────────────────────────────────────────────────────────

async def test_confiance_identique_programme_apercu_et_fiche(client: AsyncClient, db: AsyncSession, admin_headers):
    from services.temps_courses import PARIS
    dans = timedelta(hours=2)
    await _seed(db, "COH1C7", dans=dans)
    # Le jour du programme est le jour civil À PARIS de la course, pas « aujourd'hui » :
    # lancé après 22 h UTC, « dans 2 h » tombe déjà sur le lendemain parisien.
    jour = (datetime.now(timezone.utc) + dans).astimezone(PARIS).date()

    fiche = await client.get("/api/v1/courses/COH1C7/predictions", headers=admin_headers)
    assert fiche.status_code == 200, fiche.text
    assert fiche.json()["confiance"] == 84, "la fiche doit servir la confiance du n°1, pas la moyenne (80)"

    apercu = await client.get("/api/v1/courses/COH1C7/apercu")
    assert apercu.status_code == 200
    assert apercu.json()["confiance"] == 84

    programme = await client.get("/api/v1/programme/apercu", params={"jour": jour.isoformat()})
    assert programme.status_code == 200, programme.text
    assert programme.json()["courses"]["COH1C7"]["confiance"] == 84


async def test_confiance_absente_quand_le_prono_est_verrouille(client: AsyncClient, db: AsyncSession, monkeypatch, inscrire):
    # Quota dépassé → réponse verrouillée : aucun agrégat IA ne doit fuiter, la
    # confiance comme le reste.
    await _seed(db, "COH2C7", dans=timedelta(hours=2))
    import api.routes.predictions as mod

    async def _quota_epuise(user, course_id):
        return False, 0
    monkeypatch.setattr(mod, "_prono_quota_check", _quota_epuise)
    headers = await inscrire(email="quota@blackturf.fr", password="TestPass12!")
    r = await client.get("/api/v1/courses/COH2C7/predictions", headers=headers)
    assert r.status_code == 200
    assert r.json()["verrouille"] is True
    assert r.json()["confiance"] is None


# ── Paris de valeur ───────────────────────────────────────────────────────────

async def test_fiche_sert_le_pari_du_cycle_meme_si_la_cote_live_ne_le_confirme_plus(
    client: AsyncClient, db: AsyncSession, admin_headers, monkeypatch
):
    """Avant le gel (T-10), la cote live sert à l'AFFICHAGE de la cote ; le pari de
    valeur reste celui du cycle. Ici la cote live tombe à 1,5 — à ce prix aucun
    détecteur ne verrait de valeur — et le pari ★★★ à +25 % doit rester servi,
    exactement comme /value-bets le sert."""
    # 6 h et non 2 : SQLite relit `date_heure` sans fuseau et `_is_prono_fige`
    # la compare alors à l'heure LOCALE de la machine de test (UTC+2 l'été) —
    # à 2 h la course paraîtrait déjà gelée et la cote live ne serait pas lue.
    part2 = await _seed(db, "COH3C7", dans=timedelta(hours=6))

    async def _cotes_ecrasees(course_id):
        return [{"numero": 1, "cote": 1.5}, {"numero": 2, "cote": 1.5}, {"numero": 3, "cote": 1.5}]
    monkeypatch.setattr("services.pmu_cotes.fetch_live_cotes", _cotes_ecrasees)

    fiche = (await client.get("/api/v1/courses/COH3C7/predictions", headers=admin_headers)).json()
    par_pid = {p["participation_id"]: p for p in fiche["predictions"]}
    vb = par_pid[part2]["value_bet"]
    assert vb is not None
    assert vb["niveau"] == 3 and vb["ev_max"] == 0.25
    assert par_pid[part2]["cote_pmu"] == 1.5, "la cote affichée, elle, suit bien le direct"
    assert all(p["value_bet"] is None for pid, p in par_pid.items() if pid != part2)

    liste = (await client.get("/api/v1/value-bets", headers=admin_headers)).json()
    ceux_de_la_course = [v for v in liste if v["course_id"] == "COH3C7"]
    assert [(v["participation_id"], v["niveau"], v["ev_max"]) for v in ceux_de_la_course] == [(part2, 3, 0.25)]
    # Le dossard est ce que le parieur cherche en premier sur la carte : la liste
    # doit le porter, comme le flux WS le faisait déjà.
    assert ceux_de_la_course[0]["numero"] == 2


async def test_delai_standard_identique_fiche_et_liste(client: AsyncClient, db: AsyncSession, admin_headers, inscrire):
    """Pari détecté il y a 1 min : invisible pour Standard sur la fiche ET sur la
    liste ; visible pour Expert sur les deux. Vingt minutes plus tard, visible
    partout."""
    part2 = await _seed(db, "COH4C7", dans=timedelta(hours=2), vb_detecte_il_y_a=timedelta(minutes=1))
    std = await _standard_headers(db, inscrire)

    def _vb_fiche(payload):
        return next(p["value_bet"] for p in payload["predictions"] if p["participation_id"] == part2)

    fiche_std = (await client.get("/api/v1/courses/COH4C7/predictions", headers=std)).json()
    assert fiche_std["verrouille"] is False
    assert _vb_fiche(fiche_std) is None
    liste_std = (await client.get("/api/v1/value-bets", headers=std)).json()
    assert not [v for v in liste_std if v["course_id"] == "COH4C7"]

    fiche_exp = (await client.get("/api/v1/courses/COH4C7/predictions", headers=admin_headers)).json()
    assert _vb_fiche(fiche_exp)["niveau"] == 3
    liste_exp = (await client.get("/api/v1/value-bets", headers=admin_headers)).json()
    assert [v["participation_id"] for v in liste_exp if v["course_id"] == "COH4C7"] == [part2]

    await db.execute(update(ValueBet).where(ValueBet.participation_id == part2)
                     .values(detecte_a=datetime.now(timezone.utc) - timedelta(minutes=20)))
    await db.commit()
    fiche_std = (await client.get("/api/v1/courses/COH4C7/predictions", headers=std)).json()
    assert _vb_fiche(fiche_std)["niveau"] == 3
    liste_std = (await client.get("/api/v1/value-bets", headers=std)).json()
    assert [v["participation_id"] for v in liste_std if v["course_id"] == "COH4C7"] == [part2]


async def test_liste_ne_tronque_plus_a_vingt(client: AsyncClient, db: AsyncSession, admin_headers):
    """74 paris détectés sur la journée du 2026-09-07 : à 20 par défaut, la page
    dédiée en taisait la moitié sans le dire, et un pari visible sur sa fiche
    manquait sur la liste."""
    for i in range(25):
        await _seed(db, f"COH5C{i:02d}", dans=timedelta(hours=1 + i / 60))
    liste = (await client.get("/api/v1/value-bets", headers=admin_headers)).json()
    assert len([v for v in liste if v["course_id"].startswith("COH5C")]) == 25
