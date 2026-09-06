"""Ce que l'audit du 2026-09-06 a trouvé derrière trois anomalies `data_quality`.

Trois défauts d'ÉCRITURE, tous silencieux : la ligne existait, elle était vide ou
fausse. Un test par défaut, et chacun échoue sur le code d'avant.
"""
import pytest
from datetime import datetime, timedelta
from sqlalchemy import text

from db.models import Cheval, Course, Participation, Equipement, HistoriqueCourse
import ml.features as tr
from ml.features import SQL_DRAW_BIAS, cle_hippodrome, corde_zone
from scraper.base import PartantScrape
from scraper.db_writer import champs_reecrits_participation, equipement_precedent


# ── 1. Une cote connue ne doit JAMAIS être remplacée par un NULL ──────────────

def _partant(**kw):
    base = dict(numero=1, nom="A", cote_pmu=4.2, jockey="J", entraineur="E")
    base.update(kw)
    return PartantScrape(**base)


def test_le_rescrape_sans_cote_ne_vide_pas_la_cote_deja_connue():
    """Le 05/09/2026, la dernière passe de la journée a effacé 295 cotes sur 743.

    Le PMU cesse de publier `dernierRapportDirect` quand la course quitte le pari ;
    l'upsert repassait NULL par-dessus. `cotes_historique` avait toujours les cotes :
    ce n'est donc pas une donnée manquante, c'est une donnée détruite.
    """
    champs = champs_reecrits_participation(_partant(), None, None, None)
    assert "cote_pmu" not in champs
    # Les champs du même bloc `rapports` meurent ensemble : garder la cote sans son
    # horodatage reviendrait à ne plus savoir de quand elle date.
    for k in ("cote_pmu_datetime", "cote_reference", "mouvement_cote_pct",
              "tendance_cote", "tendance_force", "est_favori_pmu"):
        assert k not in champs
    # …mais tout ce qui NE vient PAS des rapports continue d'être réactualisé.
    assert champs["non_partant"] is False


def test_une_cote_presente_est_bien_reecrite_avec_son_horodatage():
    quand = datetime(2026, 9, 6, 12, 0)
    champs = champs_reecrits_participation(
        _partant(cote_pmu_datetime=quand), 4.2, None, 5.0)
    assert champs["cote_pmu"] == 4.2
    assert champs["cote_pmu_datetime"] == quand
    assert champs["cote_reference"] == 5.0


def test_la_stalle_absente_du_flux_n_efface_pas_la_stalle_connue():
    assert "numero_corde" not in champs_reecrits_participation(_partant(), 4.2, None, None)
    assert champs_reecrits_participation(
        _partant(numero_corde=7), 4.2, None, None)["numero_corde"] == 7


# ── 2. « La course précédente » ne peut pas être la course en cours ───────────

async def _course(db, cid, quand):
    db.add(Course(course_id=cid, reunion_id="R",
                  hippodrome_nom="VINCENNES", numero=1, nom=cid,
                  discipline="Attelé", distance=2700, date_heure=quand))


async def _engage(db, cid, pid, oeilleres):
    db.add(Participation(participation_id=pid, course_id=cid, cheval_id="CH", numero=1))
    db.add(Equipement(equipement_id="eq_" + pid, participation_id=pid,
                      cheval_id="CH", course_id=cid, oeilleres=oeilleres))


@pytest.mark.asyncio
async def test_le_cheval_n_est_pas_compare_a_lui_meme(db):
    """`oeilleres_change` est tombé de ~1 070/mois en avril à 8 en septembre.

    La recherche « dernier équipement du cheval, `date_heure DESC` » n'excluait pas
    la course en cours : dès la 2e passe du scraper, la ligne la plus récente était
    celle qu'on venait d'écrire. Le cheval se comparait à lui-même, le changement
    retombait à False et l'upsert écrasait le True du premier passage.
    """
    base = datetime(2026, 9, 1, 12, 0)
    db.add(Cheval(cheval_id="CH", nom="PEGASE"))
    await _course(db, "HIER", base)
    await _course(db, "AUJOURDHUI", base + timedelta(days=7))
    await _engage(db, "HIER", "p_hier", "SANS_OEILLERES")
    await _engage(db, "AUJOURDHUI", "p_auj", "OEILLERES_CLASSIQUE")
    await db.commit()

    prec = await equipement_precedent(db, "CH", "AUJOURDHUI")
    assert prec is not None, "la course d'avant doit être trouvée"
    assert prec[1] == "SANS_OEILLERES"      # et non l'équipement du jour même


@pytest.mark.asyncio
async def test_une_course_posterieure_n_est_pas_la_course_precedente(db):
    """Un cheval déjà engagé la semaine prochaine ne doit pas servir de référence."""
    base = datetime(2026, 9, 1, 12, 0)
    db.add(Cheval(cheval_id="CH", nom="PEGASE"))
    await _course(db, "AUJOURDHUI", base)
    await _course(db, "DEMAIN", base + timedelta(days=1))
    await _engage(db, "AUJOURDHUI", "p_auj", "SANS_OEILLERES")
    await _engage(db, "DEMAIN", "p_dem", "OEILLERES_AUSTRALIENNES")
    await db.commit()

    assert await equipement_precedent(db, "CH", "AUJOURDHUI") is None


