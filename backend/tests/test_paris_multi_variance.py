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
        plafond = int(montant * 0.35)          # var_cap risqué resserré à 0.35
        paris = [p for niv in d["niveaux"] for p in niv["paris"]]
        if len(paris) >= 2:                    # à 1 seul ticket le plafond est inerte
            for p in paris:
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

    def test_risque_spread_plusieurs_mises(self):
        # DEMANDE USER : « plus de mises différentes en risqué » — fini le 10€ sur un
        # seul Simple Gagnant. Avec 10€ et un champ complet de candidats, le plan
        # risqué doit répartir sur ≥2 tickets, chacun ≥ 2€ (plancher produit) et
        # chaque ticket GAGNANT rend ≥ ×10 de la MISE TOTALE du plan (contrat
        # 2026-07-02 : 10€ joués → tout gagnant rend ≥ 100€, peu importe le type).
        plan = generer_plan(10, "agressif", _field(8), self.COURSE, respect_montant=True)
        d = plan_to_dict(plan)
        paris = [p for niv in d["niveaux"] for p in niv["paris"]]
        assert len(paris) >= 2, f"1 seul ticket risqué : {paris}"
        assert sum(p["mise"] for p in paris) == 10          # tout le montant joué
        # Le contrat ×10 vs mise TOTALE porte sur les tickets PRINCIPAUX. Les tickets de
        # COUVERTURE (petites mises ajoutées pour multiplier les chances de toucher) ne le
        # portent pas et sont explicitement marqués comme tels.
        principaux = [p for p in paris if not p["couverture"]]
        assert principaux, "plan sans aucun ticket principal"
        for p in paris:
            assert p["mise"] >= 2
        for p in principaux:
            assert p["gain_potentiel"] >= 10 * 10 * 0.95, (
                f"{p['type']} gain {p['gain_potentiel']} < ×10 du plan (10€ → ≥100€)"
            )

    def test_modere_spread_et_gain_vs_total(self):
        # Modéré : chaque ticket GAGNANT rend ≥ ×4 de la MISE TOTALE du plan
        # (10€ joués → tout gagnant rend ≥ 40€).
        plan = generer_plan(10, "equilibre", _field(8), self.COURSE, respect_montant=True)
        d = plan_to_dict(plan)
        paris = [p for niv in d["niveaux"] for p in niv["paris"]]
        assert paris, "plan modéré vide"
        assert sum(p["mise"] for p in paris) == 10
        principaux = [p for p in paris if not p["couverture"]]
        assert principaux, "plan sans aucun ticket principal"
        for p in paris:
            assert p["mise"] >= 2
        for p in principaux:
            assert p["gain_potentiel"] >= 4 * 10 * 0.95, (
                f"{p['type']} gain {p['gain_potentiel']} < ×4 du plan (10€ → ≥40€)"
            )


