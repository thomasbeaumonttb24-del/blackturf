"""Aperçu PUBLIC de l'analyse d'une course (`/courses/{id}/apercu`).

Cet endpoint alimente la carte vue par un visiteur SANS abonnement. Son unique
raison d'être est le funnel : montrer qu'une analyse existe et ce qu'elle vaut,
sans livrer le pronostic payant. Les invariants testés ici sont donc, dans
l'ordre : aucune identité de cheval avant le départ, et révélation complète une
fois la course courue.
"""
import uuid
import pytest
from datetime import datetime, timezone, date, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Hippodrome, Reunion, Course, Cheval, Participation, Prediction, Resultat,
    FeatureML,
)

pytestmark = pytest.mark.asyncio


async def _course_analysee(db: AsyncSession, course_id: str, statut: str = "a_venir",
                           champ: int = 3, avec_features: bool = False) -> None:
    """Course notée : le n°1 du modèle (n°7) N'EST PAS le favori des cotes (n°3),
    ce qui est précisément le cas que la carte met en avant. `champ` complète le
    lot avec des chevaux de fond pour tester la queue de classement révélée."""
    hippo = Hippodrome(hippodrome_id=str(uuid.uuid4()), nom="Vincennes Test", code="VCT")
    db.add(hippo)
    db.add(Reunion(
        reunion_id=f"RA-{course_id}", date=date.today(),
        hippodrome_id=hippo.hippodrome_id, hippodrome_nom="Vincennes Test", numero=9,
    ))
    db.add(Course(
        course_id=course_id, reunion_id=f"RA-{course_id}", numero=1, nom="Prix Aperçu",
        date_heure=datetime.now(timezone.utc) + timedelta(hours=3),
        hippodrome_nom="Vincennes Test", discipline="Attelé", distance=2700,
        nb_partants=champ, statut=statut,
    ))

    lot = [
        (7, "OUTSIDER TEST", 9.5, 0.30, 1),
        (3, "FAVORI MARCHE", 2.4, 0.25, 2),
        (5, "TOCARD TEST", 48.0, 0.01, 3),
    ]
    # Chevaux de fond : ils portent des noms reconnaissables pour vérifier
    # QUI est révélé et qui ne l'est pas.
    for i in range(4, champ + 1):
        lot.append((10 + i, f"FOND {i}", 60.0 + i, 0.005, i))
    for numero, nom, cote, proba, rang in lot:
        cheval_id = str(uuid.uuid4())
        db.add(Cheval(cheval_id=cheval_id, nom=nom, age=5, sexe="H"))
        part_id = str(uuid.uuid4())
        db.add(Participation(
            participation_id=part_id, course_id=course_id, cheval_id=cheval_id,
            numero=numero, cote_pmu=cote, non_partant=False,
        ))
        db.add(Prediction(
            prediction_id=str(uuid.uuid4()), participation_id=part_id, course_id=course_id,
            proba_top1=proba, proba_top3=min(0.99, proba * 2), rang_predit=rang,
            confidence_score=61.4,
        ))
        if avec_features:
            # Features réelles au sens du modèle : ce sont elles qui produisent
            # les signaux (forme excellente, terrain défavorable, jockey en
            # forme…). `None` est posé volontairement pour vérifier que le
            # comptage des critères ne compte pas les colonnes vides.
            db.add(FeatureML(participation_id=part_id, features={
                "forme_5_courses": 0.72 if proba > 0.2 else 0.28,
                "forme_tendance": 0.15 if proba > 0.2 else -0.12,
                "jockey_win_rate_30d": 0.24,
                "terrain_win_rate": 0.05 if proba > 0.2 else 0.45,
                "elo_vs_moyenne": 90.0 if proba > 0.2 else -80.0,
                "jours_repos": 21,
                "feature_jamais_calculee": None,
            }))
    await db.commit()


async def test_apercu_est_public_et_ne_livre_aucune_identite(client: AsyncClient, db: AsyncSession):
    """Sans compte, sur une course à venir : des agrégats, jamais un cheval."""
    await _course_analysee(db, "RAP1C1")
    resp = await client.get("/api/v1/courses/RAP1C1/apercu")
    assert resp.status_code == 200

    data = resp.json()
    assert data["disponible"] is True
    assert data["revele"] is False
    assert data["verdict"] is None
    assert data["nb_analyses"] == 3
    assert data["confiance"] == 61
    assert data["proba_top1"] == pytest.approx(0.30)
    # Le n°1 du modèle n'est pas le favori des cotes → c'est l'accroche de la carte.
    assert data["accord_marche"] is False
    assert data["bande_cote"] == "8 à 15"
    assert data["nb_ecartes"] == 1  # le cheval à 1 % de chances

    # AUCUN numéro ni nom de cheval ne doit transiter tant que la course n'est pas
    # courue : le pronostic reste la contrepartie de l'abonnement.
    brut = resp.text.upper()
    for nom in ("OUTSIDER TEST", "FAVORI MARCHE", "TOCARD TEST"):
        assert nom not in brut


