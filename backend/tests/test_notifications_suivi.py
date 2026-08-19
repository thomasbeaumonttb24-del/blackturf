"""
Suivi des notifications — deux manques structurels constatés le 2026-08-17.

1. PRÉFÉRENCES DÉCORATIVES. L'écran /notifications écrivait `vb_niveau_min`,
   `resultats_suivis`, `alertes_systeme` dans `users.push_subscription["prefs"]`…
   et AUCUN envoi ne les lisait. Un utilisateur qui montait son seuil à ★★★★
   continuait de recevoir tous les ★★.

2. ONGLET « RÉSULTATS » VIDE PAR CONSTRUCTION. Seuls les value bets créaient des
   alertes : personne n'a jamais su ce qu'était devenu le cheval signalé. Le suivi
   s'arrêtait au signal. `notify_resultats_course` (appelée par le pipeline
   post-course, après le règlement des paris) ferme la boucle.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from db.models import (AlerteLog, BankrollEntry, Cheval, Course, Hippodrome,
                       Participation, Prediction, Resultat, Reunion, User, ValueBet)
from services.alerts import (PREFS_DEFAUT, notify_resultats_course,
                             notify_value_bets, prefs_utilisateur)


# ─── Préférences ───────────────────────────────────────────────

def test_prefs_defauts_quand_rien_de_stocke():
    u = User(user_id="u1", email="a@b.c", push_subscription=None)
    assert prefs_utilisateur(u) == PREFS_DEFAUT


def test_prefs_partielles_completees_par_les_defauts():
    u = User(user_id="u1", email="a@b.c", push_subscription={"prefs": {"vb_niveau_min": 4}})
    p = prefs_utilisateur(u)
    assert p["vb_niveau_min"] == 4
    assert p["resultats_suivis"] is True


def test_prefs_valeur_aberrante_ramenee_dans_les_bornes():
    """Une valeur corrompue en base ne doit pas faire taire toutes les alertes."""
    u = User(user_id="u1", email="a@b.c", push_subscription={"prefs": {"vb_niveau_min": 99}})
    assert prefs_utilisateur(u)["vb_niveau_min"] == 4
    u.push_subscription = {"prefs": {"vb_niveau_min": "n'importe quoi"}}
    assert prefs_utilisateur(u)["vb_niveau_min"] == PREFS_DEFAUT["vb_niveau_min"]


def test_abonnement_push_exclut_les_prefs():
    """`push_subscription` sert de fourre-tout (endpoint + keys + prefs) : on ne passe
    à pywebpush que les champs de la spec Push API."""
    from services.alerts import _abonnement_push
    u = User(user_id="u1", email="a@b.c", push_subscription={
        "endpoint": "https://push.example/x", "keys": {"p256dh": "k", "auth": "a"},
        "prefs": {"vb_niveau_min": 3},
    })
    abo = _abonnement_push(u)
    assert abo is not None and "prefs" not in abo
    assert abo["endpoint"] == "https://push.example/x"


def test_abonnement_push_absent_si_pas_dendpoint():
    """Un utilisateur peut n'avoir QUE des préférences, sans abonnement push."""
    from services.alerts import _abonnement_push
    u = User(user_id="u1", email="a@b.c", push_subscription={"prefs": {"vb_niveau_min": 3}})
    assert _abonnement_push(u) is None


# ─── Filtrage du lot value bets par utilisateur ────────────────

async def _user(db, *, plan="expert", prefs=None, email_verified=True) -> User:
    # Adresse confirmée par défaut : depuis services/email_verification, un envoi
    # n'atteint plus une adresse que personne n'a confirmée.
    u = User(user_id=str(uuid.uuid4()), email=f"{uuid.uuid4().hex[:8]}@t.fr",
             hashed_password="x", plan=plan, is_active=True,
             email_verified=email_verified,
             push_subscription=({"prefs": prefs} if prefs else None))
    db.add(u)
    await db.commit()
    return u


async def _alertes(db, user_id, type_alerte=None):
    q = select(AlerteLog).where(AlerteLog.user_id == user_id, AlerteLog.canal == "in-app")
    if type_alerte:
        q = q.where(AlerteLog.type_alerte == type_alerte)
    return (await db.execute(q)).scalars().all()


