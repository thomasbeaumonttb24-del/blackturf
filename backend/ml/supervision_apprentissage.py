"""Ce que le système apprend, quand il l'a appris, et ce que ça a changé.

La supervision savait dire « le modèle a été promu » et « la température vaut
1,2567 ». Elle ne savait pas dire :

  - qu'un des dix-huit apprentissages nocturnes n'avait pas tourné depuis trois
    jours (ils vivent tous derrière le retrain, dans un seul job RQ : quand le
    worker se fait OOM-killer, ils sautent en silence — vécu le 20/08/2026, quatre-
    vingt-treize secondes après un déploiement annoncé réussi) ;
  - qu'un correcteur était en place SANS avoir prouvé qu'il améliorait quoi que ce
    soit ;
  - qu'une correction avait été apprise mais jamais servie.

RÈGLE DE CE MODULE : tout provient d'un état réellement persisté. Un outil qui n'a
pas assez de données rend ``mesure_disponible = false`` et dit pourquoi. Aucune
valeur neutre n'est jamais déguisée en mesure — c'est précisément la confusion qui
a fait vivre quatre mécanismes inertes pendant des mois.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(module="supervision_apprentissage")


def _age_heures(quand) -> Optional[float]:
    if quand is None:
        return None
    if isinstance(quand, str):
        try:
            quand = datetime.fromisoformat(quand)
        except ValueError:
            return None
    if quand.tzinfo is None:
        quand = quand.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - quand).total_seconds() / 3600, 1)


async def _etat_meta_learner() -> dict:
    """Le correcteur contextuel est-il en service, et l'a-t-il MÉRITÉ ?

    Il s'entraînait par COURSE (label « le vrai gagnant est-il dans mon top-3 ? »,
    entrée = la proba du gagnant, six features sur quinze constantes) et sa sortie
    corrigeait la proba de CHAQUE partant. Rien ne vérifiait que l'appliquer
    améliorait la probabilité servie : l'AUC publiée mesurait sa performance sur SA
    tâche à lui.
    """
    from ml.meta_learner import TRAINING_CONTRACT, get_meta_learner

    ml = get_meta_learner()
    m = dict(ml._metrics or {})
    return {
        "actif": bool(ml.is_trained),
        "contrat": getattr(ml, "_contract", None),
        "contrat_attendu": TRAINING_CONTRACT,
        "contrat_a_jour": getattr(ml, "_contract", None) == TRAINING_CONTRACT,
        "entraine_le": ml._trained_at.isoformat() if ml._trained_at else None,
        "n_exemples": ml._n_samples or None,
        "n_courses": m.get("n_courses"),
        "taux_de_base": m.get("pos_rate"),
        # Le verdict qui décide : mieux que NE RIEN corriger, ou pas.
        "logloss_avec_correction": m.get("logloss_meta"),
        "logloss_sans_correction": m.get("logloss_sans_correction"),
        "gain_logloss": m.get("gain_logloss"),
        "mesure_disponible": m.get("gain_logloss") is not None,
        "statut": m.get("status") or ("en_service" if ml.is_trained else "inactif"),
    }


async def _etat_harville(session: AsyncSession) -> dict:
    """Exposants de position du modèle d'arrivée — mesurés ou neutres."""
    from ml.harville_calibration import MIN_COURSES
    from ml.plackett_luce import EXPOSANTS_NEUTRES

    donnees, maj = None, None
    try:
        r = (await session.execute(text(
            "SELECT data, updated_at FROM harville_exposants WHERE id = 1"))).first()
        if r and r[0]:
            donnees = r[0] if isinstance(r[0], dict) else json.loads(r[0])
            maj = r[1]
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass
    if not donnees:
        return {"mesure_disponible": False, "exposants": list(EXPOSANTS_NEUTRES),
                "corrige": False, "min_courses": MIN_COURSES,
                "pourquoi": "aucun ajustement retenu à ce jour — le modèle "
                            "d'arrivée tourne sans correction (Plackett-Luce nu)"}
    return {
        "mesure_disponible": True,
        "exposants": donnees.get("exposants"),
        "corrige": bool(donnees.get("retenus")),
        "gain_log_vraisemblance": donnees.get("gain"),
        # Le gain sur les courses qui N'ONT PAS servi à choisir les exposants.
        # C'est lui qui décide : un gain qui ne survit pas hors échantillon est du
        # sur-ajustement, pas une correction.
        "gain_validation": donnees.get("gain_validation"),
        "n_courses": donnees.get("n_courses"),
        "min_courses": MIN_COURSES,
        "mis_a_jour_le": maj.isoformat() if hasattr(maj, "isoformat") else maj,
    }


