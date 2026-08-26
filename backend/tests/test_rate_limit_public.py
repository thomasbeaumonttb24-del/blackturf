"""Plafond public par IP — il protège de l'aspiration, pas du visiteur.

Constaté le 26/08/2026 : des 429 sur des pages publiques. Deux causes, toutes
deux vérifiées, et aucune n'est un abus :
  - le PARTAGE D'IP (NAT d'entreprise ou d'opérateur mobile) : tous les lecteurs
    additionnent leurs requêtes dans le même seau ;
  - le RENDU SERVEUR : `NEXT_PUBLIC_API_URL` pointe sur le domaine public, donc
    les fetch SSR du conteneur Next repassent par nginx, qui pose un `X-Real-IP`
    unique — celui du conteneur. Toutes les pages rendues côté serveur partagent
    alors UNE seule IP, visiteurs et robots confondus.
"""
import pytest

from api.middleware import rate_limit


def test_plafond_public_couvre_une_session_de_lecture():
    """Une page publique déclenche ~2 appels comptés ici (aperçu + bilan, ou
    programme + aperçu du programme). Derrière une IP partagée — NAT, ou le
    conteneur Next qui rend toutes les pages côté serveur — il faut couvrir
    plusieurs dizaines de pages par minute pour ne jamais renvoyer un 429 à un
    lecteur ordinaire."""
    APPELS_PAR_PAGE = 2
    PAGES_PAR_MINUTE_SOUS_UNE_IP = 60
    assert rate_limit.PUBLIC_PAR_MINUTE >= APPELS_PAR_PAGE * PAGES_PAR_MINUTE_SOUS_UNE_IP


def test_plafond_public_reste_un_garde_fou():
    """…mais il reste un plafond : sans limite, un aspirateur ferait tourner la
    base à sa cadence. On borne donc aussi par le haut."""
    assert rate_limit.PUBLIC_PAR_MINUTE <= 600


@pytest.mark.asyncio
async def test_429_au_dela_du_plafond(monkeypatch):
    """Le compteur Redis pilote bien la décision : à PUBLIC_PAR_MINUTE + 1, on
    refuse — le garde-fou n'a pas été neutralisé en relevant le chiffre."""
    from fastapi import HTTPException

    class _Pipeline:
        def __init__(self, valeur):
            self.valeur = valeur

        def incr(self, _k):
            return self

        def expire(self, _k, _s, **_kw):
            return self

        async def execute(self):
            return [self.valeur, True]

    class _Redis:
        def __init__(self, valeur):
            self.valeur = valeur

        def pipeline(self):
            return _Pipeline(self.valeur)

    class _Request:
        client = type("C", (), {"host": "203.0.113.9"})()
        headers: dict = {}

    # Juste sous le plafond : passe.
    await rate_limit.rate_limit_public(_Request(), _Redis(rate_limit.PUBLIC_PAR_MINUTE))

    # Juste au-dessus : refusé.
    with pytest.raises(HTTPException) as exc:
        await rate_limit.rate_limit_public(_Request(), _Redis(rate_limit.PUBLIC_PAR_MINUTE + 1))
    assert exc.value.status_code == 429
    assert exc.value.headers.get("Retry-After") == "60"


@pytest.mark.asyncio
async def test_fenetre_fixe_le_ttl_nest_pose_qu_a_la_creation():
    """Le TTL doit être posé avec `nx=True`.

    Réarmé à chaque appel, il faisait une fenêtre GLISSANTE : le compteur ne
    retombait jamais à zéro tant que l'IP appelait, donc une fois le plafond
    franchi elle restait bloquée indéfiniment — un simple navigateur qui recharge
    entretenait son propre 429. C'est ce qui rendait les 429 du 26/08/2026
    permanents au lieu de durer une minute."""
    from api.middleware import rate_limit as rl

    appels = []

    class _Pipeline:
        def incr(self, _k):
            return self

        def expire(self, _k, ttl, **kwargs):
            appels.append((ttl, kwargs))
            return self

        async def execute(self):
            return [1, True]

    class _Redis:
        def pipeline(self):
            return _Pipeline()

    class _Request:
        client = type("C", (), {"host": "203.0.113.10"})()
        headers: dict = {}

    await rl.rate_limit_public(_Request(), _Redis())

    assert appels, "aucun TTL posé"
    for ttl, kwargs in appels:
        assert kwargs.get("nx") is True, f"TTL {ttl}s réarmé à chaque appel → fenêtre glissante"
