"""20 features sur 211 à variance nulle : ce qui est réparé, et ce qui ne l'est pas.

L'alerte `features_mortes` répétait chaque heure le même compte, sans distinguer les
trois cas qui s'y mélangeaient :

  1. une feature morte PAR BUG de notre côté — `career_momentum`, qui valait
     exactement 0,0 pour tous les partants de toutes les courses parce que le
     chargeur ELO gardait dix deltas là où la feature en demande douze ;
  2. une feature morte par ABSENCE DE SOURCE — les quatre « commentaire de course »
     et les trois taux de dynamique, vérifiés contre l'API PMU le 2026-08-31 ;
  3. une feature morte pour une raison que PERSONNE n'a établie — le seul cas qui
     mérite de réveiller quelqu'un.

Et une affirmation de l'alerte, « le modèle les apprend comme du bruit », qui ne doit
plus être vraie : l'entraînement écarte désormais les colonnes constantes.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import text

from ml import feature_health as fh
from services import data_quality as dq


# ── 1. L'entraînement n'apprend plus une colonne constante ────────────────────

def _jeu(n=300, colonnes_mortes=("commentaire_signal", "dyn_finit_fort")):
    rng = np.random.default_rng(42)
    X = pd.DataFrame(rng.standard_normal((n, 12)),
                     columns=[f"feat_{i}" for i in range(12)])
    for c in colonnes_mortes:
        X[c] = 0.0                      # constante : exactement le cas de production
    X["course_id"] = [f"course_{i // 10:03d}" for i in range(n)]
    y = pd.Series((rng.random(n) < 0.30).astype(int))
    return X, y


def test_une_colonne_constante_n_entre_pas_dans_le_modele(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # catboost_info/ (cf. test_ml_units)
    from ml.models import BlackTurfEnsemble

    X, y = _jeu()
    modele = BlackTurfEnsemble()
    modele.train(X, y)

    assert set(modele.constant_features) == {"commentaire_signal", "dyn_finit_fort"}
    assert "commentaire_signal" not in modele.feature_names
    assert "dyn_finit_fort" not in modele.feature_names
    # Les vivantes, elles, sont toutes là : on écarte le mort, pas le vecteur.
    assert all(f"feat_{i}" in modele.feature_names for i in range(12))


def test_le_modele_predit_encore_quand_la_colonne_morte_est_presente(tmp_path, monkeypatch):
    """L'inférence continue de FOURNIR la colonne : le vecteur servi ne change pas,
    c'est le modèle qui ne la regarde plus. Sans ça, on aurait un écart train/serve."""
    monkeypatch.chdir(tmp_path)
    from ml.models import BlackTurfEnsemble

    X, y = _jeu()
    modele = BlackTurfEnsemble()
    modele.train(X, y)
    probas = modele.predict_proba(X.head(10))
    assert len(probas) == 10 and all(0.0 <= float(p) <= 1.0 for p in probas)


def test_sans_colonne_constante_rien_n_est_ecarte(tmp_path, monkeypatch):
    """Le garde-fou ne doit pas se mettre à couper des features vivantes."""
    monkeypatch.chdir(tmp_path)
    from ml.models import BlackTurfEnsemble

    X, y = _jeu(colonnes_mortes=())
    modele = BlackTurfEnsemble()
    modele.train(X, y)
    assert modele.constant_features == []


# ── 2. Le registre des causes établies ────────────────────────────────────────

def test_le_registre_separe_ce_qui_est_explique_de_ce_qui_ne_l_est_pas():
    out = fh.classer_mortes([
        "commentaire_signal", "dyn_finit_fort",      # cause établie
        "career_momentum", "draw_bias_score",        # personne n'a établi la cause
    ])
    assert out["documentees"] == ["commentaire_signal", "dyn_finit_fort"]
    assert out["inexpliquees"] == ["career_momentum", "draw_bias_score"]
    # La cause dit OÙ la donnée manque, pas seulement qu'elle manque : le
    # commentaire est absent de /performances-detaillees, pas de l'API entière.
    assert "performances-detaillees" in out["raisons"]["commentaire_signal"]


