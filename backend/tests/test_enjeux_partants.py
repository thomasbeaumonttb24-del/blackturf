"""
Enjeux PMU par cheval — invariants.

Ce que ces tests protègent, dans l'ordre d'importance :

1. La troncature à 12 chevaux du PMU ne doit JAMAIS être présentée comme une
   course complète : l'argent des non-listés existe, il est agrégé, il est dit.
2. Un afflux se mesure contre la POPULATION de la course, pas contre zéro : si
   toute la masse double, personne n'a reçu d'afflux.
3. Un relevé identique au précédent ne crée pas de ligne — sinon la fenêtre
   d'analyse se remplit de doublons qui simulent une stabilité inexistante.
"""
from datetime import datetime, timedelta, timezone

import pytest

from services.pmu_enjeux import parser_enjeux, CAP_COMBINAISONS
from services.enjeux_analyse import analyser_enjeux
from scraper.orchestrator import _fenetre_enjeux


def _combi(par_type: dict[str, list[tuple[list[int], int]]], maj_ms: int = 1787769750000):
    return {
        "combinaisons": [
            {
                "pariType": t,
                "updateTime": maj_ms,
                "listeCombinaisons": [{"combinaison": c, "totalEnjeu": e} for c, e in lignes],
            }
            for t, lignes in par_type.items()
        ]
    }


def _masse(**kw):
    return [{"typePari": t, "totalEnjeu": v} for t, v in kw.items()]


# ── Parsing ──────────────────────────────────────────────────────────────────

def test_liste_complete_pas_de_reste_invente():
    """8 partants, 8 chevaux listés : l'écart masse/somme est un arrondi PMU,
    pas de l'argent caché — il ne doit pas devenir une ligne « autres »."""
    vue = parser_enjeux(
        _combi({"SIMPLE_GAGNANT": [([n], n * 1000) for n in range(1, 9)]}),
        _masse(SIMPLE_GAGNANT=36415),  # somme listée = 36 000
        nb_partants=8,
    )
    sg = vue["simples"]["SIMPLE_GAGNANT"]
    assert sg["tronque"] is False
    assert sg["autres_centimes"] == 0
    assert sg["nb_autres"] == 0
    assert sg["par_cheval"][5] == 5000


def test_liste_tronquee_la_queue_du_peloton_est_dite():
    """16 partants, 12 listés : les 4 restants existent et pèsent la différence."""
    lignes = [([n], 100_000) for n in range(1, CAP_COMBINAISONS + 1)]
    vue = parser_enjeux(
        _combi({"SIMPLE_GAGNANT": lignes}),
        _masse(SIMPLE_GAGNANT=1_500_000),  # 1 200 000 listés + 300 000 non listés
        nb_partants=16,
    )
    sg = vue["simples"]["SIMPLE_GAGNANT"]
    assert sg["tronque"] is True
    assert sg["autres_centimes"] == 300_000
    assert sg["nb_autres"] == 4


def test_sans_nb_partants_une_liste_pleine_est_presumee_tronquee():
    """Le programme PMU ne porte pas encore le nombre de partants au moment du
    relevé : à 12 chevaux pile, on présume la troncature. Se tromper dans l'autre
    sens ferait disparaître en silence l'argent des chevaux non listés."""
    lignes = [([n], 100_000) for n in range(1, CAP_COMBINAISONS + 1)]
    sg = parser_enjeux(_combi({"SIMPLE_GAGNANT": lignes}),
                       _masse(SIMPLE_GAGNANT=1_500_000))["simples"]["SIMPLE_GAGNANT"]
    assert sg["tronque"] is True
    assert sg["autres_centimes"] == 300_000
    assert sg["nb_autres"] is None, "on sait qu'il en manque, pas combien"


