"""LE MODÈLE TECHNIQUE — la valeur propre du cheval, sans lire la cote.

Le défaut qu'il corrige
───────────────────────
Le modèle de victoire en service apprend AVEC la cote : les quatre colonnes de
marché portent 41 % de son importance, et sa proba brute est corrélée à 0,92 avec
la cote (en log). Mélanger ensuite « modèle » et « marché » revient à mélanger le
marché avec lui-même : le modèle ne peut presque rien dire que la cote ne dise déjà,
et un cheval sous-évalué par les parieurs le reste dans le classement.

Ce module entraîne un modèle de VICTOIRE et un modèle de PLACEMENT (top 3) qui ne
voient AUCUNE information venue des parieurs : ni la cote, ni ses dérivés (rang de
cote, popularité, mouvements, masse d'enjeux, concentration du champ, accord des
signaux…). Il ne lit que la course et le cheval : forme, ELO, confrontations,
aptitudes distance / terrain, jockey, entraîneur, repos, ferrure, risque de faute…

Mesuré le 2026-09-16, modèles entraînés jusqu'au 10/08, jugés sur 1 536 courses
figées à T-10 du 17/08 au 16/09 :

                                  seul (AUC)   mélangé à la cote : gain de
                                               log-vraisemblance sur la cote
    modèle de victoire en service   0,7314       +0,011 [+0,004 ; +0,019]
    MODÈLE TECHNIQUE                0,7287       +0,032 [+0,019 ; +0,045]
    (classement final mélangé : 0,7523 → 0,7560)

Seul, il classe un peu moins bien que la cote — normal, il se prive d'elle. Mais il
se trompe AUTREMENT (corrélation 0,73 au lieu de 0,92) : c'est cette indépendance
qui fait trois fois plus d'information une fois mélangée au marché. Et ses
désaccords sont justes : un cheval qu'il juge 1,6 fois plus probable que la cote
gagne 9,7 % du temps pour 8,1 % annoncés et 4,6 % implicites dans la cote.

Placement, même période, log-loss par partant (↓ mieux) :
    proba placé en service 0,5430 · cote seule 0,5564 · technique × cote 0,5055

Ce qui a été mesuré et ÉCARTÉ (hors échantillon, même protocole) : des modèles
séparés par discipline (+0,006 non significatif, classement −0,002), des poids
modèle/cote propres à chaque discipline ou à l'ouverture de la course (−0,004 : du
sur-apprentissage), ajouter au mélange le risque de galop, le taux de
disqualification, la faute récente ou l'inédit (+0,001 non significatif — le
modèle technique les porte déjà). Le type de course vit DANS le modèle, qui en a
toutes les variables (`discipline_code`, `risque_galop_trot`, `nb_partants`…).

Le cycle nocturne
─────────────────
1. Entraînement sur 12 mois qui s'ARRÊTENT `VALIDATION_JOURS` jours avant
   aujourd'hui (mesuré : 30 jours d'écart ne coûtent que −0,003, non significatif).
2. Les courses de ces derniers jours — jamais vues — servent de juge : on relit les
   features EXACTES servies à T-10 (`prediction_snapshots`), on y applique le
   modèle, on apprend le mélange avec la cote en validation croisée chronologique.
3. Mis en service seulement si le mélange bat la cote seule (IC entièrement
   positif) sans annoncer ni classer moins bien que ce qui est servi — mêmes
   critères que `ml.melange_arrivees`. Le placement a son propre verdict.
4. Sinon le modèle en place est conservé tel quel, et l'examen est tracé.
"""
from __future__ import annotations

import json
import math
import os
import pickle
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Sequence

import numpy as np
import pandas as pd
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ml import melange_arrivees as ma
from ml.learning_steps import _vers_datetime

log = structlog.get_logger(module="modele_technique")

# Tout ce qui vient des PARIEURS. Les sept colonnes officielles de marché
# (`models.COLONNES_MARCHE`) plus leurs dérivés trouvés dans le vecteur servi :
# mouvements de cote, masse d'enjeux, indice de steam, et les mesures du champ
# calculées À PARTIR des cotes (concentration, nombre d'outsiders, écart au 2e,
# accord des signaux, confiance composite, momentum de cote).
COLONNES_PARIEURS = frozenset({
    "cote_pmu", "prob_implicite", "rang_cote", "est_favori", "rang_popularite",
    "rang_cote_relatif", "indice_valeur",
    "spi_score", "mouvement_30min", "mouvement_bm_pct", "variance_cotes_7j",
    "pool_gagnant_ratio", "pool_gagnant_evolution", "tendance_cote_force",
    "market_timing_score", "field_hhi", "nb_outsiders", "ecart_proba_top2",
    "signal_agreement", "composite_confidence", "momentum_3j",
})

