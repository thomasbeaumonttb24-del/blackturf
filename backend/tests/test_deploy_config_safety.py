"""Invariants de configuration de déploiement dont la violation est silencieuse.

Ces réglages ne cassent rien quand ils sont faux : l'application démarre, les
tests passent, le site répond. Seule la posture de sécurité change — donc rien
ne le signale. On les verrouille ici.

Lecture par expressions régulières plutôt que par PyYAML : `yaml` n'est pas
déclaré dans requirements.txt (il n'est présent qu'en dépendance transitive), et
un test de sécurité ne doit pas dépendre d'un paquet qui peut disparaître à la
prochaine montée de version sans que personne ne le remarque.
"""
from __future__ import annotations

import os
import pathlib
import re

import pytest


RACINE = pathlib.Path(os.environ.get("BLACKTURF_BACKEND_DIR")
                      or pathlib.Path(__file__).resolve().parents[1]).parent
COMPOSE_BASE = RACINE / "docker-compose.yml"
COMPOSE_PROD = RACINE / "docker-compose.prod.yml"
DOCKERFILE = RACINE / "backend" / "Dockerfile"


def _lire(chemin: pathlib.Path) -> str:
    if not chemin.exists():
        pytest.skip(f"{chemin.name} absent de ce contexte de test")
    return chemin.read_text(encoding="utf-8")


def _publications_du_port_api(texte: str) -> list[str]:
    """Entrées `ports:` du service `api` qui publient le port 8000.

    On isole d'abord le bloc du service `api` (jusqu'au service suivant, repéré
    par son indentation) pour ne pas capter le mapping d'un autre service.
    """
    bloc = re.search(r"^  api:\n(.*?)(?=^  \S)", texte, re.S | re.M)
    if not bloc:
        pytest.skip("service `api` introuvable dans le compose")
    return [m.group(1).strip().strip('"\'')
            for m in re.finditer(r"^\s*-\s*(\S*8000\S*)\s*$", bloc.group(1), re.M)]


def _commandes_uvicorn() -> list[str]:
    commandes: list[str] = []
    for chemin in (COMPOSE_BASE, COMPOSE_PROD):
        if chemin.exists():
            commandes += [m.group(1).strip() for m in re.finditer(
                r"^\s*command:\s*(.*uvicorn.*)$", chemin.read_text(encoding="utf-8"), re.M)]
    if DOCKERFILE.exists():
        bloc = re.search(r"CMD \[(.*?)\]", DOCKERFILE.read_text(encoding="utf-8"), re.S)
        if bloc and "uvicorn" in bloc.group(1):
            commandes.append(" ".join(re.findall(r'"([^"]+)"', bloc.group(1))))
    return commandes


def test_le_port_api_n_est_publie_que_sur_la_loopback():
    """`--forwarded-allow-ips=*` fait confiance aux X-Forwarded-* de l'appelant.

    Publier le port de l'API sur 0.0.0.0 la rend joignable en direct depuis
    Internet, en contournant nginx : n'importe qui peut alors usurper
    X-Forwarded-For et fausser le rate-limiting et les logs d'IP. La seule chose
    qui l'empêchait était un pare-feu Hetzner en amont — une garantie extérieure
    au dépôt, donc invisible ici et susceptible de disparaître sans bruit.
    """
    for mapping in _publications_du_port_api(_lire(COMPOSE_BASE)):
        assert mapping.startswith("127.0.0.1:"), (
            f"Le port de l'API est publié sur '{mapping}' : joignable hors de "
            "l'hôte. Attendu un binding loopback '127.0.0.1:8000:8000' — ou "
            "alors retirer --forwarded-allow-ips=* de la commande uvicorn.")


def test_uvicorn_honore_les_entetes_du_reverse_proxy():
    """Sans --proxy-headers, uvicorn ignore X-Forwarded-Proto et construit ses
    redirections 307 en http://. Depuis une page https le navigateur refuse de
    les suivre (contenu mixte) : la requête meurt sans erreur visible — c'est ce
    qui vidait le centre de notifications."""
    commandes = _commandes_uvicorn()
    assert commandes, "aucune commande uvicorn trouvée"
    for cmd in commandes:
        assert "--proxy-headers" in cmd, f"--proxy-headers manquant : {cmd}"


def test_toute_confiance_aux_entetes_transferes_est_justifiee():
    """Si --forwarded-allow-ips=* est présent, le binding loopback DOIT l'être aussi."""
    if not any("--forwarded-allow-ips=*" in c for c in _commandes_uvicorn()):
        pytest.skip("aucune confiance globale accordée aux en-têtes transférés")
    exposees = [m for m in _publications_du_port_api(_lire(COMPOSE_BASE))
                if not m.startswith("127.0.0.1:")]
    assert not exposees, (
        "--forwarded-allow-ips=* combiné à un port publié publiquement "
        f"{exposees} : usurpation de X-Forwarded-For possible.")
