"""L'EXPOSANT DE NETTETÉ — la dernière correction de la probabilité servie.

Le défaut qu'il corrige
───────────────────────
`services.data_quality.calibration_par_bande` mesure, chaque heure, si une
probabilité de X % gagne bien X % du temps. Relevé du 2026-09-04, fenêtre 90 jours :

    bande      n servi   réel    écart
    0,00-0,40  46 497  0,0880  0,0893  -0,0013   <- excellent
    0,40-0,50     354  0,4427  0,3639  +0,0788   <- l'alerte
    0,50-0,60     138  0,5429  0,4855  +0,0574
    0,70+          29  0,7936  0,4138  +0,3798

Ce n'est pas une dérive isolée du haut de la distribution : c'est le MÊME défaut vu
des deux bouts. La masse de probabilité manquante en bas (−0,0013 sur 46 497
partants ≈ 60 victoires) est du même ordre que l'excédent du haut (≈ 45 victoires
sur ~520 partants). Rien ne se perd : la probabilité est simplement trop
CONCENTRÉE sur les premiers du classement. Une distribution trop pointue, pas une
courbe fausse.

Pourquoi la courbe isotone ne le règle pas
──────────────────────────────────────────
Elle le règle, et la renormalisation le défait. Mesuré dans la bande 0,70+ : la
courbe rend 0,6122, c'est 0,7973 qui est servi. Diviser par la somme du champ rend
au favori la confiance que la calibration venait de lui retirer — et il le faut
bien, puisqu'un seul cheval gagne et que les probabilités doivent sommer à 1.

L'audit du 2026-08-31 a mesuré cinq façons de renormaliser (deuxième passe, pas de
renormalisation, plafond au sommet de la courbe…) : aucune ne domine, parce
qu'elles se battent toutes sur les ~490 partants de la queue. Chercher là était
chercher au mauvais endroit.

Ce que fait ce module
─────────────────────
Une seule opération, sur le vecteur ENTIER de la course :

    p_servie ∝ p^exposant           (puis Σ = 1)

Sous 1, elle aplatit : le favori descend, le champ remonte. Au-dessus, l'inverse.
Trois propriétés en font le bon outil ici :

  1. Σ = 1 est vrai PAR CONSTRUCTION — la renormalisation ne peut plus défaire la
     correction, puisqu'elle en fait partie.
  2. L'ORDRE est strictement conservé (x ↦ x^a est croissante sur R+). Le
     classement affiché, le rang prédit, l'ordre des value bets : rien ne bouge.
     Seules bougent les valeurs — c'est-à-dire la cote juste et l'espérance, ce que
     l'alerte dit précisément faussées.
  3. C'est UN paramètre, ajusté sur toute la population (≈ 47 000 partants,
     ≈ 4 400 courses), pas sur les 96 observations d'une bande. C'est la différence
     entre mesurer une forme et sur-ajuster une queue.

Les garanties
─────────────
Défaut 1,0 = identité EXACTE : tant que la mesure ne conclut pas, rien n'est
appliqué, et la valeur en place ne bouge pas. Un exposant n'est retenu que s'il
tient HORS ÉCHANTILLON, sur des courses qui n'ont pas servi à le choisir :

  1. la log-vraisemblance du vrai gagnant s'améliore ;
  2. l'écart de calibration de la queue (p ≥ 0,40) — celui de l'alerte — ne se
     dégrade pas, quand il y a assez d'observations pour en juger.

BOUCLE FERMÉE, ÉVITÉE PAR CONSTRUCTION. L'ajustement se fait sur la proba SERVIE,
donc sur une grandeur qui porte déjà l'exposant en vigueur. Deux précautions :
l'ajustement ne lit que les prédictions POSTÉRIEURES à la mise en service de cet
exposant, et le nouvel exposant est le PRODUIT de l'ancien et du résiduel mesuré —
composition exacte, puisque (p^a)^b = p^(ab) et que la renormalisation commute avec
la puissance. La correction converge donc au lieu de chasser son propre résidu.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional, Sequence

import numpy as np
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(module="sharpness_calibration")

# Identité. C'est la valeur en place tant que rien n'est prouvé — et le repli de
# toutes les lectures.
EXPOSANT_NEUTRE = 1.0

# Bornes DURES de l'exposant composé. Au-delà, ce n'est plus une correction de
# netteté mais une réécriture de la sortie du modèle : on refuserait de la servir,
# autant ne jamais l'apprendre. 0,5 revient déjà à prendre la racine des probas.
EXPOSANT_MIN, EXPOSANT_MAX = 0.5, 1.5

# Grille de recherche du résiduel. Pas de 0,02 : plus fin que ce que la mesure sait
# distinguer sur ~4 000 courses, inutile d'aller au-delà.
GRILLE = tuple(round(x, 2) for x in np.arange(0.70, 1.31, 0.02))

# Nombre minimal de COURSES exploitables avant d'ajuster quoi que ce soit. Même
# ordre de grandeur que `blend_calibration` : sous ce volume, un exposant tiré de
# quelques réunions serait pire que l'identité.
MIN_COURSES = 400

# Gain minimal de log-vraisemblance PAR COURSE exigé hors échantillon. Strictement
# positif : à égalité, on ne touche à rien.
MIN_GAIN_LOGV = 1e-4

# Seuil de la « queue » : c'est la zone où l'alerte de calibration se déclenche.
BANDE_HAUTE = 0.40
# En dessous de ce nombre d'observations dans la queue de validation, l'écart de
# bande n'est pas jugeable (2,9 points d'écart-type binomial à 300 obs, bien plus à
# 50) : le garde-fou s'efface plutôt que de bloquer sur du bruit.
MIN_OBS_BANDE_HAUTE = 50

_cache: Optional[dict] = None


def appliquer(probas: np.ndarray, exposant: float) -> np.ndarray:
    """p ∝ p^exposant, renormalisé Σ = 1 sur la course. Fonction PURE.

    Exposant neutre (ou vecteur dégénéré) → vecteur inchangé, à l'identique. La
    fonction est appelée sur CHAQUE course servie : elle ne doit jamais lever, et
    jamais inventer une distribution là où il n'y en a pas.
    """
    p = np.asarray(probas, dtype=float)
    try:
        e = float(exposant)
    except (TypeError, ValueError):
        return p
    if not np.isfinite(e) or abs(e - EXPOSANT_NEUTRE) < 1e-9 or p.size == 0:
        return p
    # Vecteur sans masse : il n'y a pas de distribution à re-former. Le plancher
    # ci-dessous en fabriquerait une (uniforme) là où le pipeline n'en a produit
    # aucune — un chiffre inventé plutôt qu'un trou visible.
    if not np.isfinite(p).all() or float(np.nansum(p)) <= 0:
        return p
    e = float(np.clip(e, EXPOSANT_MIN, EXPOSANT_MAX))
    # Plancher strictement positif : 0^exposant vaut 0, et une course entièrement
    # nulle n'aurait plus de somme à renormaliser.
    base = np.clip(p, 1e-12, None)
    puissance = np.power(base, e)
    somme = float(puissance.sum())
    if not np.isfinite(somme) or somme <= 0:
        return p
    return puissance / somme


def _log_vraisemblance(courses: Sequence[tuple], exposant: float) -> float:
    """Log-vraisemblance moyenne du VRAI gagnant sous cet exposant.

    Règle de score PROPRE : elle récompense une probabilité juste, pas seulement un
    bon ordre — et l'ordre, ici, ne bouge de toute façon jamais.
    """
    total, n = 0.0, 0
    for p, gagnant in courses:
        q = appliquer(p, exposant)
        total += float(np.log(max(float(q[gagnant]), 1e-15)))
        n += 1
    return total / n if n else float("-inf")


def ecart_bande_haute(courses: Sequence[tuple], exposant: float) -> tuple[float, int]:
    """(écart de calibration, nb d'observations) sur la queue p ≥ BANDE_HAUTE.

    C'est LA grandeur que l'alerte remonte : moyenne des probabilités servies moins
    fréquence de victoire réelle, sur les partants annoncés au-dessus du seuil.
    Positif = sur-confiance. Renvoie (0.0, 0) si la queue est vide.
    """
    servi, reel, n = 0.0, 0.0, 0
    for p, gagnant in courses:
        q = appliquer(p, exposant)
        for j in range(len(q)):
            if q[j] >= BANDE_HAUTE:
                servi += float(q[j])
                reel += 1.0 if j == gagnant else 0.0
                n += 1
    if not n:
        return 0.0, 0
    return (servi - reel) / n, n


def ajuster_exposant(courses: Sequence[tuple], frac_ajustement: float = 0.8,
                     exposant_en_place: float = EXPOSANT_NEUTRE) -> dict:
    """Exposant qui maximise la vraisemblance du gagnant, VALIDÉ hors échantillon.

    `courses` = [(probas servies de la course, index du gagnant)], en ordre
    chronologique. Fonction PURE : elle ne lit ni base ni horloge.

    Le résultat porte `exposant` = valeur À SERVIR (composée avec celle en place,
    cf. l'en-tête du module) et `residuel` = ce que la mesure a trouvé sur la
    grandeur observée.
    """
    def _refus(**extra):
        return {"retenu": False, "exposant": exposant_en_place,
                "residuel": EXPOSANT_NEUTRE, **extra}

    coupe = int(len(courses) * frac_ajustement)
    ajustement, validation = list(courses[:coupe]), list(courses[coupe:])
    if not ajustement or not validation:
        return _refus(raison="pas de part de validation")

    base = _log_vraisemblance(ajustement, EXPOSANT_NEUTRE)
    if not np.isfinite(base):
        return _refus(raison="log-vraisemblance non calculable")

    meilleur, meilleure = EXPOSANT_NEUTRE, base
    for e in GRILLE:
        v = _log_vraisemblance(ajustement, e)
        if v > meilleure:
            meilleure, meilleur = v, float(e)
    if abs(meilleur - EXPOSANT_NEUTRE) < 1e-9:
        return _refus(raison="aucun exposant ne fait mieux sur la part d'ajustement",
                      logv_neutre=round(base, 6))

    logv_ref = _log_vraisemblance(validation, EXPOSANT_NEUTRE)
    logv_new = _log_vraisemblance(validation, meilleur)
    ecart_ref, n_bande = ecart_bande_haute(validation, EXPOSANT_NEUTRE)
    ecart_new, _ = ecart_bande_haute(validation, meilleur)
    gain_logv = logv_new - logv_ref

    compose = float(np.clip(exposant_en_place * meilleur, EXPOSANT_MIN, EXPOSANT_MAX))
    commun = {
        "residuel": meilleur,
        "exposant_en_place": exposant_en_place,
        "exposant_candidat": compose,
        "logv_validation_en_place": round(logv_ref, 6),
        "logv_validation_candidat": round(logv_new, 6),
        "gain_logv": round(gain_logv, 6),
        "ecart_bande_haute_en_place": round(ecart_ref, 4),
        "ecart_bande_haute_candidat": round(ecart_new, 4),
        "n_bande_haute": n_bande,
        "n_courses": len(courses),
    }
    if gain_logv <= MIN_GAIN_LOGV:
        return _refus(raison="pas de gain hors échantillon", **commun)
    # La queue est exactement ce dont l'alerte se plaint : on ne la dégrade pas pour
    # gagner ailleurs. Jugée seulement quand elle porte assez d'observations —
    # bloquer sur 12 partants serait remplacer une mesure par un tirage au sort.
    if n_bande >= MIN_OBS_BANDE_HAUTE and abs(ecart_new) > abs(ecart_ref):
        return _refus(raison="la calibration de la queue se dégraderait", **commun)
    return {"retenu": True, "exposant": compose, **commun}


async def _charger_courses(session: AsyncSession, depuis: Optional[str]) -> list[tuple]:
    """[(probas servies, index du gagnant)] par course, en ordre chronologique.

    Source : les prédictions FIGÉES avant le départ (`prediction_evaluation`, mêmes
    gardes anti-fuite que les isotones). La proba lue est `proba_top1`, c'est-à-dire
    CE QUI A ÉTÉ SERVI — l'exposant corrige la sortie de toute la chaîne, blend
    marché compris, pas la sortie du modèle.

    `depuis` borne la lecture aux prédictions produites APRÈS la mise en service de
    l'exposant courant : sans ça, l'ajustement mesurerait un mélange de régimes et
    composerait avec un exposant qui n'a pas produit ces lignes-là.
    """
    conditions = ""
    params: dict = {}
    if depuis:
        conditions = " AND pe.created_at >= :depuis"
        params["depuis"] = depuis
    rows = (await session.execute(text(f"""
        SELECT pe.course_id, pa.numero, pe.proba_top1, r.classement, c.date_heure
        FROM prediction_evaluation pe
        JOIN participations pa ON pa.participation_id = pe.participation_id
        JOIN courses c         ON c.course_id         = pe.course_id
        JOIN resultats r       ON r.course_id         = pe.course_id
        WHERE pe.is_replayable = true
          AND pe.proba_top1 IS NOT NULL
          AND pa.non_partant = false
          AND r.classement IS NOT NULL
          AND c.date_heure IS NOT NULL
          AND pe.created_at IS NOT NULL
          AND pe.created_at < c.date_heure{conditions}
        ORDER BY c.date_heure ASC, pe.course_id ASC
    """), params)).all()

    par_course: dict[str, list] = {}
    arrivees: dict[str, object] = {}
    for course_id, numero, proba, classement, _dh in rows:
        par_course.setdefault(course_id, []).append((int(numero), float(proba)))
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
            # `position == 1`, jamais l'index 0 : le classement n'est pas garanti trié.
            try:
                if int(e.get("position")) == 1:
                    gagnant_num = int(e.get("numero"))
                    break
            except (TypeError, ValueError, AttributeError):
                continue
        if gagnant_num is None or len(partants) < 4:
            continue
        index = {num: i for i, (num, _) in enumerate(partants)}
        if gagnant_num not in index:
            continue    # gagnant absent des prédictions : course écartée
        p = np.array([x for _, x in partants], dtype=float)
        somme = float(p.sum())
        if somme <= 0:
            continue
        # Renormalisée : la course sert de distribution, pas de collection de valeurs
        # (des partants peuvent manquer à l'appel des prédictions).
        out.append((p / somme, index[gagnant_num]))
    return out


async def calculer_et_persister(session: AsyncSession) -> dict:
    """Ajuste l'exposant sur les arrivées réelles et le stocke.

    Ne remplace JAMAIS la valeur en place quand la mesure ne conclut pas : même
    règle de démarrage à froid que toutes les autres calibrations du système.
    """
    global _cache
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS sharpness_calibration (
            id INTEGER PRIMARY KEY,
            data TEXT NOT NULL,
            updated_at TIMESTAMP
        )
    """))
    en_place = await charger_exposant(session)
    exposant = float(en_place.get("exposant") or EXPOSANT_NEUTRE)
    # Fenêtre de lecture : depuis la mise en service de l'exposant courant. Neutre
    # (jamais rien appliqué) → tout l'historique est exploitable.
    depuis = en_place.get("applique_depuis") if abs(exposant - EXPOSANT_NEUTRE) > 1e-9 else None

    courses = await _charger_courses(session, depuis)
    if len(courses) < MIN_COURSES:
        log.warning("sharpness.cold_start_preserve", n_courses=len(courses),
                    min_courses=MIN_COURSES, exposant=exposant, depuis=depuis)
        await _tracer_examen(session, {
            "status": "skipped_insufficient_data", "retenu": False,
            "exposant_en_place": exposant, "n_courses": len(courses),
            "raison": "échantillon trop court",
        })
        return {"status": "skipped_insufficient_data", "n_courses": len(courses),
                "exposant": exposant}

    verdict = ajuster_exposant(courses, exposant_en_place=exposant)
    if not verdict["retenu"]:
        log.info("sharpness.valeur_conservee", **verdict)
        # ON TRACE LE REFUS, PAS SEULEMENT L'ACCEPTATION. Sans cette ligne, la
        # table reste VIDE tant qu'aucun exposant ne tient — et rien, dans l'état
        # persistant, ne distingue « le correcteur a examiné et écarté » de « le
        # correcteur n'a jamais tourné ». C'est exactement ce qui s'est produit :
        # l'alerte `calibration_derive` répétait 145 fois une dérive pendant que le
        # job nocturne l'examinait chaque nuit et refusait, à raison, de corriger.
        # L'état persistant doit faire foi contre les journaux.
        await _tracer_examen(session, {"status": "valeur_conservee", **verdict})
        return {"status": "valeur_conservee", **verdict}

    donnees = dict(verdict)
    # Horodatage de MISE EN SERVICE : c'est lui qui borne le prochain ajustement.
    donnees["applique_depuis"] = datetime.now(timezone.utc).isoformat()
    await session.execute(text("""
        INSERT INTO sharpness_calibration (id, data, updated_at)
        VALUES (1, :data, CURRENT_TIMESTAMP)
        ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data,
                                       updated_at = EXCLUDED.updated_at
    """), {"data": json.dumps(donnees)})
    _cache = donnees
    await _tracer_examen(session, {"status": "ok", **verdict})
    log.info("sharpness.ajuste", **verdict)
    return {"status": "ok", **donnees}


