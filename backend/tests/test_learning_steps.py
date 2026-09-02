"""Un apprentissage qui ne tourne pas doit finir par se voir.

Onze apprentissages s'enchaînent dans un SEUL job RQ, derrière le retrain nocturne,
et aucun n'a d'entrée propre dans `services/jobs.py`. Deux angles morts, tous deux
vécus :

  - le worker s'est fait OOM-killer le 20/08/2026 à 02:04, quatre-vingt-treize
    secondes APRÈS avoir déployé v511 : aucun des onze n'a tourné cette nuit-là,
    et le rapport du matin annonçait une nuit réussie ;
  - chaque étape était enveloppée d'un `try/except` qui journalisait un `warning` :
    une étape pouvait échouer toutes les nuits pendant des semaines sans que rien
    ne le signale, sa calibration restant figée sur une courbe périmée.

Règle appliquée, la même que partout ailleurs dans ce système : l'ÉTAT PERSISTANT
fait foi contre les logs.
"""
from datetime import datetime, timedelta, timezone

import pytest

from ml import learning_steps as ls


def _factory(db):
    """Fabrique de session qui rend TOUJOURS la session de test.

    `etape` ouvre volontairement une session PROPRE pour écrire son journal : si
    l'étape a empoisonné sa transaction, l'écriture échouerait avec elle et la
    panne redeviendrait muette au pire moment.
    """
    class _Ctx:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_a):
            return False

    return lambda: _Ctx()


@pytest.mark.asyncio
async def test_une_etape_reussie_pose_une_date_de_succes(db):
    async with ls.etape(_factory(db), "isotone_top3"):
        pass
    etat = await ls.etat_apprentissages(db)
    assert [e["step"] for e in etat["etapes"]] == ["isotone_top3"]
    assert etat["etapes"][0]["last_status"] == "ok"
    assert etat["etapes"][0]["last_success_at"] is not None
    assert etat["perimees"] == []


@pytest.mark.asyncio
async def test_une_etape_en_echec_n_interrompt_pas_la_nuit(db):
    """Comportement des try/except d'origine, conservé : les dix suivantes doivent
    quand même s'exécuter."""
    executee = []
    async with ls.etape(_factory(db), "poids_profils"):
        raise RuntimeError("base indisponible")
    async with ls.etape(_factory(db), "clv_monitor"):
        executee.append("clv")
    assert executee == ["clv"], "l'étape suivante doit tourner malgré l'échec"


@pytest.mark.asyncio
async def test_un_echec_conserve_la_date_du_dernier_succes(db):
    """C'est cet ÉCART qui rend la panne visible : sans lui, un échec effacerait la
    preuve qu'un succès a eu lieu un jour."""
    async with ls.etape(_factory(db), "edge_monitor"):
        pass
    etat = await ls.etat_apprentissages(db)
    succes = etat["etapes"][0]["last_success_at"]

    async with ls.etape(_factory(db), "edge_monitor"):
        raise ValueError("colonne absente")

    etat = await ls.etat_apprentissages(db)
    ligne = etat["etapes"][0]
    assert ligne["last_status"] == "echec"
    assert "ValueError" in ligne["last_error"]
    assert ligne["last_success_at"] == succes, (
        "la date du dernier succès ne recule pas et ne s'efface pas")


@pytest.mark.asyncio
async def test_une_etape_sans_succes_depuis_deux_jours_est_perimee(db):
    await ls.enregistrer_etape(db, "calibration_cote", statut="ok")
    await db.execute(
        __import__("sqlalchemy").text(
            "UPDATE learning_step_runs SET last_success_at = :vieux "
            "WHERE step = 'calibration_cote'"),
        {"vieux": datetime.now(timezone.utc) - timedelta(hours=72)})
    await db.commit()

    perimees = await ls.etapes_perimees(db)
    assert [e["step"] for e in perimees] == ["calibration_cote"]


@pytest.mark.asyncio
async def test_une_etape_qui_n_a_jamais_reussi_est_perimee(db):
    """Le cas d'une étape cassée depuis son installation — exactement ce qu'on
    veut voir, et que le seul `warning` masquait."""
    async with ls.etape(_factory(db), "temperature"):
        raise RuntimeError("jamais passée")
    perimees = await ls.etapes_perimees(db)
    assert [e["step"] for e in perimees] == ["temperature"]


@pytest.mark.asyncio
async def test_une_etape_recente_n_est_pas_perimee(db):
    async with ls.etape(_factory(db), "gates_segments"):
        pass
    assert await ls.etapes_perimees(db) == []


