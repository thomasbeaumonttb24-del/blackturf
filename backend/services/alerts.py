"""
Service d'alertes — BlackTurf.
Email (Resend) + Web Push (VAPID) + In-app (WebSocket via Redis).
"""
import json
import uuid
import structlog
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import httpx

from api.config import get_settings
from db.models import User, AlerteLog

settings = get_settings()
log = structlog.get_logger()


# ─────────────────────────────────────────────
# Email (Resend)
# ─────────────────────────────────────────────
async def send_email(
    to: str,
    subject: str,
    html: str,
    text: Optional[str] = None,
) -> bool:
    """Envoie un email via Resend API."""
    if not settings.resend_api_key:
        log.warning("alerts.email.no_api_key")
        return False

    payload = {
        "from": f"{settings.email_from_name} <{settings.email_from}>",
        "to": [to],
        "subject": subject,
        "html": html,
    }
    if text:
        payload["text"] = text

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                json=payload,
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            )
            resp.raise_for_status()
            return True
    except Exception as e:
        log.error("alerts.email.failed", to=to, error=str(e))
        return False


def _value_bet_email_html(vb: dict) -> str:
    """Template email value bet."""
    etoiles = "⭐" * vb["niveau"]
    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
  <div style="background: #1a1a2e; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
    <h1 style="margin: 0; font-size: 24px;">🏇 BlackTurf</h1>
    <p style="margin: 5px 0 0; opacity: 0.7;">Le Terminal IA des Parieurs Gagnants</p>
  </div>
  <div style="background: #0f3460; color: white; padding: 20px; border-radius: 0 0 8px 8px;">
    <h2 style="color: #e94560;">Value Bet détecté {etoiles}</h2>
    <table style="width: 100%; border-collapse: collapse;">
      <tr><td style="padding: 8px 0; opacity: 0.7;">Cheval</td><td style="font-weight: bold;">{vb.get('nom_cheval', 'N/A')}</td></tr>
      <tr><td style="padding: 8px 0; opacity: 0.7;">Hippodrome</td><td>{vb.get('hippodrome', 'N/A')}</td></tr>
      <tr><td style="padding: 8px 0; opacity: 0.7;">Cote</td><td>{vb.get('cote', 'N/A')}</td></tr>
      <tr><td style="padding: 8px 0; opacity: 0.7;">EV</td><td style="color: #4ade80;">+{round(vb.get('ev', 0) * 100, 1)}%</td></tr>
    </table>
    <p style="margin-top: 20px; padding: 15px; background: rgba(255,255,255,0.1); border-radius: 6px; font-size: 12px; opacity: 0.7;">
      ⚠️ Le jeu doit rester un plaisir. Jouez de façon responsable. BlackTurf ne garantit aucun gain.
      Interdiction de participer aux jeux d'argent aux mineurs.
    </p>
    <a href="https://blackturf.fr/programme" style="display: block; text-align: center; margin-top: 15px; padding: 12px 24px; background: #e94560; color: white; text-decoration: none; border-radius: 6px;">
      Voir sur BlackTurf →
    </a>
  </div>
</body>
</html>
"""


def _digest_email_html(courses: list[dict]) -> str:
    """Template digest matinal."""
    rows = ""
    for c in courses:
        rows += f"""
    <tr style="border-bottom: 1px solid rgba(255,255,255,0.1);">
      <td style="padding: 10px 8px;">{c.get('heure', '')}</td>
      <td style="padding: 10px 8px; font-weight: bold;">{c.get('hippodrome', '')}</td>
      <td style="padding: 10px 8px;">{c.get('nom_cheval', '')} (N°{c.get('numero', '')})</td>
      <td style="padding: 10px 8px; color: #4ade80;">+{round(c.get('ev', 0)*100, 1)}%</td>
      <td style="padding: 10px 8px;">{"⭐" * c.get('niveau', 1)}</td>
    </tr>"""

    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; max-width: 700px; margin: 0 auto; padding: 20px;">
  <div style="background: #1a1a2e; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
    <h1 style="margin: 0;">🏇 BlackTurf — Digest du jour</h1>
  </div>
  <div style="background: #0f3460; color: white; padding: 20px; border-radius: 0 0 8px 8px;">
    <h2>Value Bets du jour ({len(courses)} détectés)</h2>
    <table style="width: 100%; border-collapse: collapse;">
      <thead>
        <tr style="opacity: 0.6; font-size: 12px; text-transform: uppercase;">
          <th style="padding: 8px; text-align: left;">Heure</th>
          <th style="padding: 8px; text-align: left;">Hippodrome</th>
          <th style="padding: 8px; text-align: left;">Cheval</th>
          <th style="padding: 8px; text-align: left;">EV</th>
          <th style="padding: 8px; text-align: left;">Niveau</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
    <p style="margin-top: 20px; font-size: 12px; opacity: 0.5;">
      ⚠️ Jouez de façon responsable. BlackTurf est un outil d'aide à la décision, pas une garantie de gain.
    </p>
    <a href="https://blackturf.fr/programme" style="display: block; text-align: center; margin-top: 15px; padding: 12px; background: #e94560; color: white; text-decoration: none; border-radius: 6px;">
      Voir le programme complet →
    </a>
  </div>
</body>
</html>
"""


