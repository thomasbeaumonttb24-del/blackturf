"""LE MÉLANGE APPRIS SUR LES ARRIVÉES — d'où sortent la proba de victoire servie,
le classement affiché et la cote juste.

Le défaut qu'il corrige
───────────────────────
Mesuré le 2026-09-16 sur les prédictions FIGÉES avant le départ (dernier calcul à
T-10 min, cote du même instant), hors échantillon, 1 607 courses du 17/08 au 16/09 :

                                     log-vraisemblance     classement intra-course
                                     du gagnant (↓ mieux)  (AUC, ↑ mieux)
    proba servie (chaîne actuelle)        1,9853                0,7507
    cote seule (1/cote, marge retirée)    1,9586                0,7473
    CE MÉLANGE (2 paramètres)             1,9479                0,7508

    gain sur la proba servie  +0,0374 [+0,0089 ; +0,0659]   ← IC 95 %, par course
    gain sur la cote seule    +0,0107 [+0,0026 ; +0,0189]
    classement vs servi       +0,0001 [−0,0029 ; +0,0030]   ← parité

Sur toute la période rejouable (4 763 courses, juin → septembre) : +0,0369
[+0,0211 ; +0,0527] sur la proba servie. La chaîne actuelle — courbe isotone, puis
mélange LINÉAIRE `α·modèle + (1−α)·marché` avec un α posé à la main (0,42, décroissant
au-delà de la cote 12), puis netteté — CLASSE aussi bien que le marché mais
ANNONCE moins juste que lui : ses cotes justes sont moins fiables que la cote PMU
qu'elles prétendent corriger. Aucun des étages n'est faux pris seul ; c'est leur
forme qui l'est. Un mélange linéaire de probabilités ne sait ni rendre au marché sa
netteté, ni laisser le modèle déplacer un outsider proportionnellement à sa cote.

Ce que fait ce module
─────────────────────
Le second étage de Benter (1994), la forme reconnue pour combiner un modèle
fondamental et le marché : un LOGIT CONDITIONNEL par course.

    p_i ∝ exp( β_modèle · ln p̂_i  +  β_marché · ln q_i )          Σ p_i = 1

    p̂_i = proba de victoire BRUTE du modèle, normalisée sur la course
          (`proba_top1_raw`, avant toute correction)
    q_i  = proba implicite du marché, 1/cote normalisée (marge retirée)

Deux paramètres, appris chaque nuit sur les arrivées réelles, en maximisant la
vraisemblance du VRAI gagnant. Mesuré : β_modèle ≈ 0,29-0,37, β_marché ≈ 0,67-0,72,
stables d'une moitié de la période à l'autre. Leur somme ≈ 1,04 : le marché garde
sa netteté, le modèle déplace chaque cheval d'un FACTEUR (p̂_i^β) et non d'un écart
absolu — c'est ce qui manquait au mélange linéaire.

Ajouter d'autres entrées a été mesuré et n'apporte rien hors échantillon : la
proba placé brute (+0,0366 au lieu de +0,0374), des interactions par discipline
(+0,0364), un terme quadratique de cote (+0,0438 mais coefficients instables, de
signe opposé d'une moitié à l'autre). Deux paramètres, donc.

Les covariables du marché (2026-09-27)
──────────────────────────────────────
Le mélange à deux paramètres laissait trois défauts, mesurés hors échantillon sur
2 096 courses figées ≤ 2 h avant le départ (18/08 → 27/09) :
  - gros favoris (cote juste < 3) annoncés 46,2 %, réalisés 40,4 % (z −3,3) ;
  - « sous-cotés » (cote PMU 1,2 à 1,5 × la cote juste) annoncés 7,1 %, réalisés
    4,7 % : l'écart de prix affiché était du bruit ;
  - tranche de cote juste 6-10 sous-estimée (+8 %).

Trois termes, tous connus au moment du calcul, s'ajoutent au logit :

    z_i = β_modèle·ln p̂_i + β_marché·ln q_i
          + γ_mv·mouvement_30min_i        (cote qui s'allonge = argent qui part)
          + γ_geny·ln q_geny_i            (2e source de cote, repli = cote PMU)
          + γ_fav·[i = favori du marché]  (le public surjoue le favori)

    gain sur le mélange à deux paramètres +0,0183 [+0,0100 ; +0,0267]
    γ ≈ −0,27 / +0,24 / −0,33, mêmes signes et ordres de grandeur par moitié.
    Écarts de prix 1,2-1,5 : annoncés 14,1 %, réalisés 14,7 % (marché T-10 9,5 %).

Mesurés et ÉCARTÉS : traiter à part les écarts positifs et négatifs du modèle
(−0,0004), le mouvement depuis l'ouverture (+0,0001), la cote Betfair Exchange
(valeurs aberrantes). Les covariables ne sont servies que si elles battent, hors
échantillon et IC entièrement positif, le mélange à deux paramètres de la même
nuit, avec des γ de même signe sur les deux moitiés. Sinon : deux paramètres.

Ce qu'elles ne font PAS : battre la cote de CLÔTURE. Le PMU paie la clôture, qui
rachète l'essentiel de l'écart vu avant le départ (rendement des écarts 1,2-1,5
au rapport de clôture ≈ 0). La cote juste dit vrai sur la chance ; elle ne promet
pas un gain.

Le classement affiché suit cette probabilité (cf. `ml.pipeline.predict_course`) :
le rang 1 est le cheval dont la cote juste est la plus basse, sans exception.

Les garanties
─────────────
1. Rien ne change tant que la mesure ne conclut pas : pas de paramètres retenus →
   la chaîne d'avant est servie à l'identique.
2. Un jeu de paramètres n'est retenu que s'il tient HORS ÉCHANTILLON, en validation
   croisée chronologique (deux moitiés, chacune jugée avec les paramètres appris
   sur l'autre) :
     a. il bat la cote seule, intervalle de confiance entièrement positif ;
     b. il ne fait pas moins bien que ce qui est servi (tolérance `TOL_LOGV`) ;
     c. il ne dégrade pas le classement de ce qui est servi (tolérance `TOL_AUC`).
3. PAS DE BOUCLE FERMÉE. Les deux entrées — la proba brute du modèle et la cote —
   ne dépendent pas de ce module. Une fois en service, la comparaison (b) oppose
   le candidat de la nuit aux paramètres de la veille, et (a) garde la référence
   fixe qu'est le marché : la mesure ne peut pas chasser son propre résidu.
4. Course sans cote pour TOUS ses partants → étage non appliqué, chaîne d'avant.
   Une donnée manquante ne se remplace pas par une valeur devinée.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

import numpy as np
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ml.learning_steps import _vers_datetime
from ml.prediction_evaluation import sans_modeles_retires

log = structlog.get_logger(module="melange_arrivees")

# Fenêtre d'apprentissage. 90 jours ≈ 4 500 courses : de quoi mesurer un écart de
# 0,01 de log-vraisemblance (écart-type par course ≈ 0,58), sans remonter au régime
# d'avant le 17/08 où la dernière prédiction datait de la veille au soir.
FENETRE_JOURS = 90

# Seules les prédictions calculées PRÈS DU DÉPART décrivent ce qui est servi au
# moment où l'on joue : le calcul de T-10 min, avec la cote de T-10 min. Un calcul
# de la veille, cote du matin, apprend un autre mélange (le marché du matin informe
# moins) — mesuré : β_marché 0,81 sur la période où les prédictions étaient figées
# la veille, 0,67-0,72 depuis qu'elles le sont à T-10.
FRAICHEUR_MAX_MIN = 120

# En deçà, l'intervalle du critère (a) est trop large pour conclure quoi que ce soit.
MIN_COURSES = 600
MIN_PARTANTS = 4

# Plancher des probabilités avant le logarithme. Une proba brute de 1e-6 (clip du
# modèle) vaudrait −13,8 : un seul cheval écraserait l'ajustement. 1e-5 ≈ cote 100 000.
PLANCHER = 1e-5

# Bornes DURES des coefficients. Négatif = le modèle ou le marché classerait à
# l'envers ; au-delà de 2 = une distribution plus pointue que les deux sources
# réunies. Hors de ces bornes on refuse de servir, donc on refuse d'apprendre.
BETA_MIN, BETA_MAX = 0.0, 2.0

# Tolérances des critères (b) et (c). Petites mais non nulles : une fois l'étage en
# service, le candidat de la nuit n'est comparé qu'à celui de la veille, et deux
# ajustements sur des fenêtres décalées d'un jour diffèrent de quelques 1e-4.
TOL_LOGV = 0.002
TOL_AUC = 0.003

# ── Covariables du marché (cf. docstring, 2026-09-27) ────────────────────────
# Ordre des colonnes ajoutées à [ln p̂, ln q] ; les γ appris suivent cet ordre.
COVARIABLES = ("mouvement_30min", "ln_q_geny", "favori_marche")
# Le mouvement sur 30 min est une variation relative de cote : au-delà de ±100 %
# ce n'est plus un signal mais une cote mal lue (même borne qu'à la mesure).
MOUVEMENT_BORNE = 1.0
# Borne DURE des γ : hors de ±3, un terme seul renverserait le classement du
# marché. Hors bornes on refuse de servir, donc on refuse d'apprendre.
GAMMA_MAX = 3.0

_cache: Optional[dict] = None


# ──────────────────────────────────────────────────────────────────────────────
# La transformation
# ──────────────────────────────────────────────────────────────────────────────

def probas_marche(cotes: Sequence[float]) -> Optional[np.ndarray]:
    """1/cote normalisée sur la course, ou None si UN partant n'a pas de cote."""
    c = np.asarray(cotes, dtype=float)
    if c.size == 0 or not np.isfinite(c).all() or (c <= 1.0).any():
        return None
    q = 1.0 / c
    return q / q.sum()


