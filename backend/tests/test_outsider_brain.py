"""Cerveau des outsiders : règles de place, sélection, raisons, masquage public."""
import json

import numpy as np
import pandas as pd
import pytest

from ml import outsider_brain as ob


def test_places_payees_regle_pmu():
    assert ob.nb_places(3) == 0
    assert ob.nb_places(4) == 2
    assert ob.nb_places(7) == 2
    assert ob.nb_places(8) == 3
    assert ob.nb_places(18) == 3


def _jeu(n_courses=600, seed=0):
    """Courses synthétiques : la place dépend de proba_top3 ET d'un signal caché
    `f_forme_3_courses` que seul le cerveau voit."""
    rng = np.random.default_rng(seed)
    lignes = []
    jour0 = pd.Timestamp("2026-08-01")
    for c in range(n_courses):
        partants = int(rng.integers(8, 16))
        for k in range(6):
            p3 = float(rng.uniform(0.03, 0.35))
            forme = float(rng.normal())
            cote = float(rng.uniform(10, 60))
            logit = -2.2 + 4 * p3 + 0.9 * forme
            pos = 1 if rng.random() < 1 / (1 + np.exp(-logit)) else 9
            lignes.append({
                "participation_id": f"p{c}_{k}", "course_id": f"C{c}", "numero": k + 1,
                "cote_figee": cote, "cote_premiere": cote * float(rng.uniform(0.8, 1.2)),
                "proba_top1": p3 / 3, "proba_top3": p3, "rang_predit": k + 4,
                "partants": partants, "position_arrivee": pos,
                "features": json.dumps({"forme_3_courses": forme, "elo_vs_champ": float(rng.normal())}),
                "jour": jour0 + pd.Timedelta(days=c // 12),
            })
    return pd.DataFrame(lignes)


def test_preparer_aplatit_et_derive():
    d = ob.preparer(_jeu(5))
    assert "f_forme_3_courses" in d.columns and "features" not in d.columns
    assert d["places"].eq(3).all()
    assert d.groupby("course_id")["p3_rank"].min().eq(1).all()
    assert np.isfinite(d["derive"]).all()


def test_entrainer_promeut_un_cerveau_qui_voit_le_signal(monkeypatch):
    monkeypatch.setattr(ob, "MIN_LIGNES_ENTRAINEMENT", 500)
    monkeypatch.setattr(ob, "MIN_LIGNES_VALIDATION", 200)
    d = ob.preparer(_jeu())
    d["y"] = ob._place(d)
    res = ob.entrainer_sur(d, d["jour"].max() - pd.Timedelta(days=13))
    assert res["status"] == "promu"
    assert res["auc_cerveau"] > res["auc_general"]
    art = res["artefact"]
    s = ob.scorer(d.drop(columns=["y"]).head(60), art)
    assert s["chance"].between(0, 1).all()
    sel = ob.selection(s)
    assert (sel["cote_figee"] >= ob.COTE_OUTSIDER_MIN).all()
    assert sel.groupby("course_id").size().max() <= ob.MAX_PAR_COURSE
    assert set(sel["niveau"]) <= {"fort", "a_suivre"}
    assert all(isinstance(r, list) for r in s["raisons"])


def test_sans_cerveau_aucune_selection():
    d = ob.preparer(_jeu(3))
    assert ob.selection(ob.scorer(d, None)).empty


def test_raison_sous_cote_ignore_les_appariements_absurdes():
    row = pd.Series({"cote_figee": 21.0, "f_cote_betfair_exchange": 2.0, "f_cote_unibet": 14.0})
    assert "14 contre 21" in ob._phrase("sous_cote_pmu", row, 5)
    row = pd.Series({"cote_figee": 21.0, "f_cote_betfair_exchange": 2.0})
    assert "contre" not in ob._phrase("sous_cote_pmu", row, 5)


def test_masquage_public():
    from api.routes.outsiders import masquer
    a_venir = {"numero": 7, "nom_cheval": "X", "cote_signal": 22.0, "cote_actuelle": 25.0,
               "chance_place": 0.3, "raisons": ["a"], "termine": False, "code": "R1C1"}
    fini = dict(a_venir, termine=True)
    out = masquer([a_venir, fini], complet=False)
    assert out[0]["verrouille"] and out[0]["nom_cheval"] is None and out[0]["raisons"] == []
    assert out[0]["code"] == "R1C1"
    assert not out[1]["verrouille"] and out[1]["nom_cheval"] == "X"
    assert masquer([a_venir], complet=True)[0]["nom_cheval"] == "X"