async def test_seuil_utilisateur_filtre_le_lot(db, monkeypatch):
    """Deux utilisateurs, seuils différents, MÊME lot : chacun reçoit ses niveaux."""
    monkeypatch.setattr("services.alerts.send_inapp", _ok)
    exigeant = await _user(db, prefs={"vb_niveau_min": 4})
    permissif = await _user(db, prefs={"vb_niveau_min": 2})

    lot = [
        {"course_id": "C1", "participation_id": "p1", "nom_cheval": "DEUX", "niveau": 2},
        {"course_id": "C1", "participation_id": "p2", "nom_cheval": "QUATRE", "niveau": 4},
    ]
    await notify_value_bets(db, [exigeant.user_id, permissif.user_id], lot)

    a_exigeant = await _alertes(db, exigeant.user_id)
    a_permissif = await _alertes(db, permissif.user_id)
    assert len(a_exigeant) == 1 and a_exigeant[0].payload["nb_value_bets"] == 1
    assert a_exigeant[0].payload["value_bets"][0]["nom_cheval"] == "QUATRE"
    assert a_permissif[0].payload["nb_value_bets"] == 2


async def test_aucune_ligne_si_rien_au_niveau_demande(db, monkeypatch):
    """Pas de notification vide en base : mieux vaut rien qu'un « 0 pari détecté »."""
    monkeypatch.setattr("services.alerts.send_inapp", _ok)
    user = await _user(db, prefs={"vb_niveau_min": 4})
    await notify_value_bets(db, [user.user_id],
                            [{"course_id": "C1", "participation_id": "p1",
                              "nom_cheval": "DEUX", "niveau": 2}])
    assert await _alertes(db, user.user_id) == []


async def test_niveau_absent_notifie_quand_meme(db, monkeypatch):
    """Entre taire une alerte et en envoyer une de trop, le silence est la faute la
    plus coûteuse : un niveau manquant ne doit JAMAIS supprimer la notification."""
    monkeypatch.setattr("services.alerts.send_inapp", _ok)
    user = await _user(db, prefs={"vb_niveau_min": 4})
    await notify_value_bets(db, [user.user_id],
                            [{"course_id": "C1", "participation_id": "p1",
                              "nom_cheval": "SANS_NIVEAU"}])
    assert len(await _alertes(db, user.user_id)) == 1


async def _ok(*a, **k):
    return True


# ─── Suivi post-course ─────────────────────────────────────────

async def _seed_course_terminee(db, *, course_id="17082026R1C6", numero_gagnant=7):
    hippo = Hippodrome(hippodrome_id=str(uuid.uuid4()), nom="CLAIREFONTAINE",
                       code=f"H{uuid.uuid4().hex[:6]}")
    db.add(hippo)
    db.add(Reunion(reunion_id=f"R-{course_id}", date=datetime.now(timezone.utc).date(),
                   hippodrome_id=hippo.hippodrome_id, hippodrome_nom=hippo.nom, numero=1))
    db.add(Course(course_id=course_id, reunion_id=f"R-{course_id}", numero=6,
                  nom="PRIX TEST", date_heure=datetime.now(timezone.utc) - timedelta(hours=1),
                  hippodrome_nom=hippo.nom, discipline="Plat", distance=2000,
                  nb_partants=8, statut="termine"))
    db.add(Resultat(course_id=course_id,
                    classement=[{"numero": numero_gagnant, "position": 1},
                                {"numero": 3, "position": 2},
                                {"numero": 1, "position": 3}],
                    rapports={"simple_gagnant": 6.4}))
    await db.commit()
    return course_id


async def _seed_value_bet(db, course_id, *, numero, nom, niveau=3, cote=6.4):
    cheval = Cheval(cheval_id=str(uuid.uuid4()), nom=nom, age=5, sexe="H")
    db.add(cheval)
    part = Participation(participation_id=str(uuid.uuid4()), course_id=course_id,
                         cheval_id=cheval.cheval_id, numero=numero, cote_pmu=cote,
                         non_partant=False)
    db.add(part)
    await db.flush()
    pred = Prediction(prediction_id=str(uuid.uuid4()), participation_id=part.participation_id,
                      course_id=course_id, proba_top1=0.3, proba_top3=0.6,
                      rang_predit=1, confidence_score=70.0)
    db.add(pred)
    db.add(ValueBet(vb_id=str(uuid.uuid4()), prediction_id=pred.prediction_id,
                    course_id=course_id, participation_id=part.participation_id,
                    ev_pmu=0.3, ev_max=0.3, meilleure_source="pmu", niveau=niveau,
                    spi_detected=False, actif=True, notifie=True))
    await db.commit()


async def test_value_bet_gagnant_notifie_avec_le_rapport_reel(db, monkeypatch):
    monkeypatch.setattr("services.alerts.send_inapp", _ok)
    user = await _user(db, prefs={"vb_niveau_min": 2})
    cid = await _seed_course_terminee(db, numero_gagnant=7)
    await _seed_value_bet(db, cid, numero=7, nom="LOUBRALTAR")

    cr = await notify_resultats_course(db, cid)

    assert cr["value_bets"] == 1
    a = (await _alertes(db, user.user_id, "resultat_value_bet"))[0]
    assert a.payload["position"] == 1
    assert a.payload["rapport_simple_gagnant"] == 6.4
    assert a.payload["arrivee"] == "7 - 3 - 1"


