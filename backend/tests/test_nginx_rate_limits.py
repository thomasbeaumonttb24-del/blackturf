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

RACINE = pathlib.Path(os.environ.get("BLACKTURF_BACKEND_DIR")
                      or pathlib.Path(__file__).resolve().parents[1]).parent
COMPOSE_PROD_NGINX = RACINE / "nginx" / "nginx.prod.conf"


def _conf() -> str:
    if not COMPOSE_PROD_NGINX.exists():
        pytest.skip("nginx.prod.conf absent de ce contexte (image sans le dépôt)")
    return COMPOSE_PROD_NGINX.read_text(encoding="utf-8")


def _zone_du_bloc(texte: str, chemin: str) -> str | None:
    """Zone `limit_req` appliquée à `location <chemin>`, ou None s'il n'y en a pas."""
    bloc = re.search(rf"location {re.escape(chemin)} {{(.*?)^        }}", texte, re.S | re.M)
    if not bloc:
        pytest.skip(f"location {chemin} introuvable")
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
