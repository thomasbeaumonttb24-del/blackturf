"""Invariants de la FENÊTRE d'entraînement.

La fenêtre est glissante : chaque nuit elle perd un jour ancien et gagne un jour
récent. Tant qu'elle valait trois mois, elle perdait plus qu'elle ne gagnait et
le dataset d'entraînement RÉTRÉCISSAIT d'une version à l'autre (42 285 partants
le 17/08/2026, 41 121 le 25/08) alors que la base en contenait 175 718
exploitables sur douze mois. Rien ne le signalait : le retrain réussissait, le
modèle se déployait, seul le compteur de l'admin baissait.

On verrouille ici les trois propriétés qui rendent ça impossible :
  1. élargir la fenêtre ne peut pas réduire le dataset ;
  2. le plafond mémoire garde les partants les PLUS RÉCENTS (il fait stagner le
     compteur, jamais décroître) ;
  3. le défaut de configuration couvre un cycle saisonnier complet.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text


async def _semer(db, n_courses: int, base: datetime) -> None:
    """n_courses courses terminées d'un partant chacune, un jour d'écart.

    Insertion par l'ORM et non en SQL brut : les colonnes non nulles de `courses`
    tiennent leur valeur d'un `default=` Python, invisible côté SQLite.
    """
    from db.models import Course, Participation, HistoriqueCourse, FeatureML

    for i in range(n_courses):
        cid = f"C{i:04d}"
        pid = f"P{i:04d}"
        quand = base - timedelta(days=i)
        db.add(Course(
            course_id=cid, reunion_id="R1", numero=1, date_heure=quand,
            hippodrome_nom="Vincennes", discipline="Attelé", distance=2700,
            nb_partants=1, statut="termine",
        ))
        db.add(Participation(
            participation_id=pid, course_id=cid, cheval_id=f"H{i:04d}", numero=1,
        ))
        db.add(HistoriqueCourse(
            historique_id=f"X{i:04d}", cheval_id=f"H{i:04d}", course_id=cid,
            date_course=quand.date(), hippodrome="Vincennes",
            discipline="Attelé", distance=2700, position_arrivee=(i % 5) + 1,
        ))
        db.add(FeatureML(
            participation_id=pid,
            features={"cote_pmu": 3.0 + i, "nb_partants": 1},
            # `computed_at` STRICTEMENT avant le départ : le flag
            # train_prerace_only écarte tout ce qui a été calculé après (les
            # features backfillées fuiraient l'arrivée).
            computed_at=quand - timedelta(hours=2),
        ))
    await db.commit()


@pytest.mark.asyncio
async def test_elargir_la_fenetre_ne_peut_pas_reduire_le_dataset(db):
    from ml.pipeline import _build_training_dataset_from_db

    await _semer(db, 90, datetime.now() - timedelta(hours=1))

    X_court, _, _ = await _build_training_dataset_from_db(db, mois=1)
    X_long, _, _ = await _build_training_dataset_from_db(db, mois=12)

    assert len(X_court) < len(X_long), (
        "une fenêtre plus longue doit voir strictement plus de partants ; "
        f"1 mois={len(X_court)}, 12 mois={len(X_long)}"
    )
    assert len(X_long) == 90


@pytest.mark.asyncio
async def test_identifiants_pris_sur_les_colonnes_et_ordre_chronologique(db):
    """`course_id` pilote le découpage par groupe et `X` est supposé trié.

    Les features JSON ne portent NI l'un NI l'autre ici : si le builder se fiait
    au JSON, `temporal_holdout_mask` découperait sur une colonne absente et le
    hold-out temporel deviendrait un hold-out aléatoire — fuite silencieuse.
    """
    from ml.pipeline import _build_training_dataset_from_db

    await _semer(db, 10, datetime.now() - timedelta(hours=1))
    X, y3, y1 = await _build_training_dataset_from_db(db, mois=12)

    assert "course_id" in X.columns and X["course_id"].notna().all()
    assert "cheval_id" in X.columns and X["cheval_id"].notna().all()
    # Semé à un jour d'écart DÉCROISSANT : le plus ancien (C0009) sort en premier.
    assert list(X["course_id"]) == sorted(X["course_id"], reverse=True)
    assert len(y3) == len(y1) == len(X)
    # position = (i % 5) + 1 → 1er pour i ∈ {0,5}, top-3 pour position ≤ 3.
    assert y1.sum() == 2
    assert y3.sum() == 6


@pytest.mark.asyncio
async def test_le_plafond_memoire_garde_les_partants_les_plus_recents(db):
    """Un plafond doit rogner l'ANCIEN, jamais le récent.

    Rogner le récent reviendrait à réintroduire exactement le défaut qu'on
    corrige : un modèle qui n'a pas vu les dernières semaines.
    """
    from ml.pipeline import _build_training_dataset_from_db

    base = datetime.now() - timedelta(hours=1)
    await _semer(db, 40, base)

    X, _, _ = await _build_training_dataset_from_db(db, mois=12, max_rows=10)

    assert len(X) <= 10, f"plafond ignoré : {len(X)} lignes"
    gardees = set(X["course_id"])
    # C0000 est la plus RÉCENTE (jour J), C0039 la plus ancienne.
    assert "C0000" in gardees
    assert "C0039" not in gardees


def test_la_fenetre_par_defaut_couvre_un_cycle_saisonnier():
    """Trois mois d'été n'ont jamais montré au modèle un terrain lourd d'hiver.

    Au-delà de la décroissance du compteur, une fenêtre courteampute la
    saisonnalité : le modèle d'août n'a vu que des terrains d'été.
    """
    from api.config import Settings

    s = Settings()
    assert s.retrain_history_months >= 12, (
        "la fenêtre par défaut est retombée sous douze mois — le dataset "
        "recommencerait à rétrécir d'une version à l'autre"
    )
    assert s.retrain_max_rows >= 175_000, (
        "le plafond mémoire est descendu sous le volume réellement disponible : "
        "il rognerait de l'historique au lieu de servir de garde-fou"
    )


@pytest.mark.asyncio
async def test_un_partant_ne_peut_pas_avoir_deux_lignes_d_historique(db):
    """UN PARTANT, UNE LIGNE D'ENTRAÎNEMENT — garanti par le schéma, pas par un
    filtre à la lecture.

    `_save_historical_course` faisait un `on_conflict_do_nothing` SANS cible : la
    clé primaire étant un uuid neuf à chaque exécution, il n'y avait jamais de
    conflit et les re-scrapes empilaient jusqu'à dix copies du même partant. Le jeu
    d'entraînement se joint sur (cheval_id, course_id) : chaque copie y devenait une
    ligne d'apprentissage supplémentaire, features et label identiques, poids
    multiplié d'autant.

    La migration 0012 a dédoublonné et posé un index unique partiel. Il n'était PAS
    déclaré dans le modèle : `Base.metadata.create_all` — donc toute cette suite de
    tests et l'environnement de développement — tournait sans la garde qui protège
    la production. Ce test verrouille sa déclaration.
    """
    from sqlalchemy.exc import IntegrityError

    from db.models import HistoriqueCourse

    base = datetime.now() - timedelta(hours=1)
    await _semer(db, 3, base)

    db.add(HistoriqueCourse(
        historique_id="DOUBLON", cheval_id="H0000", course_id="C0000",
        date_course=base.date(), hippodrome="Vincennes", discipline="Attelé",
        distance=2700, position_arrivee=1,
    ))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


@pytest.mark.asyncio
async def test_les_courses_externes_echappent_a_l_unicite(db):
    """L'index est PARTIEL, comme en base : une course externe n'a pas
    d'identifiant PMU (`course_id` nul), on ne peut pas la dédoublonner sur cette
    clé — et la jointure d'entraînement ne l'atteint jamais."""
    from db.models import HistoriqueCourse

    for i in range(2):
        db.add(HistoriqueCourse(
            historique_id=f"EXT{i}", cheval_id="H9999", course_id=None,
            date_course=(datetime.now() - timedelta(days=30)).date(),
            hippodrome="Baden-Baden", discipline="Plat", distance=2000,
            position_arrivee=i + 1,
        ))
    await db.commit()          # aucune erreur : elles sont hors index partiel

    from ml.pipeline import _build_training_dataset_from_db
    X, _, _ = await _build_training_dataset_from_db(db, mois=12)
    assert "H9999" not in set(X["cheval_id"]) if len(X) else True, (
        "une course externe n'entre jamais dans le jeu d'entraînement")


@pytest.mark.asyncio
async def test_le_plafond_memoire_compte_des_partants(db):
    """Le plafond borne la MÉMOIRE : il compte les lignes réellement produites."""
    from ml.pipeline import _build_training_dataset_from_db

    base = datetime.now() - timedelta(hours=1)
    await _semer(db, 20, base)
    await db.commit()

    X, _, _ = await _build_training_dataset_from_db(db, mois=12, max_rows=10)
    assert len(X) <= 10
    assert "C0000" in set(X["course_id"]), "le plus récent est toujours gardé"
    assert X["course_id"].is_unique
