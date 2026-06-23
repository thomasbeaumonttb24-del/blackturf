"""Tests refonte paris 2026-06-17 :
- nouveaux paris Multi (en 4→7) / Mini Multi / Pick5 : génération + règlement ;
- garde-fou de VARIANCE (var_cap) : le profil risqué ne met JAMAIS toute la mise sur
  un seul pari tout-ou-rien (bug « toute la mise sur un Trio ») ;
- dérivation des drapeaux est_multi / est_pick5 depuis la vérité PMU.
"""
import math

import pytest

from services.bet_catalog import derive_bet_flags
from services.bet_settlement import settle_pari
from services.mise_calculator import (
    generer_plan, plan_to_dict, _is_high_variance, _fam,
)
from ml.combo_bets import enumerate_bet_candidates


def _classement(*nums):
    return [{"numero": n, "position": i + 1} for i, n in enumerate(nums)]


def _field(n=8):
    """Champ synthétique (probas Σ≈1, cotes croissantes)."""
    rows = [(0.30, 2.8), (0.20, 4.2), (0.15, 6.0), (0.12, 9.0),
            (0.08, 12.0), (0.06, 18.0), (0.05, 24.0), (0.04, 32.0)][:n]
    return [{"numero": i + 1, "nom": f"H{i+1}", "nom_cheval": f"H{i+1}",
             "proba_top1": p, "proba_top3": min(1.0, p * 2.2),
             "cote_pmu": c, "non_partant": False}
            for i, (p, c) in enumerate(rows)]


# ── Catalog : drapeaux Multi / Pick5 ─────────────────────────────────────────
class TestCatalogMultiPick5:
    def test_codes_exacts(self):
        f = derive_bet_flags(["E_SIMPLE_GAGNANT", "E_MULTI", "E_PICK5"])
        assert f["est_multi"] is True
        assert f["est_pick5"] is True

    def test_substring_tolerance(self):
        # Libellés PMU mal préfixés → détection par sous-chaîne.
        f = derive_bet_flags(["E_MULTI_EN_7", "PICK_5"])
        assert f["est_multi"] is True
        assert f["est_pick5"] is True

    def test_absents_par_defaut(self):
        f = derive_bet_flags(["E_SIMPLE_GAGNANT", "E_COUPLE_GAGNANT"])
        assert f["est_multi"] is False
        assert f["est_pick5"] is False


# ── Génération des candidats Multi / Pick5 ───────────────────────────────────
class TestGenerationMultiPick5:
    COURSE = {
        "nb_partants": 16,
        "paris_disponibles": ["E_SIMPLE_GAGNANT", "E_COUPLE_GAGNANT", "E_TRIO",
                              "E_MULTI", "E_PICK5"],
    }

    def test_multi_spectre_4_a_7(self):
        cands = enumerate_bet_candidates(_field(8), self.COURSE)
        types = {c["type_pari"] for c in cands}
        for n in (4, 5, 6, 7):
            assert f"Multi en {n}" in types, f"Multi en {n} manquant"

    def test_pick5_present(self):
        cands = enumerate_bet_candidates(_field(8), self.COURSE)
        assert any(c["type_pari"] == "Pick5" for c in cands)

    def test_multi_7_plus_probable_que_multi_4(self):
        cands = {c["type_pari"]: c for c in enumerate_bet_candidates(_field(8), self.COURSE)}
        assert cands["Multi en 7"]["proba_gain"] > cands["Multi en 4"]["proba_gain"]

    def test_pas_de_multi_si_non_offert(self):
        course = {"nb_partants": 16,
                  "paris_disponibles": ["E_SIMPLE_GAGNANT", "E_TRIO"]}
        cands = enumerate_bet_candidates(_field(8), course)
        assert not any("Multi" in c["type_pari"] for c in cands)
        assert not any(c["type_pari"] == "Pick5" for c in cands)

    def test_mini_multi_label_10_13_partants(self):
        course = {"nb_partants": 12,
                  "paris_disponibles": ["E_SIMPLE_GAGNANT", "E_MULTI"]}
        cands = enumerate_bet_candidates(_field(8), course)
        assert any(c["type_pari"].startswith("Mini Multi en") for c in cands)


