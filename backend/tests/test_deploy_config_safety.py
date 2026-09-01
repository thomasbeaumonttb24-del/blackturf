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


from ._descripteurs_deploiement import (  # noqa: E402
    COMPOSE_BASE, COMPOSE_PROD, DOCKERFILE, RACINE, exiger as _lire,
)


def _publications_du_port_api(texte: str) -> list[str]:
    """Entrées `ports:` du service `api` qui publient le port 8000.

    On isole d'abord le bloc du service `api` (jusqu'au service suivant, repéré
    par son indentation) pour ne pas capter le mapping d'un autre service.
    """
    bloc = re.search(r"^  api:\n(.*?)(?=^  \S)", texte, re.S | re.M)
    assert bloc, ("service `api` introuvable dans le compose : le motif de lecture "
                  "ne reconnaît plus le fichier, donc l'invariant du binding loopback "
                  "ne vérifie plus rien (un skip le rendrait indolore).")
    return [m.group(1).strip().strip('"\'')
            for m in re.finditer(r"^\s*-\s*(\S*8000\S*)\s*$", bloc.group(1), re.M)]


def _exiger_les_descripteurs() -> None:
    """Les trois descripteurs sont suivis par git : leur absence est une erreur
    d'invocation, jamais une particularité du contexte. Cf.
    `_descripteurs_deploiement` pour le raisonnement complet et l'échappatoire.
    """
    for chemin in (COMPOSE_BASE, COMPOSE_PROD, DOCKERFILE):
        _lire(chemin)


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
    _exiger_les_descripteurs()
    commandes = _commandes_uvicorn()
    assert commandes, "aucune commande uvicorn trouvée"
    for cmd in commandes:
        assert "--proxy-headers" in cmd, f"--proxy-headers manquant : {cmd}"


def test_toute_confiance_aux_entetes_transferes_est_justifiee():
    """Si --forwarded-allow-ips=* est présent, le binding loopback DOIT l'être aussi.

    L'exigence des descripteurs vient AVANT le test de présence du drapeau : sans
    elle, une commande uvicorn introuvable donnait « aucune confiance globale
    accordée aux en-têtes transférés » — un skip qui se lit comme un satisfecit
    alors qu'il signalait qu'on n'avait rien lu du tout.
    """
    _exiger_les_descripteurs()
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
    assert bloc, ("service `worker` introuvable dans docker-compose.prod.yml : la "
                  "fenêtre de retraining n'est plus vérifiée par personne.")
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
    for chemin in (COMPOSE_BASE, COMPOSE_PROD):
        bloc = re.search(r"^  db:\n(.*?)(?=^  \S)", _lire(chemin), re.S | re.M)
        assert bloc, f"service `db` introuvable dans {chemin.name}"
        m = re.search(r"^\s*shm_size:\s*(\d+)\s*(m|mb|g|gb)\s*$",
                      bloc.group(1), re.M | re.I)
        assert m, (f"{chemin.name} : le service `db` ne déclare pas `shm_size` — "
                   "PostgreSQL retombe sur les 64 Mo par défaut de Docker")
        mo = int(m.group(1)) * (1024 if m.group(2).lower() in ("g", "gb") else 1)
        assert mo >= 128, f"{chemin.name} : shm_size={mo} Mo, trop juste"


def test_l_absence_de_descripteur_est_rouge_et_non_silencieuse():
    """Le garde-fou lui-même : sans les fichiers, on ÉCHOUE, on ne saute pas.

    C'est l'invariant du 2026-08-31 : `pytest` lancé dans l'image (son contexte
    naturel, sans le dépôt) affichait « 1380 passed, 10 skipped » et rendait 0,
    ayant sauté toute la vérification d'exposition réseau, des quotas nginx et
    des variables transmises aux conteneurs. Un skip ne se voit pas dans une
    suite de 1 400 lignes ; c'est exactement le mode de panne que ces tests
    existent pour couvrir.
    """
    from . import _descripteurs_deploiement as d

    # `pytest.fail` et `pytest.skip` lèvent tous deux des `BaseException` (Failed /
    # Skipped) : on capture donc à ce niveau, et c'est le TYPE qui tranche.
    with pytest.raises(BaseException) as capture:  # noqa: PT011
        d.exiger(RACINE / "descripteur-qui-n-existe-pas.yml")
    assert type(capture.value).__name__ == "Failed", (
        "l'absence d'un descripteur suivi par git doit lever un ÉCHEC, pas un "
        f"{type(capture.value).__name__}")


def test_la_cle_vapid_publique_atteint_le_build_du_frontend():
    """`NEXT_PUBLIC_*` est inliné AU BUILD : absent des `args`, il n'existe pas.

    Le mode de panne est muet et total. Sans cette variable dans le bundle,
    `pushManager.subscribe({applicationServerKey: undefined})` lève, le
    `catch` affichait « Erreur lors de l'activation », et AUCUN abonnement push
    n'a jamais pu être créé — 0 utilisateur sur 26 avec un `endpoint` au
    2026-08-31, pendant que 22 349 envois étaient journalisés en échec. Le
    déclarer seulement dans `environment:` ne suffit pas : au runtime, Next a
    déjà figé la valeur.
    """
    texte = _lire(COMPOSE_PROD)
    bloc = re.search(r"^  frontend:\n(.*?)(?=^  \S)", texte, re.S | re.M)
    assert bloc, "service `frontend` introuvable dans docker-compose.prod.yml"
    args = re.search(r"^\s+args:\n(.*?)(?=^\s{4}\w)", bloc.group(1), re.S | re.M)
    assert args and "NEXT_PUBLIC_VAPID_PUBLIC_KEY=" in args.group(1), (
        "NEXT_PUBLIC_VAPID_PUBLIC_KEY absent des `build.args` du frontend : la "
        "clé publique ne sera pas dans le bundle et personne ne pourra activer "
        "les notifications push.")

    dockerfile = _lire(RACINE / "frontend" / "Dockerfile")
    assert "ARG NEXT_PUBLIC_VAPID_PUBLIC_KEY" in dockerfile, (
        "le Dockerfile du frontend ne déclare pas l'ARG : compose la passe, "
        "Docker l'ignore, et la panne redevient silencieuse.")


