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
    def __init__(self, status=200, payload=None, texte="", headers=None, contenu=b""):
        self.status_code = status
        self._payload = payload or {}
        self.text = texte
        self.headers = headers or {}
        self.content = contenu

    def json(self):
        return self._payload


JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def _image_ok():
    return _Reponse(200, headers={"content-type": "image/jpeg"}, contenu=JPEG)


def _vers_meta(url: str) -> bool:
    return url.startswith("https://graph.")


def _client(appels, reponses, statuts=None, corps=None, images=None, image=None):
    """
    Double du client httpx.

    `reponses` répond aux POST (conteneur, puis publication). `statuts` répond aux GET
    d'état du conteneur — l'appel que Meta impose ENTRE les deux : `POST /media`
    n'enregistre qu'une URL, et publier avant que Meta ait fini de télécharger l'image
    échoue en 400 / 9007 / 2207027. Par défaut le conteneur est prêt du premier coup :
    un test qui ne porte pas sur l'attente n'a pas à la décrire.

    Les GET vers le SITE (téléchargement préalable de l'image) ne sont pas mêlés à
    `appels`, qui ne décrit que le dialogue avec Meta : ils vont dans `images`, et
    `image` fixe la réponse du site (un JPEG valide par défaut).
    """

    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, data=None):
            appels.append(url)
            if corps is not None:
                corps.append(data or {})
            return reponses.pop(0)

        async def get(self, url, params=None, **kw):
            if not _vers_meta(url):
                if images is not None:
                    images.append(url)
                return image if image is not None else _image_ok()
            appels.append(url)
            if statuts is None:
                return _Reponse(200, {"status_code": "FINISHED"})
            return statuts.pop(0)

    return _C


def _sans_attente(monkeypatch):
    """Neutralise les pauses : l'attente réelle va jusqu'à 100 s (25 essais de 4 s)."""

    async def _dors_pas(_):
        return None

    monkeypatch.setattr(instagram.asyncio, "sleep", _dors_pas)


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
    """
    Trois appels, dans cet ordre : création du conteneur, état du conteneur, publication.

    Le nom dit « deux temps » parce que c'est le vocabulaire de Meta (media puis
    media_publish) ; la consultation d'état s'intercale entre les deux depuis f8e45b6.
    """
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
    assert appels[1].endswith("/conteneur-1")  # l'état est bien consulté...
    assert appels[2].endswith("/media_publish")  # ...AVANT de publier


async def test_on_attend_que_meta_ait_prepare_le_conteneur(monkeypatch):
    """
    L'invariant de f8e45b6 : tant que le conteneur n'est pas FINISHED, on ne publie pas.

    Sans cette attente, Meta refusait CHAQUE publication (400 / 9007 / 2207027) : le
    défaut était invisible en simulation, où l'on s'arrête avant l'appel qui échoue.
    """
    _configurer(monkeypatch, actif=True)
    _sans_attente(monkeypatch)
    appels: list[str] = []
    statuts = [
        _Reponse(200, {"status_code": "IN_PROGRESS"}),
        _Reponse(200, {"status_code": "IN_PROGRESS"}),
        _Reponse(200, {"status_code": "FINISHED"}),
    ]
    reponses = [_Reponse(200, {"id": "conteneur-1"}), _Reponse(200, {"id": "media-9"})]
    monkeypatch.setattr(instagram.httpx, "AsyncClient", _client(appels, reponses, statuts))

    res = await instagram.publier_image("https://blackturf.fr/visuels/quinte.jpg", "Bonjour")

    assert res.publie is True
    # On a bien patienté : trois consultations d'état, et la publication en dernier.
    assert [a.rsplit("/", 1)[-1] for a in appels] == [
        "media",
        "conteneur-1",
        "conteneur-1",
        "conteneur-1",
        "media_publish",
    ]


async def test_un_conteneur_en_erreur_n_est_jamais_publie(monkeypatch):
    _configurer(monkeypatch, actif=True)
    _sans_attente(monkeypatch)
    appels: list[str] = []
    statuts = [_Reponse(200, {"status_code": "ERROR", "status": "Media download failed"})]
    monkeypatch.setattr(
        instagram.httpx,
        "AsyncClient",
        _client(appels, [_Reponse(200, {"id": "conteneur-1"})], statuts),
    )

    res = await instagram.publier_image("https://blackturf.fr/visuels/quinte.jpg", "Bonjour")

    assert res.publie is False
    assert "ERROR" in (res.raison or "")
    assert "Media download failed" in (res.raison or "")
    assert not any(a.endswith("/media_publish") for a in appels)