def _en_nombres(valeurs, n: int) -> np.ndarray:
    """Tableau de n flottants, NaN pour ce qui manque ou ne se lit pas."""
    out = np.full(n, np.nan)
    if valeurs is None:
        return out
    try:
        valeurs = list(valeurs)
    except TypeError:
        return out
    if len(valeurs) != n:
        return out
    for i, v in enumerate(valeurs):
        try:
            out[i] = float(v)
        except (TypeError, ValueError):
            pass
    return out


def matrice_covariables(cotes: Sequence[float], mouvements=None,
                        cotes_geny=None) -> Optional[np.ndarray]:
    """Matrice n×3 des covariables du marché (ordre `COVARIABLES`). Fonction PURE.

    None si la cote PMU manque pour un partant (l'étage entier ne s'applique pas).
    Une covariable absente pour un cheval prend sa valeur NEUTRE, exactement comme
    dans les features apprises : mouvement 0, cote Geny = cote PMU.
    """
    q = probas_marche(cotes)
    if q is None:
        return None
    n = q.size
    mv = np.clip(np.nan_to_num(_en_nombres(mouvements, n), nan=0.0),
                 -MOUVEMENT_BORNE, MOUVEMENT_BORNE)
    c = np.asarray(cotes, dtype=float)
    g = _en_nombres(cotes_geny, n)
    g = np.where(np.isfinite(g) & (g > 1.0), g, c)
    qg = (1.0 / g) / float((1.0 / g).sum())
    fav = np.zeros(n)
    fav[int(np.argmax(q))] = 1.0          # ex æquo : le premier dans l'ordre reçu
    return np.column_stack([mv, np.log(np.clip(qg, PLANCHER, None)), fav])


