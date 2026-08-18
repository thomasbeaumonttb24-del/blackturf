"""
Régression 2026-08-17 — le centre de notifications affichait « Aucune notification ·
Tout est lu » alors que la base contenait 22 400 alertes in-app NON LUES pour le
compte concerné (et que le badge de la navbar affichait bien « 9+ »).

Trois bugs empilés, un test par bug :

1. ROUTE FANTÔME — la liste n'existait que sur `/notifications/`. Le front appelle
   `/notifications` : FastAPI répondait 307 vers `http://…` (uvicorn sans
   `--proxy-headers` ignorait le X-Forwarded-Proto de nginx), et un navigateur sur
   une page https refuse de suivre une redirection http → requête morte, écran vide.
2. CONTENU ILLISIBLE — `_alerte_dict` lisait `titre`/`description` à la racine du
   payload, que rien ne produit : tout se serait affiché « value_bet_digest » avec
   une description vide.
3. TRIPLONS — chaque value bet écrit une ligne par canal (in-app + email + push) ;
   le centre listait les trois et le badge comptait 67 175 « non lues » pour 22 400
   événements réels.

Plus : les PRÉFÉRENCES étaient décoratives (écrites par l'UI, lues par personne) et
l'onglet « Résultats » structurellement vide (aucun code ne produisait d'alerte de
résultat).
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from api.routes.notifications import CATEGORIES, _alerte_dict, _rendu
from db.models import AlerteLog, User


# ─── Rendu du payload (bug 2) ──────────────────────────────────

def test_rendu_value_bet_unitaire():
    """Payload réel d'un value bet unitaire (aucun champ `titre` à la racine)."""
    titre, desc = _rendu("value_bet", {
        "ev": 2.15, "cote": 6.4, "niveau": 3, "course_id": "17082026R1C6",
        "hippodrome": "HIPPODROME DE CLAIREFONTAINE", "nom_cheval": "LOUBRALTAR",
        "heure_depart": "2026-08-17T15:13:00+00:00",
    })
    assert "LOUBRALTAR" in titre
    assert "★★★" in titre
    assert "6,40" in titre                      # cote formatée à la française
    assert "CLAIREFONTAINE" in desc
    assert titre != "value_bet"                 # l'ancien rendu tombait sur le type


def test_rendu_digest_un_seul_pari():
    """Digest à 1 élément → on raconte le pari, pas « 1 paris de valeur »."""
    titre, desc = _rendu("value_bet_digest", {
        "nb_value_bets": 1,
        "value_bets": [{
            "niveau": 2, "cote": 9.2, "nom_cheval": "RAPIDE DA CLODIA AA",
            "course_id": "17082026R4C7", "hippodrome": "HIPPODROME DE MONT DE MARSAN",
        }],
    })
    assert "RAPIDE DA CLODIA AA" in titre
    assert "MONT DE MARSAN" in desc


def test_rendu_digest_multiple_liste_les_chevaux():
    vbs = [{"niveau": 3, "nom_cheval": f"CHEVAL {i}", "cote": 4.0} for i in range(5)]
    titre, desc = _rendu("value_bet_digest", {"nb_value_bets": 5, "value_bets": vbs})
    assert titre.startswith("5 paris de valeur")
    assert "CHEVAL 0" in desc
    assert "+2 autres" in desc                  # aperçu borné à 3 + reste compté


def test_rendu_resultat_pari_gagnant():
    titre, desc = _rendu("resultat_pari", {
        "nb_gagnes": 1, "nb_perdus": 0, "gain_net": 45.2,
        "hippodrome": "HIPPODROME DE VINCENNES", "arrivee": "3 - 1 - 7",
    })
    assert "gagné" in titre.lower()
    assert "+45,20" in titre
    assert "3 - 1 - 7" in desc


def test_rendu_resultat_value_bet_selon_la_place():
    t1, _ = _rendu("resultat_value_bet", {"nom_cheval": "ALPHA", "position": 1,
                                          "rapport_simple_gagnant": 6.4})
    t3, _ = _rendu("resultat_value_bet", {"nom_cheval": "BETA", "position": 3})
    t0, _ = _rendu("resultat_value_bet", {"nom_cheval": "GAMMA", "position": None})
    assert "GAGNÉ" in t1 and "6,40" in t1
    assert "placé" in t3
    assert "non placé" in t0


