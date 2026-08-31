"""Métriques de CLASSEMENT intra-course, et référence marché.

Pourquoi ce module existe
─────────────────────────
Tout le système mesurait sa qualité avec `roc_auc_score` **poolé** : une seule
AUC calculée sur toutes les lignes de toutes les courses mélangées
(`ml/models.py:_walk_forward_validation`, `_evaluate`, et
`ml/pipeline.py:_head_to_head_auc`). C'est la métrique qui décide des
promotions.

Elle ne mesure pas ce que le produit fait. Une AUC poolée récompense la
capacité à séparer « un partant d'une course facile » d'« un partant d'une
course difficile » — variance INTER-course — alors que le produit ne fait
qu'une chose : ordonner les partants À L'INTÉRIEUR d'une course. Un modèle qui
se contente de relire la cote obtient une excellente AUC poolée.

Mesuré le 20/08/2026 sur 3 322 courses de la cohorte pré-course :

    AUC intra-course du modèle complet     0,7340
    AUC intra-course de la cote qu'il voit  0,7351

Soit 0,001 d'écart, du bruit — alors que l'AUC poolée affichée était de 0,75 et
servait à promouvoir 513 versions successives. Aucune ligne du code ne comparait
jamais le modèle au marché ; le gate ne confrontait le challenger qu'au champion
précédent, si bien que deux modèles sous le marché pouvaient se succéder
indéfiniment.

Ce module fournit les deux manques : une métrique de classement, et la référence
qu'il faut battre pour exister.
"""
from __future__ import annotations

import numpy as np

__all__ = [
    "within_race_auc",
    "market_scores_from_cotes",
    "extract_cotes",
    "rank_auc_report",
]


def _auc_one_group(scores: np.ndarray, labels: np.ndarray) -> float | None:
    """AUC de Mann-Whitney sur UNE course. None si la course ne discrimine pas.

    AUC = P(score d'un partant positif > score d'un partant négatif), les
    ex æquo comptant pour 0,5. Calculée par la somme des rangs moyens plutôt
    que par une double boucle : identique au résultat, mais O(n log n).

    Une course sans positif ou sans négatif ne porte aucune information de
    classement — elle est écartée plutôt que comptée 0,5, ce qui tirerait
    silencieusement toutes les moyennes vers le hasard.
    """
    n = len(scores)
    n_pos = int(labels.sum())
    n_neg = n - n_pos
    if n_pos == 0 or n_neg == 0:
        return None

    # Rangs moyens (les ex æquo partagent le rang moyen → gèrent le 0,5).
    order = np.argsort(scores, kind="mergesort")
    ranks = np.empty(n, dtype=float)
    ranks[order] = np.arange(1, n + 1, dtype=float)
    s_sorted = scores[order]
    i = 0
    while i < n:
        j = i + 1
        while j < n and s_sorted[j] == s_sorted[i]:
            j += 1
        if j - i > 1:
            ranks[order[i:j]] = (i + 1 + j) / 2.0
        i = j

    somme_rangs_pos = float(ranks[labels == 1].sum())
    return (somme_rangs_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def within_race_auc(labels, scores, groups) -> float:
    """AUC de classement moyennée PAR COURSE. 0,5 = hasard, 1,0 = parfait.

    Chaque course pèse le même poids, quel que soit son nombre de partants :
    c'est la sémantique du produit (une fiche par course), et cela empêche les
    grands champs de dominer la moyenne.

    Fonctionne avec n'importe quel nombre de positifs par course — label
    « gagnant » (un seul) comme label « top 3 » (jusqu'à trois).

    Renvoie 0,5 si aucune course n'est exploitable, pour rester une valeur
    neutre comparable plutôt qu'un NaN qui contaminerait un gate.
    """
    labels = np.asarray(labels, dtype=float)
    scores = np.asarray(scores, dtype=float)
    groups = np.asarray(groups)
    if len(labels) == 0 or not (len(labels) == len(scores) == len(groups)):
        return 0.5

    aucs: list[float] = []
    # np.unique trie et donne les indices par groupe en une passe.
    ordre = np.argsort(groups, kind="mergesort")
    g_tri, s_tri, l_tri = groups[ordre], scores[ordre], labels[ordre]
    frontieres = np.flatnonzero(np.r_[True, g_tri[1:] != g_tri[:-1], True])
    for deb, fin in zip(frontieres[:-1], frontieres[1:]):
        a = _auc_one_group(s_tri[deb:fin], l_tri[deb:fin])
        if a is not None:
            aucs.append(a)

    return float(np.mean(aucs)) if aucs else 0.5


def market_scores_from_cotes(cotes) -> np.ndarray | None:
    """Score de classement du MARCHÉ : la probabilité implicite 1/cote.

    Pas besoin de retirer l'overround : il est multiplicatif et commun à tous
    les partants d'une course, donc sans effet sur l'ORDRE. On garde la forme
    la plus simple, moins susceptible de diverger de la référence qu'elle
    prétend incarner.

    None si aucune cote exploitable — l'appelant doit alors s'abstenir de
    conclure plutôt que de comparer à une référence dégradée.
    """
    if cotes is None:
        return None
    c = np.asarray(cotes, dtype=float)
    valides = np.isfinite(c) & (c > 1.0)
    if valides.sum() < 0.5 * len(c):
        return None
    # Une cote absente devient le pire score de la course, jamais un +inf qui
    # placerait le partant en tête.
    return np.where(valides, 1.0 / np.where(valides, c, 1.0), 0.0)


# Colonnes de features portant la cote PMU, par ordre de préférence. La liste
# survit au point 2 (retrait des colonnes de marché du vecteur d'entraînement) :
# extract_cotes rendra None et l'appelant devra fournir les cotes séparément,
# ce qui est le comportement voulu — la référence marché ne doit pas dépendre
# de la présence de la cote dans les features.
_COTE_COLS = ("cote_pmu", "cote_actuelle", "cote_reference")


def extract_cotes(X) -> np.ndarray | None:
    """Cotes PMU depuis un DataFrame de features, si elles s'y trouvent."""
    if X is None or not hasattr(X, "columns"):
        return None
    for col in _COTE_COLS:
        if col in X.columns:
            return X[col].to_numpy(dtype=float, na_value=np.nan)
    return None


def rank_auc_report(labels, scores, groups, cotes=None) -> dict:
    """Classement du modèle, celui du marché, et l'écart entre les deux.

    `delta_market` est le seul chiffre qui dit si le modèle mérite d'exister :
    positif, il apporte quelque chose que la cote ne dit pas ; négatif, le
    produit ferait mieux avec un `ORDER BY cote_pmu`.

    `market_rank_auc` et `delta_market` valent None quand les cotes sont
    indisponibles — un gate ne doit jamais interpréter une absence de mesure
    comme un succès.
    """
    modele = within_race_auc(labels, scores, groups)
    marche_scores = market_scores_from_cotes(cotes)
    if marche_scores is None:
        return {"rank_auc": modele, "market_rank_auc": None, "delta_market": None}

    marche = within_race_auc(labels, marche_scores, groups)
    return {
        "rank_auc": modele,
        "market_rank_auc": marche,
        "delta_market": modele - marche,
    }