def covariables_de_features(features: Sequence[dict],
                            cotes: Sequence[float]) -> Optional[np.ndarray]:
    """`matrice_covariables` à partir des vecteurs de features servis."""
    return matrice_covariables(
        cotes,
        [f.get("mouvement_30min") for f in features],
        [f.get("cote_geny") for f in features],
    )


def appliquer(p_modele: Sequence[float], cotes: Sequence[float],
              beta_modele: float, beta_marche: float,
              covariables: Optional[np.ndarray] = None,
              gammas: Optional[Sequence[float]] = None) -> Optional[np.ndarray]:
    """p ∝ p̂^β_modèle · q^β_marché · exp(Σ γ_k·x_k), Σ = 1. Fonction PURE.

    Sans `gammas` : le mélange à deux paramètres, à l'identique. Avec `gammas`, les
    `covariables` (n × len(gammas)) sont exigées : s'il en manque, None — l'appelant
    retombe sur deux paramètres plutôt que de servir un logit tronqué.

    Renvoie None quand l'étage ne s'applique pas (cote manquante, proba modèle sans
    masse, coefficients hors bornes) : l'appelant garde alors sa chaîne. Elle ne lève
    jamais — elle est appelée sur chaque course servie.
    """
    try:
        bm, bk = float(beta_modele), float(beta_marche)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(bm) and math.isfinite(bk)):
        return None
    if not (BETA_MIN <= bm <= BETA_MAX and BETA_MIN <= bk <= BETA_MAX) or bm + bk <= 0:
        return None
    p = np.asarray(p_modele, dtype=float)
    q = probas_marche(cotes)
    if q is None or p.size != q.size or p.size < 2:
        return None
    if not np.isfinite(p).all() or float(p.sum()) <= 0:
        return None
    p = np.clip(p / p.sum(), PLANCHER, None)
    z = bm * np.log(p) + bk * np.log(np.clip(q, PLANCHER, None))
    if gammas is not None:
        try:
            gm = np.asarray(gammas, dtype=float).reshape(-1)
            x = np.asarray(covariables, dtype=float)
        except (TypeError, ValueError):
            return None
        if (x.ndim != 2 or x.shape != (p.size, gm.size) or not np.isfinite(x).all()
                or not np.isfinite(gm).all() or (np.abs(gm) > GAMMA_MAX).any()):
            return None
        z = z + x @ gm
    z = z - z.max()
    e = np.exp(z)
    return e / e.sum()


