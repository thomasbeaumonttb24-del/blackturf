"""Un canal d'envoi mort doit se voir — il est resté muet deux mois.

Entre le 07/06 et le 01/08/2026, `digest_matin` a échoué 253 fois d'affilée
(clé Resend invalide) : le job tournait, les logs disaient « done », `envoye`
valait `false` en base, et personne n'a rien vu. La surveillance de fraîcheur ne
regardait que les données d'entrée, jamais la sortie.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AlerteLog
from services.data_quality import (
    MIN_ENVOIS_POUR_JUGER_CANAL,
    livraison_alertes,
    rapport_qualite,
)

NOW = datetime.now(timezone.utc)


async def _envois(db: AsyncSession, canal: str, *, ok: int, echecs: int,
                  age_heures: float = 1.0) -> None:
    for i in range(ok + echecs):
        db.add(AlerteLog(
            alerte_id=str(uuid.uuid4()),
            user_id=None,
            type_alerte="digest_matin",
            canal=canal,
            payload={},
            envoye=(i < ok),
            created_at=NOW - timedelta(hours=age_heures),
        ))
    await db.commit()


async def test_canal_sain(db: AsyncSession):
    await _envois(db, "email", ok=20, echecs=0)
    out = await livraison_alertes(db)
    assert out["canaux"]["email"]["statut"] == "ok"


async def test_canal_totalement_casse(db: AsyncSession):
    """Le cas réel : 100 % d'échecs, sur des semaines."""
    await _envois(db, "email", ok=0, echecs=30)
    out = await livraison_alertes(db)
    canal = out["canaux"]["email"]
    assert canal["statut"] == "failing"
    assert canal["taux_echec"] == 1.0


async def test_quelques_echecs_isoles_ne_declenchent_pas_l_alerte_critique(db: AsyncSession):
    """Un push expiré ou une adresse en rebond ne veut pas dire canal mort."""
    await _envois(db, "push", ok=19, echecs=1)
    out = await livraison_alertes(db)
    assert out["canaux"]["push"]["statut"] == "degraded"


async def test_trop_peu_d_envois_pour_conclure(db: AsyncSession):
    await _envois(db, "email", ok=0, echecs=MIN_ENVOIS_POUR_JUGER_CANAL - 1)
    out = await livraison_alertes(db)
    assert out["canaux"]["email"]["statut"] == "insufficient_data"


async def test_les_vieux_envois_sortent_de_la_fenetre(db: AsyncSession):
    """La panne d'hier ne doit pas masquer le rétablissement d'aujourd'hui."""
    await _envois(db, "email", ok=0, echecs=30, age_heures=72)
    out = await livraison_alertes(db, heures=24)
    assert "email" not in out["canaux"]


async def test_le_rapport_qualite_remonte_le_canal_casse(db: AsyncSession):
    """C'est ce chemin-là qui écrit dans system_errors, donc au back-office."""
    await _envois(db, "email", ok=0, echecs=30)
    rapport = await rapport_qualite(db)

    codes = [a["code"] for a in rapport["anomalies"]]
    assert "canal_envoi_casse" in codes
    assert rapport["statut_global"] == "critical"
    anomalie = next(a for a in rapport["anomalies"] if a["code"] == "canal_envoi_casse")
    assert "30" in anomalie["message"] and "100" in anomalie["message"]


# ── La RAISON de l'échec doit être enregistrée ───────────────────────────────
async def test_un_envoi_rate_dit_pourquoi(monkeypatch):
    """115 860 échecs ont été journalisés entre juin et août 2026 avec une colonne
    `erreur` vide : diagnostiquer imposait de relire les logs conteneur, effacés
    à chaque redémarrage. Un échec doit porter sa cause."""
    from services import alerts

    monkeypatch.setattr(alerts.settings, "resend_api_key", "", raising=False)
    resultat = await alerts.send_email(to="x@y.z", subject="s", html="<p>h</p>")

    assert not resultat, "sans clé d'API, l'envoi ne peut pas réussir"
    assert resultat.erreur and "RESEND_API_KEY" in resultat.erreur


async def test_le_push_sans_cles_vapid_dit_pourquoi(monkeypatch):
    """Cas réel : 22 345 tentatives, 22 345 échecs, aucune trace — les clés VAPID
    n'ont jamais été posées en production."""
    from services import alerts

    monkeypatch.setattr(alerts.settings, "vapid_private_key", "", raising=False)
    resultat = await alerts.send_web_push({"endpoint": "https://push/x"}, "t", "c")

    assert not resultat
    assert resultat.erreur and "VAPID" in resultat.erreur


async def test_le_resultat_reste_utilisable_comme_un_booleen():
    """Les appelants existants écrivent `if ok:` — le changement de type ne doit
    rien casser."""
    from services.alerts import ResultatEnvoi

    assert bool(ResultatEnvoi(True)) is True
    assert bool(ResultatEnvoi(False, "raison")) is False
    if ResultatEnvoi(True):
        pass
    else:
        raise AssertionError("un envoi réussi doit être vrai")
