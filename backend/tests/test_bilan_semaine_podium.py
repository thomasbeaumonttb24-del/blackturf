"""Le podium hebdomadaire publié sur la mosaïque Instagram.

La tuile du dimanche affiche les TROIS meilleurs plans de la semaine : le premier en
grand, le 2ᵉ et le 3ᵉ en dessous et en plus petit. Deux règles décident de ce qui y
entre, et aucune des deux n'est rattrapable après publication :

1. UNE COURSE N'Y FIGURE QU'UNE FOIS. Trois profils tournent sur chaque course et
   produisent trois plans distincts. Sans dédoublonnage, un gros gain remplit le
   podium à lui seul — trois lignes avec le même hippodrome et le même numéro de
   course, ce qui se lit comme un bug d'affichage.
2. SEULS LES PLANS GAGNANTS Y ENTRENT. Un « meilleur gain » à 0 € n'est pas un gain.

Le profil, lui, ne sort jamais : le plus gros gain vient presque toujours du profil
risqué, et l'afficher reviendrait à mettre en avant le plan le plus dangereux.
"""
from datetime import datetime, timedelta, timezone

import pytest

from db.models import BetPlanSettlement, BetPlanSnapshot, Course

# Semaine du dimanche 30 août au samedi 5 septembre 2026.
FIN = "2026-09-05"


def _plan(mise: float) -> dict:
    return {"montant_joue": mise, "niveaux": [{"niveau": "securite", "paris": [{
        "type": "Simple Gagnant", "chevaux": [{"numero": 1, "nom": "X"}],
        "mise": mise, "gain_potentiel": mise * 3, "probabilite": 0.3,
        "ev_estime": 0.1, "description": "d"}]}]}


def _course(db, course_id: str, depart: datetime, hippodrome: str):
    db.add(Course(course_id=course_id, reunion_id="1", numero=1, nom="Prix T",
                  date_heure=depart, hippodrome_nom=hippodrome, discipline="Plat",
                  distance=2000, nb_partants=10, statut="termine"))


def _emission(db, course_id: str, profil: str, depart: datetime, *, retour: float,
              mise: float = 10.0, type_pari: str = "Simple Gagnant"):
    sid = f"bp-{course_id}-{profil}"
    db.add(BetPlanSnapshot(
        plan_snapshot_id=sid, course_id=course_id, subject_hash="system",
        profil=profil, montant_demande=mise, plan=_plan(mise),
        plan_hash=f"h-{sid}", cotes_utilisees={"1": 3.0}, algo_config={},
        algo_version="t", nb_paris=1, montant_joue=mise,
        emitted_at=depart - timedelta(minutes=20),
        course_start_at=depart, is_pre_course=True, origin="profil_run",
    ))
    db.add(BetPlanSettlement(
        settlement_id=f"st-{sid}", plan_snapshot_id=sid, course_id=course_id,
        bilan={"paris": [{"type": type_pari, "gain": retour}]} if retour > 0
        else {"paris": []},
        montant_mise=mise, montant_retour=retour, net=retour - mise,
        roi=(retour - mise) / mise * 100, nb_paris=1,
        nb_gagnes=1 if retour > 0 else 0, statut="settled",
        settled_at=depart + timedelta(hours=1),
    ))


async def _bilan(client) -> dict:
    r = await client.get(f"/api/v1/stats/bilan-semaine?fin={FIN}")
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_le_podium_donne_les_trois_meilleurs_dans_l_ordre(db, client):
    depart = datetime(2026, 9, 2, 13, 0, tzinfo=timezone.utc)
    for i, (retour, lieu) in enumerate([
        (50.0, "HIPPODROME DE VINCENNES"),
        (314.0, "HIPPODROME DE DEAUVILLE"),
        (120.0, "HIPPODROME DE CHANTILLY"),
        (0.0, "HIPPODROME DE CAEN"),
    ]):
        cid = f"02092026R1C{i}"
        _course(db, cid, depart, lieu)
        _emission(db, cid, "agressif", depart, retour=retour)
    await db.commit()

    podium = (await _bilan(client))["meilleurs_plans"]
    assert [p["retour"] for p in podium] == [314.0, 120.0, 50.0], (
        f"podium trié par gain décroissant attendu, reçu : {podium}"
    )
    assert podium[0]["hippodrome"] == "Deauville"
    assert all("profil" not in p for p in podium), (
        "le profil ne doit jamais sortir de l'API du visuel"
    )


@pytest.mark.asyncio
async def test_une_course_n_occupe_qu_une_place(db, client):
    """Les trois profils d'une même course ne remplissent pas le podium."""
    depart = datetime(2026, 9, 2, 13, 0, tzinfo=timezone.utc)
    _course(db, "02092026R1C1", depart, "HIPPODROME DE DEAUVILLE")
    for profil, retour in [("agressif", 900.0), ("modere", 400.0), ("prudent", 200.0)]:
        _emission(db, "02092026R1C1", profil, depart, retour=retour)
    _course(db, "02092026R1C2", depart, "HIPPODROME DE VINCENNES")
    _emission(db, "02092026R1C2", "agressif", depart, retour=60.0)
    await db.commit()

    podium = (await _bilan(client))["meilleurs_plans"]
    courses = [p["code"] for p in podium]
    assert courses == ["R1C1", "R1C2"], (
        f"une course par place attendue, reçu : {courses}"
    )
    assert podium[0]["retour"] == 900.0, "le meilleur plan de la course est conservé"


@pytest.mark.asyncio
async def test_un_plan_perdant_n_entre_pas_au_podium(db, client):
    depart = datetime(2026, 9, 2, 13, 0, tzinfo=timezone.utc)
    _course(db, "02092026R1C1", depart, "HIPPODROME DE DEAUVILLE")
    _emission(db, "02092026R1C1", "agressif", depart, retour=0.0)
    await db.commit()

    bilan = await _bilan(client)
    assert bilan["meilleurs_plans"] == []
    assert bilan["meilleur_plan"] is None
    assert bilan["nb_plans"] == 1, "le plan reste compté dans le volume de la semaine"


@pytest.mark.asyncio
async def test_le_premier_du_podium_est_le_meilleur_plan(db, client):
    """Les deux clés doivent rester d'accord : le visuel lit les deux."""
    depart = datetime(2026, 9, 2, 13, 0, tzinfo=timezone.utc)
    for i, retour in enumerate([80.0, 240.0]):
        cid = f"02092026R1C{i}"
        _course(db, cid, depart, "HIPPODROME DE DEAUVILLE")
        _emission(db, cid, "agressif", depart, retour=retour)
    await db.commit()

    bilan = await _bilan(client)
    assert bilan["meilleur_plan"] == bilan["meilleurs_plans"][0]
