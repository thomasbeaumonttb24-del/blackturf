"""
Communauté — salon de discussion entre membres connectés (/chat).

Écriture par REST : validation, anti-flood et rafraîchissement de session passent
par le client axios comme partout ailleurs. Diffusion en direct par Redis pub/sub
vers `/ws/chat` (ws.py). L'API tourne sur DEUX workers uvicorn : une liste de
sockets en mémoire ne joindrait que la moitié du salon, d'où le passage par Redis.

Accès : tout compte connecté (gratuit compris) — un salon vide ne crée aucun lien.
Écrire exige un pseudo et une adresse confirmée. La modération (suppression,
bannissement, signalements) est réservée à l'admin.
"""
import json
import re
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from api.routes.auth import get_current_user, require_admin
from db import redis_client
from db.database import get_db
from db.models import User, ChatMessage, ChatSignalement, gen_uuid
from services.email_verification import email_confirme

log = structlog.get_logger()
router = APIRouter()

CANAL_SALON = "chat:salon"
LONGUEUR_MAX = 500
INTERVALLE_MIN_S = 2
PLANS_ABONNES = ("starter", "standard", "expert")

# Règles du pseudo (format, mots réservés, unicité) : services/pseudo.py, communes
# à l'inscription, au profil et au salon.


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def _role(user: User) -> str:
    if user.is_admin:
        return "admin"
    if user.plan in PLANS_ABONNES:
        return "abonne"
    return "membre"


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    # SQLite (tests) rend des datetimes naïfs malgré timezone=True.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _serialiser(msg: ChatMessage, auteur: User) -> dict:
    return {
        "message_id": msg.message_id,
        "contenu": msg.contenu,
        "created_at": _iso(msg.created_at),
        "auteur": {
            "user_id": auteur.user_id,
            "pseudo": auteur.pseudo or "Membre",
            "role": _role(auteur),
        },
    }


def _nettoyer(texte: str) -> str:
    # Caractères de contrôle retirés (sauf saut de ligne), pas plus de deux sauts
    # de ligne d'affilée : un message ne doit pas pouvoir occuper tout l'écran.
    texte = re.sub(r"[\x00-\x09\x0b-\x1f\x7f]", "", texte.replace("\r\n", "\n"))
    return re.sub(r"\n{3,}", "\n\n", texte).strip()


def _exiger_non_banni(user: User) -> None:
    if user.chat_banni_at is not None:
        raise HTTPException(
            status_code=403,
            detail="Votre accès à la communauté a été suspendu par la modération.",
        )


async def publier(evenement: dict) -> None:
    """Diffuse un évènement à tous les sockets du salon, sur tous les workers.

    Un échec Redis ne fait pas échouer l'écriture : le message est en base et
    apparaîtra au prochain chargement de l'historique.
    """
    try:
        redis = await redis_client.get_redis()
        await redis.publish(CANAL_SALON, json.dumps(evenement))
    except Exception as e:  # noqa: BLE001
        log.error("chat.publish_failed", type=evenement.get("type"), error=str(e))


async def signaler_aux_barres_de_navigation(auteur_id: str) -> None:
    """Fait monter la bulle « non lus » sur TOUTES les pages, en direct.

    La barre de navigation écoute déjà `/ws/user/alertes` : on y passe plutôt que
    d'ouvrir une socket du salon sur chaque page (qui fausserait aussi le nombre de
    présents). Aucun contenu dans la trame — un banni ne lit rien par ce biais.
    """
    try:
        redis = await redis_client.get_redis()
        await redis.publish("alertes:broadcast", json.dumps({"type": "chat_message", "auteur_id": auteur_id}))
    except Exception as e:  # noqa: BLE001
        log.warning("chat.bulle_publish_failed", error=str(e))


async def _creneau_libre(user_id: str) -> bool:
    """Un message toutes les INTERVALLE_MIN_S secondes par compte (fail-open)."""
    try:
        redis = await redis_client.get_redis()
        return bool(await redis.set(f"chat:rl:{user_id}", "1", nx=True, ex=INTERVALLE_MIN_S))
    except Exception:  # noqa: BLE001
        return True


# ─────────────────────────────────────────────
# Membre
# ─────────────────────────────────────────────
class PseudoIn(BaseModel):
    pseudo: str = Field(min_length=1, max_length=40)


class MessageIn(BaseModel):
    contenu: str = Field(min_length=1, max_length=2000)


class SignalementIn(BaseModel):
    motif: Optional[str] = Field(default=None, max_length=200)


@router.get("/chat/moi")
async def chat_moi(user: User = Depends(get_current_user)):
    return {
        "user_id": user.user_id,
        "pseudo": user.pseudo,
        "banni": user.chat_banni_at is not None,
        "email_confirme": email_confirme(user),
        "is_admin": bool(user.is_admin),
    }


