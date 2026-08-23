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
        # Le contrat ×10 vs mise TOTALE porte sur TOUS les tickets, sans exception
        # (décision produit 2026-08-20), y compris les tickets d'appoint à 2€.
        for p in paris:
            assert p["mise"] >= 2
        for p in paris:
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
        for p in paris:
            assert p["mise"] >= 2
        for p in paris:
            assert p["gain_potentiel"] >= 4 * 10 * 0.95, (
                f"{p['type']} gain {p['gain_potentiel']} < ×4 du plan (10€ → ≥40€)"
            )


# ── Tickets d'APPOINT (2026-08-20) ───────────────────────────────────────────
class TestTicketsAppoint:
    """Le reliquat du plan finance des paris D'APPOINT à la mise plancher.

    Décision produit du 2026-08-20 : la tranche du profil se mesure sur la MISE
    TOTALE du plan, SANS EXCEPTION — un ticket d'appoint porte donc exactement le
    même contrat que les autres. À 2€ de mise sur un plan de 10€, cela impose un
    rapport ≥ cible/2, d'où « peu de tickets, mais tous dans la tranche »."""

    COURSE = {
        "nb_partants": 12,
        "paris_disponibles": ["E_SIMPLE_GAGNANT", "E_SIMPLE_PLACE", "E_COUPLE_GAGNANT",
                              "E_COUPLE_PLACE", "E_COUPLE_ORDRE", "E_TRIO", "E_2SUR4"],
    }

    @pytest.mark.parametrize("profil,cible", [
        ("conservateur", 1.8), ("equilibre", 4.0), ("agressif", 10.0)])
    def test_contrat_tenu_par_tous_les_tickets(self, profil, cible):
        """AUCUN ticket affiché ne sort de la tranche, quelle que soit sa mise."""
        for montant in (10, 20, 50):
            d = plan_to_dict(generer_plan(montant, profil, _field(8), self.COURSE,
                                          respect_montant=True))
            paris = [p for niv in d["niveaux"] for p in niv["paris"]]
            assert paris
            if "tranche de gain habituelle" in d["resume_ia"]:
                continue        # filet hors-bande : le contrat est explicitement non garanti
            for p in paris:
                assert p["gain_potentiel"] >= cible * montant * 0.95, (
                    f"{profil}/{montant}€ : {p['type']} rend {p['gain_potentiel']}€ "
                    f"= ×{p['gain_potentiel']/montant:.1f} < ×{cible} de la mise totale")

    @pytest.mark.parametrize("profil", ["conservateur", "equilibre", "agressif"])
    def test_montant_integralement_joue_et_plancher(self, profil):
        d = plan_to_dict(generer_plan(10, profil, _field(8), self.COURSE,
                                      respect_montant=True))
        paris = [p for niv in d["niveaux"] for p in niv["paris"]]
        assert sum(p["mise"] for p in paris) == 10      # aucune réserve fantôme
        assert all(p["mise"] >= 2 for p in paris)       # plancher produit « jamais 1€ »

    def test_quasi_certitude_reste_sur_un_seul_ticket(self):
        """« Si confiant d'un cheval, jouer un seul ; sinon plusieurs » : le NOMBRE de
        paris suit l'analyse. Sur une quasi-certitude (_solo_confident), pas d'appoint."""
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
        assert paris[0]["mise"] == 10, "la mise entière doit aller sur le pari sûr"

    def test_appoint_suit_le_champ_de_la_course(self):
        """Le nb de tickets d'appoint dépend du CHAMP : un grand champ est plus
        incertain et offre plus de combinaisons jouables, un champ réduit non."""
        from services.mise_calculator import _couverture_max
        assert _couverture_max(7) == 2
        assert _couverture_max(8) == 2
        assert _couverture_max(9) == 3
        assert _couverture_max(13) == 3
        assert _couverture_max(18) == 4
        assert _couverture_max(None) == 3        # info absente → valeur médiane

    def test_appoint_alterne_frequence_et_gros_lot(self):
        """L'ordre de financement alterne le pari le plus PROBABLE et celui au plus gros
        RAPPORT, au lieu de financer trois variantes du même pari."""
        from services.mise_calculator import _ordre_couverture
        a = {"proba_gain": 0.30, "rapport_estime": 5.0}    # le plus probable
        b = {"proba_gain": 0.05, "rapport_estime": 60.0}   # le plus gros rapport
        c = {"proba_gain": 0.20, "rapport_estime": 8.0}
        ordre = _ordre_couverture([c, a, b])
        assert ordre[0] is a and ordre[1] is b, [
            (x["proba_gain"], x["rapport_estime"]) for x in ordre]
        assert len(ordre) == 3 and len({id(x) for x in ordre}) == 3

    CHAMP_LARGE = [(0.16, 5.5), (0.14, 6.5), (0.12, 8.0), (0.10, 11.0), (0.09, 13.0),
                   (0.08, 15.0), (0.07, 18.0), (0.06, 22.0), (0.05, 28.0), (0.04, 35.0),
                   (0.04, 42.0), (0.03, 55.0), (0.03, 70.0), (0.02, 90.0)]

    def _champ(self):
        return [{"numero": i + 1, "nom": f"H{i+1}", "nom_cheval": f"H{i+1}",
                 "proba_top1": p, "proba_top3": min(1.0, p * 2.2),
                 "cote_pmu": c, "non_partant": False}
                for i, (p, c) in enumerate(self.CHAMP_LARGE)]

    def test_risque_grand_champ_propose_plusieurs_paris(self):
        """Plusieurs tickets DANS la tranche, tous ancrés sur les 2 premiers prédits.

        Le nombre de tickets dépend du budget, pas seulement du champ : la cible ×10
        du risqué impose `mise ≥ cible / rapport`, et une combinaison ANCRÉE sur les
        2 premiers paie moins qu'un trio d'outsiders — donc coûte plus cher par ticket.
        C'est le prix assumé de l'ancrage : mesure du 2026-08-23 (winsorisée), un Trio
        contenant les 2 premiers prédits rend −8,1 % contre −75,5 % sans. Trois tickets
        d'outsiders à 2€ étaient trois façons de perdre.
        """
        champ = self._champ()
        course = dict(self.COURSE, nb_partants=len(self.CHAMP_LARGE))
        for montant, mini in ((10, 2), (30, 3)):
            d = plan_to_dict(generer_plan(montant, "agressif", champ, course,
                                          respect_montant=True))
            paris = [p for niv in d["niveaux"] for p in niv["paris"]]
            assert len(paris) >= mini, (
                f"grand champ risqué {montant}€ : seulement {len(paris)} pari(s)")
            assert sum(p["mise"] for p in paris) == montant
            for p in paris:
                assert p["gain_potentiel"] >= montant * 10 * 0.95, (
                    f"{p['type']} rend {p['gain_potentiel']}€ < ×10 du plan")

    def test_risque_etale_plusieurs_combinaisons_sur_la_meme_ancre(self):
        """Deux combinaisons ancrées ne diffèrent que par leur pied libre : c'est la
        structure voulue, pas un doublon. La règle anti-doublon « ne diffèrent que d'un
        cheval » ne doit donc pas les confondre, sinon le risqué retombe à un ticket."""
        champ = self._champ()
        course = dict(self.COURSE, nb_partants=len(self.CHAMP_LARGE))
        d = plan_to_dict(generer_plan(30, "agressif", champ, course,
                                      respect_montant=True))
        combos = [p for niv in d["niveaux"] for p in niv["paris"]
                  if len(p["chevaux"]) >= 2]
        assert len(combos) >= 2, f"une seule combinaison : {combos}"
        # Même appui (les 2 premiers prédits), pieds libres différents.
        libres = {tuple(sorted(c["numero"] for c in p["chevaux"])) for p in combos}
        assert len(libres) == len(combos), "combinaisons identiques"

    def test_plafond_de_rang_suit_le_classement(self):
        """Le plan doit se correler au CLASSEMENT de l'IA (demande user 2026-08-20).

        Mesure sur 459 courses reglees : le vrai gagnant est dans le top-3 predit 61,7 %
        du temps, dans le top-8 95,9 %. Jouer un cheval au-dela, c'est parier contre le
        modele qui produit le pronostic."""
        from services.mise_calculator import _rang_max_effectif, PROFIL_CONFIG
        # bornes par profil, du plus strict au plus large
        assert PROFIL_CONFIG["conservateur"]["rang_max"] == 5
        assert PROFIL_CONFIG["equilibre"]["rang_max"] == 6
        assert PROFIL_CONFIG["agressif"]["rang_max"] == 8
        # champ large : c'est le plafond du profil qui borne
        assert _rang_max_effectif(8, 20) == 8
        # champ reduit : le rang 8 serait le dernier cheval -> le champ borne
        assert _rang_max_effectif(8, 8) == 5
        assert _rang_max_effectif(8, 9) == 6
        # plancher 4 : un champ minuscule ne doit pas tuer tout pari combine
        assert _rang_max_effectif(8, 4) == 4
        assert _rang_max_effectif(None, 12) is None

    def test_aucun_cheval_hors_du_classement(self):
        """Aucun cheval joue ne doit sortir du plafond de rang du profil (marge de deux
        crans pour les paris PLACE : se placer est bien plus frequent que gagner)."""
        from services.mise_calculator import (
            _rang_max_effectif, PROFIL_CONFIG, RANG_MAX_BONUS_PLACE)
        champ = _field(8)
        rang = {int(p["numero"]): i for i, p in enumerate(
            sorted(champ, key=lambda x: float(x["proba_top1"]), reverse=True), start=1)}
        for profil in ("conservateur", "equilibre", "agressif"):
            d = plan_to_dict(generer_plan(10, profil, champ, self.COURSE,
                                          respect_montant=True))
            paris = [p for niv in d["niveaux"] for p in niv["paris"]]
            if "tranche de gain habituelle" in d["resume_ia"]:
                continue          # filet hors-bande : gates explicitement relachees
            plafond = _rang_max_effectif(PROFIL_CONFIG[profil]["rang_max"],
                                         self.COURSE["nb_partants"])
            for pa in paris:
                marge = RANG_MAX_BONUS_PLACE if "Placé" in pa["type"] else 0
                for h in pa["chevaux"]:
                    assert rang[int(h["numero"])] <= plafond + marge, (
                        f"{profil}/{pa['type']} joue le rang "
                        f"{rang[int(h['numero'])]} > plafond {plafond + marge}")

    def test_pas_de_pari_duplique(self):
        d = plan_to_dict(generer_plan(20, "agressif", _field(8), self.COURSE,
                                      respect_montant=True))
        paris = [p for niv in d["niveaux"] for p in niv["paris"]]
        vus = set()
        for p in paris:
            cle = (p["type"], frozenset(c["numero"] for c in p["chevaux"]))
            assert cle not in vus, f"pari dupliqué : {cle}"
            vus.add(cle)

    def test_jamais_deux_simple_place(self):
        """Règle produit : un Simple Placé paie moins que la mise totale → deux tickets
        dont un seul passe = perdant. L'appoint ne doit pas la contourner."""
        for profil in ("conservateur", "equilibre"):
            d = plan_to_dict(generer_plan(10, profil, _field(8), self.COURSE,
                                          respect_montant=True))
            paris = [p for niv in d["niveaux"] for p in niv["paris"]]
            assert sum(1 for p in paris if p["type"] == "Simple Placé") <= 1


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


