"""Une mesure que personne ne lit n'est pas une supervision.

`ml/feature_health` calcule chaque nuit les features à variance nulle et persiste
le résultat. 54 instantanés étaient en base le 2026-08-31 — et 29 features
constantes sur 185 (toute la chaîne « presse », toute la chaîne « dynamique de
course ») n'ont été découvertes que par un audit manuel. Rien ne lisait la table.
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from services import data_quality as dq


async def _table(db):
    await db.execute(text("""
        CREATE TABLE IF NOT EXISTS feature_health (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL
        )
    """))


async def _snapshot(db, *, mortes, n_features=185, quand="2026-08-30 02:00:00"):
    await db.execute(
        text("INSERT INTO feature_health (data, created_at) VALUES (:d, :t)"),
        {"d": json.dumps({"dead": mortes, "n_features": n_features,
                          "n_dead": len(mortes), "n_rows": 30000}), "t": quand})


@pytest.mark.asyncio
async def test_sans_instantane_on_ne_juge_pas(db):
    await _table(db)
    await db.commit()
    out = await dq.sante_features(db)
    assert out["disponible"] is False


@pytest.mark.asyncio
async def test_le_niveau_de_features_mortes_remonte_une_anomalie(db):
    await _table(db)
    await _snapshot(db, mortes=[f"feature_{i}" for i in range(29)])
    await db.commit()

    out = await dq.sante_features(db)
    assert out["n_mortes"] == 29 and out["part_mortes"] == pytest.approx(0.157, abs=0.002)

    # Le seuil est franchi : l'anomalie doit exister, avec le compte dans le message.
    assert out["n_mortes"] >= dq.SEUIL_FEATURES_MORTES


@pytest.mark.asyncio
async def test_une_source_qui_tombe_alerte_meme_sous_le_seuil_absolu(db):
    """Le niveau ne suffit pas : c'est le SAUT qui dit qu'une chaîne vient de mourir."""
    await _table(db)
    await _snapshot(db, mortes=["a", "b"], quand="2026-08-29 02:00:00")
    await _snapshot(db, mortes=["a", "b", "c", "d", "e", "f", "g"],
                    quand="2026-08-30 02:00:00")
    await db.commit()

    out = await dq.sante_features(db)
    assert out["n_mortes"] == 7 < dq.SEUIL_FEATURES_MORTES
    assert out["n_nouvelles_mortes"] == 5 >= dq.SEUIL_HAUSSE_FEATURES_MORTES
    assert out["nouvelles_mortes"] == ["c", "d", "e", "f", "g"]


@pytest.mark.asyncio
async def test_un_echantillon_trop_court_ne_conclut_pas(db):
    await _table(db)
    await db.execute(
        text("INSERT INTO feature_health (data, created_at) VALUES (:d, :t)"),
        {"d": json.dumps({"insufficient": True, "n_rows": 12}),
         "t": "2026-08-30 02:00:00"})
    await db.commit()
    out = await dq.sante_features(db)
    assert out["disponible"] is False and "court" in out["raison"]