def test_sans_nb_partants_un_reste_d_arrondi_n_est_pas_une_troncature():
    """12 partants pile : l'écart masse/somme est l'arrondi à l'euro des montants
    publiés (ici 0,03 % de la masse), pas un peloton caché."""
    lignes = [([n], 100_000) for n in range(1, CAP_COMBINAISONS + 1)]
    sg = parser_enjeux(_combi({"SIMPLE_GAGNANT": lignes}),
                       _masse(SIMPLE_GAGNANT=1_200_415))["simples"]["SIMPLE_GAGNANT"]
    assert sg["tronque"] is False
    assert sg["autres_centimes"] == 0


def test_masse_absente_retombe_sur_la_somme():
    vue = parser_enjeux(_combi({"SIMPLE_PLACE": [([1], 500), ([2], 700)]}), None, nb_partants=2)
    assert vue["simples"]["SIMPLE_PLACE"]["masse_centimes"] == 1200


def test_combines_separes_des_simples():
    vue = parser_enjeux(
        _combi({
            "SIMPLE_GAGNANT": [([3], 900)],
            "COUPLE_GAGNANT": [([3, 5], 400)],
        }),
        None, nb_partants=6,
    )
    assert set(vue["simples"]) == {"SIMPLE_GAGNANT"}
    assert vue["combines"]["COUPLE_GAGNANT"] == [{"combinaison": [3, 5], "centimes": 400}]


def test_payload_vide_ne_casse_pas():
    assert parser_enjeux(None, None) == {"simples": {}, "combines": {}}


# ── Analyse des mouvements ───────────────────────────────────────────────────

def _snap(t, sg, masse=None):
    return {"t": t, "sg": dict(sg), "sp": {}, "masse_sg": masse or sum(sg.values()),
            "masse_sp": None, "autres_sg": 0, "autres_sp": 0, "nb_autres": 0}


T0 = datetime(2026, 8, 26, 18, 0, tzinfo=timezone.utc)


def test_une_hausse_generale_n_est_pas_un_afflux():
    """Toute la masse double dans les mêmes proportions : aucune part ne bouge,
    donc aucune alerte. C'est le piège n°1 d'un montant brut."""
    avant = _snap(T0, {1: 100_000, 2: 200_000, 3: 300_000})
    apres = _snap(T0 + timedelta(minutes=20), {1: 200_000, 2: 400_000, 3: 600_000})
    vue = analyser_enjeux([avant, apres])
    assert vue["alertes"] == []
    assert all(abs(l["delta_part_pts"]) < 0.01 for l in vue["par_cheval"])


def test_grosse_mise_detectee_et_chiffree():
    avant = _snap(T0, {1: 100_000, 2: 200_000, 3: 300_000})
    # +40 000 € sur le 2, +100 € de bruit sur les autres.
    apres = _snap(T0 + timedelta(minutes=20), {1: 110_000, 2: 4_200_000, 3: 310_000})
    vue = analyser_enjeux([avant, apres])
    alerte = vue["alertes"][0]
    assert alerte["numero"] == 2
    assert alerte["type"] == "grosse_mise"
    assert alerte["delta_eur"] == pytest.approx(40_000.0)
    ligne = next(l for l in vue["par_cheval"] if l["numero"] == 2)
    assert ligne["grosse_mise"] is True
    assert ligne["delta_part_pts"] > 30


def test_un_seul_releve_n_alerte_pas():
    vue = analyser_enjeux([_snap(T0, {1: 100_000, 2: 200_000})])
    assert vue["alertes"] == []
    assert vue["fenetre_min"] is None
    assert all(l["delta_eur"] is None for l in vue["par_cheval"])


def test_cheval_entrant_dans_le_classement_signale_sans_delta_invente():
    """Un cheval absent du top 12 au relevé précédent : on ne peut pas chiffrer
    sa hausse (on ignore d'où il part) — on le dit au lieu de la fabriquer."""
    avant = _snap(T0, {1: 100_000, 2: 200_000})
    apres = _snap(T0 + timedelta(minutes=20), {1: 100_000, 2: 200_000, 9: 90_000})
    ligne = next(l for l in analyser_enjeux([avant, apres])["par_cheval"] if l["numero"] == 9)
    assert ligne["entre_dans_classement"] is True
    assert ligne["delta_eur"] is None
    assert ligne["afflux"] is False


