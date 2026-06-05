"""
validation.py — Validation de plausibilité à l'écriture (intégrité données).

Garde-fou au point d'entrée en base : une cote, une distance, une position
aberrante (HTML mal parsé, champ décalé) ne doit JAMAIS être stockée. Mieux vaut
un NULL qu'une fausse donnée qui fausserait les pronostics.

Chaque validateur retourne la valeur si plausible, sinon None. Pur, sans effet de
bord — l'appelant décide quoi faire (ignorer le champ, logguer).
"""
from __future__ import annotations

from typing import Optional

# Bornes de plausibilité (domaine hippique FR).
COTE_MIN, COTE_MAX = 1.01, 1000.0          # cote décimale
DISTANCE_MIN, DISTANCE_MAX = 800, 8000      # mètres (sprint → grand fond)
POSITION_MAX = 40                           # au-delà = aberrant (incidents = 90/99 à part)
NB_PARTANTS_MIN, NB_PARTANTS_MAX = 1, 30
PROBA_MIN, PROBA_MAX = 0.0, 1.0
PENETROMETRE_MIN, PENETROMETRE_MAX = 0.0, 9.0


def _to_float(v) -> Optional[float]:
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def valid_cote(c) -> Optional[float]:
    """Cote décimale plausible (1.01–1000). None sinon."""
    f = _to_float(c)
    if f is None or not (COTE_MIN <= f <= COTE_MAX):
        return None
    return round(f, 2)


def valid_distance(d) -> Optional[int]:
    """Distance en mètres (800–8000). None sinon."""
    f = _to_float(d)
    if f is None or not (DISTANCE_MIN <= f <= DISTANCE_MAX):
        return None
    return int(f)


def valid_position(p, *, incident_ok: bool = True) -> Optional[int]:
    """
    Position d'arrivée. 1–40 plausible. 90/99 = incident accepté si incident_ok.
    None si aberrant.
    """
    f = _to_float(p)
    if f is None:
        return None
    n = int(f)
    if 1 <= n <= POSITION_MAX:
        return n
    if incident_ok and n in (90, 99):
        return n
    return None


def valid_nb_partants(n) -> Optional[int]:
    f = _to_float(n)
    if f is None or not (NB_PARTANTS_MIN <= f <= NB_PARTANTS_MAX):
        return None
    return int(f)


def valid_proba(p) -> Optional[float]:
    f = _to_float(p)
    if f is None or not (PROBA_MIN <= f <= PROBA_MAX):
        return None
    return f


def valid_penetrometre(c) -> Optional[float]:
    f = _to_float(c)
    if f is None or not (PENETROMETRE_MIN <= f <= PENETROMETRE_MAX):
        return None
    return round(f, 2)
