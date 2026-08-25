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


def _descripteurs_presents() -> list[pathlib.Path]:
    """Fichiers de déploiement lisibles depuis ce contexte d'exécution.

    L'image de prod ne contient QUE `/app` : ni les compose, ni le Dockerfile
    (le gate ne monte que `tests/`). `_commandes_uvicorn()` renvoyait alors une
    liste vide et le test échouait sur « aucune commande uvicorn trouvée » —
    un rouge permanent qui ne signalait aucun défaut de configuration et qui
    finissait par masquer les vrais (constaté le 2026-08-19).

    Pour exercer VRAIMENT l'invariant depuis l'image, monter les descripteurs :
        -e BLACKTURF_BACKEND_DIR=/app \\
        -v /opt/blackturf/docker-compose.yml:/docker-compose.yml:ro \\
        -v /opt/blackturf/docker-compose.prod.yml:/docker-compose.prod.yml:ro \\
        -v /opt/blackturf/backend/Dockerfile:/backend/Dockerfile:ro
    """
    return [p for p in (COMPOSE_BASE, COMPOSE_PROD, DOCKERFILE) if p.exists()]


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
    if not _descripteurs_presents():
        pytest.skip("compose et Dockerfile absents de ce contexte (image sans le dépôt)")
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


def test_les_variables_lues_par_le_code_atteignent_les_conteneurs():
    """Une variable absente du bloc `environment:` n'atteint JAMAIS le conteneur.

    Le compose ne transmet QUE ce qu'il énumère : `.env` sert à résoudre
    `${...}`, pas à peupler l'environnement du conteneur. La violation est
    parfaitement silencieuse — le réglage prend sa valeur par défaut et personne
    n'en sait rien. C'est ce qui avait fait vivre les jetons d'accès 12 h au lieu
    de 60 min, et ce qui aurait envoyé les notifications d'abonnement sur
    `admin@blackturf.fr`, une adresse que personne ne lit, alors que `.env`
    portait la bonne (2026-08-20).
    """
    for chemin in (COMPOSE_BASE, COMPOSE_PROD):
        texte = _lire(chemin)
        assert "ADMIN_EMAIL=${ADMIN_EMAIL}" in texte, (
            f"{chemin.name} : ADMIN_EMAIL n'est transmis à aucun conteneur — "
            "les e-mails de supervision des abonnements partiraient sur la "
            "valeur par défaut du code."
        )


def test_la_fenetre_de_retraining_atteint_le_worker():
    """Le retrain tourne dans le WORKER : le réglage doit y être énuméré.

    Absent du bloc `environment:`, `RETRAIN_HISTORY_MONTHS` retomberait sur le
    défaut du code sans que rien ne le dise — et une fenêtre trop courte fait
    RÉTRÉCIR le dataset d'entraînement d'une version à l'autre (42 285 partants
    le 17/08/2026, 41 121 le 25/08) au lieu de le faire croître. Même silence
    pour `RETRAIN_MAX_ROWS`, dont l'absence lèverait le garde-fou mémoire.
    """
    texte = _lire(COMPOSE_PROD)
    motif = "^  worker:" + chr(10) + "(.*?)(?=^  [^ ])"
    bloc = re.search(motif, texte, re.S | re.M)
    if not bloc:
        pytest.skip("service `worker` introuvable dans le compose")
    for variable in ("RETRAIN_HISTORY_MONTHS", "RETRAIN_MAX_ROWS"):
        assert re.search(rf"^\s*-\s*{variable}=", bloc.group(1), re.M), (
            f"{variable} n'est pas transmis au worker : le retrain nocturne "
            "utiliserait le défaut du code, en silence."
        )


def test_le_service_db_declare_un_dev_shm_suffisant():
    """Docker plafonne /dev/shm à 64 Mo : PostgreSQL y meurt en silence.

    La mémoire partagée DYNAMIQUE des workers parallèles de PostgreSQL est
    allouée dans /dev/shm (~8 Mo par segment). Sous le défaut Docker, tout plan
    parallèle sur une grosse table échoue en « could not resize shared memory
    segment : No space left on device » — et comme l'échec avorte la transaction
    entière, l'erreur remontée à l'utilisateur porte sur une requête ANODINE
    exécutée ensuite. Panne du 20/08/2026 : /admin/api/dashboard en 500 et
    9 `post_course_sync` perdus par jour, pour un réglage absent d'un fichier.
    """
    fichiers = [p for p in (COMPOSE_BASE, COMPOSE_PROD) if p.exists()]
    if not fichiers:
        pytest.skip("aucun compose lisible dans ce contexte de test")
    for chemin in fichiers:
        bloc = re.search(r"^  db:\n(.*?)(?=^  \S)", _lire(chemin), re.S | re.M)
        assert bloc, f"service `db` introuvable dans {chemin.name}"
        m = re.search(r"^\s*shm_size:\s*(\d+)\s*(m|mb|g|gb)\s*$",
                      bloc.group(1), re.M | re.I)
        assert m, (f"{chemin.name} : le service `db` ne déclare pas `shm_size` — "
                   "PostgreSQL retombe sur les 64 Mo par défaut de Docker")
        mo = int(m.group(1)) * (1024 if m.group(2).lower() in ("g", "gb") else 1)
        assert mo >= 128, f"{chemin.name} : shm_size={mo} Mo, trop juste"
