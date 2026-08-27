"""Tests algo d'apprentissage 2026-06-29 :
- TRANCHES de GAIN / MISE TOTALE par profil (prudent ×1.8–5 / modéré ×4–15 / risqué ≥10,
  demande user 2026-07-13) : chaque ticket GAGNANT reste dans la bande de son profil,
  mesurée sur la mise TOTALE du plan (y compris mise fractionnée en plusieurs tickets) ;
- CALIBRATION estimé→réel du rapport (rapport_realization_factor) : recale le rapport
  sur les paiements PMU réels appris → le gate de bande s'applique au gain réellement
  attendu (un Placé estimé ×1.9 mais payé ×1.3 tombe sous la bande prudent → écarté) ;
- neutralité totale (cold-start) tant qu'aucune calibration n'est apprise.
"""
import pytest

from services.bet_catalog import derive_bet_flags
from services.mise_calculator import (
    generer_plan, plan_to_dict, PROFIL_CONFIG, reprice_plan_live,
)
from ml.signal_performance import rapport_realization_factor
from services.hippodromes import ZONE_ETRANGER, ZONE_FRANCE, zone_depuis_pays


# ── Champ synthétique riche (tous types offerts) ─────────────────────────────
def _field(n=10):
    rows = [(0.30, 2.8), (0.20, 4.2), (0.15, 6.0), (0.12, 9.0), (0.08, 12.0),
            (0.06, 18.0), (0.05, 24.0), (0.04, 32.0), (0.03, 41.0), (0.02, 55.0)][:n]
    return [{"numero": i + 1, "nom": f"H{i+1}", "nom_cheval": f"H{i+1}",
             "proba_top1": p, "proba_top3": min(1.0, p * 2.2),
             "cote_pmu": c, "non_partant": False}
            for i, (p, c) in enumerate(rows)]


COURSE = {
    "nb_partants": 16,
    "paris_disponibles": ["E_SIMPLE_GAGNANT", "E_SIMPLE_PLACE", "E_COUPLE_GAGNANT",
                          "E_COUPLE_PLACE", "E_COUPLE_ORDRE", "E_TRIO", "E_MULTI",
                          "E_PICK5", "E_TIERCE", "E_QUARTE_PLUS", "E_QUINTE_PLUS",
                          "E_DEUX_SUR_QUATRE"],
    "est_tierce": True, "est_quarte": True, "est_quinte": True, "est_2sur4": True,
}


def _rapports_selectionnes(plan_d):
    """Rapport effectif de chaque pari du plan = gain_potentiel / mise (rapport DU TICKET)."""
    out = []
    for niv in plan_d["niveaux"]:
        for p in niv["paris"]:
            if p["mise"] > 0:
                out.append((p["type"], p["gain_potentiel"] / p["mise"]))
    return out


def _gains_vs_total(plan_d):
    """Multiple de GAIN / MISE TOTALE de chaque ticket = gain_potentiel / montant_total.
    C'est la grandeur de la BANDE produit (demande user 2026-07-13), pas le rapport du ticket.

    TOUS les tickets sont concernés, sans exception (décision produit 2026-08-20) : un
    ticket affiché dans un plan respecte la tranche du profil, quelle que soit sa mise."""
    total = plan_d["montant_total"] or 1
    out = []
    for niv in plan_d["niveaux"]:
        for p in niv["paris"]:
            if p["mise"] > 0:
                out.append((p["type"], p["gain_potentiel"] / total))
    return out