def en_service() -> Optional[tuple[float, float]]:
    """(β_modèle, β_marché) du mélange À DEUX PARAMÈTRES retenu, ou None.

    C'est la référence des mesures (contrôle de promotion, avantage servi, bancs) et
    le repli de `predict_course` quand les covariables ne se calculent pas.
    """
    d = _cache or {}
    if not d.get("retenu"):
        return None
    try:
        return float(d["beta_modele"]), float(d["beta_marche"])
    except (KeyError, TypeError, ValueError):
        return None


def en_service_etendu() -> Optional[tuple[float, float, tuple[float, ...]]]:
    """(β_modèle, β_marché, γ) du mélange AVEC covariables retenu, ou None."""
    d = _cache or {}
    e = d.get("etendu") or {}
    if not d.get("retenu") or not e.get("retenu"):
        return None
    try:
        gammas = tuple(float(v) for v in e["gammas"])
        if len(gammas) != len(COVARIABLES) or list(e.get("noms") or []) != list(COVARIABLES):
            return None
        return float(e["beta_modele"]), float(e["beta_marche"]), gammas
    except (KeyError, TypeError, ValueError):
        return None


# ──────────────────────────────────────────────────────────────────────────────
# L'ajustement (fonctions pures)
# ──────────────────────────────────────────────────────────────────────────────
# Une course = dict(x=matrice n×(2+k) [ln p̂, ln q, covariables…], g=index du
# gagnant, servi=proba servie normalisée). Ordre chronologique. Les deux premières
# colonnes suffisent au mélange à deux paramètres (`k=2`).

def _vers_course(p_brut, cotes, gagnant: int, p_servi,
                 covariables: Optional[np.ndarray] = None) -> Optional[dict]:
    p = np.asarray(p_brut, dtype=float)
    q = probas_marche(cotes)
    s = np.asarray(p_servi, dtype=float)
    if q is None or p.size != q.size or p.size < MIN_PARTANTS or not (0 <= gagnant < p.size):
        return None
    if not np.isfinite(p).all() or p.sum() <= 0 or not np.isfinite(s).all() or s.sum() <= 0:
        return None
    x = np.column_stack([np.log(np.clip(p / p.sum(), PLANCHER, None)),
                         np.log(np.clip(q, PLANCHER, None))])
    if covariables is not None:
        cv = np.asarray(covariables, dtype=float)
        if cv.ndim != 2 or cv.shape[0] != p.size or not np.isfinite(cv).all():
            return None
        x = np.column_stack([x, cv])
    return {"x": x, "g": int(gagnant), "servi": s / s.sum(), "q": q}


def _log_proba(beta: np.ndarray, x: np.ndarray) -> np.ndarray:
    z = x[:, :beta.size] @ beta
    z = z - z.max()
    return z - math.log(float(np.exp(z).sum()))


def _borner(beta: np.ndarray) -> np.ndarray:
    b = beta.copy()
    b[:2] = np.clip(b[:2], BETA_MIN, BETA_MAX)
    b[2:] = np.clip(b[2:], -GAMMA_MAX, GAMMA_MAX)
    return b


def ajuster_beta(courses: Sequence[dict], iterations: int = 50, k: int = 2) -> np.ndarray:
    """Maximum de vraisemblance du logit conditionnel, par Newton-Raphson.

    `k` = nombre de colonnes de `x` utilisées : 2 pour le mélange modèle × marché,
    2 + len(COVARIABLES) avec les covariables. La vraisemblance est concave en β :
    Newton converge en quelques pas depuis n'importe quel point raisonnable. Une
    petite régularisation vers « le marché seul » (0, 1, 0…) tient lieu de
    garde-fou quand l'échantillon est dégénéré.
    """
    beta = np.array([0.3, 0.7] + [0.0] * (k - 2))
    prior = np.array([0.0, 1.0] + [0.0] * (k - 2))
    ridge = 1e-3
    for _ in range(iterations):
        grad = -ridge * (beta - prior)
        hess = -ridge * np.eye(k)
        for c in courses:
            x = c["x"][:, :k]
            p = np.exp(_log_proba(beta, x))
            moy = p @ x
            grad += x[c["g"]] - moy
            hess -= (x * p[:, None]).T @ x - np.outer(moy, moy)
        try:
            pas = np.linalg.solve(hess, grad)
        except np.linalg.LinAlgError:
            break
        beta = beta - pas
        if float(np.abs(pas).max()) < 1e-7:
            break
    return _borner(beta)


