"""Exposants de position — corriger le biais de Harville avec des MESURES.

Le problème
───────────
`ml.combo_bets` prend les probabilités de VICTOIRE comme forces d'un Plackett-Luce.
Ce modèle reproduit exactement la première place — par construction, P(i gagne) =
s_i / Σs — mais il suppose que la course pour la DEUXIÈME place obéit à la même
hiérarchie que celle pour la première. Elle n'y obéit pas : c'est le biais de
Harville, documenté depuis Henery (1981) et Stern (1990), et il va toujours dans le
même sens — le placé du favori est SURESTIMÉ, celui des outsiders sous-estimé.

Ça compte ici parce que tout le catalogue combiné en dépend : Couplé Placé, Trio,
2sur4, Multi. Une probabilité de placé surestimée donne une EV surestimée, donc des
paris émis qui ne devaient pas l'être.

La correction
─────────────
Un exposant par position : à la position j, les forces valent `s^λ_j`, avec
λ₁ = 1 (la victoire est exacte, on n'y touche pas) et λ₂, λ₃ ≤ 1 pour aplatir la
hiérarchie des accessits.

Ce module AJUSTE ces exposants sur les arrivées réelles, il ne les invente pas :
sans mesure suffisante, ils valent 1,0 et le comportement est identique à celui
d'aujourd'hui. Même règle de démarrage à froid que toutes les autres calibrations
du système.

Méthode
───────
On maximise la vraisemblance des arrivées observées sur les courses figées avant
départ (`prediction_evaluation`, mêmes gardes anti-fuite que les isotones) : pour
chaque course on connaît les forces (proba de victoire du modèle, prédite AVANT le
départ, donc hors échantillon pour lui) et l'ordre réel des trois premiers ; la
vraisemblance de cet ordre sous le modèle à exposants s'écrit en forme fermée.
Recherche sur grille — deux paramètres, surface lisse.

Les exposants sont CHOISIS sur les 80 % de courses les plus anciennes et VALIDÉS
sur les 20 % les plus récentes : les deux gains doivent être positifs. Deux
paramètres sur des milliers de courses ne peuvent pas beaucoup sur-apprendre, mais
« pas beaucoup » n'est pas « pas du tout » — et une correction du biais de placé
qui ne tient plus sur le dernier mois n'a pas à être appliquée demain.
"""
from __future__ import annotations

import json
from typing import Optional, Sequence

import numpy as np
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ml.plackett_luce import EXPOSANTS_NEUTRES, forces_par_position, p_ordre_exact

log = structlog.get_logger(module="harville_calibration")

# Nombre minimal de COURSES exploitables avant d'ajuster quoi que ce soit. En
# dessous, on garde les exposants neutres : une correction tirée de trois réunions
# serait pire que pas de correction.
MIN_COURSES = 400
# Bornes de recherche. λ = 1 est le Plackett-Luce nu ; en dessous de 0,4 on ne
# corrige plus un biais, on efface la hiérarchie du modèle.
LAMBDA_MIN, LAMBDA_MAX = 0.40, 1.20
N_PAS = 17
# Gain minimal de log-vraisemblance PAR COURSE exigé pour remplacer les exposants
# neutres — sur la part d'AJUSTEMENT **et** sur celle de VALIDATION. Strictement
# positif : à égalité, on garde le comportement d'avant.
MIN_GAIN_LOGV = 1e-4

_cache: Optional[tuple[float, ...]] = None


def log_vraisemblance(courses: list[tuple[np.ndarray, list[int]]],
                      exposants: Sequence[float]) -> float:
    """Log-vraisemblance moyenne des arrivées observées, sous ces exposants.

    Fonction pure, testable sans base. `courses` = [(forces, ordre_réel_top3)].
    """
    total, n = 0.0, 0
    for forces, ordre in courses:
        if len(forces) < 2 or not ordre:
            continue
        sp = forces_par_position(forces, exposants, n_positions=max(3, len(ordre)))
        p = p_ordre_exact(sp, ordre)
        total += float(np.log(max(p, 1e-15)))
        n += 1
    return total / n if n else float("-inf")


