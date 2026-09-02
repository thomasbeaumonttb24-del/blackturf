"""La supervision doit dire ce qui apprend, ce qui n'apprend plus, et ce qui n'a
jamais prouvé qu'il servait à quelque chose.

Trois angles morts que cette vue ferme :

  - les dix-huit apprentissages nocturnes vivent derrière le retrain dans un seul
    job RQ : un OOM du worker les fait sauter en silence ;
  - un correcteur pouvait être en service SANS avoir prouvé qu'il améliorait la
    probabilité servie ;
  - une correction pouvait être apprise et jamais servie.

Invariant de ce module : tout provient d'un état réellement persisté. Un outil sans
mesure rend `mesure_disponible = false` et dit pourquoi — jamais une valeur neutre
déguisée en mesure.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from ml import learning_steps as ls
from ml.supervision_apprentissage import etat_outils_apprentissage


@pytest.mark.asyncio
async def test_a_froid_tout_est_declare_indisponible_et_explique(db):
    etat = await etat_outils_apprentissage(db)
    assert etat["etapes"] == []
    assert etat["etapes_perimees"] == []
    assert etat["alerte"] is False

    arrivee = etat["modele_arrivee"]
    assert arrivee["mesure_disponible"] is False
    assert arrivee["corrige"] is False
    assert arrivee["pourquoi"], "une absence de mesure doit s'expliquer"
    assert arrivee["exposants"] == [1.0, 1.0, 1.0, 1.0, 1.0], (
        "sans mesure, le modèle d'arrivée tourne sans correction")

    assert etat["correcteur_contextuel"]["mesure_disponible"] is False
    assert etat["plans"]["mesure_disponible"] is False
    assert etat["gates_types"]["mesure_disponible"] is False


@pytest.mark.asyncio
async def test_une_etape_perimee_declenche_l_alerte(db):
    await ls.enregistrer_etape(db, "isotone_top3", statut="ok")
    await ls.enregistrer_etape(db, "poids_profils", statut="ok")
    await db.execute(text(
        "UPDATE learning_step_runs SET last_success_at = :vieux "
        "WHERE step = 'poids_profils'"),
        {"vieux": datetime.now(timezone.utc) - timedelta(hours=96)})
    await db.commit()

    etat = await etat_outils_apprentissage(db)
    assert etat["etapes_perimees"] == ["poids_profils"]
    assert etat["alerte"] is True
    ages = {e["step"]: e["age_heures"] for e in etat["etapes"]}
    assert ages["poids_profils"] > 48
    assert ages["isotone_top3"] < 1


@pytest.mark.asyncio
async def test_le_verdict_du_correcteur_est_expose(db):
    """C'est LE chiffre qui manquait : le correcteur fait-il mieux que ne rien
    corriger ? L'AUC publiée mesurait sa performance sur SA tâche, pas ça."""
    from ml.meta_learner import TRAINING_CONTRACT, get_meta_learner

    ml = get_meta_learner()
    ancien_modele, anciennes = ml._model, ml._metrics
    try:
        ml._model = object()
        ml._contract = TRAINING_CONTRACT
        ml._n_samples = 12400
        ml._metrics = {"status": "ok", "n_courses": 1240, "pos_rate": 0.29,
                       "logloss_meta": 0.5712, "logloss_sans_correction": 0.5804,
                       "gain_logloss": 0.0092}
        etat = (await etat_outils_apprentissage(db))["correcteur_contextuel"]
    finally:
        ml._model, ml._metrics = ancien_modele, anciennes

    assert etat["actif"] is True
    assert etat["contrat_a_jour"] is True
    assert etat["mesure_disponible"] is True
    assert etat["logloss_avec_correction"] < etat["logloss_sans_correction"]
    assert etat["gain_logloss"] > 0
    assert etat["n_courses"] == 1240
    assert etat["taux_de_base"] == 0.29, (
        "le taux de base par PARTANT (~0,27), pas celui par course (0,617)")


@pytest.mark.asyncio
async def test_un_contrat_perime_est_signale(db):
    """Un pickle entraîné sous un autre contrat ne doit pas passer pour à jour."""
    from ml.meta_learner import get_meta_learner

    ml = get_meta_learner()
    ancien = getattr(ml, "_contract", None)
    try:
        ml._contract = "course/top3_du_gagnant/v0"
        etat = (await etat_outils_apprentissage(db))["correcteur_contextuel"]
    finally:
        ml._contract = ancien
    assert etat["contrat_a_jour"] is False
    assert etat["contrat"] == "course/top3_du_gagnant/v0"


