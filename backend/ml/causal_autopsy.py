"""
causal_autopsy.py — Tags causaux post-course (Phase 3).

Module de calcul PUR. Explique POURQUOI une course a fini ainsi, en termes de
dynamique physique (et non juste « le modèle s'est trompé ») :

  - le gagnant a-t-il mené de bout en bout, ou est-il venu de loin ?
  - notre favori a-t-il faibli, ou n'a-t-il jamais été dans le coup ?
  - la course s'est-elle jouée sur un train lent (sprint final) ou rapide (usure) ?

Signal principal : position à 500 m du poteau (`temps_passage.position_500m`),
comparée à la position d'arrivée. Aucune donnée inventée : si la position à 500 m
est absente, seuls les tags basés sur proba/arrivée sont émis.
"""
from __future__ import annotations

from typing import Optional

# Seuil : gagner/perdre N places sur les 500 derniers mètres = mouvement notable.
GAIN_NOTABLE = 3


def _final_order(position_reelle: dict) -> list:
    """Numéros classés par position d'arrivée (incidents >= 90 exclus)."""
    valides = [(n, p) for n, p in position_reelle.items() if p and 1 <= p < 90]
    valides.sort(key=lambda x: x[1])
    return [n for n, _ in valides]


def tag_race_causes(
    winner_num: Optional[int],
    position_reelle: dict,
    pos500_by_num: Optional[dict] = None,
    proba_by_num: Optional[dict] = None,
    nb_partants: Optional[int] = None,
) -> list:
    """
    Produit une liste de tags causaux : [{tag, description}].

    position_reelle : {numero: position_arrivee}
    pos500_by_num   : {numero: position_a_500m}  (peut être None / partiel)
    proba_by_num    : {numero: proba_top3 IA}
    """
    pos500_by_num = pos500_by_num or {}
    proba_by_num = proba_by_num or {}
    tags = []

    order = _final_order(position_reelle)
    if not order or winner_num is None:
        return tags

    nb = nb_partants or len(position_reelle)

    def gain(num):
        """Places gagnées entre 500 m et l'arrivée (positif = a remonté)."""
        p500 = pos500_by_num.get(num)
        pfin = position_reelle.get(num)
        if p500 is None or pfin is None or pfin >= 90:
            return None
        return p500 - pfin

    # ── Style du gagnant ───────────────────────────────────────────────
    w500 = pos500_by_num.get(winner_num)
    if w500 is not None:
        if w500 <= 2:
            tags.append({
                "tag": "gagnant_mene_bout_en_bout",
                "description": f"Gagnant (N°{winner_num}) déjà en tête à 500m — course de bout en bout.",
            })
        elif w500 >= 4:
            tags.append({
                "tag": "gagnant_finit_fort",
                "description": f"Gagnant (N°{winner_num}) {w500}e à 500m — est venu de loin, grosse accélération finale.",
            })

    # ── Sort de notre favori (plus forte proba IA) ─────────────────────
    if proba_by_num:
        favori = max(proba_by_num, key=proba_by_num.get)
        fav_fin = position_reelle.get(favori)
        fav500 = pos500_by_num.get(favori)
        top3 = set(order[:3])
        if fav_fin is not None and favori not in top3:
            if fav500 is not None and fav500 <= 3:
                tags.append({
                    "tag": "favori_faiblit",
                    "description": f"Favori IA (N°{favori}) bien placé à 500m ({fav500}e) puis a faibli — fini {fav_fin}e.",
                })
            elif fav500 is not None and fav500 >= 4:
                tags.append({
                    "tag": "favori_jamais_dans_le_coup",
                    "description": f"Favori IA (N°{favori}) déjà distancé à 500m ({fav500}e) — jamais dans le coup.",
                })
            else:
                tags.append({
                    "tag": "favori_decu",
                    "description": f"Favori IA (N°{favori}) hors du top-3 (fini {fav_fin}e).",
                })

    # ── Surprise : gagnant peu probable selon l'IA ─────────────────────
    if winner_num in proba_by_num and proba_by_num[winner_num] < 0.20:
        tags.append({
            "tag": "surprise_outsider",
            "description": f"Gagnant (N°{winner_num}) coté à {proba_by_num[winner_num]*100:.0f}% top-3 par l'IA — surprise.",
        })

    # ── Physionomie de course (train) — nécessite position_500m ────────
    if pos500_by_num:
        gains = [g for n in order if (g := gain(n)) is not None]
        if gains:
            closers = sum(1 for g in gains if g >= GAIN_NOTABLE)
            faders = sum(1 for g in gains if g <= -GAIN_NOTABLE)
            w_gain = gain(winner_num)
            if closers >= 2 and w_gain is not None and w_gain >= GAIN_NOTABLE:
                tags.append({
                    "tag": "train_lent_sprint_final",
                    "description": "Train lent : plusieurs chevaux ont remonté fort dans les 500m, course jouée au sprint.",
                })
            elif faders >= 2 and w500 is not None and w500 <= 2:
                tags.append({
                    "tag": "train_rapide_usure",
                    "description": "Train rapide : des chevaux de tête ont craqué, mais le gagnant a tenu — course d'usure.",
                })

    return tags
