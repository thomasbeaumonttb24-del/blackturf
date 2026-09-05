"""Le fonds de photos des visuels : une par jour, et jamais un portrait.

Deux règles, toutes les deux payées.

**Une photo différente chaque jour.** L'index tournait sur le QUANTIÈME du mois : le
1er et le 31 tombaient sur la même image, et le cycle se calait sur la longueur du
mois — sur un fonds de 32 photos, février n'en aurait jamais montré que 28. Il tourne
maintenant sur le nombre de jours écoulés depuis l'époque. Ce test vérifie ce qui
rend la rotation vraie : assez de photos, et aucun doublon dans la liste (deux entrées
identiques feraient revenir la même image dans le même tour).

**Jamais de portrait.** Les visuels posent la photo dans une bande LARGE. Une source
verticale n'y entre pas sans perdre son sujet : les deux chevaux de `galop-duo`
(rapport 0,67) sortaient décapités quel que soit l'ancrage du cadrage. Trois photos
ont été retirées pour cette raison le 2026-09-05 ; ce test empêche qu'on en rajoute
une sans s'en apercevoir — le défaut ne se voit que sur le visuel publié.

Les dimensions sont lues dans l'en-tête JPEG, sans dépendance : le backend n'a pas de
bibliothèque d'images et n'a pas à en gagner une pour ce contrôle.
"""
from __future__ import annotations

import re
import struct

from tests._descripteurs_deploiement import RACINE, exiger

MOSAIQUE = RACINE / "frontend" / "src" / "lib" / "mosaique.tsx"
DOSSIER_PHOTOS = RACINE / "frontend" / "public" / "img" / "course"

# En dessous, la rotation revient trop vite pour qu'on ne la remarque pas.
MINIMUM_PHOTOS = 30

# Marqueurs JPEG « Start Of Frame » qui portent les dimensions. SOF4 (0xC4) et
# SOF8/SOF12 (0xC8, 0xCC) sont des tables, pas des cadres : ils sont exclus.
_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def _photos_declarees() -> list[str]:
    source = exiger(MOSAIQUE)
    bloc = re.search(r"const PHOTOS = \[(.*?)\] as const;", source, re.S)
    assert bloc, "la liste PHOTOS a changé de forme : ce test ne la lit plus"
    return re.findall(r'"([^"]+)"', bloc.group(1))


def _dimensions_jpeg(chemin) -> tuple[int, int]:
    """Largeur, hauteur d'un JPEG, lues dans son en-tête."""
    data = chemin.read_bytes()
    assert data[:2] == b"\xff\xd8", f"{chemin.name} n'est pas un JPEG"
    i = 2
    while i < len(data) - 9:
        if data[i] != 0xFF:
            i += 1
            continue
        marqueur = data[i + 1]
        if marqueur in _SOF:
            hauteur, largeur = struct.unpack(">HH", data[i + 5:i + 9])
            return largeur, hauteur
        if marqueur in (0xD8, 0x01) or 0xD0 <= marqueur <= 0xD7:
            i += 2
            continue
        taille = struct.unpack(">H", data[i + 2:i + 4])[0]
        i += 2 + taille
    raise AssertionError(f"dimensions introuvables dans {chemin.name}")


def test_le_fonds_compte_assez_de_photos_pour_que_la_rotation_se_voie():
    photos = _photos_declarees()
    assert len(photos) >= MINIMUM_PHOTOS, (
        f"{len(photos)} photos : la même image reviendrait tous les {len(photos)} jours"
    )


def test_aucune_photo_n_est_declaree_deux_fois():
    photos = _photos_declarees()
    doublons = sorted({p for p in photos if photos.count(p) > 1})
    assert not doublons, f"la même image reviendrait deux fois dans un tour : {doublons}"


def test_la_rotation_avance_d_un_jour_a_l_autre():
    """L'index doit suivre le NOMBRE DE JOURS, pas le quantième : sinon le 1er et le
    31 montrent la même image et la fin du fonds n'est jamais atteinte en février."""
    source = exiger(MOSAIQUE)
    assert "86_400_000" in source, (
        "photoDuJour ne compte plus les jours écoulés — vérifier qu'elle ne retombe "
        "pas sur le quantième du mois"
    )


def test_toutes_les_photos_declarees_existent():
    manquantes = [
        p for p in _photos_declarees()
        if p.startswith("course/") and not (DOSSIER_PHOTOS / p.split("/", 1)[1]).exists()
    ]
    assert not manquantes, f"déclarées mais absentes du dépôt : {manquantes}"


def test_aucune_photo_orpheline_dans_le_dossier():
    """Un fichier présent mais jamais tiré est un poids mort dans le dépôt — et le
    signe qu'on a retiré une photo de la liste sans supprimer son fichier."""
    declarees = {p.split("/", 1)[1] for p in _photos_declarees() if p.startswith("course/")}
    presentes = {f.name for f in DOSSIER_PHOTOS.glob("*.jpg")}
    assert presentes == declarees, (
        f"orphelines : {sorted(presentes - declarees)} · "
        f"déclarées sans fichier : {sorted(declarees - presentes)}"
    )


def test_aucune_photo_du_fonds_n_est_en_portrait():
    """Une source verticale posée dans une bande large perd son sujet, quel que soit
    l'ancrage du cadrage. Constaté le 2026-09-05 : les deux chevaux de galop-duo
    (0,67) sortaient décapités sur la story."""
    portraits = []
    for fichier in sorted(DOSSIER_PHOTOS.glob("*.jpg")):
        largeur, hauteur = _dimensions_jpeg(fichier)
        if largeur / hauteur < 1.15:
            portraits.append(f"{fichier.name} ({largeur}×{hauteur}, {largeur / hauteur:.2f})")
    assert not portraits, (
        "photos trop verticales pour une bande large — le cheval y sera coupé : "
        + ", ".join(portraits)
    )


def test_la_provenance_de_chaque_photo_est_journalisee():
    """Une image dont on ne sait plus d'où elle vient est une image qu'on ne peut plus
    défendre — et on publie ces visuels sur un compte de marque."""
    sources = exiger(DOSSIER_PHOTOS / "SOURCES.txt")
    for fichier in sorted(DOSSIER_PHOTOS.glob("*.jpg")):
        assert fichier.name in sources, f"{fichier.name} n'a pas de source déclarée"
