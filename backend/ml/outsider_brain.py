"""LE CERVEAU DES OUTSIDERS — repérer les grosses cotes capables de se placer.

Ce qu'il fait
─────────────
Un modèle dédié, appris UNIQUEMENT sur les partants cotés 10 ou plus, qui estime la
chance d'un outsider de finir dans les places payées au Simple Placé (3 premiers,
2 premiers à 7 partants ou moins). Il lit :

- tout le vecteur de features servi avant la course (forme, ELO, jockey, entraîneur,
  terrain, distance, presse, ferrure…) EXACTEMENT tel qu'il était à l'instant du
  pronostic (`prediction_snapshots`, jamais un recalcul après coup) ;
- le pronostic du modèle général (proba victoire / placé, rang, place relative parmi
  les outsiders de la course) ;
- le MARCHÉ autrement que par la seule cote PMU : écart avec les bookmakers et
  Betfair (un outsider plus généreux au PMU qu'ailleurs est sous-coté au PMU), et la
  dérive de sa cote depuis le premier pronostic du jour (un outsider « joué »).

- sa place DANS LE CHAMP du jour pour chacun de ces critères : rang de forme,
  d'ELO, de podiums, de jockey, de vitesse… parmi TOUS les partants de la course
  (ajouté le 2026-10-07 : AUC +0,005 sur les 3 mêmes découpes, log-loss
  meilleure partout ; un critère ne vaut que comparé aux adversaires du jour).

Sa sortie est mélangée à parts égales avec la proba placé du modèle général
recalibrée sur la réalité des outsiders (isotone) : les deux se trompent autrement.

Mesuré le 2026-10-07 (snapshots live 18/08 → 06/10, 3 découpes chronologiques,
modèle entraîné sur le passé, jugé sur les 2 semaines suivantes jamais vues) :

                         AUC vs modèle général recalibré   log-loss
    découpe 01/09-15/09        +0,042                       mieux
    découpe 15/09-29/09        +0,021                       mieux
    découpe 29/09-07/10        +0,012                       mieux

    Sélection (au plus 2 par course, cote ≥ 15) :
      chance ≥ 22 % : ~25 / jour, placés 27 %
      chance ≥ 25 % : ~12 / jour, placés 31 %
      chance ≥ 28 % : ~6 / jour,  placés 35 %
    Outsider moyen (cote ≥ 15) : placés 13 %.

HONNÊTETÉ : aucun rendement positif n'est prouvé. Joués à plat, les outsiders
retenus perdent encore (Simple Placé −6 à −12 % selon le seuil). Le cerveau sait
repérer ceux qui se placent DEUX À TROIS FOIS plus souvent que les autres ; il ne
promet pas de battre le prélèvement. Ne jamais l'afficher comme « rentable ».

Le cycle
────────
Chaque nuit (`pipeline`, après le modèle technique) : jeu d'entraînement relu dans
les snapshots, les `VALIDATION_JOURS` derniers jours servent de juge. Mis en service
seulement si le mélange classe au moins aussi bien que le modèle général recalibré
sur ces jours jamais vus ; sinon l'ancien cerveau reste (ou aucun : le module
retombe alors sur la proba placé recalibrée seule).
"""
from __future__ import annotations

import json
import math
import os
import pickle
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Sequence

import numpy as np
import pandas as pd
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(module="outsider_brain")

COTE_APPRENTISSAGE_MIN = 10.0     # apprend sur ≥ 10 (plus de données, cote en feature)
COTE_OUTSIDER_MIN = 15.0          # n'affiche que ≥ 15
SEUIL_A_SUIVRE = 0.22             # chance de place estimée
SEUIL_FORT = 0.28
MAX_PAR_COURSE = 2
JOURS_HISTORIQUE = 120   # tous les partants sont lus : ~70 k lignes, mémoire du worker
VALIDATION_JOURS = 14
MIN_LIGNES_ENTRAINEMENT = 5_000
MIN_LIGNES_VALIDATION = 1_500
TOLERANCE_AUC = 0.002             # le mélange doit classer au moins aussi bien
POIDS_CERVEAU = 0.5

NOM_FICHIER = "outsider_brain.pkl"

PARAMS_LGB = dict(n_estimators=400, learning_rate=0.02, num_leaves=15,
                  min_child_samples=100, subsample=0.8, subsample_freq=1,
                  colsample_bytree=0.5, reg_lambda=5.0, verbose=-1, random_state=0)