async def test_apercu_revele_tout_une_fois_la_course_courue(client: AsyncClient, db: AsyncSession):
    """Course terminée = plus jouable : on montre ce que le modèle avait dit,
    réussite comme échec. C'est la preuve donnée au prospect."""
    await _course_analysee(db, "RAP2C1", statut="termine")
    db.add(Resultat(
        course_id="RAP2C1",
        classement=[
            {"numero": 3, "nom": "FAVORI MARCHE", "position": 1},
            {"numero": 7, "nom": "OUTSIDER TEST", "position": 2},
            {"numero": 5, "nom": "TOCARD TEST", "position": 3},
        ],
    ))
    await db.commit()

    data = (await client.get("/api/v1/courses/RAP2C1/apercu")).json()
    assert data["revele"] is True
    v = data["verdict"]
    assert [l["numero"] for l in v["arrivee"]] == [3, 7, 5]
    assert v["top3_modele"][0]["numero"] == 7
    assert v["top3_modele"][0]["nom"] == "OUTSIDER TEST"
    # Le gagnant (n°3) était 2ᵉ du modèle : raté sur le n°1, trouvé dans le top 3.
    assert v["rang_predit_gagnant"] == 2
    assert v["gagnant_top1"] is False
    assert v["gagnant_top3"] is True


async def test_apercu_course_non_analysee_repond_200_disponible_false(client: AsyncClient, db: AsyncSession):
    """Pas d'analyse en base → on le dit franchement (200 + disponible=false),
    jamais un 404 qui ferait disparaître la carte sans explication."""
    hippo = Hippodrome(hippodrome_id=str(uuid.uuid4()), nom="Sans Analyse", code="SAN")
    db.add(hippo)
    db.add(Reunion(
        reunion_id="RSA", date=date.today(), hippodrome_id=hippo.hippodrome_id,
        hippodrome_nom="Sans Analyse", numero=8,
    ))
    db.add(Course(
        course_id="RAP3C1", reunion_id="RSA", numero=1, nom="Prix Sans Analyse",
        date_heure=datetime.now(timezone.utc) + timedelta(hours=2),
        hippodrome_nom="Sans Analyse", discipline="Plat", distance=1600,
        nb_partants=0, statut="a_venir",
    ))
    await db.commit()

    resp = await client.get("/api/v1/courses/RAP3C1/apercu")
    assert resp.status_code == 200
    assert resp.json()["disponible"] is False


async def test_apercu_course_inconnue_404(client: AsyncClient):
    assert (await client.get("/api/v1/courses/NEXISTEPAS/apercu")).status_code == 404


async def test_apercu_classement_ne_nomme_que_la_queue(client: AsyncClient, db: AsyncSession):
    """Le classement montré avant la course : la FORME complète (rang +
    probabilités de chaque ligne) mais seulement les DERNIERS chevaux nommés.
    C'est l'avant-goût : on prouve la profondeur de l'analyse sans livrer la
    sélection, qui reste la contrepartie de l'abonnement."""
    await _course_analysee(db, "RAP4C1", champ=10)
    resp = await client.get("/api/v1/courses/RAP4C1/apercu")
    data = resp.json()

    lignes = data["classement"]
    assert len(lignes) == 10
    assert data["nb_lignes_revelees"] == 2

    # Toutes les lignes portent rang et probabilités — la distribution est visible.
    assert [l["rang"] for l in lignes] == list(range(1, 11))
    assert all(l["proba_top1"] is not None for l in lignes)

    # Les 8 premières ne portent NI numéro NI nom.
    for l in lignes[:8]:
        assert l["revele"] is False
        assert "numero" not in l and "nom" not in l
    # Les 2 dernières sont nommées, avec leur cote et la cote juste du modèle.
    for l in lignes[-2:]:
        assert l["revele"] is True
        assert l["nom"].startswith("FOND")
        assert l["cote"] is not None and l["cote_juste"] is not None

    # Le haut du classement ne fuit pas dans la charge utile brute.
    brut = resp.text.upper()
    assert "OUTSIDER TEST" not in brut and "FAVORI MARCHE" not in brut


async def test_apercu_petit_champ_ne_revele_aucune_ligne(client: AsyncClient, db: AsyncSession):
    """Dans un petit champ, écarter deux chevaux revient presque à donner la
    sélection : on ne nomme alors personne."""
    await _course_analysee(db, "RAP5C1", champ=5)
    data = (await client.get("/api/v1/courses/RAP5C1/apercu")).json()
    assert data["nb_lignes_revelees"] == 0
    assert all(l["revele"] is False for l in data["classement"])


