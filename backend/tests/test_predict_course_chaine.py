"""La chaîne de prédiction, exécutée POUR DE VRAI.

`predict_course` porte l'ordre des calibrations, la normalisation par course, le
modèle de victoire, le blend marché et le classement affiché — soit tout ce qui
décide des probabilités servies. Aucun test ne l'EXÉCUTAIT : les garde-fous
existants lisent son code SOURCE, ce qui prouve l'ordre des appels mais pas qu'ils
produisent un résultat cohérent.

Ce module la fait tourner de bout en bout, sur une vraie base et un vrai modèle
entraîné, et vérifie les invariants qui ne se voient pas dans le source :

  - les probabilités restent des probabilités ;
  - la somme des probas de victoire vaut 1 par course, celle des placés vaut 3 ;
  - le classement affiché suit bien la proba servie ;
  - la proba BRUTE persistée est la sortie du modèle AVANT toute calibration —
    c'est elle que les fits de la nuit relisent, et la boucle se refermerait si
    elle portait déjà une correction ;
  - le blend marché est bien la DERNIÈRE étape.

BORNE DU TEST — le calcul des features est remplacé par une liste réaliste.
`_load_course_batch_data` emploie du SQL PostgreSQL que SQLite refuse ; le
reproduire ici reviendrait à tester le moteur de base plutôt que la chaîne. Ce
n'est pas la partie modifiée, et elle a ses propres tests.
"""
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import text

from db.models import Cheval, Course, Entraineur, Jockey, Participation

DEPART = datetime.now(timezone.utc) + timedelta(hours=3)
N_PARTANTS = 10


class _Factory:
    """Fabrique de session qui rend TOUJOURS la session de test.

    `predict_course` ouvre sa propre session via `AsyncSessionLocal`, qui pointe
    sur une base SQLite EN MÉMOIRE — donc une base différente, et vide, à chaque
    connexion. C'est ce détail qui a laissé cette fonction sans aucune exécution
    en test.
    """

    def __init__(self, db):
        self._db = db

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *_a):
        return False


async def _semer_course(db, course_id):
    db.add(Course(course_id=course_id, reunion_id="R1", numero=1, nom="Prix du test",
                  date_heure=DEPART, hippodrome_nom="Vincennes", discipline="Attelé",
                  distance=2700, nb_partants=N_PARTANTS, statut="a_venir",
                  terrain_officiel="Bon"))
    db.add(Jockey(jockey_id=f"J-{course_id}", nom="Jockey Un"))
    db.add(Entraineur(entraineur_id=f"E-{course_id}", nom="Entraineur Un"))
    for i in range(N_PARTANTS):
        db.add(Cheval(cheval_id=f"H-{course_id}-{i}", nom=f"Cheval {i}",
                      elo_score_global=1500 + i * 12, age=5, sexe="H"))
        db.add(Participation(
            participation_id=f"{course_id}-P{i}", course_id=course_id,
            cheval_id=f"H-{course_id}-{i}", numero=i + 1,
            cote_pmu=round(2.0 + i * 2.4, 1), jockey_id=f"J-{course_id}",
            entraineur_id=f"E-{course_id}", non_partant=False))
    await db.commit()


def _features(course_id):
    """Features réalistes : un favori net, un champ dégressif, des cotes cohérentes.

    Les clés portent les noms que le modèle attend ; `predict_proba` réindexe sur
    ses propres `feature_names`, donc une clé absente vaut 0 — même comportement
    qu'en production quand un scraper n'a rien remonté.
    """
    out = []
    for i in range(N_PARTANTS):
        cote = round(2.0 + i * 2.4, 1)
        out.append({
            "participation_id": f"{course_id}-P{i}",
            "course_id": course_id,
            "cheval_id": f"H-{course_id}-{i}",
            "numero": i + 1,
            "nom": f"Cheval {i}",
            "cote_pmu": cote,
            "prob_implicite": round(1.0 / cote, 4),
            "rang_cote": i + 1,
            "est_favori": 1 if i == 0 else 0,
            "nb_partants": N_PARTANTS,
            "elo_global": 1600.0 - i * 18,
            "forme_5_courses": round(0.85 - i * 0.06, 3),
            "jours_repos": 20 + i,
            "spi_score": 0.0,
            "elo_vs_moyenne": 60.0 - i * 12,
            "field_hhi": 0.14,
        })
    return out


