"""Tests des modules ajoutés/réveillés par la refonte 2026-06 :
features dormantes (terrain/corde/vitesse/poids/géo), détecteur d'outsiders,
apprentissage par profil (poids), justificatifs du plan de mise."""
import pytest

from ml.features import (
    get_terrain_famille, corde_zone, compute_vitesse_relative,
    compute_delta_poids, haversine_km, bucket_distance_km,
    compute_distance_deplacement, HIPPODROME_GEO,
)
from ml.outsider_detector import compute_outsider_score
from ml.profil_learning import shrunk_weight
from services.mise_calculator import (
    generer_plan, plan_to_dict, _motif_rejet, _effective_config,
)
from services.bet_settlement import settle_pari


# ── Features dormantes ───────────────────────────────────────────────────────
class TestTerrainFamille:
    def test_libelles_pmu(self):
        assert get_terrain_famille("BON") == "ferme"
        assert get_terrain_famille("TRES_SOUPLE") == "intermediaire"
        assert get_terrain_famille("Très lourd") == "lourd"
        assert get_terrain_famille("collant") == "lourd"

    def test_bon_souple_est_intermediaire(self):
        # "bon souple" contient "souple" ET "bon" — intermédiaire testé avant ferme.
        assert get_terrain_famille("bon souple") == "intermediaire"

    def test_inconnu(self):
        assert get_terrain_famille(None) == "inconnu"
        assert get_terrain_famille("") == "inconnu"
        assert get_terrain_famille("xyz") == "inconnu"


class TestCordeZone:
    def test_zones(self):
        assert corde_zone(1) == "interieure"
        assert corde_zone(4) == "interieure"
        assert corde_zone(5) == "milieu"
        assert corde_zone(8) == "milieu"
        assert corde_zone(9) == "exterieure"
        assert corde_zone(16) == "exterieure"

    def test_inconnu(self):
        assert corde_zone(None) == "inconnu"
        assert corde_zone(0) == "inconnu"


class TestVitesseRelative:
    def test_neutre_sans_donnees(self):
        assert compute_vitesse_relative([], 15.0) == 0.5
        assert compute_vitesse_relative([15.0], None) == 0.5

    def test_clip(self):
        # ratio 1.05+ → 1.0 ; 0.95- → 0.0 ; 1.0 → 0.5
        assert compute_vitesse_relative([15.75], 15.0) == 1.0
        assert compute_vitesse_relative([14.25], 15.0) == 0.0
        assert abs(compute_vitesse_relative([15.0], 15.0) - 0.5) < 1e-9


class TestDeltaPoids:
    def test_neutre(self):
        assert compute_delta_poids(None, [58.0]) == 0.0
        assert compute_delta_poids(58.0, []) == 0.0
        assert compute_delta_poids(500.0, [58.0]) == 0.0  # valeur aberrante ignorée

    def test_allegement_negatif(self):
        v = compute_delta_poids(55.0, [58.0, 58.0])
        assert v < 0
        assert v == pytest.approx(-0.6)

    def test_borne(self):
        assert compute_delta_poids(70.0, [55.0]) == 1.0


class TestGeo:
    def test_haversine_paris_marseille(self):
        d = haversine_km(48.86, 2.35, 43.30, 5.37)
        assert 620 < d < 700

    def test_bucket(self):
        assert bucket_distance_km(None) == 0.5
        assert bucket_distance_km(10) == 0.0
        assert bucket_distance_km(600) == 1.0

    def test_deplacement_connu(self):
        # Domicile Vincennes, course à Cagnes-sur-Mer → loin (≈1)
        hist = ["VINCENNES"] * 5 + ["ENGHIEN"]
        v = compute_distance_deplacement("CAGNES-SUR-MER", hist)
        assert v > 0.9

    def test_deplacement_local(self):
        v = compute_distance_deplacement("VINCENNES", ["VINCENNES"] * 3)
        assert v == 0.0

    def test_deplacement_inconnu(self):
        assert compute_distance_deplacement("HIPPODROME MYSTERE XYZ", ["VINCENNES"]) == 0.5
        assert compute_distance_deplacement(None, ["VINCENNES"]) == 0.5
        assert compute_distance_deplacement("VINCENNES", []) == 0.5

    def test_deplacement_noms_pmu_prefixes(self):
        # Formats réels DB : "HIPPODROME DE PARIS-VINCENNES", "HIPPODROME DE VICHY",
        # "HIPPODROME DE TOULOUSE LA CEPIERE" (match par inclusion)
        hist = ["HIPPODROME DE PARIS-VINCENNES"] * 4 + ["Vincennes"] * 2
        v = compute_distance_deplacement("HIPPODROME DE TOULOUSE LA CEPIERE", hist)
        assert v > 0.9  # Vincennes → Toulouse ≈ 590 km
        v2 = compute_distance_deplacement("HIPPODROME DE VICHY", ["HIPPODROME DE VICHY"] * 3)
        assert v2 == 0.0

    def test_geo_table_coords_valides(self):
        for nom, (lat, lon) in HIPPODROME_GEO.items():
            assert 41 < lat < 52, nom     # France métropolitaine
            assert -5.5 < lon < 9, nom


