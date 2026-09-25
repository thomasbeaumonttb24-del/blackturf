"""Défi du mois : dépôt, règles anti-triche, règlement, classement, récompenses."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from db.models import (
    AlerteLog, BetPlanSnapshot, Cheval, Course, DefiPari, DefiRecompense, Participation,
    Resultat, Subscription, User,
)
from services import defi

pytestmark = pytest.mark.asyncio

MAINTENANT = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _cache_classement_vide():
    """Le cache du classement vit dans le processus : chaque test part d'une base neuve."""
    defi.invalider_classement()
    yield
    defi.invalider_classement()


async def _user(db, email="joueur@blackturf.fr", **champs) -> User:
    champs.setdefault("pseudo", email.split("@")[0][:20])
    u = User(user_id=str(uuid.uuid4()), email=email, email_verified=True,
             plan=champs.pop("plan", "free"), **champs)
    db.add(u)
    await db.commit()
    return u


async def _course(db, course_id="C1", *, depart=None, statut="a_venir", nb=10,
                  non_partants=(), paris_disponibles=None) -> Course:
    c = Course(course_id=course_id, reunion_id="R1", numero=1, numero_reunion=1,
               date_heure=depart or MAINTENANT + timedelta(hours=2),
               hippodrome_nom="Vincennes", discipline="Attelé", distance=2700,
               nb_partants=nb, statut=statut, paris_disponibles=paris_disponibles)
    db.add(c)
    for n in range(1, nb + 1):
        cid = str(uuid.uuid4())
        db.add(Cheval(cheval_id=cid, nom=f"Cheval {n}", age=5, sexe="H"))
        db.add(Participation(participation_id=str(uuid.uuid4()), course_id=course_id,
                             cheval_id=cid, numero=n, non_partant=n in non_partants))
    await db.commit()
    return c


async def _arrivee(db, course: Course, ordre=(3, 7, 1), rapports=None, detail=None):
    course.statut = "termine"
    db.add(Resultat(course_id=course.course_id,
                    classement=[{"numero": n, "position": i} for i, n in enumerate(ordre, 1)],
                    rapports=rapports if rapports is not None else {"simple_gagnant": 4.2,
                                                                    "couple_gagnant": 12.5},
                    rapports_detail=detail if detail is not None else {"simple_place": [
                        {"combinaison": "3", "rapport": 1.6},
                        {"combinaison": "7", "rapport": 2.3},
                        {"combinaison": "1", "rapport": 1.9},
                    ]}))
    await db.commit()


# ─── Dépôt ──────────────────────────────────────────────────────────────────

async def test_pari_perso_engage_et_debite(db):
    u = await _user(db)
    await _course(db)
    p = await defi.engager_pari(db, u, "C1", "Simple Gagnant", [3], 50)
    assert (p.statut, p.origine, p.mois) == ("en_attente", "perso", defi.mois_courant())
    assert await defi.solde(db, u.user_id, p.mois) == defi.CAPITAL_MENSUEL - 50


async def test_origine_plan_seulement_si_le_joueur_a_vu_ce_plan(db):
    from api.config import get_settings
    from services.bet_plan_snapshots import SYSTEM_SUBJECT, subject_hash

    u = await _user(db)
    autre = await _user(db, email="autre@blackturf.fr")
    await _course(db)
    plan = {"niveaux": [{"niveau": "securite", "paris": [
        {"type": "Couplé Gagnant", "chevaux": [{"numero": 7}, {"numero": 3}], "mise": 5}]}]}

    def snap(sujet):
        return BetPlanSnapshot(course_id="C1", subject_hash=sujet, profil="equilibre",
                               montant_demande=10, plan=plan, plan_hash=str(uuid.uuid4()),
                               cotes_utilisees={}, algo_config={}, algo_version="t",
                               nb_paris=1, montant_joue=5, emitted_at=MAINTENANT,
                               is_pre_course=True)
    db.add_all([snap(subject_hash(u.user_id, get_settings().secret_key)), snap(SYSTEM_SUBJECT)])
    await db.commit()

    vu = await defi.engager_pari(db, u, "C1", "Couplé Gagnant", [3, 7], 10)
    assert vu.origine == "plan"
    # Un compte qui n'a pas consulté le plan ne doit pas pouvoir le deviner par l'étiquette.
    pas_vu = await defi.engager_pari(db, autre, "C1", "Couplé Gagnant", [3, 7], 10)
    assert pas_vu.origine == "perso"


