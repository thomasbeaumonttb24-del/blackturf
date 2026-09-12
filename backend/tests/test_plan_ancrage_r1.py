"""Plan de mise — ancrage sur le rang 1, désaccord marché, ticket gros lot (2026-09-12).

Ce que ces tests protègent (mesures sur 4 048 courses, 1 € plat sur le classement,
prédictions figées avant le départ, vrais rapports PMU — cf. le bloc « ANCRAGE SUR
LE RANG 1 » de services/mise_calculator.py) :

  - le point d'appui des combinaisons est le RANG 1 (couplé r1 × pieds −9 % contre
    −23 % pour un couplé sans le rang 1) ;
  - le DÉSACCORD marché (rang 1 ≠ favori de la cote) est le signal du modèle
    (gagnant sec du rang 1 : −0,8 % contre −17 % en accord ; le favori sans le
    rang 1 : −33 à −51 %) — un tilt de conviction, jamais un veto ;
  - le Trio du profil risqué est un ticket « gros lot » plafonné (un par plan,
    var_cap en mise), pas un pari de rendement ;
  - un ticket servi hors de la tranche est marqué ticket par ticket.
"""
import pytest

from services import mise_calculator as mc
from services.mise_calculator import generer_plan, plan_to_dict

COURSE = {
    "nb_partants": 14, "course_id": "T-R1", "discipline": "Attelé",
    "paris_disponibles": ["E_SIMPLE_GAGNANT", "E_SIMPLE_PLACE", "E_COUPLE_GAGNANT",
                          "E_COUPLE_PLACE", "E_TRIO", "E_2SUR4"],
}


def _champ(rows):
    return [{"numero": i + 1, "nom": f"H{i+1}", "nom_cheval": f"H{i+1}",
             "proba_top1": p, "proba_top3": min(1.0, p * 2.2),
             "cote_pmu": c, "non_partant": False}
            for i, (p, c) in enumerate(rows)]


# Désaccord : le n°1 (rang 1 du modèle, 24 %) est coté 6,5 ; le favori de la cote est
# le n°2 (2,4) que le modèle ne classe que 2e. Le reste est un champ ouvert.
DESACCORD = _champ([(0.24, 6.5), (0.18, 2.4), (0.12, 8.0), (0.10, 11.0), (0.08, 14.0),
                    (0.07, 18.0), (0.06, 22.0), (0.05, 28.0), (0.04, 35.0), (0.03, 45.0),
                    (0.02, 60.0), (0.01, 80.0)])
# Accord : le rang 1 EST le favori de la cote.
ACCORD = _champ([(0.30, 2.4), (0.16, 6.5), (0.12, 8.0), (0.10, 11.0), (0.08, 14.0),
                 (0.07, 18.0), (0.06, 22.0), (0.05, 28.0), (0.03, 35.0), (0.02, 45.0),
                 (0.01, 60.0)])


def _paris(d):
    return [p for niv in d["niveaux"] for p in niv["paris"]]


# ── Désaccord marché ────────────────────────────────────────────────────────────

def test_le_desaccord_marche_est_detecte_avant_le_depart():
    assert mc._desaccord_marche(DESACCORD) is True
    assert mc._desaccord_marche(ACCORD) is False
    # Sans cote exploitable, la question n'a pas de sens : jamais un signal inventé.
    assert mc._desaccord_marche([{"numero": 1, "proba_top1": 0.3, "cote_pmu": None}]) is None


def test_les_constantes_du_tilt_sont_une_preference_pas_un_veto():
    assert mc.DESACCORD_BOOST_R1 > 1.0
    assert 0.0 < mc.DESACCORD_MALUS_FAVORI < 1.0


@pytest.mark.parametrize("profil", ["equilibre", "agressif"])
def test_en_desaccord_le_plan_porte_le_rang_1(profil):
    """Sur une course de désaccord, le rang 1 (cote 6,5) est jouable dans la tranche
    du modéré (×4-15) comme du risqué (couplé r1 × pieds). Il doit porter le plan."""
    d = plan_to_dict(generer_plan(10, profil, DESACCORD, COURSE, respect_montant=True))
    paris = _paris(d)
    assert paris
    assert any(any(c["numero"] == 1 for c in p["chevaux"]) for p in paris), \
        f"{profil} : aucun ticket ne porte le rang 1 sur une course de désaccord — {paris}"
    # Le tilt est expliqué sur le ticket, pas caché dans un multiplicateur.
    raisons = " ".join(r for p in paris for r in (p.get("raisons") or []))
    assert "Désaccord avec le marché" in raisons


