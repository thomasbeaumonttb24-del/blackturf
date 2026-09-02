"""ALPHA — la confiance accordée au modèle face au marché, APPRISE.

Ce que fait alpha
─────────────────
La probabilité de victoire servie est un mélange :

    p_servie = alpha × p_modèle + (1 − alpha) × p_marché_dévigué

`alpha` décroît avec la cote (le modèle est moins fiable sur les gros outsiders).
C'est le dernier arbitrage de toute la chaîne, et il décide de tout ce qui suit :
le classement affiché, les cotes justes, l'EV, donc les paris émis.

Le problème
───────────
Ses quatre paramètres — ALPHA_MAX 0,42, ALPHA_MIN 0,12, seuil 12, décroissance
0,030 — sont posés à la main. Le commentaire de `ml.pipeline` qui les accompagne
les justifie par un raisonnement (« le marché agrège l'info de milliers de
parieurs »), pas par une mesure : rien n'a jamais vérifié que 0,42 valait mieux que
0,30 ou 0,55 sur les vraies arrivées.

Or ce réglage n'est pas neutre, et il dépend de ce que le modèle a appris. Mesuré
sur six jeux simulés, en faisant varier la finesse du marché : l'alpha qui maximise
le classement servi va de 0,05 à 0,95 selon le cas. Une constante ne peut pas
couvrir cet écart — et un modèle entraîné autrement (cf. le drapeau
`market_residual`) déplace l'optimum d'un bout à l'autre de la plage.

Ce que fait ce module
─────────────────────
Il ajuste `alpha_max` sur les courses figées avant départ, en maximisant la
log-vraisemblance du VRAI gagnant — une règle de score propre, celle qui compte
pour des probabilités qui alimentent une EV.

DEUX conditions pour remplacer la valeur en place, toutes deux mesurées sur des
courses qui n'ont pas servi à choisir :
  1. la log-vraisemblance s'améliore ;
  2. le CLASSEMENT intra-course ne se dégrade pas — le produit ordonne des
     partants, on n'échange pas cette qualité-là contre de la calibration.

Sans mesure suffisante, ou si l'une des deux conditions échoue, la valeur d'origine
reste en place. Aucune valeur inventée, jamais.
"""
from __future__ import annotations

import json
from typing import Optional, Sequence

import numpy as np
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(module="blend_calibration")

# Valeurs EN PLACE — celles de `ml.pipeline.predict_course`. Elles restent la
# référence et le repli : ce module ne les remplace que sur preuve.
ALPHA_MAX_DEFAUT = 0.42
ALPHA_MIN_DEFAUT = 0.12
ALPHA_FULL_COTE = 12.0
ALPHA_DECAY = 0.030

# Nombre minimal de COURSES exploitables avant d'ajuster. En dessous, on garde les
# valeurs en place : un alpha tiré de quelques réunions serait pire qu'un alpha
# réglé à la main.
MIN_COURSES = 400
# Grille de recherche sur alpha_max. Le pas de 0,05 est plus fin que l'écart que la
# mesure sait distinguer : inutile d'aller plus loin.
GRILLE_ALPHA = tuple(round(x, 2) for x in np.arange(0.05, 0.96, 0.05))
# Gain minimal de log-vraisemblance PAR COURSE exigé pour remplacer la valeur en
# place. Strictement positif : à égalité, on ne touche à rien.
MIN_GAIN_LOGV = 1e-4

_cache: Optional[dict] = None


def melange(p_modele: np.ndarray, cotes: np.ndarray,
            alpha_max: float = ALPHA_MAX_DEFAUT,
            alpha_min: float = ALPHA_MIN_DEFAUT,
            seuil: float = ALPHA_FULL_COTE,
            decay: float = ALPHA_DECAY) -> np.ndarray:
    """Le blend marché, à l'identique de `ml.pipeline.predict_course`.

    Fonction PURE. Elle DOIT rester le miroir exact du pipeline : si les deux
    divergent, l'alpha est ajusté sur un mélange qui n'est pas celui qu'on sert.

    Un partant sans cote garde la proba du modèle — comme en production, où une
    cote manquante ne doit pas valoir « proba nulle ».
    """
    p = np.asarray(p_modele, dtype=float)
    c = np.asarray(cotes, dtype=float)
    alpha = np.clip(alpha_max - decay * np.maximum(c - seuil, 0.0),
                    alpha_min, alpha_max)
    implied = np.where(c > 1.0, 1.0 / np.where(c > 1.0, c, 1.0), 0.0)
    somme = float(implied.sum())
    if somme <= 0:
        return p
    implied_norm = implied / somme
    blend = np.where(implied > 0, alpha * p + (1.0 - alpha) * implied_norm, p)
    total = float(blend.sum())
    return blend / total if total > 0 else p


