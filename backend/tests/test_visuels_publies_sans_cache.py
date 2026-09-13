"""Un visuel qui part sur Instagram se lit SANS CACHE, et ne se rend pas sans données.

Incident du 2026-09-11 : la story du 10/09 est partie à 02 h 30 avec « 0 € rendu »,
sans le taux de Top 3 ni le meilleur gain — un visuel qui ne ressemblait même plus aux
précédents, puisque ces deux blocs se taisent quand leurs données manquent.

L'API était juste (159 plans, 961,80 € rendus). La route `/visuels/story.jpg` lisait
l'API avec `fetch(..., { next: { revalidate: 600 } })` : le cache de données de Next
sert la réponse PÉRIMÉE d'abord et ne la rafraîchit qu'ensuite. Meta a récupéré
l'image à 02:30:08 avec la réponse lue la veille à 06 h 32 (journée encore vide) ; le
vrai appel à l'API est parti à 02:30:10, deux secondes trop tard.

Ce que ces tests verrouillent, sur les routes dont l'image ou la légende est PUBLIÉE :
  1. aucune lecture de données en cache (`next: { revalidate }` interdit, `no-store`
     exigé) ;
  2. la story répond une erreur HTTP — jamais une image à zéro — quand l'API ne répond
     pas, ou qu'elle ne dit plus ce que le job de publication a validé (`plans=`) ;
  3. le job transmet ce nombre de plans validé dans l'URL qu'il donne à Meta.
"""
from __future__ import annotations

import re

from tests._descripteurs_deploiement import RACINE, exiger

VISUELS = RACINE / "frontend" / "src" / "app" / "visuels"

# Routes dont la sortie part telle quelle dans une publication automatique.
PUBLIEES = (
    VISUELS / "story.jpg" / "route.tsx",
    VISUELS / "mosaique" / "[tuile]" / "route.tsx",
    VISUELS / "mosaique" / "legendes.json" / "route.ts",
)

STORY = VISUELS / "story.jpg" / "route.tsx"
JOBS = RACINE / "backend" / "services" / "jobs.py"

# Images que Meta vient chercher lui-même, et la mémoire d'envoi qui les lui sert.
IMAGES_PUBLIEES = (STORY, VISUELS / "mosaique" / "[tuile]" / "route.tsx")
ENVOI = RACINE / "frontend" / "src" / "lib" / "envoi-visuel.ts"


def test_meta_recoit_l_image_deja_composee_pour_l_envoi():
    """
    Incident du 2026-09-13 : la tuile hebdomadaire se composait en 8,5 s, Meta abandonnait
    avant (nginx : 499) et refusait le conteneur six passages de suite. Le service fait
    composer l'image sous une clé `envoi=`, et la route doit resservir CES octets à Meta
    au lieu de tout recomposer.

    La mémoire n'est relue QUE sous une clé d'envoi : sans elle, une visite du studio
    pourrait déposer une image que Meta publierait plus tard — exactement le défaut du
    2026-09-11 sous une autre forme.
    """
    for chemin in IMAGES_PUBLIEES:
        code = _code(chemin)
        assert "cleEnvoi(req.url)" in code, f"{chemin.relative_to(RACINE)} : clé d'envoi non lue"
        assert "envoiGarde(envoi)" in code, f"{chemin.relative_to(RACINE)} : image gardée non resservie"
        assert 'garderEnvoi(envoi, new Uint8Array(jpeg), "image/jpeg")' in code, (
            f"{chemin.relative_to(RACINE)} : le JPEG rendu n'est pas gardé pour Meta"
        )
    lib = _code(ENVOI)
    assert 'searchParams.get("envoi")' in lib
    assert "if (!cle) return null;" in lib, "sans clé d'envoi, rien ne doit être relu"
    assert "if (!cle) return;" in lib, "sans clé d'envoi, rien ne doit être gardé"


def _code(chemin) -> str:
    """Le source sans ses commentaires : ils citent précisément ce qui est interdit."""
    src = exiger(chemin)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("//"))


def test_aucune_route_publiee_ne_lit_ses_donnees_en_cache():
    for chemin in PUBLIEES:
        code = _code(chemin)
        assert "fetch(" in code, f"{chemin.name} : plus de lecture d'API ? revoir ce test"
        assert not re.search(r"next\s*:\s*\{\s*revalidate", code), (
            f"{chemin.relative_to(RACINE)} lit ses données avec `next: {{ revalidate }}` : "
            "le cache sert la réponse PÉRIMÉE d'abord — c'est ce qui a publié la story "
            "du 2026-09-10 à « 0 € rendu »."
        )
        assert 'cache: "no-store"' in code, f"{chemin.relative_to(RACINE)} : `no-store` exigé"


def test_la_story_n_a_aucun_cache_de_route():
    code = _code(STORY)
    assert not re.search(r"export\s+const\s+revalidate", code)
    assert 'export const dynamic = "force-dynamic"' in code
    assert "public, max-age" not in code, "l'image publiée ne se met pas en cache"


def test_la_story_refuse_de_se_rendre_sans_donnees():
    """Une image à zéro part et ne se corrige plus ; une erreur HTTP fait échouer la
    publication, que le job retente au passage suivant."""
    code = _code(STORY)
    assert "if (!bilan)" in code
    assert "status: 503" in code


def test_la_story_refuse_un_bilan_different_de_celui_valide():
    code = _code(STORY)
    assert 'searchParams.get("plans")' in code
    assert "status: 409" in code
    assert "journee_complete" in code


def test_le_job_transmet_le_nombre_de_plans_valide():
    src = exiger(JOBS)
    assert re.search(r"/visuels/story\.jpg\?jour=\{jour\}&plans=\{int\(d\['nb_plans'\]\)\}", src), (
        "l'URL donnée à Meta doit porter `plans=` : c'est ce qui empêche l'image de "
        "diverger du bilan que le job a validé"
    )