# ── Détecteur d'outsiders ────────────────────────────────────────────────────
def _mk_field(probas_cotes):
    return [{"numero": i + 1, "nom": f"H{i+1}", "proba_top1": p, "cote_pmu": c}
            for i, (p, c) in enumerate(probas_cotes)]


class TestOutsiderDetector:
    def test_champ_trop_petit(self):
        r = compute_outsider_score(_mk_field([(0.5, 2.0), (0.3, 3.0)]))
        assert r["score"] == 0.0 and not r["course_a_outsider"]

    def test_sans_edge_pas_de_course_outsider(self):
        # Champ avec favori écrasant, outsiders sans edge → pas de course à outsider
        field = _mk_field([(0.50, 1.8), (0.20, 4.5), (0.10, 9.0), (0.08, 12.0),
                           (0.06, 16.0), (0.04, 25.0), (0.02, 40.0)])
        r = compute_outsider_score(field)
        assert not r["course_a_outsider"]
        assert r["candidats"] == []

    def test_outsider_a_edge_detecte(self):
        # N°4 cote 12 : marché ~7% normalisé mais modèle 18% → gros edge
        field = _mk_field([(0.22, 3.5), (0.18, 4.5), (0.14, 6.0), (0.18, 12.0),
                           (0.10, 10.0), (0.08, 14.0), (0.06, 20.0), (0.04, 30.0)])
        r = compute_outsider_score(field, surprise_rate=0.32)
        assert r["candidats"], "outsider à edge attendu"
        assert r["candidats"][0]["numero"] == 4
        assert r["score"] > 0.5
        assert r["course_a_outsider"]

    def test_surprise_rate_none_ok(self):
        field = _mk_field([(0.2, 4.0), (0.18, 5.0), (0.15, 6.0), (0.15, 9.0),
                           (0.12, 11.0), (0.1, 14.0), (0.06, 22.0), (0.04, 30.0)])
        r = compute_outsider_score(field, surprise_rate=None)
        assert 0.0 <= r["score"] <= 1.0


# ── Règlement 2sur4 en formule combinée (gain_mult) ──────────────────────────
def _classement(*nums):
    return [{"numero": n, "position": i + 1} for i, n in enumerate(nums)]


class TestSettle2sur4Combine:
    """Un 2sur4 à N chevaux = C(N,2) combinaisons : le rapport PMU (base 1€) paie
    PAR combinaison gagnante. Avant fix : mise entière × rapport (jusqu'à 6× trop)."""
    RAPPORTS = {"e_deux_sur_quatre": 14.0}

    def test_4_chevaux_2_places_paie_un_sixieme(self):
        # top-4 = 1,2,3,4 ; sélection 1,2,90,91 → 2 dans top-4 → 1 combinaison / 6
        r = settle_pari("2sur4", [1, 2, 90, 91], _classement(1, 2, 3, 4, 5, 6, 7, 8),
                        self.RAPPORTS, 12)
        assert r["gagne"] and r["rapport_reel"] == 14.0
        assert r["gain_mult"] == pytest.approx(1 / 6)

    def test_4_chevaux_3_places(self):
        r = settle_pari("2sur4", [1, 2, 3, 90], _classement(1, 2, 3, 4, 5, 6, 7, 8),
                        self.RAPPORTS, 12)
        assert r["gain_mult"] == pytest.approx(3 / 6)

    def test_4_chevaux_tous_places_paie_plein(self):
        r = settle_pari("2sur4", [1, 2, 3, 4], _classement(1, 2, 3, 4, 5, 6, 7, 8),
                        self.RAPPORTS, 12)
        assert r["gain_mult"] == pytest.approx(1.0)

    def test_formule_simple_2_chevaux_inchangee(self):
        r = settle_pari("2sur4", [1, 3], _classement(1, 2, 3, 4, 5, 6, 7, 8),
                        self.RAPPORTS, 12)
        assert r["gagne"] and r["gain_mult"] == 1.0

    def test_perdu_aucune_combinaison(self):
        r = settle_pari("2sur4", [90, 91, 92, 93], _classement(1, 2, 3, 4, 5, 6, 7, 8),
                        self.RAPPORTS, 12)
        assert not r["gagne"]

    def test_autres_types_gain_mult_neutre(self):
        r = settle_pari("Simple Gagnant", [1], _classement(1, 2, 3, 4),
                        {"e_simple_gagnant": 4.2}, 8)
        assert r["gain_mult"] == 1.0