def _auc_course(scores: np.ndarray, g: int) -> float:
    """Part des perdants classés sous le gagnant (ex æquo = ½)."""
    autres = np.delete(scores, g)
    if autres.size == 0:
        return float("nan")
    sg = scores[g]
    return float(((autres < sg).sum() + 0.5 * (autres == sg).sum()) / autres.size)


def _moy_ic(valeurs: Sequence[float]) -> tuple[float, float, float]:
    v = np.asarray(valeurs, dtype=float)
    m = float(v.mean())
    if v.size < 2:
        return m, float("-inf"), float("inf")
    se = float(v.std(ddof=1) / math.sqrt(v.size))
    return m, m - 1.96 * se, m + 1.96 * se


def _validation_croisee(courses: list[dict], k: int) -> dict:
    """Validation croisée chronologique en deux moitiés, `k` colonnes.

    Par course, dans l'ordre d'entrée : −ln p(gagnant) et AUC intra-course, chaque
    course notée avec des coefficients appris sur l'AUTRE moitié.
    """
    n = len(courses)
    moitie = n // 2
    ll = np.empty(n)
    auc = np.empty(n)
    plis = []
    for app, val in ((range(0, moitie), range(moitie, n)), (range(moitie, n), range(0, moitie))):
        b = ajuster_beta([courses[i] for i in app], k=k)
        plis.append([round(float(v), 4) for v in b])
        for i in val:
            c = courses[i]
            lp = _log_proba(b, c["x"][:, :k])
            ll[i] = -float(lp[c["g"]])
            auc[i] = _auc_course(lp, c["g"])
    return {"ll": ll, "auc": auc, "plis": plis}


def _ic(valeurs) -> tuple[float, list[float]]:
    m, bas, haut = _moy_ic(valeurs)
    return round(m, 5), [round(bas, 5), round(haut, 5)]


def _examiner_etendu(courses: list[dict], base: dict, ll_marche: np.ndarray,
                     ll_servi: np.ndarray, auc_servi: np.ndarray) -> dict:
    """Le mélange AVEC covariables face au mélange à deux paramètres de la même nuit.

    Retenu seulement s'il bat ce mélange hors échantillon (IC entièrement positif),
    avec des γ de même signe sur les deux moitiés, sans annoncer ni classer moins
    bien que ce qui est servi.
    """
    k = 2 + len(COVARIABLES)
    cv = _validation_croisee(courses, k)
    gain_base, gain_base_ic = _ic(base["ll"] - cv["ll"])
    gm, gm_ic = _ic(ll_marche - cv["ll"])
    gs, _gs_ic = _ic(ll_servi - cv["ll"])
    da, da_ic = _ic(cv["auc"] - auc_servi)
    final = ajuster_beta(courses, k=k)
    g1, g2 = np.asarray(cv["plis"][0][2:]), np.asarray(cv["plis"][1][2:])
    stables = bool(np.all(np.sign(g1) == np.sign(g2)) and np.all(g1 != 0))
    verdict = {
        "noms": list(COVARIABLES),
        "beta_modele": round(float(final[0]), 4),
        "beta_marche": round(float(final[1]), 4),
        "gammas": [round(float(v), 4) for v in final[2:]],
        "coefs_par_moitie": cv["plis"],
        "gain_logv_vs_deux_parametres": gain_base,
        "gain_logv_vs_deux_parametres_ic95": gain_base_ic,
        "gain_logv_vs_marche": gm,
        "gain_logv_vs_marche_ic95": gm_ic,
        "gain_logv_vs_servi": gs,
        "delta_auc_vs_servi": da,
        "delta_auc_vs_servi_ic95": da_ic,
        "auc_melange": round(float(np.mean(cv["auc"])), 4),
    }
    if not gain_base_ic[0] > 0:
        return {"retenu": False, "raison": "ne bat pas le mélange à deux paramètres", **verdict}
    if not stables:
        return {"retenu": False, "raison": "coefficients instables d'une moitié à l'autre",
                **verdict}
    if gs < -TOL_LOGV:
        return {"retenu": False, "raison": "annonce moins juste que ce qui est servi", **verdict}
    if da < -TOL_AUC:
        return {"retenu": False, "raison": "classerait moins bien que ce qui est servi",
                **verdict}
    return {"retenu": True, **verdict}


