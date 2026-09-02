"""Le méta-apprenant doit apprendre ce qu'il corrige.

Ce qu'il faisait
────────────────
Il s'entraînait sur ``race_learning_log``, une ligne par COURSE :

  - label   « le vrai gagnant est-il dans le top-3 prédit ? » — une propriété de la
            COURSE, alors que sa sortie remplace la proba de CHAQUE partant ;
  - entrée  ``gagnant_proba_ia``, la proba du GAGNANT, connue seulement après
            l'arrivée, alors qu'au service il reçoit la proba de tous les partants ;
  - six features sur quinze (``jours_repos``, ``elo_vs_moyenne``,
    ``forme_5_courses``, ``spi_score``, ``cote_pmu`` = min du champ, ``rang_cote``
    fabriqué depuis la proba) étaient des CONSTANTES à l'entraînement et de vraies
    valeurs au service ;
  - taux de base 0,617 par course contre ~0,27 par partant.

Et rien ne vérifiait que l'appliquer améliorait quoi que ce soit : l'AUC publiée
mesurait sa performance sur SA tâche, pas sur celle qu'on lui faisait faire.
"""
import numpy as np
import pytest

from ml import meta_learner as ml


# ── Regroupement par course ────────────────────────────────────────────────

def test_grouper_par_course_preserve_l_ordre_chronologique():
    rows = [("C1", 1), ("C1", 2), ("C2", 1), ("C1", 3)]
    out = ml._grouper_par_course(rows)
    assert [cid for cid, _ in out] == ["C1", "C2", "C1"], (
        "les lignes arrivent triées par date : on ne réordonne rien")
    assert len(out[0][1]) == 2


# ── Label : le partant, pas la course ──────────────────────────────────────

def test_le_top3_est_lu_sur_la_position_pas_sur_l_ordre_du_tableau():
    """Le classement n'est pas garanti trié (même précédent que
    `calibration_longshots.fetch_winners`)."""
    classement = [{"numero": 7, "position": 3}, {"numero": 2, "position": 1},
                  {"numero": 9, "position": 5}, {"numero": 4, "position": 2}]
    assert ml._top3_du_classement(classement) == {2, 4, 7}


def test_un_classement_illisible_ne_produit_aucun_label():
    """Aucune valeur par défaut : sans arrivée exploitable, pas d'exemple."""
    assert ml._top3_du_classement(None) == set()
    assert ml._top3_du_classement([]) == set()
    assert ml._top3_du_classement("pas du json") == set()
    assert ml._top3_du_classement([{"numero": None, "position": None}]) == set()


def test_le_classement_json_en_chaine_est_accepte():
    """asyncpg rend un dict, le codec SQLite des tests rend une chaîne."""
    assert ml._top3_du_classement(
        '[{"numero": 3, "position": 1}, {"numero": 5, "position": 2}]') == {3, 5}


# ── L'entrée du fit est celle du service ───────────────────────────────────

def test_base_proba_reconstruit_l_entree_du_service():
    """`base_proba_de_course` doit être le miroir exact de la chaîne d'inférence :
    isotone top3, puis température centrée sur la course."""
    raw = [0.40, 0.30, 0.20, 0.10]
    sans_courbe = ml.base_proba_de_course(raw, None, 4, temperature=1.0)
    assert np.allclose(sans_courbe, raw, atol=1e-6), (
        "sans courbe ni température, la reconstruction est l'identité")


def test_la_temperature_resserre_autour_de_la_moyenne_du_champ():
    """T > 1 doit RÉDUIRE l'écart favori↔champ, pas propulser les outsiders vers
    0,5 — c'est tout l'objet du centrage sur la moyenne des logits."""
    raw = [0.60, 0.30, 0.06, 0.04]
    chaud = ml.base_proba_de_course(raw, None, 4, temperature=1.5)
    assert chaud[0] < raw[0], "le favori est ramené vers le champ"
    assert chaud[3] > raw[3], "l'outsider remonte, mais…"
    assert chaud[3] < 0.20, "…il ne part pas vers 0,5"
    assert np.all(np.diff(chaud) < 0), "l'ordre du champ est préservé"


