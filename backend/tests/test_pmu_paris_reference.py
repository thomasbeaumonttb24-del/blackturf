"""Le catalogue PMU : ce qui est offert, ce qui est jouable, ce que ça rend.

Deux écarts mesurés le 2026-08-19 motivent ces tests :

- les pools INTERNATIONAUX (4,6 % des courses, 145 sur 60 jours) n'étaient
  reconnus par aucun code : le catalogue déclarait alors AUCUN pari disponible.
  Le Couplé Ordre réellement offert n'était jamais proposé, tandis que des Trio
  et des Multi inexistants l'étaient — d'où leur ROI de −99 % à −100 % : ils ne
  gagnaient jamais parce qu'ils n'existaient pas ;
- `E_REPORT_PLUS` couvre 97,3 % des courses et n'est volontairement pas exploité.
"""
import pytest

from services.bet_catalog import derive_bet_flags
from services.pmu_paris_reference import (
    CATALOGUE,
    PAR_NOM,
    mise_base,
    partants_min,
    prelevement,
)


# ── Pools internationaux ─────────────────────────────────────────────────────
def test_les_pools_internationaux_sont_reconnus():
    """Course réelle 19082026R5C3 : le PMU n'y offre QUE des codes internationaux
    et un Trio Ordre."""
    flags = derive_bet_flags([
        "COUPLE_ORDRE_INTERNATIONAL", "E_TRIO_ORDRE",
        "SIMPLE_GAGNANT_INTERNATIONAL", "SIMPLE_PLACE_INTERNATIONAL",
    ])
    assert flags["est_simple_gagnant"] is True
    assert flags["est_simple_place"] is True
    assert flags["est_couple_ordre"] is True, (
        "le Couplé Ordre est réellement jouable sur cette course")
    assert flags["est_trio_ordre"] is True
    assert flags["est_trio"] is False, "le Trio simple n'est PAS offert ici"
    assert flags["est_couple_gagnant"] is False


def test_le_pari_a_report_est_ignore_sciemment():
    """`E_REPORT_PLUS` couvre 97,3 % des courses. Il rejoue la mise gagnée d'une
    course sur une seconde : le prélèvement s'applique DEUX fois (~28 % cumulés).
    Un seul étage dépasse déjà l'avantage du modèle."""
    flags = derive_bet_flags(["E_REPORT_PLUS", "E_SIMPLE_GAGNANT"])
    assert flags["est_simple_gagnant"] is True
    assert not any(v for k, v in flags.items() if k != "est_simple_gagnant"), (
        "le report ne doit activer aucun drapeau")


def test_un_code_inconnu_n_invente_aucun_pari():
    """Mieux vaut rater un pari que d'en conseiller un impossible au guichet."""
    flags = derive_bet_flags(["E_PARI_QUI_N_EXISTE_PAS"])
    assert not any(flags.values())


# ── Cohérence de la référence ────────────────────────────────────────────────
def test_le_prelevement_croit_avec_la_difficulte():
    """C'est le fait structurant du pari mutuel : plus le pari est difficile,
    plus le PMU prélève — donc plus l'avantage requis pour rentrer dans ses frais
    est grand."""
    assert prelevement("Simple Gagnant") < prelevement("Couplé Gagnant")
    assert prelevement("Couplé Gagnant") < prelevement("Trio")
    assert prelevement("Trio") < prelevement("Multi en 5")


def test_un_pari_inconnu_prend_l_hypothese_prudente():
    """On ne sous-estime jamais l'adversaire principal."""
    assert prelevement("Pari Exotique Inconnu") == 0.25
    assert mise_base("Pari Exotique Inconnu") == 1.0


def test_les_variantes_multi_partagent_la_regle():
    """« Multi en 4 », « Mini Multi en 6 » : mêmes règle et prélèvement, seul le
    nombre de chevaux couverts change."""
    for variante in ("Multi en 4", "Multi en 7", "Mini Multi en 5"):
        assert prelevement(variante) == prelevement("Multi en 5")
        assert mise_base(variante) == 3.0


def test_les_champs_minimaux_sont_declares():
    """Le PMU n'ouvre pas un Trio ou un Multi sur un champ réduit : proposer un
    pari indisponible est aussi faux que d'en rater un."""
    assert partants_min("Trio") >= 8
    assert partants_min("Multi en 4") >= 14
    assert partants_min("Simple Gagnant") <= 4


def test_chaque_entree_porte_sa_mesure_ou_avoue_son_ignorance():
    """Un rendement affiché sans échantillon serait une opinion déguisée."""
    for p in CATALOGUE:
        if p.roi_mesure is not None:
            assert p.n_mesure >= 50, f"{p.nom} : ROI affiché sur {p.n_mesure} conseils"
        else:
            assert "insuffisant" in p.quand_le_jouer.lower() or "mince" in p.quand_le_jouer.lower()


def test_le_2sur4_illustre_que_gagner_souvent_n_est_pas_gagner():
    """56 % de réussite et pourtant −27,2 % : c'est le contre-exemple qui empêche
    de confondre fréquence et rentabilité."""
    p = PAR_NOM["2sur4"]
    assert p.taux_reussite > 0.5
    assert p.roi_mesure < -20


# ── Champ minimal, sur le chemin de secours ──────────────────────────────────
def test_le_secours_n_invente_pas_un_trio_sur_un_petit_champ():
    """Sans `paris_disponibles`, le code supposait Couplé et Trio disponibles
    partout. Le PMU ne les ouvre pas sous 8 partants : une course à 6 se voyait
    proposer un pari impossible à jouer au guichet."""
    flags = derive_bet_flags(None, nb_partants=6)
    assert flags["est_simple_gagnant"] is True
    assert flags["est_simple_place"] is True
    assert flags["est_trio"] is False
    assert flags["est_couple_gagnant"] is False


def test_le_secours_reste_complet_sur_un_champ_suffisant():
    flags = derive_bet_flags(None, nb_partants=12)
    assert flags["est_trio"] is True
    assert flags["est_couple_gagnant"] is True


def test_champ_inconnu_ne_bloque_rien():
    """Sans information sur le nombre de partants, on ne restreint pas : mieux
    vaut le comportement historique qu'un blocage arbitraire."""
    flags = derive_bet_flags(None)
    assert flags["est_trio"] is True
