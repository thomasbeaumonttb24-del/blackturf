"""L'écart à l'arrivée, du libellé PMU aux longueurs.

`historique_courses.ecart_longueurs` valait NULL sur les 330 145 lignes de la
table. Le writer testait `isinstance(ecart, (int, float))` alors que le PMU
publie un OBJET : `{"knownValue": "UN_NEZ", "rawValue": "Nez"}`. Quatre features
en dépendaient — `ecart_moyen_recent`, `proximite_vainqueur`,
`nb_defaites_courtes`, `defaite_courte_derniere` — toutes constantes, donc
apprises comme du bruit par le modèle.

Les libellés testés ici sont ceux RÉELLEMENT observés : relevé du 2026-08-31 sur
802 courses passées de l'API PMU, 33 valeurs distinctes.
"""
from __future__ import annotations

import pytest

from scraper.sources.pmu import (
    _ecart_au_vainqueur, _ecart_en_longueurs, _ecart_texte_en_longueurs,
)


def _v(connu, brut):
    return {"knownValue": connu, "rawValue": brut}


@pytest.mark.parametrize("connu,brut,attendu", [
    ("UN_NEZ", "Nez", 0.05),
    ("ENCOLURE", "Encolure", 0.30),
    ("DEMI_LONGUEUR", "1/2 L", 0.50),
    ("TROIS_QUARTS_DE_LONGUEUR", "3/4 L", 0.75),
    ("UNE_LONGUEUR", "1 L", 1.0),
    ("UNE_LONGUEUR_ET_QUART", "1 L 1/4", 1.25),
    ("UNE_LONGUEUR_ET_DEMIE", "1 L 1/2", 1.5),
    ("UNE_LONGUEUR_TROIS_QUARTS", "1 L 3/4", 1.75),
    ("DEUX_LONGUEURS", "2 L", 2.0),
    ("DEUX_LONGUEURS_ET_DEMIE", "2 L 1/2", 2.5),
    ("TROIS_LONGUEURS", "3 L", 3.0),
    ("TROIS_LONGUEURS_ET_DEMIE", "3 L 1/2", 3.5),
    ("QUATRE_LONGUEURS", "4 L", 4.0),
    ("QUATRE_LONGUEURS_ET_DEMIE", "4 L 1/2", 4.5),
    ("CINQ_LONGUEURS", "5 L", 5.0),
    ("CINQ_LONGUEURS_ET_DEMIE", "5 L 1/2", 5.5),
    ("SIX_LONGUEURS", "6 L", 6.0),
    ("SEPT_LONGUEURS", "7 L", 7.0),
    ("SEPT_LONGUEURS_ET_DEMIE", "7 L 1/2", 7.5),
    ("HUIT_LONGUEURS", "8 L", 8.0),
    ("HUIT_LONGUEURS_ET_DEMIE", "8 L 1/2", 8.5),
    ("NEUF_LONGUEURS", "9 L", 9.0),
    ("DIX_LONGUEURS", "10 L", 10.0),
    ("ONZE_LONGUEURS", "11 L", 11.0),
    ("DOUZE_LONGUEURS", "12 L", 12.0),
    ("TREIZE_LONGUEURS", "13 L", 13.0),
    ("QUATORZE_LONGUEURS", "14 L", 14.0),
    ("QUINZE_LONGUEURS", "15 L", 15.0),
    ("SEIZE_LONGUEURS", "16 L", 16.0),
    ("VINGT_LONGUEURS", "20 L", 20.0),
    ("DEAD_HEAT_ALT", "Dead-heat", 0.0),
    ("LOIN", "Loin", 25.0),
])
def test_les_33_libelles_reellement_observes_sont_couverts(connu, brut, attendu):
    assert _ecart_en_longueurs(_v(connu, brut)) == pytest.approx(attendu)


@pytest.mark.parametrize("brut,attendu", [
    ("Courte tête", 0.10), ("Tête", 0.15), ("Courte encolure", 0.20),
])
def test_le_repli_sur_rawvalue_rattrape_les_inconnu(brut, attendu):
    """30 écarts sur 802 portent `knownValue = INCONNU` mais un `rawValue` précis.

    Sans le repli, ces marges — les plus SERRÉES, donc les plus informatives —
    seraient les seules à se perdre.
    """
    assert _ecart_en_longueurs(_v("INCONNU", brut)) == pytest.approx(attendu)
    assert _ecart_texte_en_longueurs(brut) == pytest.approx(attendu)