def test_les_echantillons_portent_les_vraies_valeurs_du_partant():
    """C'est LE défaut corrigé : chaque partant apporte SES features, pas une
    constante partagée."""
    from datetime import datetime, timezone
    dh = datetime(2026, 5, 12, 15, 30, tzinfo=timezone.utc)
    classement = [{"numero": 1, "position": 1}, {"numero": 2, "position": 4},
                  {"numero": 3, "position": 2}]
    lignes = [
        ("C1", 1, 0.55, {"jours_repos": 12, "cote_pmu": 2.1, "rang_cote": 1,
                         "elo_vs_moyenne": 90.0, "forme_5_courses": 0.8,
                         "spi_score": 0.4},
         "Plat", "Bon", "Pau", 3, dh, False, 2000, classement),
        ("C1", 2, 0.25, {"jours_repos": 60, "cote_pmu": 14.0, "rang_cote": 5,
                         "elo_vs_moyenne": -40.0, "forme_5_courses": 0.2,
                         "spi_score": -0.3},
         "Plat", "Bon", "Pau", 3, dh, False, 2000, classement),
        ("C1", 3, 0.20, {"jours_repos": 30, "cote_pmu": 6.0, "rang_cote": 3,
                         "elo_vs_moyenne": 10.0, "forme_5_courses": 0.5,
                         "spi_score": 0.0},
         "Plat", "Bon", "Pau", 3, dh, False, 2000, classement),
    ]
    ech = ml._echantillons_de_course(lignes, None)
    assert len(ech) == 3
    assert [lab for _, lab in ech] == [1, 0, 1], "label = CE cheval est top-3"

    idx = {n: i for i, n in enumerate(ml.FEATURE_NAMES)}
    cotes = [v[idx["cote_pmu"]] for v, _ in ech]
    assert cotes == [2.1, 14.0, 6.0], "la cote du PARTANT, pas le min du champ"
    repos = [v[idx["jours_repos"]] for v, _ in ech]
    assert repos == [12.0, 60.0, 30.0], "plus de constante 20"
    elos = [v[idx["elo_vs_moyenne"]] for v, _ in ech]
    assert elos == [90.0, -40.0, 10.0], "plus de constante 0.0"
    rangs = [v[idx["rang_cote"]] for v, _ in ech]
    assert rangs == [1.0, 5.0, 3.0], "le vrai rang, pas 1/proba×0.5"
    mois = [v[idx["season_month"]] for v, _ in ech]
    assert mois == [5.0, 5.0, 5.0], "le mois vient de la course"
    assert all(len(v) == len(ml.FEATURE_NAMES) + 1 for v, _ in ech)


def test_une_course_sans_arrivee_ne_produit_aucun_exemple():
    from datetime import datetime, timezone
    dh = datetime(2026, 5, 12, 15, 30, tzinfo=timezone.utc)
    lignes = [("C1", 1, 0.5, {}, "Plat", "Bon", "Pau", 2, dh, False, 2000, None)]
    assert ml._echantillons_de_course(lignes, None) == []


# ── Découpage du hold-out ──────────────────────────────────────────────────

def test_le_hold_out_est_decoupe_par_course_pas_par_ligne():
    """Les partants d'une même course partagent leurs features de champ : un
    découpage par ligne les laisserait fuir dans leur propre hold-out."""
    groupes = ["C1"] * 4 + ["C2"] * 4 + ["C3"] * 4 + ["C4"] * 4 + ["C5"] * 4
    masque = ml._masque_holdout_par_course(groupes, frac_train=0.8)
    assert masque.sum() == 4, "une course sur cinq en hold-out"
    for cid in ("C1", "C2", "C3", "C4", "C5"):
        vus = {bool(m) for m, g in zip(masque, groupes) if g == cid}
        assert len(vus) == 1, f"{cid} est à cheval sur les deux côtés"


