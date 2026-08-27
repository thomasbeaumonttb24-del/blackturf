"""
Service d'alertes — BlackTurf.
Email (Resend) + Web Push (VAPID) + In-app (WebSocket via Redis).
"""
import json
import os
import uuid
import structlog
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import httpx

from api.config import get_settings
from db.models import User, AlerteLog
from services.email_verification import clause_email_utilisable

settings = get_settings()
log = structlog.get_logger()


# ─────────────────────────────────────────────
# Préférences de notification
# ─────────────────────────────────────────────
# Stockées dans `users.push_subscription["prefs"]` (colonne JSON déjà existante,
# pas de migration). Elles étaient PUREMENT DÉCORATIVES jusqu'au 2026-08-17 :
# l'écran /notifications les écrivait, et AUCUN envoi ne les lisait — un
# utilisateur qui montait son seuil à ★★★★ continuait de recevoir tous les ★★.
PREFS_DEFAUT: dict = {
    "vb_niveau_min": 2,       # ne notifier que les value bets de ce niveau ou plus
    "resultats_suivis": True,  # résultats des courses où l'utilisateur a un pari/une alerte
    "alertes_systeme": True,   # annonces produit, maintenance
}


def prefs_utilisateur(user: User) -> dict:
    """Préférences effectives d'un utilisateur (défauts pour les clés absentes)."""
    brut = (user.push_subscription or {}).get("prefs") or {}
    prefs = dict(PREFS_DEFAUT)
    for k in PREFS_DEFAUT:
        if k in brut and brut[k] is not None:
            prefs[k] = brut[k]
    try:
        prefs["vb_niveau_min"] = max(1, min(4, int(prefs["vb_niveau_min"])))
    except (TypeError, ValueError):
        prefs["vb_niveau_min"] = PREFS_DEFAUT["vb_niveau_min"]
    prefs["resultats_suivis"] = bool(prefs["resultats_suivis"])
    prefs["alertes_systeme"] = bool(prefs["alertes_systeme"])
    return prefs


def _passe_le_seuil(vb: dict, seuil: int) -> bool:
    """Ce value bet doit-il être notifié à un utilisateur dont le seuil est `seuil` ?

    Niveau ABSENT ou illisible → on notifie. Entre taire une alerte et en envoyer
    une de trop, le silence est la faute la plus coûteuse : l'utilisateur ne peut pas
    savoir qu'il n'a pas été prévenu. Seul un niveau EXPLICITE et strictement
    inférieur au seuil filtre.
    """
    brut = vb.get("niveau")
    if brut is None:
        return True
    try:
        return int(brut) >= seuil
    except (TypeError, ValueError):
        return True


def _abonnement_push(user: User) -> Optional[dict]:
    """Objet d'abonnement Web Push SEUL, sans la clé `prefs`.

    `push_subscription` sert de fourre-tout (endpoint + keys + prefs) ; passer le
    dict entier à pywebpush l'expose à une clé qu'il n'attend pas. On isole les
    champs de la spec Push API, et on renvoie None s'il n'y a pas de vrai
    abonnement (un utilisateur peut n'avoir QUE des préférences).
    """
    sub = user.push_subscription or {}
    if not sub.get("endpoint"):
        return None
    return {k: v for k, v in sub.items() if k in ("endpoint", "keys", "expirationTime")}


# ─────────────────────────────────────────────
# Email (Resend)
# ─────────────────────────────────────────────
@dataclass(frozen=True)
class ResultatEnvoi:
    """Issue d'un envoi, avec sa RAISON d'échec.

    Les expéditeurs ne renvoyaient qu'un booléen : la colonne `alertes_log.erreur`
    est donc restée vide sur 115 860 échecs (juin-août 2026), et diagnostiquer la
    panne demandait de relire les logs conteneur — effacés à chaque redémarrage.
    Cet objet reste utilisable comme un booléen (`if ok:`) pour ne rien casser
    chez les appelants, mais transporte de quoi comprendre.
    """
    ok: bool
    erreur: Optional[str] = None

    def __bool__(self) -> bool:
        return self.ok


def _raison(resultat) -> Optional[str]:
    """Raison d'échec d'un envoi, quel que soit le type renvoyé."""
    return getattr(resultat, "erreur", None)