def test_ratio_place_gagnant_compare_des_parts_pas_des_montants():
    """La masse placée est plus petite que la masse gagnante : comparer les
    montants bruts donnerait un ratio < 1 pour tout le monde."""
    snap = {"t": T0, "sg": {1: 500_000, 2: 500_000}, "sp": {1: 300_000, 2: 100_000},
            "masse_sg": 1_000_000, "masse_sp": 400_000,
            "autres_sg": 0, "autres_sp": 0, "nb_autres": 0}
    lignes = {l["numero"]: l for l in analyser_enjeux([snap])["par_cheval"]}
    assert lignes[1]["ratio_place_gagnant"] == pytest.approx(1.5)   # argent prudent
    assert lignes[2]["ratio_place_gagnant"] == pytest.approx(0.5)   # argent qui vise la gagne


def test_troncature_remontee_dans_la_vue():
    snap = _snap(T0, {n: 10_000 for n in range(1, 13)}, masse=200_000)
    snap.update(autres_sg=80_000, nb_autres=4)
    vue = analyser_enjeux([snap])
    assert vue["tronque"] is True
    assert vue["autres"]["gagnant_eur"] == pytest.approx(800.0)
    assert vue["autres"]["nb_chevaux"] == 4


# ── Fenêtre de relevé ────────────────────────────────────────────────────────

def test_fenetre_enjeux():
    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    ms = lambda dt: int(dt.timestamp() * 1000)  # noqa: E731
    assert _fenetre_enjeux(ms(now + timedelta(hours=1)), maintenant=now) is True
    assert _fenetre_enjeux(ms(now + timedelta(hours=6)), maintenant=now) is False
    assert _fenetre_enjeux(ms(now - timedelta(minutes=5)), maintenant=now) is True
    assert _fenetre_enjeux(ms(now - timedelta(hours=2)), maintenant=now) is False
    # Format inattendu : on relève quand même (un trou coûte plus cher).
    assert _fenetre_enjeux("n'importe quoi", maintenant=now) is True


# ── Écriture ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_releve_identique_non_reecrit(db):
    import uuid

    from sqlalchemy import select
    from db.models import Course, Hippodrome, Reunion, EnjeuxCourseHistorique
    from scraper.db_writer import save_enjeux_course

    hippo = Hippodrome(hippodrome_id=str(uuid.uuid4()), nom="TEST", code="TST")
    db.add(hippo)
    db.add(Reunion(reunion_id="R9", date=datetime(2026, 8, 26).date(),
                   hippodrome_id=hippo.hippodrome_id, hippodrome_nom="TEST", numero=9))
    db.add(Course(course_id="26082026R9C1", reunion_id="R9", numero=1,
                  date_heure=datetime(2026, 8, 26, 14, 0, tzinfo=timezone.utc),
                  hippodrome_nom="TEST", discipline="trot", distance=2000,
                  nb_partants=8, statut="a_venir"))
    await db.flush()

    vue = parser_enjeux(
        _combi({"SIMPLE_GAGNANT": [([1], 1000), ([2], 2000)]}),
        _masse(SIMPLE_GAGNANT=3000), nb_partants=8,
    )
    assert await save_enjeux_course(db, "26082026R9C1", vue) is True
    await db.flush()
    assert await save_enjeux_course(db, "26082026R9C1", vue) is False  # rien n'a bougé

    vue2 = parser_enjeux(
        _combi({"SIMPLE_GAGNANT": [([1], 1000), ([2], 9000)]}),
        _masse(SIMPLE_GAGNANT=10000), nb_partants=8,
    )
    assert await save_enjeux_course(db, "26082026R9C1", vue2) is True
    await db.flush()

    lignes = (await db.execute(select(EnjeuxCourseHistorique))).scalars().all()
    assert len(lignes) == 2