def test_le_hold_out_prend_les_courses_les_plus_recentes():
    groupes = ["C1"] * 2 + ["C2"] * 2 + ["C3"] * 2 + ["C4"] * 2 + ["C5"] * 2
    masque = ml._masque_holdout_par_course(groupes, frac_train=0.8)
    assert [g for m, g in zip(masque, groupes) if m] == ["C5", "C5"]


# ── Gate d'utilité ─────────────────────────────────────────────────────────

class _Correcteur:
    """Modèle factice qui rend la proba qu'on lui dicte."""

    def __init__(self, sortie):
        self._sortie = np.asarray(sortie, dtype=float)

    def predict_proba(self, X):
        return np.column_stack([1 - self._sortie, self._sortie])


def test_un_correcteur_qui_n_apporte_rien_est_declare_inutile():
    """Il rend exactement la proba de base : le mélange est l'identité, gain nul."""
    base = np.array([0.8, 0.2, 0.6, 0.1, 0.9, 0.3], dtype=np.float32)
    y = np.array([1, 0, 1, 0, 1, 0])
    X = np.column_stack([base] + [np.zeros_like(base)] * 14)
    v = ml._verdict_utilite(_Correcteur(base), X, y)
    assert v["utile"] is False
    assert v["gain_logloss"] == pytest.approx(0.0, abs=1e-6)


def test_un_correcteur_qui_degrade_est_rejete():
    base = np.array([0.8, 0.2, 0.6, 0.1, 0.9, 0.3], dtype=np.float32)
    y = np.array([1, 0, 1, 0, 1, 0])
    X = np.column_stack([base] + [np.zeros_like(base)] * 14)
    v = ml._verdict_utilite(_Correcteur(1.0 - base), X, y)   # à contresens
    assert v["utile"] is False
    assert v["gain_logloss"] < 0


def test_un_correcteur_qui_ameliore_est_accepte():
    base = np.array([0.5] * 6, dtype=np.float32)             # base sans information
    y = np.array([1, 0, 1, 0, 1, 0])
    X = np.column_stack([base] + [np.zeros_like(base)] * 14)
    v = ml._verdict_utilite(_Correcteur([0.9, 0.1] * 3), X, y)
    assert v["utile"] is True
    assert v["gain_logloss"] > ml.MIN_GAIN_LOGLOSS
    assert v["logloss_meta"] < v["logloss_sans_correction"]


def test_le_verdict_juge_le_melange_reellement_servi():
    """Le gate doit noter ce que le service applique — `META_BLEND_BASE` de base
    plus le reste de correction — et non la sortie brute du correcteur."""
    assert 0.0 < ml.META_BLEND_BASE < 1.0
    base = np.array([0.5] * 6, dtype=np.float32)
    y = np.array([1, 0, 1, 0, 1, 0])
    X = np.column_stack([base] + [np.zeros_like(base)] * 14)
    sortie = np.array([1.0, 0.0] * 3)                        # parfait mais extrême
    v = ml._verdict_utilite(_Correcteur(sortie), X, y)
    from sklearn.metrics import log_loss
    melange = ml.META_BLEND_BASE * base + (1 - ml.META_BLEND_BASE) * sortie
    attendu = float(log_loss(y, np.clip(melange, 0.01, 0.99), labels=[0, 1]))
    assert v["logloss_meta"] == pytest.approx(attendu, abs=1e-6)


def test_un_hold_out_sans_les_deux_classes_ne_conclut_pas():
    base = np.array([0.5] * 4, dtype=np.float32)
    X = np.column_stack([base] + [np.zeros_like(base)] * 14)
    v = ml._verdict_utilite(_Correcteur(base), X, np.array([1, 1, 1, 1]))
    assert v["utile"] is False
    assert v["gain_logloss"] is None


# ── Câblage ────────────────────────────────────────────────────────────────

