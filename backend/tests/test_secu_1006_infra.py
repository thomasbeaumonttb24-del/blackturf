"""Durcissement d'infrastructure du 06/10 : exemption interne du rendu serveur,
plafonds de conteneurs, Redis.

Le défaut fermé ici : le rendu serveur de TOUTES les pages publiques lisait l'API
par le domaine public, donc sous une seule adresse, dans un seul seau de quota.
Un client en boucle sur une route rendue côté serveur vidait ce seau ; chaque
lecture SSR prenait un 429 et les pages sortaient vides pour tout le monde.
"""
from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from api.middleware import rate_limit, throttle

from ._descripteurs_deploiement import COMPOSE_BASE, COMPOSE_PROD, RACINE, exiger

SECRET = "s" * 48


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
        self.appels = 0

    def pipeline(self):
        self.appels += 1
        return _Pipeline(self.valeur)


def _requete(entetes: dict, hote: str = "172.18.0.7"):
    return SimpleNamespace(client=SimpleNamespace(host=hote), headers=entetes)


@pytest.fixture
def secret_regle(monkeypatch):
    monkeypatch.setattr(throttle, "get_settings", lambda: SimpleNamespace(bt_secret_interne=SECRET))


@pytest.mark.asyncio
async def test_le_rendu_serveur_n_est_pas_compte(secret_regle):
    redis = _Redis(rate_limit.PUBLIC_PAR_MINUTE * 10)  # seau déjà vidé
    await rate_limit.rate_limit_public(_requete({"x-bt-interne": SECRET}), redis)
    assert redis.appels == 0, "un appel interne ne doit même pas toucher le compteur"


@pytest.mark.asyncio
async def test_un_mauvais_secret_reste_compte(secret_regle):
    from fastapi import HTTPException
    redis = _Redis(rate_limit.PUBLIC_PAR_MINUTE + 1)
    for entetes in ({}, {"x-bt-interne": ""}, {"x-bt-interne": SECRET[:-1] + "x"}):
        with pytest.raises(HTTPException) as exc:
            await rate_limit.rate_limit_public(_requete(entetes), redis)
        assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_secret_vide_exemption_coupee(monkeypatch):
    """Vide côté réglages = fonction coupée, même si l'appelant envoie un en-tête vide."""
    from fastapi import HTTPException
    monkeypatch.setattr(throttle, "get_settings", lambda: SimpleNamespace(bt_secret_interne=""))
    for entetes in ({"x-bt-interne": ""}, {"x-bt-interne": "nimporte"}):
        assert throttle.est_appel_interne(_requete(entetes)) is False
    with pytest.raises(HTTPException):
        await rate_limit.rate_limit_public(_requete({"x-bt-interne": ""}),
                                           _Redis(rate_limit.PUBLIC_PAR_MINUTE + 1))


@pytest.mark.asyncio
async def test_le_login_ne_beneficie_jamais_de_l_exemption(secret_regle):
    """Le rendu serveur ne se connecte jamais : un secret volé ne doit pas devenir
    un passe-droit de credential-stuffing."""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await throttle.rate_limit_auth(_requete({"x-bt-interne": SECRET}), _Redis(11))
    assert exc.value.status_code == 429


def test_ip_cliente_sans_nginx():
    """Appel direct sur api:8000 (pas de X-Real-IP) : l'adresse de socket fait foi,
    et un X-Real-IP vide ne range pas tout le monde sous une clé vide."""
    assert throttle._client_ip(_requete({})) == "172.18.0.7"
    assert throttle._client_ip(_requete({"x-real-ip": "  "})) == "172.18.0.7"
    assert throttle._client_ip(_requete({"x-real-ip": "203.0.113.4"})) == "203.0.113.4"


def test_secret_interne_trop_court_refuse(monkeypatch):
    from pydantic import ValidationError

    from api.config import Settings
    monkeypatch.setenv("BT_SECRET_INTERNE", "court")
    with pytest.raises(ValidationError):
        Settings()
    monkeypatch.setenv("BT_SECRET_INTERNE", "")
    assert Settings().bt_secret_interne == ""


