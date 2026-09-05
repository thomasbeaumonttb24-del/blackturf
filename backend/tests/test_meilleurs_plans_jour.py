"""Le visuel publie le plan CONSEILLÉ, pas le meilleur plan de la journée.

Un plan est ré-émis à chaque mouvement de cote : ~33 snapshots pré-course par
course en production. `/stats/meilleurs-plans-jour` triait ces ré-émissions sur
`net DESC` et remontait donc le MEILLEUR snapshot du jour — y compris un conseil
périmé qui n'était plus affiché au moment du départ.

Constat du 2026-09-04 sur 04092026R5C4, profil agressif :
    snapshots de 07:14 à 13:43 → Couplé Gagnant gagnant, 10 € → 1 286 €
    snapshots de 14:05 à 15:08 → plan perdant,           10 € →     0 €
L'endpoint renvoyait 1 286 € pendant que la fiche course publique affichait
« Risqué −10 € ». La mosaïque Instagram aurait publié un gain jamais conseillé,
sur une publication qu'on ne peut plus corriger.

Ces tests verrouillent les quatre façons dont un chiffre faux pouvait entrer dans
un visuel public : le conseil périmé, le plan d'un utilisateur, le plan émis après
le départ, et le règlement pas encore définitif.
"""
from datetime import datetime, timedelta, timezone

import pytest

from db.models import BetPlanSettlement, BetPlanSnapshot, Course, Hippodrome, Reunion

JOUR = "2026-09-04"
DEPART = datetime(2026, 9, 4, 15, 30, tzinfo=timezone.utc)


def _plan(mise: float) -> dict:
    return {"montant_joue": mise, "niveaux": [{"niveau": "securite", "paris": [{
        "type": "Couplé Gagnant", "chevaux": [{"numero": 1, "nom": "X"}],
        "mise": mise, "gain_potentiel": mise * 3, "probabilite": 0.3,
        "ev_estime": 0.1, "description": "d"}]}]}


def _course(db, course_id: str, *, hippodrome: str = "HIPPODROME DU LION D ANGERS"):
    db.add(Course(course_id=course_id, reunion_id="5", numero=4, nom="Prix T",
                  date_heure=DEPART, hippodrome_nom=hippodrome, discipline="Plat",
                  distance=2000, nb_partants=10, statut="termine"))


def _emission(db, course_id: str, suffixe: str, *, retour: float, emitted_at,
              profil: str = "agressif", mise: float = 10.0,
              origin: str = "profil_run", pre_course: bool = True,
              statut: str = "settled"):
    """Une émission de plan et son règlement. `retour` = ce que rend le plan."""
    sid = f"bp-{course_id}-{suffixe}"
    db.add(BetPlanSnapshot(
        plan_snapshot_id=sid, course_id=course_id, subject_hash="system",
        profil=profil, montant_demande=mise, plan=_plan(mise),
        plan_hash=f"h-{sid}", cotes_utilisees={"1": 3.0}, algo_config={},
        algo_version="t", nb_paris=1, montant_joue=mise, emitted_at=emitted_at,
        course_start_at=DEPART, is_pre_course=pre_course, origin=origin,
    ))
    db.add(BetPlanSettlement(
        settlement_id=f"st-{sid}", plan_snapshot_id=sid, course_id=course_id,
        bilan={"paris": []}, montant_mise=mise, montant_retour=retour,
        net=retour - mise, roi=(retour - mise) / mise * 100, nb_paris=1,
        nb_gagnes=1 if retour > 0 else 0, statut=statut,
        settled_at=DEPART + timedelta(hours=1),
    ))


async def _corps(client) -> dict:
    r = await client.get(f"/api/v1/stats/meilleurs-plans-jour?jour={JOUR}")
    assert r.status_code == 200, r.text
    return r.json()


async def _plans(client) -> list[dict]:
    return (await _corps(client))["plans"]


@pytest.mark.asyncio
async def test_le_conseil_perime_ne_remonte_pas(db, client):
    """Le cas 04092026R5C4 : gagnant le matin, perdant au départ."""
    _course(db, "04092026R5C4")
    _emission(db, "04092026R5C4", "matin", retour=1286.0,
              emitted_at=DEPART - timedelta(hours=8))
    _emission(db, "04092026R5C4", "depart", retour=0.0,
              emitted_at=DEPART - timedelta(minutes=22))
    await db.commit()

    plans = await _plans(client)
    assert plans == [], (
        "le plan conseillé au départ perdait : rien ne doit être publié. "
        f"Reçu : {plans}"
    )


@pytest.mark.asyncio
async def test_c_est_le_montant_du_dernier_conseil_qui_est_publie(db, client):
    """Un conseil plus modeste au départ ne doit pas être remplacé par un gros
    gain périmé : c'est le montant DU DERNIER conseil qui sort."""
    _course(db, "04092026R5C4")
    _emission(db, "04092026R5C4", "matin", retour=1286.0,
              emitted_at=DEPART - timedelta(hours=8))
    _emission(db, "04092026R5C4", "depart", retour=49.0,
              emitted_at=DEPART - timedelta(minutes=22))
    await db.commit()

    plans = await _plans(client)
    assert len(plans) == 1
    assert plans[0]["retour"] == 49.0
    assert plans[0]["net"] == 39.0
    assert plans[0]["profil"] == "agressif"


