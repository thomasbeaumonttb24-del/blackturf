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
    assert all(a["lus"] == len(art["colonnes"]) and a["criteres"] for a in s["analyse"])
    assert any(c.startswith("r_") for c in art["colonnes"])
    assert art["version"] == ob.VERSION


def test_sans_cerveau_aucune_selection():
    d = ob.preparer(_jeu(3))
    assert ob.selection(ob.scorer(d, None)).empty


def test_raison_sous_cote_ignore_les_appariements_absurdes():
    row = pd.Series({"cote_figee": 21.0, "f_cote_betfair_exchange": 2.0, "f_cote_unibet": 14.0})
    assert "14 contre 21" in ob._phrase("sous_cote_pmu", row, {})
    row = pd.Series({"cote_figee": 21.0, "f_cote_betfair_exchange": 2.0})
    assert ob._phrase("sous_cote_pmu", row, {}) is None      # jamais de phrase générique


def test_non_abonne_ne_recoit_rien_d_identifiant_sur_une_course_a_venir():
    from types import SimpleNamespace
    from api.routes.outsiders import acces_complet, filtrer
    a_venir = {"course_id": "07102026R1C1", "code": "R1C1", "hippodrome": "VINCENNES", "date_heure": "x",
               "numero": 7, "nom_cheval": "X", "casaque_image_url": "u", "jockey": "J", "cote_signal": 22.0,
               "cote_actuelle": 25.0, "chance_place": 0.3, "raisons": ["a"], "niveau": "a_suivre",
               "termine": False, "non_partant": False}
    fort = dict(a_venir, niveau="fort")
    fini = dict(a_venir, termine=True, numero=3, nom_cheval="Y")
    out = filtrer([a_venir, fort, fini], complet=False)
    assert out[0] == {"verrouille": True, "termine": False, "niveau": "fort"}
    assert out[1] == {"verrouille": True, "termine": False, "niveau": "a_suivre"}
    assert out[2]["nom_cheval"] == "Y" and out[2]["verrouille"] is False
    assert [l["nom_cheval"] for l in filtrer([a_venir, fini], complet=True)] == ["X", "Y"]
    assert not acces_complet(None)
    assert not acces_complet(SimpleNamespace(plan="free", is_admin=False))
    assert not acces_complet(SimpleNamespace(plan="decouverte", is_admin=False))
    for plan in ("standard", "starter", "expert", "pro"):
        assert acces_complet(SimpleNamespace(plan=plan, is_admin=False))
    assert acces_complet(SimpleNamespace(plan="free", is_admin=True))


def test_lire_musique():
    assert ob.lire_musique("1a3a(25)Da0a5a7a") == ("1a 3a Da 0a 5a", 2, 5)
    assert ob.lire_musique(None) == (None, None, 0)
    assert ob.lire_musique("") == (None, None, 0)


def test_fiche_place_chaque_critere_dans_le_champ():
    row = pd.Series({"n_champ": 9, "partants": 9, "cote_figee": 21.0, "cote_premiere": 30.0,
                     "rang_predit": 1, "musique": "2a1a3a",
                     "f_taux_top3": 0.6, "r_taux_top3": 1.0,          # meilleur du champ
                     "f_jours_repos": 120.0, "r_jours_repos": 1.0,    # le plus long repos : mauvais
                     "f_cote_unibet": 12.0})
    f = ob.fiche(row, {"colonnes": ["a"] * 456, "sens": {"taux_top3": 1}})
    par = {c["libelle"]: c for c in f["criteres"]}
    assert f["lus"] == 456
    assert par["Podiums sur ses dernières courses"]["detail"] == "1er sur 9 · 60 %"
    assert par["Podiums sur ses dernières courses"]["verdict"] == "favorable"
    assert par["Jours depuis sa dernière course"]["verdict"] == "defavorable"
    assert par["Musique (5 dernières)"]["verdict"] == "favorable"
    assert par["Cote ailleurs qu'au PMU"]["detail"] == "12 ailleurs contre 21 au PMU"
    assert par["Mouvement de cote"]["verdict"] == "favorable"
    assert f["favorables"] >= 4 and f["defavorables"] >= 1


def test_sans_cote_de_reference_pas_de_mouvement():
    df = _jeu(3)
    df["cote_premiere"] = None         # pas de cote de référence PMU
    d = ob.preparer(df)
    assert (d["derive"] == 0).all()
    row = d.iloc[0]
    assert not any(c["libelle"] == "Mouvement de cote" for c in ob.fiche(row, {"colonnes": []})["criteres"])


def test_raisons_chiffrees_et_classement_sur_les_vrais_partants():
    sens = {}
    row = pd.Series({"n_champ": 7, "partants": 12, "rang_predit": 3, "f_rang_cote": 9,
                     "f_jockey_taux_place_global": 0.37, "r_jockey_taux_place_global": 1.0,
                     "musique": "1a2a5a3a7a"})
    assert ob._phrase("modele", row, sens) == "Notre modèle le classe 3e sur 12, devant son rang au marché (9e)"
    assert ob._phrase("entourage", row, sens) == "Jockey : taux de places 37 % (1er sur 7 partants)"
    assert ob._phrase("forme", row, sens).startswith("Forme : 3 podiums sur ses 5 dernières courses")
    f = ob.fiche(row, {"colonnes": []})
    modele = [c for c in f["criteres"] if c["libelle"].startswith("Classement")][0]
    assert modele["detail"] == "3e sur 12"
    # modèle derrière son rang de cote : pas de raison « modèle »
    assert ob._phrase("modele", row.copy().replace({3: 10}), sens) is None


def test_colonne_analyse_toujours_entre_guillemets():
    """`analyse` est un mot réservé de PostgreSQL : non cité, toute requête plante
    (premier déploiement du 07/10/2026 : registre jamais écrit, page vide)."""
    import inspect
    import re
    from services import outsiders as so
    src = so._SQL_LISTE + inspect.getsource(so.rafraichir_signaux)
    sql = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    nus = re.findall(r'(?<![":\w])analyse(?![":\w])', sql)
    assert nus == [], f"« analyse » non cité dans le SQL : {len(nus)} occurrence(s)"
