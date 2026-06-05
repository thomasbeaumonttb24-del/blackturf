"""
confrontation_features.py — Features de confrontations directes (Phase 1.3).

Module de calcul PUR (aucune DB). À partir de l'historique déjà chargé des
partants d'une course, produit pour chaque cheval son bilan de duels passés
contre les AUTRES partants du jour : a-t-il déjà battu ses rivaux, combien de
fois, contre combien d'adversaires distincts.

Deux chevaux se sont affrontés s'ils ont une ligne d'historique partageant la
même date + le même hippodrome. On compare alors leurs positions d'arrivée.

RÈGLE D'INTÉGRITÉ : aucune valeur inventée. Pas de rencontre connue → features
neutres + conf_nb_data=0 (le modèle sait que le signal est absent).

Format des lignes d'historique attendu (tuple, cf. SELECT batch de features.py) :
  idx 0 = position_arrivee, idx 3 = hippodrome, idx 4 = date_course
"""
from __future__ import annotations

import unicodedata
from collections import defaultdict

POSITION_INCIDENT = 90  # position >= seuil = incident → duel non valide

CONFRONTATION_FEATURE_KEYS = (
    "conf_nb_rencontres",
    "conf_taux_victoire",
    "conf_bilan_net",
    "conf_nb_rivaux_battus",
    "conf_nb_rivaux_bourreaux",
    "conf_nb_data",
)

_NEUTRAL = {k: 0.0 for k in CONFRONTATION_FEATURE_KEYS}


def _norm_hippo(nom) -> str:
    if not nom:
        return ""
    s = unicodedata.normalize("NFKD", str(nom)).encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


def _valid_pos(p) -> bool:
    return isinstance(p, int) and 1 <= p < POSITION_INCIDENT


def _race_key(row):
    # (date, hippodrome normalisé)
    date = row[4] if len(row) > 4 else None
    hippo = row[3] if len(row) > 3 else None
    return (date, _norm_hippo(hippo))


def compute_confrontation_features(hist_by_cheval: dict, field_ids) -> dict:
    """
    hist_by_cheval : {cheval_id: [ligne_historique, ...]} pour les partants.
    field_ids      : itérable des cheval_id présents dans la course.

    Retourne {cheval_id: {features de confrontation}}. Toujours toutes les clés
    (CONFRONTATION_FEATURE_KEYS) ; neutre si aucune rencontre connue.
    """
    field = [c for c in field_ids if c]
    result = {cid: dict(_NEUTRAL) for cid in field}
    if len(field) < 2:
        return result

    field_set = set(field)

    # Indexe chaque course passée par (date, hippodrome) → {cheval_id: position}
    races: dict[tuple, dict] = defaultdict(dict)
    for cid in field:
        for row in hist_by_cheval.get(cid, []) or []:
            pos = row[0] if len(row) > 0 else None
            if not _valid_pos(pos):
                continue
            key = _race_key(row)
            if key[0] is None:
                continue
            # garde la meilleure (plus récente non gérée ici : 1 ligne/cheval/course)
            races[key].setdefault(cid, pos)

    # Tally par cheval
    stats = {cid: {"v": 0, "d": 0, "battus": set(), "bourreaux": set()} for cid in field}
    for key, par_cheval in races.items():
        presents = [c for c in par_cheval if c in field_set]
        if len(presents) < 2:
            continue
        for i in range(len(presents)):
            for j in range(i + 1, len(presents)):
                a, b = presents[i], presents[j]
                pa, pb = par_cheval[a], par_cheval[b]
                if pa < pb:
                    stats[a]["v"] += 1; stats[a]["battus"].add(b)
                    stats[b]["d"] += 1; stats[b]["bourreaux"].add(a)
                elif pb < pa:
                    stats[b]["v"] += 1; stats[b]["battus"].add(a)
                    stats[a]["d"] += 1; stats[a]["bourreaux"].add(b)
                # égalité (dead-heat) : ni victoire ni défaite

    for cid in field:
        s = stats[cid]
        total = s["v"] + s["d"]
        if total > 0:
            result[cid] = {
                "conf_nb_rencontres": float(total),
                "conf_taux_victoire": round(s["v"] / total, 3),
                "conf_bilan_net": round((s["v"] - s["d"]) / total, 3),
                "conf_nb_rivaux_battus": float(len(s["battus"])),
                "conf_nb_rivaux_bourreaux": float(len(s["bourreaux"])),
                "conf_nb_data": float(total),
            }
    return result