async def test_conteneur_jamais_pret_abandonne_sans_publier(monkeypatch):
    """Meta peut ne jamais finir : on abandonne au lieu de publier dans le vide."""
    _configurer(monkeypatch, actif=True)
    _sans_attente(monkeypatch)
    appels: list[str] = []

    class _ToujoursEnCours(list):
        def pop(self, _=0):
            return _Reponse(200, {"status_code": "IN_PROGRESS"})

    monkeypatch.setattr(
        instagram.httpx,
        "AsyncClient",
        _client(appels, [_Reponse(200, {"id": "conteneur-1"})], _ToujoursEnCours()),
    )

    res = await instagram.publier_image("https://blackturf.fr/visuels/quinte.jpg", "Bonjour")

    assert res.publie is False
    assert "pas prêt" in (res.raison or "")
    assert not any(a.endswith("/media_publish") for a in appels)


async def test_une_panne_reseau_pendant_l_attente_ne_leve_pas(monkeypatch):
    _configurer(monkeypatch, actif=True)
    appels: list[str] = []

    _Base = _client(appels, [_Reponse(200, {"id": "conteneur-1"})])

    class _C(_Base):
        async def get(self, url, params=None, **kw):
            if not _vers_meta(url):
                return _image_ok()
            appels.append(url)
            raise instagram.httpx.ConnectError("connexion coupee")

    monkeypatch.setattr(instagram.httpx, "AsyncClient", _C)

    res = await instagram.publier_image("https://blackturf.fr/visuels/quinte.jpg", "Bonjour")

    assert res.publie is False
    assert "illisible" in (res.raison or "")
    assert "ConnectError" in (res.raison or "")
    assert not any(a.endswith("/media_publish") for a in appels)


async def test_une_faute_de_programmation_n_est_pas_maquillee_en_panne_reseau(monkeypatch):
    """
    Le 2026-09-03, ce fichier lui-même échouait sur « état du conteneur illisible :
    AttributeError » — le double n'avait pas de `get`. La raison, identique à celle
    d'une panne réseau, laissait croire à une publication cassée en production. Une
    erreur qui n'est pas de transport doit se nommer.
    """
    _configurer(monkeypatch, actif=True)
    appels: list[str] = []

    _Base = _client(appels, [_Reponse(200, {"id": "conteneur-1"})])

    class _C(_Base):
        async def get(self, url, params=None, **kw):
            if not _vers_meta(url):
                return _image_ok()
            raise AttributeError("boum")

    monkeypatch.setattr(instagram.httpx, "AsyncClient", _C)

    res = await instagram.publier_image("https://blackturf.fr/visuels/quinte.jpg", "Bonjour")

    assert res.publie is False
    assert "illisible" not in (res.raison or "")
    assert "AttributeError: boum" in (res.raison or "")


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


async def test_le_jeton_reel_en_base_est_inatteignable_sous_pytest(monkeypatch):
    """Le 2026-08-26, la gate exécutée dans l'image de production a publié pour de
    bon vers Meta : `_configure()` lisait le jeton en base — donc la base de PROD —
    alors que le test croyait n'avoir aucun jeton. Le verrou porte sur la lecture
    en base, pas sur l'appel réseau (les tests le simulent déjà)."""
    _configurer(monkeypatch, jeton="", actif=True)

    def _interdit(*a, **kw):
        raise AssertionError("la base a été interrogée pour un jeton depuis un test")

    monkeypatch.setattr("db.database.AsyncSessionLocal", _interdit)

    jeton, _ = await instagram._configure()

    assert jeton is None
    res = await instagram.publier_image("https://blackturf.fr/visuels/quinte.jpg", "Bonjour")
    assert res.publie is False
    assert "jeton" in (res.raison or "")


# ── Stories ─────────────────────────────────────────────────────────────────
# Une story n'est pas un post de fil : c'est le MÊME endpoint, avec
# `media_type=STORIES` à la création du conteneur. Sans ce champ, l'API crée un post
# de fil — c'est ce qui a empêché toute publication de story jusqu'au 2026-09-06,
# et le défaut est invisible côté code : l'appel réussit, il publie simplement au
# mauvais endroit.

