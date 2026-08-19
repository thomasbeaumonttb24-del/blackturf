"""Le palmarès PUBLIC mesure la cohorte PRÉ-COURSE, pas la seule cohorte rejouable.

Contexte (bug constaté le 19/08/2026) : `/stats/track-record` filtrait ses agrégats
sur `is_replayable = true`. Ce drapeau (migration 0030) distingue le snapshot
immuable — rejouable à l'identique en backtest — de la ligne `predictions` héritée,
mutable. C'est une propriété de REJOUABILITÉ, pas d'intégrité temporelle : l'exiger
réduisait la page publique aux courses postérieures au 18/08, soit 44 courses. La
page annonçait « 19 courses analysées » en attelé (1 598 réelles), « 4 » en monté
(188 réelles) et « 21 » en plat (1 683 réelles).

Deux contrats vivent donc côte à côte, et ces tests interdisent de les confondre :

  * APPRENTISSAGE (calibrateurs, backtests, méta-learner) → cohorte REJOUABLE
    stricte. Vérifié par `test_prediction_evaluation_contract.py`.
  * PUBLICATION (palmarès public) → cohorte PRÉ-COURSE : la prédiction devait
    exister avant le départ (`p.created_at < c.date_heure`), garde anti-backfill
    identique à celle du palmarès des gains.
"""

import inspect

from api.routes import stats


def _source_normalisee() -> str:
    return " ".join(inspect.getsource(stats._compute_track_record).lower().split())


def test_chaque_agregat_public_garde_la_preuve_temporelle():
    """Aucun agrégat publié ne compte une course sans prono figé avant le départ."""
    src = _source_normalisee()
    # 6 requêtes SQL de cohorte (global, mesure_depuis, par jour, par discipline,
    # tendance 30 j, compteur rejouable) + les filtres ORM (meilleurs pronos,
    # value bets, favori IA) portent tous la garde.
    assert src.count("p.created_at < c.date_heure") >= 6
    assert "predictionevaluation.created_at < course.date_heure" in src


def test_les_taux_publies_ne_sont_pas_restreints_a_la_cohorte_rejouable():
    """`is_replayable` ne sert QU'À compter le sous-ensemble strict, jamais à filtrer.

    Un seul usage est légitime : la requête dédiée qui alimente
    `global.nb_courses_rejouables`. Toute réapparition ailleurs re-casserait les
    volumes affichés par discipline.
    """
    src = _source_normalisee()
    assert src.count("is_replayable = true") == 1
    assert "predictionevaluation.is_replayable" not in src


def test_le_sous_ensemble_rejouable_reste_publie():
    """« Vérifiable » garde un chiffre : le compte strict est exposé à part."""
    src = _source_normalisee()
    assert '"nb_courses_rejouables": nb_rejouables' in src


def test_le_repere_hasard_est_calcule_sur_le_champ_reel():
    """« 59,8 % » ne veut rien dire sans ce qu'il bat — et ce repère n'est pas codé en dur."""
    src = _source_normalisee()
    assert "least(3.0, nb_partants::numeric) / nb_partants" in src
    assert '"hasard_top3": hasard_top3' in src
