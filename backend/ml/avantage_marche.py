"""Le produit servi bat-il la cote ?

`model_versions.rank_delta_market` répond à une question voisine mais DIFFÉRENTE :
il compare le classement du modèle NU à celui de la cote, sur le hold-out de la
nuit. C'est la bonne mesure pour juger l'entraînement — et c'est la mauvaise pour
juger le produit, parce que ce n'est pas le modèle nu qu'on sert.

Ce que reçoit l'abonné a traversé toute la chaîne : calibration isotonique,
température, exposants d'arrivée, MÉLANGE AVEC LE MARCHÉ (`ml/blend_calibration`,
alpha décroissant avec la cote), netteté. Le mélange, en particulier, change tout :
mesuré le 2026-09-07 sur 1 024 courses réelles, le modèle nu classe à 0,7326 quand
la cote seule classe à 0,7486 — il est DESSOUS de 0,0160 — pendant que le produit
servi classe à 0,7519, soit AU-DESSUS de 0,0033.

Les deux chiffres sont vrais, et ils disent des choses opposées. Ce n'est pas le
modèle nu qu'on sert : il n'a jamais eu pour mission de battre la cote tout seul.
Confondre les deux mène à une décision précise et fausse : câbler `BT_MARKET_GATE`
sur le delta du modèle nu — négatif sur chaque version depuis v528 — figerait le
modèle À VIE.

CORRECTION du 2026-09-24 : on a longtemps écrit ici que le nu était sous la cote
« par construction », le drapeau `market_residual` ayant retiré la cote de son
apprentissage. C'est faux en production : `BT_MARKET_RESIDUAL` n'y est défini dans
aucun conteneur, le modèle apprend AVEC la cote (34 % de l'importance de v544) et
reste pourtant sous elle. L'ablation hors temps du 24/09
(`scripts/ablation_cote_servi.py`) situe l'essentiel de ce déficit dans l'âge du
modèle servi, pas dans la cote. Le gate de promotion porte désormais sur le
produit SERVI (cf. `mesure_gate_servi` plus bas).

Ce module mesure donc la seule grandeur qui autorise un verdict produit, sur les
prédictions RÉELLEMENT SERVIES, et il la mesure comme on la lit : AUC de classement
intra-course, chaque course pesant le même poids.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import numpy as np
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

# Fenêtre par défaut. Assez longue pour un échantillon utile, assez courte pour
# décrire le produit d'AUJOURD'HUI et non la moyenne d'un trimestre : c'est une
# mesure de surveillance, pas une étude.
FENETRE_JOURS = 21

# Sous ce nombre de courses exploitables, aucun verdict n'est rendu. L'écart à
# mesurer se joue à quelques millièmes d'AUC ; sur deux cents courses il serait
# noyé. Une mesure insuffisante rend `mesure_disponible = False` et dit pourquoi —
# jamais un 0,5 neutre déguisé en résultat.
MIN_COURSES = 300

# Requête volontairement sans `is_replayable` : ce drapeau garantit qu'une
# prédiction est REJOUABLE à l'identique (features figées), garde utile pour
# l'entraînement mais qui n'a rien à voir avec « cette prédiction a-t-elle été
# servie ». La garde qui compte ici est temporelle — le conseil existait avant le
# départ — et la cote retenue est celle FIGÉE au moment du conseil, celle qui a
# réellement servi à mélanger, pas celle d'aujourd'hui.
_REQUETE = """
    WITH gagnant AS (
        SELECT r.course_id, (e->>'numero')::int AS numero
        FROM resultats r, jsonb_array_elements(r.classement) e
        WHERE (e->>'position')::int = 1
    )
    SELECT pe.course_id,
           pa.numero::int                          AS numero,
           pe.proba_top1                           AS servie,
           pe.proba_top1_raw                       AS brute,
           pe.cote_figee                           AS cote,
           g.numero                                AS gagnant
    FROM prediction_evaluation pe
    JOIN participations pa ON pa.participation_id = pe.participation_id
    JOIN courses c         ON c.course_id         = pe.course_id
    JOIN gagnant g         ON g.course_id         = pe.course_id
    WHERE pe.proba_top1 IS NOT NULL
      AND pe.cote_figee IS NOT NULL
      AND pe.cote_figee > 0
      AND c.date_heure IS NOT NULL
      AND pe.created_at IS NOT NULL
      AND pe.created_at < c.date_heure
      AND c.date_heure >= now() - make_interval(days => :jours)
