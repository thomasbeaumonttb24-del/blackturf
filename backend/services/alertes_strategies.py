"""Alertes e-mail des stratégies (plan Expert).

Une stratégie (table `strategies`) décrit des critères de course (`filtres`) et de
signal (`indicateurs`). Quand `alerte_email` est coché, l'utilisateur reçoit un
e-mail dès qu'un pari de valeur visible correspond à au moins une de ses
stratégies.

Règles anti-spam, dans cet ordre :
  - au plus UN e-mail toutes les 4 heures par utilisateur (même délai que le push
    récapitulatif de `services.alerts.notify_value_bets`) ;
  - un même signal (course + partant) n'est jamais envoyé deux fois ;
  - aucun signal n'est perdu pendant le délai : chaque passage relit TOUS les
    paris visibles à venir, pas seulement les nouveaux, et envoie ceux qui n'ont
    pas encore fait l'objet d'un e-mail dès que le délai est écoulé ;
  - envoi idempotent via `email_campaigns.deliver` (table `email_livraisons`,
    clé d'idempotence Resend) : une reprise après erreur ne double jamais un mail.

Garde-fous : plan Expert (seul plan qui a accès aux stratégies), compte actif,
adresse utilisable (`clause_email_utilisable`), pas d'opposition marketing, même
visibilité que la page Value bets pour ce plan (`valuebets_visibilite.filtres_sql`),
et même interrupteur que les lettres (`EMAIL_EDITORIAL_ENABLED`).
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select

from db.models import AlerteLog, Cheval, Course, Participation, Prediction, Strategie, User, ValueBet
from services.email_verification import clause_email_utilisable
from services.valuebets_visibilite import filtres_sql

log = structlog.get_logger()
PARIS = ZoneInfo("Europe/Paris")

PLAN_STRATEGIES = "expert"
DELAI_ENTRE_EMAILS = timedelta(hours=4)
TYPE_ALERTE = "strategie_email"
MAX_SIGNAUX_PAR_EMAIL = 12


def cle_signal(course_id: str, participation_id: str) -> str:
    return f"{course_id}:{participation_id}"


def _egal(a, b) -> bool:
    return str(a or "").strip().lower() == str(b or "").strip().lower()


def correspond(filtres: Optional[dict], indicateurs: Optional[dict], *, course, vb, pred, cheval) -> bool:
    """Le pari de valeur `vb` satisfait-il la stratégie ?

    Critère absent = pas de contrainte. `ev_min` porte sur l'espérance du pari de
    valeur (`ev_max`, celle affichée sur le site) ; `niveau_vb_min` sur ses étoiles ;
    `proba_top3_min` et `confidence_min` sur la prédiction du partant ; `elo_min`
    sur l'ELO global du cheval. Une valeur manquante côté données ne satisfait
    jamais un minimum demandé.
    """
    f = filtres or {}
    i = indicateurs or {}

    if f.get("discipline") and not _egal(f["discipline"], course.discipline):
        return False
    if f.get("hippodrome") and not _egal(f["hippodrome"], course.hippodrome_nom):
        return False
    if f.get("niveau_course") and not _egal(f["niveau_course"], course.niveau_course):
        return False
    if f.get("terrain") and not _egal(f["terrain"], course.terrain_officiel):
        return False
    if f.get("est_quinte") and not course.est_quinte:
        return False
    for cle, valeur, sens in (
        ("distance_min", course.distance, 1), ("distance_max", course.distance, -1),
        ("nb_partants_min", course.nb_partants, 1), ("nb_partants_max", course.nb_partants, -1),
    ):
        borne = f.get(cle)
        if borne is None:
            continue
        if valeur is None or (valeur - borne) * sens < 0:
            return False

    def minimum(cle: str, valeur) -> bool:
        borne = i.get(cle)
        return borne is None or (valeur is not None and valeur >= borne)

    return (
        minimum("ev_min", vb.ev_max)
        and minimum("niveau_vb_min", vb.niveau)
        and minimum("proba_top3_min", getattr(pred, "proba_top3", None))
        and minimum("confidence_min", getattr(pred, "confidence_score", None))
        and minimum("elo_min", getattr(cheval, "elo_score_global", None))
    )


def _utc(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


async def _deja_envoyes(session, user_id: str, depuis: datetime) -> tuple[set[str], Optional[datetime]]:
    """Signaux déjà envoyés à cet utilisateur et date du dernier envoi."""
    rows = (await session.execute(
        select(AlerteLog.payload, AlerteLog.created_at).where(
            AlerteLog.user_id == user_id,
            AlerteLog.type_alerte == TYPE_ALERTE,
            AlerteLog.canal == "email",
            AlerteLog.envoye == True,  # noqa: E712
            AlerteLog.created_at >= depuis,
        )
    )).all()
    cles: set[str] = set()
    dernier = None
    for payload, cree in rows:
        cles.update((payload or {}).get("signal_keys") or [])
        if cree is not None and (dernier is None or _utc(cree) > dernier):
            dernier = _utc(cree)
    return cles, dernier


def _item(vb, part, cheval, course, noms: Iterable[str]) -> dict:
    return {
        "course_id": course.course_id,
        "heure": _utc(course.date_heure).astimezone(PARIS).strftime("%H:%M"),
        "hippodrome": course.hippodrome_nom,
        "course_nom": course.nom, "reunion": course.numero_reunion, "course_num": course.numero,
        "nom_cheval": cheval.nom, "numero": part.numero,
        "ev": float(vb.ev_max), "niveau": vb.niveau, "cote": part.cote_pmu,
        "casaque_url": part.casaque_image_url,
        "strategies": sorted(set(noms)),
    }


async def envoyer_alertes_strategies(session, now: Optional[datetime] = None) -> int:
    """Un passage : un e-mail récapitulatif par utilisateur concerné. Renvoie le
    nombre d'e-mails effectivement partis."""
    from services.email_campaigns import deliver, editorial_enabled
    from services.alerts import _unsubscribe_url, make_unsubscribe_token
    from services.email_templates import alertes_strategies as gabarit, SITE

    if not editorial_enabled():
        return 0
    now = now or datetime.now(timezone.utc)

    strategies = (await session.execute(
        select(Strategie, User).join(User, User.user_id == Strategie.user_id).where(
            Strategie.alerte_email == True,  # noqa: E712
            User.plan == PLAN_STRATEGIES,
            User.is_active == True,  # noqa: E712
            User.marketing_opt_out_at.is_(None),
            clause_email_utilisable(),
        )
    )).all()
    if not strategies:
        return 0
    par_user: dict[str, tuple[User, list[Strategie]]] = {}
    for strat, user in strategies:
        par_user.setdefault(user.user_id, (user, []))[1].append(strat)

    # Paris visibles pour un Expert, départ encore à venir, partant maintenu.
    lignes = (await session.execute(
        select(ValueBet, Participation, Cheval, Course, Prediction)
        .join(Participation, Participation.participation_id == ValueBet.participation_id)
        .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
        .join(Course, Course.course_id == ValueBet.course_id)
        .outerjoin(Prediction, Prediction.prediction_id == ValueBet.prediction_id)
        .where(*filtres_sql(PLAN_STRATEGIES, now), Course.date_heure > now,
               Participation.non_partant == False)  # noqa: E712
        .order_by(Course.date_heure, ValueBet.ev_max.desc())
    )).all()
    if not lignes:
        return 0

    envoyes = 0
    for user_id, (user, strats) in par_user.items():
        deja, dernier = await _deja_envoyes(session, user_id, now - timedelta(days=2))
        if dernier is not None and now - dernier < DELAI_ENTRE_EMAILS:
            continue  # délai en cours : les signaux attendent le prochain passage

        items, cles = [], []
        for vb, part, cheval, course, pred in lignes:
            cle = cle_signal(course.course_id, part.participation_id)
            if cle in deja or cle in cles:
                continue
            noms = [s.nom for s in strats
                    if correspond(s.filtres, s.indicateurs, course=course, vb=vb, pred=pred, cheval=cheval)]
            if noms:
                items.append(_item(vb, part, cheval, course, noms))
                cles.append(cle)
        if not items:
            continue
        items, cles = items[:MAX_SIGNAUX_PAR_EMAIL], cles[:MAX_SIGNAUX_PAR_EMAIL]

        desabo = _unsubscribe_url(user_id)
        html, texte = gabarit(items, desabo)
        n = len(items)
        sujet = f"BlackTurf — {n} signal{'aux' if n > 1 else ''} pour vos stratégies"
        # Campagne propre à CET ensemble de signaux : une reprise ne double rien,
        # et un nouvel ensemble plus tard fait un nouvel e-mail.
        # 16 car. : « strategie- » (10) + UUID (36) + « - » + 16 = 63 ≤ String(64) de
        # email_livraisons.campagne (à 20, 67 car. : INSERT refusé, aucun e-mail parti).
        empreinte = hashlib.sha256("|".join(sorted(cles)).encode()).hexdigest()[:16]
        oneclick = f"{SITE}/api/v1/newsletter/desabonnement-compte?jeton={make_unsubscribe_token(user_id)}"
        if await deliver(session, f"strategie-{user_id}-{empreinte}", user.email, sujet, html, texte,
                         oneclick, now, journal={"signal_keys": cles, "nb": n}):
            envoyes += 1
    log.info("alertes_strategies.passage", utilisateurs=len(par_user), envoyes=envoyes)
    return envoyes