async def _etat_temperature(session: AsyncSession) -> dict:
    """Température de calibration : ajustée sur mesure, ou laissée au cliquet ?"""
    from ml.adaptive_learning import T_MAX, T_MIN, TEMP_MIN_COURSES
    from ml.algo_flags import FLAGS

    temperature, maj = None, None
    try:
        r = (await session.execute(text(
            "SELECT temperature, updated_at FROM adaptive_learning_state "
            "ORDER BY updated_at DESC LIMIT 1"))).first()
        if r:
            temperature = float(r[0]) if r[0] is not None else None
            maj = r[1]
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass
    return {
        "temperature": temperature,
        "bornes": [T_MIN, T_MAX],
        "ajustee_sur_mesure": bool(FLAGS.temp_fit),
        "min_courses": TEMP_MIN_COURSES,
        "mis_a_jour_le": maj.isoformat() if hasattr(maj, "isoformat") else maj,
        "lecture": ("ajustée chaque nuit en minimisant la log-vraisemblance sur les "
                    "courses les plus récentes"
                    if FLAGS.temp_fit else
                    "cliquet par course — monte sur les surprises, ne redescend "
                    "que rarement : dérive attendue vers le haut"),
    }


async def _etat_alpha(session: AsyncSession) -> dict:
    """ALPHA — combien de confiance le modèle reçoit face au marché.

    Dernier arbitrage de la chaîne : il décide du classement affiché, des cotes
    justes, de l'EV, donc des paris émis. Il était posé à la main (0,42), justifié
    par un raisonnement et non par une mesure.
    """
    from ml.blend_calibration import ALPHA_MAX_DEFAUT, MIN_COURSES

    donnees, maj = None, None
    try:
        r = (await session.execute(text(
            "SELECT data, updated_at FROM blend_alpha WHERE id = 1"))).first()
        if r and r[0]:
            donnees = r[0] if isinstance(r[0], dict) else json.loads(r[0])
            maj = r[1]
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass
    if not donnees:
        return {"mesure_disponible": False, "alpha_max": ALPHA_MAX_DEFAUT,
                "appris": False, "min_courses": MIN_COURSES,
                "pourquoi": "alpha jamais ajusté sur les arrivées — la valeur "
                            "réglée à la main reste en place"}
    return {
        "mesure_disponible": True,
        "alpha_max": donnees.get("alpha_max"),
        "appris": bool(donnees.get("retenu")),
        "alpha_en_place": donnees.get("alpha_en_place"),
        "gain_logv": donnees.get("gain_logv"),
        "gain_rang": donnees.get("gain_rang"),
        "n_courses": donnees.get("n_courses"),
        "min_courses": MIN_COURSES,
        "raison": donnees.get("raison"),
        "mis_a_jour_le": maj.isoformat() if hasattr(maj, "isoformat") else maj,
    }


async def _etat_nettete(session: AsyncSession) -> dict:
    """NETTETÉ — la probabilité servie est-elle trop concentrée sur les premiers ?

    Dernière correction de la chaîne : p ∝ p^exposant, Σ=1. Elle ne change AUCUN
    classement (une puissance conserve l'ordre) ; elle change les valeurs, donc la
    cote juste et l'espérance. Neutre (1,0) tant que la mesure ne conclut pas.
    """
    from ml.sharpness_calibration import EXPOSANT_NEUTRE, MIN_COURSES

    donnees, maj = None, None
    try:
        r = (await session.execute(text(
            "SELECT data, updated_at FROM sharpness_calibration WHERE id = 1"))).first()
        if r and r[0]:
            donnees = r[0] if isinstance(r[0], dict) else json.loads(r[0])
            maj = r[1]
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass
    if not donnees:
        return {"mesure_disponible": False, "exposant": EXPOSANT_NEUTRE,
                "appris": False, "min_courses": MIN_COURSES,
                "pourquoi": "netteté jamais ajustée sur les arrivées — la "
                            "distribution du modèle est servie telle quelle"}
    return {
        "mesure_disponible": True,
        "exposant": donnees.get("exposant"),
        "appris": bool(donnees.get("retenu")),
        "residuel": donnees.get("residuel"),
        "gain_logv": donnees.get("gain_logv"),
        "ecart_bande_haute_en_place": donnees.get("ecart_bande_haute_en_place"),
        "ecart_bande_haute_candidat": donnees.get("ecart_bande_haute_candidat"),
        "n_bande_haute": donnees.get("n_bande_haute"),
        "n_courses": donnees.get("n_courses"),
        "min_courses": MIN_COURSES,
        "raison": donnees.get("raison"),
        "mis_a_jour_le": maj.isoformat() if hasattr(maj, "isoformat") else maj,
    }