# ── 1. Fonction PURE de calibration ──────────────────────────────────────────
class TestFacteurCalibration:
    def test_neutre_sans_table(self):
        assert rapport_realization_factor("conservateur", "Simple Placé", None) == 1.0
        assert rapport_realization_factor("conservateur", "Simple Placé", {}) == 1.0

    def test_neutre_profil_ou_type_inconnu(self):
        calib = {"profils": {"conservateur": {"Simple Placé": {"factor": 0.7}}}}
        assert rapport_realization_factor("agressif", "Simple Placé", calib) == 1.0
        assert rapport_realization_factor("conservateur", "Trio", calib) == 1.0
        assert rapport_realization_factor(None, None, calib) == 1.0

    def test_lookup_facteur_appris(self):
        calib = {"profils": {"conservateur": {"Simple Placé": {"factor": 0.65}}}}
        assert rapport_realization_factor("conservateur", "Simple Placé", calib) == 0.65

    def test_fallback_global_par_type(self):
        """Couple (profil × type) sans facteur appris → POOL GLOBAL du type (tous
        profils). Cas réel : Couplé Ordre 5 gagnants en risqué (facteur neutre) mais
        21 gagnants tous profils → surestimation ×3.8 enfin corrigée."""
        calib = {"profils": {"agressif": {"Couplé Ordre": {"factor": 1.0, "n_win": 5}}},
                 "global": {"Couplé Ordre": {"factor": 0.55, "n_win": 21}}}
        assert rapport_realization_factor("agressif", "Couplé Ordre", calib) == 0.55
        # profil sans entrée du tout → global aussi
        assert rapport_realization_factor("equilibre", "Couplé Ordre", calib) == 0.55

    def test_facteur_profil_prime_sur_global(self):
        calib = {"profils": {"agressif": {"Couplé Gagnant": {"factor": 0.713}}},
                 "global": {"Couplé Gagnant": {"factor": 0.90}}}
        assert rapport_realization_factor("agressif", "Couplé Gagnant", calib) == 0.713