# ── Tickets de COUVERTURE (2026-08-20) ───────────────────────────────────────
class TestCouverture:
    """Depuis la calibration des rapports et des probabilités (19/08), le contrat
    « ×g de la mise TOTALE » ne finançait plus qu'UN ticket par course (mesuré en
    base : 1,55 → 1,00 pari/plan en modéré). Une seule chance de toucher par course.
    On finance désormais des tickets de COUVERTURE sur le reliquat : le contrat reste
    tenu par les tickets principaux, la couverture ajoute des chances."""

    COURSE = {
        "nb_partants": 12,
        "paris_disponibles": ["E_SIMPLE_GAGNANT", "E_SIMPLE_PLACE", "E_COUPLE_GAGNANT",
                              "E_COUPLE_PLACE", "E_COUPLE_ORDRE", "E_TRIO", "E_2SUR4"],
    }

    @pytest.mark.parametrize("profil,cible", [("equilibre", 4.0), ("agressif", 10.0)])
    def test_contrat_tenu_par_les_principaux(self, profil, cible):
        d = plan_to_dict(generer_plan(10, profil, _field(8), self.COURSE,
                                      respect_montant=True))
        paris = [p for niv in d["niveaux"] for p in niv["paris"]]
        principaux = [p for p in paris if not p["couverture"]]
        assert principaux
        if "tranche de gain habituelle" in d["resume_ia"]:
            pytest.skip("filet hors-bande : le contrat est explicitement non garanti")
        for p in principaux:
            assert p["gain_potentiel"] >= cible * 10 * 0.95

    @pytest.mark.parametrize("profil", ["conservateur", "equilibre", "agressif"])
    def test_montant_integralement_joue_et_plancher(self, profil):
        d = plan_to_dict(generer_plan(10, profil, _field(8), self.COURSE,
                                      respect_montant=True))
        paris = [p for niv in d["niveaux"] for p in niv["paris"]]
        assert sum(p["mise"] for p in paris) == 10      # aucune réserve fantôme
        assert all(p["mise"] >= 2 for p in paris)       # plancher produit « jamais 1€ »

    def test_couverture_annoncee_dans_le_resume(self):
        """Si un ticket de couverture est financé, le résumé le DIT — sinon le joueur
        croit que tous les tickets visent le multiplicateur du profil."""
        d = plan_to_dict(generer_plan(20, "equilibre", _field(8), self.COURSE,
                                      respect_montant=True))
        paris = [p for niv in d["niveaux"] for p in niv["paris"]]
        couv = [p for p in paris if p["couverture"]]
        assert couv, "aucune couverture financée sur ce champ (le test perdrait son objet)"
        assert "COUVERTURE" in d["resume_ia"]
        for p in couv:
            assert any("COUVERTURE" in r for r in p["raisons"]), (
                "un ticket de couverture doit s'annoncer dans ses raisons")

    @pytest.mark.parametrize("profil", ["equilibre", "agressif"])
    def test_plan_pas_reduit_a_une_mise_unique(self, profil):
        """SYMPTÔME D'ORIGINE (20/08) : « il n'y a plus que des mises de 10€ » — un seul
        ticket absorbait tout le plan. Sans quasi-certitude, modéré et risqué doivent
        proposer plusieurs paris DISTINCTS. (Les mises peuvent être égales quand deux
        tickets contractuels ont le même besoin — c'est légitime ; ce qui ne l'est pas,
        c'est de tout mettre sur un seul ticket.)"""
        d = plan_to_dict(generer_plan(10, profil, _field(8), self.COURSE,
                                      respect_montant=True))
        paris = [p for niv in d["niveaux"] for p in niv["paris"]]
        assert len(paris) >= 2, f"{profil} : plan réduit à un ticket unique : {paris}"
        cles = {(p["type"], frozenset(c["numero"] for c in p["chevaux"])) for p in paris}
        assert len(cles) == len(paris), f"{profil} : paris non distincts"

    def test_couverture_financee_quand_le_contrat_ne_tient_qu_un_ticket(self):
        """Quand le contrat ×g ne finance qu'UN ticket et que le modèle n'est pas sûr,
        la réserve de couverture doit produire au moins un pari supplémentaire."""
        d = plan_to_dict(generer_plan(20, "equilibre", _field(8), self.COURSE,
                                      respect_montant=True))
        paris = [p for niv in d["niveaux"] for p in niv["paris"]]
        assert any(p["couverture"] for p in paris)
        assert len({p["mise"] for p in paris}) >= 2, "mises toutes identiques"

    def test_quasi_certitude_reste_sur_un_seul_ticket(self):
        """Demande user : « si confiant d'un cheval, jouer un seul ; sinon plusieurs ».
        Le NOMBRE de paris suit l'analyse de la course. Quand le meilleur pari est une
        quasi-certitude (_solo_confident), on ne dilue pas en couverture."""
        ecrase = [(0.62, 1.5), (0.12, 7.0), (0.09, 10.0), (0.06, 15.0),
                  (0.05, 20.0), (0.03, 30.0), (0.02, 45.0), (0.01, 70.0)]
        champ = [{"numero": i + 1, "nom": f"H{i+1}", "nom_cheval": f"H{i+1}",
                  "proba_top1": p, "proba_top3": min(1.0, p * 2.2),
                  "cote_pmu": c, "non_partant": False}
                 for i, (p, c) in enumerate(ecrase)]
        d = plan_to_dict(generer_plan(10, "conservateur", champ, self.COURSE,
                                      respect_montant=True))
        paris = [p for niv in d["niveaux"] for p in niv["paris"]]
        assert len(paris) == 1, f"mise diluée sur une quasi-certitude : {paris}"
        assert not paris[0]["couverture"]
        assert paris[0]["mise"] == 10, "la mise entière doit aller sur le pari sûr"

    def test_course_ouverte_diversifie(self):
        """Contrepartie du test précédent : sans quasi-certitude, modéré et risqué
        proposent PLUSIEURS paris différents."""
        ouvert = [(0.16, 5.5), (0.15, 6.0), (0.14, 6.5), (0.13, 7.0),
                  (0.12, 8.0), (0.11, 9.0), (0.10, 11.0), (0.09, 13.0)]
        champ = [{"numero": i + 1, "nom": f"H{i+1}", "nom_cheval": f"H{i+1}",
                  "proba_top1": p, "proba_top3": min(1.0, p * 2.2),
                  "cote_pmu": c, "non_partant": False}
                 for i, (p, c) in enumerate(ouvert)]
        for profil in ("equilibre", "agressif"):
            d = plan_to_dict(generer_plan(10, profil, champ, self.COURSE,
                                          respect_montant=True))
            paris = [p for niv in d["niveaux"] for p in niv["paris"]]
            assert len(paris) >= 2, f"{profil} : 1 seul pari sur une course ouverte"
            cles = {(p["type"], frozenset(c["numero"] for c in p["chevaux"]))
                    for p in paris}
            assert len(cles) == len(paris), f"{profil} : paris non distincts"

    def test_couverture_ne_duplique_pas_un_pari_principal(self):
        d = plan_to_dict(generer_plan(20, "equilibre", _field(8), self.COURSE,
                                      respect_montant=True))
        paris = [p for niv in d["niveaux"] for p in niv["paris"]]
        vus = set()
        for p in paris:
            cle = (p["type"], frozenset(c["numero"] for c in p["chevaux"]))
            assert cle not in vus, f"pari dupliqué en couverture : {cle}"
            vus.add(cle)

    def test_jamais_deux_simple_place(self):
        """Règle produit : un Simple Placé paie moins que la mise totale → deux tickets
        dont un seul passe = perdant. La couverture ne doit pas la contourner."""
        for profil in ("conservateur", "equilibre"):
            d = plan_to_dict(generer_plan(10, profil, _field(8), self.COURSE,
                                          respect_montant=True))
            paris = [p for niv in d["niveaux"] for p in niv["paris"]]
            assert sum(1 for p in paris if p["type"] == "Simple Placé") <= 1

    def test_couverture_reste_au_plancher_les_mises_different(self):
        """Le reliquat grossit les tickets CONTRACTUELS, pas la couverture : c'est ce
        qui produit des mises visiblement différentes dans le plan."""
        d = plan_to_dict(generer_plan(20, "equilibre", _field(8), self.COURSE,
                                      respect_montant=True))
        paris = [p for niv in d["niveaux"] for p in niv["paris"]]
        couv = [p for p in paris if p["couverture"]]
        principaux = [p for p in paris if not p["couverture"]]
        assert couv and principaux
        assert all(p["mise"] == 2 for p in couv), "la couverture reste au plancher 2€"
        assert max(p["mise"] for p in principaux) > min(p["mise"] for p in couv)


