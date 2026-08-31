"""Localisation des descripteurs de déploiement, et refus de les sauter en silence.

Trois modules de tests (`test_deploy_config_safety`, `test_nginx_rate_limits`,
`test_nginx_conf_servie`) ne lisent pas du code Python mais les FICHIERS DE
DÉPLOIEMENT : les deux compose, le Dockerfile de l'API, `nginx/nginx.prod.conf`.
Ils vérifient des invariants dont la violation ne casse rien — le site répond,
la suite passe — et ne change que la posture de sécurité : port de l'API publié
hors loopback, quota nginx qui vide la console d'admin, variable jamais
transmise au conteneur.

Le défaut corrigé ici : ces fichiers vivent à la RACINE du dépôt, alors que
l'image de prod ne contient que `/app` (`tests/` est même dockerignoré). Lancé
dans son contexte naturel — l'image — pytest ne les trouvait pas et SAUTAIT :

    $ docker run --rm -v /opt/blackturf/backend:/app -w /app blackturf-api pytest -q
    1380 passed, 10 skipped                                    EXIT=0

Dix invariants de sécurité rendus muets, sortie verte, code de retour 0. Le mode
de panne était exactement celui que ces tests existent pour couvrir : une
violation silencieuse. Un `skipped` dans une suite de 1 400 lignes ne se voit pas.

Règle posée : un descripteur SUIVI PAR GIT est toujours disponible dans un
checkout du dépôt. S'il manque, ce n'est pas une particularité du contexte,
c'est que l'invocation ne monte pas le dépôt — et cela doit être ROUGE, pas
silencieux. Le contournement existe mais il est explicite :

    BLACKTURF_INVARIANTS_DEPLOIEMENT=optionnels pytest ...

`nginx/nginx.runtime.conf` échappe à la règle : il est gitignoré et n'existe que
sur le serveur, son absence en local est normale.

Invocation qui exerce réellement les dix invariants (depuis le VPS) :

    scripts/gate_tests.sh
"""
from __future__ import annotations

import os
import pathlib

import pytest

RACINE = pathlib.Path(os.environ.get("BLACKTURF_BACKEND_DIR")
                      or pathlib.Path(__file__).resolve().parents[1]).parent

COMPOSE_BASE = RACINE / "docker-compose.yml"
COMPOSE_PROD = RACINE / "docker-compose.prod.yml"
DOCKERFILE = RACINE / "backend" / "Dockerfile"
NGINX_PROD = RACINE / "nginx" / "nginx.prod.conf"

_VARIABLE = "BLACKTURF_INVARIANTS_DEPLOIEMENT"


def descripteurs_optionnels() -> bool:
    return os.environ.get(_VARIABLE, "").strip().lower() in ("optionnels", "1", "true", "oui")


def exiger(chemin: pathlib.Path) -> str:
    """Contenu du descripteur, ou ÉCHEC bruyant s'il n'est pas monté.

    Jamais `pytest.skip` : c'est précisément le silence qu'on ferme ici.
    """
    if chemin.exists():
        return chemin.read_text(encoding="utf-8")
    if descripteurs_optionnels():
        pytest.skip(f"{chemin.name} absent, {_VARIABLE}=optionnels")
    pytest.fail(
        f"{chemin.name} introuvable sous {RACINE} : cette exécution ne vérifie AUCUN "
        "invariant de déploiement (port de l'API, quotas nginx, variables transmises "
        "aux conteneurs). Monter le dépôt et poser BLACKTURF_BACKEND_DIR — voir "
        f"scripts/gate_tests.sh — ou assumer le trou avec {_VARIABLE}=optionnels.",
        pytrace=False,
    )