# ── 1 bis. ZONE DE MARCHÉ (France / étranger) ────────────────────────────────
# Le rapport parimutuel se forme sur le marché où l'argent entre. Mesuré sur les
# pronostics figés puis réglés : Simple Gagnant 0,939 en France contre 0,807 à
# l'étranger ; Simple Placé 0,977 contre 0,883. Sans cette clé, un facteur moyen
# unique mélangeait les deux marchés — et 52 % des paris prudents gagnants sur
# réunion étrangère payaient sous la tranche ×1,8 du profil (22 % en France).
class TestZoneMarche:
    def test_pays_vers_zone(self):
        assert zone_depuis_pays("FRA") == ZONE_FRANCE
        assert zone_depuis_pays("fra") == ZONE_FRANCE
        assert zone_depuis_pays("FR") == ZONE_FRANCE      # lignes anciennes
        assert zone_depuis_pays("USA") == ZONE_ETRANGER
        assert zone_depuis_pays("GBR") == ZONE_ETRANGER

    def test_pays_inconnu_ne_devine_aucune_zone(self):
        """None plutôt que « étranger » : un pays manquant ne prouve rien, et se
        tromper appliquerait le facteur étranger à des courses françaises."""
        for valeur in (None, "", "  ", "UNK", "unknown"):
            assert zone_depuis_pays(valeur) is None

    def test_zone_prime_sur_profil_et_global(self):
        calib = {"zones": {ZONE_ETRANGER: {"Simple Gagnant": {"factor": 0.80}}},
                 "profils": {"agressif": {"Simple Gagnant": {"factor": 0.95}}},
                 "global": {"Simple Gagnant": {"factor": 0.93}}}
        assert rapport_realization_factor(
            "agressif", "Simple Gagnant", calib, zone=ZONE_ETRANGER) == 0.80
        # même calibration, zone France non apprise → on redescend sur le profil
        assert rapport_realization_factor(
            "agressif", "Simple Gagnant", calib, zone=ZONE_FRANCE) == 0.95

    def test_zone_neutre_redescend_sur_profil_puis_global(self):
        """Facteur 1.0 = « rien d'appris ici » (< RC_MIN_WINS gagnants) → niveau suivant."""
        calib = {"zones": {ZONE_ETRANGER: {"Trio": {"factor": 1.0, "n_win": 3}}},
                 "profils": {"agressif": {"Trio": {"factor": 1.0, "n_win": 5}}},
                 "global": {"Trio": {"factor": 0.82, "n_win": 35}}}
        assert rapport_realization_factor(
            "agressif", "Trio", calib, zone=ZONE_ETRANGER) == 0.82

    def test_sans_zone_comportement_inchange(self):
        """Non-régression : un appel sans zone lit exactement ce qu'il lisait avant."""
        calib = {"zones": {ZONE_ETRANGER: {"Simple Placé": {"factor": 0.50}}},
                 "profils": {"conservateur": {"Simple Placé": {"factor": 0.90}}},
                 "global": {"Simple Placé": {"factor": 0.96}}}
        assert rapport_realization_factor("conservateur", "Simple Placé", calib) == 0.90
        assert rapport_realization_factor(None, "Simple Placé", calib) == 0.96

    def test_zone_appliquee_au_plan_et_bande_toujours_respectee(self):
        """Bout en bout : la zone rabote les rapports AVANT les gates, donc le plan
        étranger est plus sévère que le plan France — et dans les deux cas aucun
        ticket ne sort de la tranche du profil."""
        types_eq = list(PROFIL_CONFIG["equilibre"]["types"])
        calib = {"zones": {ZONE_ETRANGER: {t: {"factor": 0.55} for t in types_eq},
                           ZONE_FRANCE: {t: {"factor": 1.0} for t in types_eq}}}
        gmin = PROFIL_CONFIG["equilibre"]["gain_cible_mult"]
        gmax = PROFIL_CONFIG["equilibre"]["gain_cible_max"]
        etr = plan_to_dict(generer_plan(20, "equilibre", _field(10), COURSE,
                                        respect_montant=True, rapport_calib=calib,
                                        zone=ZONE_ETRANGER))
        fra = plan_to_dict(generer_plan(20, "equilibre", _field(10), COURSE,
                                        respect_montant=True, rapport_calib=calib,
                                        zone=ZONE_FRANCE))
        for plan_d, nom in ((etr, "etranger"), (fra, "france")):
            ratios = _gains_vs_total(plan_d)
            assert ratios, f"plan {nom} vide"
            for t, g in ratios:
                assert g >= gmin - 0.1, f"{nom}/{t} ×{g:.2f} sous la bande {gmin}"
                assert g <= gmax + 0.1, f"{nom}/{t} ×{g:.2f} au-dessus de {gmax}"
        # La zone étranger doit RÉELLEMENT changer quelque chose (sélection ou rapports).
        assert _rapports_selectionnes(etr) != _rapports_selectionnes(fra)

    def test_zone_sans_calibration_reste_neutre(self):
        """Cold-start : tant que rien n'est appris par zone, passer une zone ne change
        rien au plan (aucune correction inventée)."""
        a = plan_to_dict(generer_plan(20, "agressif", _field(10), COURSE,
                                      respect_montant=True))
        b = plan_to_dict(generer_plan(20, "agressif", _field(10), COURSE,
                                      respect_montant=True, zone=ZONE_ETRANGER))
        assert _rapports_selectionnes(a) == _rapports_selectionnes(b)


