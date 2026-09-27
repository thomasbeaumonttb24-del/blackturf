"""Alertes e-mail des stratégies (services/alertes_strategies.py).

Invariants : seul un compte Expert actif, joignable et non opposé reçoit l'alerte ;
un signal ne part qu'une fois ; au plus un e-mail par 4 h, sans perdre les signaux
arrivés pendant ce délai ; aucun envoi si l'interrupteur des lettres est coupé.
Aucun e-mail réel : `send_email` est remplacé.
"""
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from db.models import Strategie, ValueBet
from services import alertes_strategies as al
from services.alerts import ResultatEnvoi
from services.email_templates import alertes_strategies as gabarit
from tests.test_alerts_weekly_best_vb import _make_user, _seed_value_bet

NOW = datetime(2026, 9, 21, 9, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _interrupteur(monkeypatch):
    monkeypatch.setenv("EMAIL_EDITORIAL_ENABLED", "1")


@pytest.fixture
def envoi(monkeypatch):
    sender = AsyncMock(return_value=ResultatEnvoi(True))
    monkeypatch.setattr("services.alerts.send_email", sender)
    return sender


async def _vb(db, course_id, *, ev=0.15, niveau=3, dans=timedelta(hours=3)):
    await _seed_value_bet(db, course_id, statut="a_venir", date_heure=NOW + dans, ev=ev, niveau=niveau)
    vb = await db.get(ValueBet, f"vb-{course_id}")
    vb.detecte_a = NOW - timedelta(minutes=30)
    vb.actif = True
    await db.commit()


async def _strategie(db, user, *, alerte=True, filtres=None, indicateurs=None, nom="Ma stratégie"):
    s = Strategie(strategie_id=str(uuid.uuid4()), user_id=user.user_id, nom=nom,
                  filtres=filtres or {}, indicateurs=indicateurs or {"ev_min": 0.05}, alerte_email=alerte)
    db.add(s)
    await db.commit()
    return s


# ─── Correspondance ────────────────────────────────────────────────────────

def _objets(**course):
    base = dict(discipline="Plat", hippodrome_nom="Vincennes", niveau_course=None, terrain_officiel="Bon",
                est_quinte=False, distance=1800, nb_partants=12)
    base.update(course)
    return dict(course=SimpleNamespace(**base), vb=SimpleNamespace(ev_max=0.12, niveau=3),
                pred=SimpleNamespace(proba_top3=0.55, confidence_score=70), cheval=SimpleNamespace(elo_score_global=1600))


def test_correspondance_criteres():
    o = _objets()
    assert al.correspond({}, {}, **o)
    assert al.correspond({"discipline": "plat", "distance_min": 1600, "distance_max": 2000}, {"ev_min": 0.10}, **o)
    assert not al.correspond({"discipline": "Attelé"}, {}, **o)
    assert not al.correspond({"distance_max": 1600}, {}, **o)
    assert not al.correspond({"est_quinte": True}, {}, **o)
    assert not al.correspond({}, {"ev_min": 0.20}, **o)
    assert not al.correspond({}, {"niveau_vb_min": 4}, **o)
    assert not al.correspond({}, {"proba_top3_min": 0.6}, **o)
    assert not al.correspond({}, {"elo_min": 1700}, **o)


def test_donnee_absente_ne_satisfait_pas_un_minimum():
    o = _objets(nb_partants=None)
    o["pred"] = None
    assert al.correspond({}, {"ev_min": 0.05}, **o)
    assert not al.correspond({}, {"proba_top3_min": 0.5}, **o)
    assert not al.correspond({"nb_partants_min": 8}, {}, **o)


# ─── Envoi ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_expert_seulement_et_alerte_cochee(db, envoi):
    await _vb(db, "S1")
    expert = await _make_user(db, "expert")
    standard = await _make_user(db, "standard")
    sans_alerte = await _make_user(db, "expert")
    await _strategie(db, expert)
    await _strategie(db, standard)
    await _strategie(db, sans_alerte, alerte=False)
    assert await al.envoyer_alertes_strategies(db, NOW) == 1
    assert [c.kwargs["to"] for c in envoi.await_args_list] == [expert.email]
    kwargs = envoi.await_args_list[0].kwargs
    assert "Cheval S1" in kwargs["html"] and "Ma stratégie" in kwargs["html"]
    assert kwargs["unsubscribe_url"] and kwargs["text"]


@pytest.mark.asyncio
async def test_opposition_marketing_et_criteres_non_remplis(db, envoi):
    await _vb(db, "S2", ev=0.08)
    oppose = await _make_user(db, "expert")
    oppose.marketing_opt_out_at = NOW
    exigeant = await _make_user(db, "expert")
    await db.commit()
    await _strategie(db, oppose)
    await _strategie(db, exigeant, indicateurs={"ev_min": 0.20})
    assert await al.envoyer_alertes_strategies(db, NOW) == 0
    envoi.assert_not_awaited()


@pytest.mark.asyncio
async def test_un_signal_ne_part_qu_une_fois_et_delai_de_4h(db, envoi):
    await _vb(db, "S3")
    user = await _make_user(db, "expert")
    await _strategie(db, user)
    assert await al.envoyer_alertes_strategies(db, NOW) == 1
    # Même signal au passage suivant : rien.
    assert await al.envoyer_alertes_strategies(db, NOW + timedelta(minutes=10)) == 0
    # Nouveau signal pendant le délai : il attend…
    await _vb(db, "S4", dans=timedelta(hours=6))
    assert await al.envoyer_alertes_strategies(db, NOW + timedelta(hours=1)) == 0
    # …et part, seul, une fois les 4 h écoulées.
    assert await al.envoyer_alertes_strategies(db, NOW + timedelta(hours=4, minutes=5)) == 1
    dernier = envoi.await_args_list[-1].kwargs["html"]
    assert "Cheval S4" in dernier and "Cheval S3" not in dernier
    assert envoi.await_count == 2


@pytest.mark.asyncio
async def test_depart_passe_non_partant_et_interrupteur(db, envoi, monkeypatch):
    await _vb(db, "S5", dans=timedelta(minutes=-10))
    user = await _make_user(db, "expert")
    await _strategie(db, user)
    assert await al.envoyer_alertes_strategies(db, NOW) == 0
    await _vb(db, "S6")
    monkeypatch.setenv("EMAIL_EDITORIAL_ENABLED", "0")
    assert await al.envoyer_alertes_strategies(db, NOW) == 0
    envoi.assert_not_awaited()


@pytest.mark.asyncio
async def test_echec_d_envoi_ne_consomme_ni_signal_ni_delai(db, monkeypatch):
    await _vb(db, "S7")
    user = await _make_user(db, "expert")
    await _strategie(db, user)
    monkeypatch.setattr("services.alerts.send_email", AsyncMock(return_value=ResultatEnvoi(False, "panne")))
    assert await al.envoyer_alertes_strategies(db, NOW) == 0
    ok = AsyncMock(return_value=ResultatEnvoi(True))
    monkeypatch.setattr("services.alerts.send_email", ok)
    assert await al.envoyer_alertes_strategies(db, NOW + timedelta(minutes=10)) == 1
    assert ok.await_count == 1


def test_gabarit_echappe_et_nomme_les_strategies():
    item = {"course_id": "X", "heure": "14:00", "hippodrome": "<b>Vincennes</b>", "course_nom": "Prix",
            "reunion": 1, "course_num": 4, "nom_cheval": "ECLAT", "numero": 9, "ev": 0.142, "niveau": 3,
            "cote": 21.0, "casaque_url": None, "strategies": ["Plat <rapide>"]}
    html, texte = gabarit([item], "https://blackturf.fr/desabonnement?token=t")
    assert "<b>Vincennes</b>" not in html and "&lt;b&gt;Vincennes" in html
    assert "Plat &lt;rapide&gt;" in html and "+14,2 %" in html
    assert "blackturf.fr/strategies" in html and "09 74 75 13 13" in html
    assert "Plat <rapide>" in texte and "desabonnement?token=t" in texte
