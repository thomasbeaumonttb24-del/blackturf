"""Tests de la métrique de classement intra-course et de la référence marché.

Cette métrique décide des promotions de modèle : une erreur ici se traduit
directement par la mise en production d'un mauvais classeur, sans que rien ne
le signale. Les cas limites sont donc verrouillés autant que le cas nominal.
"""
import numpy as np
import pytest

from ml.ranking_metrics import (
    extract_cotes, market_scores_from_cotes, rank_auc_report, within_race_auc,
)


# ── Cas nominal ─────────────────────────────────────────────────────────────

def test_classement_parfait_vaut_1():
    """Le gagnant en tête de chaque course."""
    labels = [1, 0, 0, 1, 0, 0]
    scores = [0.9, 0.5, 0.1, 0.8, 0.4, 0.2]
    groups = ["c1", "c1", "c1", "c2", "c2", "c2"]
    assert within_race_auc(labels, scores, groups) == 1.0


def test_classement_inverse_vaut_0():
    labels = [1, 0, 0]
    scores = [0.1, 0.5, 0.9]
    groups = ["c1", "c1", "c1"]
    assert within_race_auc(labels, scores, groups) == 0.0


def test_gagnant_au_milieu():
    """Gagnant 2e sur 3 : il bat un partant sur deux → 0,5."""
    assert within_race_auc([0, 1, 0], [0.9, 0.5, 0.1], ["c"] * 3) == 0.5


def test_chaque_course_pese_pareil_quel_que_soit_le_champ():
    """Une course à 18 partants ne doit pas peser plus qu'une course à 4.

    Sans ce choix, la moyenne serait dominée par les grands champs (Plat,
    quintés) alors que le produit affiche une fiche par course.
    """
    # c1 : 4 partants, classement parfait. c2 : 18 partants, classement inverse.
    labels = [1, 0, 0, 0] + [1] + [0] * 17
    scores = [1.0, 0.3, 0.2, 0.1] + [0.0] + list(np.linspace(1.0, 0.1, 17))
    groups = ["c1"] * 4 + ["c2"] * 18
    # 1,0 et 0,0 → moyenne 0,5 exactement si les courses pèsent pareil.
    assert within_race_auc(labels, scores, groups) == pytest.approx(0.5)


# ── Ex æquo et cas dégénérés ────────────────────────────────────────────────

def test_ex_aequo_comptent_pour_moitie():
    """Trois partants au même score = aucune information → 0,5."""
    assert within_race_auc([1, 0, 0], [0.5, 0.5, 0.5], ["c"] * 3) == 0.5


def test_ex_aequo_partiels():
    """Gagnant à égalité avec un seul des deux perdants : bat l'un (1),
    ex æquo avec l'autre (0,5) → 0,75."""
    assert within_race_auc([1, 0, 0], [0.5, 0.5, 0.1], ["c"] * 3) == pytest.approx(0.75)


def test_course_sans_gagnant_est_ecartee_pas_comptee_neutre():
    """Une course sans positif ne porte aucune information de classement.

    La compter 0,5 tirerait silencieusement la moyenne vers le hasard — un
    modèle excellent paraîtrait médiocre si beaucoup de courses n'ont pas de
    label exploitable.
    """
    labels = [1, 0, 0] + [0, 0, 0]          # c2 : aucun gagnant
    scores = [0.9, 0.5, 0.1] + [0.9, 0.5, 0.1]
    groups = ["c1"] * 3 + ["c2"] * 3
    assert within_race_auc(labels, scores, groups) == 1.0


def test_course_ou_tous_gagnent_est_ecartee():
    labels = [1, 1, 1]
    assert within_race_auc(labels, [0.9, 0.5, 0.1], ["c"] * 3) == 0.5


def test_aucune_course_exploitable_renvoie_le_hasard():
    """Valeur neutre comparable, jamais un NaN qui contaminerait un gate."""
    assert within_race_auc([0, 0], [0.5, 0.2], ["c", "c"]) == 0.5
    assert within_race_auc([], [], []) == 0.5


def test_longueurs_incoherentes_ne_plantent_pas():
    assert within_race_auc([1, 0], [0.5], ["c", "c"]) == 0.5


# ── Plusieurs positifs (label top-3) ────────────────────────────────────────

def test_label_top3_avec_trois_positifs():
    """La métrique doit accepter le label top-3, pas seulement le gagnant.

    3 placés en tête sur 6 partants → séparation parfaite → 1,0.
    """
    labels = [1, 1, 1, 0, 0, 0]
    scores = [0.9, 0.8, 0.7, 0.3, 0.2, 0.1]
    assert within_race_auc(labels, scores, ["c"] * 6) == 1.0


# ── Ordre des lignes ────────────────────────────────────────────────────────