# ── 2. TRANCHES respectées par profil (sans calibration) ─────────────────────
class TestTranchesRespectees:
    @pytest.mark.parametrize("profil", ["conservateur", "equilibre", "agressif"])
    def test_aucun_pari_hors_bande(self, profil):
        # BANDE sur le GAIN / MISE TOTALE (demande user 2026-07-13) : gmin = gain_cible_mult,
        # gmax = gain_cible_max. Vaut aussi pour une mise fractionnée (chaque ticket ∈ bande).
        cfg = PROFIL_CONFIG[profil]
        gmin = cfg["gain_cible_mult"]
        gmax = cfg.get("gain_cible_max")
        plan = plan_to_dict(generer_plan(20, profil, _field(10), COURSE,
                                         respect_montant=True))
        ratios = _gains_vs_total(plan)
        assert ratios, "plan vide inattendu sur un champ riche"
        for t, g in ratios:
            # tolérance d'arrondi (gain_potentiel arrondi à l'euro sur 20€ → ±0.05)
            assert g >= gmin - 0.1, f"{profil}/{t} gain ×{g:.2f} du total < bande {gmin}"
            if gmax is not None:
                assert g <= gmax + 0.1, f"{profil}/{t} gain ×{g:.2f} du total > bande {gmax}"

    def test_risque_jamais_sous_x10(self):
        """Demande user : un ticket risqué gagnant ne doit JAMAIS rendre < ×10 du total."""
        plan = plan_to_dict(generer_plan(20, "agressif", _field(10), COURSE,
                                         respect_montant=True))
        for t, g in _gains_vs_total(plan):
            assert g >= 10 - 0.1, f"risqué/{t} ×{g:.2f} du total sous la bande ×10"

    def test_bandes_profils(self):
        """Prudent ×1.8–5, modéré ×4–15, risqué ≥10. Les bandes
        prudent/modéré se chevauchent sur 4–5 et modéré/risqué sur 10–15 ;
        la séparation stricte n'est donc pas requise."""
        assert PROFIL_CONFIG["conservateur"]["rapport_min"] == 1.8
        assert PROFIL_CONFIG["conservateur"]["rapport_max"] == 5.0
        assert PROFIL_CONFIG["conservateur"]["gain_cible_mult"] == 1.8
        assert PROFIL_CONFIG["conservateur"]["gain_cible_max"] == 5.0
        assert PROFIL_CONFIG["equilibre"]["rapport_min"] == 4.0
        assert PROFIL_CONFIG["equilibre"]["rapport_max"] == 15.0
        assert PROFIL_CONFIG["equilibre"]["gain_cible_mult"] == 4.0
        assert PROFIL_CONFIG["equilibre"]["gain_cible_max"] == 15.0
        assert PROFIL_CONFIG["agressif"]["rapport_min"] == 10.0
        assert PROFIL_CONFIG["agressif"]["gain_cible_mult"] == 10.0
        assert PROFIL_CONFIG["agressif"]["gain_cible_max"] is None

    @pytest.mark.parametrize("profil,mult,montant", [
        ("conservateur", 1.8, 20), ("equilibre", 4.0, 20), ("agressif", 10.0, 20),
        ("conservateur", 1.8, 10), ("equilibre", 4.0, 10), ("agressif", 10.0, 10),
        ("conservateur", 1.8, 6), ("equilibre", 4.0, 6), ("agressif", 10.0, 6),
        ("conservateur", 1.8, 30), ("equilibre", 4.0, 30), ("agressif", 10.0, 30),
    ])
    def test_gain_vs_mise_totale(self, profil, mult, montant):
        """Contrat 2026-07-13 (bande RESPECTÉE même fractionnée) : CHAQUE ticket gagnant
        rend ≥ gain_cible_mult × la mise TOTALE, qu'il y ait 1 ou plusieurs tickets. On
        n'abaisse PLUS la cible pour forcer la diversification (ce serait sous la bande)."""
        plan = plan_to_dict(generer_plan(montant, profil, _field(10), COURSE,
                                         respect_montant=True))
        paris = [p for niv in plan["niveaux"] for p in niv["paris"]]
        assert paris, "plan vide inattendu"
        for p in paris:
            assert p["gain_potentiel"] >= mult * montant * 0.95, (
                f"{profil}/{p['type']} gain {p['gain_potentiel']}€ "
                f"< ×{mult} du plan ({montant}€, {len(paris)} tickets)"
            )

    def test_trio_modere_cap_strict(self):
        """Trio gardé en modéré mais var_cap strict (≤0.30) → jamais 10€ plein dessus."""
        assert PROFIL_CONFIG["equilibre"]["var_cap"] <= 0.30
        plan = plan_to_dict(generer_plan(20, "equilibre", _field(10), COURSE,
                                         respect_montant=True))
        plafond = int(20 * 0.30)
        for niv in plan["niveaux"]:
            for p in niv["paris"]:
                if p["type"] in ("Trio", "Trio Ordre", "Tiercé Désordre"):
                    assert p["mise"] <= plafond + 1, f"Trio modéré {p['mise']}€ > {plafond}€"


