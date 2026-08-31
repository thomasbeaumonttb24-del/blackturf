"""
cote_juste.py — Conversion proba de victoire → « cote juste » affichée.

La cote juste est l'inverse de la probabilité de victoire du modèle, sans marge :
c'est le prix à partir duquel le pari devient rentable si la proba est exacte.

PRÉCISION D'AFFICHAGE
---------------------
L'arrondi était fixé à 1 décimale sur toute la plage. À 4,1 une décimale vaut 2,4 %
de résolution : deux chevaux séparés de 2 % de proba tombaient sur le même nombre.
On adapte donc la précision à l'ordre de grandeur, pour une résolution relative à
peu près constante (~0,5 %) :

    < 10      → 2 décimales   (4,12 / 4,14)
    10 – 100  → 1 décimale    (16,1 / 16,7)
    ≥ 100     → entier        (128 / 214)

Le plafond passe de 100 à 999 : écraser tous les gros outsiders sur « 100 » créait
des ex æquo purement cosmétiques entre des chevaux que le modèle sépare d'un facteur 3.
"""
from __future__ import annotations

from typing import Optional

COTE_JUSTE_MIN = 1.01
COTE_JUSTE_MAX = 999.0
# En-deçà, l'inverse n'a plus de sens d'affichage (1/0.001 = 1000 > plafond).
PROBA_MIN = 0.001


def cote_juste(proba: Optional[float]) -> Optional[float]:
    """Cote juste affichable pour une proba de victoire. None si proba inexploitable."""
    try:
        p = float(proba)
    except (TypeError, ValueError):
        return None
    if p <= PROBA_MIN:
        return None
    valeur = min(COTE_JUSTE_MAX, max(COTE_JUSTE_MIN, 1.0 / p))
    if valeur < 10.0:
        return round(valeur, 2)
    if valeur < 100.0:
        return round(valeur, 1)
    return round(valeur, 0)