def test_un_libelle_inconnu_ne_produit_jamais_de_chiffre_invente():
    assert _ecart_en_longueurs(_v("GALAXIE_LOINTAINE", "???")) is None
    assert _ecart_en_longueurs(None) is None
    assert _ecart_en_longueurs({"knownValue": None, "rawValue": None}) is None


# ── Cumul jusqu'au vainqueur ────────────────────────────────────────────────

def _course(marges):
    """marges : {place: libellé ou None}. La place 1 n'a pas de marge."""
    return {"participants": [
        {"place": {"place": rang}, "distanceAvecPrecedent": m, "itsHim": False}
        for rang, m in marges.items()
    ]}


def test_le_vainqueur_est_a_zero_longueur():
    c = _course({1: None})
    moi = {"place": {"place": 1}}
    assert _ecart_au_vainqueur(c, moi) == 0.0


def test_l_ecart_est_cumule_depuis_le_vainqueur_et_non_sur_le_precedent():
    """LE défaut de fond que ce cumul corrige.

    Le PMU publie la marge sur le cheval PRÉCÉDENT ; la feature lit « 0 =
    vainqueur » et en déduit une proximité au gagnant. Reporter la marge brute
    aurait fait passer un 4ᵉ battu d'un nez sur le 3ᵉ pour un cheval collé au
    vainqueur, alors qu'il en est à 2,05 longueurs.
    """
    c = _course({1: None,
                 2: _v("UNE_LONGUEUR", "1 L"),
                 3: _v("UNE_LONGUEUR", "1 L"),
                 4: _v("UN_NEZ", "Nez")})
    assert _ecart_au_vainqueur(c, {"place": {"place": 4}}) == pytest.approx(2.05)
    assert _ecart_au_vainqueur(c, {"place": {"place": 2}}) == pytest.approx(1.0)


def test_une_chaine_incomplete_ne_donne_pas_une_somme_partielle():
    """Un chiffre faux est pire que pas de chiffre : une marge illisible ou une
    place manquante dans la chaîne 2..moi annule le cumul."""
    illisible = _course({1: None,
                         2: _v("MARGE_MYSTERE", "?!"),
                         3: _v("UNE_LONGUEUR", "1 L")})
    assert _ecart_au_vainqueur(illisible, {"place": {"place": 3}}) is None

    trouee = _course({1: None, 3: _v("UNE_LONGUEUR", "1 L")})
    assert _ecart_au_vainqueur(trouee, {"place": {"place": 3}}) is None


def test_un_cheval_sans_place_exploitable_ne_produit_rien():
    c = _course({1: None, 2: _v("UNE_LONGUEUR", "1 L")})
    assert _ecart_au_vainqueur(c, {"place": {"place": "DAI"}}) is None
    assert _ecart_au_vainqueur(c, {"place": None}) is None
    assert _ecart_au_vainqueur(c, None) is None


# ── Allocation : ce qui est physiquement impossible n'entre pas en base ──────

from scraper.sources.pmu import (  # noqa: E402
    ALLOCATION_PLAFOND, _allocation_vraisemblable,
)


def test_seul_l_impossible_dans_les_deux_unites_est_ecarte():
    """Le plafond est la lecture la plus GÉNÉREUSE, et ce n'est pas de la prudence
    de façade : un premier seuil posé à 50 000 000 « euros » a écarté 1 455 lignes
    en base, dont 1 192 entre 50 M et 238 M qui valent 500 k€ à 2,4 M€ lues en
    centimes — des grands prix parfaitement réels, restaurés depuis.

    On écarte, on ne ramène pas au plafond : un montant faux ramené à 50 M€ reste
    faux et passe alors pour une donnée.
    """
    assert _allocation_vraisemblable(109_000_000_000) is None   # 1,09 Md EUR
    assert _allocation_vraisemblable(-5) is None
    # Plausible en centimes (2,4 M€) : conservé, quelle que soit l'unité réelle.
    assert _allocation_vraisemblable(238_175_000) == 238_175_000


def test_les_montants_reels_passent_intacts():
    # Médianes relevées le 2026-08-31 : 20 100 côté historique externe,
    # 2 000 000 centimes côté courses.
    assert _allocation_vraisemblable(20_100) == 20_100
    assert _allocation_vraisemblable(2_000_000) == 2_000_000
    assert _allocation_vraisemblable(ALLOCATION_PLAFOND) == ALLOCATION_PLAFOND


def test_une_absence_reste_une_absence():
    assert _allocation_vraisemblable(None) is None
    assert _allocation_vraisemblable("260000") is None
    assert _allocation_vraisemblable(True) is None