def evaluer(courses: Sequence[dict]) -> dict:
    """Validation croisée chronologique en deux moitiés + ajustement final.

    Fonction PURE. Chaque course est jugée avec des coefficients appris sur l'AUTRE
    moitié : aucune n'a servi à choisir les paramètres qui la notent.

    Quand les courses portent les covariables (x à plus de deux colonnes), le
    mélange étendu est examiné aussi (clé `etendu`). Les critères « pas moins juste,
    pas moins bien classé que ce qui est servi » s'appliquent à ce qui SERA servi :
    le mélange étendu s'il est retenu, sinon celui à deux paramètres. Sans cette
    règle, une fois les covariables en service, le mélange à deux paramètres
    échouerait chaque nuit face à elles et plus rien ne se réapprendrait.
    """
    courses = list(courses)
    n = len(courses)
    if n < 2:
        return {"retenu": False, "raison": "échantillon vide", "n_courses": n}
    base = _validation_croisee(courses, 2)
    ll_marche = np.array([-math.log(max(float(c["q"][c["g"]]), 1e-15)) for c in courses])
    ll_servi = np.array([-math.log(max(float(c["servi"][c["g"]]), 1e-15)) for c in courses])
    auc_servi = np.array([_auc_course(c["servi"], c["g"]) for c in courses])
    auc_marche = np.array([_auc_course(c["q"], c["g"]) for c in courses])

    gm, gm_bas, gm_haut = _moy_ic(ll_marche - base["ll"])
    gs, gs_bas, gs_haut = _moy_ic(ll_servi - base["ll"])
    da, da_bas, da_haut = _moy_ic(base["auc"] - auc_servi)
    final = ajuster_beta(courses)
    verdict = {
        "beta_modele": round(float(final[0]), 4),
        "beta_marche": round(float(final[1]), 4),
        "betas_par_moitie": base["plis"],
        "n_courses": n,
        "gain_logv_vs_marche": round(gm, 5),
        "gain_logv_vs_marche_ic95": [round(gm_bas, 5), round(gm_haut, 5)],
        "gain_logv_vs_servi": round(gs, 5),
        "gain_logv_vs_servi_ic95": [round(gs_bas, 5), round(gs_haut, 5)],
        "delta_auc_vs_servi": round(da, 5),
        "delta_auc_vs_servi_ic95": [round(da_bas, 5), round(da_haut, 5)],
        "auc_melange": round(float(np.mean(base["auc"])), 4),
        "auc_servi": round(float(np.mean(auc_servi)), 4),
        "auc_marche": round(float(np.mean(auc_marche)), 4),
    }
    if n < MIN_COURSES:
        return {"retenu": False, "raison": "échantillon trop court", **verdict}
    if not gm_bas > 0:
        return {"retenu": False, "raison": "ne bat pas la cote seule hors échantillon",
                **verdict}
    etendu = None
    if all(c["x"].shape[1] >= 2 + len(COVARIABLES) for c in courses):
        etendu = _examiner_etendu(courses, base, ll_marche, ll_servi, auc_servi)
        verdict["etendu"] = etendu
    if etendu is not None and etendu.get("retenu"):
        return {"retenu": True, **verdict}
    if gs < -TOL_LOGV:
        return {"retenu": False, "raison": "annonce moins juste que ce qui est servi",
                **verdict}
    if da < -TOL_AUC:
        return {"retenu": False, "raison": "classerait moins bien que ce qui est servi",
                **verdict}
    return {"retenu": True, **verdict}


# ──────────────────────────────────────────────────────────────────────────────
# Base
# ──────────────────────────────────────────────────────────────────────────────