@pytest.mark.parametrize("type_pari, chevaux, points, message", [
    ("Trio", [1, 2, 3], 10, "Type de pari"),
    ("Simple Gagnant", [1, 2], 10, "choisissez 1"),
    ("Couplé Gagnant", [2, 2], 10, "choisissez 2"),
    ("Simple Gagnant", [1], 5, "Mise entre"),
    ("Simple Gagnant", [1], 101, "Mise entre"),
    ("Simple Gagnant", [42], 10, "non-partant"),
    ("Simple Gagnant", [4], 10, "non-partant"),
])
async def test_paris_invalides_refuses(db, type_pari, chevaux, points, message):
    u = await _user(db)
    await _course(db, non_partants=(4,))
    with pytest.raises(defi.DefiErreur, match=message):
        await defi.engager_pari(db, u, "C1", type_pari, chevaux, points)


async def test_pseudo_obligatoire_pour_jouer(db):
    u = await _user(db, pseudo=None)
    await _course(db)
    with pytest.raises(defi.DefiErreur, match="pseudo"):
        await defi.engager_pari(db, u, "C1", "Simple Gagnant", [3], 10)


async def test_depot_ferme_avant_le_depart(db):
    u = await _user(db)
    await _course(db, depart=MAINTENANT + timedelta(minutes=1))
    with pytest.raises(defi.DefiErreur, match="fermés"):
        await defi.engager_pari(db, u, "C1", "Simple Gagnant", [3], 10)


async def test_depot_ferme_si_arrivee_connue_meme_avec_horaire_en_retard(db):
    u = await _user(db)
    c = await _course(db)
    db.add(Resultat(course_id=c.course_id, classement=[{"numero": 3, "position": 1}]))
    await db.commit()
    with pytest.raises(defi.DefiErreur, match="fermés"):
        await defi.engager_pari(db, u, "C1", "Simple Gagnant", [3], 10)


async def test_pari_non_propose_sur_la_course(db):
    u = await _user(db)
    await _course(db, paris_disponibles=["E_SIMPLE_GAGNANT", "E_SIMPLE_PLACE"])
    with pytest.raises(defi.DefiErreur, match="pas proposé"):
        await defi.engager_pari(db, u, "C1", "Couplé Placé", [1, 2], 10)


async def test_maximum_de_paris_par_course(db):
    u = await _user(db)
    await _course(db)
    for n in range(1, defi.MAX_PARIS_PAR_COURSE + 1):
        await defi.engager_pari(db, u, "C1", "Simple Gagnant", [n], 10)
    with pytest.raises(defi.DefiErreur, match="Maximum"):
        await defi.engager_pari(db, u, "C1", "Simple Gagnant", [9], 10)


async def test_solde_insuffisant(db):
    u = await _user(db)
    for i in range(4):
        await _course(db, course_id=f"C{i}")
        for n in range(1, 4):
            if await defi.solde(db, u.user_id, defi.mois_courant()) >= 100:
                await defi.engager_pari(db, u, f"C{i}", "Simple Gagnant", [n], 100)
    assert await defi.solde(db, u.user_id, defi.mois_courant()) == 0
    await _course(db, course_id="C9")
    with pytest.raises(defi.DefiErreur, match="insuffisant"):
        await defi.engager_pari(db, u, "C9", "Simple Gagnant", [1], 10)


# ─── Règlement ──────────────────────────────────────────────────────────────

async def test_reglement_points_fois_rapport_officiel(db):
    u = await _user(db)
    c = await _course(db)
    g = await defi.engager_pari(db, u, "C1", "Simple Gagnant", [3], 20)
    pl = await defi.engager_pari(db, u, "C1", "Simple Placé", [7], 10)
    perdu = await defi.engager_pari(db, u, "C1", "Couplé Gagnant", [3, 1], 30)
    await _arrivee(db, c)

    assert await defi.regler_course(db, "C1") == 3
    for p in (g, pl, perdu):
        await db.refresh(p)
    assert (g.statut, g.rapport, g.points_retour) == ("gagne", 4.2, 84.0)
    # Placé : le rapport du cheval JOUÉ (2,3), pas celui du vainqueur.
    assert (pl.statut, pl.rapport, pl.points_retour) == ("gagne", 2.3, 23.0)
    assert (perdu.statut, perdu.points_retour) == ("perd", 0.0)
    assert await defi.solde(db, u.user_id, g.mois) == pytest.approx(1000 - 60 + 84 + 23)
    assert await defi.regler_course(db, "C1") == 0  # idempotent