def _models_dir() -> Path:
    return Path(os.getenv("BT_MODELS_DIR", "/app/models"))


def nb_places(partants: int) -> int:
    """Places payées au Simple Placé PMU : 0 sous 4 partants, 2 jusqu'à 7, sinon 3."""
    if partants < 4:
        return 0
    return 2 if partants <= 7 else 3


# ──────────────────────────────────────────────────────────────────────────────
# Lecture des snapshots
# ──────────────────────────────────────────────────────────────────────────────

# Dernier ET premier snapshot pré-course de chaque partant (live seulement). Le
# premier donne la cote du premier pronostic : sa dérive jusqu'au dernier est un
# signal de marché disponible avant le départ.
_SQL_SNAPSHOTS = """
WITH last AS (
  SELECT DISTINCT ON (s.participation_id)
         s.participation_id, s.course_id, s.proba_top1, s.proba_top3, s.rang_predit,
         s.cote_figee, s.features, s.observed_at
  FROM prediction_snapshots s
  WHERE s.is_pre_course AND s.origin = 'live' AND s.observed_at <= s.course_start_at
    AND {filtre}
  ORDER BY s.participation_id, s.observed_at DESC
), first AS (
  SELECT DISTINCT ON (s.participation_id) s.participation_id, s.cote_figee AS cote_premiere
  FROM prediction_snapshots s
  WHERE s.is_pre_course AND s.origin = 'live' AND s.cote_figee IS NOT NULL
    AND s.observed_at <= s.course_start_at AND {filtre}
  ORDER BY s.participation_id, s.observed_at ASC
)
SELECT l.participation_id, l.course_id, p.numero, p.cheval_id, p.musique,
       l.cote_figee, f.cote_premiere, l.proba_top1, l.proba_top3, l.rang_predit,
       l.features, l.observed_at,
       (SELECT count(*) FROM participations p2
         WHERE p2.course_id = l.course_id AND NOT coalesce(p2.non_partant, false)) AS partants
       {colonnes_resultat}
FROM last l
LEFT JOIN first f USING (participation_id)
JOIN participations p ON p.participation_id = l.participation_id
WHERE NOT coalesce(p.non_partant, false) AND l.cote_figee >= :cote_min
"""

_COLONNES_RESULTAT = """,
       hc.position_arrivee,
       EXISTS (SELECT 1 FROM historique_courses h2
               WHERE h2.course_id = l.course_id AND h2.position_arrivee IS NOT NULL) AS course_terminee
"""


async def charger_snapshots(session: AsyncSession, *, depuis: Optional[datetime] = None,
                            course_ids: Optional[Sequence[str]] = None,
                            avec_resultat: bool = False,
                            cote_min: float = 1.0) -> pd.DataFrame:
    """Snapshots pré-course (dernier + cote du premier) de TOUS les partants
    (le rang de chaque critère se mesure contre tout le champ ; `preparer` ne
    garde ensuite que les cotes ≥ 10)."""
    params: dict = {"cote_min": cote_min}
    if course_ids is not None:
        if not course_ids:
            return pd.DataFrame()
        filtre = "s.course_id = ANY(:cids)"
        params["cids"] = list(course_ids)
    else:
        filtre = "s.course_start_at >= :depuis"
        params["depuis"] = depuis or (datetime.now(timezone.utc) - timedelta(days=JOURS_HISTORIQUE))
    sql = _SQL_SNAPSHOTS.format(filtre=filtre,
                                colonnes_resultat=_COLONNES_RESULTAT if avec_resultat else "")
    if avec_resultat:
        sql = sql.replace("JOIN participations p ON p.participation_id = l.participation_id",
                          "JOIN participations p ON p.participation_id = l.participation_id\n"
                          "LEFT JOIN historique_courses hc ON hc.cheval_id = p.cheval_id "
                          "AND hc.course_id = l.course_id")
    rows = (await session.execute(text(sql), params)).mappings().all()
    return pd.DataFrame([dict(r) for r in rows])


# ──────────────────────────────────────────────────────────────────────────────
# Matrice de features (identique à l'entraînement et en service)
# ──────────────────────────────────────────────────────────────────────────────

def _features_dict(brut) -> dict:
    if isinstance(brut, dict):
        return brut
    if isinstance(brut, str):
        try:
            return json.loads(brut)
        except ValueError:
            return {}
    return {}