# ── Garde-fou variance : jamais toute la mise sur un Trio ─────────────────────
class TestVarianceCap:
    COURSE = {
        "nb_partants": 16,
        "paris_disponibles": ["E_SIMPLE_GAGNANT", "E_COUPLE_GAGNANT", "E_COUPLE_ORDRE",
                              "E_TRIO", "E_MULTI", "E_PICK5", "E_TIERCE", "E_QUARTE_PLUS",
                              "E_QUINTE_PLUS", "E_DEUX_SUR_QUATRE"],
        "est_tierce": True, "est_quarte": True, "est_quinte": True, "est_2sur4": True,
    }

    def test_risque_ne_met_pas_tout_sur_un_seul_haute_variance(self):
        montant = 50
        plan = generer_plan(montant, "agressif", _field(8), self.COURSE,
                            respect_montant=True)
        d = plan_to_dict(plan)
        plafond = int(montant * 0.45)
        for niv in d["niveaux"]:
            for p in niv["paris"]:
                if _is_high_variance({"type_pari": p["type"]}):
                    assert p["mise"] <= plafond + 1, (
                        f"{p['type']} mise {p['mise']}€ > plafond variance {plafond}€"
                    )

    def test_risque_diversifie_si_haute_variance(self):
        # Si le meilleur pari est haute-variance, le plan doit comporter ≥2 paris
        # (ou laisser une réserve) — pas 100% sur un ticket.
        plan = generer_plan(50, "agressif", _field(8), self.COURSE, respect_montant=True)
        d = plan_to_dict(plan)
        paris = [p for niv in d["niveaux"] for p in niv["paris"]]
        hv = [p for p in paris if _is_high_variance({"type_pari": p["type"]})]
        if hv:
            # soit ≥2 paris, soit une réserve laissée (montant_joue < total)
            assert len(paris) >= 2 or d["montant_joue"] < d["montant_total"]