async def test_une_story_declare_son_type_a_la_creation_du_conteneur(monkeypatch):
    _configurer(monkeypatch, actif=True)
    appels: list[str] = []
    corps: list[dict] = []
    reponses = [_Reponse(200, {"id": "conteneur-s"}), _Reponse(200, {"id": "media-s"})]
    monkeypatch.setattr(instagram.httpx, "AsyncClient", _client(appels, reponses, corps=corps))

    res = await instagram.publier_story("https://blackturf.fr/visuels/story.jpg?jour=2026-09-05")

    assert res.publie is True and res.media_id == "media-s"
    assert corps[0]["media_type"] == "STORIES", "sans ce champ, Meta publie dans le FIL"
    # Le jour arrive intact ; la clé d'envoi s'ajoute derrière (2026-09-13).
    assert "story.jpg?jour=2026-09-05&envoi=" in corps[0]["image_url"]


async def test_une_story_ne_transporte_aucune_legende(monkeypatch):
    """Une story n'affiche pas de légende, et Meta ne documente pas ce qu'il fait du
    champ dans ce cas. Envoyer sur une publication de marque un champ dont on ignore
    le devenir, c'est deux fois trop de risque pour zéro bénéfice."""
    _configurer(monkeypatch, actif=True)
    corps: list[dict] = []
    reponses = [_Reponse(200, {"id": "c"}), _Reponse(200, {"id": "m"})]
    monkeypatch.setattr(instagram.httpx, "AsyncClient", _client([], reponses, corps=corps))

    await instagram.publier_story("https://blackturf.fr/visuels/story.jpg")

    assert "caption" not in corps[0]


async def test_le_fil_garde_sa_legende_et_ne_declare_pas_de_type(monkeypatch):
    """Garde de non-régression : l'ajout des stories ne doit rien changer au fil."""
    _configurer(monkeypatch, actif=True)
    corps: list[dict] = []
    reponses = [_Reponse(200, {"id": "c"}), _Reponse(200, {"id": "m"})]
    monkeypatch.setattr(instagram.httpx, "AsyncClient", _client([], reponses, corps=corps))

    await instagram.publier_image("https://blackturf.fr/visuels/quinte.jpg", "Bonjour")

    assert corps[0]["caption"] == "Bonjour"
    assert "media_type" not in corps[0]


async def test_une_story_ne_part_pas_non_plus_sans_interrupteur(monkeypatch):
    """Le garde-fou central vaut aussi pour les stories : la nouvelle voie ne doit pas
    contourner l'interrupteur."""
    _configurer(monkeypatch, actif=False)
    appels: list[str] = []
    monkeypatch.setattr(instagram.httpx, "AsyncClient", _client(appels, []))

    res = await instagram.publier_story("https://blackturf.fr/visuels/story.jpg")

    assert res.publie is False
    assert "simulation" in (res.raison or "")
    assert appels == []


# ── Téléchargement de l'image AVANT Meta ────────────────────────────────────
# 2026-09-13 : la tuile hebdomadaire n'est jamais partie. Composée à la demande en
# 8,5 s, elle n'arrivait pas avant que Meta abandonne (nginx : 499), et Meta refusait
# le conteneur (« Media download has failed ») six passages de suite. Le service fait
# désormais composer l'image lui-même, sur une URL à clé d'envoi que le site garde en
# mémoire, et ne confie à Meta que cette URL — donc des octets déjà vérifiés.


async def test_l_image_est_telechargee_avant_d_etre_confiee_a_meta(monkeypatch):
    _configurer(monkeypatch, actif=True)
    appels: list[str] = []
    corps: list[dict] = []
    images: list[str] = []
    reponses = [_Reponse(200, {"id": "c"}), _Reponse(200, {"id": "m"})]
    monkeypatch.setattr(
        instagram.httpx, "AsyncClient", _client(appels, reponses, corps=corps, images=images),
    )

    res = await instagram.publier_image(
        "https://blackturf.fr/visuels/mosaique/1-1?semaine=2026-09-12", "Bonjour",
    )

    assert res.publie is True
    assert len(images) == 1, "l'image doit être téléchargée une fois, avant Meta"
    # Meta reçoit EXACTEMENT l'URL que le service vient de faire composer : c'est elle
    # que le site garde en mémoire sous sa clé d'envoi.
    assert corps[0]["image_url"] == images[0]
    assert images[0].startswith("https://blackturf.fr/visuels/mosaique/1-1?semaine=2026-09-12&envoi=")