@pytest.mark.asyncio
async def test_le_nombre_d_observations_est_conserve(db):
    async with ls.etape(_factory(db), "poids_profils") as e:
        e.n_obs = 4231
    etat = await ls.etat_apprentissages(db)
    assert etat["etapes"][0]["n_obs"] == 4231


@pytest.mark.asyncio
async def test_une_interruption_traverse_toujours(db):
    """On avale les `Exception`, jamais une `BaseException` : un arrêt propre du
    worker ne doit pas se transformer en nuit fantôme qui continue de tourner."""
    with pytest.raises(KeyboardInterrupt):
        async with ls.etape(_factory(db), "retrain"):
            raise KeyboardInterrupt


# ── Câblage de la nuit ─────────────────────────────────────────────────────

def test_chaque_apprentissage_nocturne_est_journalise():
    import inspect
    from ml import pipeline

    src = inspect.getsource(pipeline._run_nightly_retraining_unlocked)
    attendues = {
        "retrain", "calibration_longshots", "isotone_top1", "isotone_top3",
        "temperature", "calibration_cote", "rattrapage_runs_profils",
        "rattrapage_plans", "gates_segments", "performance_signaux",
        "performance_bandes_ev", "poids_profils", "calibration_rapports",
        "edge_monitor", "sante_features", "clv_monitor", "poids_appris_types",
        "integrite_pmu",
    }
    for nom in attendues:
        assert f'etape(AsyncSessionLocal, "{nom}")' in src, nom


def test_la_memoire_est_rendue_avant_les_deux_gouffres():
    """`compute_signal_performance` et `compute_edge_monitor` lisent `features_ml`
    en entier : ce sont eux qui tournaient quand l'OOM killer a choisi sa victime."""
    import inspect
    from ml import pipeline

    src = inspect.getsource(pipeline._run_nightly_retraining_unlocked)
    i_release = src.index("nightly.avant_agregats_lourds")
    i_signal = src.index('etape(AsyncSessionLocal, "performance_signaux")')
    assert i_release < i_signal


def test_le_rapport_du_matin_expose_les_apprentissages():
    import inspect
    from scripts import check_retrain_nightly as rapport

    assert "_bloc_apprentissages" in inspect.getsource(rapport._html)
    assert "etat_apprentissages" in inspect.getsource(rapport.main)


def test_le_rapport_signale_les_etapes_perimees():
    from scripts.check_retrain_nightly import _bloc_apprentissages

    etat = {
        "etapes": [
            {"step": "isotone_top3", "last_success_at": None,
             "last_status": "echec", "last_error": "boom", "n_obs": None},
            {"step": "clv_monitor",
             "last_success_at": datetime(2026, 9, 1, 3, 0, tzinfo=timezone.utc),
             "last_status": "ok", "last_error": None, "n_obs": 12},
        ],
        "perimees": [{"step": "isotone_top3"}],
        "seuil_heures": 48,
    }
    html = _bloc_apprentissages(etat)
    assert "isotone_top3" in html
    assert "PÉRIMÉ" in html
    assert "1 apprentissage(s) sans succès" in html
    assert "01/09 03:00" in html


def test_le_rapport_reste_lisible_sans_journal():
    from scripts.check_retrain_nightly import _bloc_apprentissages

    html = _bloc_apprentissages({})
    assert "Aucune étape journalisée" in html


def test_les_horodatages_portent_leur_fuseau_dans_le_schema():
    """asyncpg REFUSE de lier un datetime conscient du fuseau à une colonne
    `TIMESTAMP` sans fuseau : « invalid input for query argument ».

    SQLite l'accepte sans broncher — le défaut ne se voit donc QU'EN PRODUCTION,
    où il rendait ce journal muet : `etapes_perimees` renvoyait une liste vide et
    aucune étape ne s'écrivait. C'est exactement la panne silencieuse que ce
    module existe pour rendre visible, et elle se serait cachée dans son propre
    angle mort. Constaté en prod le 02/09/2026, quelques minutes après le
    déploiement.

    Aucun test sur SQLite ne peut reproduire ça : on verrouille donc le SCHÉMA.
    """
    from ml.learning_steps import _DDL

    assert "TIMESTAMPTZ" in _DDL
    assert "last_attempt_at  TIMESTAMPTZ" in _DDL
    assert "last_success_at  TIMESTAMPTZ" in _DDL


def test_les_horodatages_ecrits_portent_bien_un_fuseau():
    """L'autre moitié de l'invariant : si le code se mettait à écrire des dates
    naïves, la colonne TIMESTAMPTZ les interpréterait dans le fuseau du serveur —
    et une étape passerait pour périmée, ou pour fraîche, selon l'heure."""
    from ml.learning_steps import _maintenant

    assert _maintenant().tzinfo is not None