def test_l_entrainement_lit_les_previsions_par_partant():
    import inspect
    src = inspect.getsource(ml.MetaLearner.train)
    assert "FROM prediction_evaluation" in src, (
        "source = les prédictions FIGÉES par partant, avec leurs features gelées")
    assert "FROM race_learning_log" not in src, (
        "race_learning_log est agrégé par course : ce n'est pas la bonne unité "
        "(le nom peut rester dans la docstring, qui explique ce qui a changé)")
    assert "pe.created_at < c.date_heure" in src, "garde anti-fuite"
    assert "pe.is_replayable = true" in src, "garde anti-fuite"


def test_un_modele_non_valide_n_est_jamais_conserve():
    import inspect
    src = inspect.getsource(ml.MetaLearner.train)
    i_verdict = src.index('verdict = _verdict_utilite')
    i_garde = src.index("self._model = model")
    assert i_verdict < i_garde, "on valide AVANT de conserver"
    assert 'if not verdict["utile"]' in src
    assert "self._model = None" in src


def test_le_biais_contextuel_n_est_plus_compte_deux_fois():
    """La matrice de biais et le méta-apprenant corrigent la même chose. Les
    appliquer tous les deux comptait la correction deux fois — et faisait diverger
    l'entrée du méta-apprenant de celle qu'il avait apprise."""
    import inspect
    from ml import pipeline
    src = inspect.getsource(pipeline.predict_course)
    assert "bias_correction=0.0," in src
    assert "bias_correction=bias_correction," not in src


# ── Bout en bout, contre la vraie vue `prediction_evaluation` ───────────────

@pytest.mark.asyncio
async def test_entrainement_bout_en_bout_sur_des_partants(db):
    """Le méta-apprenant s'entraîne sur des PARTANTS issus de la vue, avec le
    label du partant, et ne se conserve que s'il prouve son utilité."""
    from datetime import datetime, timedelta, timezone

    from db.models import (
        Cheval, Course, Participation, PredictionSnapshot, Resultat,
    )

    rng = np.random.default_rng(3)
    depart0 = datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc)
    n_courses, n_partants = 300, 8

    for c in range(n_courses):
        cid = f"R1C{c:04d}"
        depart = depart0 + timedelta(hours=c)
        db.add(Course(course_id=cid, reunion_id="R1", numero=c + 1, nom="T",
                      date_heure=depart, hippodrome_nom="Pau", discipline="Plat",
                      distance=2000, nb_partants=n_partants, statut="termine",
                      terrain_officiel="Bon"))
        force = rng.random(n_partants)
        arrivee = list(np.argsort(-force) + 1)
        db.add(Resultat(course_id=cid, classement=[
            {"numero": int(num), "position": pos + 1}
            for pos, num in enumerate(arrivee)]))
        for i in range(n_partants):
            pid = f"{cid}-{i}"
            db.add(Cheval(cheval_id=pid, nom=f"H{i}"))
            db.add(Participation(participation_id=pid, course_id=cid,
                                 cheval_id=pid, numero=i + 1,
                                 cote_pmu=float(2 + 4 * (1 - force[i])),
                                 non_partant=False))
            db.add(PredictionSnapshot(
                snapshot_id=f"s-{pid}", prediction_run_id=f"run-{cid}",
                prediction_id=f"p-{pid}", participation_id=pid, course_id=cid,
                features={"cote_pmu": float(2 + 4 * (1 - force[i])),
                          "rang_cote": int(np.argsort(-force).tolist().index(i)) + 1,
                          "jours_repos": 20 + i, "elo_vs_moyenne": float(force[i] * 100),
                          "forme_5_courses": float(force[i]), "spi_score": 0.0},
                features_hash=f"h-{pid}", feature_schema_hash="sc",
                proba_top1=float(force[i] / force.sum()),
                proba_top3=float(min(0.9, force[i])),
                proba_top1_raw=float(force[i] / force.sum()),
                proba_top3_raw=float(min(0.9, force[i])),
                rang_predit=i + 1, observed_at=depart - timedelta(minutes=30),
                course_start_at=depart, is_pre_course=True, origin="live",
                is_replayable=True,
            ))
    await db.commit()

    apprenant = ml.MetaLearner()
    out = await apprenant.train(db)

    assert out["status"] in ("ok", "rejected_not_useful"), out
    assert out["n_samples"] == n_courses * n_partants, (
        "une ligne par PARTANT, pas une par course")
    assert out["n_courses"] == n_courses
    assert 0.30 < out["pos_rate"] < 0.45, (
        f"taux de base par partant ≈ 3/8, jamais 0,617 par course : {out['pos_rate']}")
    assert out["logloss_sans_correction"] is not None, (
        "le gate doit toujours pouvoir comparer à l'absence de correction")
    # Le gate décide seul : le modèle n'est conservé QUE s'il a prouvé son utilité.
    assert apprenant.is_trained is (out["status"] == "ok")