def ajuster_exposants(courses: list[tuple[np.ndarray, list[int]]],
                      lambda_min: float = LAMBDA_MIN,
                      lambda_max: float = LAMBDA_MAX,
                      n_pas: int = N_PAS,
                      frac_ajustement: float = 0.8) -> dict:
    """Exposants (1, λ₂, λ₃) qui améliorent la vraisemblance des arrivées réelles.

    CHOISIS sur une part des courses, VALIDÉS sur l'autre. Les exposants ne sont
    retenus que si le gain se retrouve sur des courses qui n'ont pas servi à les
    choisir. Deux paramètres sur des milliers de courses ne peuvent pas beaucoup
    sur-apprendre — mais « pas beaucoup » n'est pas « pas du tout », et c'est
    l'exigence appliquée partout ailleurs dans ce système : un correcteur qui n'a
    rien prouvé hors de ses propres données ne corrige rien.

    Découpage CHRONOLOGIQUE : les courses arrivent triées, la part de validation est
    la plus RÉCENTE. Une correction du biais de placé qui ne tient plus sur le
    dernier mois n'a pas à être appliquée demain.

    Fonction pure. Renvoie toujours un verdict lisible : les exposants retenus, ceux
    du modèle nu, et les deux écarts de log-vraisemblance qui ont décidé.
    `retenus=False` signifie « la mesure ne conclut pas » — les exposants neutres
    restent en place.

    λ₁ vaut toujours 1 : la première place est exacte sous Plackett-Luce, et la
    toucher casserait la seule propriété que le modèle garantit.
    """
    def _refus(logv_a=None, logv_v=None, gain_a=None, gain_v=None):
        return {"retenus": False, "exposants": list(EXPOSANTS_NEUTRES),
                "logv_neutre": logv_a, "logv_ajuste": logv_v,
                "gain": gain_a, "gain_validation": gain_v,
                "n_courses": len(courses)}

    coupe = int(len(courses) * frac_ajustement)
    ajustement, validation = courses[:coupe], courses[coupe:]
    if not ajustement or not validation:
        return _refus()

    neutre_a = log_vraisemblance(ajustement, EXPOSANTS_NEUTRES)
    neutre_v = log_vraisemblance(validation, EXPOSANTS_NEUTRES)
    if not (np.isfinite(neutre_a) and np.isfinite(neutre_v)):
        return _refus()

    grille = np.linspace(lambda_min, lambda_max, n_pas)
    meilleur, meilleure_logv = None, neutre_a
    for l2 in grille:
        for l3 in grille:
            if l3 > l2:
                continue     # la hiérarchie s'aplatit en descendant les positions
            exps = (1.0, float(l2), float(l3), float(l3), float(l3))
            v = log_vraisemblance(ajustement, exps)
            if v > meilleure_logv:
                meilleure_logv, meilleur = v, exps

    if meilleur is None:
        return _refus(round(neutre_a, 6), round(neutre_a, 6), 0.0, 0.0)

    gain_ajustement = meilleure_logv - neutre_a
    gain_validation = log_vraisemblance(validation, meilleur) - neutre_v
    # LES DEUX doivent être positifs : un gain qui ne survit pas au passage sur des
    # courses non vues est du sur-ajustement, pas une correction.
    if gain_ajustement <= MIN_GAIN_LOGV or gain_validation <= MIN_GAIN_LOGV:
        return _refus(round(neutre_a, 6), round(meilleure_logv, 6),
                      round(gain_ajustement, 6), round(gain_validation, 6))
    return {"retenus": True, "exposants": list(meilleur),
            "logv_neutre": round(neutre_a, 6),
            "logv_ajuste": round(meilleure_logv, 6),
            "gain": round(gain_ajustement, 6),
            "gain_validation": round(gain_validation, 6),
            "n_courses": len(courses)}