# ── Cap modèle/marché des probas chevaux (combos) — audit ROI 2026-07-02 ─────
class TestCapModeleMarche:
    def test_cap_outsider_sur_evalue(self):
        """Cheval cote 12 (marché ~7%) que le modèle voit à 30% → capé à 1.55× le
        marché puis renormalisé. Les favoris (cote < 4) ne sont pas touchés."""
        import numpy as np
        from ml.combo_bets import _cap_model_probas, CAP_RATIO
        cotes = np.array([2.0, 5.0, 12.0])
        pm = 1.0 / cotes
        pm = pm / pm.sum()
        p1 = np.array([0.50, 0.20, 0.30])
        out = _cap_model_probas(p1, pm, cotes)
        assert abs(out.sum() - 1.0) < 1e-9
        # l'outsider capé : sa proba relative ne dépasse plus 1.55× le marché
        # (comparaison AVANT renormalisation : part brute capée)
        assert p1[2] > CAP_RATIO * pm[2]              # était sur-évalué
        assert out[2] < p1[2]                          # a bien été réduit
        assert out[0] > p1[0] - 1e-9                   # favori non raboté (renorm ↑)

    def test_cap_neutre_si_modele_sous_marche(self):
        import numpy as np
        from ml.combo_bets import _cap_model_probas
        cotes = np.array([3.0, 6.0, 10.0])
        pm = 1.0 / cotes
        pm = pm / pm.sum()
        p1 = pm.copy()                                 # modèle = marché → rien à caper
        out = _cap_model_probas(p1, pm, cotes)
        assert np.allclose(out, p1)

    def test_cap_flag_off(self, monkeypatch):
        import numpy as np
        import ml.algo_flags as af
        from ml.combo_bets import _cap_model_probas
        monkeypatch.setenv("BT_COMBO_MARKET_CAP", "0")
        monkeypatch.setattr(af, "FLAGS", af.AlgoFlags())
        cotes = np.array([2.0, 12.0])
        pm = 1.0 / cotes
        pm = pm / pm.sum()
        p1 = np.array([0.5, 0.5])
        out = _cap_model_probas(p1, pm, cotes)
        assert np.allclose(out, p1)                    # rollback : identité


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