@pytest.mark.asyncio
async def test_deux_profils_sur_la_meme_course_ne_font_qu_une_ligne(db, client):
    """Le visuel montre trois COURSES : la même course répétée par profil donnerait
    l'impression d'un doublon. C'est le meilleur profil qui la représente."""
    _course(db, "04092026R5C4")
    for profil, retour in (("agressif", 30.0), ("conservateur", 49.0)):
        _emission(db, "04092026R5C4", f"d-{profil}", retour=retour,
                  profil=profil, emitted_at=DEPART - timedelta(minutes=22))
    await db.commit()

    plans = await _plans(client)
    assert len(plans) == 1
    assert plans[0]["profil"] == "conservateur"
    assert plans[0]["retour"] == 49.0


@pytest.mark.asyncio
async def test_le_plan_d_un_utilisateur_n_est_jamais_publie(db, client):
    """`bet_plan_snapshots` contient AUSSI les plans personnels des abonnés (269
    snapshots pré-course de 1 à 50 € en prod). Publier la mise de quelqu'un serait
    publier sa donnée, et à une mise qui n'est pas celle du plan du site."""
    _course(db, "04092026R5C4")
    _emission(db, "04092026R5C4", "user", retour=800.0, mise=50.0,
              origin="mise_plan", emitted_at=DEPART - timedelta(minutes=30))
    await db.commit()

    assert await _plans(client) == []


@pytest.mark.asyncio
async def test_un_plan_emis_apres_le_depart_n_est_jamais_publie(db, client):
    _course(db, "04092026R5C4")
    _emission(db, "04092026R5C4", "apres", retour=800.0, pre_course=False,
              emitted_at=DEPART + timedelta(minutes=5))
    await db.commit()

    assert await _plans(client) == []


@pytest.mark.asyncio
async def test_un_reglement_pas_definitif_sort_du_visuel(db, client):
    """Rapport Multi publié en différé → règlement 'partial'. On ne publie pas un
    chiffre qui va changer, et surtout on ne retombe pas sur un snapshot plus
    ancien pour combler le trou — ce serait le bug d'origine."""
    _course(db, "04092026R5C4")
    _emission(db, "04092026R5C4", "matin", retour=1286.0,
              emitted_at=DEPART - timedelta(hours=8))
    _emission(db, "04092026R5C4", "depart", retour=49.0, statut="partial",
              emitted_at=DEPART - timedelta(minutes=22))
    await db.commit()

    assert await _plans(client) == []


@pytest.mark.asyncio
async def test_l_hippodrome_vient_de_la_course_pas_de_la_reunion(db, client):
    """`reunions` ne compte que quinze lignes recyclées d'une journée à l'autre :
    son hippodrome est faux pour 36 des 52 courses du 2026-09-04. Le visuel doit
    lire `courses.hippodrome_nom`, jamais la jointure par la réunion.

    La réunion est délibérément renseignée avec un AUTRE hippodrome : c'est le seul
    montage où l'ancienne jointure `reunions → hippodromes` se trahit."""
    db.add(Hippodrome(hippodrome_id="h-nancy", nom="HIPPODROME DE NANCY-BRABOIS",
                      code="NANCY"))
    db.add(Reunion(reunion_id="5", date=DEPART.date(), hippodrome_id="h-nancy",
                   hippodrome_nom="HIPPODROME DE NANCY-BRABOIS", numero=5))
    _course(db, "04092026R5C4", hippodrome="HIPPODROME DE LYON-PARILLY")
    _emission(db, "04092026R5C4", "depart", retour=49.0,
              emitted_at=DEPART - timedelta(minutes=22))
    await db.commit()

    plans = await _plans(client)
    assert len(plans) == 1
    assert plans[0]["hippodrome"] == "Lyon-Parilly"


@pytest.mark.asyncio
async def test_les_totaux_du_jour_portent_sur_les_plans_publies(db, client):
    """Le bilan du soir compte les MÊMES plans que le podium — pas les ré-émissions.

    Deux courses, deux profils chacune, quatre ré-émissions par conseil : la story
    doit voir 4 plans, pas 16, et un total de retour de 49 + 0 + 236 + 0 = 285 €.
    """
    for course_id in ("04092026R5C4", "04092026R5C7"):
        _course(db, course_id)
    attendu = {
        ("04092026R5C4", "conservateur"): 49.0,
        ("04092026R5C4", "agressif"): 0.0,
        ("04092026R5C7", "conservateur"): 0.0,
        ("04092026R5C7", "agressif"): 236.0,
    }
    for (course_id, profil), retour in attendu.items():
        for k in range(4):
            # Les trois premières ré-émissions annoncent un gros gain périmé.
            _emission(db, course_id, f"{profil}-{k}", profil=profil,
                      retour=1286.0 if k < 3 else retour,
                      emitted_at=DEPART - timedelta(hours=6) + timedelta(hours=k))
    await db.commit()

    corps = await _corps(client)
    assert corps["nb_plans"] == 4, "quatre conseils, pas seize ré-émissions"
    assert corps["nb_plans_gagnants"] == 2
    assert corps["total_retour"] == 285.0
    # La mise reste servie par l'API même si le visuel ne l'affiche pas : sans elle,
    # personne ne peut dire si la journée a gagné ou perdu.
    assert corps["total_mise"] == 40.0
    assert corps["total_net"] == 245.0


@pytest.mark.asyncio
async def test_un_jour_sans_plan_reste_publiable(db, client):
    """Aucun plan réglé : totaux à zéro, pas d'erreur. Un visuel qui plante ne se
    publie pas, et c'est le matin qu'on le découvrirait."""
    corps = await _corps(client)
    assert corps["nb_plans"] == 0
    assert corps["total_retour"] == 0
    assert corps["total_mise"] == 0
    assert corps["plans"] == []