def _log_vraisemblance(courses: Sequence[tuple], alpha_max: float) -> float:
    """Log-vraisemblance moyenne du VRAI gagnant sous cet alpha.

    Règle de score PROPRE : elle récompense une probabilité juste, pas seulement un
    bon ordre. C'est ce qu'il faut pour des probabilités qui alimentent une EV.
    """
    total, n = 0.0, 0
    for p_modele, cotes, gagnant in courses:
        p = melange(p_modele, cotes, alpha_max=alpha_max)
        total += float(np.log(max(float(p[gagnant]), 1e-15)))
        n += 1
    return total / n if n else float("-inf")


def _rang_auc(courses: Sequence[tuple], alpha_max: float) -> float:
    """Classement intra-course moyen du mélange, chaque course pesant pareil."""
    from ml.ranking_metrics import within_race_auc

    labels, scores, groupes = [], [], []
    for i, (p_modele, cotes, gagnant) in enumerate(courses):
        p = melange(p_modele, cotes, alpha_max=alpha_max)
        for j in range(len(p)):
            labels.append(1.0 if j == gagnant else 0.0)
            scores.append(float(p[j]))
            groupes.append(i)
    if not labels:
        return 0.5
    return within_race_auc(np.array(labels), np.array(scores), np.array(groupes))


def ajuster_alpha(courses: Sequence[tuple], frac_ajustement: float = 0.8,
                  alpha_en_place: float = ALPHA_MAX_DEFAUT) -> dict:
    """`alpha_max` qui maximise la log-vraisemblance du gagnant, VALIDÉ hors échantillon.

    `courses` = [(p_modèle_normalisée, cotes, index_du_gagnant)].

    Fonction pure. Deux conditions pour remplacer la valeur en place, toutes deux
    mesurées sur les courses les plus RÉCENTES, qui n'ont pas servi à choisir :
    la log-vraisemblance s'améliore, ET le classement intra-course ne se dégrade
    pas. Le produit ordonne des partants : on n'échange pas cette qualité-là contre
    de la calibration.
    """
    def _refus(**extra):
        return {"retenu": False, "alpha_max": alpha_en_place, **extra}

    coupe = int(len(courses) * frac_ajustement)
    ajustement, validation = list(courses[:coupe]), list(courses[coupe:])
    if not ajustement or not validation:
        return _refus(raison="pas de part de validation")

    base_a = _log_vraisemblance(ajustement, alpha_en_place)
    if not np.isfinite(base_a):
        return _refus(raison="log-vraisemblance non calculable")

    meilleur, meilleure = alpha_en_place, base_a
    for a in GRILLE_ALPHA:
        v = _log_vraisemblance(ajustement, a)
        if v > meilleure:
            meilleure, meilleur = v, float(a)
    if meilleur == alpha_en_place:
        return _refus(raison="aucun alpha ne fait mieux sur la part d'ajustement",
                      logv_en_place=round(base_a, 6))

    logv_ref = _log_vraisemblance(validation, alpha_en_place)
    logv_new = _log_vraisemblance(validation, meilleur)
    rang_ref = _rang_auc(validation, alpha_en_place)
    rang_new = _rang_auc(validation, meilleur)
    gain_logv = logv_new - logv_ref
    gain_rang = rang_new - rang_ref

    commun = {
        "alpha_candidat": meilleur, "alpha_en_place": alpha_en_place,
        "logv_validation_en_place": round(logv_ref, 6),
        "logv_validation_candidat": round(logv_new, 6),
        "gain_logv": round(gain_logv, 6),
        "rang_validation_en_place": round(rang_ref, 6),
        "rang_validation_candidat": round(rang_new, 6),
        "gain_rang": round(gain_rang, 6),
        "n_courses": len(courses),
    }
    if gain_logv <= MIN_GAIN_LOGV:
        return _refus(raison="pas de gain hors échantillon", **commun)
    if gain_rang < 0:
        return _refus(raison="le classement se dégraderait", **commun)
    return {"retenu": True, "alpha_max": meilleur, **commun}