def test_une_source_eteinte_expres_n_est_pas_une_feature_inexpliquee():
    """Couper une source est une DÉCISION ; la supervision ne doit pas la répéter.

    `couverture_sources` le savait déjà pour les cotes (`silent_disabled`) et la
    santé des features l'ignorait : huit features remontaient chaque heure comme
    « mortes sans cause établie » alors que leur source était dans
    `SCRAPER_DISABLED_SOURCES`.
    """
    mortes = ["running_style_code", "steam_move_betclic", "career_momentum"]
    out = fh.classer_mortes(mortes, sources_desactivees={"france_galop", "betclic"})
    assert out["inexpliquees"] == ["career_momentum"]
    assert "france_galop" in out["raisons"]["running_style_code"]


def test_rallumer_la_source_remet_la_feature_dans_l_inexplique():
    """Le contraire d'une liste figée : la cause se dément toute seule.

    C'est la propriété qui distingue « nommer la source » de « inscrire un nom dans
    un registre » — sans elle, rallumer france_galop laisserait ses features
    silencieusement exemptées d'alerte pour toujours.
    """
    out = fh.classer_mortes(["running_style_code"], sources_desactivees=set())
    assert out["inexpliquees"] == ["running_style_code"]
    assert out["documentees"] == []


def test_le_registre_signale_ses_propres_entrees_perimees():
    """« Cette donnée n'existe pas à la source » cesse d'être vrai le jour où la
    source revient. Une liste d'exceptions qu'on ne vérifie jamais devient un angle
    mort permanent — c'est exactement ce qu'on vient de corriger ailleurs."""
    toutes = list(fh.SANS_SOURCE)
    assert fh.registre_perime(toutes) == []          # tout est encore mort : RAS
    ressuscitee = toutes[0]
    assert fh.registre_perime(toutes[1:]) == [ressuscitee]


# ── 3. L'alerte ne remonte plus que l'inexpliqué ──────────────────────────────

async def _table(db):
    await db.execute(text("""
        CREATE TABLE IF NOT EXISTS feature_health (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL)
    """))


async def _snapshot(db, *, mortes, n_features=211, quand="2026-09-03 02:00:00"):
    await db.execute(
        text("INSERT INTO feature_health (data, created_at) VALUES (:d, :t)"),
        {"d": json.dumps({"dead": list(mortes), "n_features": n_features,
                          "n_dead": len(mortes), "n_rows": 30000}), "t": quand})


@pytest.mark.asyncio
async def test_les_mortes_documentees_ne_declenchent_plus_l_alerte(db):
    """Sept features dont la cause est vérifiée depuis le 2026-08-31 : les répéter
    93 fois n'a jamais rien appris à personne, et noyait le reste."""
    await _table(db)
    await _snapshot(db, mortes=list(fh.SANS_SOURCE))
    await db.commit()

    out = await dq.sante_features(db)
    assert out["n_mortes"] == len(fh.SANS_SOURCE)          # le total reste dit
    assert out["n_mortes_inexpliquees"] == 0               # mais rien à signaler
    assert out["n_mortes_inexpliquees"] < dq.SEUIL_FEATURES_MORTES


@pytest.mark.asyncio
async def test_l_alerte_nomme_les_features_dont_personne_n_a_la_cause(db):
    await _table(db)
    inconnues = [f"mystere_{i:02d}" for i in range(dq.SEUIL_FEATURES_MORTES)]
    await _snapshot(db, mortes=list(fh.SANS_SOURCE) + inconnues)
    await db.commit()

    out = await dq.sante_features(db)
    assert out["n_mortes_inexpliquees"] == dq.SEUIL_FEATURES_MORTES
    assert out["mortes_inexpliquees"][0] == "mystere_00"
    assert out["n_mortes_documentees"] == len(fh.SANS_SOURCE)


@pytest.mark.asyncio
async def test_une_entree_du_registre_qui_revit_est_signalee(db):
    await _table(db)
    survivante = sorted(fh.SANS_SOURCE)[0]
    await _snapshot(db, mortes=[f for f in fh.SANS_SOURCE if f != survivante])
    await db.commit()

    out = await dq.sante_features(db)
    assert out["registre_perime"] == [survivante]