# --- Budget de connexions PostgreSQL -----------------------------------------
# Le pool SQLAlchemy est un budget PARTAGÉ entre processus, mais il se configure
# service par service : rien, dans un fichier, ne rappelle qu'il existe un
# plafond commun. C'est ce qui a laissé passer 20 + 40 = 60 connexions par
# processus contre 47 disponibles au total.

_DEFAUT_POOL_SIZE = 4        # api.config.Settings.db_pool_size
_DEFAUT_MAX_OVERFLOW = 4     # api.config.Settings.db_max_overflow
# Valeur par défaut de PostgreSQL, jamais surchargée dans les compose. Ces
# sessions sont réservées au superutilisateur : le rôle applicatif `bt_app` n'y
# a pas droit, et c'est exactement ce que disait l'erreur du 31/08 —
# « remaining connection slots are reserved for roles with the SUPERUSER attribute ».
_RESERVE_SUPERUSER = 3
# Marge laissée aux sessions humaines et outillées : `psql` de diagnostic,
# `alembic upgrade` pendant un déploiement, workers de fond TimescaleDB (3
# sessions observées en production le 01/09).
_MARGE_HORS_APPLICATIF = 6

_SERVICES_APPLICATIFS = ("api", "scraper", "worker", "scheduler")


def _bloc_service(texte: str, service: str):
    return re.search(rf"^  {service}:\n(.*?)(?=^  \S)", texte, re.S | re.M)


def _pool_du_service(corps: str) -> tuple[int, int]:
    """(pool_size, max_overflow) tels que le CONTENEUR les recevra.

    Une variable absente du bloc `environment:` n'atteint pas le conteneur : on
    retombe alors sur le défaut du code, et c'est bien ce défaut qu'il faut
    compter — pas zéro.
    """
    def _lu(nom: str, defaut: int) -> int:
        m = re.search(rf"^\s*-\s*{nom}=(\d+)\s*$", corps, re.M)
        return int(m.group(1)) if m else defaut
    return _lu("DB_POOL_SIZE", _DEFAUT_POOL_SIZE), _lu("DB_MAX_OVERFLOW", _DEFAUT_MAX_OVERFLOW)


def _workers_uvicorn(corps: str) -> int:
    """Nombre de PROCESSUS uvicorn — chacun a son propre pool.

    Point aveugle du réglage d'origine : `--workers 2` double silencieusement la
    consommation de l'API. Sans commande explicite, c'est le CMD du Dockerfile
    qui s'applique.
    """
    m = re.search(r"^\s*command:\s*(.*uvicorn.*)$", corps, re.M)
    source = m.group(1) if m else _lire(DOCKERFILE)
    w = re.search(r"--workers\D+(\d+)", source)
    return int(w.group(1)) if w else 1


def test_budget_connexions_postgres():
    """La somme des pools doit tenir sous `max_connections`.

    Panne du 2026-08-31 20:31 : `/admin/api/adaptive-learning/history` en
    `TooManyConnectionsError`. L'endpoint n'y était pour rien — il a seulement eu
    le tort d'arriver après les autres. La cause est arithmétique : cinq
    processus (deux workers uvicorn, scraper, worker RQ, scheduler) réclamaient
    jusqu'à 60 connexions chacun, soit 300, contre 47 réellement accordées au
    rôle applicatif.

    Rien ne rendait ce dépassement visible : au repos la production n'ouvre que
    ~23 sessions, tout va bien, et la saturation n'arrive qu'au premier pic
    simultané — donc en production, sous charge, et jamais en test.
    """
    texte = _lire(COMPOSE_PROD)

    bloc_db = _bloc_service(texte, "db")
    assert bloc_db, "service `db` introuvable dans docker-compose.prod.yml"
    m = re.search(r"-c\s+max_connections=(\d+)", bloc_db.group(1))
    assert m, ("le service `db` ne fixe plus `max_connections` : le budget de "
               "connexions ne repose plus sur rien de vérifiable.")
    plafond = int(m.group(1)) - _RESERVE_SUPERUSER

    detail: list[str] = []
    total = 0
    for service in _SERVICES_APPLICATIFS:
        bloc = _bloc_service(texte, service)
        assert bloc, (f"service `{service}` introuvable : un processus qui se connecte "
                      "à PostgreSQL sans être compté dans le budget est exactement "
                      "le défaut que ce test ferme.")
        corps = bloc.group(1)
        pool, overflow = _pool_du_service(corps)
        procs = _workers_uvicorn(corps) if service == "api" else 1
        cout = (pool + overflow) * procs
        total += cout
        detail.append(f"{service}: ({pool}+{overflow})x{procs} = {cout}")

    assert total <= plafond - _MARGE_HORS_APPLICATIF, (
        f"budget de connexions dépassé : {total} demandées, {plafond} accordées "
        f"au rôle applicatif dont {_MARGE_HORS_APPLICATIF} à laisser libres pour "
        f"psql/alembic/TimescaleDB. Détail — {' | '.join(detail)}. "
        "Soit réduire les pools, soit monter `max_connections` (et la mémoire du "
        "conteneur db avec).")
