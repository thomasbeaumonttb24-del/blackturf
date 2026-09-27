"""Console admin : suivi du parrainage (qui parraine qui, où en est chacun)."""
import uuid
from datetime import datetime, timezone

import pytest

from db.models import Parrainage, SubscriptionEvent, User
from services import parrainage as P


async def _compte(db, email, **kw):
    u = User(user_id=str(uuid.uuid4()), email=email, prenom=email.split("@")[0].capitalize(),
             plan=kw.pop("plan", "free"), email_verified=True, **kw)
    db.add(u)
    await db.commit()
    return u


@pytest.mark.asyncio
async def test_reserve_a_ladmin(client, auth_headers):
    assert (await client.get("/admin/api/parrainages", headers=auth_headers)).status_code == 403


@pytest.mark.asyncio
async def test_suivi_complet(client, db, admin_headers):
    victor = await _compte(db, "victor@blackturf.fr", plan="expert")
    zoe = await _compte(db, "zoe@blackturf.fr")
    code_v = await P.code_de(victor, db)
    await P.code_de(zoe, db)
    maintenant = datetime.now(timezone.utc)

    lea = await _compte(db, "lea@blackturf.fr")
    tom = await _compte(db, "tom@blackturf.fr")
    max_ = await _compte(db, "max@blackturf.fr")
    for f in (lea, tom, max_):
        await P.rattacher_filleul(f, code_v, db)
    await db.commit()
    liens = {l.filleul_id: l for l in (await db.execute(__import__("sqlalchemy").select(Parrainage))).scalars()}
    # Léa a payé et Victor est crédité ; Tom a été refusé (carte de Victor) ; Max attend.
    liens[lea.user_id].statut = "valide"
    liens[lea.user_id].valide_at = maintenant
    liens[lea.user_id].credit_pose_at = maintenant
    liens[lea.user_id].credit_cents = 500
    liens[lea.user_id].remise_filleul_at = maintenant
    liens[tom.user_id].statut = "refuse"
    liens[tom.user_id].motif = "carte_du_parrain"
    liens[tom.user_id].remise_filleul_at = maintenant
    db.add(SubscriptionEvent(event_id=str(uuid.uuid4()), user_id=lea.user_id, email=lea.email,
                             type="paiement_recu", montant_cents=1400))
    db.add(SubscriptionEvent(event_id=str(uuid.uuid4()), user_id=lea.user_id, email=lea.email,
                             type="paiement_recu", montant_cents=1900))
    await db.commit()

    r = await client.get("/admin/api/parrainages", headers=admin_headers)
    assert r.status_code == 200, r.text
    d = r.json()

    s = d["resume"]
    assert s["liens_generes"] == 2 and s["parrains_actifs"] == 1 and s["filleuls"] == 3
    assert (s["valides"], s["en_attente"], s["refuses"]) == (1, 1, 1)
    assert s["taux_conversion"] == pytest.approx(33.3)
    assert s["credits_parrains_cents"] == 500 and s["remises_filleuls_cents"] == 1000
    assert s["ca_filleuls_cents"] == 3300  # 14 € + 19 € encaissés auprès de Léa
    assert s["rendement"] == pytest.approx(2.2)

    (v,) = d["parrains"]
    assert v["email"] == "victor@blackturf.fr" and v["code"] == code_v
    assert (v["filleuls"], v["valides"], v["en_attente"], v["refuses"]) == (3, 1, 1, 1)
    assert v["gagne_cents"] == 500 and v["ca_filleuls_cents"] == 3300

    par_filleul = {l["filleul"]["email"]: l for l in d["liens"]}
    assert par_filleul["lea@blackturf.fr"]["etape"] == "credite"
    assert par_filleul["lea@blackturf.fr"]["parrain"]["email"] == "victor@blackturf.fr"
    assert par_filleul["tom@blackturf.fr"]["motif_libelle"].startswith("Le filleul a payé avec la carte du parrain")
    assert par_filleul["max@blackturf.fr"]["etape"] == "attente_paiement"
    assert len(d["evolution"]) == 6 and d["evolution"][-1]["inscrits"] == 3


@pytest.mark.asyncio
async def test_fiche_compte_parrain_et_filleul(client, db, admin_headers):
    victor = await _compte(db, "victor@blackturf.fr", plan="expert")
    lea = await _compte(db, "lea@blackturf.fr")
    await P.rattacher_filleul(lea, await P.code_de(victor, db), db)
    await db.commit()

    fiche_v = (await client.get(f"/admin/api/users/{victor.user_id}", headers=admin_headers)).json()["parrainage"]
    assert fiche_v["code"] and fiche_v["parraine_par"] is None
    assert [f["email"] for f in fiche_v["filleuls"]] == ["lea@blackturf.fr"]
    assert fiche_v["filleuls"][0]["statut"] == "en_attente"

    fiche_l = (await client.get(f"/admin/api/users/{lea.user_id}", headers=admin_headers)).json()["parrainage"]
    assert fiche_l["parraine_par"]["email"] == "victor@blackturf.fr" and fiche_l["filleuls"] == []
