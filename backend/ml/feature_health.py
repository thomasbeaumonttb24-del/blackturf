"""
feature_health.py — Détection des features MORTES / CONSTANTES (scraper cassé).

Le détecteur de drift (drift_detector.py) surveille la PERFORMANCE (Brier/ADWIN)
mais PAS la distribution des features. Une feature qui devient constante ou nulle
(source de scrape morte → valeur par défaut figée, ex. Turfoo 403 → taux=0.12 pour
tous) n'est jamais alertée : variance nulle ⇒ les arbres ne splittent jamais dessus
(impact 0) MAIS le DÉFAUT trompeur (même valeur partout) se présente comme un faux
signal uniforme.

Ce module échantillonne les features_ml pré-départ récentes et calcule, par feature
numérique : taux de NULL/absent, variance, nb de valeurs distinctes. Il FLAGGE les
features « mortes » (null_rate élevé OU variance ~0 OU ≤1 valeur distincte), journalise
et persiste un snapshot (table feature_health). `get_dead_features()` expose la liste
pour exclusion OPTIONNELLE au retrain (par défaut on LOGGE seulement, on n'exclut pas
automatiquement → pas de surprise silencieuse sur le modèle ; règle no-fake-data).
"""
from __future__ import annotations

import json
import math
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

# Seuils de déclaration « feature morte ». Conservateurs : on ne flagge que le franchement
# dégénéré (sinon faux positifs sur des features légitimement rares comme jument_pleine).
NULL_RATE_DEAD = 0.95      # ≥95% de valeurs manquantes/NULL → morte
DISTINCT_DEAD = 1          # ≤1 valeur distincte (présente) → constante
VAR_EPS = 1e-9            # variance sous ce seuil = constante numérique
SAMPLE_LIMIT = 40000      # plafond de lignes échantillonnées (mémoire bornée)
# Clés non-features (méta) à ignorer dans le scan.
_META_KEYS = {
    "participation_id", "course_id", "numero", "cheval_id", "position",
    "y_top3", "y_win", "date_heure",
}


async def compute_feature_health(session: AsyncSession, jours: int = 45) -> dict:
    """Scanne les features_ml pré-départ des `jours` derniers jours. Retourne un dict
    {n_rows, n_features, dead: [...], stats: {feat: {null_rate, distinct, var}}}."""
    rows = (await session.execute(text("""
        SELECT fm.features
        FROM features_ml fm
        JOIN participations pa ON pa.participation_id = fm.participation_id
        JOIN courses c ON c.course_id = pa.course_id
        WHERE c.date_heure IS NOT NULL
          AND fm.computed_at < c.date_heure
          AND c.date_heure >= now() - (:j || ' days')::interval
        ORDER BY c.date_heure DESC
        LIMIT :lim
    """), {"j": jours, "lim": SAMPLE_LIMIT})).fetchall()

    data = [(f if isinstance(f, dict) else json.loads(f)) for (f,) in rows]
    n = len(data)
    if n < 200:
        return {"n_rows": n, "insufficient": True}

    # Inventaire des clés numériques.
    keys: set[str] = set()
    for d in data:
        keys.update(d.keys())
    keys -= _META_KEYS

    stats: dict[str, dict] = {}
    dead: list[str] = []
    for k in sorted(keys):
        present = 0
        seen: set = set()
        s = s2 = 0.0
        numeric = True
        for d in data:
            v = d.get(k, None)
            if v is None:
                continue
            present += 1
            if len(seen) <= 12:
                seen.add(v)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                numeric = False
            else:
                s += v
                s2 += v * v
        null_rate = round(1.0 - present / n, 4)
        distinct = len(seen)
        var = None
        if numeric and present > 1:
            mean = s / present
            var = max(0.0, s2 / present - mean * mean)
        is_dead = (
            null_rate >= NULL_RATE_DEAD
            or distinct <= DISTINCT_DEAD
            or (var is not None and var < VAR_EPS)
        )
        stats[k] = {
            "null_rate": null_rate,
            "distinct": distinct,
            "var": (round(var, 9) if var is not None else None),
            "dead": is_dead,
        }
        if is_dead:
            dead.append(k)

    snap = {"n_rows": n, "n_features": len(keys), "n_dead": len(dead),
            "dead": dead, "stats": stats, "jours": jours}
    return snap


async def persist_feature_health(session: AsyncSession, snap: dict) -> None:
    if snap.get("insufficient"):
        return
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS feature_health (
            id BIGSERIAL PRIMARY KEY,
            data JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    await session.execute(text("INSERT INTO feature_health (data) VALUES (:d)"),
                          {"d": json.dumps(snap)})
    await session.commit()


async def get_dead_features(session: AsyncSession) -> list[str]:
    """Liste des features mortes du dernier snapshot (pour exclusion optionnelle au
    retrain). Vide si aucun snapshot. Lecture seule, jamais bloquante."""
    try:
        r = (await session.execute(text(
            "SELECT data FROM feature_health ORDER BY created_at DESC LIMIT 1"))).first()
        if not r:
            return []
        return list((r[0] or {}).get("dead", []))
    except Exception:
        return []