def test_rendu_ne_plante_pas_sur_payload_vide():
    """Payload absent/inconnu : titre lisible, jamais d'exception (le centre ne doit
    jamais tomber à cause d'une seule ligne mal formée)."""
    titre, desc = _rendu("type_inconnu", {})
    assert titre == "Type inconnu"
    assert desc == ""


def test_alerte_dict_expose_la_categorie():
    """La catégorie est calculée côté SERVEUR : le front n'a pas à deviner la
    taxonomie par sous-chaînes (« course » matchait « resultat » par accident)."""
    a = AlerteLog(alerte_id="a1", user_id="u1", type_alerte="resultat_pari",
                  canal="in-app", payload={"course_id": "17082026R1C6"},
                  lue=False, envoye=True, created_at=datetime.now(timezone.utc))
    d = _alerte_dict(a)
    assert d["categorie"] == "resultat"
    assert d["course_id"] == "17082026R1C6"     # bouton « Voir la course »


def test_toutes_les_categories_sont_des_onglets_du_front():
    assert set(CATEGORIES.values()) <= {"value_bet", "resultat", "systeme"}


# ─── Endpoints (bugs 1 et 3) ───────────────────────────────────

async def _seed_user(db, *, plan="expert", prefs=None) -> User:
    u = User(user_id=str(uuid.uuid4()), email=f"{uuid.uuid4().hex[:8]}@t.fr",
             hashed_password="x", plan=plan, is_active=True,
             push_subscription=({"prefs": prefs} if prefs else None))
    db.add(u)
    await db.commit()
    return u


async def _seed_alerte(db, user, *, canal="in-app", type_alerte="value_bet_digest",
                       lue=False, payload=None, minutes_ago=1):
    a = AlerteLog(
        alerte_id=str(uuid.uuid4()), user_id=user.user_id, type_alerte=type_alerte,
        canal=canal, payload=payload if payload is not None else {
            "nb_value_bets": 1,
            "value_bets": [{"niveau": 3, "nom_cheval": "LOUBRALTAR", "cote": 6.4,
                            "course_id": "17082026R1C6", "hippodrome": "CLAIREFONTAINE"}],
        },
        lue=lue, envoye=True,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )
    db.add(a)
    await db.commit()
    return a


async def _auth(client, user) -> dict:
    """En-tête Bearer pour cet utilisateur (jeton signé, comme en production)."""
    from api.routes.auth import create_tokens
    return {"Authorization": f"Bearer {create_tokens(user.user_id, user.plan).access_token}"}


async def test_liste_accessible_sans_slash_final(client, db):
    """LE bug bloquant : `/notifications` (sans slash) doit répondre 200 DIRECTEMENT.
    Un 307 renvoie le navigateur vers http:// derrière le proxy → requête bloquée."""
    user = await _seed_user(db)
    await _seed_alerte(db, user)
    headers = await _auth(client, user)

    r = await client.get("/api/v1/notifications", headers=headers)

    assert r.status_code == 200, f"redirection ou erreur : {r.status_code}"
    assert len(r.json()["items"]) == 1


async def test_liste_accessible_avec_slash_final(client, db):
    """L'ancien chemin reste servi : un front en cache ne doit pas casser."""
    user = await _seed_user(db)
    await _seed_alerte(db, user)
    r = await client.get("/api/v1/notifications/", headers=await _auth(client, user))
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1


async def test_un_evenement_une_seule_ligne_malgre_trois_canaux(client, db):
    """Bug 3 : un value bet écrit in-app + email + push. Le centre montre UN élément
    et le compteur compte UN non lu, pas trois."""
    user = await _seed_user(db)
    for canal in ("in-app", "email", "push"):
        await _seed_alerte(db, user, canal=canal)
    headers = await _auth(client, user)

    liste = (await client.get("/api/v1/notifications", headers=headers)).json()
    compteur = (await client.get("/api/v1/notifications/count-unread", headers=headers)).json()

    assert len(liste["items"]) == 1
    assert liste["items"][0]["canal"] == "in-app"
    assert liste["total_unread"] == 1
    assert compteur["count"] == 1