async def _etat_plans(session: AsyncSession) -> dict:
    """Ce que l'apprentissage des PLANS a réellement sous la main.

    Le compteur qui compte : des COURSES conseillées, pas des ré-émissions. Le même
    plan est ré-émis à chaque mouvement de cote (~33 fois par course) ; compter les
    snapshots faisait croire à trente fois plus d'observations qu'il n'y en a.
    """
    try:
        r = (await session.execute(text("""
            SELECT COUNT(*) AS n_snapshots,
                   COUNT(DISTINCT s.course_id) AS n_courses,
                   -- MÊME clé de conseil que la déduplication de
                   -- `ml.bet_plan_performance.compute_forward_performance` :
                   -- (course × profil × montant × bankroll). Un compteur qui
                   -- s'écarterait de la clé réellement appliquée annoncerait un
                   -- nombre d'observations que l'apprentissage n'a pas.
                   -- COALESCE sur la bankroll : elle est NULLE sur les plans du
                   -- système, et une concaténation avec NULL rend NULL — la clé
                   -- entière disparaîtrait, et le compte tomberait à zéro.
                   COUNT(DISTINCT s.course_id || '|' || s.profil || '|'
                         || CAST(s.montant_demande AS VARCHAR) || '|'
                         || COALESCE(CAST(s.bankroll AS VARCHAR), '-')) AS n_conseils
            FROM bet_plan_snapshots s
            JOIN bet_plan_settlements t
              ON t.plan_snapshot_id = s.plan_snapshot_id AND t.statut = 'settled'
            WHERE s.is_pre_course = true
        """))).first()
    except Exception as e:
        try:
            await session.rollback()
        except Exception:
            pass
        log.warning("supervision.plans_indisponible", err=str(e)[:140])
        return {"mesure_disponible": False}
    n_snap = int(r[0] or 0) if r else 0
    n_courses = int(r[1] or 0) if r else 0
    n_conseils = int(r[2] or 0) if r else 0
    return {
        "mesure_disponible": n_conseils > 0,
        "n_snapshots_bruts": n_snap,
        "n_conseils_distincts": n_conseils,
        "n_courses": n_courses,
        "re_emissions_par_conseil": (round(n_snap / n_conseils, 1)
                                     if n_conseils else None),
        "lecture": ("un conseil = une observation. Les ré-émissions d'un même plan "
                    "à chaque mouvement de cote ne comptent qu'une fois — sinon "
                    "les seuils de fiabilité sont atteints avec une seule course"),
    }


async def _gates_actives(session: AsyncSession) -> dict:
    """Décisions automatiques en vigueur sur les types de pari."""
    try:
        rows = (await session.execute(text("""
            SELECT segment_key, status, factor, reason, roi_pct, n_paris, updated_at
            FROM bet_plan_segment_gates
            WHERE dimension = 'type_pari'
            ORDER BY status, segment_key
        """))).all()
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass
        return {"mesure_disponible": False, "gates": []}
    gates = [{"type": r[0], "statut": r[1], "facteur": float(r[2]),
              "raison": r[3], "roi_pct": (float(r[4]) if r[4] is not None else None),
              "n_paris": (int(r[5]) if r[5] is not None else None),
              "mis_a_jour_le": r[6].isoformat() if hasattr(r[6], "isoformat") else r[6]}
             for r in rows]
    return {
        "mesure_disponible": bool(gates),
        "gates": gates,
        "n_suspendus": sum(1 for g in gates if g["statut"] == "suspended"),
        "n_reduits": sum(1 for g in gates if g["statut"] == "reduced"),
        "lecture": ("un segment sous le seuil de fiabilité ne produit AUCUNE "
                    "décision : sa dernière décision connue reste appliquée, plutôt "
                    "que d'être effacée par un « actif » par défaut"),
    }


async def etat_outils_apprentissage(session: AsyncSession) -> dict:
    """Vue unique de tous les outils d'apprentissage, pour la supervision IA."""
    from ml.learning_steps import etat_apprentissages

    etapes = await etat_apprentissages(session)
    for e in etapes.get("etapes", []):
        e["age_heures"] = _age_heures(e.get("last_success_at"))

    outils = {
        "etapes": etapes.get("etapes", []),
        "etapes_perimees": [e["step"] for e in etapes.get("perimees", [])],
        "seuil_perime_heures": etapes.get("seuil_heures"),
        "correcteur_contextuel": await _etat_meta_learner(),
        "modele_arrivee": await _etat_harville(session),
        "alpha_marche": await _etat_alpha(session),
        "nettete_probas": await _etat_nettete(session),
        "temperature": await _etat_temperature(session),
        "plans": await _etat_plans(session),
        "gates_types": await _gates_actives(session),
    }
    outils["alerte"] = bool(outils["etapes_perimees"])
    return outils