def preparer(df: pd.DataFrame, cote_min: float = COTE_APPRENTISSAGE_MIN) -> pd.DataFrame:
    """Aplatit le vecteur servi (préfixe `f_`), place chaque critère dans le champ
    (préfixe `r_`, rang centile parmi TOUS les partants lus de la course), puis ne
    garde que les partants cotés ≥ `cote_min` et ajoute les colonnes dérivées.

    Les rangs « parmi les outsiders » (`p3_rank`, `p3_rel`) se calculent, eux,
    après ce filtre — comme à l'entraînement.
    """
    d = df.reset_index(drop=True).copy()
    feats = pd.DataFrame([_features_dict(x) for x in d["features"]])
    feats = feats.apply(pd.to_numeric, errors="coerce")
    feats = feats.loc[:, feats.notna().any()]
    feats.columns = [f"f_{c}" for c in feats.columns]
    d = pd.concat([d.drop(columns=["features"]), feats], axis=1)
    for c in ("cote_figee", "cote_premiere", "proba_top1", "proba_top3", "rang_predit", "partants"):
        d[c] = pd.to_numeric(d.get(c), errors="coerce")

    fcols = list(feats.columns)
    g = d.groupby("course_id")
    rangs = g[fcols].rank(pct=True)
    rangs.columns = [f"r_{c[2:]}" for c in fcols]
    d = pd.concat([d, rangs], axis=1)
    d["r_p3"] = g["proba_top3"].rank(pct=True)
    d["r_p1"] = g["proba_top1"].rank(pct=True)
    d["n_champ"] = g["course_id"].transform("size")
    d = d[d["cote_figee"] >= cote_min].reset_index(drop=True)

    d["cote_premiere"] = d["cote_premiere"].fillna(d["cote_figee"])
    d["lc"] = np.log(d["cote_figee"].clip(lower=1.01))
    d["derive"] = np.log(d["cote_figee"].clip(lower=1.01) / d["cote_premiere"].clip(lower=1.01))
    d["places"] = d["partants"].fillna(0).astype(int).map(nb_places)
    d["p3_rank"] = d.groupby("course_id")["proba_top3"].rank(ascending=False)
    d["p3_rel"] = d["proba_top3"] / d.groupby("course_id")["proba_top3"].transform("max").clip(lower=1e-6)
    d["edge3"] = np.log(d["proba_top3"].clip(lower=1e-3)) + d["lc"]
    return d


COLONNES_DERIVEES = ["proba_top1", "proba_top3", "rang_predit", "lc", "derive", "partants",
                     "places", "p3_rank", "p3_rel", "edge3"]


def matrice(d: pd.DataFrame, colonnes: Sequence[str]) -> pd.DataFrame:
    return (d.reindex(columns=list(colonnes)).apply(pd.to_numeric, errors="coerce")
            .astype("float32"))


def _place(d: pd.DataFrame) -> np.ndarray:
    pos = pd.to_numeric(d["position_arrivee"], errors="coerce")
    return ((pos >= 1) & (pos <= d["places"])).astype(int).to_numpy()


# ──────────────────────────────────────────────────────────────────────────────
# Entraînement nocturne
# ──────────────────────────────────────────────────────────────────────────────

def _auc(y: np.ndarray, p: np.ndarray) -> float:
    from sklearn.metrics import roc_auc_score
    return float(roc_auc_score(y, p))


def _selection(d: pd.DataFrame, chance: np.ndarray, seuil: float) -> pd.DataFrame:
    t = d.assign(chance=chance)
    t = t[(t["cote_figee"] >= COTE_OUTSIDER_MIN) & (t["chance"] >= seuil)]
    t = t.sort_values("chance", ascending=False).groupby("course_id").head(MAX_PAR_COURSE)
    return t