async def _charger_courses(session: AsyncSession) -> list[dict]:
    """Courses rejouables, en ordre chronologique.

    Source : `prediction_evaluation` (dernier instantané PRÉ-DÉPART de chaque
    partant, mêmes gardes anti-fuite que les isotones et la netteté). Une course
    n'est gardée que COMPLÈTE : tous ses partants prédits près du départ, tous cotés,
    gagnant identifié. Une course à moitié présente fausserait la normalisation.
    """
    depuis = datetime.now(timezone.utc) - timedelta(days=FENETRE_JOURS)
    # Les covariables se lisent dans le vecteur de features FIGÉ avec la prédiction
    # (jamais dans `features_ml`, que les recalculs réécrivent après la course).
    mv, geny = _extraits_features(session)
    rows = (await session.execute(text(f"""
        SELECT pe.course_id, pa.numero, pe.proba_top1_raw, pe.cote_figee,
               pe.proba_top1, r.classement, c.date_heure, pe.created_at, np.n,
               pe.features IS NOT NULL AS a_features, {mv} AS mv30, {geny} AS geny
        FROM prediction_evaluation pe
        JOIN participations pa ON pa.participation_id = pe.participation_id
        JOIN courses c         ON c.course_id         = pe.course_id
        JOIN resultats r       ON r.course_id         = pe.course_id
        JOIN (SELECT course_id, count(*) AS n FROM participations
               WHERE COALESCE(non_partant, false) = false
               GROUP BY course_id) np ON np.course_id = pe.course_id
        WHERE pe.is_replayable = true{sans_modeles_retires('pe')}
          AND pe.proba_top1_raw IS NOT NULL
          AND pe.proba_top1 IS NOT NULL
          AND COALESCE(pa.non_partant, false) = false
          AND r.classement IS NOT NULL
          AND c.date_heure IS NOT NULL
          AND pe.created_at IS NOT NULL
          AND pe.created_at < c.date_heure
          AND c.date_heure >= :depuis
        ORDER BY c.date_heure ASC, pe.course_id ASC, pa.numero ASC
    """), {"depuis": depuis})).all()

    # La fraîcheur se juge en Python : l'arithmétique d'intervalles n'a pas la même
    # syntaxe en PostgreSQL et en SQLite, et les deux drivers ne rendent pas le même
    # type d'horodatage (cf. `learning_steps._vers_datetime`).
    fraicheur = timedelta(minutes=FRAICHEUR_MAX_MIN)
    par_course: dict[str, dict] = {}
    for (course_id, numero, brut, cote, servi, classement, dh, cree, n_partants,
         a_features, mv30, cote_geny) in rows:
        d = par_course.setdefault(course_id, {"lignes": [], "classement": classement,
                                              "n_partants": int(n_partants or 0)})
        depart, calcul = _vers_datetime(dh), _vers_datetime(cree)
        if depart is None or calcul is None or depart - calcul > fraicheur:
            d["perimee"] = True
            continue
        if not a_features:
            d["sans_features"] = True
        d["lignes"].append((int(numero), float(brut),
                            float(cote) if cote is not None else float("nan"),
                            float(servi), mv30, cote_geny))

    out: list[dict] = []
    for d in par_course.values():
        lignes = d["lignes"]
        if d.get("perimee") or len(lignes) < MIN_PARTANTS or len(lignes) != d["n_partants"]:
            continue
        classement = d["classement"]
        if isinstance(classement, str):
            try:
                classement = json.loads(classement)
            except (ValueError, TypeError):
                continue
        gagnant = None
        for e in classement or []:
            # `position == 1`, jamais l'index 0 : le classement n'est pas garanti trié.
            try:
                if int(e.get("position")) == 1:
                    gagnant = int(e.get("numero"))
                    break
            except (TypeError, ValueError, AttributeError):
                continue
        numeros = [ligne[0] for ligne in lignes]
        if gagnant is None or gagnant not in numeros:
            continue
        # Sans vecteur figé, les covariables ne sont pas celles qui ont été servies :
        # la course sort de l'échantillon (legacy d'avant les instantanés, 17/08).
        if d.get("sans_features"):
            continue
        cotes = [ligne[2] for ligne in lignes]
        cov = matrice_covariables(cotes, [ligne[4] for ligne in lignes],
                                  [ligne[5] for ligne in lignes])
        if cov is None:
            continue
        c = _vers_course([ligne[1] for ligne in lignes], cotes,
                         numeros.index(gagnant), [ligne[3] for ligne in lignes], cov)
        if c is not None:
            out.append(c)
    return out


