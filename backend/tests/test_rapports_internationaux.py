"""Pools INTERNATIONAUX : le rapport PMU n'est pas publié sous la clé habituelle.

Sur une course étrangère reprise par le PMU, le rapport définitif arrive sous
`<type>_international` (`couple_ordre_international`, `trio_international`…) et JAMAIS
sous `couple_ordre` / `e_couple_ordre`. Le règlement ne connaissait ces variantes que
pour les deux SIMPLES.

Ce qu'a coûté l'oubli, le 2026-09-09 sur `09092026R6C6` : un Couplé Ordre 6→3
réellement GAGNANT, payé 24,6 par le PMU, réglé « rapport pas encore publié ». Le plan
est resté `partial`, re-tenté ≈300 fois dans la nuit ; `journee_complete` est donc resté
faux et **la story du soir n'est jamais partie** — un seul plan sur 212.

Une clé manquante ici ne ressemble jamais à un bug : elle se lit comme une attente
légitime. D'où le test de COUVERTURE ci-dessous, qui part du catalogue des paris
réellement offerts et non d'une liste réécrite à la main.
"""
from __future__ import annotations

import pytest

from services.bet_catalog import _CODE_FLAG, _CODES_IGNORES
from services.bet_settlement import _RAPPORT_KEYS, settle_pari

# L'arrivée réelle de 09092026R6C6 (12 partants) : 6, 3, 5, 8, 9…
CLASSEMENT = [{"numero": n, "position": i + 1}
              for i, n in enumerate([6, 3, 5, 8, 9, 4, 12, 11, 1, 7, 10, 2])]

# Les rapports tels qu'ils sont réellement en base pour cette course : les combinés
# « classiques » sous `e_*`, mais le Couplé ORDRE seulement en international.
RAPPORTS = {
    "e_trio": 61.6,
    "e_couple_place": 8.2,
    "e_couple_gagnant": 19.5,
    "couple_ordre_international": 24.6,
    "simple_place_international": 1.8,
    "simple_gagnant_international": 5.4,
}

# Drapeau canonique du catalogue → libellé de pari du moteur de mise.
_FLAG_LIBELLE = {
    "est_simple_gagnant": "Simple Gagnant",
    "est_simple_place":   "Simple Placé",
    "est_couple_gagnant": "Couplé Gagnant",
    "est_couple_place":   "Couplé Placé",
    "est_couple_ordre":   "Couplé Ordre",
    "est_trio":           "Trio",
    "est_trio_ordre":     "Trio Ordre",
}


def test_le_couple_ordre_international_est_regle_au_bon_rapport():
    """Le cas exact du 2026-09-09 : 6 puis 3, à l'ordre, payé 24,6."""
    r = settle_pari("Couplé Ordre", [6, 3], CLASSEMENT, RAPPORTS, 12)
    assert r["gagne"] is True
    assert r["rapport_reel"] == 24.6, (
        "un Couplé Ordre gagnant d'un pool international doit être payé : sans sa clé, "
        "le plan reste 'partial' à vie et bloque la publication de la journée"
    )
    assert r["note"] is None


def test_un_couple_ordre_perdant_reste_perdant():
    """Garde-fou : la nouvelle clé ne doit pas créditer un pari qui a perdu (ordre
    inversé = perdu, c'est tout l'intérêt du pari à l'ordre)."""
    r = settle_pari("Couplé Ordre", [3, 6], CLASSEMENT, RAPPORTS, 12)
    assert r["gagne"] is False and r["rapport_reel"] is None


def test_le_simple_place_international_reste_exact_par_cheval():
    """Le placé se règle sur `rapports_detail`, jamais sur l'agrégat : le rapport du
    3e placé (1,9) ne doit pas être remplacé par celui du vainqueur (1,8)."""
    detail = {"simple_place_international": [
        {"rapport": 1.8, "combinaison": "6"},
        {"rapport": 1.75, "combinaison": "3"},
        {"rapport": 1.9, "combinaison": "5"},
    ]}
    r = settle_pari("Simple Placé", [5], CLASSEMENT, RAPPORTS, 12, detail)
    assert r["gagne"] and r["rapport_reel"] == 1.9


@pytest.mark.parametrize("code", sorted(
    c for c in _CODE_FLAG if c.endswith("_INTERNATIONAL") and c not in _CODES_IGNORES
))
def test_chaque_pari_international_du_catalogue_a_sa_cle_de_rapport(code):
    """COUVERTURE — le catalogue et le règlement doivent parler du même pari.

    `bet_catalog` déclare disponible un pari international ; s'il n'a pas sa clé de
    rapport ici, le moteur PROPOSE le pari et le règlement ne saura jamais le payer.
    C'est exactement l'écart qui a bloqué la story du 2026-09-09. Ce test échoue donc
    dès qu'un nouveau code `*_INTERNATIONAL` est ajouté au catalogue sans sa clé.
    """
    libelle = _FLAG_LIBELLE[_CODE_FLAG[code]]
    attendue = code.lower()
    assert attendue in _RAPPORT_KEYS[libelle], (
        f"{code} est offert par le catalogue mais « {libelle} » ne connaît pas la clé "
        f"de rapport « {attendue} » : un pari gagnant resterait en attente pour toujours"
    )
