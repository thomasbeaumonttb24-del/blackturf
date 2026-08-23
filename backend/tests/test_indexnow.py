"""IndexNow — signalement des URLs du jour à Bing, Yandex, Naver et Seznam.

Deux garde-fous comptent ici :

- sans clé configurée, la fonction doit rester SILENCIEUSE et inoffensive. Elle est
  appelée depuis un job de scraping : une exception y ferait perdre des données de
  course, ce qui coûterait infiniment plus qu'un signalement manqué ;
- on ne signale que des URLs de blackturf.fr. Envoyer l'URL d'un autre domaine ferait
  rejeter la requête entière par le service, et les vraies URLs avec.
"""
import pytest

from services import indexnow

pytestmark = pytest.mark.asyncio


async def test_sans_cle_ne_fait_rien(monkeypatch):
    monkeypatch.setattr(indexnow.settings, "indexnow_key", "", raising=False)
    assert await indexnow.signaler(["https://blackturf.fr/programme"]) == 0


async def test_urls_d_un_autre_domaine_ecartees(monkeypatch):
    monkeypatch.setattr(indexnow.settings, "indexnow_key", "cle-de-test-123456", raising=False)
    envoye: dict = {}

    class _Resp:
        status_code = 200
        text = ""

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json):
            envoye["payload"] = json
            return _Resp()

    monkeypatch.setattr(indexnow.httpx, "AsyncClient", _Client)

    n = await indexnow.signaler([
        "https://blackturf.fr/programme",
        "https://exemple.fr/pirate",           # autre domaine
        "https://blackturf.fr/programme",      # doublon
        "http://blackturf.fr/non-https",       # pas https
    ])

    assert n == 1
    assert envoye["payload"]["urlList"] == ["https://blackturf.fr/programme"]
    assert envoye["payload"]["host"] == "blackturf.fr"
    assert envoye["payload"]["keyLocation"].endswith(".txt")


async def test_une_panne_reseau_ne_remonte_jamais(monkeypatch):
    monkeypatch.setattr(indexnow.settings, "indexnow_key", "cle-de-test-123456", raising=False)

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json):
            raise RuntimeError("réseau coupé")

    monkeypatch.setattr(indexnow.httpx, "AsyncClient", _Client)
    assert await indexnow.signaler(["https://blackturf.fr/programme"]) == 0



async def test_urls_du_jour_couvre_les_pages_perissables():
    urls = indexnow.urls_du_jour(["23082026R1C3", "23082026R1C4"], "2026-08-23")
    assert "https://blackturf.fr/programme" in urls
    assert "https://blackturf.fr/quinte-du-jour" in urls
    assert "https://blackturf.fr/resultats" in urls
    assert "https://blackturf.fr/resultats/2026-08-23" in urls
    assert "https://blackturf.fr/courses/23082026R1C3" in urls
    # L'accueil et les pages éditoriales ne bougent pas : les signaler sans cesse est le
    # meilleur moyen de se faire ignorer.
    assert "https://blackturf.fr/" not in urls
    assert not any(u.endswith("/tarifs") for u in urls)
