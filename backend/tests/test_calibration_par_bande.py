"""Une probabilité de X % doit gagner X % du temps — et on doit le SAVOIR.

Mesure du 2026-08-31 : sous 0,40 la calibration est excellente (écart −0,0013 sur
46 497 partants) ; au-dessus, la probabilité servie dépasse le taux réel de 6 à
38 points. Rien ne le signalait, alors que la « cote juste » affichée et
l'espérance de gain qui en découle sont faussées d'autant.

Le point délicat n'est pas de détecter l'écart, c'est de ne PAS crier sur du
bruit : la bande 0,70+ compte 29 observations. D'où le seuil de preuve.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from services import data_quality as dq


async def _seed(db, *, n_par_bande):
    """Crée des partants dont la proba SERVIE et l'issue réelle sont contrôlées.

    Un partant par course : la bande de calibration se lit partant par partant, et
    une course par ligne évite toute interaction entre les probas d'un même champ.
    """
    from datetime import datetime, timedelta, timezone

    from db.models import Course, Participation, Prediction, Resultat

    depart = datetime.now(timezone.utc) - timedelta(days=1)
    i = 0
    for proba, taux, n in n_par_bande:
        for k in range(n):
            i += 1
            cid = f"C{i:06d}"
            gagne = k < round(taux * n)
            db.add(Course(course_id=cid, reunion_id="R1", numero=1, nom="T",
                          date_heure=depart, hippodrome_nom="Vincennes",
                          discipline="Attelé", distance=2700, nb_partants=10,
                          statut="termine"))
            db.add(Participation(participation_id=f"P{i:06d}", course_id=cid,
                                 cheval_id=f"H{i:06d}", numero=7, non_partant=False))
            db.add(Prediction(prediction_id=f"PR{i:06d}", participation_id=f"P{i:06d}",
                              course_id=cid, proba_top1=proba, proba_top3=0.9,
                              rang_predit=1, created_at=depart - timedelta(minutes=30)))
            db.add(Resultat(course_id=cid,
                            classement=[{"numero": 7 if gagne else 9, "position": 1}]))
    await db.commit()


@pytest.mark.asyncio
async def test_une_cohorte_trop_courte_ne_conclut_rien(db):
    await _seed(db, n_par_bande=[(0.45, 0.40, 20)])
    out = await dq.calibration_par_bande(db)
    assert out["disponible"] is False and out["n"] == 20


@pytest.mark.asyncio
async def test_une_bande_bien_calibree_ne_declenche_rien(db):
    await _seed(db, n_par_bande=[(0.10, 0.10, 400)])
    out = await dq.calibration_par_bande(db)
    bande = next(b for b in out["bandes"] if b["bande"] == "0.00-0.40")
    assert bande["n"] == 400 and abs(bande["ecart"]) < dq.SEUIL_ECART_CALIBRATION
    assert bande["concluant"] is True


@pytest.mark.asyncio
async def test_une_derive_prouvee_est_signalee(db):
    """Annoncé 45 %, réalisé 36 % sur 400 partants : c'est le défaut réel de
    production, à un volume qui autorise à le nommer."""
    await _seed(db, n_par_bande=[(0.45, 0.36, 400)])
    out = await dq.calibration_par_bande(db)
    bande = next(b for b in out["bandes"] if b["bande"] == "0.40-0.50")
    assert bande["n"] == 400
    assert bande["ecart"] == pytest.approx(0.09, abs=0.005)
    assert bande["concluant"] is True


@pytest.mark.asyncio
async def test_un_ecart_enorme_sur_trop_peu_de_monde_reste_non_concluant(db):
    """LE piège que ce seuil existe pour éviter.

    La bande 0,70+ affiche +38 points d'écart en production… sur 29 observations.
    Le chiffre est publié, mais il ne conclut pas — sinon la supervision passerait
    son temps à crier sur du bruit binomial, et finirait ignorée le jour où l'écart
    serait vrai.
    """
    await _seed(db, n_par_bande=[(0.10, 0.10, 400), (0.80, 0.40, 25)])
    out = await dq.calibration_par_bande(db)
    haute = next(b for b in out["bandes"] if b["bande"] == "0.70-1.00")
    assert haute["n"] == 25 and haute["ecart"] > 0.3
    assert haute["concluant"] is False


@pytest.mark.asyncio
async def test_sans_correction_en_service_rien_n_est_promis(db):
    """Pas d'exposant de netteté appliqué → pas de sous-fenêtre, et surtout pas de
    table manquante qui ferait échouer la mesure entière."""
    await _seed(db, n_par_bande=[(0.45, 0.36, 400)])
    out = await dq.calibration_par_bande(db)
    assert out["correction_nettete_depuis"] is None
    assert "bandes_depuis_correction" not in out


@pytest.mark.asyncio
async def test_la_mesure_isole_ce_qui_a_ete_servi_APRES_la_correction(db):
    """Une fenêtre de 90 jours regarde surtout le passé.

    Sans distinguer les pronostics produits APRÈS la mise en service d'une
    correction, l'alerte se répète des semaines durant sur un défaut déjà corrigé —
    et personne ne peut dire si le correctif a pris.
    """
    import json
    from datetime import datetime, timedelta, timezone

    await _seed(db, n_par_bande=[(0.45, 0.36, 400)])
    # Correction mise en service APRÈS les pronostics ci-dessus (produits à J-1).
    await db.execute(text("""
        CREATE TABLE IF NOT EXISTS sharpness_calibration (
            id INTEGER PRIMARY KEY, data TEXT NOT NULL, updated_at TIMESTAMP)
    """))
    hier = datetime.now(timezone.utc) - timedelta(hours=2)
    await db.execute(
        text("INSERT INTO sharpness_calibration (id, data) VALUES (1, :d)"),
        {"d": json.dumps({"exposant": 0.85, "retenu": True,
                          "applique_depuis": hier.isoformat()})})
    await db.commit()

    out = await dq.calibration_par_bande(db)
    assert out["correction_nettete_depuis"] is not None
    # Aucun pronostic n'a encore été servi sous la correction : on le dit, on ne
    # prétend pas que l'écart mesuré la juge.
    assert out["n_depuis_correction"] == 0
    assert out["bandes_depuis_correction"] == []
    # La mesure de fond, elle, continue de rapporter la dérive historique.
    bande = next(b for b in out["bandes"] if b["bande"] == "0.40-0.50")
    assert bande["ecart"] == pytest.approx(0.09, abs=0.005)