def entrainer_sur(d: pd.DataFrame, fin_train: pd.Timestamp) -> dict:
    """Entraîne et juge sur un DataFrame préparé (fonction pure, testable).

    `d` doit porter `jour` (date de course), `y` (placé 0/1) et les colonnes de
    `preparer`. Renvoie l'artefact (`retenu`) et les métriques de validation.
    """
    import lightgbm as lgb
    from sklearn.isotonic import IsotonicRegression

    colonnes = ([c for c in d.columns if c.startswith("f_")]
                + [c for c in d.columns if c.startswith("r_")] + COLONNES_DERIVEES)
    tr = d["jour"] < fin_train
    va = (~tr) & (d["cote_figee"] >= COTE_OUTSIDER_MIN)
    tr15 = tr & (d["cote_figee"] >= COTE_OUTSIDER_MIN)
    out: dict = {"n_train": int(tr.sum()), "n_validation": int(va.sum()),
                 "fin_train": str(fin_train.date())}
    if tr.sum() < MIN_LIGNES_ENTRAINEMENT or va.sum() < MIN_LIGNES_VALIDATION:
        out["status"] = "insuffisant"
        return out

    y = d["y"].to_numpy()
    clf = lgb.LGBMClassifier(**PARAMS_LGB)
    clf.fit(matrice(d[tr], colonnes), y[tr.to_numpy()])
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    iso.fit(d.loc[tr15, "proba_top3"], y[tr15.to_numpy()])

    dv = d[va]
    yv = y[va.to_numpy()]
    p_base = iso.predict(dv["proba_top3"])
    p_mix = POIDS_CERVEAU * clf.predict_proba(matrice(dv, colonnes))[:, 1] + (1 - POIDS_CERVEAU) * p_base
    auc_mix, auc_base = _auc(yv, p_mix), _auc(yv, p_base)
    out.update(auc_cerveau=round(auc_mix, 4), auc_general=round(auc_base, 4),
               place_outsiders=round(float(yv.mean()), 4))
    for nom, seuil in (("a_suivre", SEUIL_A_SUIVRE), ("fort", SEUIL_FORT)):
        s = _selection(dv.assign(y=yv), p_mix, seuil)
        out[f"sel_{nom}"] = {"n": int(len(s)), "places": round(float(s["y"].mean()), 4) if len(s) else None,
                             "par_jour": round(len(s) / max(dv["jour"].nunique(), 1), 1)}
    out["retenu"] = bool(auc_mix >= auc_base - TOLERANCE_AUC)
    if not out["retenu"]:
        out["status"] = "rejete"
        return out

    # Validé : réappris sur TOUT l'historique pour la mise en service.
    clf_final = lgb.LGBMClassifier(**PARAMS_LGB)
    clf_final.fit(matrice(d, colonnes), y)
    tout15 = d["cote_figee"] >= COTE_OUTSIDER_MIN
    iso_final = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    iso_final.fit(d.loc[tout15, "proba_top3"], y[tout15.to_numpy()])
    out["status"] = "promu"
    out["artefact"] = {"cerveau": clf_final, "iso_general": iso_final, "colonnes": colonnes,
                       "sens": sens_criteres(d[tout15.to_numpy()], y[tout15.to_numpy()]),
                       "entraine_le": datetime.now(timezone.utc).isoformat(),
                       "validation": {k: v for k, v in out.items() if k != "artefact"}}
    return out


async def entrainer_et_valider() -> dict:
    """Étape nocturne : relit les snapshots, juge, met en service si ça tient."""
    from db.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        brut = await charger_snapshots(session, avec_resultat=True)
        await session.commit()   # clore la lecture avant l'entraînement (idle timeout)
    if brut.empty:
        return {"status": "insuffisant", "n_lignes": 0}
    brut = brut[brut["course_terminee"].astype(bool)]
    brut = brut[brut["partants"] >= 4]
    d = preparer(brut)
    d["y"] = _place(d)
    d["jour"] = pd.to_datetime(d["observed_at"], utc=True).dt.tz_convert("Europe/Paris").dt.normalize().dt.tz_localize(None)
    fin_train = d["jour"].max() - pd.Timedelta(days=VALIDATION_JOURS - 1)
    res = entrainer_sur(d, fin_train)
    res["n_lignes"] = int(len(d))
    art = res.pop("artefact", None)
    if art is not None:
        chemin = _models_dir() / NOM_FICHIER
        tmp = chemin.with_suffix(".tmp")
        with open(tmp, "wb") as fh:
            pickle.dump(art, fh)
        os.replace(tmp, chemin)
        _CACHE.clear()
    log.info("outsider_brain.entrainement", **{k: v for k, v in res.items()
                                               if not isinstance(v, dict)})
    return res


# ──────────────────────────────────────────────────────────────────────────────
# Service
# ──────────────────────────────────────────────────────────────────────────────

_CACHE: dict = {}


