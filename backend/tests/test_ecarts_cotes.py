"""Écarts PMU / bookmakers (services.ecarts_cotes).

Ce que ces tests verrouillent :
  1. le prix juste retire la marge du bookmaker (somme du champ) ;
  2. écart > 0 = le PMU paie PLUS (intéressant), < 0 = il paie moins ;
  3. une source qui cote moins de 80 % du champ est ignorée ; Geny jamais lu ;
  4. un écart positif d'une seule source n'est pas « proposé » ;
  5. chaque raison s'appuie sur une donnée de la course.
"""
import math

import pytest

from services.ecarts_cotes import (
    SEUIL_FORT, detecter_ecarts, probas_par_source, resume_course,
)


def _champ(pmu, **sources):
    """Partants numérotés 1..n ; `sources` = {colonne: [cotes]}."""
    out = []
    for i, c in enumerate(pmu):
        p = {"numero": i + 1, "participation_id": f"p{i + 1}", "non_partant": False,
             "cote_pmu": c}
        for col, cotes in sources.items():
            p[col] = cotes[i]
        out.append(p)
    return out


def _par_numero(ecarts):
    return {e["numero"]: e for e in ecarts}


def test_prix_juste_sans_marge():
    # Bookmaker à 2 / 2 : marge nulle → proba 0,5 chacun. Avec marge (1,8 / 1,8)
    # la somme vaut 1,11 → proba renormalisée à 0,5 aussi.
    pr = probas_par_source(_champ([2, 2], cote_unibet=[1.8, 1.8]))
    assert pr["cote_unibet"][0] == pytest.approx(0.5)
    assert sum(pr["cote_unibet"].values()) == pytest.approx(1.0)


def test_pmu_qui_paie_plus_est_un_ecart_positif():
    champ = _champ([6.0, 2.0, 4.0],
                   cote_unibet=[3.6, 2.0, 4.5], cote_bet365=[3.5, 2.1, 4.33])
    e = _par_numero(detecter_ecarts(champ))
    assert e[1]["ecart"] > SEUIL_FORT
    assert e[1]["niveau"] == "fort"
    assert e[1]["cote_juste_bookmakers"] < 6.0
    # Trié du plus intéressant au moins intéressant.
    ecarts = detecter_ecarts(champ)
    assert [x["ecart"] for x in ecarts] == sorted((x["ecart"] for x in ecarts), reverse=True)


def test_pmu_qui_paie_moins_est_defavorable():
    champ = _champ([1.5, 5.0, 5.0],
                   cote_unibet=[2.5, 3.0, 3.0], cote_bet365=[2.6, 2.9, 3.0])
    e = _par_numero(detecter_ecarts(champ))
    assert e[1]["ecart"] < 0 and e[1]["niveau"] == "defavorable"
    assert any("moins" in r for r in e[1]["raisons"])


def test_source_peu_couvrante_ignoree_et_geny_jamais_lu():
    champ = _champ([6.0, 2.0, 4.0, 8.0, 10.0],
                   cote_unibet=[3.0, 2.0, 4.5, 8.0, 10.0],
                   cote_bet365=[3.0, None, None, None, None],   # 20 % du champ
                   cote_geny=[50.0, 1.1, 1.1, 1.1, 1.1])
    e = _par_numero(detecter_ecarts(champ))
    assert e[1]["sources"] == ["Unibet"]
    assert "Geny" not in e[1]["cotes_bookmakers"]


def test_une_seule_source_n_est_pas_proposee():
    champ = _champ([6.0, 2.0, 4.0], cote_unibet=[3.0, 2.0, 4.5])
    e = _par_numero(detecter_ecarts(champ))
    assert e[1]["niveau"] == "a_confirmer"
    assert resume_course(detecter_ecarts(champ))["meilleur"] is None
    assert any("seule source" in t for t in e[1]["prudence"])


def test_cote_tres_haute_pas_proposee():
    champ = _champ([60.0, 2.0, 3.0], cote_unibet=[20.0, 2.0, 3.0], cote_bet365=[21.0, 2.0, 3.0])
    e = _par_numero(detecter_ecarts(champ))[1]
    assert e["ecart"] > SEUIL_FORT and e["niveau"] == "a_confirmer"
    assert any("au-delà de 40" in t for t in e["prudence"])


def test_non_partant_ignore_et_champ_sans_bookmaker_vide():
    champ = _champ([6.0, 2.0, 4.0], cote_unibet=[3.0, 2.0, 4.5], cote_bet365=[3.0, 2.0, 4.5])
    champ[0]["non_partant"] = True
    assert 1 not in _par_numero(detecter_ecarts(champ))
    assert detecter_ecarts(_champ([3.0, 2.0])) == []