def _extraits_features(session: AsyncSession) -> tuple[str, str]:
    """Expressions SQL lisant mouvement_30min et cote_geny dans `pe.features`.

    Extraites en base plutôt que de rapatrier 90 jours de vecteurs entiers (~200
    clés par partant). PostgreSQL et SQLite n'ont pas la même syntaxe JSON.
    """
    try:
        dialecte = session.bind.dialect.name
    except AttributeError:
        dialecte = "postgresql"
    if dialecte == "sqlite":
        return ("json_extract(pe.features, '$.mouvement_30min')",
                "json_extract(pe.features, '$.cote_geny')")
    return ("(pe.features::jsonb ->> 'mouvement_30min')",
            "(pe.features::jsonb ->> 'cote_geny')")


_DDL = """
    CREATE TABLE IF NOT EXISTS melange_arrivees (
        id INTEGER PRIMARY KEY,
        data TEXT NOT NULL,
        updated_at TIMESTAMP
    )
"""
# Ligne 1 = les paramètres EN SERVICE (écrits seulement quand une mesure tient).
# Ligne 2 = le dernier EXAMEN, retenu ou non. Une décision et une mesure ne
# partagent pas la même ligne (même convention que `sharpness_calibration`).
_ID_SERVICE, _ID_EXAMEN = 1, 2


async def _ecrire(session: AsyncSession, ident: int, donnees: dict) -> None:
    await session.execute(text("""
        INSERT INTO melange_arrivees (id, data, updated_at)
        VALUES (:id, :data, CURRENT_TIMESTAMP)
        ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data,
                                       updated_at = EXCLUDED.updated_at
    """), {"id": ident, "data": json.dumps(donnees, ensure_ascii=False)})


async def _lire(session: AsyncSession, ident: int) -> Optional[dict]:
    try:
        r = (await session.execute(text(
            "SELECT data FROM melange_arrivees WHERE id = :id"), {"id": ident})).first()
    except Exception as e:                                       # noqa: BLE001
        # DÉSEMPOISONNER la transaction : avant la première nuit la table n'existe
        # pas, et asyncpg ferait échouer la requête SUIVANTE de l'appelant.
        try:
            await session.rollback()
        except Exception:                                        # noqa: BLE001
            pass
        log.debug("melange_arrivees.lecture_ignoree", err=str(e)[:120])
        return None
    if not r or not r[0]:
        return None
    return r[0] if isinstance(r[0], dict) else json.loads(r[0])


async def charger(session: AsyncSession) -> dict:
    """Paramètres en service, ou « non retenu ». Met le cache mémoire à jour."""
    global _cache
    donnees = await _lire(session, _ID_SERVICE)
    if donnees and donnees.get("retenu"):
        _cache = donnees
    return _cache or {"retenu": False}


async def charger_dernier_examen(session: AsyncSession) -> Optional[dict]:
    return await _lire(session, _ID_EXAMEN)


async def calculer_et_persister(session: AsyncSession) -> dict:
    """Examine le mélange sur les arrivées et le met en service s'il tient.

    Ne retire JAMAIS des paramètres en service quand la mesure du soir ne conclut
    pas : même règle de démarrage à froid que toutes les calibrations du système.
    """
    global _cache
    await session.execute(text(_DDL))
    courses = await _charger_courses(session)
    verdict = evaluer(courses)
    examen = {**verdict, "examine_le": datetime.now(timezone.utc).isoformat(),
              "fenetre_jours": FENETRE_JOURS, "fraicheur_max_min": FRAICHEUR_MAX_MIN}
    try:
        await _ecrire(session, _ID_EXAMEN, examen)
    except Exception as e:                                       # noqa: BLE001
        # Une trace de supervision ne doit jamais faire échouer l'apprentissage.
        log.warning("melange_arrivees.trace_examen_ignoree", err=str(e)[:140])
    if not verdict.get("retenu"):
        log.info("melange_arrivees.valeur_conservee", **{k: v for k, v in verdict.items()
                                                          if k not in ("betas_par_moitie",
                                                                       "etendu")})
        return {"status": "valeur_conservee", **verdict}
    donnees = {**examen, "applique_depuis": datetime.now(timezone.utc).isoformat()}
    await _ecrire(session, _ID_SERVICE, donnees)
    _cache = donnees
    _et = verdict.get("etendu") or {}
    log.info("melange_arrivees.ajuste", beta_modele=verdict["beta_modele"],
             beta_marche=verdict["beta_marche"], n_courses=verdict["n_courses"],
             etendu=bool(_et.get("retenu")), gammas=_et.get("gammas"),
             gain_etendu=_et.get("gain_logv_vs_deux_parametres"),
             gain_logv_vs_marche=verdict["gain_logv_vs_marche"],
             gain_logv_vs_servi=verdict["gain_logv_vs_servi"])
    return {"status": "ok", **donnees}