# Ligne 1 = l'exposant EN SERVICE (écrite seulement quand un ajustement tient, pour
# que sa date de mise en service reste celle du dernier vrai changement).
# Ligne 2 = le dernier EXAMEN, écrit à chaque passage, retenu ou non. Les deux ne
# doivent pas partager la même ligne : l'un est une décision, l'autre une mesure.
_ID_EXAMEN = 2


async def _tracer_examen(session: AsyncSession, verdict: dict) -> None:
    """Enregistre le dernier examen de l'exposant. Ne touche jamais l'exposant servi."""
    donnees = dict(verdict)
    donnees["examine_le"] = datetime.now(timezone.utc).isoformat()
    try:
        await session.execute(text("""
            INSERT INTO sharpness_calibration (id, data, updated_at)
            VALUES (:id, :data, CURRENT_TIMESTAMP)
            ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data,
                                           updated_at = EXCLUDED.updated_at
        """), {"id": _ID_EXAMEN, "data": json.dumps(donnees)})
    except Exception as e:                                       # noqa: BLE001
        # Une trace de supervision ne doit jamais faire échouer la calibration.
        log.warning("sharpness.trace_examen_ignoree", err=str(e)[:140])


async def charger_dernier_examen(session: AsyncSession) -> dict | None:
    """Dernier examen de l'exposant (retenu ou écarté), ou None s'il n'a jamais tourné."""
    try:
        r = (await session.execute(text(
            "SELECT data FROM sharpness_calibration WHERE id = :id"),
            {"id": _ID_EXAMEN})).first()
    except Exception:                                            # noqa: BLE001
        try:
            await session.rollback()
        except Exception:
            pass
        return None
    if not r or not r[0]:
        return None
    return r[0] if isinstance(r[0], dict) else json.loads(r[0])


