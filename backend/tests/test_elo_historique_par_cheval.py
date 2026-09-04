"""Le chargeur ELO servait les premiers chevaux et laissait les autres à sec.

La requête de lot demandait :

    SELECT cheval_id, delta_elo … WHERE cheval_id = ANY(:cids)
    ORDER BY cheval_id, date_course DESC
    LIMIT 200

Un `LIMIT` GLOBAL sur un tri par cheval sert le premier cheval de l'ordre des
identifiants jusqu'à épuisement du quota, puis le deuxième, et rend zéro ligne aux
suivants. Une carrière tient couramment 40 lignes : passé le cinquième cheval, le
reste du champ n'avait plus d'historique ELO du tout — et toujours les mêmes, l'ordre
des UUID ne bougeant pas d'un cycle à l'autre.

Ce que ces chevaux-là lisaient : `delta_elo_5courses`, `velocity_elo`,
`elo_trend_30j`, `bounce_score` et `career_momentum` à 0 « neutre ». Rien ne pouvait
le signaler : les features gardaient de la variance grâce aux chevaux servis, donc
`feature_health` ne les voyait pas mourir.

`career_momentum`, lui, était mort pour de bon, et pour une raison indépendante : le
plafond par cheval valait 10 quand la feature en demande 12.
"""
from __future__ import annotations

import re

import pytest

from ml.features import ELO_DELTAS_PAR_CHEVAL, momentum_carriere
import ml.features as features


# ── Le plafond est PAR CHEVAL, et il est assez haut ───────────────────────────

def _sql_du_chargeur() -> str:
    """Le SQL du chargeur de lot, commentaires Python retirés.

    Les retirer n'est pas cosmétique : le commentaire qui explique le défaut cite la
    requête fautive, `LIMIT 200` compris. Sans ce nettoyage, le test se déclencherait
    sur sa propre documentation.
    """
    import inspect
    lignes = [l for l in inspect.getsource(features._load_course_batch_data).splitlines()
              if not l.strip().startswith("#")]
    return "\n".join(lignes)


def test_la_requete_elo_plafonne_par_cheval_et_non_globalement():
    sql = _sql_du_chargeur()
    assert "ROW_NUMBER() OVER (PARTITION BY cheval_id" in sql
    # Un `LIMIT` chiffré rendrait le plafond de nouveau global : c'est le défaut même.
    assert not re.search(r"LIMIT\s+\d+", sql), "plafond global réintroduit"


def test_le_plafond_couvre_la_fenetre_dont_le_momentum_a_besoin():
    """Douze deltas : six récents contre six précédents. Le lien entre la constante
    et la feature est la cause exacte de la variance nulle — on le verrouille."""
    assert ELO_DELTAS_PAR_CHEVAL >= 12


# ── La feature qui en dépend ──────────────────────────────────────────────────

def test_dix_deltas_ne_suffisaient_pas_et_c_etait_tout_le_defaut():
    """Avec l'ancien plafond, cet appel était le SEUL possible — et il rend 0,0.

    Autrement dit : quelle que soit la carrière du cheval, la feature valait zéro.
    """
    assert momentum_carriere([12.0, 8.0, -3.0, 5.0, 9.0, 11.0, -7.0, 2.0, 4.0, 1.0]) == 0.0


def test_un_cheval_en_progression_a_un_momentum_positif():
    # 6 dernières courses (en tête de liste) bien meilleures que les 6 d'avant :
    # (20 − (−10)) / 10 = 3,0, borné à 1,0.
    assert momentum_carriere([20.0] * 6 + [-10.0] * 6) == pytest.approx(1.0)
    # Un écart plus modeste reste dans la plage, et garde son signe.
    assert momentum_carriere([5.0] * 6 + [1.0] * 6) == pytest.approx(0.4)


def test_un_cheval_en_declin_a_un_momentum_negatif():
    assert momentum_carriere([-10.0] * 6 + [20.0] * 6) < 0


def test_le_momentum_reste_borne():
    assert -1.0 <= momentum_carriere([500.0] * 6 + [-500.0] * 6) <= 1.0


def test_une_carriere_plate_donne_zero_comme_une_carriere_inconnue():
    """Limite ASSUMÉE et documentée : le vecteur doit garder la même forme, donc
    « je ne sais pas » et « stable » partagent la valeur 0,0. Ce qui change, c'est
    que le premier cas ne concerne plus tout le monde."""
    assert momentum_carriere([3.0] * 12) == 0.0
    assert momentum_carriere([]) == 0.0


def test_une_valeur_illisible_ne_fait_pas_lever_le_calcul():
    assert momentum_carriere([None, "?", 5.0]) == 0.0
