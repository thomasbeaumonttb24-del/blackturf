"""Le formulaire d'inscription et l'API doivent exiger le MÊME mot de passe.

Défaut constaté en production le 02/09/2026 : la page `/inscription` annonçait
« 8 caractères minimum » et sa validation zod acceptait 8 caractères, tandis que
`RegisterRequest` en exigeait 10. Le visiteur passait la validation du
navigateur, recevait un HTTP 422, et lisait le message brut de Pydantic — en
anglais — sous un champ qui venait de lui promettre que 8 suffisaient. Trace
nginx du 02/09 à 21:43, une seule adresse :

    POST /api/v1/auth/register HTTP/2.0" 422 159
    POST /api/v1/auth/register HTTP/2.0" 422 160
    POST /api/v1/auth/register HTTP/2.0" 422 159

Trois tentatives en vingt-trois secondes, puis plus rien. Aucun compte créé ce
jour-là. La panne ne produit ni 5xx, ni exception, ni alerte : côté serveur tout
va bien, c'est le contrat entre les deux moitiés du produit qui est rompu.

Ces tests ferment l'écart dans les deux sens : la politique de l'API est lue sur
le schéma, et le module partagé du frontend doit l'annoncer à l'identique.
"""
from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from api.routes.auth import RegisterRequest
from tests._descripteurs_deploiement import RACINE, exiger

MODULE_FRONT = RACINE / "frontend" / "src" / "lib" / "motdepasse.ts"
PAGES_AUTH = RACINE / "frontend" / "src" / "app" / "(auth)"

# `login` est volontairement hors périmètre : on y SAISIT un mot de passe
# existant, on n'en CRÉE pas. Y appliquer la politique de création verrouillerait
# dehors tout compte dont le mot de passe est antérieur à cette politique — sa
# règle `min(6, "Mot de passe requis")` est un contrôle de présence, pas une
# politique. Seuls les formulaires qui posent un mot de passe sont concernés.
PAGES_QUI_CREENT_UN_MOT_DE_PASSE = {"inscription", "reinitialiser-mot-de-passe"}


def _longueur_minimale_api() -> int:
    """Longueur minimale RÉELLEMENT appliquée par l'API, lue sur le schéma.

    Lue plutôt qu'écrite en dur : si quelqu'un change `Field(min_length=…)`,
    c'est le frontend qui doit devenir rouge, pas ce test.
    """
    contraintes = RegisterRequest.model_fields["password"].metadata
    minimums = [c.min_length for c in contraintes
                if getattr(c, "min_length", None) is not None]
    assert minimums, "RegisterRequest.password n'impose plus de longueur minimale"
    return max(minimums)


@pytest.mark.parametrize("mauvais", ["Test1234", "Motdepas9"])
def test_api_refuse_sous_le_minimum(mauvais: str):
    """Le cas exact rencontré par le visiteur du 02/09 : 8 et 9 caractères."""
    with pytest.raises(ValidationError):
        RegisterRequest(email="a@b.fr", password=mauvais)


@pytest.mark.parametrize("trivial", ["Motdepasse", "1234567890"])
def test_api_refuse_lettres_seules_et_chiffres_seuls(trivial: str):
    """Assez long, mais uniquement des lettres ou uniquement des chiffres."""
    with pytest.raises(ValidationError):
        RegisterRequest(email="a@b.fr", password=trivial)


def test_api_accepte_un_mot_de_passe_conforme():
    """Témoin négatif : sans lui, un schéma cassé rendrait les tests ci-dessus
    verts pour la mauvaise raison (tout serait refusé)."""
    assert RegisterRequest(email="a@b.fr", password="MotDePasse2026").password


def test_le_frontend_annonce_la_meme_longueur_que_l_api():
    source = exiger(MODULE_FRONT)
    trouve = re.search(r"MOT_DE_PASSE_MIN\s*=\s*(\d+)", source)
    assert trouve, f"{MODULE_FRONT.name} ne déclare plus MOT_DE_PASSE_MIN"
    annonce = int(trouve.group(1))
    attendu = _longueur_minimale_api()
    assert annonce == attendu, (
        f"Le frontend annonce {annonce} caractères, l'API en exige {attendu}. "
        "C'est l'écart qui a fait échouer les inscriptions du 02/09/2026 : "
        "le visiteur passe la validation du navigateur et se prend un 422."
    )


def test_le_frontend_annonce_la_regle_dans_le_texte_affiche():
    """Le texte montré sous le champ doit porter le même nombre que la règle :
    c'est la promesse faite au visiteur AVANT qu'il tape, et c'est elle qui
    mentait le 02/09."""
    source = exiger(MODULE_FRONT)
    aide = re.search(r'MOT_DE_PASSE_AIDE\s*=\s*"([^"]+)"', source)
    assert aide, f"{MODULE_FRONT.name} ne déclare plus MOT_DE_PASSE_AIDE"
    attendu = _longueur_minimale_api()
    assert str(attendu) in aide.group(1), (
        f"Le texte affiché — « {aide.group(1)} » — ne mentionne pas les "
        f"{attendu} caractères exigés par l'API."
    )


def test_le_frontend_exige_lettres_et_chiffres():
    """La longueur ne suffit pas : « Motdepasse » fait 10 caractères et l'API
    le refuse quand même. Sans cette règle côté navigateur, l'écart se rouvre
    sur un mot de passe assez long mais trivial."""
    source = exiger(MODULE_FRONT)
    assert "refine" in source and r"\p{L}" in source, (
        "Le module de mot de passe du frontend ne reproduit plus le refus des "
        "mots de passe composés uniquement de lettres ou uniquement de chiffres "
        "(isalpha/isdigit côté API)."
    )


def test_aucune_page_de_creation_ne_redefinit_sa_propre_regle():
    """Les deux formulaires (inscription, réinitialisation) portaient chacun leur
    copie de la règle, et les deux ont dérivé. Ils doivent passer par le module
    partagé, seul endroit comparé à l'API par les tests ci-dessus."""
    if not PAGES_AUTH.exists():
        exiger(MODULE_FRONT)  # échoue avec le message d'aide au montage
        pytest.fail(f"{PAGES_AUTH} introuvable", pytrace=False)

    vues: set[str] = set()
    fautives: list[str] = []
    for page in PAGES_AUTH.rglob("page.tsx"):
        if page.parent.name not in PAGES_QUI_CREENT_UN_MOT_DE_PASSE:
            continue
        vues.add(page.parent.name)
        texte = page.read_text(encoding="utf-8")
        # Une règle de longueur écrite sur place, au lieu de `champMotDePasse`.
        if re.search(r"password:\s*z\s*\.\s*string\(\)\s*\.\s*min\(", texte):
            fautives.append(page.parent.name)

    assert not fautives, (
        "Ces pages redéfinissent la longueur du mot de passe au lieu d'importer "
        f"`champMotDePasse` depuis lib/motdepasse.ts : {sorted(fautives)}. "
        "C'est par cette duplication que l'inscription et l'API ont divergé."
    )
    # Témoin : sans lui, un dossier renommé viderait la boucle et rendrait le
    # test vert sans avoir rien inspecté.
    assert vues == PAGES_QUI_CREENT_UN_MOT_DE_PASSE, (
        f"Pages de création de mot de passe inspectées : {sorted(vues)}, "
        f"attendues : {sorted(PAGES_QUI_CREENT_UN_MOT_DE_PASSE)}. "
        "Un formulaire renommé ou déplacé échappe à ce contrôle."
    )
