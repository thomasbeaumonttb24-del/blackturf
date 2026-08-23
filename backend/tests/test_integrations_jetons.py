"""Dépôt et renouvellement du jeton Instagram.

Trois invariants portent la sécurité de cette intégration :

- **aucune route ne renvoie jamais la valeur du jeton** — une interface qui réaffiche un
  secret finit par le laisser fuiter dans une capture d'écran ou un journal ;
- **un jeton qui ne fonctionne pas n'est pas enregistré** — sinon l'intégration se croit
  configurée et la publication échoue en silence des semaines plus tard ;
- **le renouvellement écrit sa raison d'échec en base** — un renouvellement raté en
  silence, c'est une publication morte deux mois après, sans la moindre trace.
"""
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from db.models import JetonIntegration
from services import jetons as svc

pytestmark = pytest.mark.asyncio

JETON = "IGAA" + "x" * 120


class _Resp:
    def __init__(self, status=200, payload=None, texte=""):
        self.status_code = status
        self._payload = payload or {}
        self.text = texte
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._payload


def _client_http(reponses):
    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None):
            return reponses.pop(0)

    return _C


async def test_depot_refuse_un_jeton_que_instagram_rejette(
    client: AsyncClient, admin_headers, monkeypatch, db
):
    from api.routes import integrations

    monkeypatch.setattr(
        integrations.httpx,
        "AsyncClient",
        _client_http([_Resp(400, {"error": {"message": "Invalid OAuth access token"}})]),
    )

    resp = await client.post(
        "/admin/api/integrations/instagram", json={"jeton": JETON}, headers=admin_headers
    )
    assert resp.status_code == 400

    # Rien ne doit avoir été enregistré : une intégration qui se croit configurée est
    # pire qu'une intégration absente.
    res = await db.execute(select(JetonIntegration))
    assert res.scalars().all() == []


async def test_depot_valide_enregistre_sans_jamais_renvoyer_le_jeton(
    client: AsyncClient, admin_headers, monkeypatch, db
):
    from api.routes import integrations

    monkeypatch.setattr(
        integrations.httpx,
        "AsyncClient",
        _client_http([_Resp(200, {"user_id": "17841433070236786", "username": "blackturf.fr"})]),
    )

    resp = await client.post(
        "/admin/api/integrations/instagram", json={"jeton": JETON}, headers=admin_headers
    )
    assert resp.status_code == 200
    corps = resp.json()
    assert corps["configure"] is True
    assert corps["compte_id"] == "17841433070236786"
    # L'invariant central : la valeur ne sort jamais.
    assert JETON not in resp.text

    etat = await client.get("/admin/api/integrations/instagram", headers=admin_headers)
    assert JETON not in etat.text


async def test_etat_inaccessible_sans_droits_admin(client: AsyncClient, auth_headers):
    resp = await client.get("/admin/api/integrations/instagram", headers=auth_headers)
    assert resp.status_code == 403


async def test_jeton_tronque_refuse_avant_tout_appel(client: AsyncClient, admin_headers):
    """Un collage tronqué est l'erreur la plus fréquente : on la nomme tout de suite."""
    resp = await client.post(
        "/admin/api/integrations/instagram", json={"jeton": "trop-court"}, headers=admin_headers
    )
    assert resp.status_code == 422


async def test_renouvellement_prolonge_et_remplace_la_valeur(db, monkeypatch):
    await svc.deposer(db, JETON, compte_id="17841433070236786", duree_secondes=3600)

    monkeypatch.setattr(
        svc.httpx,
        "AsyncClient",
        _client_http([_Resp(200, {"access_token": "IGAA-nouveau", "expires_in": 5184000})]),
    )
    ok, raison = await svc.renouveler_instagram(db)

    assert ok is True and raison is None
    jeton = await svc.lire(db)
    assert jeton.valeur == "IGAA-nouveau"
    # SQLite relit une date sans fuseau : on normalise comme le fait le service.
    assert svc._aware(jeton.expire_at) > datetime.now(timezone.utc) + timedelta(days=50)
    assert jeton.dernier_renouvellement_at is not None


async def test_echec_de_renouvellement_ecrit_sa_raison_en_base(db, monkeypatch):
    await svc.deposer(db, JETON, duree_secondes=3600)

    monkeypatch.setattr(
        svc.httpx, "AsyncClient", _client_http([_Resp(400, {}, "jeton expiré")])
    )
    ok, raison = await svc.renouveler_instagram(db)

    assert ok is False
    jeton = await svc.lire(db)
    # Sans cette trace, une publication morte deux mois plus tard reste inexplicable.
    assert jeton.derniere_erreur


async def test_renouvellement_declenche_seulement_a_l_approche_de_l_echeance(db):
    loin = JetonIntegration(
        fournisseur="test-loin",
        valeur="x",
        expire_at=datetime.now(timezone.utc) + timedelta(days=45),
    )
    proche = JetonIntegration(
        fournisseur="test-proche",
        valeur="x",
        expire_at=datetime.now(timezone.utc) + timedelta(days=3),
    )
    assert svc.renouvellement_necessaire(loin) is False
    assert svc.renouvellement_necessaire(proche) is True
    assert svc.renouvellement_necessaire(None) is False
