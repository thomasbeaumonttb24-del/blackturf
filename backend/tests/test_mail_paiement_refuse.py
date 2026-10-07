"""E-mail de supervision d'un paiement refusé (2026-10-07).

Le même « Paiement en échec — accès coupé » couvrait une carte refusée à
l'inscription (aucun accès n'a jamais existé) et un renouvellement refusé.
"""
from datetime import datetime, timezone

import pytest

from db.models import SubscriptionEvent
from services import abonnements

pytestmark = pytest.mark.asyncio


@pytest.fixture
def envois(monkeypatch):
    recus = []

    async def _email(**kw):
        recus.append(kw)
    import services.alerts as alerts
    monkeypatch.setattr(alerts, "send_email", _email)
    return recus


def _event(motif, tentative=1, acces_ouvert=False, relance=1_760_000_000):
    return SubscriptionEvent(
        event_id="e", email="client@x.fr", type="paiement_echoue", plan="expert",
        montant_cents=950, stripe_subscription_id="sub_x",
        periode_fin=datetime(2026, 11, 7, 17, 57, tzinfo=timezone.utc),
        detail={"motif": motif, "tentative": tentative, "prochaine_relance": relance,
                "acces_ouvert": acces_ouvert, "plan_apres": "free"})


async def test_carte_refusee_a_l_inscription_ne_parle_pas_d_acces_coupe(envois):
    await abonnements._notifier_admin(_event("subscription_create"))
    mail = envois[0]
    assert "Carte refusée à l'inscription" in mail["subject"]
    assert "coupé" not in mail["subject"]
    assert "jamais eu accès" in mail["html"]
    assert "Fin de période" not in mail["html"]  # mois jamais payé
    assert "1 sur 3" in mail["html"]


async def test_renouvellement_refuse_dit_acces_coupe_et_heure_de_paris(envois):
    await abonnements._notifier_admin(_event("subscription_cycle"))
    mail = envois[0]
    assert "Renouvellement refusé — accès coupé" in mail["subject"]
    assert "07/11/2026 à 18:57" in mail["html"]  # 17:57 UTC = 18:57 Paris (heure d'hiver)


async def test_relance_et_derniere_tentative(envois):
    await abonnements._notifier_admin(_event("subscription_create", tentative=3, relance=None))
    mail = envois[0]
    assert "Relance refusée" in mail["subject"]
    assert "aucune" in mail["html"]


async def test_acces_maintenu_par_un_autre_abonnement(envois):
    await abonnements._notifier_admin(_event("subscription_cycle", acces_ouvert=True))
    assert "accès maintenu" in envois[0]["subject"]