def en_service() -> Optional[dict]:
    """Artefact en service (rechargé si le fichier a changé), ou None."""
    chemin = _models_dir() / NOM_FICHIER
    try:
        mtime = chemin.stat().st_mtime
    except OSError:
        return None
    if _CACHE.get("mtime") != mtime:
        try:
            with open(chemin, "rb") as fh:
                _CACHE.update(art=pickle.load(fh), mtime=mtime)
        except Exception as e:  # noqa: BLE001
            log.warning("outsider_brain.chargement_impossible", err=str(e)[:160])
            return None
    return _CACHE.get("art")


# Ce que le cerveau a « vu » : contribution de chaque feature au score (SHAP natif
# LightGBM), regroupée en raisons lisibles. Seules les contributions POSITIVES
# servent de raisons ; la cote elle-même n'est jamais une raison.
_GROUPES: list[tuple[str, tuple[str, ...]]] = [
    ("sous_cote_pmu", ("f_cote_unibet", "f_cote_betfair_exchange", "f_cote_winamax", "f_cote_bzh",
                       "f_cote_betclic", "f_cote_marche_min", "f_gap_pmu_betfair", "f_ratio_pmu_geny",
                       "f_spread_bookmakers", "f_consensus_sources")),
    ("joue", ("derive", "f_mouvement_30min", "f_mouvement_ouverture", "f_steam_move_betclic",
              "f_tendance_cote_force", "f_market_timing_score", "f_pool_gagnant_ratio")),
    ("modele", ("proba_top3", "proba_top1", "p3_rel", "p3_rank", "rang_predit", "edge3",
                "f_valeur_latente", "f_indice_valeur", "f_valeur_vs_champ", "f_valeur_rang_relatif")),
    ("niveau", ("f_elo_vs_champ", "f_elo_global", "f_elo_vs_max", "f_elo_vs_moyenne", "f_elo_pct_rank",
                "f_elo_discipline", "f_gains_par_course_log", "f_gains_log", "f_opposition_quality",
                "f_class_drop_ratio_reel", "f_class_drop_ratio", "f_class_drop_flag")),
    ("forme", ("f_forme_1_course", "f_forme_3_courses", "f_forme_5_courses", "f_forme_10_courses",
               "f_forme_tendance", "f_time_decay_form", "f_recent_win_rate", "f_taux_top3",
               "f_taux_place_3", "f_taux_place_2", "f_regularite", "f_proximite_vainqueur",
               "f_defaite_courte_derniere", "f_speed_figure_recent", "f_speed_figure_best",
               "f_current_form_vs_best", "f_delta_elo_5courses", "f_velocity_elo")),
    ("entourage", ("f_jockey_forme_7j", "f_jockey_forme_30j", "f_jockey_roi", "f_jockey_taux_place_global",
                   "f_jockey_taux_victoire_global", "f_jockey_victoires_saison", "f_entraineur_forme_14j",
                   "f_entraineur_forme_30j", "f_entraineur_taux_place", "f_entraineur_taux_global",
                   "f_entraineur_roi", "f_entraineur_victoires_saison", "f_combo_jockey_entraineur",
                   "f_asso_jockey_entraineur_taux", "f_jockey_cheval_synergy_score", "f_changement_jockey",
                   "f_jockey_hist_score")),
    ("aptitudes", ("f_pref_terrain_actuel", "f_pref_terrain_bon", "f_pref_terrain_souple",
                   "f_pref_terrain_lourd", "f_pref_distance_actuelle", "f_pref_hippodrome",
                   "f_record_hippodrome", "f_sire_dist_winrate", "f_sire_terrain_winrate",
                   "f_running_style_terrain_fit", "f_corde_preference", "f_draw_bias_score",
                   "f_draw_bias_relatif", "f_delta_dist_prefere")),
    ("presse", ("f_nb_experts_presse", "f_presse_rang_moyen", "f_presse_score_borda",
                "f_presse_consensus_score", "f_presse_nb_sources", "f_nb_premier_presse",
                "f_pronostic_expert_rang", "f_rang_pronostic_geny", "f_avis_entraineur_score")),
    ("course", ("f_field_hhi", "f_nb_outsiders", "f_ecart_proba_top2", "partants", "places",
                "f_niveau_course_code", "f_nb_partants")),
    ("signaux", ("f_commentaire_malchance_recente", "f_commentaire_signal", "f_deferre_code",
                 "f_premier_deferre", "f_deferre_complet", "f_nouvelles_oeilleres", "f_oeilleres_delta",
                 "f_equipement_score", "f_jours_repos", "f_fraicheur_score", "f_trainer_return_bonus")),
]
_GROUPE_DE = {col: g for g, cols in _GROUPES for col in cols}