# ── 3. CALIBRATION appliquée : bandes toujours respectées sur le rapport corrigé ─
class TestCalibrationAppliquee:
    def test_facteur_bas_ecarte_ou_recale_sous_bande(self):
        """Un facteur < 1 abaisse le rapport attendu → tout pari qui tombe sous la
        bande de son profil est écarté ; ceux qui restent respectent la bande sur le
        RAPPORT CORRIGÉ (gain affiché = gain réellement attendu)."""
        # On rabote fortement TOUS les types courants du modéré.
        types_eq = list(PROFIL_CONFIG["equilibre"]["types"])
        calib = {"profils": {"equilibre": {t: {"factor": 0.5} for t in types_eq}}}
        plan = plan_to_dict(generer_plan(20, "equilibre", _field(10), COURSE,
                                         respect_montant=True, rapport_calib=calib))
        gmin = PROFIL_CONFIG["equilibre"]["gain_cible_mult"]
        gmax = PROFIL_CONFIG["equilibre"]["gain_cible_max"]
        for t, g in _gains_vs_total(plan):
            assert g >= gmin - 0.1, f"calib: {t} gain ×{g:.2f} du total sous bande {gmin}"
            assert g <= gmax + 0.1, f"calib: {t} gain ×{g:.2f} du total au-dessus bande {gmax}"

    def test_calibration_baisse_le_gain_affiche(self):
        """Le gain affiché reflète le rapport CORRIGÉ.

        Comparé PARI PAR PARI (type + chevaux), pas sur le maximum du plan : la
        calibration change aussi QUELS paris passent les gates, donc deux plans n'ont
        aucune raison d'aligner leurs extrêmes. Sur un pari présent dans les deux, en
        revanche, le rapport corrigé doit valoir le facteur × le rapport brut.
        """
        def _par_pari(plan_d):
            return {(p["type"], tuple(sorted(c["numero"] for c in p["chevaux"]))):
                    p["gain_potentiel"] / p["mise"]
                    for niv in plan_d["niveaux"] for p in niv["paris"] if p["mise"] > 0}

        types_eq = list(PROFIL_CONFIG["equilibre"]["types"])
        plan_sans = plan_to_dict(generer_plan(20, "equilibre", _field(10), COURSE,
                                              respect_montant=True))
        sans = _par_pari(plan_sans)
        for facteur in (0.9, 0.8, 0.6):
            calib = {"profils": {"equilibre": {t: {"factor": facteur} for t in types_eq}}}
            avec = _par_pari(plan_to_dict(generer_plan(
                20, "equilibre", _field(10), COURSE,
                respect_montant=True, rapport_calib=calib)))
            communs = set(sans) & set(avec)
            assert communs, f"facteur {facteur} : aucun pari commun aux deux plans"
            for cle in communs:
                # arrondis en cascade (rapport arrondi à 0.1, mise entière) → 10 % de marge
                assert avec[cle] <= sans[cle] * facteur * 1.10 + 0.5, (
                    f"{cle} (facteur {facteur}) : rapport corrigé {avec[cle]:.1f} "
                    f"vs brut {sans[cle]:.1f}")

    def test_neutre_si_calib_vide(self):
        """rapport_calib vide → plan identique au plan sans calibration (cold-start sûr)."""
        a = plan_to_dict(generer_plan(20, "equilibre", _field(10), COURSE,
                                      respect_montant=True))
        b = plan_to_dict(generer_plan(20, "equilibre", _field(10), COURSE,
                                      respect_montant=True, rapport_calib={"profils": {}}))
        assert _rapports_selectionnes(a) == _rapports_selectionnes(b)


