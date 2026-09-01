"""`niveau_course_code` lisait la mauvaise colonne, et le disait à personne.

Constat du 2026-09-01 : la feature figurait parmi les 24 à variance strictement
nulle sur 208. Le réflexe est de conclure à une donnée manquante — c'est vrai
pour 23 d'entre elles (`chevaux.running_style`, `chevaux.taux_en_tete`,
`chevaux.prix_vente_yearling`, `participations.retard_gains`,
`participations.cote_betclic` : ZÉRO ligne renseignée sur des centaines de
milliers). Pas pour celle-ci : `courses.niveau_course` est remplie à 100 % avec
7 869 libellés distincts.

Le défaut était que ce champ ne contient pas ce que son nom promet. Il porte les
`conditions` du PMU — qui a le droit de courir — et l'encodeur y cherchait
« group1 », « listed », « reclam ». Aucune correspondance possible : toutes les
courses tombaient sur la même valeur de repli.

Ces tests fixent les deux moitiés du correctif : la classe vient du champ
STRUCTURÉ (`categorie_particularite`), et l'encodage DISCRIMINE réellement — un
test qui vérifierait seulement « ça renvoie un entier » aurait passé avant comme
après.
"""
from __future__ import annotations

from ml.features import _encode_niveau


# Conditions d'engagement réelles observées en production : c'est ce que porte
# `niveau_course`, et c'est pour cela qu'il ne peut pas servir de niveau.
CONDITIONS_REELLES = (
    "Pour pur sang males, hongres et femelles de trois ans",
    "Pour chevaux entiers, hongres et juments de 4 ans et au-dessus",
    "Pour juments de 4 ans et au-dessus n'ayant pas gagne",
    "PRIX DE LA SOCIETE DES COURSES",
)

# Catégories réelles observées en production, avec leur volume sur un an.
CATEGORIES_REELLES = (
    "COURSE_A_CONDITIONS", "INCONNU", "HANDICAP", "AUTOSTART", "HANDICAP_DIVISE",
    "A_RECLAMER", "INTERNATIONALE_AUTOSTART", "NATIONALE", "HANDICAP_CATEGORIE_DIVISE",
    "EUROPEENNE", "APPRENTIS_LADS_JOCKEYS", "HANDICAP_DE_CATEGORIE", "AMATEURS",
    "GROUPE_I", "GROUPE_III", "COURSE_A_CONDITION_QUALIF_HP", "GROUPE_II",
    "A_RECLAMER_AUTOSTART", "HANDICAP_A_RECLAMER", "A_RECLAMER_APPRENTIS_LADS_JOCK",
)


def test_le_texte_des_conditions_seul_ne_discrimine_rien():
    """Le défaut d'origine, figé pour qu'il ne revienne pas.

    Sans la catégorie, les libellés de production donnent TOUS la même valeur :
    c'est exactement la variance nulle constatée. Le test l'assume au lieu de le
    cacher — ce qui doit changer, c'est qu'on ne s'appuie plus sur ce champ.
    """
    valeurs = {_encode_niveau(texte) for texte in CONDITIONS_REELLES}
    assert len(valeurs) == 1, (
        "surprise : les conditions d'engagement discriminent quelque chose. Si "
        "c'est voulu, ce test doit être réécrit — mais alors l'encodage du texte "
        "libre doit être mesuré, pas deviné.")


def test_la_categorie_pmu_discrimine_vraiment():
    """Le correctif ne vaut que s'il produit plusieurs classes SUR LES DONNÉES RÉELLES.

    Une feature « réparée » qui rendrait encore une constante serait un
    correctif cosmétique : la variance nulle resterait, l'alerte aussi, et le
    modèle apprendrait toujours du bruit.
    """
    valeurs = {_encode_niveau("Pour tous chevaux de 5 ans", cat) for cat in CATEGORIES_REELLES}
    assert len(valeurs) >= 5, (
        f"seulement {len(valeurs)} classes distinctes sur les 20 catégories les "
        "plus fréquentes de production : la feature resterait quasi constante.")


def test_l_ordre_de_prestige_est_respecte():
    """Groupe I < Groupe II/III < ... : l'échelle doit rester ordonnée."""
    assert _encode_niveau(None, "GROUPE_I") == 0
    assert _encode_niveau(None, "GROUPE_II") == 1
    assert _encode_niveau(None, "GROUPE_III") == 1
    assert _encode_niveau(None, "GROUPE_I") < _encode_niveau(None, "GROUPE_III")


def test_groupe_i_n_avale_pas_groupe_ii_et_iii():
    """Piège de sous-chaîne : « GROUPE_I » est contenu dans « GROUPE_II ».

    Sans garde, les Groupe II et III seraient classés Groupe I — 382 courses par
    an rangées au sommet de l'échelle, et l'erreur serait invisible : la feature
    aurait bien de la variance, elle serait simplement FAUSSE.
    """
    assert _encode_niveau(None, "GROUPE_II") != _encode_niveau(None, "GROUPE_I")
    assert _encode_niveau(None, "GROUPE_III") != _encode_niveau(None, "GROUPE_I")


def test_la_classe_la_plus_discriminante_gagne_sur_les_categories_composees():
    """`HANDICAP_A_RECLAMER` et `A_RECLAMER_APPRENTIS_LADS_JOCK` existent.

    L'ordre des tests dans l'encodeur doit être délibéré : une course à réclamer
    reste une course à réclamer, que ses partants soient montés par des
    apprentis ou qu'elle serve de handicap.
    """
    reclamer = _encode_niveau(None, "A_RECLAMER")
    assert _encode_niveau(None, "HANDICAP_A_RECLAMER") == reclamer
    assert _encode_niveau(None, "A_RECLAMER_APPRENTIS_LADS_JOCK") == reclamer
    assert _encode_niveau(None, "A_RECLAMER_AUTOSTART") == reclamer


def test_ce_qui_n_est_pas_un_niveau_n_est_pas_encode_comme_tel():
    """`AUTOSTART` est un mode de départ, `NATIONALE`/`EUROPEENNE` un recrutement.

    Les faire entrer dans l'échelle de prestige lui ferait dire ce qu'elle ne
    mesure pas. Ils partagent donc la valeur « non classé ».
    """
    non_classe = _encode_niveau(None, "INCONNU")
    for categorie in ("AUTOSTART", "NATIONALE", "EUROPEENNE", "INTERNATIONALE"):
        assert _encode_niveau(None, categorie) == non_classe, (
            f"{categorie} est encodé comme un niveau alors qu'il n'en est pas un.")


def test_l_inconnu_garde_la_valeur_d_avant_le_correctif():
    """Le cas « on ne sait pas » ne doit pas bouger.

    3 483 courses par an ont `INCONNU`, et c'est aussi ce que rendait l'ancien
    code pour l'INTÉGRALITÉ du champ. Leur donner une valeur neuve ferait porter
    au modèle un changement là où rien n'a été appris de nouveau.
    """
    assert _encode_niveau("Pour tous chevaux", "INCONNU") == 3
    assert _encode_niveau("Pour tous chevaux", None) == 3
    assert _encode_niveau("Pour tous chevaux", "") == 3


def test_le_texte_libre_reste_lu_en_repli():
    """Une source non-PMU qui écrirait « Listed » ou « Group 2 » garde son sens."""
    assert _encode_niveau("Group1 Stakes", None) == 0
    assert _encode_niveau("Group2 handicap", None) == 1
    assert _encode_niveau("Listed race", None) == 2
    assert _encode_niveau("Claiming / reclamer", None) == 4