async def test_rapport_pas_encore_publie_reste_en_attente(db):
    u = await _user(db)
    c = await _course(db)
    p = await defi.engager_pari(db, u, "C1", "Simple Gagnant", [3], 20)
    await _arrivee(db, c, rapports={}, detail={})
    await defi.regler_course(db, "C1")
    await db.refresh(p)
    assert p.statut == "en_attente"


async def test_rapport_jamais_publie_rembourse_apres_72h(db):
    u = await _user(db)
    c = await _course(db)
    p = await defi.engager_pari(db, u, "C1", "Simple Placé", [3], 20)
    await _arrivee(db, c, rapports={}, detail={})
    c.date_heure = MAINTENANT - timedelta(hours=73)
    await db.commit()
    await defi.regler_course(db, "C1")
    await db.refresh(p)
    assert (p.statut, p.points_retour) == ("rembourse", 20.0)


async def test_non_partant_apres_depot_rembourse(db):
    u = await _user(db)
    c = await _course(db)
    p = await defi.engager_pari(db, u, "C1", "Simple Gagnant", [5], 40)
    (await db.execute(select(Participation).where(
        Participation.course_id == "C1", Participation.numero == 5))).scalar_one().non_partant = True
    await _arrivee(db, c)
    await defi.regler_course(db, "C1")
    await db.refresh(p)
    assert (p.statut, p.points_retour) == ("rembourse", 40.0)
    assert await defi.solde(db, u.user_id, p.mois) == 1000


async def test_course_annulee_rembourse_via_rattrapage(db):
    u = await _user(db)
    c = await _course(db)
    p = await defi.engager_pari(db, u, "C1", "Simple Gagnant", [5], 40)
    c.statut = "annule"
    await db.commit()
    assert await defi.regler_en_attente(db) == 1
    await db.refresh(p)
    assert p.statut == "rembourse"


# ─── Classement ─────────────────────────────────────────────────────────────

async def _paris_regles(db, user, n, gagnant=False, prefixe="K"):
    mois = defi.mois_courant()
    for i in range(n):
        db.add(DefiPari(user_id=user.user_id, mois=mois, course_id=f"{prefixe}{i}",
                        type_pari="Simple Gagnant", chevaux=[1], points=10, origine="perso",
                        engage_at=MAINTENANT, statut="gagne" if gagnant else "perd",
                        rapport=3.0 if gagnant else None,
                        points_retour=30.0 if gagnant else 0.0))
    await db.commit()


async def test_classement_minimum_de_paris_admin_et_comptes_exclus(db):
    fort = await _user(db, email="fort@x.fr", pseudo="Fort")
    faible = await _user(db, email="faible@x.fr")
    debutant = await _user(db, email="debutant@x.fr")
    admin = await _user(db, email="admin@x.fr", is_admin=True)
    banni = await _user(db, email="banni@x.fr", is_active=False)
    await _paris_regles(db, fort, 10, gagnant=True)
    await _paris_regles(db, faible, 10)
    await _paris_regles(db, debutant, 3, gagnant=True)
    await _paris_regles(db, admin, 20, gagnant=True)
    await _paris_regles(db, banni, 20, gagnant=True)

    lignes = await defi.classement(db, defi.mois_courant())
    par_id = {l["user_id"]: l for l in lignes}
    assert banni.user_id not in par_id
    assert (par_id[fort.user_id]["rang"], par_id[fort.user_id]["nom"]) == (1, "Fort")
    assert par_id[fort.user_id]["solde"] == 1200
    assert par_id[faible.user_id]["rang"] == 2
    assert par_id[debutant.user_id]["rang"] is None
    assert par_id[admin.user_id]["rang"] is None and par_id[admin.user_id]["hors_concours"]
    assert "@" not in par_id[faible.user_id]["nom"]


