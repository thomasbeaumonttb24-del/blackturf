from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
import uuid

import pytest
from sqlalchemy import select

from db.models import (BetPlanSnapshot, BetPlanSettlement, EmailEdition, EmailLivraison,
                       NewsletterAbonne, User, Course, Prediction, PredictionSnapshot,
                       Participation, Cheval)
from services import email_campaigns as campaign
from services.alerts import ResultatEnvoi
from services.email_templates import daily, weekly
from tests.test_alerts_weekly_best_vb import _seed_value_bet, _make_user

NOW = datetime(2026, 9, 21, 7, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _enable_editorial_for_campaign_tests(monkeypatch):
    monkeypatch.setenv("EMAIL_EDITORIAL_ENABLED", "1")


@pytest.mark.asyncio
async def test_editorial_send_paused_until_review(db, monkeypatch):
    monkeypatch.setenv("EMAIL_EDITORIAL_ENABLED", "0")
    await seed_plan(db)
    assert await campaign.send_daily(db, NOW) == 0
    assert await campaign.send_weekly(db, NOW) == 0
    assert (await db.execute(select(EmailLivraison))).scalars().all() == []


async def seed_plan(db, number=1, *, stake=10, returned=50, origin="profil_run", pre=True,
                    pending=False, suffix="a", departure=None):
    cid = f"16092026R1C{number}"
    departure = departure or datetime(2026, 9, 16, 12, tzinfo=timezone.utc)
    if not await db.get(Course, cid):
        await _seed_value_bet(db, cid, date_heure=departure)
    sid = cid + suffix
    db.add(BetPlanSnapshot(plan_snapshot_id=sid, course_id=cid, subject_hash="system",
                          profil="equilibre", montant_demande=stake, plan={}, plan_hash=sid,
                          cotes_utilisees={}, algo_config={}, algo_version="test", nb_paris=1,
                          montant_joue=stake, emitted_at=departure - timedelta(minutes=30 if suffix == "a" else 10),
                          course_start_at=departure, is_pre_course=pre, origin=origin))
    db.add(BetPlanSettlement(settlement_id=sid, plan_snapshot_id=sid, course_id=cid,
                            bilan={"total_mise": stake, "total_gain": returned, "net": returned-stake,
                                   "en_attente": 1 if pending else 0},
                            montant_mise=stake, montant_retour=returned, net=returned-stake,
                            nb_paris=1, nb_gagnes=int(returned > stake), statut="partial" if pending else "settled",
                            settled_at=departure+timedelta(hours=1)))
    await db.commit()
    return sid


@pytest.mark.asyncio
async def test_top_net_and_losses_complete_week(db):
    for n, stake, returned in [(1, 100, 110), (2, 10, 70), (3, 10, 60), (4, 10, 50), (5, 10, 0)]:
        await seed_plan(db, n, stake=stake, returned=returned)
    data = await campaign.build_week(db, NOW)
    assert [p["net"] for p in data["top"]] == [60, 50, 40]
    assert data["profils"] == [{"label": "Modéré", "n": 5, "mise": 140, "retour": 290, "net": 150}]
    assert data["debut"] == "14/09/2026" and data["fin"] == "20/09/2026"


@pytest.mark.asyncio
async def test_weekly_algorithm_numbers_use_latest_complete_pre_race_run(db):
    departure = datetime(2026, 9, 16, 12, tzinfo=timezone.utc)
    for race, winner in [(1, 1), (2, 2)]:
        cid = f"16092026R1C{race}"
        await _seed_value_bet(db, cid, numero_gagnant=winner, date_heure=departure)
        for number in (2, 3):
            horse_id = f"horse-{cid}-{number}"
            part_id = f"part-{cid}-{number}"
            pred_id = f"pred-{cid}-{number}"
            db.add(Cheval(cheval_id=horse_id, nom=f"Cheval {number}", age=4, sexe="H"))
            db.add(Participation(participation_id=part_id, course_id=cid,
                                 cheval_id=horse_id, numero=number, non_partant=False))
            db.add(Prediction(prediction_id=pred_id, participation_id=part_id,
                              course_id=cid, proba_top1=.1, proba_top3=.3, rang_predit=number))
        await db.commit()
        for number in (1, 2, 3):
            db.add(PredictionSnapshot(snapshot_id=f"s-{cid}-{number}", prediction_run_id=f"run-{cid}",
                prediction_id=f"pred-{cid}" if number == 1 else f"pred-{cid}-{number}",
                participation_id=f"part-{cid}" if number == 1 else f"part-{cid}-{number}",
                course_id=cid, features={}, features_hash="x" * 64,
                feature_schema_hash="y" * 64, proba_top1=.3, proba_top3=.6,
                rang_predit=number, observed_at=departure-timedelta(minutes=10),
                course_start_at=departure, is_pre_course=True, origin="live", is_replayable=True))
    await db.commit()
    start, end = campaign.period(NOW)
    assert await campaign.weekly_algorithm_numbers(db, start, end) == {
        "courses": 2, "gagnant_top3": 2, "premier_gagnant": 1, "hasard_top3": 37.5, "hasard_courses": 2}
    cid = "16092026R1C2"
    db.add(PredictionSnapshot(snapshot_id="latest-incomplete", prediction_run_id="later-run",
        prediction_id=f"pred-{cid}", participation_id=f"part-{cid}", course_id=cid,
        features={}, features_hash="x" * 64, feature_schema_hash="y" * 64,
        proba_top1=.3, proba_top3=.6, rang_predit=1,
        observed_at=departure-timedelta(minutes=5), course_start_at=departure,
        is_pre_course=True, origin="live", is_replayable=True))
    await db.commit()
    assert await campaign.weekly_algorithm_numbers(db, start, end) == {
        "courses": 1, "gagnant_top3": 1, "premier_gagnant": 1, "hasard_top3": 37.5, "hasard_courses": 1}


@pytest.mark.asyncio
async def test_latest_pending_blocks_instead_of_older_winner(db):
    await seed_plan(db, returned=1000)
    await seed_plan(db, pending=True, suffix="b")
    assert await campaign.build_week(db, NOW) is None


@pytest.mark.asyncio
async def test_latest_loss_replaces_old_winner_private_and_post_excluded(db):
    await seed_plan(db, returned=1000)
    await seed_plan(db, returned=0, suffix="b")
    await seed_plan(db, 2, returned=9999, origin="mise_plan")
    await seed_plan(db, 3, returned=9999, pre=False)
    data = await campaign.build_week(db, NOW)
    assert data["top"] == []
    assert data["profils"][0]["net"] == -10
    assert data["profils"][0]["n"] == 1


@pytest.mark.asyncio
async def test_corrupt_financial_data_blocks(db):
    sid = await seed_plan(db)
    result = await db.get(BetPlanSettlement, sid)
    result.net = 999
    await db.commit()
    with pytest.raises(ValueError, match="incohérent"):
        await campaign.build_week(db, NOW)


@pytest.mark.asyncio
async def test_double_opt_in_dedup_and_preferences(db, monkeypatch):
    await seed_plan(db)
    account = await _make_user(db, "standard")
    optout = await _make_user(db, "free")
    optout.push_subscription = {"prefs": {"email_hebdomadaire": False}}
    for email, status in [(account.email, "confirme"), ("newsletter@example.com", "confirme"),
                          ("waiting@example.com", "en_attente"), (optout.email, "confirme"),
                          ("gone@example.com", "desinscrit")]:
        db.add(NewsletterAbonne(email=email, statut=status, token_desinscription=uuid.uuid4().hex,
                               confirme_at=NOW if status == "confirme" else None))
    await db.commit()
    sender = AsyncMock(return_value=ResultatEnvoi(True, provider_id="mail-1"))
    monkeypatch.setattr("services.alerts.send_email", sender)
    await campaign.send_weekly(db, NOW)
    await campaign.send_weekly(db, NOW + timedelta(minutes=30))
    assert sender.await_count == 3
    assert {c.kwargs["to"] for c in sender.await_args_list} == {account.email, "newsletter@example.com", campaign.CONTROL_ADDRESS}
    assert sum(c.kwargs["to"] == campaign.CONTROL_ADDRESS for c in sender.await_args_list) == 1
    assert all(c.kwargs["idempotency_key"] and c.kwargs["text"] for c in sender.await_args_list)
    assert all(c.kwargs["unsubscribe_url"] for c in sender.await_args_list if c.kwargs["to"] != campaign.CONTROL_ADDRESS)
    edition = await db.get(EmailEdition, "hebdo-2026-09-14")
    assert "token" not in str(edition.donnees)


@pytest.mark.asyncio
async def test_retry_frozen_payload_and_ambiguous_expiry(db, monkeypatch):
    sender = AsyncMock(side_effect=[ResultatEnvoi(False, "timeout"), ResultatEnvoi(True)])
    monkeypatch.setattr("services.alerts.send_email", sender)
    args = (db, "test", "a@example.com", "subject", "HTML", "TEXT", "https://blackturf.fr/unsub")
    assert not await campaign.deliver(*args, NOW)
    assert await campaign.deliver(db, "test", "a@example.com", "NEW", "CHANGED", "NEW", "https://other", NOW+timedelta(minutes=30))
    assert sender.await_args_list[0] == sender.await_args_list[1]
    row = (await db.execute(select(EmailLivraison))).scalar_one()
    row.statut = "pending"
    await db.commit()
    assert not await campaign.deliver(*args, NOW+timedelta(hours=24))
    assert sender.await_count == 2
    assert row.statut == "review"


@pytest.mark.asyncio
async def test_daily_paris_cutoff_preference_and_idempotence(db, monkeypatch):
    departure = NOW + timedelta(hours=5)
    await _seed_value_bet(db, "DAILY", statut="a_venir", date_heure=departure)
    from db.models import ValueBet
    vb = await db.get(ValueBet, "vb-DAILY")
    vb.detecte_a = NOW - timedelta(minutes=20)
    user = await _make_user(db, "standard")
    optedout = await _make_user(db, "expert")
    optedout.push_subscription = {"prefs": {"email_quotidien": False}}
    await db.commit()
    sender = AsyncMock(return_value=ResultatEnvoi(True))
    monkeypatch.setattr("services.alerts.send_email", sender)
    await campaign.send_daily(db, NOW)
    await campaign.send_daily(db, NOW+timedelta(minutes=15))
    assert sender.await_count == 2
    assert {c.kwargs["to"] for c in sender.await_args_list} == {user.email, campaign.CONTROL_ADDRESS}
    assert "14:00" in sender.await_args_list[0].kwargs["html"]  # UTC 12 → Paris 14


@pytest.mark.asyncio
async def test_standard_delay_and_non_partants(db, monkeypatch):
    await _seed_value_bet(db, "RECENT", statut="a_venir", date_heure=NOW+timedelta(hours=3))
    from db.models import ValueBet, Participation
    vb = await db.get(ValueBet, "vb-RECENT")
    vb.detecte_a = NOW - timedelta(minutes=5)
    await _make_user(db, "standard")
    await db.commit()
    sender = AsyncMock(return_value=True)
    monkeypatch.setattr("services.alerts.send_email", sender)
    await campaign.send_daily(db, NOW)
    assert sender.await_count == 0
    part = await db.get(Participation, "part-RECENT")
    part.non_partant = True
    await db.commit()
    await campaign.send_daily(db, NOW+timedelta(minutes=20))
    assert sender.await_count == 0


def test_render_escapes_and_limits_email_size():
    item = {"course_id": "R1C1", "heure": "14:00", "hippodrome": "<img src=x>",
            "nom_cheval": "TrèsLongNom"*30, "numero": 12, "niveau": 4, "ev": .12}
    html, plain = daily([item]*100, "DÉMONSTRATION", "https://example.com/unsub")
    assert "<img src=x>" not in html and "&lt;img src=x&gt;" in html
    assert html.count("Consulter cette course") == 12
    assert len(html.encode()) < 100_000
    assert "instagram.com/blackturf.fr" in html and "logo-nuit.png" in html
    assert "viewport" in html and "table-layout:fixed" in html
    assert "★★★★" in html and "Niveau 4/4" in html
    assert "hero-valeurs.jpg" in html and "Photo d’illustration" in html
    assert "img/email/instagram-glyph.png" in html
    assert "https://example.com/unsub" in plain


def test_three_star_signal_and_weekly_photo():
    item = {"course_id": "R1C1", "heure": "14:00", "hippodrome": "Vincennes",
            "nom_cheval": "Exemple", "numero": 2, "niveau": 3, "ev": .08}
    html, plain = daily([item], "DÉMONSTRATION", "https://example.com/unsub")
    assert "★★★</span><span" in html and "☆</span>" in html
    assert "Niveau 3/4" in plain
    html, _ = weekly({"debut": "14/09/2026", "fin": "20/09/2026", "top": [], "profils": []})
    assert "hero-bilan.jpg" in html and "sans lien avec les courses" in html
    assert "Toute la semaine" not in html
    html, plain = weekly({"debut": "14/09/2026", "fin": "20/09/2026", "top": [],
                          "algo": {"courses": 7, "gagnant_top3": 4, "premier_gagnant": 2,
                                   "hasard_top3": 30.2}})
    assert "4/7" in html and "2/7" in plain
    assert "57,1 %" in html and "28,6 %" in plain
    assert "30,2 %" in html and "au hasard" in plain
    assert "courses évaluables" in html and "Prudent" not in html


@pytest.mark.parametrize("date", [datetime(2026, 3, 30, 7, tzinfo=timezone.utc), datetime(2026, 10, 26, 8, tzinfo=timezone.utc)])
def test_calendar_week_across_dst(date):
    start, end = campaign.period(date)
    assert start.weekday() == end.weekday() == 0
    assert start.hour == end.hour == 0
    assert (end.date()-start.date()).days == 7


@pytest.mark.asyncio
async def test_public_archive_and_one_click(client, db):
    await seed_plan(db)
    data = await campaign.build_week(db, NOW)
    db.add(EmailEdition(cle="hebdo-2026-09-14", donnees=data))
    user = await _make_user(db, "free")
    from services.alerts import make_unsubscribe_token
    response = await client.get("/api/v1/newsletter/bilans/2026-09-14")
    assert response.status_code == 200
    assert "pertes comprises" not in response.text and "token=" not in response.text
    response = await client.post("/api/v1/newsletter/desabonnement-compte", params={"jeton": make_unsubscribe_token(user.user_id)}, content="List-Unsubscribe=One-Click")
    assert response.status_code == 200
    await db.refresh(user)
    assert user.marketing_opt_out_at is not None


@pytest.mark.asyncio
async def test_signed_webhook_and_suppression(client, db, monkeypatch):
    import base64
    import hashlib
    import hmac
    import json
    import time
    from api.config import get_settings
    key = b"test-only-signing-key"
    monkeypatch.setattr(get_settings(), "resend_webhook_secret", "whsec_" + base64.b64encode(key).decode())
    db.add(EmailLivraison(cle="delivery", campagne="test", email="bounce@example.com", requete={},
                         statut="sent", provider_id="provider-1"))
    await db.commit()
    def signed(kind, delta=0):
        timestamp = str(int(time.time())+delta)
        payload = json.dumps({"type": kind, "data": {"email_id": "provider-1"}}).encode()
        digest = base64.b64encode(hmac.new(key, f"evt.{timestamp}.".encode()+payload, hashlib.sha256).digest()).decode()
        return payload, {"svix-id": "evt", "svix-timestamp": timestamp, "svix-signature": "v1,"+digest}
    body, headers = signed("email.bounced")
    path = "/api/v1/newsletter/resend-webhook"
    assert (await client.post(path, content=body+b" ", headers=headers)).status_code == 400
    old_body, old_headers = signed("email.bounced", -600)
    assert (await client.post(path, content=old_body, headers=old_headers)).status_code == 400
    assert (await client.post(path, content=body, headers=headers)).status_code == 200
    body, headers = signed("email.delivered")
    assert (await client.post(path, content=body, headers=headers)).status_code == 200
    row = await db.get(EmailLivraison, "delivery")
    await db.refresh(row)
    assert row.statut == "bounced"  # delayed events cannot unsuppress an address
    sender = AsyncMock(return_value=True)
    monkeypatch.setattr("services.alerts.send_email", sender)
    assert not await campaign.deliver(db, "next-week", row.email, "s", "h", "t", "https://example.com", NOW)
    sender.assert_not_called()


@pytest.mark.asyncio
async def test_newsletter_only_oneclick_post(client, db):
    token = "newsletter-unsubscribe-test-token"
    subscriber = NewsletterAbonne(email="letter@example.com", statut="confirme", confirme_at=NOW,
                                  token_desinscription=token)
    db.add(subscriber)
    await db.commit()
    for _ in range(2):
        response = await client.post("/api/v1/newsletter/desinscription", params={"jeton": token},
                                     content="List-Unsubscribe=One-Click")
        assert response.status_code == 200
    await db.refresh(subscriber)
    assert subscriber.statut == "desinscrit"


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["provisoire", "gain_indetermine", "nb_en_attente"])
async def test_provisional_totals_never_published(db, flag):
    sid = await seed_plan(db)
    row = await db.get(BetPlanSettlement, sid)
    row.bilan = {**row.bilan, flag: True}
    await db.commit()
    assert await campaign.build_week(db, NOW) is None


@pytest.mark.asyncio
async def test_sender_headers_without_network(monkeypatch):
    import httpx
    from services import alerts
    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    monkeypatch.setattr(alerts.settings, "resend_api_key", "test-only")
    observed = []
    def respond(request):
        import json
        observed.append((dict(request.headers), json.loads(request.content)))
        return httpx.Response(200, json={"id": "provider-demo"})
    real_client = httpx.AsyncClient
    monkeypatch.setattr(alerts.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(respond)))
    result = await alerts.send_email("example@example.com", "subject", "html", "plain",
                                     idempotency_key="test-id", unsubscribe_url="https://example.com/unsubscribe")
    assert result.provider_id == "provider-demo"
    headers, payload = observed[0]
    assert headers["idempotency-key"] == "test-id"
    assert payload["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert payload["text"] == "plain"
