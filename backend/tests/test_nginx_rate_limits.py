"""Le quota nginx de la console d'admin ne doit pas la vider en silence.

Le 2026-08-19, `/admin/` partageait la zone `auth` (10 requêtes par MINUTE,
pensée pour /auth/login). Or une seule ouverture de /admin/algorithme déclenche
une dizaine d'appels, plus un battement toutes les 15 s : nginx répondait 429
sans en-tête CORS, donc le navigateur affichait « blocked by CORS policy » et
trois panneaux (qualité de calibration, historique d'apprentissage, matrice de
biais) restaient vides — sans message d'erreur à l'écran.

Rien ne le signalait : l'API répondait 200 en curl, les tests passaient, la page
se chargeait. On verrouille donc ici la seule chose qui protégeait l'admin de ce
trou : le fait que sa zone ne soit pas celle du brute-force de login.
"""
from __future__ import annotations

import os
import pathlib
import re

import pytest

from ._descripteurs_deploiement import NGINX_PROD as COMPOSE_PROD_NGINX, exiger  # noqa: E402


def _conf() -> str:
    # `nginx.prod.conf` est suivi par git : son absence signifie que le dépôt
    # n'est pas monté, pas que le contexte est particulier. Échec bruyant plutôt
    # que trois quotas d'admin vérifiés par personne. Cf. _descripteurs_deploiement.
    return exiger(COMPOSE_PROD_NGINX)


def _zone_du_bloc(texte: str, chemin: str) -> str | None:
    """Zone `limit_req` appliquée à `location <chemin>`, ou None s'il n'y en a pas."""
    bloc = re.search(rf"location {re.escape(chemin)} {{(.*?)^        }}", texte, re.S | re.M)
    assert bloc, (f"location {chemin} introuvable dans nginx.prod.conf : le bloc a "
                  "été renommé ou déplacé, et son quota n'est plus verrouillé.")
    m = re.search(r"limit_req\s+zone=(\w+)", bloc.group(1))
    return m.group(1) if m else None


def _taux_par_seconde(texte: str, zone: str) -> float:
    m = re.search(rf"limit_req_zone[^;]*zone={zone}:[^;]*rate=(\d+)r/([sm])", texte)
    assert m, f"zone {zone} déclarée nulle part"
    valeur = float(m.group(1))
    return valeur if m.group(2) == "s" else valeur / 60.0


def test_l_admin_n_est_pas_limite_comme_un_formulaire_de_login():
    texte = _conf()
    zone = _zone_du_bloc(texte, "/admin/")
    assert zone != "auth", (
        "La console d'admin partage la zone `auth` (10 r/min) : ses panneaux "
        "reçoivent des 429 que le navigateur affiche en erreur CORS.")


def test_le_quota_admin_absorbe_une_ouverture_de_page():
    """~10 appels au chargement + un battement toutes les 15 s."""
    texte = _conf()
    zone = _zone_du_bloc(texte, "/admin/")
    if zone is None:
        pytest.skip("aucun limit_req sur /admin/ — rien à vérifier")
    assert _taux_par_seconde(texte, zone) >= 1.0, (
        f"zone {zone} sous 1 requête/seconde : insuffisant pour la page de supervision")


def test_le_login_reste_strictement_limite():
    """Le desserrage de l'admin ne doit pas déteindre sur le brute-force de mot de passe."""
    texte = _conf()
    assert _taux_par_seconde(texte, "auth") <= 1.0, (
        "la zone `auth` protège /auth/login : elle doit rester serrée")


# --- Durcissement du 06/10 ----------------------------------------------------

def _locations(texte: str) -> list[tuple[str, str]]:
    """(chemin, corps) de chaque `location` — blocs indentés de 8 espaces."""
    return [(m.group(1).strip(), m.group(2)) for m in re.finditer(
        r"^        location ([^{]+)\{(.*?)^        \}", texte, re.S | re.M)]


def test_l_entete_interne_est_efface_sur_toute_location_proxifiee():
    """`X-BT-Interne` lève les quotas par IP de l'API (rendu serveur du frontend).

    Il n'est légitime que par le réseau Docker. Une seule location qui le
    relaierait depuis Internet offrirait le contournement à quiconque devine ou
    vole le secret — et nginx n'hérite PAS des proxy_set_header du serveur dans
    une location qui en déclare : il faut le répéter partout.
    """
    texte = _conf()
    proxifiees = [(chemin, corps) for chemin, corps in _locations(texte) if "proxy_pass" in corps]
    assert len(proxifiees) >= 7, "lecture des locations cassée : rien ne serait vérifié"
    oublis = [chemin for chemin, corps in proxifiees
              if not re.search(r'proxy_set_header\s+X-BT-Interne\s+""\s*;', corps)]
    assert not oublis, f"X-BT-Interne relayé tel quel depuis Internet sur : {oublis}"


def test_les_visuels_ont_leur_propre_quota():
    """/visuels/ rend une image ou lit l'API SANS cache à chaque appel : sans
    limite, un client en boucle occupe le CPU du frontend."""
    texte = _conf()
    zone = _zone_du_bloc(texte, "/visuels/")
    assert zone and zone != "auth", "location /visuels/ sans limit_req propre"
    assert _taux_par_seconde(texte, zone) <= 5, "quota /visuels/ trop large pour protéger quoi que ce soit"


def test_les_poignees_de_main_websocket_sont_limitees():
    texte = _conf()
    assert _zone_du_bloc(texte, "/ws/"), "location /ws/ sans limit_req"
    bloc = dict(_locations(texte))["/ws/"]
    m = re.search(r"proxy_read_timeout\s+(\d+)s", bloc)
    # Les canaux pinguent toutes les 30 s (api/routes/ws.py::PING_INTERVAL) :
    # un timeout sous ~2 pings couperait des connexions saines.
    assert m and 60 <= int(m.group(1)) <= 600, "proxy_read_timeout de /ws/ hors de [60 s, 10 min]"


def test_les_hotes_inconnus_sont_coupes():
    """Sans serveur par défaut, le premier bloc de chaque port servait n'importe
    quel Host — IP nue comprise, certificat et noms hébergés avec."""
    texte = _conf()
    assert re.search(r"listen 80 default_server;\s*server_name _;\s*return 444;", texte), (
        "pas de serveur par défaut en 444 sur le port 80")
    assert re.search(r"listen 443 ssl(?: http2)? default_server;[^\n]*\s*server_name _;\s*ssl_reject_handshake on;", texte), (
        "pas de refus de poignée de main TLS pour un SNI inconnu")
    assert re.search(r"^\s*ssl_session_tickets off;", texte, re.M), "tickets de session TLS actifs"