def _f(row: pd.Series, col: str) -> Optional[float]:
    v = row.get(col)
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def _phrase(groupe: str, row: pd.Series, n_out: int) -> Optional[str]:
    """Raison lisible et chiffrée quand la donnée le permet."""
    cote = _f(row, "cote_figee")
    if groupe == "sous_cote_pmu":
        autres = [v for v in (_f(row, c) for c in ("f_cote_betfair_exchange", "f_cote_unibet",
                                                   "f_cote_winamax", "f_cote_betclic", "f_cote_bzh"))
                  if v and cote and cote * 0.35 <= v < cote * 0.85]
        # Bornée basse : une cote 10 fois plus courte ailleurs est presque toujours un
        # mauvais appariement de cheval chez la source, pas une information.
        if autres:
            return f"Mieux coté ailleurs qu'au PMU ({max(autres):.0f} contre {cote:.0f}) : sous-coté au PMU"
        return "Le marché hors PMU le juge plus sérieusement que sa cote PMU"
    if groupe == "joue":
        prem = _f(row, "cote_premiere")
        if prem and cote and cote < prem * 0.85:
            return f"Joué depuis le premier pronostic (cote {prem:.0f} → {cote:.0f})"
        return "Mouvement de cote favorable avant le départ"
    if groupe == "modele":
        r = _f(row, "rang_predit"); n = _f(row, "partants")
        if r and n:
            return f"Notre modèle le classe {int(r)}e sur {int(n)}, bien mieux que sa cote"
        return "Notre modèle l'estime au-dessus de sa cote"
    if groupe == "niveau":
        return "Niveau (ELO, gains) au-dessus de ce que dit sa cote"
    if groupe == "forme":
        return "Forme récente encourageante"
    if groupe == "entourage":
        return "Jockey / entraîneur en réussite"
    if groupe == "aptitudes":
        return "Conditions du jour à sa convenance (terrain, distance, piste)"
    if groupe == "presse":
        return "Cité par la presse spécialisée"
    if groupe == "course":
        hhi = _f(row, "f_field_hhi")
        return "Course ouverte, sans favori écrasant" if hhi is not None and hhi < 0.12 else None
    if groupe == "signaux":
        return "Changement ou signal d'écurie favorable (ferrure, œillères, repos)"
    return None


def raisons(contribs: np.ndarray, colonnes: Sequence[str], row: pd.Series,
            n_out: int, maxi: int = 3) -> list[str]:
    """Top raisons positives (groupes distincts) d'après les contributions SHAP."""
    par_groupe: dict[str, float] = {}
    for col, c in zip(colonnes, contribs):
        g = _GROUPE_DE.get(col)
        if g is None or c <= 0:
            continue
        par_groupe[g] = par_groupe.get(g, 0.0) + float(c)
    out: list[str] = []
    for g, _ in sorted(par_groupe.items(), key=lambda kv: kv[1], reverse=True):
        p = _phrase(g, row, n_out)
        if p and p not in out:
            out.append(p)
        if len(out) >= maxi:
            break
    return out


