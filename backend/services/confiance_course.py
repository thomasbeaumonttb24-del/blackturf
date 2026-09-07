"""Confiance du modèle sur une course — définition UNIQUE, et ce qu'elle vaut.

Le chiffre « confiance 84/100 » est affiché à trois endroits : la pastille du
programme, l'aperçu public d'une fiche course et la carte de la fiche réservée
aux abonnés. Jusqu'au 2026-09-07, les deux premiers prenaient le score de
confiance du cheval classé n°1, la troisième faisait la moyenne des trois
premiers : la même course affichait 84 sur le programme et 80 sur sa fiche.

Un seul chiffre, une seule règle : la confiance d'une course est celle que le
modèle accorde à SON PREMIER CHOIX (`confidence_score`, 0-100).

CE QUE CE SCORE MESURE, et ne mesure pas (cf. ml/models.py,
`predict_with_confidence`) : 0,6 × accord des trois sous-modèles entre eux
+ 0,4 × proximité de la probabilité avec la cote du marché. C'est un ACCORD,
pas une chance de gagner. Un cheval donné gagnant à 19 % peut porter un accord
de 77/100 sans contradiction : les trois modèles et le marché s'entendent pour
dire « 19 % ».

MESURÉ le 2026-09-07 sur 90 jours (3 912 n°1 réglés) : le n°1 gagne 29 % quand
l'accord est sous 60 et 34 % quand il dépasse 85 ; corrélation avec la
probabilité prédite 0,13, avec la cote 0,11. Le score discrimine peu. Plutôt
que d'afficher un nombre que le lecteur prend pour une probabilité, on lui
donne à côté le fait mesurable : « à ce niveau d'accord, le n°1 a gagné X %
des N dernières courses ». Aucun chiffre inventé : tout vient de la base.
"""
from __future__ import annotations

import time
from typing import Optional

from sqlalchemy import text

# Tranches d'accord (bornes basses) : celles de la mesure du 2026-09-07.
TRANCHES = (0, 60, 70, 75, 80, 85)
FENETRE_JOURS = 90
_TTL_SECONDES = 3600

_cache: dict = {"a": 0.0, "table": None}


def confiance_course(score_n1: Optional[float]) -> Optional[int]:
    """Confiance affichée (0-100, entier) à partir du `confidence_score` du n°1."""
    if score_n1 is None:
        return None
    return int(round(float(score_n1)))


def confiance_depuis_predictions(predictions) -> Optional[int]:
    """Même règle, à partir d'objets portant `rang_predit` et `confidence_score`.

    On cherche explicitement le rang 1 plutôt que « le premier de la liste » :
    l'ordre d'une liste dépend de la requête qui l'a produite, la règle non.
    """
    for p in predictions or ():
        if getattr(p, "rang_predit", None) == 1:
            return confiance_course(getattr(p, "confidence_score", None))
    return None


def tranche(score: Optional[int]) -> Optional[tuple[int, Optional[int]]]:
    """(borne basse, borne haute exclue ou None) de la tranche d'un score."""
    if score is None:
        return None
    s = float(score)
    for i, bas in enumerate(TRANCHES):
        haut = TRANCHES[i + 1] if i + 1 < len(TRANCHES) else None
        if haut is None or s < haut:
            return (bas, haut)
    return None


_SQL_REUSSITE = f"""
WITH res AS (
  SELECT DISTINCT ON (cheval_id, course_id) cheval_id, course_id, position_arrivee
  FROM historique_courses WHERE course_id IS NOT NULL AND position_arrivee IS NOT NULL
  ORDER BY cheval_id, course_id, position_arrivee
)
SELECT p.confidence_score AS conf, (r.position_arrivee = 1) AS gagne
FROM predictions p
JOIN participations pa ON pa.participation_id = p.participation_id
JOIN courses c ON c.course_id = p.course_id
JOIN res r ON r.cheval_id = pa.cheval_id AND r.course_id = p.course_id
WHERE p.rang_predit = 1 AND c.statut = 'termine'
  AND c.date_heure >= now() - interval '{FENETRE_JOURS} days'
  -- borne pré-départ : une prédiction recalculée après l'arrivée ne prouve rien
  AND p.created_at < c.date_heure
  AND NOT pa.non_partant AND r.position_arrivee < 99 AND p.confidence_score IS NOT NULL
"""


async def reussite_par_tranche(session) -> dict:
    """{borne basse: {"n": int, "gagne_pct": float}} sur FENETRE_JOURS, cache 1 h.

    PostgreSQL seulement (`DISTINCT ON`) : ailleurs, ou en cas d'erreur, on
    renvoie {} et l'affichage omet la ligne — jamais un chiffre de repli.
    """
    if _cache["table"] is not None and time.monotonic() - _cache["a"] < _TTL_SECONDES:
        return _cache["table"]
    # `DISTINCT ON` n'existe qu'en PostgreSQL. Sur un autre moteur (SQLite en
    # test) on ne tente même pas la requête : un échec SQL avorterait la
    # transaction de l'appelant, et le rollback de rattrapage effacerait ce que
    # le test venait d'insérer.
    bind = getattr(session, "bind", None)
    if bind is not None and getattr(getattr(bind, "dialect", None), "name", "") != "postgresql":
        return {}
    table: dict = {}
    try:
        rows = (await session.execute(text(_SQL_REUSSITE))).all()
        agg: dict = {}
        for conf, gagne in rows:
            t = tranche(conf)
            if t is None:
                continue
            e = agg.setdefault(t[0], [0, 0])
            e[0] += 1
            e[1] += 1 if gagne else 0
        table = {bas: {"n": n, "gagne_pct": round(100.0 * g / n, 1)} for bas, (n, g) in agg.items() if n}
    except Exception:
        try:
            from db.database import desempoisonner
            await desempoisonner(session)
        except Exception:
            pass
        # Ne pas réessayer à chaque requête pendant une panne : vide, 5 min.
        _cache["table"], _cache["a"] = {}, time.monotonic() - _TTL_SECONDES + 300
        return {}
    _cache["table"], _cache["a"] = table, time.monotonic()
    return table


def contexte_confiance(score: Optional[int], table: dict) -> Optional[dict]:
    """Le fait mesuré qui accompagne le score, ou None si rien de mesuré.

    Clés : score, tranche_min, tranche_max (None = « et plus »), n_courses,
    n1_gagne_pct, fenetre_jours. Une tranche de moins de 50 courses n'est pas
    servie : on ne cite pas un pourcentage calculé sur trois cas.
    """
    t = tranche(score)
    if t is None or not table:
        return None
    e = table.get(t[0])
    if not e or e["n"] < 50:
        return None
    return {
        "score": int(score),
        "tranche_min": t[0],
        "tranche_max": t[1],
        "n_courses": e["n"],
        "n1_gagne_pct": e["gagne_pct"],
        "fenetre_jours": FENETRE_JOURS,
    }