async def _charger_courses(session: AsyncSession) -> list[tuple]:
    """(proba modèle brute normalisée, cotes, index du gagnant) par course.

    Source : les prédictions FIGÉES avant le départ (`prediction_evaluation`, mêmes
    gardes anti-fuite que les isotones). La proba est la BRUTE — celle d'avant le
    blend — puisque c'est elle que le blend prend en entrée. La cote retenue est
    celle FIGÉE au moment du conseil quand elle existe : celle qui a réellement
    servi à mélanger, pas celle d'aujourd'hui.
    """
    rows = (await session.execute(text("""
        SELECT pe.course_id, pa.numero, pe.proba_top1_raw,
               COALESCE(pe.cote_figee, pa.cote_pmu) AS cote, r.classement
        FROM prediction_evaluation pe
        JOIN participations pa ON pa.participation_id = pe.participation_id
        JOIN courses c         ON c.course_id         = pe.course_id
        JOIN resultats r       ON r.course_id         = pe.course_id
        WHERE pe.is_replayable = true
          AND pe.proba_top1_raw IS NOT NULL
          AND COALESCE(pe.cote_figee, pa.cote_pmu) > 1
          AND r.classement IS NOT NULL
          AND c.date_heure IS NOT NULL
          AND pe.created_at IS NOT NULL
          AND pe.created_at < c.date_heure
        ORDER BY c.date_heure ASC, pe.course_id ASC
    """))).all()

    par_course: dict[str, list] = {}
    arrivees: dict[str, object] = {}
    for course_id, numero, proba, cote, classement in rows:
        par_course.setdefault(course_id, []).append(
            (int(numero), float(proba), float(cote)))
        arrivees.setdefault(course_id, classement)

    out: list[tuple] = []
    for course_id, partants in par_course.items():
        classement = arrivees.get(course_id)
        if isinstance(classement, str):
            try:
                classement = json.loads(classement)
            except (ValueError, TypeError):
                continue
        gagnant_num = None
        for e in classement or []:
            try:
                if int(e.get("position")) == 1:
                    gagnant_num = int(e.get("numero"))
                    break
            except (TypeError, ValueError, AttributeError):
                continue
        if gagnant_num is None or len(partants) < 4:
            continue
        index = {num: i for i, (num, _, _) in enumerate(partants)}
        if gagnant_num not in index:
            continue    # gagnant absent des prédictions : course écartée
        p = np.array([x for _, x, _ in partants], dtype=float)
        somme = p.sum()
        if somme <= 0:
            continue
        cotes = np.array([c for _, _, c in partants], dtype=float)
        out.append((p / somme, cotes, index[gagnant_num]))
    return out


async def calculer_et_persister(session: AsyncSession) -> dict:
    """Ajuste `alpha_max` sur les arrivées réelles et le stocke.

    Ne remplace JAMAIS la valeur en place quand la mesure ne conclut pas : même
    règle de démarrage à froid que toutes les autres calibrations du système.
    """
    global _cache
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS blend_alpha (
            id INTEGER PRIMARY KEY,
            data TEXT NOT NULL,
            updated_at TIMESTAMP
        )
    """))
    courses = await _charger_courses(session)
    if len(courses) < MIN_COURSES:
        log.warning("blend_alpha.cold_start_preserve", n_courses=len(courses),
                    min_courses=MIN_COURSES)
        return {"status": "skipped_insufficient_data", "n_courses": len(courses)}

    en_place = (await charger_alpha(session))["alpha_max"]
    verdict = ajuster_alpha(courses, alpha_en_place=en_place)
    if not verdict["retenu"]:
        log.info("blend_alpha.valeur_conservee", **verdict)
        return {"status": "valeur_conservee", **verdict}

    await session.execute(text("""
        INSERT INTO blend_alpha (id, data, updated_at)
        VALUES (1, :data, CURRENT_TIMESTAMP)
        ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data,
                                       updated_at = EXCLUDED.updated_at
    """), {"data": json.dumps(verdict)})
    _cache = dict(verdict)
    log.info("blend_alpha.ajuste", **verdict)
    return {"status": "ok", **verdict}


async def charger_alpha(session: AsyncSession) -> dict:
    """Alpha appris, ou celui en place. Met le cache mémoire à jour."""
    global _cache
    try:
        r = (await session.execute(text(
            "SELECT data FROM blend_alpha WHERE id = 1"))).first()
        if r and r[0]:
            data = r[0] if isinstance(r[0], dict) else json.loads(r[0])
            if data.get("alpha_max"):
                _cache = data
    except Exception as e:
        # DÉSEMPOISONNER la transaction. asyncpg marque la transaction AVORTÉE dès
        # qu'une requête échoue — ici typiquement « relation inexistante » avant le
        # premier calcul nocturne. Sans ce rollback, la requête SUIVANTE échoue non
        # pour son propre défaut mais parce que la transaction est déjà morte, et
        # son diagnostic ment (constaté au démarrage : `blend_alpha` rapportait
        # « transaction avortée » alors que son seul tort était de passer après
        # `harville`).
        try:
            await session.rollback()
        except Exception:
            pass
        log.debug("blend_alpha.chargement_ignore", err=str(e)[:120])
    return _cache or {"alpha_max": ALPHA_MAX_DEFAUT, "retenu": False}


def alpha_en_cache() -> float:
    """`alpha_max` pour l'inférence, SANS accès base.

    Le cache est rempli au démarrage de l'API et à chaque recalcul nocturne ; tant
    qu'il est vide, on rend la valeur en place — jamais un alpha deviné.
    """
    return float((_cache or {}).get("alpha_max") or ALPHA_MAX_DEFAUT)
