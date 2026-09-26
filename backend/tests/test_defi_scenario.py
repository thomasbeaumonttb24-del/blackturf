"""Défi du mois — scénario complet, de bout en bout, par l'API.

Plusieurs joueurs aux profils différents font chacun des choses différentes sur
les mêmes courses, puis on vérifie tout ce que le site en montre : règlement,
soldes, classement, étiquettes plan/perso, notifications, back-office, clôture,
récompenses et fin des récompenses.

  Alice   compte gratuit qui a consulté le plan : joue le Tiercé et le Couplé du plan.
  Bruno   compte gratuit sans quota, n'a jamais vu le plan : ses propres chevaux,
          dont un pari sur une course annulée.
  Chloé   abonnée Expert : Multi, Quinté+, bute sur la limite de 3 paris par
          course, et un cheval devient non-partant après son pari.
  Emma    joue, puis son compte est suspendu : elle sort du classement.
  David   ancien compte sans pseudo : bloqué tant qu'il n'en a pas choisi un.
  Admin   joue le meilleur pari mais reste hors concours.
  Visiteur sans compte : voit le classement, ne peut pas parier.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from db.models import AlerteLog, BetPlanSnapshot, Course, DefiPari, Participation, User
from services import defi
from tests.test_defi import (
    AGREGAT_JACKPOT, ARRIVEE_JACKPOT, DETAIL_JACKPOT, TOUS_LES_CODES, _arrivee, _course,
)

pytestmark = pytest.mark.asyncio

API = "/api/v1/defi"


@pytest.fixture(autouse=True)
def _defi_lance(monkeypatch):
    monkeypatch.setattr(defi, "PREMIER_MOIS", "2000-01")
    defi.invalider_classement()
    yield
    defi.invalider_classement()


async def _compte(db, email) -> User:
    return (await db.execute(select(User).where(User.email == email))).scalars().one()


async def _completer(db, user: User, n: int):
    """Paris déjà réglés (perdus, 10 pts) plus tôt dans le mois : de quoi atteindre
    le minimum de paris pour être classé sans rejouer dix courses par joueur."""
    for _ in range(n):
        db.add(DefiPari(user_id=user.user_id, mois=defi.mois_courant(),
                        course_id=f"H{uuid.uuid4().hex[:8]}", type_pari="Simple Gagnant",
                        chevaux=[1], points=10, origine="perso", statut="perd", points_retour=0.0,
                        engage_at=datetime.now(timezone.utc) - timedelta(days=1)))
    await db.commit()


async def _parier(client, headers, course_id, type_pari, chevaux, points):
    return await client.post(f"{API}/paris", headers=headers, json={
        "course_id": course_id, "type_pari": type_pari, "chevaux": chevaux, "points": points})


async def _fermer(db, course_id):
    """Le temps passe jusqu'au départ : les paris déjà engagés l'ont été 30 min
    plus tôt, le départ prévu est passé de 5 min."""
    maintenant = datetime.now(timezone.utc)
    for p in (await db.execute(select(DefiPari).where(DefiPari.course_id == course_id))).scalars():
        p.engage_at = maintenant - timedelta(minutes=30)
    c = await db.get(Course, course_id)
    c.date_heure = maintenant - timedelta(minutes=5)
    await db.commit()
    return c


async def test_scenario_complet_du_defi(client, db, inscrire, admin_headers):
    from api.config import get_settings
    from api.routes.auth import create_tokens
    from services.alerts import notify_resultats_course
    from services.bet_plan_snapshots import subject_hash

    # ── Inscriptions ────────────────────────────────────────────────────────
    sans_pseudo = await client.post("/api/v1/auth/register", json={
        "email": "sanspseudo@x.fr", "password": "TestPassword123!"})
    assert sans_pseudo.status_code == 422, "l'inscription exige un pseudo"

    h_alice = await inscrire(email="alice@x.fr", pseudo="Alice")
    h_bruno = await inscrire(email="bruno@x.fr", pseudo="Bruno")
    h_chloe = await inscrire(email="chloe@x.fr", pseudo="Chloe")
    h_emma = await inscrire(email="emma@x.fr", pseudo="Emma")
    doublon = await client.post("/api/v1/auth/register", json={
        "email": "autre@x.fr", "password": "TestPassword123!", "pseudo": "ALICE"})
    assert doublon.status_code in (400, 409), "pseudo déjà pris, casse comprise"

    alice, bruno, chloe, emma = [await _compte(db, f"{n}@x.fr") for n in ("alice", "bruno", "chloe", "emma")]
    chloe.plan = "expert"
    admin = await _compte(db, "admin@blackturf.fr")
    admin.pseudo = "LeBoss"
    david = User(user_id=str(uuid.uuid4()), email="david@x.fr", email_verified=True, plan="free")
    db.add(david)
    await db.commit()
    h_david = {"Authorization": f"Bearer {create_tokens(david.user_id, david.plan).access_token}"}

    # ── Les courses du jour ─────────────────────────────────────────────────
    await _course(db, "Q", nb=16, paris_disponibles=TOUS_LES_CODES)          # le Quinté
    await _course(db, "P", nb=6, paris_disponibles=["E_SIMPLE_GAGNANT", "E_SIMPLE_PLACE"])
    await _course(db, "A", nb=10, paris_disponibles=["E_SIMPLE_GAGNANT"])      # sera annulée
    await _course(db, "N", nb=10, paris_disponibles=["E_SIMPLE_GAGNANT"])      # non-partant

    # Alice a consulté le plan de mise du Quinté (et elle seule).
    plan = {"niveaux": [
        {"niveau": "rendement", "label": "Rendement", "paris": [
            {"type": "Couplé Gagnant", "chevaux": [{"numero": 1}, {"numero": 4}]}]},
        {"niveau": "coup", "label": "Coup à tenter", "paris": [
            {"type": "Tiercé Ordre", "chevaux": [{"numero": 1}, {"numero": 4}, {"numero": 3}]}]},
    ]}
    db.add(BetPlanSnapshot(course_id="Q", subject_hash=subject_hash(alice.user_id, get_settings().secret_key),
                           profil="equilibre", montant_demande=10, plan=plan, plan_hash="h",
                           cotes_utilisees={}, algo_config={}, algo_version="t", nb_paris=2,
                           montant_joue=10, emitted_at=datetime.now(timezone.utc), is_pre_course=True))
    await db.commit()

    # ── Visiteur sans compte ────────────────────────────────────────────────
    client.cookies.clear()
    assert (await client.get(f"{API}/classement")).status_code == 200
    assert (await _parier(client, {}, "Q", "Simple Gagnant", [1], 10)).status_code == 401
    anonyme = (await client.get(f"{API}/course/Q")).json()
    assert anonyme["solde"] is None and anonyme["mes_paris"] == [] and anonyme["plan"] == []

    # ── Ce que chacun voit sur la carte du Quinté ───────────────────────────
    vue_alice = (await client.get(f"{API}/course/Q", headers=h_alice)).json()
    assert [(p["libelle"], p["chevaux"]) for p in vue_alice["plan"]] == [
        ("Couplé Gagnant", [1, 4]), ("Tiercé Ordre", [1, 4, 3])]
    assert len(vue_alice["types"]) == 14 and vue_alice["ouvert"] and vue_alice["solde"] == 1000
    vue_bruno = (await client.get(f"{API}/course/Q", headers=h_bruno)).json()
    assert vue_bruno["plan"] == [], "un compte qui n'a pas vu le plan n'en découvre rien ici"

    # ── Les paris ───────────────────────────────────────────────────────────
    # Alice : les deux paris de son plan (le Couplé, dans l'autre sens : même pari).
    r = await _parier(client, h_alice, "Q", "Tiercé", [1, 4, 3], 10)
    assert r.status_code == 201 and r.json()["origine"] == "plan"
    r = await _parier(client, h_alice, "Q", "Couplé Gagnant", [4, 1], 50)
    assert r.json()["origine"] == "plan"
    vue_alice = (await client.get(f"{API}/course/Q", headers=h_alice)).json()
    assert all(p["deja_joue"] for p in vue_alice["plan"]) and vue_alice["solde"] == 940

    # Bruno : ses chevaux, et quelques erreurs refusées proprement.
    assert (await _parier(client, h_bruno, "Q", "Simple Gagnant", [1], 100)).json()["origine"] == "perso"
    assert (await _parier(client, h_bruno, "Q", "Simple Placé", [10], 50)).status_code == 201
    for course_id, type_pari, chevaux, points, attendu in [
        ("P", "Tiercé", [1, 2, 3], 10, "pas proposé"),        # petite course, pas de Tiercé
        ("P", "Simple Gagnant", [9], 10, "non-partant"),      # 6 partants seulement
        ("P", "Simple Gagnant", [1], 500, "Mise entre"),
        ("P", "Couplé Gagnant", [1], 10, "choisissez 2"),
    ]:
        r = await _parier(client, h_bruno, course_id, type_pari, chevaux, points)
        assert r.status_code == 400 and attendu in r.json()["detail"], (type_pari, r.text)
    assert (await _parier(client, h_bruno, "A", "Simple Gagnant", [2], 40)).status_code == 201

    # Chloé : Multi en 5, Quinté+ dans le désordre, un Simple perdant, puis la limite.
    assert (await _parier(client, h_chloe, "Q", "Multi", [1, 4, 3, 10, 8], 30)).json()["type_pari"] == "Multi en 5"
    assert (await _parier(client, h_chloe, "Q", "Quinté+", [1, 4, 3, 8, 10], 10)).status_code == 201
    assert (await _parier(client, h_chloe, "Q", "Simple Gagnant", [2], 10)).status_code == 201
    r = await _parier(client, h_chloe, "Q", "Simple Gagnant", [3], 10)
    assert r.status_code == 400 and "Maximum 3" in r.json()["detail"]
    assert (await _parier(client, h_chloe, "N", "Simple Gagnant", [5], 20)).status_code == 201

    # Emma : un Couplé Ordre dans le mauvais ordre.
    assert (await _parier(client, h_emma, "Q", "Couplé Ordre", [4, 1], 100)).status_code == 201

    # David : pas de pseudo, pas de pari ; il en choisit un, il joue.
    r = await _parier(client, h_david, "Q", "Simple Gagnant", [1], 10)
    assert r.status_code == 400 and "pseudo" in r.json()["detail"]
    assert (await client.patch("/api/v1/auth/me", headers=h_david, json={"pseudo": "Dave"})).status_code == 200
    assert (await _parier(client, h_david, "Q", "Simple Gagnant", [1], 10)).status_code == 201

    # L'admin joue le gagnant à 100 points : il ne sera jamais classé.
    assert (await _parier(client, admin_headers, "Q", "Simple Gagnant", [1], 100)).status_code == 201

    # Tendance : le cheval le plus joué reste secret tant que les paris sont ouverts.
    assert (await client.get(f"{API}/course/Q", headers=h_bruno)).json()["tendance"]["cheval_plus_joue"] is None

    # ── Départ : plus aucun pari ────────────────────────────────────────────
    q = await _fermer(db, "Q")
    r = await _parier(client, h_bruno, "Q", "Simple Gagnant", [4], 10)
    assert r.status_code == 400 and "fermés" in r.json()["detail"]
    assert (await client.get(f"{API}/course/Q", headers=h_bruno)).json()["tendance"]["cheval_plus_joue"] == 1

    # Les paris d'avant ce jour, pour que chacun atteigne le minimum de 10 paris.
    await _completer(db, alice, 8)
    await _completer(db, bruno, 7)
    await _completer(db, chloe, 6)
    await _completer(db, emma, 9)

    # ── Arrivées ────────────────────────────────────────────────────────────
    await _arrivee(db, q, ordre=ARRIVEE_JACKPOT,
                   rapports={**AGREGAT_JACKPOT, "simple_gagnant": 5.0, "couple_gagnant": 20.0},
                   detail={**DETAIL_JACKPOT, "simple_place": [
                       {"combinaison": "1", "rapport": 1.8}, {"combinaison": "4", "rapport": 2.6},
                       {"combinaison": "3", "rapport": 2.1}]})
    a = await db.get(Course, "A")
    a.statut = "annule"
    n = await _fermer(db, "N")
    np = (await db.execute(select(Participation).where(
        Participation.course_id == "N", Participation.numero == 5))).scalars().one()
    np.non_partant = True
    await db.commit()
    await _arrivee(db, n, ordre=(2, 6, 1))

    # Le pipeline règle chaque course puis envoie les résultats.
    for cid in ("Q", "A", "N"):
        await defi.regler_course(db, cid)
        await notify_resultats_course(db, cid)
    assert (await db.execute(select(DefiPari).where(DefiPari.statut == "en_attente"))).first() is None

    # ── Ce que chacun retrouve ──────────────────────────────────────────────
    paris_alice = {p["type_pari"]: p for p in (await client.get(f"{API}/moi", headers=h_alice)).json()["paris"]}
    assert (paris_alice["Tiercé"]["statut"], paris_alice["Tiercé"]["rapport"],
            paris_alice["Tiercé"]["points_retour"]) == ("gagne", 1479.9, 14799.0)   # ordre exact
    assert paris_alice["Couplé Gagnant"]["points_retour"] == 1000.0
    moi_chloe = (await client.get(f"{API}/moi", headers=h_chloe)).json()
    par_type = {p["type_pari"]: p for p in moi_chloe["paris"] if p["course_id"] in ("Q", "N")}
    assert par_type["Multi en 5"]["points_retour"] == 3465.0                       # 30 × 115,5
    assert par_type["Quinté+"]["points_retour"] == 1382.0                          # désordre 138,2
    assert [p["statut"] for p in moi_chloe["paris"] if p["course_id"] == "N"] == ["rembourse"]
    moi_bruno = (await client.get(f"{API}/moi", headers=h_bruno)).json()
    assert {p["course_id"]: p["statut"] for p in moi_bruno["paris"] if p["course_id"] in ("A",)} == {"A": "rembourse"}
    assert moi_bruno["perso"]["nb_paris"] == 10 and moi_bruno["plan"]["nb_paris"] == 0
    moi_alice = (await client.get(f"{API}/moi", headers=h_alice)).json()
    assert moi_alice["plan"]["nb_paris"] == 2 and moi_alice["plan"]["nb_gagnes"] == 2

    # ── Classement ──────────────────────────────────────────────────────────
    cl = (await client.get(f"{API}/classement", headers=h_bruno)).json()
    classes = [(l["rang"], l["nom"], l["solde"]) for l in cl["lignes"] if l["classe"]]
    assert classes == [
        (1, "Alice", 1000 - 80 - 60 + 14799 + 1000),       # 16 659
        (2, "Chloe", 1000 - 60 - 50 + 3465 + 1382),        # 5 737
        (3, "Bruno", 1000 - 70 - 150 + 500),               # 1 280
        (4, "Emma", 1000 - 90 - 100),                      # 810
    ]
    par_nom = {l["nom"]: l for l in cl["lignes"]}
    assert par_nom["LeBoss"]["hors_concours"] and par_nom["LeBoss"]["rang"] is None
    assert par_nom["Dave"]["rang"] is None                # 1 pari : pas encore classé
    assert cl["ma_ligne"]["nom"] == "Bruno" and cl["ma_ligne"]["moi"] is True
    assert all("@" not in l["nom"] and "user_id" not in l for l in cl["lignes"])

    # ── Notifications ───────────────────────────────────────────────────────
    def types_de(u):
        return [a.type_alerte for a in alertes if a.user_id == u.user_id]
    alertes = (await db.execute(select(AlerteLog).where(AlerteLog.canal == "in-app"))).scalars().all()
    for u in (alice, bruno, chloe, emma):
        assert "resultat_defi" in types_de(u), u.pseudo
    rangs = {a.user_id: a.payload["titre"] for a in alertes if a.type_alerte == "defi_rang"}
    assert rangs.get(alice.user_id) == "Défi : vous prenez la 1re place !"
    centre = (await client.get("/api/v1/notifications", headers=h_alice)).json()["items"]
    assert any(i["titre"].startswith("Défi : pari gagné") for i in centre)

    # ── Back-office ─────────────────────────────────────────────────────────
    comptes = (await client.get("/admin/api/users?limit=200", headers=admin_headers)).json()
    ligne_alice = next(l for l in comptes if l["email"] == "alice@x.fr")
    assert (ligne_alice["defi_rang"], ligne_alice["defi_solde"], ligne_alice["nb_paris"]) == (1, 16659, 10)
    cloture = (await client.get("/admin/api/defi/cloture", headers=admin_headers)).json()
    assert not cloture["mois_termine"] and [l["nom"] for l in cloture["lignes"]][:3] == ["Alice", "Chloe", "Bruno"]
    trop_tot = await client.post("/admin/api/defi/recompenses", headers=admin_headers,
                                 json={"mois": defi.mois_courant(), "rang": 1})
    assert trop_tot.status_code == 400, "le mois n'est pas fini"

    # Emma est suspendue (fraude) : elle disparaît du classement.
    emma.is_active = False
    await db.commit()
    defi.invalider_classement()
    noms = [l["nom"] for l in (await client.get(f"{API}/classement")).json()["lignes"]]
    assert "Emma" not in noms

    # ── Fin du mois : récompenses, puis leur expiration ─────────────────────
    mois = defi.mois_courant()
    a_, m_ = map(int, mois.split("-"))
    debut_suivant = datetime(a_ + (m_ == 12), m_ % 12 + 1, 2, 12, tzinfo=timezone.utc)
    r1 = await defi.attribuer_recompense(db, mois, 1, now=debut_suivant)
    r2 = await defi.attribuer_recompense(db, mois, 2, now=debut_suivant)
    r3 = await defi.attribuer_recompense(db, mois, 3, now=debut_suivant)
    assert (r1.user_id, r1.statut, r1.plan_offert) == (alice.user_id, "applique", "expert")
    assert (r2.user_id, r2.statut) == (chloe.user_id, "manuel")       # déjà Expert : geste manuel
    assert (r3.user_id, r3.statut, r3.plan_offert) == (bruno.user_id, "applique", "standard")
    with pytest.raises(defi.DefiErreur, match="déjà attribuée"):
        await defi.attribuer_recompense(db, mois, 1, now=debut_suivant)
    await db.refresh(alice)
    await db.refresh(bruno)
    assert (alice.plan, bruno.plan) == ("expert", "standard")
    palmares = (await client.get(f"{API}/palmares")).json()
    assert [(p["rang"], p["nom"]) for p in palmares if p["mois"] == mois] == [
        (1, "Alice"), (2, "Chloe"), (3, "Bruno")]

    assert await defi.expirer_recompenses(db, now=debut_suivant + timedelta(days=31)) == 2
    await db.refresh(alice)
    await db.refresh(bruno)
    await db.refresh(chloe)
    assert (alice.plan, bruno.plan, chloe.plan) == ("free", "free", "expert")