# ── 4. Bande-EV câblée dans le MOTEUR DE MISE (levier ROI) ───────────────────
def _all_bands(mult):
    from ml.signal_performance import EV_BANDS
    return {"bands": {f"{lo:.2f}_{hi:.2f}": {"n": 500, "multiplier": mult}
                      for lo, hi in EV_BANDS}}


class TestEvBandStaking:
    def test_neutre_sans_table(self):
        """Pas de table bande-EV → plan inchangé (cold-start sûr)."""
        a = plan_to_dict(generer_plan(20, "equilibre", _field(10), COURSE,
                                      respect_montant=True))
        b = plan_to_dict(generer_plan(20, "equilibre", _field(10), COURSE,
                                      respect_montant=True, ev_band_perf={"bands": {}}))
        assert _rapports_selectionnes(a) == _rapports_selectionnes(b)

    def test_montant_integralement_joue_meme_si_toutes_bandes_toxiques(self):
        """Bandes toutes toxiques → mise allégée mais montant manuel JOUÉ en entier
        (adapter ≠ bannir ; respect_montant)."""
        plan = plan_to_dict(generer_plan(20, "equilibre", _field(10), COURSE,
                                         respect_montant=True,
                                         ev_band_perf=_all_bands(0.5)))
        assert plan["montant_joue"] == 20

    def test_gate_bande_toxique_course_toujours_jouee(self):
        """Gate bande d'EV (audit ROI 2026-07-02) : bandes toutes toxiques (mult ≤0.80)
        → les spéculatifs -EV sans edge sont écartés de la sélection, MAIS l'invariant
        produit tient : la course reste jouée et le montant manuel est joué en entier
        (filet + complément hors gates)."""
        for profil in ("agressif", "equilibre"):
            plan = plan_to_dict(generer_plan(10, profil, _field(10), COURSE,
                                             respect_montant=True,
                                             ev_band_perf=_all_bands(0.5)))
            paris = [p for n in plan["niveaux"] for p in n["paris"]]
            assert paris, f"plan {profil} vide avec bandes toxiques"
            assert plan["montant_joue"] == 10

    def test_raison_bande_ev_exposee(self):
        """Le facteur bande-EV est appliqué ET justifié dans les raisons du pari."""
        plan = plan_to_dict(generer_plan(20, "agressif", _field(10), COURSE,
                                         respect_montant=True,
                                         ev_band_perf=_all_bands(1.5)))
        raisons = [r for niv in plan["niveaux"] for p in niv["paris"] for r in p["raisons"]]
        assert any("bande d'EV" in r for r in raisons), "facteur bande-EV non exposé"


def test_filet_agressif_ne_choisit_pas_le_plus_gros_rapport_aveuglement():
    """Quand aucun pari ne passe les gates, le plan reste non vide mais choisit le
    meilleur rendement attendu, pas le jackpot le moins probable."""
    from services.mise_calculator import _effective_config, _palier, _select_conviction

    def candidat(numero, proba, rapport, ev):
        return {
            "type_pari": "Simple Gagnant",
            "chevaux": [{"numero": numero, "cote": rapport}],
            "proba_gain": proba,
            "rapport_estime": rapport,
            "ev": ev,
            "edge": 0.0,
            "niveau": "coup",
        }

    credible = candidat(1, 0.20, 12.0, -0.50)
    jackpot = candidat(2, 0.001, 100.0, -0.90)
    selected = _select_conviction(
        [jackpot, credible], 10, _palier(10), _effective_config("agressif", 0.0),
        roi_weights={}, respect_montant=True,
    )

    assert selected
    assert selected[0]["chevaux"][0]["numero"] == 1


