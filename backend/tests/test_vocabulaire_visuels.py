"""Un visuel public ne dit pas « gagné » là où il faut dire « rendu ».

Les montants portés par les visuels sociaux sont ceux de PLANS calculés et réglés
aux vrais rapports du PMU — pas d'argent encaissé par qui que ce soit. « Misé » et
« rendu » sont exacts ; « gagné », « nos gains » ou « bénéfice » ne le seraient
pas, et sur une publication qu'on ne peut plus corriger l'écart n'est pas une
nuance de style.

La story du soir rend la règle plus fragile qu'avant : elle affiche un TOTAL sans
la mise (choix produit du 2026-09-05). Un total seul se lit très vite comme un
bénéfice net — le 2026-09-04, les plans ont rendu 1 171 € pour 1 530 € misés,
c'est-à-dire une journée à −359 €. Deux garde-fous compensent, et ce sont eux que
ces tests verrouillent :

  1. le vocabulaire, sur le visuel comme dans la légende ;
  2. le dénominateur — le nombre de plans gagnants n'est jamais publié sans le
     nombre TOTAL de plans du jour, sans quoi la phrase se lit comme si tous les
     plans avaient gagné ;
  3. la mention de jeu responsable portée par l'IMAGE, pas seulement par la
     légende : une image circule hors de sa légende, et c'est l'image qu'on
     retrouve republiée.
"""
from __future__ import annotations

import re

from tests._descripteurs_deploiement import RACINE, exiger

STORY = RACINE / "frontend" / "src" / "lib" / "story.tsx"
LEGENDES = RACINE / "frontend" / "src" / "lib" / "visuels-legendes.ts"
MOSAIQUE = RACINE / "frontend" / "src" / "lib" / "mosaique.tsx"

# Mots interdits DANS LE TEXTE AFFICHÉ. Ils restent autorisés dans les commentaires,
# qui expliquent précisément pourquoi ils sont interdits — un test qui interdirait
# d'en parler empêcherait d'écrire la raison.
#
# « gagné » N'EST PAS dans cette liste, et c'est délibéré : « notre favori a gagné
# 14 courses sur 51 » parle d'un CHEVAL qui gagne une course, pas d'argent encaissé,
# et c'est la formulation juste. Ce qui est interdit, c'est le vocabulaire de
# l'ENCAISSEMENT — plus, en dessous, « gagné » collé à un montant, qui est la vraie
# faute qu'on cherche à empêcher.
INTERDITS = ("gains", "bénéfice", "bénéfices", "empoché", "empochés",
             "encaissé", "encaissés", "profit", "profits")

# « 236 € gagnés », « gagné 236 € » : un verbe d'encaissement collé à un montant.
_ARGENT_GAGNE = re.compile(
    r"(gagn\w*[^.]{0,20}(€|euro)|(€|euro)[^.]{0,20}gagn\w*)", re.I,
)


def _sans_commentaires(source: str) -> str:
    sans_bloc = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
    return re.sub(r"^\s*//.*$", " ", sans_bloc, flags=re.M)


def _mots_interdits(source: str) -> list[str]:
    texte = _sans_commentaires(source).lower()
    fautes = [m for m in INTERDITS if re.search(rf"\b{m}\b", texte)]
    trouve = _ARGENT_GAGNE.search(texte)
    if trouve:
        fautes.append(f"« gagné » collé à un montant : {trouve.group(0)[:60]}")
    return fautes


def test_la_story_ne_parle_jamais_de_gains():
    fautes = _mots_interdits(exiger(STORY))
    assert not fautes, (
        "la story affiche ce que les plans ont RENDU, pas des gains encaissés ; "
        f"mots trouvés : {fautes}"
    )


def test_la_legende_de_la_story_ne_parle_jamais_de_gains():
    fautes = _mots_interdits(exiger(LEGENDES))
    assert not fautes, f"légende sociale : mots interdits {fautes}"


def test_la_mosaique_ne_parle_jamais_de_gains():
    fautes = _mots_interdits(exiger(MOSAIQUE))
    assert not fautes, f"mosaïque : mots interdits {fautes}"


def test_le_nombre_de_plans_gagnants_ne_sort_jamais_sans_son_total():
    """`nbPlansGagnants` affiché seul se lirait comme « tous ont gagné »."""
    for chemin, gagnants, total in (
        (STORY, "d.nbPlansGagnants", "d.nbPlans"),
        (LEGENDES, "bilan.nbPlansGagnants", "bilan.nbPlans"),
    ):
        source = _sans_commentaires(exiger(chemin))
        if gagnants not in source:
            continue
        assert total in source, (
            f"{chemin.name} publie {gagnants} sans jamais publier {total} : le lecteur "
            "ne peut pas voir la proportion réelle"
        )


def test_la_story_porte_la_mention_de_jeu_responsable():
    source = exiger(STORY)
    assert "MENTION_LEGALE" in source, (
        "la mention doit être sur l'IMAGE, pas seulement dans la légende : une image "
        "circule hors de sa légende"
    )


def test_la_mise_totale_reste_servie_par_l_api():
    """Le visuel n'affiche pas la mise ; l'API doit continuer à la servir.

    Sans `total_mise`, plus personne — pas même nous — ne peut dire si la journée
    a gagné ou perdu, et le chiffre publié devient invérifiable.
    """
    stats = exiger(RACINE / "backend" / "api" / "routes" / "stats.py")
    assert '"total_mise": total_mise' in stats
    assert '"total_retour": total_retour' in stats