async def test_value_bet_non_place_notifie_aussi(db, monkeypatch):
    """Le suivi doit être honnête : un signal perdant se raconte aussi."""
    monkeypatch.setattr("services.alerts.send_inapp", _ok)
    user = await _user(db, prefs={"vb_niveau_min": 2})
    cid = await _seed_course_terminee(db, numero_gagnant=7)
    await _seed_value_bet(db, cid, numero=12, nom="PERDANT")

    await notify_resultats_course(db, cid)

    a = (await _alertes(db, user.user_id, "resultat_value_bet"))[0]
    assert a.payload["position"] is None
    assert a.payload["rapport_simple_gagnant"] is None  # aucun gain inventé


async def test_pari_personnel_prime_sur_le_value_bet(db, monkeypatch):
    """Un seul message par course : le pari RÉEL de l'utilisateur passe devant."""
    monkeypatch.setattr("services.alerts.send_inapp", _ok)
    user = await _user(db, prefs={"vb_niveau_min": 2})
    cid = await _seed_course_terminee(db)
    await _seed_value_bet(db, cid, numero=7, nom="LOUBRALTAR")
    db.add(BankrollEntry(entry_id=str(uuid.uuid4()), user_id=user.user_id, course_id=cid,
                         date=datetime.now(timezone.utc), type_pari="simple_gagnant",
                         chevaux="7", mise=10.0, cote=6.4, resultat="gagne",
                         gain_perte=54.0))
    await db.commit()

    cr = await notify_resultats_course(db, cid)

    assert cr["paris"] == 1
    assert await _alertes(db, user.user_id, "resultat_value_bet") == []
    a = (await _alertes(db, user.user_id, "resultat_pari"))[0]
    assert a.payload["gain_net"] == 54.0
    assert a.payload["nb_gagnes"] == 1


async def test_idempotent_sur_deux_appels(db, monkeypatch):
    """Le pipeline post-course peut rejouer (re-poll des rapports, catchup) : pas de
    doublon de notification."""
    monkeypatch.setattr("services.alerts.send_inapp", _ok)
    user = await _user(db, prefs={"vb_niveau_min": 2})
    cid = await _seed_course_terminee(db)
    await _seed_value_bet(db, cid, numero=7, nom="LOUBRALTAR")

    await notify_resultats_course(db, cid)
    await notify_resultats_course(db, cid)

    assert len(await _alertes(db, user.user_id, "resultat_value_bet")) == 1


async def test_pref_resultats_desactivee_respectee(db, monkeypatch):
    monkeypatch.setattr("services.alerts.send_inapp", _ok)
    user = await _user(db, prefs={"resultats_suivis": False})
    cid = await _seed_course_terminee(db)
    await _seed_value_bet(db, cid, numero=7, nom="LOUBRALTAR")

    cr = await notify_resultats_course(db, cid)

    assert cr["value_bets"] == 0
    assert cr["ignores_prefs"] == 1
    assert await _alertes(db, user.user_id) == []


async def test_seuil_filtre_aussi_le_suivi(db, monkeypatch):
    """On ne raconte la suite que des signaux que l'utilisateur avait demandés."""
    monkeypatch.setattr("services.alerts.send_inapp", _ok)
    user = await _user(db, prefs={"vb_niveau_min": 4})
    cid = await _seed_course_terminee(db)
    await _seed_value_bet(db, cid, numero=7, nom="LOUBRALTAR", niveau=2)

    cr = await notify_resultats_course(db, cid)

    assert cr["value_bets"] == 0
    assert await _alertes(db, user.user_id) == []


async def test_course_sans_arrivee_ne_notifie_rien(db, monkeypatch):
    """Pas d'annonce tant que le PMU n'a pas publié de classement exploitable."""
    monkeypatch.setattr("services.alerts.send_inapp", _ok)
    user = await _user(db)
    hippo = Hippodrome(hippodrome_id=str(uuid.uuid4()), nom="X", code=f"H{uuid.uuid4().hex[:6]}")
    db.add(hippo)
    db.add(Reunion(reunion_id="R-SANS", date=datetime.now(timezone.utc).date(),
                   hippodrome_id=hippo.hippodrome_id, hippodrome_nom="X", numero=1))
    db.add(Course(course_id="SANS1", reunion_id="R-SANS", numero=1, nom="X",
                  date_heure=datetime.now(timezone.utc) - timedelta(hours=1),
                  hippodrome_nom="X", discipline="Plat", distance=2000,
                  nb_partants=8, statut="a_venir"))
    await db.commit()

    cr = await notify_resultats_course(db, "SANS1")

    assert cr == {"paris": 0, "value_bets": 0, "ignores_prefs": 0}
    assert await _alertes(db, user.user_id) == []