# Critères détaillés sur la fiche de chaque outsider. Le cerveau en lit plus de
# 400 (valeur brute + rang dans le champ) ; ceux-ci sont ceux qu'un turfiste
# lit, chacun placé contre les adversaires du jour. Le SENS (plus haut = mieux,
# ou l'inverse) est appris sur les arrivées des outsiders (`sens_criteres`).
FICHE: list[tuple[str, str, Optional[str]]] = [
    ("taux_top3", "Podiums sur ses dernières courses", "pct"),
    ("time_decay_form", "Forme récente (pondérée)", None),
    ("forme_5_courses", "Forme sur 5 courses", None),
    ("forme_1_course", "Dernière course", None),
    ("proximite_vainqueur", "Écart au vainqueur (dernières courses)", None),
    ("recent_win_rate", "Victoires récentes", "pct"),
    ("taux_podium_carriere", "Podiums en carrière", "pct"),
    ("career_win_rate", "Victoires en carrière", "pct"),
    ("regularite", "Régularité", None),
    ("elo_global", "Niveau ELO", "entier"),
    ("elo_vs_champ", "ELO face aux adversaires du jour", "signe"),
    ("gains_par_course_log", "Gains par course", None),
    ("speed_figure_recent", "Vitesse récente", None),
    ("speed_figure_best", "Meilleure vitesse", None),
    ("dyn_reduction_km_moy", "Réduction kilométrique moyenne", None),
    ("pref_distance_actuelle", "Aptitude à la distance du jour", "pct"),
    ("pref_terrain_actuel", "Aptitude au terrain du jour", "pct"),
    ("pref_hippodrome", "Aptitude à l'hippodrome", "pct"),
    ("jockey_forme_30j", "Jockey : réussite sur 30 jours", "pct"),
    ("jockey_taux_place_global", "Jockey : taux de places", "pct"),
    ("entraineur_forme_30j", "Entraîneur : réussite sur 30 jours", "pct"),
    ("entraineur_taux_place", "Entraîneur : taux de places", "pct"),
    ("presse_consensus_score", "Avis de la presse", None),
    ("nb_courses_90j", "Courses disputées sur 90 jours", "nb"),
    ("jours_repos", "Jours depuis sa dernière course", "jours"),
    ("class_drop_ratio_reel", "Niveau de la course face à ses précédentes", None),
    ("valeur_latente", "Valeur latente", None),
]
# Sens par défaut tant qu'aucun cerveau n'a appris le sien (mesuré le 07/10 sur
# 18 255 outsiders : seuls ces trois-là jouent à l'envers).
_SENS_DEFAUT = {"jours_repos": -1, "dyn_reduction_km_moy": -1, "class_drop_ratio_reel": -1}
# Absent = 0 dans le vecteur servi pour ces critères (trot seulement, ou pas de chrono).
_ZERO_ABSENT = {"dyn_reduction_km_moy", "speed_figure_recent", "speed_figure_best"}


def sens_criteres(d: pd.DataFrame, y: np.ndarray) -> dict:
    """+1 si un rang plus haut dans le champ va avec plus de places, −1 sinon."""
    out = {}
    yy = pd.Series(y, index=d.index)
    for nom, _, _ in FICHE:
        col = f"r_{nom}"
        if col not in d:
            continue
        c = d[col].corr(yy, method="spearman")
        if c == c:  # pas NaN
            out[nom] = 1 if c >= 0 else -1
    return out


def _valeur(v: float, fmt: Optional[str]) -> Optional[str]:
    if fmt == "pct":
        return f"{v * 100:.0f} %" if v <= 1.5 else None
    if fmt == "jours":
        return f"{v:.0f} j"
    if fmt in ("nb", "entier"):
        return f"{v:.0f}"
    if fmt == "signe":
        return f"{v:+.0f}"
    return None


_MUSIQUE_RE = re.compile(r"(\d+|[A-Za-z])([a-z])")


def lire_musique(musique) -> tuple[Optional[str], Optional[int], int]:
    """(5 dernières perfs lisibles, nb de podiums dedans, nb lues). PMU : « 1a3a(25)Da… »."""
    if not isinstance(musique, str) or not musique.strip():
        return None, None, 0
    brut = re.sub(r"\(\d+\)", " ", musique)
    perfs = [m.group(1).upper() + m.group(2) for m in _MUSIQUE_RE.finditer(brut)][:5]
    if not perfs:
        return None, None, 0
    podiums = sum(1 for p in perfs if p[:-1].isdigit() and 1 <= int(p[:-1]) <= 3)
    return " ".join(perfs), podiums, len(perfs)


def _eme(p: int) -> str:
    return f"{p}{'er' if p == 1 else 'e'}"