# ── Apprentissage par profil ─────────────────────────────────────────────────
class TestShrunkWeight:
    def test_neutre_sans_data(self):
        assert shrunk_weight(0.0, 0.0, 0) == 1.0
        assert shrunk_weight(10.0, 0.0, 5) == 1.0

    def test_shrinkage(self):
        # ROI +50% sur n=15, k=15 → effectif +25% → poids 1.25
        assert shrunk_weight(50.0, 100.0, 15) == pytest.approx(1.25)

    def test_bornes(self):
        assert shrunk_weight(-500.0, 100.0, 1000) == 0.5
        assert shrunk_weight(500.0, 100.0, 1000) == 1.6


# ── Justificatifs du plan de mise ────────────────────────────────────────────
def _preds_simple():
    """Champ synthétique cohérent (probas Σ≈1) avec un favori et un outsider à edge."""
    rows = [
        (1, "ALPHA", 0.30, 0.62, 2.8), (2, "BRAVO", 0.20, 0.50, 4.2),
        (3, "CHARLIE", 0.15, 0.42, 6.0), (4, "DELTA", 0.12, 0.36, 12.0),
        (5, "ECHO", 0.08, 0.28, 11.0), (6, "FOX", 0.06, 0.22, 18.0),
        (7, "GOLF", 0.05, 0.18, 22.0), (8, "HOTEL", 0.04, 0.15, 30.0),
    ]
    return [{"numero": n, "nom_cheval": nom, "proba_top1": p1, "proba_top3": p3,
             "cote_pmu": c, "non_partant": False} for n, nom, p1, p3, c in rows]


class TestJustificatifsPlan:
    def test_raisons_presentes(self):
        plan = generer_plan(20, "equilibre", _preds_simple(),
                            {"nb_partants": 8, "est_quinte": False, "est_quarte": False})
        d = plan_to_dict(plan)
        paris = [p for n in d["niveaux"] for p in n["paris"]]
        assert paris, "au moins un pari attendu"
        for p in paris:
            assert isinstance(p.get("raisons"), list)
            assert p["raisons"], f"raisons vides pour {p['type']}"
            # Trace Kelly toujours présente
            assert any("Kelly" in r for r in p["raisons"])

    def test_paris_ecartes_avec_motif(self):
        plan = generer_plan(10, "conservateur", _preds_simple(),
                            {"nb_partants": 8, "est_quinte": False, "est_quarte": False})
        d = plan_to_dict(plan)
        assert "paris_ecartes" in d
        for e in d["paris_ecartes"]:
            assert e["motif"]
            assert e["type"]

    def test_motif_rejet_type_hors_profil(self):
        cfg = _effective_config("conservateur", 0.0)
        c = {"type_pari": "Simple Gagnant", "chevaux": [{"numero": 4, "nom": "X", "cote": 12.0}],
             "proba_gain": 0.12, "rapport_estime": 12.0, "ev": 0.4, "edge": 0.05}
        assert "hors méthode" in _motif_rejet(c, cfg)

    def test_motif_rejet_ev_negative_sans_edge(self):
        cfg = _effective_config("equilibre", 0.0)
        c = {"type_pari": "Simple Gagnant", "chevaux": [{"numero": 2, "nom": "X", "cote": 4.0}],
             "proba_gain": 0.15, "rapport_estime": 4.0, "ev": -0.4, "edge": -0.02}
        assert "PMU" in _motif_rejet(c, cfg)

    def test_facteurs_chevaux_integres(self):
        facteurs = {1: {"positifs": [{"label": "Duo J×E efficace"}], "negatifs": []},
                    2: {"positifs": [{"label": "Forme excellente"}], "negatifs": [{"label": "Terrain défavorable"}]}}
        plan = generer_plan(20, "equilibre", _preds_simple(),
                            {"nb_partants": 8}, facteurs_chevaux=facteurs)
        d = plan_to_dict(plan)
        tous = " ".join(r for n in d["niveaux"] for p in n["paris"] for r in p["raisons"])
        # Au moins un pari implique le cheval 1 ou 2 → son facteur doit apparaître
        if any(str(ch["numero"]) in ("1", "2")
               for n in d["niveaux"] for p in n["paris"] for ch in p["chevaux"]):
            assert ("Duo J×E" in tous) or ("Forme excellente" in tous)