# ─────────────────────────────────────────────
# Web Push (VAPID)
# ─────────────────────────────────────────────
async def send_web_push(subscription: dict, title: str, body: str, data: Optional[dict] = None) -> bool:
    """Envoie une notification Web Push via pywebpush."""
    if not settings.vapid_private_key:
        return False

    try:
        from pywebpush import webpush, WebPushException
        payload = json.dumps({"title": title, "body": body, "data": data or {}})
        webpush(
            subscription_info=subscription,
            data=payload,
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
        )
        return True
    except Exception as e:
        log.error("alerts.push.failed", error=str(e))
        return False


# ─────────────────────────────────────────────
# In-app (WebSocket via Redis)
# ─────────────────────────────────────────────
async def send_inapp(user_id: str, type_alerte: str, payload: dict) -> bool:
    """Publie une alerte in-app via Redis pour le WS handler."""
    try:
        from db.redis_client import get_redis
        redis = await get_redis()
        msg = json.dumps({"type": type_alerte, "data": payload, "ts": datetime.now(timezone.utc).isoformat()})
        await redis.publish(f"alertes:{user_id}", msg)
        return True
    except Exception as e:
        log.error("alerts.inapp.failed", user_id=user_id, error=str(e))
        return False


# ─────────────────────────────────────────────
# Log en DB
# ─────────────────────────────────────────────
async def _log_alerte(
    session: AsyncSession,
    user_id: Optional[str],
    type_alerte: str,
    canal: str,
    payload: dict,
    envoye: bool,
    erreur: Optional[str] = None,
):
    entry = AlerteLog(
        alerte_id=str(uuid.uuid4()),
        user_id=user_id,
        type_alerte=type_alerte,
        canal=canal,
        payload=payload,
        envoye=envoye,
        erreur=erreur,
        created_at=datetime.now(timezone.utc),
    )
    session.add(entry)


# ─────────────────────────────────────────────
# API de haut niveau
# ─────────────────────────────────────────────
async def notify_value_bet(
    session: AsyncSession,
    user_ids: list[str],
    vb_data: dict,
):
    """
    Notifie les utilisateurs d'un nouveau value bet.
    Canaux : in-app + email (si starter/pro) + push (si souscrit).
    """
    users_res = await session.execute(
        select(User).where(User.user_id.in_(user_ids))
    )
    users = users_res.scalars().all()

    for user in users:
        if not user.is_active:
            continue

        # In-app (tous)
        ok_inapp = await send_inapp(user.user_id, "value_bet", vb_data)
        await _log_alerte(session, user.user_id, "value_bet", "in-app", vb_data, ok_inapp)

        # Email (starter+)
        if user.plan in ("starter", "standard", "pro", "expert"):
            html = _value_bet_email_html(vb_data)
            ok_email = await send_email(
                to=user.email,
                subject=f"🏇 Value Bet détecté — {vb_data.get('nom_cheval', '')}",
                html=html,
            )
            await _log_alerte(session, user.user_id, "value_bet", "email", vb_data, ok_email)

        # Push (si souscrit)
        if user.push_subscription:
            etoiles = "⭐" * vb_data.get("niveau", 1)
            ok_push = await send_web_push(
                user.push_subscription,
                title=f"Value Bet {etoiles}",
                body=f"{vb_data.get('nom_cheval')} — EV +{round(vb_data.get('ev', 0)*100, 1)}%",
                data=vb_data,
            )
            await _log_alerte(session, user.user_id, "value_bet", "push", vb_data, ok_push)

    await session.commit()
    log.info("alerts.notify_value_bet", nb_users=len(users))


async def send_morning_digest(session: AsyncSession):
    """
    Digest matinal — envoyé aux abonnés actifs.
    Recense les value bets du jour.
    """
    from datetime import date
    from db.models import ValueBet, Course, Participation, Cheval

    today = date.today()
    q = (
        select(ValueBet, Participation, Cheval, Course)
        .join(Participation, Participation.participation_id == ValueBet.participation_id)
        .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
        .join(Course, Course.course_id == ValueBet.course_id)
        .where(
            Course.date_heure >= datetime.combine(today, datetime.min.time()),
            ValueBet.actif == True,
        )
        .order_by(ValueBet.ev_max.desc())
        .limit(20)
    )
    rows = (await session.execute(q)).all()
    if not rows:
        return

    courses_list = [
        {
            "heure": course.date_heure.strftime("%H:%M"),
            "hippodrome": course.hippodrome_nom,
            "nom_cheval": cheval.nom,
            "numero": part.numero,
            "ev": vb.ev_max,
            "niveau": vb.niveau,
        }
        for vb, part, cheval, course in rows
    ]

    # Utilisateurs abonnés
    users_res = await session.execute(
        select(User).where(User.plan.in_(["starter", "standard", "pro", "expert"]), User.is_active == True)
    )
    users = users_res.scalars().all()

    html = _digest_email_html(courses_list)
    for user in users:
        ok = await send_email(
            to=user.email,
            subject=f"🏇 BlackTurf — {len(courses_list)} value bets aujourd'hui",
            html=html,
        )
        await _log_alerte(session, user.user_id, "digest_matin", "email", {"nb_vb": len(courses_list)}, ok)

    await session.commit()
    log.info("alerts.morning_digest", nb_users=len(users), nb_vb=len(courses_list))
