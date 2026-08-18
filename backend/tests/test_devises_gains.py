"""
Régression : les gains de carrière étrangers étaient affichés en « € ».

`performances_carriere.gains_carriere_total` est écrasé à chaque scrape avec la
valeur PMU de la réunion en cours, exprimée dans la DEVISE LOCALE de cette réunion.
Le front collait un « € » derrière, d'où des montants absurdes en prod le 2026-08-17 :
4 293 chevaux affichés au-dessus de 5 M€, maximum 99 899 800 « € », dont 99,5 % de
chevaux dont la dernière course était en Argentine, au Chili ou à Hong Kong.

L'API doit donc livrer la devise réelle à côté du montant, et None quand elle est
indéterminée (l'UI masque alors le montant — « aucun chiffre inventé »).
La division par 100 (centimes → unité) est correcte et ne doit PAS bouger.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Cheval,
    Course,
    Hippodrome,
    HistoriqueCourse,
    Participation,
    PerformanceCarriere,
    Reunion,
)
from services.devises import devise_pour_pays, devises_gains_carriere

pytestmark = pytest.mark.asyncio

DATE_TODAY = datetime.now(timezone.utc).replace(hour=14, minute=0, second=0, microsecond=0)


async def _course(db: AsyncSession, *, course_id: str, hippodrome: str,
                  pays: str | None, quand: datetime, reunion_id: str,
                  creer_hippodrome: bool = True) -> None:
    """Crée hippodrome + réunion + course.

    `creer_hippodrome=False` reproduit le cas prod des hippodromes dont le nom porté
    par la course ne matche aucune ligne de la table `hippodromes` (338 chevaux).
    """
    hippodrome_id = str(uuid.uuid4())
    if creer_hippodrome:
        db.add(Hippodrome(
            hippodrome_id=hippodrome_id, nom=hippodrome,
            code=hippodrome[:20].upper().replace(" ", "_"), pays=pays,
        ))
    db.add(Reunion(
        reunion_id=reunion_id, date=quand.date(), hippodrome_id=hippodrome_id,
        hippodrome_nom=hippodrome, numero=1,
    ))
    db.add(Course(
        course_id=course_id, reunion_id=reunion_id, numero=1, nom=f"Prix {hippodrome}",
        date_heure=quand, hippodrome_nom=hippodrome, discipline="Plat",
        distance=1600, nb_partants=8, statut="a_venir",
    ))


async def _cheval_avec_gains(db: AsyncSession, nom: str, gains_centimes: int) -> str:
    cheval_id = str(uuid.uuid4())
    db.add(Cheval(cheval_id=cheval_id, nom=nom, age=4, sexe="H"))
    db.add(PerformanceCarriere(
        cheval_id=cheval_id, gains_carriere_total=gains_centimes,
        nb_courses_total=20, nb_victoires_total=5, nb_places_total=8,
    ))
    return cheval_id


def _partant(course_id: str, cheval_id: str, numero: int = 1) -> Participation:
    return Participation(
        participation_id=str(uuid.uuid4()), course_id=course_id, cheval_id=cheval_id,
        numero=numero, cote_pmu=3.5, non_partant=False,
    )


# ─────────────────────────────────────────────
# Table de correspondance pays → devise
# ─────────────────────────────────────────────
async def test_devise_pour_pays_couvre_les_pays_a_gains_aberrants():
    """Les 6 pays responsables des 4 274 montants aberrants en prod."""
    assert devise_pour_pays("ARG") == "ARS"
    assert devise_pour_pays("CHL") == "CLP"
    assert devise_pour_pays("HKG") == "HKD"
    assert devise_pour_pays("TUR") == "TRY"
    assert devise_pour_pays("ARE") == "AED"
    assert devise_pour_pays("URY") == "UYU"


async def test_devise_pour_pays_zone_euro_et_alias_fr():
    """`historique_courses.pays` mélange les codes 'FR' et 'FRA' (126 937 vs 115 852
    lignes en prod) : les deux doivent résoudre vers l'euro."""
    assert devise_pour_pays("FRA") == "EUR"
    assert devise_pour_pays("FR") == "EUR"
    assert devise_pour_pays("BEL") == "EUR"
    assert devise_pour_pays("fra") == "EUR"       # casse indifférente


async def test_devise_pour_pays_inconnu_renvoie_none():
    """Aucune devise devinée : un pays non cartographié fait disparaître le montant."""
    assert devise_pour_pays(None) is None
    assert devise_pour_pays("") is None
    assert devise_pour_pays("XXX") is None
    # "UNK" est le sentinelle écrit par upsert_hippodrome() quand le PMU ne donne
    # pas de pays : il ne doit surtout pas être assimilé à la France.
    assert devise_pour_pays("UNK") is None


