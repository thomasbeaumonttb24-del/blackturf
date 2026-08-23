"""Publication Instagram — l'interrupteur doit rester fermé par défaut.

Publier au nom d'une marque est irréversible et public. Le test le plus important de ce
fichier est celui qui vérifie que la présence d'un jeton dans l'environnement ne suffit
JAMAIS à déclencher une publication : il faut un réglage explicite.
"""
import pytest

from services import instagram

pytestmark = pytest.mark.asyncio


def _configurer(monkeypatch, *, jeton="jeton-de-test", compte="17841400000000000", actif=False):
    monkeypatch.setattr(instagram.settings, "meta_access_token", jeton, raising=False)
    monkeypatch.setattr(instagram.settings, "instagram_user_id", compte, raising=False)
    monkeypatch.setattr(instagram.settings, "instagram_publication_active", actif, raising=False)


class _Reponse:
    def __init__(self, status=200, payload=None, texte=""):
        self.status_code = status
        self._payload = payload or {}
        self.text = texte

    def json(self):
        return self._payload


def _client(appels, reponses):
    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, data=None):
            appels.append(url)
            return reponses.pop(0)

    return _C


async def test_un_jeton_present_ne_suffit_pas_a_publier(monkeypatch):
    """Le garde-fou central : sans réglage explicite, aucun appel réseau n'est émis."""
    _configurer(monkeypatch, actif=False)
    appels: list[str] = []
    monkeypatch.setattr(instagram.httpx, "AsyncClient", _client(appels, []))

    res = await instagram.publier_image("https://blackturf.fr/visuels/quinte.jpg", "Bonjour")

    assert res.publie is False
    assert "simulation" in (res.raison or "")
    assert appels == []  # rien n'est parti chez Meta


async def test_publication_en_deux_temps_quand_elle_est_autorisee(monkeypatch):
    _configurer(monkeypatch, actif=True)
    appels: list[str] = []
    reponses = [
        _Reponse(200, {"id": "conteneur-1"}),
        _Reponse(200, {"id": "media-9"}),
    ]
    monkeypatch.setattr(instagram.httpx, "AsyncClient", _client(appels, reponses))

    res = await instagram.publier_image("https://blackturf.fr/visuels/quinte.jpg", "Bonjour")

    assert res.publie is True
    assert res.media_id == "media-9"
    assert appels[0].endswith("/media")
    assert appels[1].endswith("/media_publish")


async def test_sans_jeton_rien_ne_part(monkeypatch):
    _configurer(monkeypatch, jeton="", actif=True)
    res = await instagram.publier_image("https://blackturf.fr/visuels/quinte.jpg", "Bonjour")
    assert res.publie is False
    assert "jeton" in (res.raison or "")


async def test_image_non_https_refusee_avant_tout_appel(monkeypatch):
    """Meta refuse une URL non https, et un lien local ne lui serait pas accessible."""
    _configurer(monkeypatch, actif=True)
    appels: list[str] = []
    monkeypatch.setattr(instagram.httpx, "AsyncClient", _client(appels, []))

    res = await instagram.publier_image("http://localhost:3000/visuels/quinte.jpg", "Bonjour")

    assert res.publie is False
    assert "https" in (res.raison or "")
    assert appels == []


async def test_legende_trop_longue_tronquee_au_lieu_de_perdre_le_post(monkeypatch):
    _configurer(monkeypatch, actif=True)
    longue = "a" * 3000
    tronquee = instagram._tronquer(longue)
    assert len(tronquee) == instagram.MAX_LEGENDE
    assert tronquee.endswith("…")


async def test_un_refus_de_meta_ne_leve_jamais(monkeypatch):
    """Le job est programmé : une exception y arrêterait les tâches suivantes."""
    _configurer(monkeypatch, actif=True)
    appels: list[str] = []
    monkeypatch.setattr(
        instagram.httpx,
        "AsyncClient",
        _client(appels, [_Reponse(400, {}, "Invalid OAuth access token")]),
    )

    res = await instagram.publier_image("https://blackturf.fr/visuels/quinte.jpg", "Bonjour")

    assert res.publie is False
    assert "conteneur" in (res.raison or "")


async def test_hote_par_defaut_est_la_voie_sans_page_facebook(monkeypatch):
    """
    La voie « Instagram Login » (graph.instagram.com) n'exige AUCUNE Page Facebook.
    L'autre voie, graph.facebook.com, l'impose — et son interface de liaison est
    défaillante côté Meta. Le défaut ne doit donc jamais rebasculer par inadvertance.
    """
    monkeypatch.setattr(instagram.settings, "instagram_api_host", "", raising=False)
    assert instagram._base().startswith("https://graph.instagram.com/")


async def test_hote_reste_configurable(monkeypatch):
    monkeypatch.setattr(instagram.settings, "instagram_api_host", "graph.facebook.com", raising=False)
    assert instagram._base().startswith("https://graph.facebook.com/")