async def test_tendance_ne_revele_le_cheval_qu_apres_fermeture(db):
    u = await _user(db)
    await _course(db)
    await defi.engager_pari(db, u, "C1", "Simple Gagnant", [3], 10)
    ouverte = await defi.tendance_course(db, "C1", True)
    fermee = await defi.tendance_course(db, "C1", False)
    assert ouverte == {"nb_joueurs": 1, "nb_paris": 1, "cheval_plus_joue": None}
    assert fermee["cheval_plus_joue"] == 3


# ─── Récompenses ────────────────────────────────────────────────────────────

MOIS_PASSE = "2026-08"
FIN_AOUT = datetime(2026, 9, 2, 12, tzinfo=timezone.utc)


async def _gagnant_aout(db, **champs):
    u = await _user(db, email=f"{uuid.uuid4().hex[:6]}@x.fr", **champs)
    for i in range(10):
        db.add(DefiPari(user_id=u.user_id, mois=MOIS_PASSE, course_id=f"A{i}",
                        type_pari="Simple Gagnant", chevaux=[1], points=10, origine="plan",
                        engage_at=FIN_AOUT - timedelta(days=10), statut="gagne",
                        rapport=3.0, points_retour=30.0))
    await db.commit()
    return u


async def test_recompense_refusee_tant_que_le_mois_court(db):
    await _gagnant_aout(db)
    with pytest.raises(defi.DefiErreur, match="pas terminé"):
        await defi.attribuer_recompense(db, MOIS_PASSE, 1,
                                        now=datetime(2026, 8, 30, tzinfo=timezone.utc))


async def test_recompense_appliquee_notifiee_puis_expiree(db):
    u = await _gagnant_aout(db)
    r = await defi.attribuer_recompense(db, MOIS_PASSE, 1, now=FIN_AOUT)
    await db.refresh(u)
    assert (r.statut, r.plan_offert, u.plan) == ("applique", "expert", "expert")
    assert (await db.execute(select(AlerteLog).where(
        AlerteLog.user_id == u.user_id))).scalar_one().type_alerte == "defi_recompense"
    with pytest.raises(defi.DefiErreur, match="déjà attribuée"):
        await defi.attribuer_recompense(db, MOIS_PASSE, 1, now=FIN_AOUT)

    assert await defi.expirer_recompenses(db, now=FIN_AOUT + timedelta(days=29)) == 0
    assert await defi.expirer_recompenses(db, now=FIN_AOUT + timedelta(days=31)) == 1
    await db.refresh(u)
    await db.refresh(r)
    assert (u.plan, r.statut) == ("free", "termine")


async def test_recompense_ne_retrograde_jamais_un_abonne(db):
    u = await _gagnant_aout(db)
    r = await defi.attribuer_recompense(db, MOIS_PASSE, 1, now=FIN_AOUT)
    # Il souscrit pendant son mois offert.
    db.add(Subscription(user_id=u.user_id, stripe_subscription_id="sub_1", plan="expert",
                        periodicite="monthly", statut="active", periode_debut=FIN_AOUT,
                        periode_fin=FIN_AOUT + timedelta(days=30)))
    await db.commit()
    await defi.expirer_recompenses(db, now=FIN_AOUT + timedelta(days=31))
    await db.refresh(u)
    await db.refresh(r)
    assert (u.plan, r.statut) == ("expert", "conserve")


async def test_recompense_manuelle_pour_un_abonne_payant(db):
    u = await _gagnant_aout(db, plan="expert")
    db.add(Subscription(user_id=u.user_id, stripe_subscription_id="sub_2", plan="expert",
                        periodicite="monthly", statut="active", periode_debut=FIN_AOUT,
                        periode_fin=FIN_AOUT + timedelta(days=30)))
    await db.commit()
    r = await defi.attribuer_recompense(db, MOIS_PASSE, 1, now=FIN_AOUT)
    assert r.statut == "manuel"


async def test_recompense_bloquee_si_paris_en_attente(db):
    u = await _gagnant_aout(db)
    db.add(DefiPari(user_id=u.user_id, mois=MOIS_PASSE, course_id="PENDING",
                    type_pari="Simple Gagnant", chevaux=[1], points=10, origine="perso",
                    engage_at=FIN_AOUT, statut="en_attente"))
    await db.commit()
    with pytest.raises(defi.DefiErreur, match="en attente"):
        await defi.attribuer_recompense(db, MOIS_PASSE, 1, now=FIN_AOUT)