# ─────────────────────────────────────────────
# Résolution de la devise par cheval
# ─────────────────────────────────────────────
async def test_devise_suit_le_pays_de_la_derniere_participation(db: AsyncSession):
    """La valeur en base a été écrite par le dernier scrape : c'est le pays de la
    DERNIÈRE course qui donne la devise, pas celui de la première."""
    await _course(db, course_id="R1C1", hippodrome="HIPPODROME DE CHANTILLY",
                  pays="FRA", quand=DATE_TODAY - timedelta(days=60), reunion_id="R1")
    await _course(db, course_id="R2C1", hippodrome="HIPPODROME DE SAN ISIDRO ARG",
                  pays="ARG", quand=DATE_TODAY, reunion_id="R2")
    cheval_id = await _cheval_avec_gains(db, "Filippiada Test", 9_989_980_000)
    db.add(_partant("R1C1", cheval_id))
    db.add(_partant("R2C1", cheval_id))
    await db.commit()

    devises = await devises_gains_carriere(db, [cheval_id])
    assert devises[cheval_id] == "ARS"


async def test_devise_repli_sur_historique_si_hippodrome_non_cartographie(db: AsyncSession):
    """338 chevaux en prod courent sur un hippodrome absent de la table `hippodromes`.
    Le pays de la dernière ligne d'historique sert alors de repli."""
    await _course(db, course_id="R1C1", hippodrome="HIPPODROME INCONNU",
                  pays=None, quand=DATE_TODAY, reunion_id="R1", creer_hippodrome=False)
    cheval_id = await _cheval_avec_gains(db, "Sans Hippodrome", 500_000_00)
    db.add(_partant("R1C1", cheval_id))
    db.add(HistoriqueCourse(
        historique_id=str(uuid.uuid4()), cheval_id=cheval_id, date_course=date.today(),
        hippodrome="HIPPODROME DE SHA TIN HONG KONG", pays="HKG",
        discipline="Plat", distance=1600,
    ))
    await db.commit()

    devises = await devises_gains_carriere(db, [cheval_id])
    assert devises[cheval_id] == "HKD"


async def test_devise_absente_si_aucune_source(db: AsyncSession):
    """Ni participation ni historique exploitables → pas de devise, donc pas
    d'affichage. On ne retombe jamais sur EUR par défaut."""
    cheval_id = await _cheval_avec_gains(db, "Orphelin", 1_000_000_00)
    await db.commit()

    devises = await devises_gains_carriere(db, [cheval_id])
    assert devises.get(cheval_id) is None


async def test_devises_gains_carriere_liste_vide(db: AsyncSession):
    assert await devises_gains_carriere(db, []) == {}


# ─────────────────────────────────────────────
# Contrat API
# ─────────────────────────────────────────────
async def test_partant_expose_la_devise_locale_et_pas_leuro(client: AsyncClient, db: AsyncSession):
    """Le cas prod : cheval argentin à 99 899 800 unités. L'API doit dire « ARS »
    et conserver le montant tel quel (la division par 100 reste correcte)."""
    await _course(db, course_id="R1C1", hippodrome="HIPPODROME DE PALERMO ARG",
                  pays="ARG", quand=DATE_TODAY, reunion_id="R1")
    cheval_id = await _cheval_avec_gains(db, "Peso Fort", 9_989_980_000)
    db.add(_partant("R1C1", cheval_id))
    await db.commit()

    resp = await client.get("/api/v1/courses/R1C1")
    assert resp.status_code == 200, resp.text
    partant = resp.json()["partants"][0]

    assert partant["gains_carriere"] == 99_899_800     # centimes → unité, inchangé
    assert partant["gains_carriere_devise"] == "ARS"


async def test_partant_francais_reste_en_euros(client: AsyncClient, db: AsyncSession):
    """Non-régression : les 86,7 % de chevaux sous le million étaient corrects,
    ils doivent le rester."""
    await _course(db, course_id="R1C1", hippodrome="HIPPODROME DE VINCENNES",
                  pays="FRA", quand=DATE_TODAY, reunion_id="R1")
    cheval_id = await _cheval_avec_gains(db, "Bien De Chez Nous", 4_541_000)
    db.add(_partant("R1C1", cheval_id))
    await db.commit()

    partant = (await client.get("/api/v1/courses/R1C1")).json()["partants"][0]
    assert partant["gains_carriere"] == 45_410
    assert partant["gains_carriere_devise"] == "EUR"


async def test_fiche_cheval_expose_la_devise(client: AsyncClient, db: AsyncSession):
    await _course(db, course_id="R1C1", hippodrome="HIPPODROME DE SANTIAGO CHILI",
                  pays="CHL", quand=DATE_TODAY, reunion_id="R1")
    cheval_id = await _cheval_avec_gains(db, "Andes", 981_990_000)
    db.add(_partant("R1C1", cheval_id))
    await db.commit()

    resp = await client.get(f"/api/v1/chevaux/{cheval_id}")
    assert resp.status_code == 200, resp.text
    perfs = resp.json()["performances"]

    assert perfs["gains_total"] == 9_819_900
    assert perfs["gains_devise"] == "CLP"
