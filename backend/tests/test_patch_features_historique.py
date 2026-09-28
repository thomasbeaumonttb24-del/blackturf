"""Règle du patch « historique v2 » : une clé n'est corrigée que si le calcul
d'avant reproduit exactement la valeur stockée (cf. scripts/patch_features_historique)."""
import math

from scripts.patch_features_historique import corrections_course, egal


def test_egal():
    assert egal(0.1 + 0.2, 0.3)
    assert not egal(0.3, 0.3001)
    assert egal(float("nan"), float("nan"))
    assert not egal(True, 1) and not egal(1, True)
    assert egal("a", "a") and egal(None, None) and not egal(None, 0)


def test_corrige_seulement_si_reproduit():
    avant = {"p1": {"a": 0.5, "b": 0.2, "c": 1.0}, "p2": {"a": 0.4, "b": 0.3, "c": 1.0}}
    apres = {"p1": {"a": 0.6, "b": 0.2, "c": 2.0}, "p2": {"a": 0.7, "b": 0.3, "c": 1.0}}
    stocke = {"p1": {"a": 0.5, "b": 0.2, "c": 9.9}, "p2": {"a": 0.41, "b": 0.3, "c": 1.0}}
    patch, stats = corrections_course(avant, apres, stocke)
    # p1.a reproduit → corrigé ; p1.c non reproduit (9.9 ≠ 1.0) → gardé ;
    # p2.a non reproduit (0.41 ≠ 0.4) → gardé ; b inchangé par le lot.
    assert patch == {"p1": {"patch": {"a": 0.6}, "ancien": {"a": 0.5}}}
    assert stats["a"] == {"diff": 2, "corrige": 1, "non_reproduit": 1, "non_fini": 0}
    assert stats["c"]["non_reproduit"] == 1
    assert "b" not in stats


def test_identite_jamais_touchee_et_vecteur_absent_ignore():
    avant = {"p1": {"participation_id": "p1", "course_id": "X", "a": 1.0}}
    apres = {"p1": {"participation_id": "p1", "course_id": "Y", "a": 2.0},
             "p9": {"a": 3.0}}
    stocke = {"p1": {"participation_id": "p1", "course_id": "X", "a": 1.0}}
    patch, _ = corrections_course(avant, apres, stocke)
    assert patch == {"p1": {"patch": {"a": 2.0}, "ancien": {"a": 1.0}}}


def test_valeur_non_finie_jamais_ecrite():
    patch, stats = corrections_course({"p": {"a": 1.0}}, {"p": {"a": math.nan}},
                                      {"p": {"a": 1.0}})
    assert patch == {} and stats["a"]["non_fini"] == 1


def test_cle_absente_du_stocke_non_reproduite():
    patch, stats = corrections_course({"p": {"a": 1.0}}, {"p": {"a": 2.0}}, {"p": {}})
    assert patch == {} and stats["a"]["non_reproduit"] == 1