async def _charger_courses(session: AsyncSession) -> list[tuple[np.ndarray, list[int]]]:
    """(forces du modèle, ordre réel des trois premiers) par course.

    Source : les prédictions FIGÉES avant le départ, avec les mêmes gardes
    anti-fuite que les calibrations isotones. Les forces sont les probas de
    VICTOIRE brutes du modèle, normalisées par course — exactement ce que
    `ml.combo_bets` passe à `_Sim`.
    """
    rows = (await session.execute(text("""
        SELECT pe.course_id, pa.numero, pe.proba_top1_raw, r.classement
        FROM prediction_evaluation pe
        JOIN participations pa ON pa.participation_id = pe.participation_id
        JOIN courses c         ON c.course_id         = pe.course_id
        JOIN resultats r       ON r.course_id         = pe.course_id
        WHERE pe.is_replayable = true
          AND pe.proba_top1_raw IS NOT NULL
          AND r.classement IS NOT NULL
          AND c.date_heure IS NOT NULL
          AND pe.created_at IS NOT NULL
          AND pe.created_at < c.date_heure
        ORDER BY c.date_heure ASC, pe.course_id ASC
    """))).all()

    par_course: dict[str, list] = {}
    arrivees: dict[str, object] = {}
    for course_id, numero, proba, classement in rows:
        par_course.setdefault(course_id, []).append((int(numero), float(proba)))
        arrivees.setdefault(course_id, classement)

    out: list[tuple[np.ndarray, list[int]]] = []
    for course_id, partants in par_course.items():
        classement = arrivees.get(course_id)
        if isinstance(classement, str):
            try:
                classement = json.loads(classement)
            except (ValueError, TypeError):
                continue
        positions: dict[int, int] = {}
        for e in classement or []:
            try:
                pos = int(e.get("position"))
                if 1 <= pos <= 3:
                    positions[pos] = int(e.get("numero"))
            except (TypeError, ValueError, AttributeError):
                continue
        if len(positions) < 3:
            continue
        index = {num: i for i, (num, _) in enumerate(partants)}
        try:
            ordre = [index[positions[1]], index[positions[2]], index[positions[3]]]
        except KeyError:
            continue        # un arrivant absent des prédictions : course écartée
        forces = np.array([p for _, p in partants], dtype=float)
        somme = forces.sum()
        if somme <= 0 or len(forces) < 4:
            continue
        out.append((forces / somme, ordre))
    return out


async def calculer_et_persister(session: AsyncSession) -> dict:
    """Ajuste les exposants sur les arrivées réelles et les stocke.

    Ne remplace JAMAIS l'état existant quand la mesure ne conclut pas : même règle
    de démarrage à froid que les autres calibrations.
    """
    global _cache
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS harville_exposants (
            id INTEGER PRIMARY KEY,
            data TEXT NOT NULL,
            updated_at TIMESTAMP
        )
    """))
    courses = await _charger_courses(session)
    if len(courses) < MIN_COURSES:
        log.warning("harville.cold_start_preserve", n_courses=len(courses),
                    min_courses=MIN_COURSES)
        return {"status": "skipped_insufficient_data", "n_courses": len(courses)}

    verdict = ajuster_exposants(courses)
    if not verdict["retenus"]:
        log.info("harville.exposants_neutres_conserves", **verdict)
        return {"status": "neutres_conserves", **verdict}

    await session.execute(text("""
        INSERT INTO harville_exposants (id, data, updated_at)
        VALUES (1, :data, CURRENT_TIMESTAMP)
        ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data,
                                       updated_at = EXCLUDED.updated_at
    """), {"data": json.dumps(verdict)})
    _cache = tuple(verdict["exposants"])
    log.info("harville.exposants_ajustes", **verdict)
    return {"status": "ok", **verdict}


async def charger_exposants(session: AsyncSession) -> tuple[float, ...]:
    """Exposants appris, ou neutres. Met le cache mémoire à jour."""
    global _cache
    try:
        r = (await session.execute(text(
            "SELECT data FROM harville_exposants WHERE id = 1"))).first()
        if r and r[0]:
            data = r[0] if isinstance(r[0], dict) else json.loads(r[0])
            exps = data.get("exposants")
            if exps:
                _cache = tuple(float(x) for x in exps)
    except Exception as e:
        log.debug("harville.chargement_ignore", err=str(e)[:120])
    return _cache or EXPOSANTS_NEUTRES


def exposants_en_cache() -> tuple[float, ...]:
    """Exposants pour l'inférence, SANS accès base.

    `ml.combo_bets` est appelé en synchrone depuis le moteur de plan : il ne peut
    pas ouvrir de session. Le cache est rempli au démarrage de l'API et à chaque
    recalcul nocturne ; tant qu'il est vide, on rend les exposants neutres —
    c'est-à-dire le comportement d'avant, jamais une correction devinée.
    """
    return _cache or EXPOSANTS_NEUTRES