@pytest.mark.asyncio
async def test_les_conseils_sont_comptes_en_courses_pas_en_re_emissions(db):
    """Le même plan est ré-émis à chaque mouvement de cote : compter les snapshots
    faisait croire à trente fois plus d'observations qu'il n'y en a."""
    from db.models import BetPlanSettlement, BetPlanSnapshot, Course

    depart = datetime(2026, 8, 20, 14, 0, tzinfo=timezone.utc)
    db.add(Course(course_id="C1", reunion_id="R1", numero=1, nom="T",
                  date_heure=depart, hippodrome_nom="Pau", discipline="Plat",
                  distance=2000, nb_partants=10, statut="termine"))
    for k in range(12):
        sid = f"bp-{k}"
        db.add(BetPlanSnapshot(
            plan_snapshot_id=sid, course_id="C1", subject_hash="system",
            profil="equilibre", montant_demande=10.0, plan={"niveaux": []},
            plan_hash=f"h{k}", cotes_utilisees={}, algo_config={},
            algo_version="t", nb_paris=1, montant_joue=4.0,
            emitted_at=depart - timedelta(minutes=10 * k),
            course_start_at=depart, is_pre_course=True, origin="mise_plan"))
        db.add(BetPlanSettlement(
            settlement_id=f"st-{k}", plan_snapshot_id=sid, course_id="C1",
            bilan={"paris": []}, montant_mise=4.0, montant_retour=0.0,
            net=-4.0, roi=-100.0, nb_paris=1, nb_gagnes=0, statut="settled",
            settled_at=depart + timedelta(hours=2)))
    await db.commit()

    plans = (await etat_outils_apprentissage(db))["plans"]
    assert plans["n_snapshots_bruts"] == 12
    assert plans["n_conseils_distincts"] == 1, "un conseil, pas douze"
    assert plans["n_courses"] == 1
    assert plans["re_emissions_par_conseil"] == 12.0


@pytest.mark.asyncio
async def test_les_gates_actives_sont_listees(db):
    from ml.bet_plan_performance import persist_segment_gates

    await persist_segment_gates(db, "type_pari", {
        "Trio": {"status": "suspended", "factor": 0.0, "reason": "avantage -12 pts",
                 "roi_pct": -37.0, "n_paris": 210},
        "Simple Placé": {"status": "active", "factor": 1.0, "reason": None,
                         "roi_pct": -6.0, "n_paris": 640},
    })
    gates = (await etat_outils_apprentissage(db))["gates_types"]
    assert gates["mesure_disponible"] is True
    assert gates["n_suspendus"] == 1
    types = {g["type"]: g for g in gates["gates"]}
    assert types["Trio"]["statut"] == "suspended"
    assert types["Trio"]["facteur"] == 0.0
    assert types["Simple Placé"]["statut"] == "active"


@pytest.mark.asyncio
async def test_la_temperature_dit_comment_elle_est_obtenue(db):
    """« 1,2567 » ne veut pas dire la même chose selon qu'elle sort d'un cliquet
    ou d'un ajustement sur mesure — la supervision doit le dire."""
    etat = (await etat_outils_apprentissage(db))["temperature"]
    assert "bornes" in etat and etat["bornes"] == [0.6, 2.0]
    assert isinstance(etat["ajustee_sur_mesure"], bool)
    assert etat["lecture"], "l'origine du chiffre doit être écrite"


@pytest.mark.asyncio
async def test_l_endpoint_est_reserve_a_l_admin():
    """Un endpoint de supervision expose l'état interne : il ne s'ouvre pas."""
    import inspect

    from api.routes import admin

    src = inspect.getsource(admin.supervision_outils_apprentissage)
    assert "require_admin" in src


