"""Biais de corde : stalles réelles (`participations.numero_corde`) × arrivées
réelles (`resultats.classement`), courses terminées ANTÉRIEURES seulement.

Jusqu'au 2026-09-24 le biais lisait `historique_courses.corde`, qui porte le SENS
DU VIRAGE (« CORDE_GAUCHE ») : tout était jeté, `draw_bias_score` sortait constant.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from db.models import Cheval, Course, Participation, Resultat
from ml.features import (
    DRAW_BIAS_MIN_TOTAL,
    SQL_DRAW_BIAS,
    SQL_DRAW_BIAS_ARRIVEES,
    biais_corde,
    cle_hippodrome,
    rang_stalle_relatif,
    sorties_corde,
    traits_corde,
)

HIPPO = "HIPPODROME DE CHANTILLY"
T0 = datetime(2026, 5, 1, 14, 0)


async def _course_passee(db, cid, quand, gagnants, n=10, hippo=HIPPO, dist=1600,
                         disc="Plat", statut="termine", stalle_de=lambda num: num):
    """Une course de `n` partants, stalle = stalle_de(numéro) ; `gagnants` = les
    numéros arrivés 1er, 2e, 3e (dans l'ordre)."""
    db.add(Course(course_id=cid, reunion_id="R", numero=1, date_heure=quand,
                  hippodrome_nom=hippo, discipline=disc, distance=dist, statut=statut))
    for num in range(1, n + 1):
        db.add(Participation(participation_id=f"{cid}-{num}", course_id=cid,
                             cheval_id="CH", numero=num, numero_corde=stalle_de(num),
                             non_partant=False))
    classement = [{"numero": g, "position": i + 1} for i, g in enumerate(gagnants)]
    classement += [{"numero": num, "position": 4 + k} for k, num in
                   enumerate(x for x in range(1, n + 1) if x not in gagnants)]
    db.add(Resultat(course_id=cid, classement=classement))


async def _lire(db, quand, hippo=HIPPO, dist=1600, disc="Plat"):
    p = {"hippo": cle_hippodrome(hippo), "disc": disc, "dist": dist, "dref": quand}
    st = (await db.execute(text(SQL_DRAW_BIAS), p)).fetchall()
    ar = (await db.execute(text(SQL_DRAW_BIAS_ARRIVEES), p)).fetchall()
    return st, ar


# ── Fonctions pures ───────────────────────────────────────────────────────────

def test_rang_relatif_sur_le_champ_reel():
    assert rang_stalle_relatif(1, [1, 2, 3, 4, 5]) == 0.0
    assert rang_stalle_relatif(5, [1, 2, 3, 4, 5]) == 1.0
    # Stalle 16 dans un champ de 14 partants (2 non-partants) : la plus extérieure.
    stalles = [1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 16]
    assert rang_stalle_relatif(16, stalles) == 1.0
    assert rang_stalle_relatif(None, stalles) is None
    assert rang_stalle_relatif(8, stalles) is None      # stalle hors du champ


def test_plusieurs_stalles_resultats_distincts():
    """Stalles basses qui se placent, hautes qui ne se placent pas → zone int.
    positive, ext. négative, pente négative (l'extérieur perd)."""
    sorties = []
    for c in range(12):                          # 12 courses de 12 partants
        for s in range(1, 13):
            top3 = 1 if s <= 3 else 0             # les 3 stalles intérieures se placent
            sorties.append((s, 12, (s - 1) / 11, top3))
    b = biais_corde(sorties)
    assert b["n"] == 144 >= DRAW_BIAS_MIN_TOTAL
    assert b["zones"]["interieure"] > 0.3 - 1e-9          # plafonné à +0,3
    assert b["zones"]["exterieure"] == pytest.approx(-0.25)   # 0 − 3/12
    assert b["zones"]["milieu"] == pytest.approx(-0.25)
    assert b["pente"] < 0

    # Résultats inversés → signes inversés : la mesure suit les arrivées.
    inv = [(s, n, r, (1 if s >= 10 else 0)) for s, n, r, _ in sorties]
    b2 = biais_corde(inv)
    assert b2["zones"]["exterieure"] > 0 and b2["zones"]["interieure"] < 0
    assert b2["pente"] > 0


def test_attendu_du_champ_et_non_taux_global():
    """Stalles 9+ n'existent que dans les grands champs : sans correction, l'ext.
    paraît pénalisée même quand chaque stalle a exactement sa chance."""
    sorties = []
    for _ in range(20):                      # petits champs de 6 : chacun sa chance
        for s in range(1, 7):
            sorties.append((s, 6, (s - 1) / 5, 1 if s in (1, 2, 3) else 0))
        for s in range(1, 7):
            sorties.append((s, 6, (s - 1) / 5, 1 if s in (4, 5, 6) else 0))
    for _ in range(20):                      # grands champs de 15 : idem
        for k in range(5):
            for s in range(1, 16):
                sorties.append((s, 15, (s - 1) / 14, 1 if s in (1 + 3 * k, 2 + 3 * k, 3 + 3 * k) else 0))
    b = biais_corde(sorties)
    for z in ("interieure", "milieu", "exterieure"):
        assert abs(b["zones"][z]) < 0.02, (z, b["zones"][z])


def test_seuils_anti_bruit():
    peu = [(s, 10, (s - 1) / 9, 1 if s <= 3 else 0) for s in range(1, 11)] * 9   # 90 < 100
    assert biais_corde(peu)["zones"] == {}
    # 100 sorties mais la zone ext. (9+) n'en a que 20 < 30 : absente.
    assez = [(s, 10, (s - 1) / 9, 1 if s <= 3 else 0) for s in range(1, 11)] * 10
    z = biais_corde(assez)["zones"]
    assert "exterieure" not in z and "interieure" in z and "milieu" in z


def test_traits_neutres_sans_stalle():
    assert traits_corde(None, [1, 2, 3], {"interieure": 0.1}, -0.2) == {
        "draw_bias_score": 0.0, "draw_bias_relatif": 0.0}
    t = traits_corde(1, list(range(1, 11)), {"interieure": 0.08}, -0.2)
    assert t["draw_bias_score"] == pytest.approx(0.08)
    assert t["draw_bias_relatif"] == pytest.approx(-0.2 * (0 - 0.5))
    # Pas de biais mesuré (échantillon insuffisant) → la pente n'est pas lue non plus.
    assert traits_corde(1, list(range(1, 11)), {}, -0.2)["draw_bias_relatif"] == 0.0


def test_sorties_ignorent_les_courses_sans_arrivee():
    st = [("A", 1, 3), ("A", 2, 1), ("B", 1, 1), ("B", 2, 2)]
    ar = [("A", '[{"numero": 2, "position": 1}, {"numero": 1, "position": 2}]')]
    out = sorties_corde(st, ar)
    assert sorted(out) == [(1, 2, 0.0, 1), (3, 2, 1.0, 1)]


# ── SQL (SQLite) : même hippodrome, distance ±400 m, antérieures seulement ────

@pytest.mark.asyncio
async def test_zero_fuite_temporelle(db):
    """La course calculée et toute course postérieure sont INVISIBLES, même
    terminées : un recalcul d'historique ne doit rien savoir du futur."""
    db.add(Cheval(cheval_id="CH", nom="PEGASE"))
    await _course_passee(db, "AVANT", T0 - timedelta(days=3), [1, 2, 3])
    await _course_passee(db, "JOUR", T0, [8, 9, 10])
    await _course_passee(db, "APRES", T0 + timedelta(days=2), [8, 9, 10])
    await db.commit()

    st, ar = await _lire(db, T0)
    assert {r[0] for r in st} == {"AVANT"}
    assert {r[0] for r in ar} == {"AVANT"}


@pytest.mark.asyncio
async def test_filtres_hippodrome_distance_discipline_statut(db):
    db.add(Cheval(cheval_id="CH", nom="PEGASE"))
    j = T0 - timedelta(days=1)
    await _course_passee(db, "OK_1600", j, [1, 2, 3])
    await _course_passee(db, "OK_1950", j, [1, 2, 3], dist=1950)
    await _course_passee(db, "LOIN", j, [1, 2, 3], dist=2100)                 # > 400 m
    await _course_passee(db, "AUTRE_HIPPO", j, [1, 2, 3], hippo="HIPPODROME DE CHANTILLY SUD")
    await _course_passee(db, "OBSTACLE", j, [1, 2, 3], disc="OBSTACLE")
    await _course_passee(db, "EN_COURS", j, [1, 2, 3], statut="a_venir")
    await _course_passee(db, "SANS_STALLE", j, [1, 2, 3], stalle_de=lambda n: None)
    await db.commit()

    st, ar = await _lire(db, T0)
    assert {r[0] for r in st} == {"OK_1600", "OK_1950"}
    assert {r[0] for r in ar} == {"OK_1600", "OK_1950"}


@pytest.mark.asyncio
async def test_bout_en_bout_stalles_basses_gagnantes(db):
    """Dossard ≠ stalle : les stalles 1-3 (dossards 10, 9, 8) gagnent toujours.
    Le biais doit suivre la STALLE, pas le numéro de programme."""
    db.add(Cheval(cheval_id="CH", nom="PEGASE"))
    for k in range(12):
        await _course_passee(db, f"C{k}", T0 - timedelta(days=k + 1), [10, 9, 8],
                             stalle_de=lambda num: 11 - num)
    await db.commit()
    st, ar = await _lire(db, T0)
    b = biais_corde(sorties_corde(st, ar))
    assert b["n"] == 120
    assert b["zones"]["interieure"] > 0 > b["zones"]["milieu"]
    assert b["pente"] < 0
    # Le partant du jour en stalle 1 reçoit le biais intérieur.
    t = traits_corde(1, list(range(1, 11)), b["zones"], b["pente"])
    assert t["draw_bias_score"] > 0 and t["draw_bias_relatif"] > 0


@pytest.mark.asyncio
async def test_rattrapage_des_vecteurs_meme_chemin_que_le_live(db):
    """scripts/patch_features_corde.py recalcule via `charger_biais_corde` +
    `traits_corde` : même valeur que le live, et la course elle-même n'entre pas
    dans son propre biais."""
    from scripts.patch_features_corde import vecteurs_corde_course
    db.add(Cheval(cheval_id="CH", nom="PEGASE"))
    for k in range(12):
        await _course_passee(db, f"C{k}", T0 - timedelta(days=k + 1), [1, 2, 3])
    # La course du jour : arrivée INVERSE (stalles 8-10) — ne doit rien changer.
    await _course_passee(db, "JOUR", T0, [8, 9, 10])
    await db.commit()
    vec = await vecteurs_corde_course(db, "JOUR")
    assert len(vec) == 10
    assert vec["JOUR-1"]["draw_bias_score"] > 0 and vec["JOUR-1"]["draw_bias_relatif"] > 0
    assert vec["JOUR-10"]["draw_bias_relatif"] < 0
