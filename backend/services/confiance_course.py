"""Confiance du modèle sur une course — définition UNIQUE.

Le chiffre « confiance 84/100 » est affiché à trois endroits : la pastille du
programme, l'aperçu public d'une fiche course et la carte « Confiance algo » de
la fiche réservée aux abonnés. Jusqu'au 2026-09-07, les deux premiers prenaient
le score de confiance du cheval classé n°1, la troisième faisait la moyenne des
trois premiers : la même course affichait 84 sur le programme et 80 sur sa
fiche (mesuré en prod sur 07092026R5C7 : 83,96 contre (83,96+79,25+77,33)/3).

Un seul chiffre, une seule règle, un seul endroit qui la porte : la confiance
d'une course est celle que le modèle accorde à SON PREMIER CHOIX. C'est ce que
l'utilisateur lit intuitivement (« à quel point l'algo croit en son favori »),
et c'est la seule définition qui reste vraie quel que soit le nombre de chevaux
notés (une moyenne sur trois n'a pas de sens sur un champ de deux partants).
"""
from __future__ import annotations

from typing import Optional


def confiance_course(score_n1: Optional[float]) -> Optional[int]:
    """Confiance affichée (0-100, entier) à partir du `confidence_score` du n°1.

    `confidence_score` est stocké sur 0-100 (cf. `db.models.Prediction`). On
    arrondit à l'entier le plus proche, comme le faisaient déjà le programme et
    l'aperçu — le front n'a plus rien à recalculer.
    """
    if score_n1 is None:
        return None
    return int(round(float(score_n1)))


def confiance_depuis_predictions(predictions) -> Optional[int]:
    """Même règle, à partir d'une liste d'objets portant `rang_predit` et
    `confidence_score` (lignes ORM `Prediction` ou équivalents).

    On cherche explicitement le rang 1 plutôt que de prendre « le premier de la
    liste » : l'ordre d'une liste dépend de la requête qui l'a produite, la règle
    ne doit pas.
    """
    for p in predictions or ():
        if getattr(p, "rang_predit", None) == 1:
            return confiance_course(getattr(p, "confidence_score", None))
    return None