@router.get("/chat/non-lus")
async def compter_non_lus(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Messages des AUTRES membres postés depuis la dernière lecture du salon.

    Jamais ouvert : on compte depuis la création du compte — un membre existant voit
    ce qui s'est dit, un nouvel inscrit ne reçoit pas tout l'historique d'un coup.
    """
    if user.chat_banni_at is not None:
        return {"non_lus": 0}
    repere = await db.scalar(select(User.chat_lu_at).where(User.user_id == user.user_id))
    if repere is None:
        repere = user.created_at
    q = select(func.count(ChatMessage.message_id)).where(
        ChatMessage.supprime_at.is_(None),
        ChatMessage.user_id != user.user_id,
    )
    if repere is not None:
        q = q.where(ChatMessage.created_at > repere)
    return {"non_lus": int(await db.scalar(q) or 0)}


@router.post("/chat/lu", status_code=204)
async def marquer_lu(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        update(User).where(User.user_id == user.user_id).values(chat_lu_at=datetime.now(timezone.utc))
    )
    await db.commit()
    return Response(status_code=204)


@router.put("/chat/pseudo")
async def choisir_pseudo(
    body: PseudoIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from services.pseudo import PseudoRefuse, normaliser, verifier_disponible
    try:
        pseudo = normaliser(body.pseudo, admin=bool(user.is_admin))
        await verifier_disponible(db, pseudo, user.user_id)
    except PseudoRefuse as e:
        raise HTTPException(status_code=e.code, detail=str(e))

    user.pseudo = pseudo
    try:
        await db.commit()
    except IntegrityError:
        # Course entre deux membres qui choisissent le même pseudo au même instant :
        # l'index unique sur lower(pseudo) tranche.
        await db.rollback()
        raise HTTPException(status_code=409, detail="Ce pseudo est déjà pris.")
    return {"pseudo": pseudo}


@router.get("/chat/messages")
async def lister_messages(
    avant: Optional[datetime] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _exiger_non_banni(user)
    q = (
        select(ChatMessage, User)
        .join(User, User.user_id == ChatMessage.user_id)
        .where(ChatMessage.supprime_at.is_(None))
    )
    if avant is not None:
        q = q.where(ChatMessage.created_at < avant)
    rows = (await db.execute(q.order_by(ChatMessage.created_at.desc()).limit(limit + 1))).all()
    plus_anciens = len(rows) > limit
    rows = rows[:limit]
    return {
        "messages": [_serialiser(m, u) for m, u in reversed(rows)],
        "plus_anciens": plus_anciens,
    }


@router.post("/chat/messages")
async def envoyer_message(
    body: MessageIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _exiger_non_banni(user)
    if not user.pseudo:
        raise HTTPException(status_code=409, detail="Choisissez un pseudo avant d'écrire.")
    if not email_confirme(user):
        raise HTTPException(
            status_code=403,
            detail="Confirmez votre adresse e-mail pour écrire dans la communauté.",
        )
    contenu = _nettoyer(body.contenu)
    if not contenu:
        raise HTTPException(status_code=422, detail="Message vide.")
    if len(contenu) > LONGUEUR_MAX:
        raise HTTPException(status_code=422, detail=f"{LONGUEUR_MAX} caractères maximum.")
    if not user.is_admin and not await _creneau_libre(user.user_id):
        raise HTTPException(
            status_code=429,
            detail=f"Doucement : un message toutes les {INTERVALLE_MIN_S} secondes.",
        )

    msg = ChatMessage(
        message_id=gen_uuid(),
        user_id=user.user_id,
        contenu=contenu,
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg)
    # Sérialisé AVANT le commit : les attributs expirent ensuite, et les relire
    # hors greenlet lèverait en asynchrone.
    payload = _serialiser(msg, user)
    await db.commit()

    await publier({"type": "message", "message": payload})
    await signaler_aux_barres_de_navigation(payload["auteur"]["user_id"])
    return payload


@router.delete("/chat/messages/{message_id}", status_code=204)
async def supprimer_message(
    message_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    msg = await db.get(ChatMessage, message_id)
    if not msg or msg.supprime_at is not None:
        raise HTTPException(status_code=404, detail="Message introuvable.")
    if msg.user_id != user.user_id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Vous ne pouvez supprimer que vos messages.")

    maintenant = datetime.now(timezone.utc)
    msg.supprime_at = maintenant
    msg.supprime_par = user.user_id
    # Un message retiré n'a plus de signalement en attente.
    await db.execute(
        update(ChatSignalement)
        .where(ChatSignalement.message_id == message_id, ChatSignalement.traite_at.is_(None))
        .values(traite_at=maintenant)
    )
    await db.commit()
    await publier({"type": "suppression", "message_ids": [message_id]})
    return Response(status_code=204)


@router.post("/chat/messages/{message_id}/signaler", status_code=204)
async def signaler_message(
    message_id: str,
    body: SignalementIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _exiger_non_banni(user)
    msg = await db.get(ChatMessage, message_id)
    if not msg or msg.supprime_at is not None:
        raise HTTPException(status_code=404, detail="Message introuvable.")
    if msg.user_id == user.user_id:
        raise HTTPException(status_code=422, detail="Vous ne pouvez pas signaler votre propre message.")

    deja = await db.scalar(
        select(ChatSignalement.signalement_id).where(
            ChatSignalement.message_id == message_id,
            ChatSignalement.user_id == user.user_id,
        )
    )
    if not deja:
        db.add(ChatSignalement(
            signalement_id=gen_uuid(),
            message_id=message_id,
            user_id=user.user_id,
            motif=(body.motif or "").strip() or None,
            created_at=datetime.now(timezone.utc),
        ))
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
        log.info("chat.signalement", message_id=message_id, par=user.user_id)
    return Response(status_code=204)


# ─────────────────────────────────────────────
# Modération (admin)
# ─────────────────────────────────────────────
class BannissementIn(BaseModel):
    banni: bool
    effacer_messages: bool = False


@router.get("/chat/moderation/signalements")
async def lister_signalements(
    _=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    Auteur = aliased(User)
    Signaleur = aliased(User)
    rows = (await db.execute(
        select(ChatSignalement, ChatMessage, Auteur, Signaleur.pseudo, Signaleur.email)
        .join(ChatMessage, ChatMessage.message_id == ChatSignalement.message_id)
        .join(Auteur, Auteur.user_id == ChatMessage.user_id)
        .join(Signaleur, Signaleur.user_id == ChatSignalement.user_id)
        .where(ChatSignalement.traite_at.is_(None))
        .order_by(ChatSignalement.created_at.desc())
        .limit(200)
    )).all()
    return {
        "signalements": [
            {
                "signalement_id": s.signalement_id,
                "motif": s.motif,
                "created_at": _iso(s.created_at),
                "signale_par": pseudo_sig or email_sig,
                "message": _serialiser(m, auteur),
                "auteur_banni": auteur.chat_banni_at is not None,
            }
            for s, m, auteur, pseudo_sig, email_sig in rows
        ]
    }


@router.post("/chat/moderation/signalements/{signalement_id}/classer", status_code=204)
async def classer_signalement(
    signalement_id: str,
    _=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    s = await db.get(ChatSignalement, signalement_id)
    if not s:
        raise HTTPException(status_code=404, detail="Signalement introuvable.")
    s.traite_at = datetime.now(timezone.utc)
    await db.commit()
    return Response(status_code=204)


@router.get("/chat/moderation/bannis")
async def lister_bannis(
    _=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(User.user_id, User.pseudo, User.email, User.chat_banni_at)
        .where(User.chat_banni_at.is_not(None))
        .order_by(User.chat_banni_at.desc())
    )).all()
    return {
        "bannis": [
            {"user_id": uid, "pseudo": pseudo, "email": email, "banni_at": _iso(at)}
            for uid, pseudo, email, at in rows
        ]
    }


@router.put("/chat/moderation/bannis/{user_id}")
async def bannir(
    user_id: str,
    body: BannissementIn,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    cible = await db.get(User, user_id)
    if not cible:
        raise HTTPException(status_code=404, detail="Membre introuvable.")
    if body.banni and cible.is_admin:
        raise HTTPException(status_code=422, detail="Un administrateur ne peut pas être banni.")

    maintenant = datetime.now(timezone.utc)
    cible.chat_banni_at = maintenant if body.banni else None
    effaces: list[str] = []
    if body.banni:
        if body.effacer_messages:
            effaces = list((await db.execute(
                select(ChatMessage.message_id).where(
                    ChatMessage.user_id == user_id, ChatMessage.supprime_at.is_(None)
                )
            )).scalars().all())
            if effaces:
                await db.execute(
                    update(ChatMessage)
                    .where(ChatMessage.message_id.in_(effaces))
                    .values(supprime_at=maintenant, supprime_par=admin.user_id)
                )
        # Les signalements visant ce membre sont réglés par le bannissement.
        await db.execute(
            update(ChatSignalement)
            .where(
                ChatSignalement.traite_at.is_(None),
                ChatSignalement.message_id.in_(
                    select(ChatMessage.message_id).where(ChatMessage.user_id == user_id)
                ),
            )
            .values(traite_at=maintenant)
        )
    await db.commit()
    log.info("chat.bannissement", user_id=user_id, banni=body.banni, effaces=len(effaces))

    if body.banni:
        # Coupe les sockets ouvertes du membre (ws.py) ; retire ses messages à l'écran.
        await publier({"type": "bannissement", "user_id": user_id})
        if effaces:
            await publier({"type": "suppression", "message_ids": effaces})
    return {"user_id": user_id, "banni": body.banni, "messages_effaces": len(effaces)}