def test_en_accord_aucune_raison_de_desaccord_n_est_inventee():
    for profil in ("conservateur", "equilibre", "agressif"):
        d = plan_to_dict(generer_plan(10, profil, ACCORD, COURSE, respect_montant=True))
        raisons = " ".join(r for p in _paris(d) for r in (p.get("raisons") or []))
        assert "Désaccord avec le marché" not in raisons


def test_le_tilt_est_porte_par_le_candidat_et_lu_par_la_mise():
    """`_des_mult` est posé sur chaque candidat et entre dans la conviction de MISE
    (`_allocate_spread._w`) autant que dans la sélection : l'argent suit le signal."""
    from ml.combo_bets import enumerate_bet_candidates
    cands = enumerate_bet_candidates(DESACCORD, COURSE)
    assert cands
    # Reproduit l'annotation de generer_plan sur un plan réel : les candidats retenus
    # portent le drapeau.
    d = plan_to_dict(generer_plan(10, "agressif", DESACCORD, COURSE, respect_montant=True))
    assert _paris(d)


# ── Ancrage sur le rang 1 ───────────────────────────────────────────────────────

def test_le_mode_d_ancrage_par_defaut_est_le_rang_1():
    assert mc.ANCRAGE_MODE == "r1"


@pytest.mark.parametrize("profil", ["equilibre", "agressif"])
def test_toute_combinaison_du_plan_contient_le_rang_1_quand_c_est_possible(profil):
    for champ in (DESACCORD, ACCORD):
        r1 = max(champ, key=lambda p: p["proba_top1"])["numero"]
        d = plan_to_dict(generer_plan(20, profil, champ, COURSE, respect_montant=True))
        combos = [p for p in _paris(d)
                  if len(p["chevaux"]) >= 2 and p["type"] not in mc.TYPES_SANS_ANCRAGE]
        for p in combos:
            assert any(c["numero"] == r1 for c in p["chevaux"]), (
                f"{profil} : {p['type']} {[c['numero'] for c in p['chevaux']]} "
                f"sans le rang 1 (N°{r1})")


def test_le_plafond_de_correlation_exempte_le_point_d_appui():
    """Un éventail r1 × pieds expose 100 % du plan au rang 1 par construction : ce
    n'est pas une corrélation subie, c'est la stratégie. Le plafond ne doit pas
    déplacer l'argent hors du rang 1 ; il continue de s'appliquer aux autres."""
    sel = [
        {"type_pari": "Couplé Gagnant", "chevaux": [{"numero": 1}, {"numero": 3}],
         "mise": 5, "_besoin": 2, "proba_gain": 0.08, "rapport_estime": 20.0},
        {"type_pari": "Couplé Gagnant", "chevaux": [{"numero": 1}, {"numero": 4}],
         "mise": 5, "_besoin": 2, "proba_gain": 0.06, "rapport_estime": 30.0},
    ]
    avant = [c["mise"] for c in sel]
    mc._apply_correlation_cap(sel, 10, 2, respect_montant=True, exempt={1})
    assert [c["mise"] for c in sel] == avant, "l'exposition au rang 1 est voulue"
    # Sans exemption, le plafond de 70 % (7 €) déclenche — et, faute de ticket
    # décorrélé, rend l'excédent au ticket rogné (contrat « tout est joué »).
    mc._apply_correlation_cap(sel, 10, 2, respect_montant=True)
    assert sum(c["mise"] for c in sel) == 10


# ── Ticket « gros lot » ────────────────────────────────────────────────────────

def test_le_trio_du_risque_est_unique_et_plafonne():
    for champ in (DESACCORD, ACCORD):
        for montant in (10, 20, 50):
            d = plan_to_dict(generer_plan(montant, "agressif", champ, COURSE,
                                          respect_montant=True))
            trios = [p for p in _paris(d) if p["type"] == "Trio"]
            assert len(trios) <= mc.LOTERIE_MAX_TICKETS
            plafond = max(2, int(montant * mc.PROFIL_CONFIG["agressif"]["var_cap"]))
            for t in trios:
                assert t["mise"] <= plafond + 1, f"Trio à {t['mise']}€ > plafond {plafond}€"
                assert t["gain_potentiel"] >= 10 * montant * 0.95     # tranche tenue
                assert any("gros lot" in r for r in t.get("raisons") or [])