async def test_annonce_email_visible_pour_un_compte_free(client, db):
    """Un compte Free ne reçoit aucune alerte value bet in-app. Sans cette exception
    son centre serait vide alors qu'il a bien reçu une annonce produit."""
    user = await _seed_user(db, plan="free")
    await _seed_alerte(db, user, canal="email", type_alerte="free_plan_announcement",
                       payload={"titre": "Votre offre découverte"})
    r = await client.get("/api/v1/notifications", headers=await _auth(client, user))
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["titre"] == "Votre offre découverte"
    assert items[0]["categorie"] == "systeme"


async def test_filtre_categorie_cote_serveur(client, db):
    user = await _seed_user(db)
    await _seed_alerte(db, user, type_alerte="value_bet_digest")
    await _seed_alerte(db, user, type_alerte="resultat_pari",
                       payload={"nb_gagnes": 1, "nb_perdus": 0, "gain_net": 12.0,
                                "course_id": "17082026R1C6"})
    headers = await _auth(client, user)

    res = (await client.get("/api/v1/notifications?categorie=resultat",
                            headers=headers)).json()
    vb = (await client.get("/api/v1/notifications?categorie=value_bet",
                           headers=headers)).json()

    assert [i["categorie"] for i in res["items"]] == ["resultat"]
    assert [i["categorie"] for i in vb["items"]] == ["value_bet"]


async def test_categorie_inconnue_rejetee(client, db):
    user = await _seed_user(db)
    r = await client.get("/api/v1/notifications?categorie=nimporte",
                          headers=await _auth(client, user))
    assert r.status_code == 422


async def test_cloisonnement_entre_utilisateurs(client, db):
    """Une notification d'un autre compte ne doit jamais apparaître ni être lisible."""
    moi = await _seed_user(db)
    autre = await _seed_user(db)
    a_autre = await _seed_alerte(db, autre)
    headers = await _auth(client, moi)

    liste = (await client.get("/api/v1/notifications", headers=headers)).json()
    assert liste["items"] == []

    r = await client.put(f"/api/v1/notifications/{a_autre.alerte_id}/lue", headers=headers)
    assert r.status_code == 404


async def test_tout_marquer_lu_couvre_tous_les_canaux(client, db):
    """Le marquage global porte sur tous les canaux : sinon les lignes email/push
    resteraient `lue=false` à vie sans que l'utilisateur puisse y toucher."""
    user = await _seed_user(db)
    for canal in ("in-app", "email", "push"):
        await _seed_alerte(db, user, canal=canal)
    headers = await _auth(client, user)

    r = await client.delete("/api/v1/notifications/all", headers=headers)
    assert r.status_code == 200
    assert r.json()["total_unread"] == 0

    restantes = (await db.execute(
        select(AlerteLog).where(AlerteLog.user_id == user.user_id,
                                AlerteLog.lue == False)  # noqa: E712
    )).scalars().all()
    assert restantes == []


async def test_prefs_persistees_et_relues(client, db):
    """Bug des préférences : muter en place le JSON ne marquait pas la colonne sale.
    On vérifie l'aller-retour complet PUT → GET."""
    user = await _seed_user(db)
    headers = await _auth(client, user)

    r = await client.put("/api/v1/notifications/prefs",
                          json={"vb_niveau_min": 4, "resultats_suivis": False},
                          headers=headers)
    assert r.status_code == 200

    prefs = (await client.get("/api/v1/notifications/prefs", headers=headers)).json()
    assert prefs["vb_niveau_min"] == 4
    assert prefs["resultats_suivis"] is False
    assert prefs["alertes_systeme"] is True     # non touché → défaut conservé


async def test_prefs_niveau_invalide_rejete(client, db):
    user = await _seed_user(db)
    r = await client.put("/api/v1/notifications/prefs", json={"vb_niveau_min": 9},
                          headers=await _auth(client, user))
    assert r.status_code == 422