@pytest.mark.parametrize("montant", [6, 30])
@pytest.mark.parametrize("profil", ["conservateur", "equilibre", "agressif"])
def test_montant_saisi_est_toujours_integralement_joue(montant, profil):
    plan = plan_to_dict(generer_plan(
        montant, profil, _field(10), COURSE, respect_montant=True,
    ))

    assert plan["montant_joue"] == montant
    assert plan["montant_reserve"] == 0


def test_le_montant_change_la_strategie_et_pas_seulement_un_ratio():
    petit = plan_to_dict(generer_plan(
        6, "equilibre", _field(10), COURSE, respect_montant=True,
    ))
    grand = plan_to_dict(generer_plan(
        30, "equilibre", _field(10), COURSE, respect_montant=True,
    ))
    paris_petit = [p for n in petit["niveaux"] for p in n["paris"]]
    paris_grand = [p for n in grand["niveaux"] for p in n["paris"]]

    # Le NOMBRE de tickets peut être identique : depuis que la tranche du profil se
    # mesure sur la mise totale sans exception (2026-08-20), financer un ticket de plus
    # exige un rapport ≥ cible/mise_plancher, ce qui ne dépend pas du montant du plan.
    # Ce qui doit changer, c'est la STRATÉGIE : palier de mise et composition du plan.
    assert petit["palier"] != grand["palier"]
    assert [(p["type"], p["mise"]) for p in paris_petit] != [
        (p["type"], p["mise"]) for p in paris_grand
    ]


# ── 5. Réévaluation des GAINS aux cotes LIVE (sélection figée) ────────────────
def _all_paris(plan):
    return [p for niv in plan["niveaux"] for p in niv["paris"]]


class TestRepriceGainsLive:
    def test_gain_simple_gagnant_suit_cote_live(self):
        """Après gel : la sélection ne bouge pas, mais le gain d'un Simple Gagnant suit
        la cote LIVE (le PMU paie la cote → gain = mise × cote live)."""
        preds = _field(10)
        plan = plan_to_dict(generer_plan(30, "equilibre", preds, COURSE,
                                         respect_montant=True))
        sg = next((p for p in _all_paris(plan) if p["type"] == "Simple Gagnant"), None)
        if not sg:
            pytest.skip("pas de Simple Gagnant dans ce plan")
        n = sg["chevaux"][0]["numero"]
        mise = sg["mise"]
        c0 = next(x["cote_pmu"] for x in preds if x["numero"] == n)
        # cote du cheval DOUBLE en live
        preds_live = [{**x, "cote_pmu": x["cote_pmu"] * 2 if x["numero"] == n else x["cote_pmu"]}
                      for x in preds]
        sel_avant = sorted((p["type"], tuple(h["numero"] for h in p["chevaux"]),
                            p["mise"]) for p in _all_paris(plan))
        reprice_plan_live(plan, preds_live, COURSE)
        sg2 = next(p for p in _all_paris(plan)
                   if p["type"] == "Simple Gagnant" and p["chevaux"][0]["numero"] == n)
        assert abs(sg2["gain_potentiel"] - round(mise * c0 * 2)) <= 1
        # SÉLECTION inchangée (mêmes paris, mêmes mises)
        sel_apres = sorted((p["type"], tuple(h["numero"] for h in p["chevaux"]),
                            p["mise"]) for p in _all_paris(plan))
        assert sel_apres == sel_avant
        assert plan["gains_live_post_gel"] is True

    def test_reprice_no_op_sans_predictions(self):
        plan = plan_to_dict(generer_plan(20, "equilibre", _field(10), COURSE,
                                         respect_montant=True))
        avant = [(p["type"], p["gain_potentiel"]) for p in _all_paris(plan)]
        reprice_plan_live(plan, [], COURSE)
        apres = [(p["type"], p["gain_potentiel"]) for p in _all_paris(plan)]
        assert avant == apres   # rien à re-tarifer → plan inchangé
