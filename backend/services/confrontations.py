"""
Confrontations directes — head-to-head entre les partants d'une course.

Reconstruit, à partir de l'historique des courses (`HistoriqueCourse`), tous les
duels passés entre les chevaux engagés aujourd'hui : qui a déjà battu qui, combien
de fois, avec quel écart, et lors de quelle dernière rencontre.

Aucune source externe : tout est calculé depuis la base. Deux chevaux se sont
"affrontés" s'ils ont une ligne d'historique partageant la même date + le même
hippodrome (≈ même course). On compare alors leurs positions d'arrivée.
"""
from __future__ import annotations

import unicodedata
from collections import defaultdict
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Participation, Cheval, HistoriqueCourse

log = structlog.get_logger()

# Position d'arrivée >= ce seuil = incident (disq./tombé/arrêté) → pas de duel valide.
POSITION_INCIDENT = 90


def _norm_hippo(nom: Optional[str]) -> str:
    """Normalise un nom d'hippodrome pour le matching (accents, casse, espaces)."""
    if not nom:
        return ""
    s = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


def _race_key(h: HistoriqueCourse) -> tuple:
    """Clé d'une course passée : même date + même hippodrome ⇒ même épreuve."""
    return (h.date_course, _norm_hippo(h.hippodrome))


def _valid_position(pos: Optional[int]) -> bool:
    return pos is not None and 1 <= pos < POSITION_INCIDENT


