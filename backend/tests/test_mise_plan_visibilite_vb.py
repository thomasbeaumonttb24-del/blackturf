"""Le plan de mise applique la règle de visibilité des paris de valeur.

`POST /courses/{id}/mise-plan` chargeait les `value_bets` actifs SANS la règle de
`services.valuebets_visibilite` : un abonné Standard y lisait en direct les paris
que /value-bets et la fiche course lui servent 15 min plus tard, et un compte
Free en voyait alors qu'il n'en voit nulle part ailleurs. Ce test pilote la
route sur SQLite et relève les paris de valeur transmis au moteur de plan
(`generer_plan`), qui les recopie tels quels dans la réponse.
"""
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.routes import courses
from db.models import Cheval, Course, Hippodrome, Participation, Prediction, Reunion, ValueBet

pytestmark = pytest.mark.asyncio

COURSE_ID = "R7C3"


async def _course_avec_deux_value_bets(db) -> None:
    """Course française dans 2 h ; ★★★ détecté il y a 1 min (n°1), il y a 40 min (n°2)."""
    maintenant = datetime.now(timezone.utc)
    hippo = Hippodrome(hippodrome_id=str(uuid.uuid4()), nom="Vincennes", code="VIN")
    db.add(hippo)
    db.add(Reunion(reunion_id="R7", date=maintenant.date(), hippodrome_id=hippo.hippodrome_id,
                   hippodrome_nom="Vincennes", numero=7))
    db.add(Course(course_id=COURSE_ID, reunion_id="R7", numero=3, nom="Prix Visibilité",
                  date_heure=maintenant + timedelta(hours=2), hippodrome_nom="Vincennes",
                  discipline="Plat", distance=1600, nb_partants=2, statut="a_venir"))
    for numero, detecte_il_y_a in ((1, timedelta(minutes=1)), (2, timedelta(minutes=40))):
        cheval = Cheval(cheval_id=str(uuid.uuid4()), nom=f"Cheval {numero}")
        part = Participation(participation_id=str(uuid.uuid4()), course_id=COURSE_ID,
                             cheval_id=cheval.cheval_id, numero=numero, cote_pmu=6.0,
                             non_partant=False)
        pred = Prediction(prediction_id=str(uuid.uuid4()),
                          participation_id=part.participation_id, course_id=COURSE_ID,
                          proba_top1=0.4 - 0.1 * numero, proba_top3=0.7, rang_predit=numero)
        db.add_all([cheval, part, pred])
        db.add(ValueBet(vb_id=str(uuid.uuid4()), prediction_id=pred.prediction_id,
                        course_id=COURSE_ID, participation_id=part.participation_id,
                        ev_pmu=0.25, ev_max=0.25, meilleure_source="pmu", niveau=3,
                        spi_detected=False, actif=True,
                        detecte_a=(maintenant - detecte_il_y_a).replace(tzinfo=None)))
    await db.commit()


async def _value_bets_transmis(db, monkeypatch, plan: str) -> set[int]:
    """Numéros portant un pari de valeur dans les `preds` donnés au moteur de plan."""
    async def _quota_ok(user, course_id):
        return True, 99, None

    async def _pas_de_cotes_live(course_id):
        return []

    captures: list = []

    def _generer_plan_espion(montant, profil, preds, *args, **kwargs):
        captures.append(preds)
        raise HTTPException(status_code=418, detail="capturé")

    import services.mise_calculator as mc
    import services.pmu_cotes as pmu_cotes
    monkeypatch.setattr(courses, "_mise_plan_quota_check", _quota_ok)
    monkeypatch.setattr(pmu_cotes, "fetch_live_cotes", _pas_de_cotes_live)
    monkeypatch.setattr(mc, "generer_plan", _generer_plan_espion)

    user = SimpleNamespace(user_id=f"u-{plan}", plan=plan, is_admin=False,
                           profil_risque="equilibre", bankroll_initiale=None)
    with pytest.raises(HTTPException) as exc:
        await courses.get_mise_plan(COURSE_ID, {"montant": 20}, db=db, user=user)
    assert exc.value.status_code == 418, exc.value.detail
    (preds,) = captures
    return {p["numero"] for p in preds if p.get("value_bet")}


@pytest.mark.parametrize("plan,attendus", [
    ("expert", {1, 2}),     # en direct
    ("standard", {2}),      # 15 min de retard : le pari d'il y a 1 min est tu
    ("starter", {2}),       # ancien nom de Standard
    ("free", set()),        # jamais
    ("decouverte", set()),  # jamais
])
async def test_mise_plan_filtre_les_value_bets_selon_le_plan(db, monkeypatch, plan, attendus):
    await _course_avec_deux_value_bets(db)
    assert await _value_bets_transmis(db, monkeypatch, plan) == attendus