# ─── API ────────────────────────────────────────────────────────────────────

async def test_api_compte_gratuit_peut_jouer_sans_plan_de_mise(client, db, auth_headers):
    await _course(db)
    resp = await client.post("/api/v1/defi/paris", headers=auth_headers, json={
        "course_id": "C1", "type_pari": "Simple Gagnant", "chevaux": [3], "points": 30})
    assert resp.status_code == 201, resp.text
    assert resp.json()["origine"] == "perso"

    moi = (await client.get("/api/v1/defi/moi", headers=auth_headers)).json()
    assert moi["solde"] == 970 and moi["nb_paris"] == 1 and moi["rang"] is None

    course = (await client.get("/api/v1/defi/course/C1", headers=auth_headers)).json()
    assert course["ouvert"] and course["solde"] == 970 and len(course["mes_paris"]) == 1

    refus = await client.post("/api/v1/defi/paris", headers=auth_headers, json={
        "course_id": "C1", "type_pari": "Simple Gagnant", "chevaux": [3], "points": 500})
    assert refus.status_code == 400 and "Mise entre" in refus.json()["detail"]


async def test_api_classement_public_sans_email(client, db, auth_headers):
    await _course(db)
    await client.post("/api/v1/defi/paris", headers=auth_headers, json={
        "course_id": "C1", "type_pari": "Simple Gagnant", "chevaux": [3], "points": 30})
    client.cookies.clear()  # la connexion a posé un cookie de session : vraiment anonyme
    anonyme = await client.get("/api/v1/defi/classement")
    assert anonyme.status_code == 200
    ligne = anonyme.json()["lignes"][0]
    assert "user_id" not in ligne and "@" not in ligne["nom"] and ligne["moi"] is False
    connecte = await client.get("/api/v1/defi/classement", headers=auth_headers)
    assert connecte.json()["lignes"][0]["moi"] is True
    assert (await client.get("/api/v1/defi/classement?mois=2026-13")).status_code == 400


async def test_api_admin_reserve_aux_admins(client, db, auth_headers, admin_headers):
    assert (await client.get("/admin/api/defi/cloture", headers=auth_headers)).status_code == 403
    resp = await client.get("/admin/api/defi/cloture", headers=admin_headers)
    assert resp.status_code == 200 and resp.json()["lignes"] == []
    refus = await client.post("/admin/api/defi/recompenses", headers=admin_headers,
                              json={"mois": defi.mois_courant(), "rang": 1})
    assert refus.status_code == 400


async def test_suppression_compte_efface_ses_paris_du_defi(client, db, admin_headers):
    u = await _user(db, email="parti@x.fr")
    await _paris_regles(db, u, 2)
    resp = await client.delete(f"/admin/api/users/{u.user_id}", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert (await db.execute(select(DefiPari))).scalars().all() == []
    assert (await db.execute(select(DefiRecompense))).scalars().all() == []


async def test_api_classement_top_et_ma_ligne(client, db, auth_headers):
    moi = (await db.execute(select(User).where(User.email == "test@blackturf.fr"))).scalar_one()
    for i in range(4):
        u = await _user(db, email=f"j{i}@x.fr", pseudo=f"J{i}")
        await _paris_regles(db, u, 10, gagnant=i % 2 == 0, prefixe=f"T{i}")
    await _paris_regles(db, moi, 3, prefixe="M")

    resp = (await client.get("/api/v1/defi/classement?top=2", headers=auth_headers)).json()
    assert [l["rang"] for l in resp["lignes"]] == [1, 2]
    assert resp["nb_classes"] == 4 and resp["nb_joueurs"] == 5
    assert resp["ma_ligne"]["moi"] is True and resp["ma_ligne"]["rang"] is None
    assert resp["ma_ligne"]["nb_paris"] == 3


async def test_classement_invalide_des_qu_un_pari_est_engage(db):
    u = await _user(db)
    await _course(db)
    assert await defi.classement_en_cache(db, defi.mois_courant()) == []
    await defi.engager_pari(db, u, "C1", "Simple Gagnant", [3], 10)
    assert len(await defi.classement_en_cache(db, defi.mois_courant())) == 1