def test_raisons_contextuelles():
    champ = _champ([30.0, 2.0, 3.0, 5.0],
                   cote_unibet=[15.0, 2.2, 3.2, 5.0],
                   cote_betfair_exchange=[16.0, 2.3, 3.4, 5.5])
    champ[0]["mouvement_cote_pct"] = 0.40        # cote PMU +40 % depuis l'ouverture
    e = _par_numero(detecter_ecarts(champ, etranger=True, pool_gagnant_eur=8000,
                                    fraicheur_min={"p1": {"cote_unibet": 90.0}}))[1]
    texte = " ".join(e["raisons"])
    assert "monté de 40 %" in texte
    assert "Outsider" in texte
    assert "étrangère" in texte
    assert "Betfair" in texte
    prud = " ".join(e["prudence"])
    assert "90 min" in prud and "8 000 €" in prud and "se referme" in prud
    # Course terminée : pas de prudence sur l'évolution d'avant départ.
    e2 = _par_numero(detecter_ecarts(champ, course_terminee=True, pool_gagnant_eur=8000))[1]
    assert not any("départ" in t or "enjeux" in t for t in e2["prudence"])


def test_ecart_vaut_proba_fois_cote_pmu_moins_un():
    champ = _champ([5.0, 2.0], cote_unibet=[4.0, 4.0 / 3.0], cote_bet365=[4.0, 4.0 / 3.0])
    e = _par_numero(detecter_ecarts(champ))[1]
    # Bookmakers : 1/4 + 3/4 = 1 → proba 0,25 ; écart = 0,25 × 5 − 1 = 0,25.
    assert e["ecart"] == pytest.approx(0.25, abs=1e-4)
    assert math.isclose(e["cote_juste_bookmakers"], 4.0, abs_tol=0.01)


# ─────────────────────────────────────────────────────────────
# Route publique /courses/{id}/ecarts-cotes
# ─────────────────────────────────────────────────────────────
import uuid as _uuid
from datetime import date as _date, datetime as _dt, timedelta as _td, timezone as _tz

from db.models import Cheval, Course, Hippodrome, Participation, Reunion


async def _course_avec_cotes(db, course_id="R9C1", depart=None):
    hippo = Hippodrome(hippodrome_id=str(_uuid.uuid4()), nom="Ecarts Test", code="ECT")
    db.add(hippo)
    db.add(Reunion(reunion_id="R9", date=_date.today(), hippodrome_id=hippo.hippodrome_id,
                   hippodrome_nom="Ecarts Test", numero=9))
    db.add(Course(course_id=course_id, reunion_id="R9", numero=1, nom="Prix Ecart",
                  date_heure=depart or (_dt.now(_tz.utc) + _td(hours=1)),
                  hippodrome_nom="Ecarts Test", discipline="Plat", distance=1600,
                  nb_partants=3, statut="a_venir"))
    for num, (pmu, uni, b365) in enumerate([(6.0, 3.6, 3.5), (2.0, 2.0, 2.1), (4.0, 4.5, 4.33)], 1):
        ch = Cheval(cheval_id=str(_uuid.uuid4()), nom=f"Cheval {num}", age=4, sexe="H")
        db.add(ch)
        db.add(Participation(participation_id=str(_uuid.uuid4()), course_id=course_id,
                             cheval_id=ch.cheval_id, numero=num, cote_pmu=pmu,
                             cote_unibet=uni, cote_bet365=b365, non_partant=False))
    await db.commit()
    return course_id


@pytest.mark.asyncio
async def test_route_ecarts_course(client, db):
    cid = await _course_avec_cotes(db)
    r = await client.get(f"/api/v1/courses/{cid}/ecarts-cotes")
    assert r.status_code == 200
    d = r.json()
    assert d["ecarts"][0]["numero"] == 1 and d["ecarts"][0]["niveau"] == "fort"
    assert d["ecarts"][0]["nom"] == "Cheval 1"
    assert d["nb_fort"] == 1 and d["meilleur"]["numero"] == 1


@pytest.mark.asyncio
async def test_route_ecarts_course_inconnue_vide(client, db):
    r = await client.get("/api/v1/courses/INCONNUE/ecarts-cotes")
    assert r.status_code == 200 and r.json()["ecarts"] == []


@pytest.mark.asyncio
async def test_route_ecarts_du_jour(client, db):
    from services.temps_courses import PARIS, jour_courses
    depart = _dt.now(_tz.utc) + _td(minutes=20)
    if depart.astimezone(PARIS).date() != jour_courses():
        pytest.skip("départ de test au lendemain (minuit à Paris)")
    await _course_avec_cotes(db, depart=depart)
    r = await client.get("/api/v1/ecarts-cotes/jour")
    assert r.status_code == 200
    lignes = r.json()["ecarts"]
    assert [l["numero"] for l in lignes] == [1]
    assert lignes[0]["code"] == "R9C1" and lignes[0]["hippodrome"] == "Ecarts Test"