async def test_la_cle_d_envoi_s_ajoute_aux_parametres_existants(monkeypatch):
    """La story porte déjà `jour=` et `plans=` : ils doivent arriver intacts à la route,
    sinon ses contrôles 409 ne s'exercent plus."""
    _configurer(monkeypatch, actif=True)
    corps: list[dict] = []
    reponses = [_Reponse(200, {"id": "c"}), _Reponse(200, {"id": "m"})]
    monkeypatch.setattr(instagram.httpx, "AsyncClient", _client([], reponses, corps=corps))

    await instagram.publier_story("https://blackturf.fr/visuels/story.jpg?jour=2026-09-12&plans=279")

    url = corps[0]["image_url"]
    assert url.startswith("https://blackturf.fr/visuels/story.jpg?jour=2026-09-12&plans=279&envoi=")
    assert url.count("?") == 1


async def test_chaque_tentative_a_sa_propre_cle_d_envoi(monkeypatch):
    """Une clé réutilisée resservirait l'image d'une tentative précédente — donc
    potentiellement celle d'un bilan qui a changé depuis."""
    _configurer(monkeypatch, actif=True)
    images: list[str] = []
    reponses = [_Reponse(200, {"id": "c"}), _Reponse(200, {"id": "m"})] * 2
    monkeypatch.setattr(instagram.httpx, "AsyncClient", _client([], reponses, images=images))

    await instagram.publier_image("https://blackturf.fr/visuels/quinte.jpg", "a")
    await instagram.publier_image("https://blackturf.fr/visuels/quinte.jpg", "b")

    assert len(set(images)) == 2


async def test_une_image_refusee_par_le_site_ne_part_jamais_chez_meta(monkeypatch):
    """Un 409 (bilan différent de celui validé) ou un 503 (API absente) doit arrêter la
    publication AVANT Meta, avec la vraie raison — pas un « 400 » de Meta."""
    _configurer(monkeypatch, actif=True)
    appels: list[str] = []
    refus = _Reponse(409, texte="Bilan différent de celui validé (plans=278, attendu=279)")
    monkeypatch.setattr(instagram.httpx, "AsyncClient", _client(appels, [], image=refus))

    res = await instagram.publier_story("https://blackturf.fr/visuels/story.jpg?jour=2026-09-12&plans=279")

    assert res.publie is False
    assert "409" in (res.raison or "")
    assert "Bilan différent" in (res.raison or "")
    assert appels == [], "rien ne doit partir chez Meta"


async def test_une_image_png_n_est_pas_confiee_a_meta(monkeypatch):
    """La route retombe sur du PNG si la conversion JPEG échoue ; Meta le refuserait."""
    _configurer(monkeypatch, actif=True)
    appels: list[str] = []
    png = _Reponse(200, headers={"content-type": "image/png"}, contenu=b"\x89PNG\r\n")
    monkeypatch.setattr(instagram.httpx, "AsyncClient", _client(appels, [], image=png))

    res = await instagram.publier_image("https://blackturf.fr/visuels/quinte.jpg", "Bonjour")

    assert res.publie is False
    assert "JPEG" in (res.raison or "")
    assert appels == []


async def test_un_site_injoignable_ne_leve_pas(monkeypatch):
    _configurer(monkeypatch, actif=True)
    appels: list[str] = []
    _Base = _client(appels, [])

    class _C(_Base):
        async def get(self, url, params=None, **kw):
            if not _vers_meta(url):
                raise instagram.httpx.ReadTimeout("trop long")
            return await super().get(url, params, **kw)

    monkeypatch.setattr(instagram.httpx, "AsyncClient", _C)

    res = await instagram.publier_image("https://blackturf.fr/visuels/quinte.jpg", "Bonjour")

    assert res.publie is False
    assert "injoignable" in (res.raison or "")
    assert appels == []


async def test_le_refus_de_meta_garde_son_explication(monkeypatch):
    """« création du conteneur refusée (400) » a masqué six passages de suite que Meta
    n'arrivait pas à télécharger l'image : l'explication de Meta doit aller en base."""
    _configurer(monkeypatch, actif=True)
    erreur = {"error": {"message": "Only photo or video can be accepted as media type.",
                        "error_user_title": "Media download has failed."}}
    monkeypatch.setattr(
        instagram.httpx, "AsyncClient", _client([], [_Reponse(400, erreur)]),
    )

    res = await instagram.publier_image("https://blackturf.fr/visuels/quinte.jpg", "Bonjour")

    assert res.publie is False
    assert res.raison == "création du conteneur refusée (400) : Media download has failed."
