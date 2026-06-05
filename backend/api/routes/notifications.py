"""
Notifications — BlackTurf.
Centre de gestion des alertes utilisateur.
GET /notifications          — liste des AlerteLog (last 50, paginée)
PUT /notifications/{id}/lue — marquer comme lue
DELETE /notifications/all   — tout marquer lu
GET /notifications/prefs    — préférences push
PUT /notifications/prefs    — mettre à jour préférences push
"""
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.auth import get_current_user
from db.database import get_db
from db.models import AlerteLog, User

log = structlog.get_logger()
router = APIRouter()


# ─── schemas ───────────────────────────────────────────────────

class PrefsUpdate(BaseModel):
    vb_niveau_min: int | None = None          # 1/2/3/4
    resultats_suivis: bool | None = None
    alertes_systeme: bool | None = None


# ─── helpers ───────────────────────────────────────────────────

def _alerte_dict(a: AlerteLog) -> dict[str, Any]:
    payload = a.payload or {}
    return {
        "alerte_id": a.alerte_id,
        "type_alerte": a.type_alerte,
        "canal": a.canal,
        "lue": a.lue,
        "envoye": a.envoye,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        # fields extracted from payload
        "titre": payload.get("titre") or payload.get("title") or a.type_alerte,
        "description": payload.get("description") or payload.get("body") or "",
        "course_id": payload.get("course_id"),
        "cheval": payload.get("cheval") or payload.get("nom_cheval"),
        "niveau": payload.get("niveau"),
    }


# ─── routes ────────────────────────────────────────────────────

@router.get("/count-unread")
async def count_unread(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Nombre de notifications non lues (pour le badge navbar)."""
    rows = (await db.execute(
        select(AlerteLog)
        .where(
            AlerteLog.user_id == current_user.user_id,
            AlerteLog.lue == False,  # noqa: E712
        )
    )).scalars().all()
    return {"count": len(rows)}


@router.get("/")
async def list_notifications(
    page: int = 1,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Liste des alertes de l'utilisateur (dernières 50, paginées)."""
    offset = (page - 1) * limit
    rows = (await db.execute(
        select(AlerteLog)
        .where(AlerteLog.user_id == current_user.user_id)
        .order_by(AlerteLog.created_at.desc())
        .offset(offset)
        .limit(limit)
    )).scalars().all()

    # Unread count
    total_unread = (await db.execute(
        select(AlerteLog)
        .where(
            AlerteLog.user_id == current_user.user_id,
            AlerteLog.lue == False,  # noqa: E712
        )
    )).scalars().all()

    return {
        "items": [_alerte_dict(a) for a in rows],
        "total_unread": len(total_unread),
        "page": page,
        "limit": limit,
    }


@router.put("/{alerte_id}/lue")
async def mark_read(
    alerte_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Marquer une notification comme lue."""
    row = (await db.execute(
        select(AlerteLog).where(
            AlerteLog.alerte_id == alerte_id,
            AlerteLog.user_id == current_user.user_id,
        )
    )).scalar_one_or_none()

    if not row:
        raise HTTPException(status_code=404, detail="Notification introuvable")

    row.lue = True
    await db.commit()
    return {"ok": True}


@router.delete("/all")
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Marquer toutes les notifications comme lues."""
    await db.execute(
        update(AlerteLog)
        .where(
            AlerteLog.user_id == current_user.user_id,
            AlerteLog.lue == False,  # noqa: E712
        )
        .values(lue=True)
    )
    await db.commit()
    return {"ok": True}


@router.get("/prefs")
async def get_prefs(
    current_user: User = Depends(get_current_user),
):
    """Préférences de notifications push (stockées dans user.push_subscription JSON)."""
    push_sub = current_user.push_subscription or {}
    prefs = push_sub.get("prefs", {})
    return {
        "vb_niveau_min": prefs.get("vb_niveau_min", 2),
        "resultats_suivis": prefs.get("resultats_suivis", True),
        "alertes_systeme": prefs.get("alertes_systeme", True),
    }


@router.put("/prefs")
async def update_prefs(
    body: PrefsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mettre à jour les préférences de notifications push."""
    push_sub = current_user.push_subscription or {}
    prefs = push_sub.get("prefs", {})

    if body.vb_niveau_min is not None:
        if body.vb_niveau_min not in (1, 2, 3, 4):
            raise HTTPException(status_code=422, detail="vb_niveau_min doit être entre 1 et 4")
        prefs["vb_niveau_min"] = body.vb_niveau_min
    if body.resultats_suivis is not None:
        prefs["resultats_suivis"] = body.resultats_suivis
    if body.alertes_systeme is not None:
        prefs["alertes_systeme"] = body.alertes_systeme

    push_sub["prefs"] = prefs
    current_user.push_subscription = push_sub
    db.add(current_user)
    await db.commit()
    return prefs
