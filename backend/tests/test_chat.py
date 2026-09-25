"""Communauté (/api/v1/chat) : accès, pseudo, messages, modération."""

BASE = "/api/v1/chat"


async def _membre(inscrire, email: str, pseudo: str | None, client) -> dict[str, str]:
    headers = await inscrire(email=email)
    if pseudo:
        r = await client.put(f"{BASE}/pseudo", json={"pseudo": pseudo}, headers=headers)
        assert r.status_code == 200, r.text
    return headers


async def test_chat_exige_un_compte(client):
    assert (await client.get(f"{BASE}/messages")).status_code == 401
    assert (await client.post(f"{BASE}/messages", json={"contenu": "yo"})).status_code == 401


async def test_compte_gratuit_ecrit_apres_avoir_choisi_un_pseudo(client, inscrire, db):
    # Compte d'avant le pseudo obligatoire (ou ouvert via Google) : il n'en a pas.
    from sqlalchemy import update
    from db.models import User
    h = await inscrire(email="gratuit@blackturf.fr")
    await db.execute(update(User).where(User.email == "gratuit@blackturf.fr").values(pseudo=None))
    await db.commit()

    moi = (await client.get(f"{BASE}/moi", headers=h)).json()
    assert moi["pseudo"] is None and moi["banni"] is False

    r = await client.post(f"{BASE}/messages", json={"contenu": "Salut"}, headers=h)
    assert r.status_code == 409

    assert (await client.put(f"{BASE}/pseudo", json={"pseudo": "Turfiste_75"}, headers=h)).status_code == 200
    r = await client.post(f"{BASE}/messages", json={"contenu": "  Salut la commu \n\n\n\n!  "}, headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["contenu"] == "Salut la commu \n\n!"
    assert corps["auteur"]["pseudo"] == "Turfiste_75"
    assert corps["auteur"]["role"] == "membre"

    liste = (await client.get(f"{BASE}/messages", headers=h)).json()
    assert [m["message_id"] for m in liste["messages"]] == [corps["message_id"]]
    assert liste["plus_anciens"] is False


async def test_compteur_de_messages_non_lus(client, inscrire):
    lecteur = await _membre(inscrire, "lecteur@blackturf.fr", "Lecteur", client)
    bavard = await _membre(inscrire, "bavard@blackturf.fr", "Bavard", client)
    assert (await client.get(f"{BASE}/non-lus", headers=lecteur)).json() == {"non_lus": 0}

    for texte in ("un", "deux"):
        assert (await client.post(f"{BASE}/messages", json={"contenu": texte}, headers=bavard)).status_code == 200

    assert (await client.get(f"{BASE}/non-lus", headers=lecteur)).json() == {"non_lus": 2}
    # Ses propres messages ne comptent pas.
    assert (await client.get(f"{BASE}/non-lus", headers=bavard)).json() == {"non_lus": 0}

    assert (await client.post(f"{BASE}/lu", headers=lecteur)).status_code == 204
    assert (await client.get(f"{BASE}/non-lus", headers=lecteur)).json() == {"non_lus": 0}

    assert (await client.post(f"{BASE}/messages", json={"contenu": "trois"}, headers=bavard)).status_code == 200
    assert (await client.get(f"{BASE}/non-lus", headers=lecteur)).json() == {"non_lus": 1}


async def test_pseudo_unique_sans_tenir_compte_de_la_casse(client, inscrire):
    await _membre(inscrire, "a@blackturf.fr", "Turfiste", client)
    h2 = await inscrire(email="b@blackturf.fr")
    r = await client.put(f"{BASE}/pseudo", json={"pseudo": "turfiste"}, headers=h2)
    assert r.status_code == 409


async def test_pseudo_modifiable_et_repercute_sur_les_messages(client, inscrire):
    h = await _membre(inscrire, "change@blackturf.fr", "AncienNom", client)
    await client.post(f"{BASE}/messages", json={"contenu": "avant"}, headers=h)
    await _membre(inscrire, "occupe@blackturf.fr", "NomPris", client)

    assert (await client.put(f"{BASE}/pseudo", json={"pseudo": "nompris"}, headers=h)).status_code == 409
    r = await client.put(f"{BASE}/pseudo", json={"pseudo": "NouveauNom"}, headers=h)
    assert r.status_code == 200 and r.json() == {"pseudo": "NouveauNom"}
    # Reprendre son propre pseudo, casse changée comprise, reste permis.
    assert (await client.put(f"{BASE}/pseudo", json={"pseudo": "nouveaunom"}, headers=h)).status_code == 200

    assert (await client.get(f"{BASE}/moi", headers=h)).json()["pseudo"] == "nouveaunom"
    messages = (await client.get(f"{BASE}/messages", headers=h)).json()["messages"]
    assert [m["auteur"]["pseudo"] for m in messages if m["contenu"] == "avant"] == ["nouveaunom"]


async def test_pseudo_invalide_ou_reserve(client, inscrire):
    h = await inscrire(email="c@blackturf.fr")
    for pseudo in ("ab", "avec espace", "x" * 21, "BlackTurfOfficiel", "LeModo"):
        r = await client.put(f"{BASE}/pseudo", json={"pseudo": pseudo}, headers=h)
        assert r.status_code == 422, pseudo


async def test_message_vide_ou_trop_long(client, inscrire):
    h = await _membre(inscrire, "d@blackturf.fr", "Dede", client)
    assert (await client.post(f"{BASE}/messages", json={"contenu": "   \n "}, headers=h)).status_code == 422
    assert (await client.post(f"{BASE}/messages", json={"contenu": "x" * 501}, headers=h)).status_code == 422


async def test_seul_l_auteur_ou_l_admin_supprime(client, inscrire, admin_headers):
    ha = await _membre(inscrire, "e@blackturf.fr", "Auteur", client)
    hb = await _membre(inscrire, "f@blackturf.fr", "Voisin", client)
    m1 = (await client.post(f"{BASE}/messages", json={"contenu": "un"}, headers=ha)).json()
    m2 = (await client.post(f"{BASE}/messages", json={"contenu": "deux"}, headers=ha)).json()

    assert (await client.delete(f"{BASE}/messages/{m1['message_id']}", headers=hb)).status_code == 403
    assert (await client.delete(f"{BASE}/messages/{m1['message_id']}", headers=ha)).status_code == 204
    assert (await client.delete(f"{BASE}/messages/{m2['message_id']}", headers=admin_headers)).status_code == 204

    assert (await client.get(f"{BASE}/messages", headers=hb)).json()["messages"] == []


async def test_signalement_puis_bannissement(client, inscrire, admin_headers):
    ha = await _membre(inscrire, "g@blackturf.fr", "Fauteur", client)
    hb = await _membre(inscrire, "h@blackturf.fr", "Temoin", client)
    msg = (await client.post(f"{BASE}/messages", json={"contenu": "pub casino"}, headers=ha)).json()
    auteur_id = msg["auteur"]["user_id"]

    # Pas d'auto-signalement ; signaler deux fois ne crée qu'un signalement.
    assert (await client.post(f"{BASE}/messages/{msg['message_id']}/signaler", json={}, headers=ha)).status_code == 422
    for _ in range(2):
        r = await client.post(f"{BASE}/messages/{msg['message_id']}/signaler",
                              json={"motif": "spam"}, headers=hb)
        assert r.status_code == 204

    # La modération est fermée aux membres.
    assert (await client.get(f"{BASE}/moderation/signalements", headers=hb)).status_code == 403
    assert (await client.put(f"{BASE}/moderation/bannis/{auteur_id}", json={"banni": True},
                             headers=hb)).status_code == 403

    sig = (await client.get(f"{BASE}/moderation/signalements", headers=admin_headers)).json()["signalements"]
    assert len(sig) == 1 and sig[0]["motif"] == "spam" and sig[0]["signale_par"] == "Temoin"

    r = await client.put(f"{BASE}/moderation/bannis/{auteur_id}",
                         json={"banni": True, "effacer_messages": True}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["messages_effaces"] == 1

    assert (await client.get(f"{BASE}/messages", headers=ha)).status_code == 403
    assert (await client.post(f"{BASE}/messages", json={"contenu": "re"}, headers=ha)).status_code == 403
    assert (await client.get(f"{BASE}/messages", headers=hb)).json()["messages"] == []
    assert (await client.get(f"{BASE}/moderation/signalements", headers=admin_headers)).json()["signalements"] == []

    bannis = (await client.get(f"{BASE}/moderation/bannis", headers=admin_headers)).json()["bannis"]
    assert [b["user_id"] for b in bannis] == [auteur_id]

    r = await client.put(f"{BASE}/moderation/bannis/{auteur_id}", json={"banni": False}, headers=admin_headers)
    assert r.status_code == 200
    assert (await client.get(f"{BASE}/messages", headers=ha)).status_code == 200