async def send_email(
    to: str,
    subject: str,
    html: str,
    text: Optional[str] = None,
) -> ResultatEnvoi:
    """Envoie un email via Resend API."""
    # Un test ne doit JAMAIS envoyer de vrai e-mail. `backend/.env` porte une
    # `RESEND_API_KEY` valide, que pydantic charge aussi sous pytest : la suite
    # d'abonnements a expédié des dizaines de messages réels à l'exploitant, au
    # nom de comptes fictifs (`6d121afe@blackturf.fr`, `sub_courant`…) — constaté
    # le 2026-08-20.
    #
    # Le garde-fou s'appuie sur `PYTEST_CURRENT_TEST`, posé par pytest pour chaque
    # test, et NON sur `ENVIRONMENT` : la suite tourne aussi dans l'image de prod
    # avec le `.env` de prod, où `ENVIRONMENT` vaut "production" (cf. le
    # neutraliseur d'ambiant dans conftest).
    # L'absence de clé se diagnostique AVANT le blocage de test : sinon un envoi
    # mal configuré rendrait « bloqué sous pytest » au lieu de sa vraie cause, et
    # l'invariant qui exige qu'un échec porte sa raison tomberait.
    if not settings.resend_api_key:
        log.warning("alerts.email.no_api_key")
        return ResultatEnvoi(False, "RESEND_API_KEY absente")

    if "PYTEST_CURRENT_TEST" in os.environ:
        log.info("alerts.email.bloque_en_test", to=to, subject=subject[:80])
        return ResultatEnvoi(False, "envoi bloqué sous pytest")

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
            return ResultatEnvoi(True)
    except Exception as e:
        log.error("alerts.email.failed", to=to, error=str(e))
        return ResultatEnvoi(False, f"{type(e).__name__}: {e}"[:400])


def _digest_email_html(courses: list[dict], unsubscribe_url: str) -> str:
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
  <div style="padding: 16px 20px; text-align: center; font-size: 11px; color: #6b7280;">
    Un seul digest quotidien. <a href="{unsubscribe_url}" style="color: #6b7280; text-decoration: underline;">Se désabonner de ces e-mails</a>.
  </div>