def fiche(row: pd.Series, art: dict) -> dict:
    """Fiche d'analyse d'un outsider : chaque critère avec sa place dans le champ."""
    sens = {**_SENS_DEFAUT, **(art.get("sens") or {})}
    n = int(_f(row, "n_champ") or _f(row, "partants") or 0)
    criteres: list[dict] = []

    def ajoute(libelle, verdict, detail, position=None):
        criteres.append({"libelle": libelle, "verdict": verdict, "detail": detail,
                         "position": position, "sur": n or None})

    perfs, podiums, lues = lire_musique(row.get("musique"))
    if perfs:
        ajoute("Musique (5 dernières)", "favorable" if podiums and podiums >= 2 else
               "defavorable" if lues >= 4 and not podiums else "neutre",
               f"{perfs} — {podiums} podium{'s' if (podiums or 0) > 1 else ''} sur {lues}")

    cote = _f(row, "cote_figee")
    autres = [v for v in (_f(row, c) for c in ("f_cote_betfair_exchange", "f_cote_unibet",
                                               "f_cote_winamax", "f_cote_betclic", "f_cote_bzh"))
              if v and cote and cote * 0.35 <= v]
    if autres and cote:
        meilleur = min(autres)
        ajoute("Cote ailleurs qu'au PMU", "favorable" if meilleur < cote * 0.85 else
               "defavorable" if meilleur > cote * 1.15 else "neutre",
               f"{meilleur:.0f} ailleurs contre {cote:.0f} au PMU")
    prem = _f(row, "cote_premiere")
    if prem and cote and abs(cote / prem - 1) >= 0.1:
        ajoute("Mouvement de cote", "favorable" if cote < prem else "defavorable",
               f"{prem:.0f} → {cote:.0f} depuis le premier pronostic")
    rang = _f(row, "rang_predit")
    if rang and n:
        ajoute("Classement de notre modèle général",
               "favorable" if rang <= max(1, round(n / 3)) else
               "defavorable" if rang > n - n // 3 else "neutre",
               f"{_eme(int(rang))} sur {n}", int(rang))

    for nom, libelle, fmt in FICHE:
        v, r = _f(row, f"f_{nom}"), _f(row, f"r_{nom}")
        if v is None or r is None or not n or (nom in _ZERO_ABSENT and v == 0):
            continue
        rang_bas = max(1, min(n, round(r * n)))              # 1 = plus petite valeur
        position = rang_bas if sens.get(nom, 1) < 0 else n - rang_bas + 1
        tiers = max(1, n // 3)
        verdict = ("favorable" if position <= tiers else
                   "defavorable" if position > n - tiers else "neutre")
        val = _valeur(v, fmt)
        ajoute(libelle, verdict, f"{_eme(position)} sur {n}" + (f" · {val}" if val else ""), position)

    return {
        "lus": len(art.get("colonnes") or []),
        "criteres": criteres,
        "favorables": sum(1 for c in criteres if c["verdict"] == "favorable"),
        "defavorables": sum(1 for c in criteres if c["verdict"] == "defavorable"),
    }


def scorer(d: pd.DataFrame, art: Optional[dict]) -> pd.DataFrame:
    """Chance de place estimée + raisons pour des lignes préparées (≥ 10)."""
    if d.empty:
        return d.assign(chance=[], raisons=[], analyse=[])
    if art is None:
        # Pas de cerveau en service : proba placé du modèle général, jamais affichée
        # comme chance réelle (le module refuse alors de sélectionner, cf. selection).
        return d.assign(chance=np.nan, raisons=[[] for _ in range(len(d))],
                        analyse=[{} for _ in range(len(d))])
    cols = art["colonnes"]
    X = matrice(d, cols)
    p_brain = art["cerveau"].predict_proba(X)[:, 1]
    p_base = art["iso_general"].predict(d["proba_top3"].fillna(0))
    chance = POIDS_CERVEAU * p_brain + (1 - POIDS_CERVEAU) * p_base
    contrib = art["cerveau"].booster_.predict(X, pred_contrib=True)
    n_out = d.groupby("course_id")["course_id"].transform("size").to_numpy()
    rs = [raisons(contrib[i, :-1], cols, d.iloc[i], int(n_out[i])) for i in range(len(d))]
    analyses = [fiche(d.iloc[i], art) for i in range(len(d))]
    return d.assign(chance=chance, raisons=rs, analyse=analyses)


def selection(scored: pd.DataFrame) -> pd.DataFrame:
    """Outsiders retenus : cote ≥ 15, chance ≥ seuil, au plus 2 par course."""
    if scored.empty or scored["chance"].isna().all():
        return scored.iloc[0:0]
    t = scored[(scored["cote_figee"] >= COTE_OUTSIDER_MIN) & (scored["places"] > 0)
               & (scored["chance"] >= SEUIL_A_SUIVRE)]
    t = t.sort_values("chance", ascending=False).groupby("course_id").head(MAX_PAR_COURSE)
    return t.assign(niveau=np.where(t["chance"] >= SEUIL_FORT, "fort", "a_suivre"))


def entrainer_sync() -> None:
    """Point d'entrée RQ (worker) : premier entraînement sans attendre la nuit."""
    import asyncio
    asyncio.run(entrainer_et_valider())