@pytest.mark.asyncio
async def test_le_compteur_de_conseils_colle_a_la_deduplication_reelle(db):
    """Le compteur affiché doit rendre EXACTEMENT le nombre d'observations que
    l'apprentissage utilise. S'il s'en écartait, la supervision annoncerait une
    quantité de données que le moteur n'a pas.

    Piège vérifié : la bankroll est NULLE sur les plans du système, et une
    concaténation avec NULL rend NULL — sans COALESCE, la clé entière disparaît et
    le compte tombe à zéro.
    """
    from db.models import BetPlanSettlement, BetPlanSnapshot, Course
    from ml.bet_plan_performance import compute_forward_performance

    depart = datetime(2026, 8, 21, 14, 0, tzinfo=timezone.utc)
    plan = {"montant_joue": 4.0, "ev_global": 0.1, "esperance_gain": 0.4,
            "niveaux": [{"niveau": "securite", "paris": [{
                "type": "Placé", "chevaux": [{"numero": 1, "nom": "X"}],
                "mise": 4.0, "gain_potentiel": 12.0, "probabilite": 0.4,
                "ev_estime": 0.1, "description": "d"}]}]}

    # 2 courses × 2 profils × 2 montants, chacun ré-émis 7 fois, bankroll NULLE.
    attendu = 0
    for c in range(2):
        cid = f"D{c}"
        db.add(Course(course_id=cid, reunion_id="R1", numero=1, nom="T",
                      date_heure=depart, hippodrome_nom="Pau", discipline="Plat",
                      distance=2000, nb_partants=10, statut="termine"))
        for profil in ("equilibre", "agressif"):
            for montant in (10.0, 50.0):
                attendu += 1
                for k in range(7):
                    sid = f"bp-{cid}-{profil}-{montant}-{k}"
                    db.add(BetPlanSnapshot(
                        plan_snapshot_id=sid, course_id=cid, subject_hash="system",
                        profil=profil, montant_demande=montant, bankroll=None,
                        plan=plan, plan_hash=sid, cotes_utilisees={},
                        algo_config={}, algo_version="t", nb_paris=1,
                        montant_joue=4.0,
                        emitted_at=depart - timedelta(minutes=10 * k),
                        course_start_at=depart, is_pre_course=True,
                        origin="mise_plan"))
                    db.add(BetPlanSettlement(
                        settlement_id=f"st-{sid}", plan_snapshot_id=sid,
                        course_id=cid,
                        bilan={"paris": [{"type": "Placé", "mise": 4.0,
                                          "gain": 0.0, "statut": "perdu"}]},
                        montant_mise=4.0, montant_retour=0.0, net=-4.0,
                        roi=-100.0, nb_paris=1, nb_gagnes=0, statut="settled",
                        settled_at=depart + timedelta(hours=2)))
    await db.commit()

    plans = (await etat_outils_apprentissage(db))["plans"]
    perf = await compute_forward_performance(db, "type_pari")

    assert plans["n_snapshots_bruts"] == attendu * 7
    assert plans["n_conseils_distincts"] == attendu, (
        "la bankroll nulle ne doit pas annuler la clé de conseil")
    assert plans["n_conseils_distincts"] == perf["global"]["n_plans"], (
        "le compteur affiché et la déduplication réelle doivent coïncider")
    assert plans["n_courses"] == 2
    assert plans["re_emissions_par_conseil"] == 7.0


@pytest.mark.asyncio
async def test_l_alpha_du_melange_est_expose(db):
    """ALPHA est le DERNIER arbitrage de la chaîne : il décide du classement
    affiché, des cotes justes, de l'EV, donc des paris émis. Il était posé à la
    main sans qu'aucune mesure ne l'ait jamais vérifié — la supervision doit dire
    s'il est appris ou hérité d'un réglage."""
    from ml.blend_calibration import ALPHA_MAX_DEFAUT

    etat = (await etat_outils_apprentissage(db))["alpha_marche"]
    assert etat["mesure_disponible"] is False
    assert etat["appris"] is False
    assert etat["alpha_max"] == ALPHA_MAX_DEFAUT, (
        "sans mesure, c'est exactement la valeur d'avant qui est servie")
    assert etat["pourquoi"], "une absence de mesure doit s'expliquer"


@pytest.mark.asyncio
async def test_un_alpha_appris_est_affiche_avec_ses_deux_gains(db):
    import json as _json

    await db.execute(text("""
        CREATE TABLE IF NOT EXISTS blend_alpha (
            id INTEGER PRIMARY KEY, data TEXT NOT NULL, updated_at TIMESTAMP)
    """))
    await db.execute(
        text("INSERT INTO blend_alpha (id, data, updated_at) "
             "VALUES (1, :d, CURRENT_TIMESTAMP)"),
        {"d": _json.dumps({"retenu": True, "alpha_max": 0.25,
                           "alpha_en_place": 0.42, "gain_logv": 0.0083,
                           "gain_rang": 0.0021, "n_courses": 3612})})
    await db.commit()

    etat = (await etat_outils_apprentissage(db))["alpha_marche"]
    assert etat["appris"] is True
    assert etat["alpha_max"] == 0.25
    assert etat["alpha_en_place"] == 0.42
    assert etat["gain_logv"] > 0, "la vraisemblance du gagnant s'améliore"
    assert etat["gain_rang"] >= 0, "le classement ne se dégrade pas"
    assert etat["n_courses"] == 3612
