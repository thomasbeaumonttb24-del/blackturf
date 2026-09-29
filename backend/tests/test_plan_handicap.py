"""Course à handicap : pas de combinaisons à 3 chevaux et plus dans les plans.

Mesure du 2026-09-29 (5 601 courses, vrais rapports PMU, deux périodes disjointes) :
en handicap le Trio rend −44 %, le 2sur4 −29 %, le Multi en 5 −91 %, alors que le
gagnant du rang 1 tient à −3 %. Déclencheur : 29092026R1C7 (handicap, 16 partants,
Trio 2-4-3 proposé par le profil risqué).
"""
import pytest

from services import mise_calculator as mc


def _field(n=16):
    out = []
    for i in range(n):
        p1 = max(0.17 - i * 0.011, 0.01)
        out.append({"numero": i + 1, "nom_cheval": f"Cheval{i + 1}",
                    "cote_pmu": round(4.5 + i * 1.6, 1), "proba_top1": p1,
                    "proba_top3": min(p1 * 3.0, 0.9), "non_partant": False})
    return out


def _info(categorie):
    return {"nb_partants": 16, "est_quinte": False, "est_quarte": True,
            "est_tierce": True, "est_2sur4": True, "est_trio": True,
            "paris_disponibles": None, "categorie_particularite": categorie}


def _types(plan):
    return {p.type for n in plan.niveaux for p in n.paris}


@pytest.mark.parametrize("categorie", ["HANDICAP", "HANDICAP_DIVISE",
                                       "HANDICAP_DE_CATEGORIE"])
def test_est_handicap(categorie):
    assert mc.est_handicap({"categorie_particularite": categorie})


@pytest.mark.parametrize("info", [None, {}, {"categorie_particularite": None},
                                  {"categorie_particularite": "COURSE_A_CONDITIONS"}])
def test_hors_handicap(info):
    assert not mc.est_handicap(info)


def test_config_handicap_retire_les_combinaisons_larges():
    cfg = mc._adapter_contexte(mc._effective_config("agressif", 0.0), _info("HANDICAP"))
    assert not (cfg["types"] & mc.HANDICAP_TYPES_EXCLUS)
    assert "Trio" not in cfg["loterie"]
    assert "Simple Gagnant" in cfg["types"]


def test_config_hors_handicap_inchangee():
    base = mc._effective_config("agressif", 0.0)
    info = dict(_info("COURSE_A_CONDITIONS"), nb_partants=12)
    assert mc._adapter_contexte(base, info) is base


@pytest.mark.parametrize("profil", ["conservateur", "equilibre", "agressif"])
def test_plan_handicap_sans_combinaison_large(profil):
    plan = mc.generer_plan(10, profil, _field(), _info("HANDICAP_DIVISE"),
                           respect_montant=True)
    assert not ({mc._fam(t) for t in _types(plan)} & mc.HANDICAP_TYPES_EXCLUS)


def test_motif_handicap_explique():
    cfg = mc._adapter_contexte(mc._effective_config("agressif", 0.0), _info("HANDICAP"))
    motif = mc._motif_rejet({"type_pari": "Trio", "chevaux": []}, cfg)
    assert "handicap" in motif.lower()


def test_risque_handicap_gagnant_sec_seulement():
    cfg = mc._adapter_contexte(mc._effective_config("agressif", 0.0), _info("HANDICAP"))
    assert not ({"Couplé Gagnant", "Couplé Ordre", "Couplé Placé"} & cfg["types"])
    assert "Simple Gagnant" in cfg["types"]
    plan = mc.generer_plan(10, "agressif", _field(), _info("HANDICAP"), respect_montant=True)
    assert _types(plan) <= {"Simple Gagnant"}


def test_modere_handicap_garde_les_couples():
    cfg = mc._adapter_contexte(mc._effective_config("equilibre", 0.0), _info("HANDICAP"))
    assert "Couplé Placé" in cfg["types"] and "Couplé Gagnant" in cfg["types"]


def _info_champ(n):
    return {"nb_partants": n, "est_quinte": False, "est_quarte": True, "est_tierce": True,
            "est_2sur4": True, "est_trio": True, "paris_disponibles": None,
            "categorie_particularite": "COURSE_A_CONDITIONS"}


def test_trio_gros_lot_coupe_a_15_partants():
    cfg = mc._adapter_contexte(mc._effective_config("agressif", 0.0), _info_champ(16))
    assert "Trio" not in cfg["types"] and not cfg["loterie"]


def test_trio_gros_lot_garde_sous_15_partants():
    for n in (8, 12, 14):
        cfg = mc._adapter_contexte(mc._effective_config("agressif", 0.0), _info_champ(n))
        assert "Trio" in cfg["types"] and "Trio" in cfg["loterie"]