def _modele_entraine(tmp_path):
    """Un vrai `BlackTurfEnsemble`, entraîné et déployé dans un dossier jetable."""
    import importlib
    import os

    os.environ["BT_MODELS_DIR"] = str(tmp_path)
    from ml import models as m
    importlib.reload(m)

    rng = np.random.RandomState(3)
    lignes, y3, yw = [], [], []
    for c in range(90):
        force = rng.randn(8)
        ordre = np.argsort(-(force + rng.randn(8) * 0.7))
        for i in range(8):
            rang = int(np.where(ordre == i)[0][0])
            cote = float(np.clip(9 - 2.5 * force[i], 1.2, 60))
            lignes.append({
                "course_id": f"c{c:03d}", "cote_pmu": cote,
                "prob_implicite": 1.0 / cote, "rang_cote": rang + 1,
                "elo_global": float(1500 + 40 * force[i]),
                "forme_5_courses": float((force[i] + 3) / 6),
                "jours_repos": 25.0, "spi_score": 0.0,
                "elo_vs_moyenne": float(40 * force[i]), "field_hhi": 0.14,
                "nb_partants": 8, "est_favori": int(rang == 0),
            })
            y3.append(int(rang < 3))
            yw.append(int(rang == 0))
    modele = m.BlackTurfEnsemble()
    modele.train(pd.DataFrame(lignes), pd.Series(y3), y_win=pd.Series(yw))
    modele.deploy(1)


async def _lancer(db, tmp_path, monkeypatch, course_id):
    """Prépare le terrain et exécute la vraie `predict_course`."""
    import importlib

    monkeypatch.chdir(tmp_path)          # catboost_info/ est écrit dans le cwd
    _modele_entraine(tmp_path)

    from ml import pipeline
    importlib.reload(pipeline)
    monkeypatch.setattr(pipeline, "AsyncSessionLocal", _Factory(db))

    async def _faux_features(_session, cid):
        return _features(cid)

    monkeypatch.setattr(pipeline, "compute_all_features_for_course", _faux_features)

    await _semer_course(db, course_id)
    return pipeline, await pipeline.predict_course(course_id, user_bankroll=100.0)


async def _servies(db, course_id):
    """Ce qui est réellement PERSISTÉ, donc ce que le produit affiche."""
    return (await db.execute(text("""
        SELECT pa.numero, pr.proba_top1, pr.proba_top3, pr.rang_predit,
               pr.proba_top1_raw, pa.cote_pmu
        FROM predictions pr
        JOIN participations pa ON pa.participation_id = pr.participation_id
        WHERE pr.course_id = :cid
    """), {"cid": course_id})).all()


@pytest.mark.asyncio
async def test_la_chaine_produit_des_probabilites_coherentes(db, tmp_path, monkeypatch):
    _, out = await _lancer(db, tmp_path, monkeypatch, "R1C1")
    assert out is not None, "la chaîne doit produire un résultat"

    rows = await _servies(db, "R1C1")
    assert len(rows) == N_PARTANTS

    p1 = [float(r[1]) for r in rows]
    p3 = [float(r[2]) for r in rows]

    # ── Ce sont des probabilités ──────────────────────────────────────────
    assert all(0.0 <= p <= 1.0 for p in p1), p1
    assert all(0.0 <= p <= 1.0 for p in p3), p3
    assert all(np.isfinite(p) for p in p1 + p3)

    # ── Les contraintes de la course ──────────────────────────────────────
    assert sum(p1) == pytest.approx(1.0, abs=1e-6), (
        "un seul gagnant : la somme des probas de victoire vaut 1")
    assert sum(p3) == pytest.approx(3.0, abs=0.05), (
        "trois places payées : la somme des probas de placé vaut 3")

    # ── Le classement affiché suit la proba servie ────────────────────────
    rangs = [int(r[3]) for r in rows]
    assert sorted(rangs) == list(range(1, N_PARTANTS + 1)), "rangs uniques et complets"
    par_rang = {int(r[3]): float(r[1]) for r in rows}
    ordonnees = [par_rang[r] for r in sorted(par_rang)]
    assert ordonnees == sorted(ordonnees, reverse=True), (
        "le rang 1 doit porter la plus forte proba de victoire")