</body>
</html>
"""


# ─────────────────────────────────────────────
# Web Push (VAPID)
# ─────────────────────────────────────────────
async def send_web_push(subscription: dict, title: str, body: str,
                        data: Optional[dict] = None) -> ResultatEnvoi:
    """Envoie une notification Web Push via pywebpush."""
    if not settings.vapid_private_key:
        # Cas réel : 22 345 tentatives, 22 345 échecs, aucune trace — les clés
        # VAPID n'ont jamais été posées en production.
        log.warning("alerts.push.no_vapid_key")
        return ResultatEnvoi(False, "VAPID_PRIVATE_KEY absente")

    try:
        from pywebpush import webpush, WebPushException
        payload = json.dumps({"title": title, "body": body, "data": data or {}})
        webpush(
            subscription_info=subscription,
            data=payload,
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
        )
        return ResultatEnvoi(True)
    except Exception as e:
        log.error("alerts.push.failed", error=str(e))
        return ResultatEnvoi(False, f"{type(e).__name__}: {e}"[:400])


# ─────────────────────────────────────────────
# In-app (WebSocket via Redis)
# ─────────────────────────────────────────────
async def send_inapp(user_id: str, type_alerte: str, payload: dict) -> ResultatEnvoi:
    """Publie une alerte in-app via Redis pour le WS handler.

    Deux corrections par rapport a la version booleenne :

    - la RAISON de l'echec est remontee (la colonne `alertes_log.erreur` restait
      vide sur ce canal, et les logs conteneur disparaissent au redemarrage :
      l'echec du 27/08 06:10 etait indiagnosticable a posteriori) ;
    - une seconde tentative est faite sur socket morte. Le pool est desormais
      controle (`db.redis_client`), mais une connexion peut toujours lacher entre
      le controle et l'envoi : ne pas rejouer, c'est perdre l'alerte pour de bon.
    """
    from db.redis_client import get_redis

    msg = json.dumps({"type": type_alerte, "data": payload,
                      "ts": datetime.now(timezone.utc).isoformat()})
    derniere: Optional[Exception] = None
    for tentative in (1, 2):
        try:
            redis = await get_redis()
            await redis.publish(f"alertes:{user_id}", msg)
            if tentative > 1:
                log.info("alerts.inapp.rejoue_ok", user_id=user_id)
            return ResultatEnvoi(True)
        except Exception as e:  # noqa: BLE001
            derniere = e
            log.warning("alerts.inapp.tentative_echouee", user_id=user_id,
                        tentative=tentative, error=str(e)[:200])
    log.error("alerts.inapp.failed", user_id=user_id, error=str(derniere))
    return ResultatEnvoi(False, f"{type(derniere).__name__}: {derniere}"[:300])


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
        # Les expediteurs renvoient un `ResultatEnvoi` (utilisable comme booleen) :
        # la colonne est un vrai `boolean` Postgres, asyncpg refuse tout autre type.
        envoye=bool(envoye),
        erreur=erreur,
        created_at=datetime.now(timezone.utc),
    )
    session.add(entry)


# ─────────────────────────────────────────────
# API de haut niveau
# ─────────────────────────────────────────────
async def notify_value_bets(
    session: AsyncSession,
    user_ids: list[str],
    value_bets: list[dict],
):
    """
    Notifie un LOT de nouveaux value bets sans e-mail unitaire.

    - un seul message in-app par lot ;
    - un seul push récapitulatif, avec cooldown persistant de 4 heures ;
    - aucun e-mail ici : le digest quotidien `send_morning_digest` est l'unique
      e-mail value bet afin d'éviter tout risque de spam ;
    - le lot est FILTRÉ PAR UTILISATEUR selon `prefs.vb_niveau_min` : chacun reçoit
      exactement les niveaux qu'il a demandés sur /notifications (avant le
      2026-08-17 tout le monde recevait le même lot brut, réglage ignoré).
    """
    # Même signal présent plusieurs fois dans le lot : une seule ligne. La clé ne
    # dépend pas de vb_id (historiquement recréé à chaque recalcul), mais de la
    # course et du partant.
    uniques: dict[str, dict] = {}
    for vb in value_bets:
        key = f"{vb.get('course_id', '')}:{vb.get('participation_id') or vb.get('nom_cheval', '')}"
        uniques[key] = vb
    batch = list(uniques.values())
    if not batch:
        return

    users_res = await session.execute(
        select(User).where(User.user_id.in_(user_ids))
    )
    users = users_res.scalars().all()

    nb_notifies = 0
    for user in users:
        if not user.is_active:
            continue

        prefs = prefs_utilisateur(user)
        seuil = prefs["vb_niveau_min"]
        perso = [vb for vb in batch if _passe_le_seuil(vb, seuil)]
        if not perso:
            continue  # rien à ce niveau pour cet utilisateur : pas de ligne vide en base

        payload = {
            "nb_value_bets": len(perso),
            "value_bets": perso,
            "signal_keys": [
                f"{vb.get('course_id', '')}:{vb.get('participation_id') or vb.get('nom_cheval', '')}"
                for vb in perso
            ],
            "niveau_min": seuil,
        }

        ok_inapp = await send_inapp(user.user_id, "value_bet_digest", payload)
        await _log_alerte(session, user.user_id, "value_bet_digest", "in-app", payload,
                          ok_inapp, _raison(ok_inapp))
        nb_notifies += 1

        # Au plus un push toutes les 4 heures par utilisateur, même après restart.
        abo = _abonnement_push(user)
        if abo:
            recent_push = await session.scalar(
                select(AlerteLog.alerte_id).where(
                    AlerteLog.user_id == user.user_id,
                    AlerteLog.type_alerte == "value_bet_digest",
                    AlerteLog.canal == "push",
                    AlerteLog.envoye == True,
                    AlerteLog.created_at >= datetime.now(timezone.utc) - timedelta(hours=4),
                ).limit(1)
            )
            if not recent_push:
                noms = ", ".join(str(v.get("nom_cheval", "")) for v in perso[:3])
                suffixe = "…" if len(perso) > 3 else ""
                ok_push = await send_web_push(
                    abo,
                    title=f"{len(perso)} value bet{'s' if len(perso) > 1 else ''} détecté{'s' if len(perso) > 1 else ''}",
                    body=f"{noms}{suffixe}",
                    data=payload,
                )
                await _log_alerte(session, user.user_id, "value_bet_digest", "push", payload,
                                  ok_push, _raison(ok_push))

    await session.commit()
    log.info("alerts.notify_value_bets", nb_users=len(users),
             nb_notifies=nb_notifies, nb_value_bets=len(batch))


async def notify_value_bet(
    session: AsyncSession,
    user_ids: list[str],
    vb_data: dict,
):
    """Compatibilité des anciens appelants : passe toujours par le lot anti-spam."""
    await notify_value_bets(session, user_ids, [vb_data])


# ─────────────────────────────────────────────
# Suivi post-course (onglet « Résultats »)
# ─────────────────────────────────────────────
def _position_de(classement, numero: Optional[int]) -> Optional[int]:
    """Place à l'arrivée d'un partant, None s'il n'est pas classé."""
    if not classement or not isinstance(classement, list) or numero is None:
        return None
    for e in classement:
        if isinstance(e, dict) and e.get("numero") == numero:
            p = e.get("position")
            return int(p) if isinstance(p, (int, float)) and p > 0 else None
    return None


def _rapport_gagnant(rapports) -> Optional[float]:
    """Rapport Simple Gagnant RÉELLEMENT publié par le PMU, sinon None (jamais
    d'estimation : un gain affiché doit être un gain payé)."""
    if not isinstance(rapports, dict):
        return None
    for key in ("simple_gagnant", "e_simple_gagnant", "simple_gagnant_international"):
        v = rapports.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
    return None


async def notify_resultats_course(session: AsyncSession, course_id: str) -> dict:
    """Notifie le RÉSULTAT d'une course à ceux qu'elle concerne.

    L'onglet « Résultats » du centre de notifications était structurellement vide :
    aucun code ne produisait d'alerte de type résultat, seuls les value bets en
    créaient. Un utilisateur alerté d'un pari de valeur n'apprenait donc JAMAIS ce
    qu'il était devenu — le suivi s'arrêtait au signal.

    Deux cas, un seul message par utilisateur et par course (le plus pertinent
    d'abord) :
      1. `resultat_pari`        — l'utilisateur a enregistré des paris sur la course
                                  (bankroll_entries réglées) → gagné/perdu + net réel ;
      2. `resultat_value_bet`   — sinon, il avait été alerté d'un value bet sur cette
                                  course → ce que le cheval a fait à l'arrivée.

    Idempotent : rappelée deux fois sur la même course (re-poll des rapports PMU,
    catchup de règlement), elle ne renvoie rien. Respecte `prefs.resultats_suivis`.
    """
    from sqlalchemy import select as _select
    from db.models import (BankrollEntry, Cheval, Course, Participation,
                           Resultat, ValueBet)

    cr = {"paris": 0, "value_bets": 0, "ignores_prefs": 0}

    course = await session.scalar(_select(Course).where(Course.course_id == course_id))
    resultat = await session.scalar(_select(Resultat).where(Resultat.course_id == course_id))
    if not course or not resultat or not resultat.classement:
        return cr  # pas d'arrivée exploitable → rien à annoncer

    classement = resultat.classement
    rapport_gagnant = _rapport_gagnant(resultat.rapports)
    arrivee = " - ".join(
        str(e.get("numero")) for e in sorted(
            (e for e in classement if isinstance(e, dict) and e.get("position")),
            key=lambda e: e["position"],
        )[:5]
    )
    contexte = {
        "course_id": course_id,
        "hippodrome": course.hippodrome_nom,
        "course_nom": course.nom,
        "arrivee": arrivee,
    }

    # Utilisateurs déjà notifiés pour cette course (idempotence) — une seule requête.
    # Bornée à partir de l'heure de départ : un résultat ne peut pas avoir été
    # annoncé avant la course, et sans cette borne on scanne toute la table
    # (200 000+ lignes) à chaque fin de course.
    q_deja = _select(AlerteLog.user_id).where(
        AlerteLog.type_alerte.in_(("resultat_pari", "resultat_value_bet")),
        AlerteLog.canal == "in-app",
        AlerteLog.payload["course_id"].as_string() == course_id,
    )
    if course.date_heure:
        q_deja = q_deja.where(AlerteLog.created_at >= course.date_heure)
    deja = set((await session.execute(q_deja)).scalars().all())

    async def _envoyer(user: User, type_alerte: str, payload: dict, titre: str, corps: str):
        ok = await send_inapp(user.user_id, type_alerte, payload)
        await _log_alerte(session, user.user_id, type_alerte, "in-app", payload,
                          ok, _raison(ok))
        abo = _abonnement_push(user)
        if abo:
            ok_push = await send_web_push(abo, title=titre, body=corps, data=payload)
            await _log_alerte(session, user.user_id, type_alerte, "push", payload,
                                  ok_push, _raison(ok_push))

    # ── 1. Paris personnels réglés ────────────────────────────
    entries = (await session.execute(
        _select(BankrollEntry).where(
            BankrollEntry.course_id == course_id,
            BankrollEntry.resultat.is_not(None),
        )
    )).scalars().all()

    par_user: dict[str, list] = {}
    for e in entries:
        par_user.setdefault(e.user_id, []).append(e)

    traites: set[str] = set(deja)
    for user_id, lot in par_user.items():
        if user_id in traites:
            continue
        user = await session.scalar(_select(User).where(User.user_id == user_id))
        if not user or not user.is_active:
            continue
        if not prefs_utilisateur(user)["resultats_suivis"]:
            cr["ignores_prefs"] += 1
            traites.add(user_id)
            continue

        nb_gagnes = sum(1 for e in lot if e.resultat == "gagne")
        nb_perdus = sum(1 for e in lot if e.resultat == "perd")
        gain_net = round(sum((e.gain_perte or 0.0) for e in lot), 2)
        payload = {
            **contexte,
            "nb_gagnes": nb_gagnes,
            "nb_perdus": nb_perdus,
            "gain_net": gain_net,
            "mise_totale": round(sum(e.mise for e in lot), 2),
        }
        titre = "Pari gagné" if (nb_gagnes and not nb_perdus) else (
            "Pari perdu" if (nb_perdus and not nb_gagnes) else "Paris réglés")
        await _envoyer(user, "resultat_pari", payload, f"🏁 {titre}",
                       f"{course.hippodrome_nom} — {gain_net:+.2f} €")
        traites.add(user_id)
        cr["paris"] += 1

    # Commit AVANT la seconde partie : sans ça, un retour anticipé faute de value
    # bet signalé (`return cr` ci-dessous) perdait les alertes de paris personnels.
    if cr["paris"]:
        await session.commit()

    # ── 2. Sort des value bets signalés ───────────────────────
    vb_rows = (await session.execute(
        _select(ValueBet, Participation, Cheval)
        .join(Participation, Participation.participation_id == ValueBet.participation_id)
        .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
        .where(ValueBet.course_id == course_id, ValueBet.notifie == True)  # noqa: E712
        .order_by(ValueBet.niveau.desc(), ValueBet.ev_max.desc())
    )).all()
    if not vb_rows:
        return cr

    # Value bet le plus PERTINENT à raconter : celui qui a fait la meilleure place
    # (un signal gagnant primant un ★★★★ non placé), sinon le mieux noté.
    candidats = []
    for vb, part, cheval in vb_rows:
        pos = _position_de(classement, part.numero)
        candidats.append({
            "nom_cheval": cheval.nom,
            "numero": part.numero,
            "niveau": vb.niveau,
            "cote": round(part.cote_pmu, 2) if part.cote_pmu else None,
            "ev": round(vb.ev_max, 4) if vb.ev_max is not None else None,
            "position": pos,
        })
    meilleur = sorted(candidats, key=lambda c: (c["position"] or 99, -(c["niveau"] or 0)))[0]

    # Destinataires : les abonnés payants actifs dont le seuil couvre ce niveau —
    # exactement ceux qui ont pu recevoir l'alerte value bet initiale.
    abonnes = (await session.execute(
        _select(User).where(
            User.plan.in_(["starter", "standard", "expert"]),
            User.is_active == True,  # noqa: E712
            # Jamais vers une adresse que personne n'a confirmée : chaque rebond
            # abîme la délivrabilité de TOUS les envois, y compris ceux des vrais
            # abonnés.
            clause_email_utilisable(),
        )
    )).scalars().all()

    for user in abonnes:
        if user.user_id in traites:
            continue
        prefs = prefs_utilisateur(user)
        if not prefs["resultats_suivis"]:
            cr["ignores_prefs"] += 1
            continue
        if int(meilleur["niveau"] or 0) < prefs["vb_niveau_min"]:
            continue  # ne raconter la suite que des signaux qu'il a demandés

        payload = {
            **contexte, **meilleur,
            "rapport_simple_gagnant": rapport_gagnant if meilleur["position"] == 1 else None,
            "nb_value_bets": len(candidats),
        }
        place = ("gagnant" if meilleur["position"] == 1
                 else f"{meilleur['position']}ᵉ" if meilleur["position"] else "non placé")
        await _envoyer(user, "resultat_value_bet", payload,
                       f"🏁 {meilleur['nom_cheval']} : {place}",
                       f"{course.hippodrome_nom} — arrivée {arrivee}")
        cr["value_bets"] += 1

    await session.commit()
    log.info("alerts.notify_resultats_course", course_id=course_id, **cr)
    return cr


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
      <tr><td style="padding: 8px 0; opacity: 0.7;">Rapport officiel pour 10€</td><td style="color: #4ade80; font-weight: bold;">{vb.get('gain_reference_10e', 'N/A')}€ (mise incluse)</td></tr>
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
            clause_email_utilisable(),
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
        await _log_alerte(session, user.user_id, "weekly_best_vb", "email", best,
                          ok_email, _raison(ok_email))

        if user.push_subscription:
            ok_push = await send_web_push(
                user.push_subscription,
                title="🏇 Meilleur pari de la semaine",
                body=f"{best['nom_cheval']} gagnant à {best.get('cote', '?')} — rapport officiel pour 10€ : {best.get('gain_reference_10e', '?')}€ (mise incluse)",
                data=best,
            )
            await _log_alerte(session, user.user_id, "weekly_best_vb", "push", best,
                              ok_push, _raison(ok_push))

    await session.commit()
    log.info("alerts.weekly_best_vb", nb_users=len(users), course_id=best["course_id"], cheval=best["nom_cheval"])


async def send_morning_digest(session: AsyncSession):
    """
    Digest matinal — envoyé aux abonnés actifs.
    Recense les value bets du jour.
    """
    from db.models import ValueBet, Course, Participation, Cheval

    now_utc = datetime.now(timezone.utc)
    now_paris = now_utc.astimezone(ZoneInfo("Europe/Paris"))
    start_paris = now_paris.replace(hour=0, minute=0, second=0, microsecond=0)
    end_paris = start_paris + timedelta(days=1)
    start_utc = start_paris.astimezone(timezone.utc)
    end_utc = end_paris.astimezone(timezone.utc)
    q = (
        select(ValueBet, Participation, Cheval, Course)
        .join(Participation, Participation.participation_id == ValueBet.participation_id)
        .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
        .join(Course, Course.course_id == ValueBet.course_id)
        .where(
            Course.date_heure >= start_utc,
            Course.date_heure < end_utc,
            Course.date_heure > now_utc,
            ValueBet.actif == True,
        )
        .order_by(ValueBet.ev_max.desc())
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
        select(User).where(
            User.plan.in_(["starter", "standard", "expert"]),
            User.is_active == True,
            User.marketing_opt_out_at.is_(None),
            clause_email_utilisable(),
        )
    )
    users = users_res.scalars().all()

    for user in users:
        # Idempotence persistante : un redémarrage ou un lancement manuel le même
        # jour ne doit jamais produire un second digest.
        deja_envoye = await session.scalar(
            select(AlerteLog.alerte_id).where(
                AlerteLog.user_id == user.user_id,
                AlerteLog.type_alerte == "digest_matin",
                AlerteLog.canal == "email",
                AlerteLog.envoye == True,
                AlerteLog.created_at >= start_utc,
                AlerteLog.created_at < end_utc,
            ).limit(1)
        )
        if deja_envoye:
            continue
        html = _digest_email_html(courses_list, _unsubscribe_url(user.user_id))
        ok = await send_email(
            to=user.email,
            subject=f"🏇 BlackTurf — {len(courses_list)} value bets aujourd'hui",
            html=html,
        )
        await _log_alerte(session, user.user_id, "digest_matin", "email",
                          {"nb_vb": len(courses_list)}, ok, _raison(ok))

    await session.commit()
    log.info("alerts.morning_digest", nb_users=len(users), nb_vb=len(courses_list))
