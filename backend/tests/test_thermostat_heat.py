"""Thermostat `heat` : sur quoi il s'appuie, et ce qu'il ne doit plus faire.

Constat du 2026-08-23 : le terme « résultats » lisait `bankroll_entries`, des paris
saisis À LA MAIN par des utilisateurs. 80 lignes étalées sur deux mois, 388 € misés,
+849 € nets — dont +578 € portés par deux tickets à ×120 et ×111. Le terme était collé
à son maximum et le thermostat annonçait heat = 0,748 (audace maximale sur TOUS les
profils) pendant que les plans du système mesuraient −6 % à −27 % de ROI.
"""
from datetime import datetime, timedelta, timezone

import pytest

from db.models import BetPlanSettlement, BetPlanSnapshot, Course, RaceLearningLog
from ml import bet_performance as bp


MAINTENANT = datetime.now(timezone.utc)


async def _seed_plans(db, n, mise, retour, *, jours=1, prefixe="H"):
    """n plans réglés identiques, émis avant le départ."""
    for i in range(n):
        cid = f"{prefixe}{i}"
        db.add(Course(course_id=cid, reunion_id="R1", numero=1, nom="T",
                      date_heure=MAINTENANT - timedelta(days=jours),
                      hippodrome_nom="Pau", discipline="Plat", distance=2000,
                      nb_partants=10, statut="termine"))
        db.add(BetPlanSnapshot(
            plan_snapshot_id=f"bp-{cid}", course_id=cid, subject_hash="system",
            profil="equilibre", montant_demande=mise, plan={"niveaux": []},
            plan_hash=f"h-{cid}", cotes_utilisees={}, algo_config={},
            algo_version="mp-t", nb_paris=1, montant_joue=mise,
            emitted_at=MAINTENANT - timedelta(days=jours, hours=1),
            course_start_at=MAINTENANT - timedelta(days=jours),
            is_pre_course=True, origin="mise_plan"))
        db.add(BetPlanSettlement(
            settlement_id=f"st-{cid}", plan_snapshot_id=f"bp-{cid}", course_id=cid,
            bilan={"paris": []}, montant_mise=mise, montant_retour=retour,
            net=retour - mise, roi=(retour - mise) / mise * 100, nb_paris=1,
            nb_gagnes=1 if retour > mise else 0, statut="settled",
            settled_at=MAINTENANT - timedelta(days=jours)))
    await db.commit()


@pytest.mark.asyncio
async def test_le_terme_resultats_lit_les_plans_emis_pas_les_saisies_manuelles(db):
    # 120 plans à l'équilibre exact du prélèvement : mise 10, retour 8 → ROI −20 %.
    await _seed_plans(db, 120, 10.0, 8.0)
    ctx = await bp.compute_model_heat(db)
    assert ctx["n_bets"] == 120
    # ROI −20 % + prélèvement 20 % → avantage ≈ 0 : le thermostat ne s'affole pas.
    assert abs(ctx["roi_recent"]) < 0.01, ctx


@pytest.mark.asyncio
async def test_un_systeme_qui_perd_vraiment_refroidit_le_thermostat(db):
    # ROI −50 % → avantage −30 points → terme au plancher.
    await _seed_plans(db, 120, 10.0, 5.0)
    ctx = await bp.compute_model_heat(db)
    assert ctx["roi_recent"] == pytest.approx(-0.30, abs=0.01)
    assert ctx["heat"] <= 0.0, "un système franchement perdant ne doit pas rester chaud"


@pytest.mark.asyncio
async def test_un_gain_isole_est_plafonne_a_50_fois_la_mise(db):
    """Le coup à ×120 qui portait tout le thermostat : le gain d'un plan est plafonné
    à 50× sa mise. Sur les 120 plans minimum du test l'effet reste visible ; sur la
    fenêtre réelle (~20 000 plans en 7 jours) un plan pèse 1/20 000."""
    await _seed_plans(db, 119, 10.0, 8.0)                       # équilibre
    await _seed_plans(db, 1, 10.0, 10_000.0, prefixe="JACKPOT")  # ×1000 sur un plan
    ctx = await bp.compute_model_heat(db)
    # Mise totale 1 200 € ; retour = 119×8 + min(10 000, 10×50) = 952 + 500.
    attendu = (952 + 500 - 1200) / 1200 + bp.PRELEVEMENT_MOYEN_SYSTEME_PCT / 100.0
    assert ctx["roi_recent"] == pytest.approx(attendu, abs=0.01)
    # Sans plafond, le même plan aurait donné plus de +800 % d'avantage.
    sans_plafond = (952 + 10_000 - 1200) / 1200
    assert ctx["roi_recent"] < sans_plafond / 10


@pytest.mark.asyncio
async def test_echantillon_trop_mince_neutralise_le_terme(db):
    await _seed_plans(db, bp._MIN_PLANS_FOR_ROI - 1, 10.0, 30.0)
    ctx = await bp.compute_model_heat(db)
    assert ctx["roi_recent"] is None, "un échantillon sous le seuil doit être ignoré"


@pytest.mark.asyncio
async def test_les_plans_trop_vieux_sortent_de_la_fenetre(db):
    await _seed_plans(db, 150, 10.0, 40.0, jours=bp._HEAT_ROI_JOURS + 3)
    ctx = await bp.compute_model_heat(db)
    assert ctx["roi_recent"] is None, (
        "des plans hors fenêtre ne doivent pas chauffer le thermostat")


@pytest.mark.asyncio
async def test_sans_aucune_donnee_le_thermostat_est_neutre(db):
    ctx = await bp.compute_model_heat(db)
    assert ctx["heat"] == 0.0
    assert ctx["roi_recent"] is None and ctx["brier"] is None
