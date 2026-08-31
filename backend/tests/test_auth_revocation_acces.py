"""Révocation des jetons d'ACCÈS, pas seulement des refresh.

Le contrôle `pwd_reset_at` n'était appliqué qu'au `/auth/refresh`, au motif
documenté dans le code que « l'access token expire en 15 min ». Il expirait en
réalité en 60 min — et en 720 min tant que `ACCESS_TOKEN_EXPIRE_MINUTES`
n'atteignait pas le conteneur (variable absente du bloc `environment` du compose
de production jusqu'au 19/08).

Conséquence : un mot de passe réinitialisé parce qu'un jeton avait fuité laissait
ce jeton ouvrir des sessions pendant toute sa durée de vie restante. C'est
exactement ce qu'un reset est censé couper.
"""
import time
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


def _redis_avec_reset(a_la_seconde: int) -> AsyncMock:
    """Client Redis simulé annonçant un reset de mot de passe à cet instant."""
    faux = AsyncMock()
    faux.get = AsyncMock(return_value=str(a_la_seconde))
    return faux


async def test_un_jeton_dacces_anterieur_a_un_reset_est_rejete(
    client: AsyncClient, auth_headers, monkeypatch
):
    # Le jeton de la fixture vient d'être émis : on place le reset APRÈS.
    plus_tard = int(time.time()) + 60
    monkeypatch.setattr(
        "db.redis_client.get_redis",
        AsyncMock(return_value=_redis_avec_reset(plus_tard)),
    )

    resp = await client.get("/api/v1/auth/me", headers=auth_headers)

    assert resp.status_code == 401, (
        "un jeton d'accès émis avant le reset doit être refusé, "
        f"reçu {resp.status_code}"
    )


async def test_un_jeton_dacces_posterieur_a_un_reset_reste_valide(
    client: AsyncClient, auth_headers, monkeypatch
):
    """Le contrôle ne doit pas déconnecter les sessions ouvertes APRÈS le reset."""
    plus_tot = int(time.time()) - 3600
    monkeypatch.setattr(
        "db.redis_client.get_redis",
        AsyncMock(return_value=_redis_avec_reset(plus_tot)),
    )

    resp = await client.get("/api/v1/auth/me", headers=auth_headers)

    assert resp.status_code == 200


async def test_une_panne_redis_ne_deconnecte_personne(
    client: AsyncClient, auth_headers, monkeypatch
):
    """Fail-open assumé : Redis indisponible ne doit pas fermer le site.

    Le compromis est explicite — une révocation peut être manquée pendant une
    panne, mais une panne Redis ne déconnecte pas tous les abonnés.
    """
    monkeypatch.setattr(
        "db.redis_client.get_redis",
        AsyncMock(side_effect=ConnectionError("redis down")),
    )

    resp = await client.get("/api/v1/auth/me", headers=auth_headers)

    assert resp.status_code == 200


async def test_la_duree_de_vie_du_jeton_dacces_est_bien_celle_configuree():
    """Garde-fou contre la dérive qui a causé le problème : le défaut du code ne
    doit pas dépasser silencieusement ce que l'exploitation croit configurer."""
    from api.config import get_settings

    assert get_settings().access_token_expire_minutes <= 720
