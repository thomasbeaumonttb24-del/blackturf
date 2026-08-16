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
        if user.plan in ("starter", "standard", "expert"):
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


# ─────────────────────────────────────────────
# Désabonnement e-mails marketing (RGPD)
# ─────────────────────────────────────────────
# Un e-mail non transactionnel DOIT porter un lien de désinscription réel. On
# signe un jeton dédié (audience "unsub") avec la clé de l'app : il permet le
# désabonnement EN UN CLIC, sans login (contrainte RGPD : ne pas exiger la
# création/récupération d'un compte pour exercer le droit d'opposition). Le
# jeton ne donne AUCUN autre droit que de poser l'opt-out marketing.
UNSUB_AUDIENCE = "unsub"


def make_unsubscribe_token(user_id: str) -> str:
    """Jeton de désabonnement signé, valable 90 jours (durée de vie d'un e-mail
    archivé dans une boîte). Audience dédiée → inutilisable comme jeton d'accès."""
    from jose import jwt as _jwt
    from datetime import timedelta as _td
    payload = {
        "sub": user_id,
        "aud": UNSUB_AUDIENCE,
        "exp": datetime.now(timezone.utc) + _td(days=90),
    }
    return _jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def read_unsubscribe_token(token: str) -> Optional[str]:
    """user_id si le jeton est valide et d'audience `unsub`, sinon None.
    L'audience est VÉRIFIÉE : un access_token ne doit jamais servir ici, et
    réciproquement ce jeton ne doit jamais ouvrir de session."""
    from jose import jwt as _jwt, JWTError as _JWTError
    try:
        payload = _jwt.decode(
            token, settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            audience=UNSUB_AUDIENCE,
        )
    except _JWTError:
        return None
    if payload.get("aud") != UNSUB_AUDIENCE:
        return None
    return payload.get("sub")


def _unsubscribe_url(user_id: str) -> str:
    return f"https://blackturf.fr/desabonnement?token={make_unsubscribe_token(user_id)}"


# Mention légale jeu responsable — identique au reste du site (footer, page tarifs).
JEU_RESPONSABLE_TXT = (
    "Le jeu peut créer une dépendance. Interdit aux mineurs. Jouez de façon responsable — "
    "joueurs-info-service.fr — 09 74 75 13 13."
)


def _winner_entry(classement) -> Optional[dict]:
    """Entrée du VAINQUEUR (position == 1) dans un classement JSON, robuste à
    l'ordre du tableau — `classement[0]` n'est PAS garanti être le 1er. Même
    logique que `_winner_entry` dans api/routes/stats.py (dupliquée ici, pure et
    minuscule, pour éviter un import routes→services)."""
    if not classement or not isinstance(classement, list):
        return None
    best = None
    best_pos = None
    for e in classement:
        if not isinstance(e, dict):
            continue
        p = e.get("position")
        if not isinstance(p, (int, float)):
            continue
        if best_pos is None or p < best_pos:
            best_pos, best = int(p), e
    return best


async def _best_value_bet_last_week(session: AsyncSession) -> Optional[dict]:
    """Meilleur value bet RÉEL des 7 derniers jours : niveau ≥3, GAGNANT
    (comparé au classement officiel), avec un rapport PMU Simple Gagnant
    RÉELLEMENT publié (jamais de gain approximé). Classé par EV décroissant —
    on renvoie le premier candidat valide, donc le plus haut EV parmi les
    gagnants réglés. None si aucun candidat honnête sur la période (le job
    appelant doit alors ne rien envoyer, pas inventer un exemple)."""
    from datetime import timedelta
    from sqlalchemy import select as _select
    from db.models import ValueBet, Participation, Cheval, Course, Resultat, Prediction

    since = datetime.now(timezone.utc) - timedelta(days=7)
    rows = (await session.execute(
        _select(ValueBet, Participation, Cheval, Course, Resultat, Prediction)
        .join(Participation, Participation.participation_id == ValueBet.participation_id)
        .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
        .join(Course, Course.course_id == ValueBet.course_id)
        .outerjoin(Resultat, Resultat.course_id == ValueBet.course_id)
        .outerjoin(Prediction, Prediction.prediction_id == ValueBet.prediction_id)
        .where(
            ValueBet.niveau >= 3,
            Course.statut == "termine",
            Course.date_heure >= since,
            # Garde anti-backfill (même principe que _vb_flat_backtest dans
            # stats.py) : le value bet doit avoir été détecté AVANT le départ,
            # sinon c'est un pari reconstruit a posteriori sur un résultat connu.
            ValueBet.detecte_a < Course.date_heure,
        )
        .order_by(ValueBet.ev_max.desc())
        .limit(200)
    )).all()

    for vb, part, cheval, course, resultat, pred in rows:
        if not resultat or not resultat.classement:
            continue
        winner = _winner_entry(resultat.classement)
        if not winner or winner.get("numero") != part.numero:
            continue  # ce value bet n'a pas gagné
        rapport = None
        if resultat.rapports:
            for key in ("simple_gagnant", "e_simple_gagnant", "simple_gagnant_international"):
                v = resultat.rapports.get(key)
                if v is not None:
                    rapport = float(v)
                    break
        if rapport is None:
            continue  # pas de rapport publié → pas de gain calculable honnêtement
        cote = pred.cote_figee if (pred and pred.cote_figee and pred.cote_figee > 1) else part.cote_pmu
        return {
            "course_id": course.course_id,
            "nom_cheval": cheval.nom,
            "numero": part.numero,
            "hippodrome_nom": course.hippodrome_nom,
            "date_heure": course.date_heure.isoformat() if course.date_heure else None,
            "cote": round(cote, 2) if cote else None,
            "ev": round(vb.ev_max, 4),
            "niveau": vb.niveau,
            "rapport_simple_gagnant": round(rapport, 2),
            "gain_reference_10e": round(10 * rapport, 2),
        }
    return None


