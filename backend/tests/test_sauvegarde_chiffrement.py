"""Invariants du chiffrement des sauvegardes — violation silencieuse par nature.

Une sauvegarde mal chiffree se produit sans erreur, pese la bonne taille, se
restaure correctement, et personne ne s'apercoit de rien. Seule sa resistance
change. C'est exactement le profil de defaut que ces tests verrouillent.

Le defaut corrige le 2026-08-31 : `openssl enc -pass file:` ne lit QUE LA PREMIERE
LIGNE du fichier de cle. Avec 32 octets aleatoires BRUTS, un premier octet a 0x0a
(1/256 des tirages) donne une passphrase VIDE — et le sel PBKDF2 etant ecrit en
clair dans le fichier, n'importe qui tenant le .enc le dechiffre sans aucune cle.
Reproduit avec le certificat de production :

    $ printf '\\x0a' > k; openssl rand 31 >> k
    $ echo "DONNEES SENSIBLES" | openssl enc -aes-256-ctr -pbkdf2 -pass file:k -out bad.enc
    $ openssl enc -d -aes-256-ctr -pbkdf2 -pass "pass:" -in bad.enc
    DONNEES SENSIBLES

Audit des 14 sauvegardes en ligne au 2026-08-31 : 0 dechiffrable sans cle, mais
2 a cle tronquee par un 0x0a, dont une reduite a 4 octets (32 bits).

La correction genere la cle en HEXADECIMAL : 64 caracteres de [0-9a-f], ou aucun
saut de ligne n'est possible. L'entropie reste de 256 bits et la restauration ne
change pas — `-pass file:` lit la premiere ligne, qui est desormais la cle entiere.
"""
from __future__ import annotations

import os
import pathlib
import re

import pytest


RACINE = pathlib.Path(os.environ.get("BLACKTURF_BACKEND_DIR")
                      or pathlib.Path(__file__).resolve().parents[1]).parent
SCRIPTS = [RACINE / "scripts" / "db_backup.sh",
           RACINE / "scripts" / "rechiffrer_sauvegardes.sh"]


def _lire(chemin: pathlib.Path) -> str:
    if not chemin.exists():
        pytest.skip(f"{chemin.name} absent de ce contexte de test "
                    f"(monter le depot pour exercer ce test)")
    return chemin.read_text(encoding="utf-8")


@pytest.mark.parametrize("chemin", SCRIPTS, ids=lambda p: p.name)
def test_la_cle_aes_est_generee_en_hexadecimal(chemin: pathlib.Path):
    """`openssl rand -out FICHIER 32` ecrit 32 octets BRUTS : c'est la forme qui
    permet un 0x0a en tete, donc une passphrase vide. Seul `-hex` l'interdit."""
    texte = _lire(chemin)
    assert re.search(r"openssl\s+rand\s+-hex\s+32\s*>", texte), (
        f"{chemin.name} doit generer la cle AES avec `openssl rand -hex 32 > \"$DK\"`")
    assert not re.search(r"openssl\s+rand\s+-out\s+\"?\$?\{?DK\}?\"?\s+32", texte), (
        f"{chemin.name} genere encore la cle en octets bruts : un premier octet a "
        f"0x0a rendrait la sauvegarde dechiffrable sans aucune cle")


@pytest.mark.parametrize("chemin", SCRIPTS, ids=lambda p: p.name)
def test_la_forme_de_la_cle_est_verifiee_avant_usage(chemin: pathlib.Path):
    """Fail-closed : si `-hex` changeait un jour de comportement, il ne faut pas
    le decouvrir a la restauration. La longueur de la premiere ligne est verifiee."""
    texte = _lire(chemin)
    assert re.search(r'head -n 1 "\$DK".*wc -c', texte), (
        f"{chemin.name} doit verifier que la premiere ligne du fichier de cle fait "
        f"bien 64 caracteres avant de s'en servir")
    assert '"64"' in texte, f"{chemin.name} doit exiger exactement 64 caracteres hex"


def test_la_restauration_lit_toujours_la_cle_de_la_meme_facon():
    """COMPATIBILITE ASCENDANTE. Les sauvegardes deja produites portent une cle de
    32 octets bruts ; les nouvelles, 64 caracteres hex. `restore_backup.sh` doit
    continuer de passer betement a `-pass file:` ce que `pkeyutl -decrypt` lui rend,
    sans chercher a distinguer les formats — c'est ce qui rend les deux
    generations restaurables par la meme commande. Verifie sur les vrais fichiers
    le 2026-08-31 : ancien format et nouveau format restaures a l'identique."""
    texte = _lire(RACINE / "scripts" / "restore_backup.sh")
    assert 'openssl pkeyutl -decrypt' in texte
    assert re.search(r'-pass "file:\$TRAVAIL/cle\.bin"', texte), (
        "restore_backup.sh doit passer le contenu scelle tel quel a -pass file:")
    assert "gzip -t" in texte, (
        "AES-CTR ne detecte pas une alteration : sans `gzip -t` une restauration "
        "corrompue passerait pour reussie")


def test_l_absence_de_copie_hors_site_est_bruyante():
    """LE SILENCE ETAIT LE DEFAUT. La copie deportee etait gardee par
    `command -v rclone` ; rclone n'ayant jamais ete installe, la branche ne s'est
    jamais executee et rien ne l'a signale. Constat du 2026-08-31 : 14 sauvegardes,
    12 Go, zero copie hors site — et la conviction qu'il y en avait une. Une
    protection qui s'auto-desactive sans le dire produit une fausse assurance."""
    texte = _lire(RACINE / "scripts" / "db_backup.sh")
    assert "BLACKTURF_BACKUP_SANS_DEPORT" in texte, (
        "la desactivation de la copie hors site doit etre EXPLICITE, jamais implicite")
    assert re.search(r"elif ! command -v rclone", texte), (
        "rclone absent doit etre traite comme un echec, pas comme un no-op")
    # Trois sorties en erreur : rclone absent, aucun distant, copie incomplete.
    assert texte.count("exit 3") >= 3, (
        "chaque cas d'absence de copie hors site doit sortir en erreur pour que le "
        "cron le remonte")


def test_la_copie_hors_site_est_verifiee_pas_supposee():
    """`rclone copy` peut sortir 0 sans avoir rien transfere. Une copie hors site
    non verifiee ne vaut pas mieux qu'une copie absente : on compare les tailles."""
    texte = _lire(RACINE / "scripts" / "db_backup.sh")
    assert "rclone size" in texte, (
        "la presence du fichier a destination doit etre VERIFIEE apres la copie")
    assert "TAILLE_DISTANTE" in texte and "TAILLE_LOCALE" in texte


def test_le_chiffrement_ne_peut_pas_se_replier_en_clair():
    """Un repli silencieux en clair est le mode de panne le plus couteux : la
    sauvegarde existe, elle a la bonne taille, et elle est lisible par quiconque."""
    texte = _lire(RACINE / "scripts" / "db_backup.sh")
    assert re.search(r'\[ -s "\$CERT" \] \|\|', texte), (
        "certificat absent doit faire ECHOUER la sauvegarde, jamais produire du clair")
    assert '1f8b' in texte, (
        "la sortie doit etre verifiee NON-gzip : c'est la preuve qu'elle est chiffree")