"""


def _auc_par_course(lignes: list[tuple], indice_score: int) -> dict:
    """AUC de classement course par course pour une colonne de score donnée.

    Renvoie {course_id: auc}. Une course sans gagnant identifié parmi ses partants,
    ou à un seul partant exploitable, est ABSENTE — jamais remplacée par 0,5, qui
    diluerait l'écart mesuré vers zéro.
    """
    from ml.ranking_metrics import within_race_auc_par_course

    labels, scores, groupes = [], [], []
    for ligne in lignes:
        score = ligne[indice_score]
        if score is None:
            continue
        labels.append(1.0 if ligne[1] == ligne[5] else 0.0)
        scores.append(float(score))
        groupes.append(ligne[0])
    if not labels:
        return {}
    return within_race_auc_par_course(
        np.array(labels), np.array(scores), np.array(groupes))


def _moyenne(par_course: dict, communes: set) -> Optional[float]:
    valeurs = [v for k, v in par_course.items() if k in communes]
    return float(np.mean(valeurs)) if valeurs else None


def _ecart_apparie(a: dict, b: dict, communes: set) -> dict:
    """Écart moyen a − b mesuré COURSE PAR COURSE, avec son intervalle à 95 %.

    C'est la seule façon honnête de trancher ici. Comparer deux moyennes agrégées
    reviendrait à comparer deux nombres dont le bruit dominant — quel cheval a
    gagné ce jour-là — est pourtant COMMUN aux deux bras et devrait s'annuler.
    Sur les mêmes courses, la différence par course est bien plus stable : mesuré
    le 2026-09-07, l'écart-type des AUC par course est de ~0,30 (donc une erreur
    type de ~0,009 sur mille courses, qui noierait un écart de 0,003), quand
    l'erreur type de la DIFFÉRENCE appariée est d'un ordre de grandeur en dessous.

    `conclut` est vrai seulement si l'intervalle ne contient pas zéro. Un écart
    positif dont l'intervalle traverse zéro n'est pas un avantage, c'est du bruit
    — et il ne doit jamais être promu en verdict.
    """
    diffs = np.array([a[c] - b[c] for c in communes if c in a and c in b], dtype=float)
    n = len(diffs)
    if n < 2:
        return {"ecart": None, "ic95": None, "conclut": False, "n": n}
    moyenne = float(diffs.mean())
    # Erreur type de la moyenne des différences appariées. `ddof=1` : on estime
    # l'écart-type sur l'échantillon, pas sur une population connue.
    erreur_type = float(diffs.std(ddof=1) / np.sqrt(n))
    demi = 1.96 * erreur_type
    bas, haut = moyenne - demi, moyenne + demi
    return {
        "ecart": round(moyenne, 4),
        "erreur_type": round(erreur_type, 5),
        "ic95": [round(bas, 4), round(haut, 4)],
        "conclut": bool(bas > 0 or haut < 0),
        "n": n,
    }


async def mesurer_avantage_servi(session: AsyncSession,
                                 jours: int = FENETRE_JOURS) -> dict:
    """Avantage du produit SERVI sur la cote, mesuré sur les courses réelles.

    Trois classements sur EXACTEMENT les mêmes courses — c'est ce qui rend les
    écarts comparables :
      `servi`  la probabilité réellement affichée (toute la chaîne, mélange compris) ;
      `brut`   la sortie du modèle avant correction, pour situer ce qu'apporte la chaîne ;
      `marche` un simple tri par cote décroissante de probabilité implicite.

    L'appariement par course est la raison d'être de `communes` : comparer deux
    moyennes calculées sur des populations différentes ferait passer un écart de
    composition pour un écart de qualité.
    """
    try:
        lignes = (await session.execute(text(_REQUETE), {"jours": jours})).all()
    except Exception as e:
        await session.rollback()
        log.warning("avantage_marche.lecture_impossible", err=str(e)[:200])
        return {"mesure_disponible": False, "raison": "lecture impossible",
                "fenetre_jours": jours}

    # La cote sert de score en probabilité implicite : plus la cote est basse,
    # meilleur le classement. On ne normalise pas — un classement ne dépend que
    # de l'ordre, et une normalisation par course n'y changerait rien.
    lignes = [(c, n, s, b, (1.0 / co) if co else None, g)
              for (c, n, s, b, co, g) in lignes]

    auc_servi = _auc_par_course(lignes, 2)
    auc_brut = _auc_par_course(lignes, 3)
    auc_marche = _auc_par_course(lignes, 4)

    communes = set(auc_servi) & set(auc_marche)
    n_courses = len(communes)
    if n_courses < MIN_COURSES:
        return {
            "mesure_disponible": False,
            "raison": (f"{n_courses} courses exploitables sur la fenêtre, "
                       f"il en faut {MIN_COURSES} pour conclure"),
            "n_courses": n_courses, "fenetre_jours": jours,
            "min_courses": MIN_COURSES,
        }

    m_servi = _moyenne(auc_servi, communes)
    m_marche = _moyenne(auc_marche, communes)
    # Le brut n'est calculé que sur les courses où il existe : `proba_top1_raw`
    # n'est renseignée que sous le drapeau BT_CALIB_ON_RAW. Son absence ne doit
    # pas amputer la mesure principale, d'où l'ensemble commun séparé.
    communes_brut = communes & set(auc_brut)
    m_brut = _moyenne(auc_brut, communes_brut) if communes_brut else None
    m_marche_vs_brut = _moyenne(auc_marche, communes_brut) if communes_brut else None

    # Ce que la chaîne de correction APPORTE : servi moins brut, sur les MÊMES
    # courses que le brut. Calculé à part plutôt qu'en ligne — une expression
    # conditionnelle imbriquée cacherait laquelle des trois moyennes manque.
    m_servi_sur_brut = _moyenne(auc_servi, communes_brut) if communes_brut else None
    apport_chaine = (round(m_servi_sur_brut - m_brut, 4)
                     if m_brut is not None and m_servi_sur_brut is not None else None)

    # Le verdict porte sur l'écart APPARIÉ, jamais sur la différence des moyennes
    # agrégées : les deux valent numériquement la même chose, mais seule la
    # version appariée porte une incertitude qui a un sens.
    servi_vs_marche = _ecart_apparie(auc_servi, auc_marche, communes)
    brut_vs_marche = _ecart_apparie(auc_brut, auc_marche, communes_brut)
    apport = _ecart_apparie(auc_servi, auc_brut, communes_brut)

    resultat = {
        "mesure_disponible": True,
        "fenetre_jours": jours,
        "n_courses": n_courses,
        "min_courses": MIN_COURSES,
        "rang_servi": round(m_servi, 4),
        "rang_marche": round(m_marche, 4),
        "delta_servi_vs_marche": servi_vs_marche["ecart"],
        "ic95_servi_vs_marche": servi_vs_marche["ic95"],
        # `None` tant que l'intervalle contient zéro : un écart positif non
        # concluant n'est pas un avantage, et ne doit pas pouvoir se lire comme tel.
        "bat_le_marche": (None if not servi_vs_marche["conclut"]
                          else bool(servi_vs_marche["ecart"] > 0)),
        "conclut": servi_vs_marche["conclut"],
        "rang_brut": round(m_brut, 4) if m_brut is not None else None,
        "delta_brut_vs_marche": brut_vs_marche["ecart"],
        "ic95_brut_vs_marche": brut_vs_marche["ic95"],
        "n_courses_brut": len(communes_brut),
        # Ce que les corrections et le mélange ajoutent au modèle nu. C'est
        # l'écart qui justifie l'existence de la chaîne — et le seul des trois
        # qui soit resté nettement positif sur toutes les fenêtres testées.
        "apport_de_la_chaine": apport["ecart"],
        "ic95_apport_de_la_chaine": apport["ic95"],
        "apport_conclut": apport["conclut"],
        "mesure_le": datetime.now(timezone.utc).isoformat(),
        "porte_sur": "produit_servi",
    }
    log.info("avantage_marche.mesure",
             n_courses=n_courses, servi=resultat["rang_servi"],
             marche=resultat["rang_marche"],
             delta=resultat["delta_servi_vs_marche"],
             conclut=resultat["conclut"], apport=resultat["apport_de_la_chaine"])
    return resultat


# ──────────────────────────────────────────────────────────────────────────────
# GATE DE PROMOTION sur le produit SERVI (`BT_MARKET_GATE`, chantier C, 24/09)
# ──────────────────────────────────────────────────────────────────────────────
# L'ancien gate comparait `rank_delta_market` — le classement de l'ensemble NU —
# à la cote, et exigeait qu'il la batte. Rejoué sur l'historique, il aurait
# bloqué TOUTES les promotions depuis v528 (07/09) : le nu est sous la cote sur
# chaque hold-out (−0,017 à −0,035), et ce n'est pas lui qu'on sert. Actif, il
# aurait gelé le modèle sur v527.
#
# Le gate ci-dessous pose la seule question qui engage l'abonné : sur les mêmes
# courses du hold-out, jamais vues par les deux modèles, le classement que le
# CHALLENGER ferait servir recule-t-il, face à la cote, par rapport à celui que
# le CHAMPION sert aujourd'hui ? Il n'exige PAS de battre la cote — le produit est
# à parité et un gate « servi > cote » gèlerait aussi —, il interdit de reculer.
#
# « Servi » = ce que `predict_course` affiche : la proba de VICTOIRE du modèle,
# passée par le mélange appris sur les arrivées (`melange_arrivees`, β en
# service) ; à défaut de β, le mélange linéaire historique (`blend_calibration`).
# L'avantage de chacun sur la cote se mesure course par course ; comme la cote
# est la même des deux côtés, la différence des deux avantages est exactement
# l'écart apparié challenger − champion, dont on prend l'intervalle à 95 %.
#
# Bloque seulement si la régression est PROUVÉE (borne haute de l'IC < 0) ET
# matérielle (< −GATE_TOLERANCE), sur au moins GATE_MIN_COURSES courses : un gate
# qui bloquerait sur du bruit gèlerait le modèle, comme en juin-août. Même
# construction que le contrôle du modèle de victoire (`pipeline._victoire_bloque`).
GATE_TOLERANCE = 0.002
GATE_MIN_COURSES = 300


def _auc_gagnant(scores: np.ndarray, g: int) -> Optional[float]:
    """Part des perdants classés sous le gagnant (ex æquo = 0,5)."""
    autres = np.delete(scores, g)
    if autres.size == 0 or not np.isfinite(scores).all():
        return None
    return float(((scores[g] > autres).sum() + 0.5 * (scores[g] == autres).sum())
                 / autres.size)


def _par_course(groupes, y_win):
    """Itère (clé, indices, index du gagnant) sur les courses à gagnant unique."""
    g = np.asarray(groupes)
    y = np.asarray(y_win, dtype=float)
    ordre = np.argsort(g, kind="stable")
    bornes = np.flatnonzero(np.r_[True, g[ordre][1:] != g[ordre][:-1], True])
    for a, b in zip(bornes[:-1], bornes[1:]):
        idx = ordre[a:b]
        yy = y[idx]
        if len(idx) < 2 or yy.sum() != 1:
            continue
        yield g[idx[0]], idx, int(np.argmax(yy))


def proba_servie(p_win, cotes, betas: Optional[tuple] = None,
                 alpha_max: Optional[float] = None) -> Optional[np.ndarray]:
    """Proba de victoire SERVIE d'une course à partir de la proba brute. Pure.

    `melange_arrivees` quand β est en service (chaîne actuelle), sinon le mélange
    linéaire historique. None si la course n'a pas de cotes exploitables : sans
    cote il n'y a ni produit servi comparable ni référence marché.
    """
    p = np.asarray(p_win, dtype=float)
    if cotes is None or p.size < 2 or not np.isfinite(p).all() or p.sum() <= 0:
        return None
    c = np.asarray(cotes, dtype=float)
    if betas is not None:
        from ml import melange_arrivees as ma
        return ma.appliquer(p, c, betas[0], betas[1])
    from ml.blend_calibration import ALPHA_MAX_DEFAUT, melange
    if not np.isfinite(c).all() or (c <= 1.0).any():
        return None
    return np.asarray(melange(p / p.sum(), c, alpha_max=alpha_max or ALPHA_MAX_DEFAUT),
                      dtype=float)


def auc_servie_par_course(p_win, y_win, groupes, cotes, betas: Optional[tuple] = None,
                          alpha_max: Optional[float] = None) -> dict:
    """{course: AUC du gagnant} du classement SERVI issu de `p_win`. Pure.

    Une course sans gagnant unique ou sans cotes exploitables est ABSENTE, jamais
    comptée 0,5 (cf. `_auc_par_course`).
    """
    if cotes is None:
        return {}
    p_all = np.asarray(p_win, dtype=float)
    c_all = np.asarray(cotes, dtype=float)
    out: dict = {}
    for cle, idx, g in _par_course(groupes, y_win):
        servie = proba_servie(p_all[idx], c_all[idx], betas, alpha_max)
        if servie is None:
            continue
        auc = _auc_gagnant(np.asarray(servie, dtype=float), g)
        if auc is not None:
            out[cle] = auc
    return out


def auc_marche_par_course(y_win, groupes, cotes) -> dict:
    """{course: AUC du gagnant} d'un simple tri par cote croissante. Pure."""
    if cotes is None:
        return {}
    c_all = np.asarray(cotes, dtype=float)
    out: dict = {}
    for cle, idx, g in _par_course(groupes, y_win):
        c = c_all[idx]
        if not np.isfinite(c).all() or (c <= 1.0).any():
            continue
        auc = _auc_gagnant(1.0 / c, g)
        if auc is not None:
            out[cle] = auc
    return out