def _weekly_best_vb_email_html(vb: dict, unsubscribe_url: str) -> str:
    """Template email hebdo — UN SEUL exemple réel, pas une moyenne enjolivée.
    Porte les deux mentions obligatoires : lien de désinscription (RGPD, e-mail
    non transactionnel) et numéro national jeu responsable."""
    etoiles = "⭐" * vb["niveau"]
    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
  <div style="background: #1a1a2e; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
    <h1 style="margin: 0; font-size: 24px;">🏇 BlackTurf</h1>
    <p style="margin: 5px 0 0; opacity: 0.7;">Le meilleur pari de valeur de la semaine</p>
  </div>
  <div style="background: #0f3460; color: white; padding: 20px; border-radius: 0 0 8px 8px;">
    <h2 style="color: #4ade80;">{etoiles} {vb['nom_cheval']} — gagnant à la cote {vb.get('cote', 'N/A')}</h2>
    <table style="width: 100%; border-collapse: collapse;">
      <tr><td style="padding: 8px 0; opacity: 0.7;">Hippodrome</td><td style="font-weight: bold;">{vb.get('hippodrome_nom', 'N/A')}</td></tr>
      <tr><td style="padding: 8px 0; opacity: 0.7;">Cote au départ</td><td>{vb.get('cote', 'N/A')}</td></tr>
      <tr><td style="padding: 8px 0; opacity: 0.7;">EV détecté</td><td style="color: #4ade80;">+{round(vb.get('ev', 0) * 100, 1)}%</td></tr>
      <tr><td style="padding: 8px 0; opacity: 0.7;">Un Simple Gagnant 10€</td><td style="color: #4ade80; font-weight: bold;">aurait rapporté {vb.get('gain_reference_10e', 'N/A')}€</td></tr>
    </table>
    <p style="margin-top: 20px; padding: 15px; background: rgba(255,255,255,0.1); border-radius: 6px; font-size: 12px; opacity: 0.7;">
      Un seul exemple réel de la semaine passée — pas une moyenne, pas une promesse de gain futur.
      BlackTurf est un outil d'aide à la décision et ne garantit aucun gain.
      ⚠️ {JEU_RESPONSABLE_TXT}
    </p>
    <a href="https://blackturf.fr/tarifs" style="display: block; text-align: center; margin-top: 15px; padding: 12px 24px; background: #e94560; color: white; text-decoration: none; border-radius: 6px;">
      Voir les paris de valeur en direct — passer Standard →
    </a>
  </div>
  <div style="padding: 16px 20px; text-align: center; font-size: 11px; color: #6b7280;">
    Vous recevez cet e-mail parce que vous avez un compte gratuit BlackTurf.
    <a href="{unsubscribe_url}" style="color: #6b7280; text-decoration: underline;">Se désabonner de ces e-mails</a>
    — désinscription immédiate, en un clic.
  </div>
</body>
</html>
"""


async def send_weekly_best_value_bet(session: AsyncSession):
    """
    Job hebdomadaire (funnel conversion Free, décision produit 2026-08-16) :
    identifie le meilleur value bet RÉEL de la semaine passée (EV le plus haut
    parmi les value bets ★★★+ réglés ET gagnants, rapport PMU publié) et
    l'envoie par email + push aux comptes Free/Découverte, avec CTA d'abonnement.

    Honnêteté stricte : si aucun value bet ★★★+ n'a gagné la semaine passée (ou
    qu'aucun rapport n'est encore publié), on N'ENVOIE RIEN plutôt que d'inventer
    un exemple ou de lisser sur une moyenne."""
    best = await _best_value_bet_last_week(session)
    if not best:
        log.info("alerts.weekly_best_vb.no_candidate")
        return

    # RGPD : on EXCLUT à l'envoi les comptes qui se sont désabonnés des e-mails
    # marketing (le lien de désinscription du mail précédent doit être réellement
    # honoré — un opt-out non appliqué vaut absence de lien).
    users_res = await session.execute(
        select(User).where(
            User.plan.in_(["free", "decouverte"]),
            User.is_active == True,
            User.marketing_opt_out_at.is_(None),
        )
    )
    users = users_res.scalars().all()
    if not users:
        log.info("alerts.weekly_best_vb.no_recipients")
        return

    subject = f"🏇 Le meilleur pari de la semaine : {best['nom_cheval']} à {best.get('cote', '?')}"
    for user in users:
        # Le lien de désabonnement est PAR destinataire (jeton signé) → le HTML
        # est rendu par utilisateur, pas mutualisé.
        html = _weekly_best_vb_email_html(best, _unsubscribe_url(user.user_id))
        ok_email = await send_email(to=user.email, subject=subject, html=html)
        await _log_alerte(session, user.user_id, "weekly_best_vb", "email", best, ok_email)

        if user.push_subscription:
            ok_push = await send_web_push(
                user.push_subscription,
                title="🏇 Meilleur pari de la semaine",
                body=f"{best['nom_cheval']} gagnant à {best.get('cote', '?')} — un 10€ aurait rapporté {best.get('gain_reference_10e', '?')}€",
                data=best,
            )
            await _log_alerte(session, user.user_id, "weekly_best_vb", "push", best, ok_push)

    await session.commit()
    log.info("alerts.weekly_best_vb", nb_users=len(users), course_id=best["course_id"], cheval=best["nom_cheval"])


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
        select(User).where(User.plan.in_(["starter", "standard", "expert"]), User.is_active == True)
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