def test_le_nom_de_service_api_est_un_hote_accepte():
    """Sans `api` dans TrustedHost, chaque lecture SSR interne prendrait un 400."""
    src = exiger(RACINE / "backend" / "api" / "main.py")
    bloc = re.search(r"allowed_hosts=\[(.*?)\]", src, re.S)
    assert bloc and '"api"' in bloc.group(1)


# --- compose ------------------------------------------------------------------

def _bloc(texte: str, service: str) -> str:
    m = re.search(rf"^  {service}:\n(.*?)(?=^  \S|^\S)", texte, re.S | re.M)
    assert m, f"service `{service}` introuvable"
    return m.group(1)


def _services(texte: str) -> list[str]:
    corps = re.search(r"^services:\n(.*?)(?=^\S)", texte, re.S | re.M).group(1)
    return re.findall(r"^  (\w+):\s*$", corps, re.M)


def test_chaque_service_de_prod_a_un_plafond_de_pid():
    texte = exiger(COMPOSE_PROD)
    services = _services(texte)
    assert len(services) >= 8, f"lecture des services cassée : {services}"
    # deploy.resources.limits.pids et non pids_limit : compose refuse les deux ensemble
    # dès qu'un bloc deploy.resources.limits existe (projet invalide, déploiement cassé).
    sans = [s for s in services if not re.search(r"^\s+pids:\s*\d+", _bloc(texte, s), re.M)]
    assert not re.search(r"^\s+pids_limit:", texte, re.M), "pids_limit interdit à côté de deploy.resources.limits"
    assert not sans, f"services sans plafond de PID : {sans}"
    sans_nnp = [s for s in services if "no-new-privileges:true" not in _bloc(texte, s)]
    assert not sans_nnp, f"services sans no-new-privileges : {sans_nnp}"


def test_le_secret_interne_atteint_api_et_frontend_mais_pas_le_build():
    texte = exiger(COMPOSE_PROD)
    front = _bloc(texte, "frontend")
    assert re.search(r"^\s+- API_URL_INTERNE=http://api:8000\s*$", front, re.M)
    assert re.search(r"^\s+- BT_SECRET_INTERNE=\$\{BT_SECRET_INTERNE:-\}\s*$", front, re.M)
    args = re.search(r"^\s+args:\n(.*?)(?=^\s{4}\w)", front, re.S | re.M).group(1)
    assert "SECRET" not in args and "INTERNE" not in args, (
        "un argument de build finit dans une couche d'image : le secret n'y a pas sa place")
    assert re.search(r"^\s+- BT_SECRET_INTERNE=", _bloc(texte, "api"), re.M)


def test_redis_sans_mot_de_passe_en_ligne_de_commande_du_healthcheck():
    for chemin in (COMPOSE_BASE, COMPOSE_PROD):
        bloc = _bloc(exiger(chemin), "redis")
        test = re.search(r"^\s+test:\s*(.*)$", bloc, re.M).group(1)
        assert '"-a"' not in test and "PASSWORD" not in test, f"{chemin.name} : {test}"
        assert "REDISCLI_AUTH=" in bloc
        for cmd in ("FLUSHALL", "DEBUG"):
            assert re.search(rf'- --rename-command\s*\n\s+- {cmd}\s*\n\s+- ""', bloc), (
                f"{chemin.name} : {cmd} n'est pas désactivé")
    assert "volatile-lru" in _bloc(exiger(COMPOSE_PROD), "redis")


def test_le_scheduler_n_est_plus_a_512m():
    bloc = _bloc(exiger(COMPOSE_PROD), "scheduler")
    m = re.search(r"limits:\s*\n(?:\s*(?:#|pids:).*\n)*\s*memory:\s*(\d+)([MG])", bloc)
    assert m, "limite mémoire du scheduler introuvable"
    mo = int(m.group(1)) * (1024 if m.group(2) == "G" else 1)
    assert mo >= 1024, "le scheduler était tué chaque nuit par l'OOM killer à 512M"