# ── Règlement Multi / Mini Multi / Pick5 ─────────────────────────────────────
class TestSettleMulti:
    CL = _classement(1, 2, 3, 4, 5, 6, 7, 8)   # top4 = {1,2,3,4}, top5 = {1..5}

    # Détail PMU réel : UNE entrée par formule « en N » (même combinaison, rapports
    # décroissants). Cas réel R3C1 18/06 : en 4 = 120, en 5 = 24, en 6 = 8.
    MULTI_DETAIL = {"e_multi": [
        {"combinaison": "1-2-3-4", "rapport": 120.0, "libelle": "e-Multi en 4"},
        {"combinaison": "1-2-3-4", "rapport": 24.0,  "libelle": "e-Multi en 5"},
        {"combinaison": "1-2-3-4", "rapport": 8.0,   "libelle": "e-Multi en 6"},
        {"combinaison": "1-2-3-4", "rapport": 3.0,   "libelle": "e-Multi en 7"},
    ]}

    def test_multi_en_5_prend_le_rapport_en_5_pas_en_4(self):
        # RÉGRESSION bug R3C1 : avant on payait detail[0] = « en 4 » (surpaie).
        r = settle_pari("Multi en 5", [1, 2, 3, 4, 5], self.CL,
                        {"e_multi": 120.0}, 16, rapports_detail=self.MULTI_DETAIL)
        assert r["gagne"] and r["rapport_reel"] == 24.0   # en 5, PAS 120 (en 4)
        assert r["gain_mult"] == 1.0      # mise plate, pas de division

    def test_multi_en_4_prend_le_rapport_en_4(self):
        r = settle_pari("Multi en 4", [1, 2, 3, 4], self.CL,
                        {"e_multi": 120.0}, 16, rapports_detail=self.MULTI_DETAIL)
        assert r["gagne"] and r["rapport_reel"] == 120.0

    def test_multi_en_4_perdant_si_un_arrivant_hors_selection(self):
        r = settle_pari("Multi en 4", [1, 2, 3, 9], self.CL, {"e_multi": 40.0}, 16)
        assert not r["gagne"]

    def test_multi_en_7_gagnant_large_filet(self):
        r = settle_pari("Multi en 7", [1, 2, 3, 4, 5, 6, 7], self.CL,
                        {"e_multi": 120.0}, 16, rapports_detail=self.MULTI_DETAIL)
        assert r["gagne"] and r["rapport_reel"] == 3.0   # en 7

    def test_multi_repli_positionnel_sans_libelle(self):
        # Vieux scrape sans libellé → repli par position (idx = N-4).
        detail = {"e_multi": [
            {"combinaison": "1-2-3-4", "rapport": 120.0},
            {"combinaison": "1-2-3-4", "rapport": 24.0},
            {"combinaison": "1-2-3-4", "rapport": 8.0},
        ]}
        r = settle_pari("Multi en 6", [1, 2, 3, 4, 5, 6], self.CL,
                        {"e_multi": 120.0}, 16, rapports_detail=detail)
        assert r["gagne"] and r["rapport_reel"] == 8.0

    def test_mini_multi_en_6_prend_la_bonne_formule(self):
        # Cas réel R3C1 (Mini Multi 10-13 partants) : en 6 = 8 €, jamais 120 (en 4).
        detail = {"e_mini_multi": [
            {"combinaison": "5-4-3-8", "rapport": 120.0, "libelle": "e-Mini Multi en 4"},
            {"combinaison": "5-4-3-8", "rapport": 24.0,  "libelle": "e-Mini Multi en 5"},
            {"combinaison": "5-4-3-8", "rapport": 8.0,   "libelle": "e-Mini Multi en 6"},
        ]}
        r = settle_pari("Mini Multi en 6", [1, 2, 3, 4, 5, 6], self.CL,
                        {"e_mini_multi": 120.0, "e_multi": 99.0}, 12,
                        rapports_detail=detail)
        assert r["gagne"] and r["rapport_reel"] == 8.0

    def test_rapport_en_5_absent_gain_en_attente(self):
        # en 5 sans détail → en attente (pas l'agrégat en-4 = surpaie).
        r = settle_pari("Multi en 5", [1, 2, 3, 4, 5], self.CL,
                        {"e_multi": 120.0}, 16)
        assert r["gagne"] and r["rapport_reel"] is None


class TestSettlePick5:
    CL = _classement(1, 2, 3, 4, 5, 6, 7, 8, 9, 10)   # top5 = {1..5}

    def test_pick5_tendu_gagnant(self):
        r = settle_pari("Pick5", [1, 2, 3, 4, 5], self.CL, {"pick5": 120.0}, 16)
        assert r["gagne"] and r["rapport_reel"] == 120.0
        assert r["gain_mult"] == 1.0

    def test_pick5_champ_6_formule_combinee(self):
        r = settle_pari("Pick5", [1, 2, 3, 4, 5, 6], self.CL, {"pick5": 120.0}, 16)
        assert r["gagne"]
        assert r["gain_mult"] == pytest.approx(1 / math.comb(6, 5))

    def test_pick5_perdant(self):
        r = settle_pari("Pick5", [1, 2, 3, 4, 9], self.CL, {"pick5": 120.0}, 16)
        assert not r["gagne"]


# ── Helpers de classification ────────────────────────────────────────────────
class TestHelpers:
    def test_fam_mini_multi(self):
        assert _fam("Mini Multi en 7") == "Multi en 7"
        assert _fam("Multi en 4") == "Multi en 4"

    def test_high_variance_classification(self):
        assert _is_high_variance({"type_pari": "Trio"})
        assert _is_high_variance({"type_pari": "Pick5"})
        assert _is_high_variance({"type_pari": "Multi en 4"})
        assert _is_high_variance({"type_pari": "Multi en 5"})
        # Multi 6/7 = filet large, PAS haute variance
        assert not _is_high_variance({"type_pari": "Multi en 7"})
        assert not _is_high_variance({"type_pari": "Mini Multi en 6"})
        assert not _is_high_variance({"type_pari": "Couplé Placé"})
