"""Le fichier nginx que la suite inspecte doit être celui que nginx sert.

`docker-compose.prod.yml` monte `nginx/nginx.runtime.conf` sur
`/etc/nginx/nginx.conf`, mais les tests de configuration lisent
`nginx/nginx.prod.conf`. Les deux fichiers sont identiques aujourd'hui — donc
les invariants (limites de débit, en-têtes, TLS) sont bien vérifiés. Rien ne le
garantit demain : le jour où quelqu'un corrige `prod.conf` sans toucher
`runtime.conf`, la suite validera un fichier que personne ne sert, et restera
verte pendant que la production tourne sur l'ancienne configuration.

Ce test verrouille la correspondance, sans imposer laquelle des deux est la
source : il exige seulement qu'elles ne divergent pas en silence.
"""
from __future__ import annotations

import os
import pathlib
import re

import pytest

RACINE = pathlib.Path(os.environ.get("BLACKTURF_BACKEND_DIR")
                      or pathlib.Path(__file__).resolve().parents[1]).parent
COMPOSE_PROD = RACINE / "docker-compose.prod.yml"
CONF_INSPECTEE = RACINE / "nginx" / "nginx.prod.conf"


def _conf_montee_sur_nginx() -> str | None:
    """Chemin (relatif au dépôt) monté sur /etc/nginx/nginx.conf, s'il existe."""
    texte = COMPOSE_PROD.read_text(encoding="utf-8")
    m = re.search(r"^\s*-\s*\./(\S+):/etc/nginx/nginx\.conf(?::\w+)?\s*$", texte, re.M)
    return m.group(1) if m else None


def test_la_conf_nginx_testee_est_bien_celle_qui_est_servie():
    # `nginx.runtime.conf` est GITIGNORÉ : il n'existe que sur le serveur, et une
    # copie oubliée dans un checkout de dev serait périmée par construction — la
    # comparer donnerait une fausse alerte. On n'exerce donc ce test que là où les
    # fichiers réellement déployés sont montés (gate de prod, BLACKTURF_BACKEND_DIR).
    if not os.environ.get("BLACKTURF_BACKEND_DIR"):
        pytest.skip("hors gate de déploiement : la conf servie n'est pas dans le dépôt")
    if not COMPOSE_PROD.exists() or not CONF_INSPECTEE.exists():
        pytest.skip("compose ou nginx.prod.conf absents de ce contexte "
                    "(monter les descripteurs pour exercer ce test)")

    chemin_monte = _conf_montee_sur_nginx()
    assert chemin_monte, (
        "aucun montage vers /etc/nginx/nginx.conf trouvé dans docker-compose.prod.yml : "
        "les tests de configuration nginx ne vérifient plus rien de servi")

    servie = RACINE / chemin_monte
    if not servie.exists():
        pytest.skip(f"{chemin_monte} absent de ce contexte")

    if servie.resolve() == CONF_INSPECTEE.resolve():
        return  # même fichier : rien à prouver de plus

    assert servie.read_text(encoding="utf-8") == CONF_INSPECTEE.read_text(encoding="utf-8"), (
        f"nginx sert '{chemin_monte}' mais la suite inspecte "
        f"'{CONF_INSPECTEE.name}', et les deux ont divergé : toute correction "
        "apportée au fichier testé ne s'applique pas à la production.")