@pytest.mark.asyncio
async def test_la_proba_brute_persistee_est_bien_celle_du_modele(db, tmp_path, monkeypatch):
    """`proba_top1_raw` / `proba_top3_raw` sont l'abscisse des courbes ajustées la
    nuit suivante. Si elles portaient déjà une correction, le fit et l'inférence
    divergeraient — c'est exactement la boucle fermée que `BT_CALIB_ON_RAW` a été
    créé pour casser."""
    _, out = await _lancer(db, tmp_path, monkeypatch, "R1C2")
    assert out is not None

    rows = (await db.execute(text(
        "SELECT proba_top1, proba_top3, proba_top1_raw, proba_top3_raw "
        "FROM predictions WHERE course_id = 'R1C2'"))).all()
    assert len(rows) == N_PARTANTS
    for _p1, _p3, p1_raw, p3_raw in rows:
        assert p1_raw is not None and p3_raw is not None, (
            "sans les brutes, toutes les calibrations nocturnes retombent sur la "
            "proba déjà calibrée — la boucle se referme")
        assert 0.0 < p1_raw < 1.0 and 0.0 < p3_raw < 1.0

    # La brute de VICTOIRE somme à 1 : sortie normalisée du modèle de victoire,
    # prise AVANT le blend marché.
    assert sum(r[2] for r in rows) == pytest.approx(1.0, abs=1e-6)


@pytest.mark.asyncio
async def test_le_blend_marche_est_bien_la_derniere_etape(db, tmp_path, monkeypatch):
    """La proba SERVIE doit être plus proche de la proba implicite de la cote que ne
    l'est la proba brute du modèle. C'est l'invariant numérique qui prouve que le
    prior extérieur s'applique APRÈS les calibrations du modèle, et pas avant."""
    _, out = await _lancer(db, tmp_path, monkeypatch, "R1C3")
    assert out is not None

    rows = (await db.execute(text("""
        SELECT pr.proba_top1, pr.proba_top1_raw, pa.cote_pmu
        FROM predictions pr
        JOIN participations pa ON pa.participation_id = pr.participation_id
        WHERE pr.course_id = 'R1C3'
    """))).all()
    implicites = np.array([1.0 / float(r[2]) for r in rows])
    implicites = implicites / implicites.sum()
    servies = np.array([float(r[0]) for r in rows])
    brutes = np.array([float(r[1]) for r in rows])

    ecart_servi = float(np.abs(servies - implicites).sum())
    ecart_brut = float(np.abs(brutes - implicites).sum())
    assert ecart_servi <= ecart_brut + 1e-9, (
        f"la proba servie doit être tirée vers le marché : {ecart_servi:.4f} "
        f"contre {ecart_brut:.4f} pour la brute")


@pytest.mark.asyncio
async def test_le_favori_du_marche_ressort_devant_le_dernier(db, tmp_path, monkeypatch):
    """Contrôle de bon sens : avec un champ dégressif net (cote 2,0 contre 23,6), la
    chaîne ne doit pas inverser l'ordre. Un test de somme à 1 passerait sur des
    probabilités uniformes ; celui-ci ne passerait pas."""
    _, out = await _lancer(db, tmp_path, monkeypatch, "R1C4")
    assert out is not None
    par_numero = {int(r[0]): float(r[1]) for r in await _servies(db, "R1C4")}
    assert par_numero[1] > par_numero[N_PARTANTS], (
        f"le favori (cote 2,0) doit devancer le tocard (cote 23,6) : "
        f"{par_numero[1]:.4f} contre {par_numero[N_PARTANTS]:.4f}")


@pytest.mark.asyncio
async def test_relancer_la_chaine_ne_duplique_pas_les_predictions(db, tmp_path, monkeypatch):
    """Un rafraîchissement de cotes rappelle `predict_course` sur la même course :
    une ligne par partant doit rester une ligne par partant."""
    pipeline, out = await _lancer(db, tmp_path, monkeypatch, "R1C5")
    assert out is not None
    assert await pipeline.predict_course("R1C5") is not None

    n = (await db.execute(text(
        "SELECT COUNT(*) FROM predictions WHERE course_id = 'R1C5'"))).scalar()
    assert n == N_PARTANTS, f"{n} lignes pour {N_PARTANTS} partants"