async def charger_exposant(session: AsyncSession) -> dict:
    """Exposant appris, ou l'identité. Met le cache mémoire à jour."""
    global _cache
    try:
        r = (await session.execute(text(
            "SELECT data FROM sharpness_calibration WHERE id = 1"))).first()
        if r and r[0]:
            data = r[0] if isinstance(r[0], dict) else json.loads(r[0])
            if data.get("exposant"):
                _cache = data
    except Exception as e:
        # DÉSEMPOISONNER : asyncpg marque la transaction AVORTÉE dès qu'une requête
        # échoue — ici typiquement « relation inexistante » avant le premier calcul
        # nocturne. Sans ce rollback, la requête SUIVANTE échoue non pour son propre
        # défaut mais parce que la transaction est déjà morte, et son diagnostic ment.
        try:
            await session.rollback()
        except Exception:
            pass
        log.debug("sharpness.chargement_ignore", err=str(e)[:120])
    return _cache or {"exposant": EXPOSANT_NEUTRE, "retenu": False}


def exposant_en_cache() -> float:
    """Exposant pour l'inférence, SANS accès base.

    Le cache est rempli au démarrage de l'API et à chaque recalcul nocturne ; tant
    qu'il est vide, on rend l'identité — jamais un exposant deviné.
    """
    try:
        e = float((_cache or {}).get("exposant") or EXPOSANT_NEUTRE)
    except (TypeError, ValueError):
        return EXPOSANT_NEUTRE
    return float(np.clip(e, EXPOSANT_MIN, EXPOSANT_MAX))