# ── 3. Les deux libellés d'hippodrome ne s'apparient que dans un sens ─────────

async def _hist(db, hid, hippo, corde, position):
    db.add(HistoriqueCourse(historique_id=hid, cheval_id="CH", hippodrome=hippo,
                            date_course=datetime(2026, 5, 1).date(), pays="AR",
                            discipline="Plat", distance=2000, corde=corde,
                            position_arrivee=position))


@pytest.mark.asyncio
async def test_le_libelle_court_se_retrouve_dans_le_libelle_long(db):
    """1 896 journalisations en 30 h, toutes « aucune valeur de corde en base ».

    `courses.hippodrome_nom` dit « HIPPODROME DE SAN ISIDRO ARG », tandis que
    `historique_courses.hippodrome` dit « SAN ISIDRO ». Le `ILIKE '%' || long || '%'`
    d'origine cherchait le LONG dans le COURT : il ne pouvait matcher pour aucun
    hippodrome, et les 83 311 lignes de corde de la table n'ont jamais servi.
    """
    db.add(Cheval(cheval_id="CH", nom="PEGASE"))
    await _hist(db, "h1", "SAN ISIDRO", "3", 1)
    await _hist(db, "h2", "SAN ISIDRO", "11", 8)
    await db.commit()

    rows = (await db.execute(text(SQL_DRAW_BIAS), {
        "hippo": cle_hippodrome("HIPPODROME DE SAN ISIDRO ARG"), "dist": 2000,
    })).fetchall()
    assert {r[0] for r in rows} == {"3", "11"}


@pytest.mark.asyncio
async def test_l_appariement_se_fait_en_mots_entiers(db):
    """Sans les espaces de garde, « MONS » se retrouverait dans « SIMONSTOWN »."""
    db.add(Cheval(cheval_id="CH", nom="PEGASE"))
    await _hist(db, "h1", "MONS", "2", 1)
    await db.commit()

    rows = (await db.execute(text(SQL_DRAW_BIAS), {
        "hippo": cle_hippodrome("HIPPODROME DE SIMONSTOWN"), "dist": 2000,
    })).fetchall()
    assert rows == []


def test_la_zone_se_lit_sur_la_stalle_pas_sur_le_dossard():
    """La zone de corde n'a de sens que sur une stalle : en plat, le numéro de
    programme suit le poids ou l'ordre d'engagement, la stalle est tirée au sort."""
    assert corde_zone(3) == "interieure"
    assert corde_zone(11) == "exterieure"
    assert corde_zone(None) == "inconnu"
    assert corde_zone(0) == "inconnu"


# ── 4. Le recul de trot est un écart à la première ligne, pas une distance ────

def test_un_champ_aligne_ne_produit_aucun_recul():
    """Le PMU sert `handicapDistance` à TOUS les partants d'une course ou à aucun.

    1 623 courses la publient sur 60 jours, 362 seulement avec un écart. Lire la
    valeur brute faisait de `recul_metres` la distance de la course (2 950 m) et
    saturait `distance_reelle_ratio` à son plafond de 1,5.
    """
    t = tr.traits_recul(2850, recul_min=2850, recul_mean=2850, recul_max=2850,
                        distance_course=2850)
    assert t["recul_metres"] == 0.0
    assert t["est_recule"] == 0.0
    assert t["recul_premiere_ligne"] == 0.0      # personne n'est reculé : pas d'avantage
    assert t["distance_reelle_ratio"] == 1.0     # et plus de plafond atteint


def test_la_premiere_ligne_se_lit_par_rapport_au_champ_du_jour():
    """C'est le défaut qui rendait `recul_premiere_ligne` constante à 0."""
    devant = tr.traits_recul(2850, recul_min=2850, recul_mean=2860, recul_max=2875,
                             distance_course=2850)
    derriere = tr.traits_recul(2875, recul_min=2850, recul_mean=2860, recul_max=2875,
                               distance_course=2850)
    assert devant["recul_premiere_ligne"] == 1.0
    assert devant["recul_metres"] == 0.0
    assert derriere["recul_premiere_ligne"] == 0.0
    assert derriere["recul_metres"] == 25.0
    assert derriere["est_recule"] == 1.0
    assert derriere["recul_vs_champ"] > devant["recul_vs_champ"]


def test_sans_handicap_de_distance_tout_reste_neutre():
    t = tr.traits_recul(None, recul_min=0, recul_mean=0, recul_max=0, distance_course=2100)
    assert t == {"recul_metres": 0.0, "recul_vs_champ": 0.0, "est_recule": 0.0,
                 "recul_premiere_ligne": 0.0, "distance_reelle_ratio": 1.0}