async def compute_confrontations(
    db: AsyncSession,
    course_id: str,
    *,
    max_history_per_cheval: int = 60,
) -> dict:
    """
    Calcule les confrontations directes entre les partants d'une course.

    Retourne un dict :
      {
        "course_id": ...,
        "nb_partants": int,
        "nb_paires_avec_duel": int,
        "paires": [ {a, b, nb, a_wins, b_wins, nuls, derniere, ecart_moyen}, ... ],
        "par_cheval": [ {numero, nom, cheval_id, nb_adversaires_connus,
                         victoires, defaites, bilan, top_victime, bete_noire}, ... ],
      }
    """
    # 1. Partants de la course --------------------------------------------------
    part_res = await db.execute(
        select(
            Participation.cheval_id,
            Participation.numero,
            Cheval.nom,
        )
        .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
        .where(
            Participation.course_id == course_id,
            Participation.non_partant.is_(False),
        )
        .order_by(Participation.numero)
    )
    partants = part_res.all()
    if len(partants) < 2:
        return {
            "course_id": course_id,
            "nb_partants": len(partants),
            "nb_paires_avec_duel": 0,
            "paires": [],
            "par_cheval": [],
        }

    cheval_ids = [p.cheval_id for p in partants]
    nom_par_id = {p.cheval_id: p.nom for p in partants}
    numero_par_id = {p.cheval_id: p.numero for p in partants}

    # 2. Historique de tous les partants ---------------------------------------
    hist_res = await db.execute(
        select(HistoriqueCourse)
        .where(HistoriqueCourse.cheval_id.in_(cheval_ids))
        .order_by(HistoriqueCourse.date_course.desc())
    )
    # On borne par cheval pour ne pas exploser sur des chevaux à long palmarès.
    hist_par_cheval: dict[str, list[HistoriqueCourse]] = defaultdict(list)
    for h in hist_res.scalars().all():
        if len(hist_par_cheval[h.cheval_id]) < max_history_per_cheval:
            hist_par_cheval[h.cheval_id].append(h)

    # 3. Indexe chaque course passée par (date, hippodrome) --------------------
    #    races[key][cheval_id] = ligne d'historique
    races: dict[tuple, dict[str, HistoriqueCourse]] = defaultdict(dict)
    partants_set = set(cheval_ids)
    for cid, lignes in hist_par_cheval.items():
        for h in lignes:
            races[_race_key(h)][cid] = h

    # 4. Pour chaque course commune à ≥2 partants → enregistre les duels --------
    #    duels[(a,b)] avec a<b (ordre stable) = liste de rencontres
    duels: dict[tuple, list[dict]] = defaultdict(list)
    for key, par_cheval in races.items():
        presents = [cid for cid in par_cheval if cid in partants_set]
        if len(presents) < 2:
            continue
        for i in range(len(presents)):
            for j in range(i + 1, len(presents)):
                a, b = presents[i], presents[j]
                ha, hb = par_cheval[a], par_cheval[b]
                if not (_valid_position(ha.position_arrivee) and _valid_position(hb.position_arrivee)):
                    continue
                pair = (a, b) if a < b else (b, a)
                duels[pair].append({
                    "date": key[0],
                    "hippodrome": ha.hippodrome,
                    "discipline": ha.discipline,
                    "distance": ha.distance,
                    # positions/écarts rattachés à l'ordre canonique (pair[0], pair[1])
                    "pos_first": (ha if pair[0] == a else hb).position_arrivee,
                    "pos_second": (hb if pair[0] == a else ha).position_arrivee,
                    "ecart_first": (ha if pair[0] == a else hb).ecart_longueurs,
                    "ecart_second": (hb if pair[0] == a else ha).ecart_longueurs,
                })

    # 5. Agrège par paire -------------------------------------------------------
    paires_out = []
    # bilan[cheval_id] = {"v": victoires, "d": defaites, victimes:{id:n}, bourreaux:{id:n}}
    bilan: dict[str, dict] = {
        cid: {"v": 0, "d": 0, "victimes": defaultdict(int), "bourreaux": defaultdict(int)}
        for cid in cheval_ids
    }

    for (first, second), rencontres in duels.items():
        first_wins = second_wins = nuls = 0
        ecarts = []
        for r in rencontres:
            pf, ps = r["pos_first"], r["pos_second"]
            if pf < ps:
                first_wins += 1
                bilan[first]["v"] += 1
                bilan[second]["d"] += 1
                bilan[first]["victimes"][second] += 1
                bilan[second]["bourreaux"][first] += 1
            elif ps < pf:
                second_wins += 1
                bilan[second]["v"] += 1
                bilan[first]["d"] += 1
                bilan[second]["victimes"][first] += 1
                bilan[first]["bourreaux"][second] += 1
            else:
                nuls += 1
            if r["ecart_first"] is not None and r["ecart_second"] is not None:
                ecarts.append(abs(r["ecart_first"] - r["ecart_second"]))

        derniere = max(rencontres, key=lambda r: r["date"])
        paires_out.append({
            "a_cheval_id": first,
            "a_numero": numero_par_id[first],
            "a_nom": nom_par_id[first],
            "b_cheval_id": second,
            "b_numero": numero_par_id[second],
            "b_nom": nom_par_id[second],
            "nb_rencontres": len(rencontres),
            "a_victoires": first_wins,
            "b_victoires": second_wins,
            "nuls": nuls,
            "ecart_moyen_longueurs": round(sum(ecarts) / len(ecarts), 2) if ecarts else None,
            "derniere_rencontre": {
                "date": derniere["date"],
                "hippodrome": derniere["hippodrome"],
                "discipline": derniere["discipline"],
                "distance": derniere["distance"],
                "a_position": derniere["pos_first"],
                "b_position": derniere["pos_second"],
            },
        })

    paires_out.sort(key=lambda p: p["nb_rencontres"], reverse=True)

    # 6. Synthèse par cheval ----------------------------------------------------
    par_cheval_out = []
    for cid in cheval_ids:
        b = bilan[cid]
        adversaires = set(b["victimes"]) | set(b["bourreaux"])
        top_victime = max(b["victimes"].items(), key=lambda kv: kv[1], default=None)
        bete_noire = max(b["bourreaux"].items(), key=lambda kv: kv[1], default=None)
        par_cheval_out.append({
            "numero": numero_par_id[cid],
            "nom": nom_par_id[cid],
            "cheval_id": cid,
            "nb_adversaires_connus": len(adversaires),
            "victoires": b["v"],
            "defaites": b["d"],
            "bilan": f"{b['v']}-{b['d']}",
            "top_victime": (
                {"nom": nom_par_id[top_victime[0]], "numero": numero_par_id[top_victime[0]],
                 "nb": top_victime[1]} if top_victime else None
            ),
            "bete_noire": (
                {"nom": nom_par_id[bete_noire[0]], "numero": numero_par_id[bete_noire[0]],
                 "nb": bete_noire[1]} if bete_noire else None
            ),
        })

    # Tri : meilleur bilan net d'abord (victoires - défaites)
    par_cheval_out.sort(key=lambda c: (c["victoires"] - c["defaites"]), reverse=True)

    return {
        "course_id": course_id,
        "nb_partants": len(partants),
        "nb_paires_avec_duel": len(paires_out),
        "paires": paires_out,
        "par_cheval": par_cheval_out,
    }