# Réglages retenus à l'expérience (900 arbres, profondeur 6) : +0,005 de
# vraisemblance sur le réglage du modèle en service, classement égal.
PARAMS_XGB = dict(n_estimators=900, max_depth=6, learning_rate=0.025, subsample=0.8,
                  colsample_bytree=0.6, min_child_weight=10, tree_method="hist",
                  eval_metric="logloss", random_state=42)

VALIDATION_JOURS = 28
MOIS_HISTORIQUE = 12
MIN_LIGNES_ENTRAINEMENT = 20_000
FRAICHEUR_MAX_MIN = ma.FRAICHEUR_MAX_MIN
# Moins de courses de validation que le mélange seul : la fenêtre ne compte que
# 28 jours (≈ 1 300 courses). L'intervalle du critère (a) reste le vrai juge.
MIN_COURSES_VALIDATION = 500

NOM_FICHIER = "modele_technique.pkl"


def _models_dir() -> Path:
    return Path(os.getenv("BT_MODELS_DIR", "/app/models"))


def colonnes_techniques(colonnes: Sequence[str]) -> list[str]:
    """Colonnes apprenables sans rien de ce que disent les parieurs."""
    from ml.models import META_COLS
    exclues = set(META_COLS) | COLONNES_PARIEURS
    return [c for c in colonnes if c not in exclues]


def matrice(features: pd.DataFrame, colonnes: Sequence[str]) -> pd.DataFrame:
    """Vecteur d'inférence : colonnes absentes à 0, comme à l'entraînement."""
    return (features.reindex(columns=list(colonnes))
            .apply(pd.to_numeric, errors="coerce").fillna(0).astype("float32"))


# ──────────────────────────────────────────────────────────────────────────────
# Le placement : proba placé technique × cote, régression logistique par partant
# ──────────────────────────────────────────────────────────────────────────────

def _x_place(p3_tech: np.ndarray, q: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p3_tech, dtype=float), 1e-4, 0.999)
    n = len(p)
    return np.column_stack([np.log(p / (1 - p)), np.log(np.clip(q, ma.PLANCHER, None)),
                            np.full(n, math.log(max(n, 2))), np.ones(n)])


def probas_place(p3_tech: Sequence[float], cotes: Sequence[float],
                 poids: Sequence[float]) -> Optional[np.ndarray]:
    """P(top 3) par partant, Σ = min(3, n), bornée à 0,99. None si inapplicable."""
    q = ma.probas_marche(cotes)
    p3 = np.asarray(p3_tech, dtype=float)
    try:
        w = np.asarray(poids, dtype=float)
    except (TypeError, ValueError):
        return None
    if q is None or p3.size != q.size or p3.size < 2 or w.shape != (4,) or not np.isfinite(w).all():
        return None
    if not np.isfinite(p3).all():
        return None
    brut = 1.0 / (1.0 + np.exp(-(_x_place(p3, q) @ w)))
    cible = float(min(3, p3.size))
    # Renormalisation par itérations bornées : un simple produit dépasserait 0,99
    # sur un grand favori et la somme ne tiendrait plus.
    p = brut * (cible / brut.sum())
    for _ in range(20):
        p = np.clip(p, 1e-4, 0.99)
        ecart = cible - p.sum()
        libres = p < 0.99
        if abs(ecart) < 1e-9 or not libres.any():
            break
        p[libres] += ecart * p[libres] / p[libres].sum()
    return np.clip(p, 1e-4, 0.99)