@pytest.mark.asyncio
async def test_cycle_scraper_ecrit_le_releve(db, monkeypatch):
    """Câblage complet du cycle : orchestrateur → scraper PMU → base.

    Ce test tient le fil que les tests unitaires laissent pendre : que la vue
    renvoyée par le scraper arrive réellement en base par le chemin de production
    (`run_pool_pmu_cycle`), et que les courses hors fenêtre ne soient pas lues.
    """
    import uuid
    from contextlib import asynccontextmanager

    from sqlalchemy import select
    from db.models import Course, EnjeuxCourseHistorique, Hippodrome, Reunion
    from scraper import orchestrator as orch

    hippo = Hippodrome(hippodrome_id=str(uuid.uuid4()), nom="Cycle Test", code="CYC")
    db.add(hippo)
    db.add(Reunion(reunion_id="RC-1", date=datetime(2026, 8, 26).date(),
                   hippodrome_id=hippo.hippodrome_id, hippodrome_nom="Cycle Test", numero=1))
    for cid in ("26082026R1C1", "26082026R1C2"):
        db.add(Course(course_id=cid, reunion_id="RC-1", numero=int(cid[-1]),
                      date_heure=datetime.now(timezone.utc) + timedelta(hours=1),
                      hippodrome_nom="Cycle Test", discipline="Attelé", distance=2700,
                      nb_partants=8, statut="a_venir"))
    await db.commit()

    lues: list[str] = []

    class FauxPmu:
        async def get_pool_data(self, reunion_id, course_id):
            return None  # la masse globale n'est pas le sujet ici

        async def get_enjeux_par_cheval(self, reunion_id, course_id, nb_partants=None):
            lues.append(course_id)
            return parser_enjeux(
                _combi({"SIMPLE_GAGNANT": [([1], 120_000), ([2], 80_000)],
                        "SIMPLE_PLACE": [([1], 40_000), ([2], 30_000)]}),
                _masse(SIMPLE_GAGNANT=200_000, SIMPLE_PLACE=70_000),
                nb_partants=nb_partants,
            )

        async def close(self):
            return None

    @asynccontextmanager
    async def _session():
        yield db

    monkeypatch.setattr(orch, "PmuScraper", lambda *a, **k: FauxPmu())
    monkeypatch.setattr(orch, "AsyncSessionLocal", _session)

    class CourseDuJour:
        def __init__(self, cid, depart):
            self.course_id, self.reunion_id, self.date_heure = cid, "RC-1", depart
            self.nb_partants = 8

    dans_fenetre = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp() * 1000)
    hors_fenetre = int((datetime.now(timezone.utc) + timedelta(hours=9)).timestamp() * 1000)

    o = orch.BlackTurfOrchestrator()
    o._courses_today = [CourseDuJour("26082026R1C1", dans_fenetre),
                        CourseDuJour("26082026R1C2", hors_fenetre)]
    await o.run_pool_pmu_cycle()

    assert lues == ["26082026R1C1"], "la course à J+9 h ne doit pas être relevée"
    lignes = (await db.execute(select(EnjeuxCourseHistorique))).scalars().all()
    assert len(lignes) == 1
    assert lignes[0].course_id == "26082026R1C1"
    assert lignes[0].enjeux["SIMPLE_GAGNANT"] == {"1": 120_000, "2": 80_000}
    assert lignes[0].masse_place_centimes == 70_000


# ── Endpoint ─────────────────────────────────────────────────────────────────

