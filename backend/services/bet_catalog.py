"""bet_catalog.py — disponibilité RÉELLE des paris par course.

Source de vérité : `courses.paris_disponibles` = liste des `paris[].codePari` du
programme PMU (ex. ["E_SIMPLE_GAGNANT","E_COUPLE_ORDRE","E_TRIO_ORDRE",...]).

Le PMU n'offre PAS les mêmes paris partout : un champ réduit (peu de partants)
remplace le Couplé Gagnant/Placé par un Couplé ORDRE et le Trio par un Trio
ORDRE. On en dérive des drapeaux canoniques que le moteur de paris consomme, pour
proposer EXACTEMENT ce que la course accepte — et jamais un pari impossible.

Fallback (course pas encore re-scrapée → paris_disponibles NULL) : on retombe sur
les booléens est_* existants + on suppose disponibles les paris quasi-universels
(simple gagnant/placé, couplé gagnant/placé, trio). Les paris à l'ORDRE restent
False sans donnée (on préfère rater un couplé ordre qu'en proposer un impossible).
"""
from __future__ import annotations

from typing import Optional

# codePari PMU (préfixe E_) → drapeau canonique de course_info.
_CODE_FLAG = {
    "E_SIMPLE_GAGNANT": "est_simple_gagnant",
    "E_SIMPLE_PLACE":   "est_simple_place",
    "E_COUPLE_GAGNANT": "est_couple_gagnant",
    "E_COUPLE_PLACE":   "est_couple_place",
    "E_COUPLE_ORDRE":   "est_couple_ordre",
    "E_TRIO":           "est_trio",
    "E_TRIO_ORDRE":     "est_trio_ordre",
    "E_DEUX_SUR_QUATRE": "est_2sur4",
    "E_SUPER_QUATRE":   "est_super4",
    "E_TIERCE":         "est_tierce",
    "E_QUARTE_PLUS":    "est_quarte",
    "E_QUINTE_PLUS":    "est_quinte",
    "E_MULTI":          "est_multi",
    "E_PICK5":          "est_pick5",
    "E_PICK_5":         "est_pick5",
}

# Tous les drapeaux gérés (init à False).
_ALL_FLAGS = (
    "est_simple_gagnant", "est_simple_place",
    "est_couple_gagnant", "est_couple_place", "est_couple_ordre",
    "est_trio", "est_trio_ordre",
    "est_2sur4", "est_super4",
    "est_tierce", "est_quarte", "est_quinte",
    "est_multi", "est_pick5",
)


def derive_bet_flags(
    paris_disponibles: Optional[list],
    *,
    est_tierce: bool = False,
    est_quarte: bool = False,
    est_quinte: bool = False,
    est_2sur4: bool = False,
) -> dict:
    """Drapeaux canoniques de disponibilité des paris pour une course.

    Si `paris_disponibles` est fourni (liste de codePari) → vérité PMU exacte.
    Sinon fallback rétro-compat sur les booléens est_* + paris universels.
    """
    flags = {f: False for f in _ALL_FLAGS}

    if paris_disponibles:
        for code in paris_disponibles:
            c = str(code).upper()
            flag = _CODE_FLAG.get(c)
            if flag:
                flags[flag] = True
            # Tolérance aux variantes de libellé PMU (E_MULTI_EN_4, MULTI, PICK_5…) :
            # on détecte aussi par sous-chaîne pour ne pas rater un Multi/Pick5 mal préfixé.
            elif "MULTI" in c:
                flags["est_multi"] = True
            elif "PICK" in c and "5" in c:
                flags["est_pick5"] = True
        return flags

    # ── Fallback (legacy, pas de liste) ──
    flags["est_simple_gagnant"] = True
    flags["est_simple_place"] = True
    flags["est_couple_gagnant"] = True
    flags["est_couple_place"] = True
    flags["est_trio"] = True
    flags["est_2sur4"] = bool(est_2sur4)
    flags["est_tierce"] = bool(est_tierce)
    flags["est_quarte"] = bool(est_quarte)
    flags["est_quinte"] = bool(est_quinte)
    # Paris à l'ordre : pas de donnée fiable sans la liste → on ne propose pas.
    return flags


def course_info_bets(course, *, nb_partants: Optional[int] = None) -> dict:
    """Construit le bloc `course_info` (drapeaux paris + nb_partants) depuis un objet
    Course ORM. Centralise la dérivation pour toutes les routes (mise-plan, bilan,
    enregistrer, analyse, freeze) → cohérence garantie."""
    info = derive_bet_flags(
        getattr(course, "paris_disponibles", None),
        est_tierce=bool(getattr(course, "est_tierce", False)),
        est_quarte=bool(getattr(course, "est_quarte", False)),
        est_quinte=bool(getattr(course, "est_quinte", False)),
        est_2sur4=bool(getattr(course, "est_2sur4", False)),
    )
    info["nb_partants"] = nb_partants if nb_partants is not None else getattr(course, "nb_partants", None)
    return info