def _ajuster_poids_place(courses: Sequence[dict], iterations: int = 60) -> np.ndarray:
    """Logistique par partant (Newton), sur [logit p3 technique, ln q, ln n, 1]."""
    X = np.vstack([_x_place(c["p3"], c["q"]) for c in courses])
    y = np.concatenate([c["top3"] for c in courses]).astype(float)
    w = np.array([0.4, 0.7, -0.4, 2.0])
    for _ in range(iterations):
        p = 1.0 / (1.0 + np.exp(-(X @ w)))
        grad = X.T @ (y - p) - 1e-3 * w
        hess = -(X * (p * (1 - p))[:, None]).T @ X - 1e-3 * np.eye(4)
        try:
            pas = np.linalg.solve(hess, grad)
        except np.linalg.LinAlgError:
            break
        w = w - pas
        if float(np.abs(pas).max()) < 1e-8:
            break
    return w


def _logloss_place(p: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(p, 1e-4, 0.9999)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).sum())


def evaluer_place(courses: Sequence[dict]) -> dict:
    """Validation croisée chronologique du placement contre la proba placé SERVIE.

    Unité de mesure : la course (somme des log-loss de ses partants) — les partants
    d'une même course ne sont pas indépendants.
    """
    courses = list(courses)
    n = len(courses)
    if n < 2:
        return {"retenu": False, "raison": "échantillon vide", "n_courses": n}
    moitie = n // 2
    gains, ll_new, ll_servi, n_partants = [], 0.0, 0.0, 0
    for app, val in ((courses[:moitie], courses[moitie:]), (courses[moitie:], courses[:moitie])):
        w = _ajuster_poids_place(app)
        for c in val:
            p = probas_place(c["p3"], c["cotes"], w)
            if p is None:
                continue
            a = _logloss_place(p, c["top3"])
            b = _logloss_place(np.asarray(c["servi3"], dtype=float), c["top3"])
            gains.append(b - a)
            ll_new += a
            ll_servi += b
            n_partants += len(p)
    if len(gains) < 2:
        return {"retenu": False, "raison": "échantillon vide", "n_courses": len(gains)}
    m, bas, haut = ma._moy_ic(gains)
    verdict = {"poids": [round(float(x), 5) for x in _ajuster_poids_place(courses)],
               "n_courses": len(gains),
               "logloss_partant_nouveau": round(ll_new / max(n_partants, 1), 5),
               "logloss_partant_servi": round(ll_servi / max(n_partants, 1), 5),
               "gain_par_course": round(m, 5), "gain_par_course_ic95": [round(bas, 5), round(haut, 5)]}
    if len(gains) < MIN_COURSES_VALIDATION:
        return {"retenu": False, "raison": "échantillon trop court", **verdict}
    if not bas > 0:
        return {"retenu": False, "raison": "ne fait pas mieux que le placé servi", **verdict}
    return {"retenu": True, **verdict}


# ──────────────────────────────────────────────────────────────────────────────
# L'objet servi
# ──────────────────────────────────────────────────────────────────────────────