def mesure_gate_servi(auc_champion: dict, auc_challenger: dict, auc_marche: dict,
                      tolerance: float = GATE_TOLERANCE,
                      min_courses: int = GATE_MIN_COURSES) -> Optional[dict]:
    """Avantage SERVI sur la cote du champion et du challenger, sur les MÊMES
    courses, et la régression de l'un à l'autre. None si rien n'est mesurable.

    `bloque` est le verdict du gate ; `sous_la_cote` (challenger prouvé sous la
    cote) est une ALERTE, pas un blocage : le champion l'est peut-être aussi, et
    bloquer dessus reviendrait à exiger de battre la cote.
    """
    communes = set(auc_champion) & set(auc_challenger) & set(auc_marche)
    if len(communes) < 2:
        return None
    challenger = _ecart_apparie(auc_challenger, auc_marche, communes)
    champion = _ecart_apparie(auc_champion, auc_marche, communes)
    regression = _ecart_apparie(auc_challenger, auc_champion, communes)
    n = regression["n"]
    suffisant = n >= min_courses
    bloque = bool(suffisant and regression["ic95"] is not None
                  and regression["ic95"][1] < 0.0
                  and regression["ecart"] < -abs(tolerance))
    return {
        "n_courses": n,
        "suffisant": suffisant,
        "avantage_challenger": challenger["ecart"],
        "ic95_avantage_challenger": challenger["ic95"],
        "avantage_champion": champion["ecart"],
        "ic95_avantage_champion": champion["ic95"],
        "regression": regression["ecart"],
        "ic95_regression": regression["ic95"],
        "sous_la_cote": bool(suffisant and challenger["ic95"] is not None
                             and challenger["ic95"][1] < 0.0),
        "tolerance": abs(tolerance),
        "bloque": bloque,
    }


def gate_servi_bloque(mesure: Optional[dict]) -> bool:
    """Verdict du gate. Une mesure absente ou insuffisante ne bloque JAMAIS :
    bloquer sur une panne de cotes figerait le modèle."""
    return bool(mesure and mesure.get("bloque"))