def test_resultat_independant_de_l_ordre_des_lignes():
    """Les lignes d'une course ne sont pas garanties contiguës : le regroupement
    doit se faire sur la valeur du groupe, jamais sur l'adjacence."""
    labels = [1, 1, 0, 0]
    scores = [0.9, 0.8, 0.1, 0.2]
    entrelace = ["c1", "c2", "c1", "c2"]
    contigu_l, contigu_s, contigu_g = [1, 0, 1, 0], [0.9, 0.1, 0.8, 0.2], ["c1", "c1", "c2", "c2"]
    assert within_race_auc(labels, scores, entrelace) == within_race_auc(
        contigu_l, contigu_s, contigu_g)


# ── Référence marché ────────────────────────────────────────────────────────

def test_score_marche_est_l_inverse_de_la_cote():
    s = market_scores_from_cotes([2.0, 4.0, 10.0])
    assert s.tolist() == [0.5, 0.25, 0.1]


def test_overround_sans_effet_sur_l_ordre():
    """1/cote suffit : l'overround est multiplicatif et commun à la course."""
    cotes = [2.0, 5.0, 20.0]
    brut = market_scores_from_cotes(cotes)
    devigge = brut / brut.sum()
    labels, groups = [1, 0, 0], ["c"] * 3
    assert within_race_auc(labels, brut, groups) == within_race_auc(labels, devigge, groups)


def test_cote_manquante_devient_le_pire_score_jamais_le_meilleur():
    """Une cote nulle/absente ne doit pas propulser le partant en tête."""
    s = market_scores_from_cotes([2.0, 0.0, 5.0, 4.0])
    assert s[1] == 0.0
    assert s[1] < s.min() + 1e-12


def test_trop_peu_de_cotes_valides_renvoie_None():
    """Comparer à une référence marché dégradée serait pire que ne pas comparer."""
    assert market_scores_from_cotes([0.0, 0.0, 0.0, 2.0]) is None
    assert market_scores_from_cotes(None) is None


# ── Rapport combiné ─────────────────────────────────────────────────────────

def test_rapport_expose_l_ecart_au_marche():
    # Modèle parfait, marché inversé (le favori perd systématiquement).
    labels = [1, 0, 0, 1, 0, 0]
    scores = [0.9, 0.5, 0.1, 0.9, 0.5, 0.1]
    cotes  = [10.0, 5.0, 2.0, 10.0, 5.0, 2.0]
    groups = ["c1"] * 3 + ["c2"] * 3
    r = rank_auc_report(labels, scores, groups, cotes)
    assert r["rank_auc"] == 1.0
    assert r["market_rank_auc"] == 0.0
    assert r["delta_market"] == 1.0


def test_sans_cotes_le_delta_est_None_jamais_zero():
    """Un gate ne doit JAMAIS lire une absence de mesure comme un succès.

    Renvoyer 0.0 ferait passer « je n'ai pas pu comparer » pour « à égalité
    avec le marché » — exactement le genre de silence qui a laissé 513
    versions se succéder sans qu'on sache qu'elles étaient sous la cote.
    """
    r = rank_auc_report([1, 0], [0.9, 0.1], ["c", "c"], cotes=None)
    assert r["market_rank_auc"] is None
    assert r["delta_market"] is None
    assert r["rank_auc"] == 1.0


def test_extract_cotes_depuis_un_dataframe():
    pd = pytest.importorskip("pandas")
    X = pd.DataFrame({"cote_pmu": [2.0, 5.0], "autre": [1, 2]})
    assert extract_cotes(X).tolist() == [2.0, 5.0]


def test_extract_cotes_absentes_renvoie_None():
    """Après le retrait des colonnes de marché du vecteur d'entraînement
    (point 2 du diagnostic), les cotes devront être fournies séparément."""
    pd = pytest.importorskip("pandas")
    assert extract_cotes(pd.DataFrame({"elo": [1.0, 2.0]})) is None
    assert extract_cotes(None) is None


# ── Cohérence avec l'AUC poolée ─────────────────────────────────────────────

def test_diverge_de_l_AUC_poolee_c_est_tout_l_interet():
    """Le cas qui justifie ce module : le biais de taille de champ.

    Deux courses où le modèle ne sait RIEN du classement interne — dans chacune,
    tous les partants ont le même score, donc AUC intra-course = 0,5, le hasard.

    Mais il donne des scores élevés à la course à 2 partants (où l'on gagne une
    fois sur deux) et bas à celle à 10 partants (une fois sur dix). L'AUC poolée
    compare les gagnants des DEUX courses aux perdants des DEUX courses : elle
    récompense cette séparation inter-course et affiche 0,70.

    C'est le mécanisme exact par lequel un simple lecteur de cote obtient une
    bonne AUC poolée sans rien apporter au classement. La métrique poolée
    servait à décider des promotions.
    """
    from sklearn.metrics import roc_auc_score

    # Course à 2 partants, tous à 0,5 ; course à 10 partants, tous à 0,1.
    labels = [1, 0] + [1] + [0] * 9
    scores = [0.5, 0.5] + [0.1] * 10
    groups = ["petit_champ"] * 2 + ["grand_champ"] * 10

    assert within_race_auc(labels, scores, groups) == 0.5      # le hasard, et c'est vrai
    assert roc_auc_score(labels, scores) == pytest.approx(0.70)  # la poolée est flattée