@pytest.mark.asyncio
async def test_une_source_qui_tombe_alerte_toujours(db):
    """Le registre ne doit rien émousser : une feature qui MEURT reste un critical."""
    await _table(db)
    await _snapshot(db, mortes=["a"], quand="2026-09-02 02:00:00")
    await _snapshot(db, mortes=["a", "b", "c", "d", "e", "f"], quand="2026-09-03 02:00:00")
    await db.commit()

    out = await dq.sante_features(db)
    assert out["n_nouvelles_mortes"] >= dq.SEUIL_HAUSSE_FEATURES_MORTES


# ── 4. Une feature qui NAÎT n'est pas une feature qui MEURT ───────────────────

def _echantillon(n_recent, n_ancien, *, clefs_recentes=(), clefs_toujours=(),
                 clefs_mortes=()):
    """Vecteurs de features du PLUS RÉCENT au plus ancien, comme la requête les rend."""
    import random
    rng = random.Random(3)
    lignes = []
    for i in range(n_recent + n_ancien):
        recent = i < n_recent
        ligne = {k: rng.random() for k in clefs_toujours}
        ligne.update({k: 0.0 for k in clefs_mortes})
        if recent:
            ligne.update({k: rng.random() for k in clefs_recentes})
        lignes.append(ligne)
    return lignes


def test_une_feature_ajoutee_hier_n_est_pas_declaree_morte():
    """`presse_rang_moyen`, `presse_score_borda` et `presse_nb_sources` ont été
    ajoutées le 2026-09-01 — trois jours avant l'alerte, et le compte de features est
    passé de 208 à 211 dans le même temps. Absentes de 95 % d'une fenêtre de 45 jours,
    elles étaient comptées mortes le jour même de leur naissance."""
    data = _echantillon(3000, 9000, clefs_recentes=["presse_rang_moyen"],
                        clefs_toujours=["cote_pmu", "elo_global"])
    out = fh.analyser_features(data)
    assert "presse_rang_moyen" not in out["dead"]
    assert out["nouvelles"] == ["presse_rang_moyen"]


def test_une_feature_reellement_morte_reste_morte():
    data = _echantillon(3000, 9000, clefs_toujours=["cote_pmu"],
                        clefs_mortes=["commentaire_signal"])
    out = fh.analyser_features(data)
    assert "commentaire_signal" in out["dead"]
    assert out["nouvelles"] == []


def test_une_feature_qui_vient_de_mourir_est_bien_vue():
    """Le cas qui compte : vivante hier, constante depuis. C'est la signature d'une
    source qui tombe, et le verdict porte sur la tranche récente pour l'attraper."""
    data = _echantillon(3000, 9000, clefs_toujours=["cote_pmu"])
    for i, ligne in enumerate(data):
        ligne["taux_en_tete"] = 0.0 if i < 3000 else (i % 7) / 10.0
    out = fh.analyser_features(data)
    assert "taux_en_tete" in out["dead"]


def test_le_verdict_ne_juge_pas_sur_une_poignee_de_lignes():
    """Plancher de la tranche récente : sous ce volume, une feature rare passerait
    pour morte par le seul effet du hasard."""
    data = _echantillon(50, 9000, clefs_toujours=["cote_pmu"])
    out = fh.analyser_features(data)
    assert out["n_rows_recent"] >= fh.MIN_LIGNES_RECENTES


def test_les_statistiques_de_la_fenetre_entiere_restent_publiees():
    """Le verdict change, la mesure ne se perd pas : les instantanés déjà en base et
    les lectures existantes gardent `null_rate` et `var` sur la fenêtre complète."""
    data = _echantillon(3000, 9000, clefs_recentes=["presse_rang_moyen"],
                        clefs_toujours=["cote_pmu"])
    stats = fh.analyser_features(data)["stats"]["presse_rang_moyen"]
    assert stats["null_rate"] > 0.5              # absente de la majorité de la fenêtre
    assert stats["null_rate_recent"] == 0.0      # mais servie aujourd'hui
    assert stats["nouvelle"] is True and stats["dead"] is False
