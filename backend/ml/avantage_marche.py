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

Les deux chiffres sont vrais, et ils disent des choses opposées. Le modèle est
entraîné sur le RÉSIDU du marché (drapeau `market_residual` : la cote a été retirée
de son vecteur d'apprentissage), il n'a donc jamais eu pour mission de battre la
cote tout seul. Confondre les deux mène à une décision précise et fausse : câbler
`BT_MARKET_GATE` sur le delta du modèle nu — structurellement négatif par
construction — figerait le modèle À VIE.

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