class ModeleTechnique:
    """Deux classifieurs sans information de marché + leurs deux mélanges appris."""

    def __init__(self, colonnes: Sequence[str]):
        self.colonnes = list(colonnes)
        self.victoire = None
        self.place = None
        self.train_fin: Optional[str] = None
        self.entraine_le: Optional[str] = None
        self.n_lignes = 0
        self.melange: dict = {}        # verdict victoire (beta_modele, beta_marche…)
        self.placement: dict = {}      # verdict placement (poids…)

    def entrainer(self, X: pd.DataFrame, y_top3: pd.Series, y_win: pd.Series) -> None:
        from xgboost import XGBClassifier
        from ml.models import _N_JOBS
        M = matrice(X, self.colonnes)
        self.victoire = XGBClassifier(**PARAMS_XGB, n_jobs=_N_JOBS)
        self.victoire.fit(M, np.asarray(y_win))
        self.place = XGBClassifier(**PARAMS_XGB, n_jobs=_N_JOBS)
        self.place.fit(M, np.asarray(y_top3))
        self.n_lignes = int(len(M))
        self.entraine_le = datetime.now(timezone.utc).isoformat()

    def brut(self, features: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        M = matrice(features, self.colonnes)
        return (self.victoire.predict_proba(M)[:, 1], self.place.predict_proba(M)[:, 1])

    def servir(self, features: pd.DataFrame, cotes: Sequence[float]
               ) -> tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """(P victoire, P placé) mélangées à la cote, ou None pour ce qui n'est pas
        retenu / pas applicable (cote manquante…)."""
        if self.victoire is None or self.place is None:
            return None, None
        p1, p3 = self.brut(features)
        win = place = None
        if self.melange.get("retenu"):
            win = ma.appliquer(p1, cotes, self.melange.get("beta_modele"),
                               self.melange.get("beta_marche"))
        if self.placement.get("retenu"):
            place = probas_place(p3, cotes, self.placement.get("poids") or [])
        return win, place

    def sauver(self, chemin: Optional[Path] = None) -> Path:
        chemin = chemin or (_models_dir() / NOM_FICHIER)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        tmp = chemin.with_name(chemin.name + ".tmp")
        with open(tmp, "wb") as f:
            pickle.dump(self, f, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(chemin)
        return chemin


# ──────────────────────────────────────────────────────────────────────────────
# Confirmation des valeurs détectées ★★
# ──────────────────────────────────────────────────────────────────────────────
# Mesuré le 2026-09-16, paris de valeur ★★ du 10/08 au 15/09 réglés au rapport PMU
# officiel du Simple Gagnant (gains plafonnés ×20), selon que le modèle technique
# (sans la cote, mélangé à la cote) confirme la valeur — p_technique × cote ≥ 1 :
#
#                         10/08 → 27/08          28/08 → 15/09
#     non confirmés    185 paris  −32,4 % ± 16    583 paris  −36,5 % ± 9
#     confirmés         92 paris   −7,1 % ± 26    355 paris   −1,1 % ± 15
#
# Même écart dans les deux moitiés (et sur toute la période 01/07 → 15/09 :
# −32,6 % contre −2,5 %). Aucun écart en ★★★ (−18,1 / −18,6) ni en ★★★★
# (+16,5 / +16,7) : la confirmation ne s'applique qu'au ★★. Un ★★ non confirmé est
# RÉTROGRADÉ en ★ — il reste écrit en base pour la mesure, il n'est plus affiché
# (`services.valuebets_visibilite.NIVEAU_MIN_VISIBLE = 2`).
NIVEAU_A_CONFIRMER = 2


def confirmer_valeur(niveau: int, p_technique: Optional[float],
                     cote: Optional[float]) -> tuple[int, Optional[bool]]:
    """(niveau retenu, confirmée ?) — None quand la confirmation ne s'applique pas
    (autre niveau, pas de proba technique, pas de cote) : le niveau est inchangé."""
    if niveau != NIVEAU_A_CONFIRMER or p_technique is None or not cote or cote <= 1:
        return niveau, None
    try:
        confirme = float(p_technique) * float(cote) >= 1.0
    except (TypeError, ValueError):
        return niveau, None
    return (niveau if confirme else niveau - 1), confirme


_instance: Optional[ModeleTechnique] = None
_mtime: Optional[float] = None


def en_service() -> Optional[ModeleTechnique]:
    """Le modèle en service, relu dès que son fichier change (un `stat` par appel).

    Même règle que le méta-apprenant : le nocturne tourne dans le worker, les
    prédictions dans le scraper — sans suivre le fichier, un modèle réappris ne
    serait servi qu'au redémarrage suivant du conteneur.
    """
    global _instance, _mtime
    chemin = _models_dir() / NOM_FICHIER
    try:
        mtime = chemin.stat().st_mtime
    except OSError:
        _instance, _mtime = None, None
        return None
    if _instance is not None and mtime == _mtime:
        return _instance
    try:
        with open(chemin, "rb") as f:
            obj = pickle.load(f)
        if isinstance(obj, ModeleTechnique):
            _instance, _mtime = obj, mtime
            log.info("modele_technique.charge", train_fin=obj.train_fin,
                     victoire=bool(obj.melange.get("retenu")),
                     placement=bool(obj.placement.get("retenu")))
    except Exception as e:                                       # noqa: BLE001
        log.warning("modele_technique.chargement_echoue", err=str(e)[:140])
    return _instance


# ──────────────────────────────────────────────────────────────────────────────
# Le cycle nocturne
# ──────────────────────────────────────────────────────────────────────────────

def _gagnant_et_places(classement) -> tuple[Optional[int], set]:
    if isinstance(classement, str):
        try:
            classement = json.loads(classement)
        except (ValueError, TypeError):
            return None, set()
    gagnant, places = None, set()
    for e in classement or []:
        try:
            pos, num = int(e.get("position")), int(e.get("numero"))
        except (TypeError, ValueError, AttributeError):
            continue
        if pos == 1 and gagnant is None:
            gagnant = num
        if pos <= 3:
            places.add(num)
    return gagnant, places


async def _courses_de_validation(session: AsyncSession, modele: ModeleTechnique,
                                 depuis: datetime) -> list[dict]:
    """Courses COMPLÈTES depuis `depuis`, scorées par `modele` sur leurs features
    exactes de T-10. Lecture en flux : une partition de features à la fois."""
    res = await session.stream(text("""
        SELECT pe.course_id, pa.numero, pe.features, pe.proba_top1, pe.proba_top3,
               pe.cote_figee, pe.created_at, c.date_heure, r.classement, np.n
        FROM prediction_evaluation pe
        JOIN participations pa ON pa.participation_id = pe.participation_id
        JOIN courses c         ON c.course_id         = pe.course_id
        JOIN resultats r       ON r.course_id         = pe.course_id
        JOIN (SELECT course_id, count(*) AS n FROM participations
               WHERE COALESCE(non_partant, false) = false
               GROUP BY course_id) np ON np.course_id = pe.course_id
        WHERE pe.is_replayable = true AND pe.features IS NOT NULL
          AND pe.proba_top1 IS NOT NULL AND pe.proba_top3 IS NOT NULL
          AND COALESCE(pa.non_partant, false) = false
          AND r.classement IS NOT NULL AND c.date_heure IS NOT NULL
          AND pe.created_at IS NOT NULL AND pe.created_at < c.date_heure
          AND c.date_heure >= :depuis
        ORDER BY c.date_heure ASC, pe.course_id ASC, pa.numero ASC
    """), {"depuis": depuis})
    fraicheur = timedelta(minutes=FRAICHEUR_MAX_MIN)
    par_course: dict[str, dict] = {}
    async for partition in res.partitions(2000):
        lignes, feats = [], []
        for cid, num, f, s1, s3, cote, cree, dh, classement, n in partition:
            depart, calcul = _vers_datetime(dh), _vers_datetime(cree)
            d = par_course.setdefault(cid, {"l": [], "classement": classement, "n": int(n or 0)})
            if depart is None or calcul is None or depart - calcul > fraicheur:
                d["perimee"] = True
                continue
            feats.append(f if isinstance(f, dict) else json.loads(f))
            lignes.append((cid, int(num), float(s1), float(s3),
                           float(cote) if cote is not None else float("nan")))
        if not lignes:
            continue
        p1, p3 = modele.brut(pd.DataFrame(feats))
        for (cid, num, s1, s3, cote), a, b in zip(lignes, p1, p3):
            par_course[cid]["l"].append((num, float(a), float(b), cote, s1, s3))

    out: list[dict] = []
    for d in par_course.values():
        l = d["l"]
        if d.get("perimee") or len(l) < ma.MIN_PARTANTS or len(l) != d["n"]:
            continue
        gagnant, places = _gagnant_et_places(d["classement"])
        nums = [x[0] for x in l]
        if gagnant is None or gagnant not in nums:
            continue
        cotes = [x[3] for x in l]
        c = ma._vers_course([x[1] for x in l], cotes, nums.index(gagnant), [x[4] for x in l])
        if c is None:
            continue
        c.update({"p3": np.array([x[2] for x in l]), "cotes": cotes,
                  "servi3": np.array([x[5] for x in l]),
                  "top3": np.array([1.0 if x in places else 0.0 for x in nums])})
        out.append(c)
    return out


_DDL = """
    CREATE TABLE IF NOT EXISTS modele_technique (
        id INTEGER PRIMARY KEY,
        data TEXT NOT NULL,
        updated_at TIMESTAMP
    )
"""
_ID_SERVICE, _ID_EXAMEN = 1, 2


async def _tracer(session: AsyncSession, ident: int, donnees: dict) -> None:
    try:
        await session.execute(text(_DDL))
        await session.execute(text("""
            INSERT INTO modele_technique (id, data, updated_at)
            VALUES (:id, :data, CURRENT_TIMESTAMP)
            ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data,
                                           updated_at = EXCLUDED.updated_at
        """), {"id": ident, "data": json.dumps(donnees, ensure_ascii=False, default=str)})
    except Exception as e:                                       # noqa: BLE001
        log.warning("modele_technique.trace_ignoree", err=str(e)[:140])


async def lire_etat(session: AsyncSession, ident: int) -> Optional[dict]:
    try:
        r = (await session.execute(text(
            "SELECT data FROM modele_technique WHERE id = :id"), {"id": ident})).first()
    except Exception:                                            # noqa: BLE001
        try:
            await session.rollback()
        except Exception:                                        # noqa: BLE001
            pass
        return None
    if not r or not r[0]:
        return None
    return r[0] if isinstance(r[0], dict) else json.loads(r[0])


async def entrainer_et_valider(maintenant: Optional[datetime] = None,
                               persister: bool = True) -> dict:
    """Entraîne, juge sur les derniers jours jamais vus, met en service si ça tient.

    `persister=False` : mesure seule (rejeu sur la base de production sans rien
    écrire ni mettre en service).
    """
    from db.database import AsyncSessionLocal
    from ml.pipeline import _build_training_dataset_from_db
    from api.config import get_settings

    maintenant = maintenant or datetime.now(timezone.utc)
    coupure = maintenant - timedelta(days=VALIDATION_JOURS)
    settings = get_settings()
    async with AsyncSessionLocal() as s:
        X, y3, yw = await _build_training_dataset_from_db(
            s, MOIS_HISTORIQUE, max_rows=settings.retrain_max_rows,
            date_fin=coupure)
    if len(X) < MIN_LIGNES_ENTRAINEMENT:
        examen = {"retenu": False, "raison": "données d'entraînement insuffisantes",
                  "n_lignes": int(len(X)), "examine_le": maintenant.isoformat()}
        if persister:
            async with AsyncSessionLocal() as s:
                await _tracer(s, _ID_EXAMEN, examen)
                await s.commit()
        return {"status": "insuffisant", **examen}

    cols = colonnes_techniques(X.columns)
    cols = [c for c in cols if X[c].nunique(dropna=False) > 1
            and pd.api.types.is_numeric_dtype(X[c])]
    modele = ModeleTechnique(cols)
    modele.train_fin = coupure.isoformat()
    modele.entrainer(X, y3, yw)
    del X
    log.info("modele_technique.entraine", n_lignes=modele.n_lignes, n_colonnes=len(cols))

    async with AsyncSessionLocal() as s:
        courses = await _courses_de_validation(s, modele, coupure)
    victoire = ma.evaluer(courses)
    if victoire.get("n_courses", 0) < MIN_COURSES_VALIDATION and victoire.get("retenu"):
        victoire = {**victoire, "retenu": False, "raison": "échantillon trop court"}
    placement = evaluer_place(courses) if courses else {"retenu": False,
                                                         "raison": "échantillon vide"}
    modele.melange = victoire
    modele.placement = placement

    examen = {
        "retenu": bool(victoire.get("retenu")),
        "placement_retenu": bool(placement.get("retenu")),
        "train_fin": modele.train_fin, "entraine_le": modele.entraine_le,
        "n_lignes": modele.n_lignes, "n_colonnes": len(cols),
        "victoire": {k: v for k, v in victoire.items()},
        "placement": {k: v for k, v in placement.items()},
        "examine_le": maintenant.isoformat(),
    }
    if not persister:
        return {"status": "mesure_seule", **examen}
    async with AsyncSessionLocal() as s:
        await _tracer(s, _ID_EXAMEN, examen)
        # Un seul des deux verdicts suffit à servir : `servir()` n'applique que ce
        # qui a été retenu, l'autre proba reste celle de la chaîne d'avant.
        if victoire.get("retenu") or placement.get("retenu"):
            chemin = modele.sauver()
            await _tracer(s, _ID_SERVICE, {**examen, "fichier": str(chemin),
                                           "applique_depuis": maintenant.isoformat()})
        await s.commit()
    log.info("modele_technique.examen", retenu=examen["retenu"],
             placement=examen["placement_retenu"],
             beta_modele=victoire.get("beta_modele"), beta_marche=victoire.get("beta_marche"),
             gain_vs_marche=victoire.get("gain_logv_vs_marche"),
             n_courses=victoire.get("n_courses"))
    en_service_ = examen["retenu"] or examen["placement_retenu"]
    return {"status": "ok" if en_service_ else "valeur_conservee", **examen}