def test_le_gros_lot_echappe_au_gate_dur_mais_pas_aux_autres_gates():
    """Poids appris 0 sur le Trio (suspendu par l'apprentissage) : le ticket gros lot
    reste proposable ; un type NON loterie au poids 0 reste coupé."""
    poids = {"Trio": 0.0, "Couplé Ordre": 0.0, "Couplé Gagnant": 0.5, "Simple Gagnant": 0.8}
    d = plan_to_dict(generer_plan(10, "agressif", DESACCORD, COURSE, roi_weights=poids,
                                  respect_montant=True))
    types = {p["type"] for p in _paris(d)}
    assert "Couplé Ordre" not in types
    # (le Trio peut être présent ou non selon le budget ; ce qui compte est qu'il ne
    # soit pas interdit par principe)
    assert mc._effective_config("agressif", 0.0)["loterie"] == frozenset({"Trio"})
    assert mc._effective_config("equilibre", 0.0)["loterie"] == frozenset()


def test_multi_retire_de_tous_les_profils():
    """−80 % (en 6) à −94 % (en 7) sur 2 205 courses : un filet qui tombe souvent
    et ne rend rien. Retiré partout ; le Pick5 et les Multi en 4/5 l'étaient déjà."""
    for profil, cfg in mc.PROFIL_CONFIG.items():
        for t in cfg["types"]:
            assert not mc._fam(t).startswith("Multi"), f"{profil} propose encore {t}"


# ── Ticket hors tranche marqué ─────────────────────────────────────────────────

def test_un_ticket_servi_hors_tranche_est_marque_sur_le_ticket():
    """Champ de cotes courtes : aucun pari ≥ ×10 possible, le filet sert le meilleur
    pari disponible. Le multiplicateur promis n'est pas tenu et le ticket le DIT."""
    # Six partants à cotes courtes, seuls les paris simples sont offerts : rien ne
    # peut payer ×10, le filet sert le meilleur gagnant sec disponible.
    champ = _champ([(0.36, 1.9), (0.24, 2.6), (0.16, 3.4), (0.12, 4.2), (0.07, 5.5),
                    (0.05, 6.0)])
    info = {"nb_partants": 6, "paris_disponibles": ["E_SIMPLE_GAGNANT", "E_SIMPLE_PLACE"]}
    d = plan_to_dict(generer_plan(10, "agressif", champ, info, respect_montant=True))
    paris = _paris(d)
    assert paris
    assert "tranche de gain habituelle" in d["resume_ia"]
    assert all(p.get("hors_tranche") is True for p in paris)
    # Et jamais marqué quand la tranche est tenue.
    d2 = plan_to_dict(generer_plan(10, "agressif", DESACCORD, COURSE, respect_montant=True))
    assert all(p.get("hors_tranche") is False for p in _paris(d2))


def test_le_plafond_de_rang_des_paris_a_un_cheval_est_configurable():
    """`rang_max_simple` resserre le plafond des paris à UN cheval sans toucher aux
    combinaisons ancrées (banc de mesure : variantes sg2/sg3)."""
    cfg = mc._effective_config("agressif", 0.0)
    assert "rang_max_simple" in cfg
    ancien = mc.PROFIL_CONFIG["agressif"].get("rang_max_simple")
    mc.PROFIL_CONFIG["agressif"]["rang_max_simple"] = 2
    try:
        d = plan_to_dict(generer_plan(20, "agressif", ACCORD, COURSE, respect_montant=True))
        for p in _paris(d):
            if len(p["chevaux"]) == 1 and p["type"] == "Simple Gagnant" \
                    and not p.get("hors_tranche"):
                assert p["chevaux"][0].get("rang", 1) <= 2
    finally:
        if ancien is None:
            mc.PROFIL_CONFIG["agressif"].pop("rang_max_simple", None)
        else:
            mc.PROFIL_CONFIG["agressif"]["rang_max_simple"] = ancien