async def _course_avec_enjeux(db, course_id="26082026R8C3", statut="termine"):
    """Course terminée + 2 relevés : le 4 encaisse 30 000 €, les autres stagnent."""
    import uuid

    from db.models import (Cheval, Course, EnjeuxCourseHistorique, Hippodrome,
                           Participation, Reunion)

    hippo = Hippodrome(hippodrome_id=str(uuid.uuid4()), nom="Enjeux Test", code="ENJ")
    db.add(hippo)
    db.add(Reunion(reunion_id=f"RE-{course_id}", date=datetime(2026, 8, 26).date(),
                   hippodrome_id=hippo.hippodrome_id, hippodrome_nom="Enjeux Test", numero=8))
    db.add(Course(course_id=course_id, reunion_id=f"RE-{course_id}", numero=3,
                  date_heure=datetime(2026, 8, 26, 14, 0, tzinfo=timezone.utc),
                  hippodrome_nom="Enjeux Test", discipline="Attelé", distance=2700,
                  nb_partants=3, statut=statut))
    for numero, nom in ((2, "PRUDENT TEST"), (4, "ARGENT MASSIF"), (7, "DELAISSE TEST")):
        cheval = Cheval(cheval_id=str(uuid.uuid4()), nom=nom)
        db.add(cheval)
        db.add(Participation(participation_id=str(uuid.uuid4()), course_id=course_id,
                             cheval_id=cheval.cheval_id, numero=numero))
    for minutes, enjeux, masse in (
        (0, {"2": 200_000, "4": 300_000, "7": 100_000}, 600_000),
        (20, {"2": 205_000, "4": 3_300_000, "7": 102_000}, 3_607_000),
    ):
        db.add(EnjeuxCourseHistorique(
            id=str(uuid.uuid4()), course_id=course_id,
            scraped_at=datetime(2026, 8, 26, 13, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes),
            masse_gagnant_centimes=masse, masse_place_centimes=masse // 2,
            enjeux={"SIMPLE_GAGNANT": enjeux, "SIMPLE_PLACE": {}},
            autres_gagnant_centimes=0, autres_place_centimes=0, nb_autres=0,
        ))
    await db.commit()
    return course_id


@pytest.mark.asyncio
async def test_endpoint_enjeux_reserve_aux_abonnes(client, db, auth_headers):
    course_id = await _course_avec_enjeux(db)
    resp = await client.get(f"/api/v1/courses/{course_id}/enjeux", headers=auth_headers)
    assert resp.status_code == 403, "un compte gratuit ne doit pas voir les enjeux par cheval"


@pytest.mark.asyncio
async def test_endpoint_enjeux_nomme_le_cheval_et_l_afflux(client, db, admin_headers):
    course_id = await _course_avec_enjeux(db)
    resp = await client.get(f"/api/v1/courses/{course_id}/enjeux", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["disponible"] is True
    tete = data["par_cheval"][0]
    assert tete["numero"] == 4 and tete["nom"] == "ARGENT MASSIF"
    assert tete["enjeu_gagnant_eur"] == pytest.approx(33_000.0)
    assert data["alertes"][0]["numero"] == 4
    assert data["alertes"][0]["type"] == "grosse_mise"


@pytest.mark.asyncio
async def test_endpoint_enjeux_course_sans_releve(client, db, admin_headers):
    """Aucune donnée ≠ erreur : la carte doit pouvoir se taire proprement."""
    import uuid

    from db.models import Course, Hippodrome, Reunion

    hippo = Hippodrome(hippodrome_id=str(uuid.uuid4()), nom="Vide Test", code="VID")
    db.add(hippo)
    db.add(Reunion(reunion_id="RV-1", date=datetime(2026, 8, 26).date(),
                   hippodrome_id=hippo.hippodrome_id, hippodrome_nom="Vide Test", numero=7))
    db.add(Course(course_id="26082026R7C1", reunion_id="RV-1", numero=1,
                  date_heure=datetime(2026, 8, 26, 15, 0, tzinfo=timezone.utc),
                  hippodrome_nom="Vide Test", discipline="Plat", distance=1600,
                  nb_partants=8, statut="termine"))
    await db.commit()

    resp = await client.get("/api/v1/courses/26082026R7C1/enjeux", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json() == {"course_id": "26082026R7C1", "disponible": False,
                           "par_cheval": [], "alertes": []}