async def test_apercu_classement_entierement_nomme_apres_la_course(client: AsyncClient, db: AsyncSession):
    """Course courue : le classement complet est public, avec la place réelle en
    face de chaque rang prédit — c'est la preuve montrée au prospect."""
    await _course_analysee(db, "RAP6C1", statut="termine", champ=10)
    db.add(Resultat(
        course_id="RAP6C1",
        classement=[
            {"numero": 3, "nom": "FAVORI MARCHE", "position": 1},
            {"numero": 7, "nom": "OUTSIDER TEST", "position": 2},
            {"numero": 5, "nom": "TOCARD TEST", "position": 3},
        ],
    ))
    await db.commit()

    data = (await client.get("/api/v1/courses/RAP6C1/apercu")).json()
    lignes = data["classement"]
    assert data["nb_lignes_revelees"] == len(lignes) == 10
    assert all(l["revele"] is True and "nom" in l for l in lignes)
    # Rang 1 du modèle = n°7, arrivé 2ᵉ.
    assert lignes[0]["numero"] == 7 and lignes[0]["position"] == 2
    # Un cheval hors des trois premiers n'a pas de position (arrivée partielle).
    assert "position" not in lignes[-1]


# ─────────────────────────────────────────────────────────────────────────────
# Profondeur de l'analyse montrée gratuitement
# ─────────────────────────────────────────────────────────────────────────────
# La page gratuite ne disait plus que « une analyse existe » : elle dit
# maintenant CE QUE le modèle a lu (combien de signaux, pour / contre, quelles
# familles) et le prouve sur les chevaux qu'il écarte. Ces deux tests gardent la
# frontière : l'agrégat ne doit désigner personne, et les signaux ne doivent
# jamais être joints à une ligne masquée.


async def test_apercu_compte_les_signaux_sans_designer_de_cheval(
    client: AsyncClient, db: AsyncSession,
):
    """L'agrégat de signaux est la preuve gratuite de profondeur : il chiffre ce
    que le modèle a retenu sur le champ. Il ne doit contenir aucun numéro, aucun
    nom, et aucune répartition qui permette de remonter à un cheval."""
    await _course_analysee(db, "RAP7C1", champ=10, avec_features=True)
    resp = await client.get("/api/v1/courses/RAP7C1/apercu")
    data = resp.json()

    sig = data["signaux_course"]
    assert sig is not None, "des features en base doivent produire des signaux"
    assert sig["total"] > 0
    # La répartition est cohérente : chaque signal tombe dans exactement un sens.
    assert sig["pour"] + sig["contre"] + sig["vigilance"] == sig["total"]
    # Les familles sont des libellés lisibles, jamais les clés brutes du ML.
    assert sig["familles"], "au moins une famille de signaux"
    assert all(f["n"] > 0 for f in sig["familles"])
    assert all(f["label"][0].isupper() for f in sig["familles"])

    # Le comptage des critères ne retient que les features RÉELLEMENT calculées :
    # `feature_jamais_calculee` vaut None, elle ne doit pas gonfler le chiffre.
    assert data["nb_criteres"] == 6

    # Le haut du classement ne fuit toujours pas — l'ajout des signaux ne doit
    # pas avoir ouvert une porte dérobée.
    brut = resp.text.upper()
    assert "OUTSIDER TEST" not in brut and "FAVORI MARCHE" not in brut


async def test_apercu_ne_joint_de_signaux_quaux_lignes_revelees(
    client: AsyncClient, db: AsyncSession,
):
    """Les signaux sont le cœur de ce qu'on vend : ils n'accompagnent que les
    chevaux que le modèle ÉCARTE (le bas du classement, déjà nommé). Une ligne
    masquée qui porterait ses signaux livrerait l'analyse ligne par ligne."""
    await _course_analysee(db, "RAP8C1", champ=10, avec_features=True)
    lignes = (await client.get("/api/v1/courses/RAP8C1/apercu")).json()["classement"]

    masquees = [l for l in lignes if not l["revele"]]
    revelees = [l for l in lignes if l["revele"]]
    assert masquees and revelees

    assert all("signaux" not in l for l in masquees)
    # Au moins une ligne révélée porte ses signaux, et chacun est complet.
    portees = [l for l in revelees if l.get("signaux")]
    assert portees, "les chevaux écartés doivent montrer POURQUOI ils le sont"
    for l in portees:
        assert len(l["signaux"]) <= 3
        for sg in l["signaux"]:
            assert sg["sens"] in ("positif", "negatif", "neutre")
            assert sg["label"]


async def test_apercu_sans_features_ne_fabrique_aucun_signal(
    client: AsyncClient, db: AsyncSession,
):
    """Aucune feature en base → aucun signal, aucun critère. On préfère une
    carte plus maigre à un chiffre reconstitué : c'est la règle de la fiche
    course (rien d'affiché qui ne vienne d'un champ réel)."""
    await _course_analysee(db, "RAP9C1", champ=10)
    data = (await client.get("/api/v1/courses/RAP9C1/apercu")).json()
    assert data["signaux_course"] is None
    assert data["nb_criteres"] == 0
    assert all("signaux" not in l for l in data["classement"])