@pytest.mark.asyncio
async def test_cold_start_le_correcteur_reste_inactif(db):
    """Sans données, aucun correcteur : la chaîne applique l'identité."""
    apprenant = ml.MetaLearner()
    out = await apprenant.train(db)
    assert out["status"] == "insufficient_data"
    assert apprenant.is_trained is False
    assert apprenant.predict_correction(0.42, {}) == pytest.approx(0.42)


# ── Contrat d'entraînement : un modèle d'un autre monde ne se sert pas ──────

def test_un_pickle_entraine_sous_un_autre_contrat_est_neutralise(tmp_path):
    """Sans cette garde, déployer la correction n'aurait rien changé : le pickle
    resté sur disque (entraîné par COURSE, avec un autre label et six features
    constantes) est rechargé au démarrage de l'API et aurait continué à corriger
    exactement comme avant — indéfiniment si le gate d'utilité rejette les
    nouveaux modèles."""
    import pickle

    ancien = ml.MetaLearner()
    ancien._model = _Correcteur([0.5])
    ancien._contract = "course/top3_du_gagnant/v0"
    chemin = tmp_path / "meta_learner.pkl"
    with open(chemin, "wb") as f:
        pickle.dump(ancien, f)

    charge = ml.MetaLearner.load(chemin)
    assert charge.is_trained is False, "un autre contrat = pas servi"
    assert charge._metrics["status"] == "contrat_perime"
    assert charge.predict_correction(0.42, {}) == pytest.approx(0.42)


def test_un_pickle_sans_contrat_du_tout_est_neutralise(tmp_path):
    """Les pickles écrits avant l'introduction du contrat n'ont pas l'attribut."""
    import pickle

    vieux = ml.MetaLearner()
    vieux._model = _Correcteur([0.5])
    del vieux._contract          # tel qu'un pickle d'avant la garde le restitue
    chemin = tmp_path / "meta_learner.pkl"
    with open(chemin, "wb") as f:
        pickle.dump(vieux, f)
    assert ml.MetaLearner.load(chemin).is_trained is False


def test_un_pickle_du_bon_contrat_est_bien_servi(tmp_path):
    import pickle

    bon = ml.MetaLearner()
    bon._model = _Correcteur([0.5])
    bon._contract = ml.TRAINING_CONTRACT
    chemin = tmp_path / "meta_learner.pkl"
    with open(chemin, "wb") as f:
        pickle.dump(bon, f)
    assert ml.MetaLearner.load(chemin).is_trained is True


def test_le_rejet_efface_le_modele_precedent():
    """Un rejet doit survivre au redémarrage : sinon la prochaine API recharge le
    pickle et réapplique une correction que la mesure vient de refuser."""
    import inspect
    from services import jobs
    src = inspect.getsource(jobs.job_meta_learner_retrain)
    assert "rejected_not_useful" in src
    assert "META_LEARNER_PATH.unlink" in src