# ── Ancrage des combinaisons sur les 2 premiers du classement ────────────────

class TestAncrageTop2:
    """Mesure du 2026-08-23 sur les conseils réglés (winsorisée à 50× la mise) :

        Couplé Gagnant  avec les 2 premiers prédits : 13,8 % de réussite, ROI  +0,5 %
                        sans                        :  3,8 %,             ROI −13,9 %
        Trio            avec                        :  3,7 %,             ROI  −8,1 %
                        sans                        :  0,7 %,             ROI −75,5 %

    Le plafond de rang borne le PIRE cheval ; l'ancrage impose un POINT D'APPUI. C'est
    le second qui décide du rendement."""

    COURSE = {"course_id": "T1", "nb_partants": 12, "discipline": "Attelé"}

    def test_le_filtre_ne_garde_que_les_combinaisons_ancrees(self):
        from services.mise_calculator import _filtrer_ancrage_top2
        simple = {"chevaux": [{"numero": 1}]}
        ancre = {"chevaux": [{"numero": 1}, {"numero": 2}], "_ancre_top2": True}
        libre = {"chevaux": [{"numero": 3}, {"numero": 4}], "_ancre_top2": False}
        out = _filtrer_ancrage_top2([simple, ancre, libre], {"ancrage_top2": True})
        assert out == [simple, ancre]           # le simple n'est jamais touché

    def test_repli_total_si_aucune_combinaison_ancree(self):
        """Promesse produit : un plan sur CHAQUE course. Sans candidat ancré, on ne
        prive de rien — la liste revient telle quelle."""
        from services.mise_calculator import _filtrer_ancrage_top2
        libres = [{"chevaux": [{"numero": 3}, {"numero": 4}], "_ancre_top2": False},
                  {"chevaux": [{"numero": 5}, {"numero": 6}], "_ancre_top2": False}]
        assert _filtrer_ancrage_top2(list(libres), {"ancrage_top2": True}) == libres

    def test_desactivable_par_profil(self):
        from services.mise_calculator import _filtrer_ancrage_top2
        cands = [{"chevaux": [{"numero": 1}, {"numero": 2}], "_ancre_top2": True},
                 {"chevaux": [{"numero": 3}, {"numero": 4}], "_ancre_top2": False}]
        assert _filtrer_ancrage_top2(list(cands), {"ancrage_top2": False}) == cands

    def test_les_trois_profils_ancrent_par_defaut(self):
        from services.mise_calculator import PROFIL_CONFIG, _effective_config
        for profil in PROFIL_CONFIG:
            assert _effective_config(profil, 0.0)["ancrage_top2"] is True

    def test_les_combinaisons_du_plan_contiennent_les_deux_premiers(self):
        champ = _field(12)
        rang = {int(p["numero"]): i for i, p in enumerate(
            sorted(champ, key=lambda x: float(x["proba_top1"]), reverse=True), start=1)}
        top2 = {n for n, r in rang.items() if r <= 2}
        for profil in ("conservateur", "equilibre", "agressif"):
            d = plan_to_dict(generer_plan(30, profil, champ, self.COURSE,
                                          respect_montant=True))
            for niv in d["niveaux"]:
                for p in niv["paris"]:
                    nums = {c["numero"] for c in p["chevaux"]}
                    if len(nums) >= 2:
                        assert top2 <= nums, (
                            f"{profil} : {p['type']} {sorted(nums)} sans appui "
                            f"sur les 2 premiers {sorted(top2)}")

    def test_le_pied_libre_rentable_prime_sur_le_troisieme_favori(self):
        """Mesure du 2026-08-23 (winsorisée) sur les trios ancrés, par rang du 3ᵉ pied :
        rang 3 → −80 % de ROI, rangs 4-5 → −21 %, rangs 6-8 → +92 %, rang 9+ → −100 %.
        À rapport et probabilité IDENTIQUES, le classement doit donc préférer le pied
        libre au rang 6-8 au 3ᵉ favori."""
        from services.mise_calculator import _select_conviction, _effective_config

        def _cand(numero_libre, rang_libre):
            return {"type_pari": "Trio",
                    "chevaux": [{"numero": 1}, {"numero": 2}, {"numero": numero_libre}],
                    "proba_gain": 0.02, "rapport_estime": 40.0, "ev": 0.0, "edge": 0.0,
                    "_ancre_top2": True, "_ancre_nums": frozenset({1, 2}),
                    "_rang_hors_ancre": rang_libre, "_rang_max": rang_libre}

        palier = {"nom": "petit", "max_bets": 3, "min_stake": 3,
                  "favor_value": True, "cap_spec": 0.6}
        ordre = _select_conviction([_cand(3, 3), _cand(7, 7)], 30, palier,
                                   _effective_config("agressif", 0.0), {})
        assert ordre and ordre[0]["_rang_hors_ancre"] == 7, (
            "le 3ᵉ pied au rang 6-8 doit primer sur le 3ᵉ favori")
