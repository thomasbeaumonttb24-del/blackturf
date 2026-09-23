"""Scheduled editorial email. Fail closed on incomplete financial evidence."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from sqlalchemy import bindparam, select, text, func
import structlog

from db.models import (EmailEdition, EmailLivraison, NewsletterAbonne, User,
                       Course, ValueBet, Participation, Cheval, Resultat, PredictionSnapshot)
from services.bet_plan_snapshots import CTE_PLAN_PUBLIE
from services.email_templates import daily, weekly, SITE
from services.email_verification import clause_email_utilisable
from services.valuebets_visibilite import filtres_sql

PARIS = ZoneInfo("Europe/Paris")
PROFILS = {"conservateur": "Prudent", "equilibre": "Modéré", "agressif": "Risqué"}
log = structlog.get_logger()


def utc(dt):
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def money(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("Montant absent ou invalide") from None
    if not result.is_finite():
        raise ValueError("Montant non fini")
    return result.quantize(Decimal("0.01"))


def period(now):
    end = now.astimezone(PARIS).replace(hour=0, minute=0, second=0, microsecond=0)
    end -= timedelta(days=end.weekday())
    return end - timedelta(days=7), end


async def insert_once(session, model, values):
    # Unique primary keys serialize creation; subsequent processing locks the row.
    if session.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    await session.execute(insert(model).values(**values).on_conflict_do_nothing())
    await session.commit()


async def weekly_algorithm_numbers(session, start, end):
    """Compare the last complete live pre-race ranking with the official winner."""
    races = (await session.execute(select(Course.course_id, Course.date_heure, Resultat.classement)
        .join(Resultat, Resultat.course_id == Course.course_id)
        .where(Course.date_heure >= start.astimezone(timezone.utc),
               Course.date_heure < end.astimezone(timezone.utc), Course.statut == "termine"))).all()
    eligible = {}
    for course_id, departure, classement in races:
        winners = []
        for row in classement or []:
            try:
                if int(row.get("position")) == 1:
                    winners.append(int(row["numero"]))
            except (TypeError, ValueError, KeyError, AttributeError):
                continue
        if len(winners) == 1:
            eligible[course_id] = (utc(departure), winners[0])
    if not eligible:
        return {"courses": 0, "gagnant_top3": 0, "premier_gagnant": 0}
    snapshots = (await session.execute(select(
        PredictionSnapshot.course_id, PredictionSnapshot.prediction_run_id,
        PredictionSnapshot.observed_at, PredictionSnapshot.rang_predit,
        Participation.numero, Participation.non_partant)
        .join(Participation, Participation.participation_id == PredictionSnapshot.participation_id)
        .where(PredictionSnapshot.course_id.in_(eligible),
               PredictionSnapshot.is_pre_course == True,
               PredictionSnapshot.is_replayable == True,
               PredictionSnapshot.origin == "live"))).all()
    runs = {}
    for course_id, run_id, observed, rank, numero, non_partant in snapshots:
        if utc(observed) >= eligible[course_id][0]:
            continue
        run = runs.setdefault(course_id, {}).setdefault(run_id, {"observed": utc(observed), "ranks": {}})
        run["observed"] = max(run["observed"], utc(observed))
        if rank in (1, 2, 3) and not non_partant:
            run["ranks"].setdefault(rank, []).append(numero)
    metrics = {"courses": 0, "gagnant_top3": 0, "premier_gagnant": 0}
    for course_id, by_run in runs.items():
        latest = max(by_run.values(), key=lambda row: row["observed"])
        ranks = latest["ranks"]
        if set(ranks) != {1, 2, 3} or any(len(values) != 1 for values in ranks.values()):
            continue
        predicted = [ranks[rank][0] for rank in (1, 2, 3)]
        if len(set(predicted)) != 3:
            continue
        winner = eligible[course_id][1]
        metrics["courses"] += 1
        metrics["gagnant_top3"] += int(winner in predicted)
        metrics["premier_gagnant"] += int(winner == predicted[0])
    return metrics


async def build_week(session, now):
    start, end = period(now)
    days = [(start + timedelta(days=i)).strftime("%d%m%Y") for i in range(7)]
    query = text("WITH " + CTE_PLAN_PUBLIE + """
        SELECT d.course_id, d.profil, d.emitted_at, c.date_heure,
               c.hippodrome_nom, c.numero_reunion, c.numero,
               p.montant_mise, p.montant_retour, p.net, p.bilan
        FROM dernier_plan_du_jour d
        JOIN courses c ON c.course_id = d.course_id
        LEFT JOIN plan_publie p ON p.course_id=d.course_id AND p.profil=d.profil
    """).bindparams(bindparam("jours", expanding=True))
    rows = (await session.execute(query, {"jours": days})).mappings().all()
    if not rows:
        return None
    totals = {p: {"label": label, "n": 0, "mise": Decimal(0), "retour": Decimal(0), "net": Decimal(0)} for p, label in PROFILS.items()}
    plans = []
    for r in rows:
        # Do not publish a partial week, silently remove a losing plan, or fall
        # back to an earlier winning snapshot when the latest is still pending.
        if r["montant_mise"] is None:
            log.warning("newsletter.semaine_incomplete", periode=start.date().isoformat(), course_id=r["course_id"])
            return None
        emitted = r["emitted_at"]
        departure = r["date_heure"]
        if isinstance(emitted, str):
            emitted = datetime.fromisoformat(emitted)
        if isinstance(departure, str):
            departure = datetime.fromisoformat(departure)
        if not departure or utc(emitted) >= utc(departure):
            raise ValueError("Plan sans preuve pré-course")
        if r["profil"] not in totals:
            raise ValueError("Profil inconnu")
        bilan = r["bilan"] if isinstance(r["bilan"], dict) else json.loads(r["bilan"] or "{}")
        if any(bilan.get(flag) for flag in ("en_attente", "provisoire", "gain_indetermine", "nb_en_attente")):
            return None
        stake, returned, net = (money(r[k]) for k in ("montant_mise", "montant_retour", "net"))
        if stake < 0 or returned < 0 or returned - stake != net:
            raise ValueError("Règlement incohérent : mise / retour / net")
        for key, value in (("total_mise", stake), ("total_gain", returned), ("net", net)):
            if money(bilan.get(key)) != value:
                raise ValueError("Le bilan ne correspond pas aux montants réglés")
        agg = totals[r["profil"]]
        agg["n"] += 1
        for key, value in (("mise", stake), ("retour", returned), ("net", net)):
            agg[key] += value
        if net > 0:
            plans.append({"course_id": r["course_id"], "profil": PROFILS[r["profil"]],
                          "date": utc(departure).astimezone(PARIS).strftime("%d/%m à %H:%M"),
                          "hippodrome": r["hippodrome_nom"],
                          "code": f"R{r['numero_reunion']}C{r['numero']}" if r["numero_reunion"] else f"Course {r['numero']}",
                          "mise": float(stake), "retour": float(returned), "net": float(net)})
    plans.sort(key=lambda x: (-x["net"], x["course_id"], x["profil"]))
    algo = await weekly_algorithm_numbers(session, start, end)
    return {"debut": start.strftime("%d/%m/%Y"), "fin": (end - timedelta(days=1)).strftime("%d/%m/%Y"),
            "periode": start.date().isoformat(), "top": plans[:3],
            "algo": algo,
            "profils": [{k: float(v) if isinstance(v, Decimal) else v for k, v in p.items()}
                        for p in totals.values() if p["n"]]}


async def deliver(session, campaign, email, subject, html, plain, unsubscribe, now):
    from services.alerts import send_email
    address = email.strip().lower()
    suppressed = await session.scalar(select(EmailLivraison.cle).where(
        EmailLivraison.email == address, EmailLivraison.statut.in_(["bounced", "complained"])).limit(1))
    if suppressed:
        return False
    key = hashlib.sha256(f"{campaign}:{address}".encode()).hexdigest()
    await insert_once(session, EmailLivraison, {
        "cle": key, "campagne": campaign, "email": address, "statut": "pending", "created_at": now,
        "requete": {"to": address, "subject": subject, "html": html, "text": plain,
                    "unsubscribe_url": unsubscribe, "idempotency_key": key},
    })
    row = (await session.execute(select(EmailLivraison).where(EmailLivraison.cle == key)
                                .with_for_update(skip_locked=True)
                                .execution_options(populate_existing=True))).scalar_one_or_none()
    if row is None:
        await session.commit()
        return False
    if row.statut != "pending":
        await session.commit()
        return False  # already handled, not an additional successful delivery
    # Resend retains idempotency keys for 24h. An ambiguous old request must not
    # be resubmitted after expiry, otherwise a timeout can cause duplicate mail.
    if now - utc(row.created_at) > timedelta(hours=23):
        row.statut = "review"
        row.erreur = "Délai de reprise dépassé : vérifier chez Resend avant toute relance."
        await session.commit()
        return False
    result = await send_email(**row.requete)
    if result:
        row.statut = "sent"
        row.envoye_at = now
        row.provider_id = getattr(result, "provider_id", None)
        row.erreur = None
    else:
        row.erreur = getattr(result, "erreur", "Échec fournisseur")
    from services.alerts import _log_alerte
    user_id = await session.scalar(select(User.user_id).where(func.lower(User.email) == address))
    await _log_alerte(session, user_id, "digest_matin" if campaign.startswith("jour-") else "weekly_best_vb",
                      "email", {"campagne": campaign}, result, row.erreur)
    await session.commit()
    return bool(result)


async def send_weekly(session, now=None):
    from services.alerts import prefs_utilisateur, _unsubscribe_url, make_unsubscribe_token
    now = now or datetime.now(timezone.utc)
    start, _ = period(now)
    key = "hebdo-" + start.date().isoformat()
    edition = await session.get(EmailEdition, key)
    if edition is None:
        data = await build_week(session, now)
        if data is None:
            return 0
        await insert_once(session, EmailEdition, {"cle": key, "donnees": data})
        edition = await session.get(EmailEdition, key)
    archive = f"{SITE}/api/v1/newsletter/bilans/{start.date().isoformat()}"
    subscribers = (await session.execute(select(NewsletterAbonne))).scalars().all()
    subscribers_by_email = {a.email.lower(): a for a in subscribers}
    all_users = (await session.execute(select(User))).scalars().all()
    users_by_email = {u.email.lower(): u for u in all_users}
    from services.email_verification import email_confirme
    users = [u for u in all_users if u.is_active and email_confirme(u)]
    targets = {}
    for user in users:
        if user.marketing_opt_out_at or not prefs_utilisateur(user)["email_hebdomadaire"]:
            continue
        subscription = subscribers_by_email.get(user.email.lower())
        if subscription and subscription.statut == "desinscrit":
            continue
        targets[user.email.lower()] = (_unsubscribe_url(user.user_id),
            f"{SITE}/api/v1/newsletter/desabonnement-compte?jeton={make_unsubscribe_token(user.user_id)}")
    for subscriber in subscribers:
        user = users_by_email.get(subscriber.email.lower())
        if subscriber.statut != "confirme" or not subscriber.confirme_at:
            continue
        if user and (user.marketing_opt_out_at or not prefs_utilisateur(user)["email_hebdomadaire"]):
            continue
        url = f"{SITE}/api/v1/newsletter/desinscription?jeton={subscriber.token_desinscription}"
        targets[subscriber.email.lower()] = (url, url)
    sent = 0
    for email, (unsubscribe, oneclick) in targets.items():
        html, plain = weekly(edition.donnees, unsubscribe, archive)
        count = len(edition.donnees["top"])
        subject = f"BlackTurf — top {count} des plans et bilan de la semaine" if count else "BlackTurf — le bilan de la semaine, pertes comprises"
        if await deliver(session, key, email, subject, html, plain, oneclick, now):
            sent += 1
            subscriber = subscribers_by_email.get(email)
            if subscriber:
                subscriber.dernier_envoi_at = now
                await session.commit()
    return sent


async def send_daily(session, now=None):
    from services.alerts import prefs_utilisateur, _unsubscribe_url, make_unsubscribe_token
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(PARIS)
    end = (local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).astimezone(timezone.utc)
    users = (await session.execute(select(User).where(
        User.plan.in_(["starter", "standard", "expert"]), User.is_active == True,
        User.marketing_opt_out_at.is_(None), clause_email_utilisable(),
    ))).scalars().all()
    sent = 0
    for user in users:
        prefs = prefs_utilisateur(user)
        if not prefs["email_quotidien"]:
            continue
        rows = (await session.execute(select(ValueBet, Participation, Cheval, Course)
            .join(Participation, Participation.participation_id == ValueBet.participation_id)
            .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
            .join(Course, Course.course_id == ValueBet.course_id)
            .where(Course.date_heure > now, Course.date_heure < end,
                   ValueBet.detecte_a <= now, Participation.non_partant == False,
                   ValueBet.niveau >= prefs["vb_niveau_min"], *filtres_sql(user.plan, now))
            .order_by(Course.date_heure, ValueBet.ev_max.desc()))).all()
        items, seen = [], set()
        for vb, part, horse, course in rows:
            if part.participation_id in seen:
                continue
            seen.add(part.participation_id)
            try:
                ev = float(vb.ev_max)
                if not Decimal(str(ev)).is_finite():
                    continue
            except (TypeError, ValueError):
                continue
            items.append({"course_id": course.course_id,
                          "heure": utc(course.date_heure).astimezone(PARIS).strftime("%H:%M"),
                          "hippodrome": course.hippodrome_nom, "nom_cheval": horse.nom,
                          "numero": part.numero, "ev": ev, "niveau": vb.niveau})
        if not items:
            continue
        html, plain = daily(items, local.strftime("%d/%m/%Y à %H:%M (Paris)"), _unsubscribe_url(user.user_id))
        oneclick = f"{SITE}/api/v1/newsletter/desabonnement-compte?jeton={make_unsubscribe_token(user.user_id)}"
        if await deliver(session, "jour-" + local.date().isoformat(), user.email,
                         f"BlackTurf — {len(items)} valeur(s) détectée(s) ce {local.strftime('%d/%m')}",
                         html, plain, oneclick, now):
            sent += 1
    return sent
