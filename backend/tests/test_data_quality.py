"""Surveillance de la fraîcheur et de la couverture des entrées (Point 13).

Une panne d'alimentation ne casse rien de visible : c'est précisément pourquoi
elle doit être mesurée. Ces tests vérifient que le module ne déclare pas « sain »
ce qui ne l'est pas, et qu'il ne crie pas non plus sur un échantillon trop petit.
"""
from datetime import datetime, timedelta, timezone

import pytest

from db.models import Course, Participation, Resultat
from services import data_quality as dq


MAINTENANT = datetime.now(timezone.utc)


async def _course(db, cid, *, depart, statut="termine", nb_partants=None):
    db.add(Course(course_id=cid, reunion_id="R1", numero=1, nom="T",
                  date_heure=depart, hippodrome_nom="Vichy", discipline="Plat",
                  distance=2000, nb_partants=nb_partants, statut=statut))


async def _partant(db, cid, numero, *, cote_pmu=None, cote_geny=None,
                   cote_pmu_datetime=None, non_partant=False):
    db.add(Participation(
        participation_id=f"p-{cid}-{numero}", course_id=cid,
        cheval_id=f"ch-{cid}-{numero}", numero=numero,
        cote_pmu=cote_pmu, cote_geny=cote_geny,
        cote_pmu_datetime=cote_pmu_datetime, non_partant=non_partant))


# ── Couverture ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_couverture_sous_le_volume_minimal_ne_conclut_pas(db):
    """3 partants ne disent rien de la santé d'une source : jamais de verdict."""
    await _course(db, "C1", depart=MAINTENANT - timedelta(hours=2))
    for n in (1, 2, 3):
        await _partant(db, "C1", n, cote_pmu=None)
    await db.commit()

    out = await dq.couverture_sources(db)
    assert out["n_partants"] == 3
    assert out["sources"]["pmu"]["statut"] == "insufficient_data"


@pytest.mark.asyncio
async def test_source_critique_sous_le_seuil_est_degraded(db):
    await _course(db, "C2", depart=MAINTENANT - timedelta(hours=2))
    # 60 partants, seulement 30 cotés → 50 % < 80 %.
    for n in range(1, 61):
        await _partant(db, "C2", n, cote_pmu=3.0 if n <= 30 else None)
    await db.commit()

    out = await dq.couverture_sources(db)
    assert out["n_partants"] == 60
    assert out["sources"]["pmu"]["couverture_pct"] == 50.0
    assert out["sources"]["pmu"]["statut"] == "degraded"


@pytest.mark.asyncio
async def test_source_appoint_a_zero_est_muette_pas_degraded(db):
    """`geny` à 0 % est un vrai signal, mais ce n'est pas la même gravité que PMU."""
    await _course(db, "C3", depart=MAINTENANT - timedelta(hours=2))
    for n in range(1, 61):
        await _partant(db, "C3", n, cote_pmu=3.0, cote_geny=None)
    await db.commit()

    out = await dq.couverture_sources(db)
    assert out["sources"]["pmu"]["statut"] == "ok"
    assert out["sources"]["geny"]["couverture_pct"] == 0.0
    assert out["sources"]["geny"]["statut"] == "silent"
    assert out["sources"]["geny"]["critique"] is False


@pytest.mark.asyncio
async def test_les_non_partants_ne_comptent_pas_dans_la_couverture(db):
    """Un cheval retiré n'a pas à être coté : l'inclure ferait chuter le taux à tort."""
    await _course(db, "C4", depart=MAINTENANT - timedelta(hours=2))
    for n in range(1, 61):
        await _partant(db, "C4", n, cote_pmu=3.0)
    for n in range(61, 81):
        await _partant(db, "C4", n, cote_pmu=None, non_partant=True)
    await db.commit()

    out = await dq.couverture_sources(db)
    assert out["n_partants"] == 60
    assert out["sources"]["pmu"]["couverture_pct"] == 100.0


# ── Fraîcheur ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scraper_mort_est_signale_stale(db):
    """Le cas réel : 4 jours sans alimentation, invisible pendant 4 jours."""
    await _course(db, "C5", depart=MAINTENANT - timedelta(days=4))
    await _partant(db, "C5", 1, cote_pmu=3.0)
    await db.commit()
    vieux = MAINTENANT - timedelta(days=4)
    await db.execute(Participation.__table__.update()
                     .where(Participation.course_id == "C5").values(updated_at=vieux))
    await db.commit()

    out = await dq.fraicheur_alimentation(db)
    assert out["statut"] == "stale"
    assert out["age_derniere_participation_h"] > dq.SEUIL_FRAICHEUR_SCRAPE_H


@pytest.mark.asyncio
async def test_programme_du_jour_insere_a_minuit_ne_declenche_pas_de_fausse_alerte(db):
    """Piège trouvé en mesurant la production : `courses.created_at` ne bouge
    qu'une fois par jour, donc à 22 h un système SAIN afficherait « dernière
    course créée il y a 22 h ». Le verdict doit porter sur les mises à jour de
    partants, pas sur la création de courses."""
    await _course(db, "C5b", depart=MAINTENANT + timedelta(hours=3), statut="a_venir")
    await _partant(db, "C5b", 1, cote_pmu=3.0)
    await db.commit()
    # Course créée il y a 22 h (programme du matin), partant rafraîchi à l'instant.
    await db.execute(Course.__table__.update()
                     .where(Course.course_id == "C5b")
                     .values(created_at=MAINTENANT - timedelta(hours=22)))
    await db.commit()

    out = await dq.fraicheur_alimentation(db)
    assert out["age_derniere_course_h"] > 20      # vieux, mais normal
    assert out["statut"] == "ok"                  # et pourtant sain


@pytest.mark.asyncio
async def test_base_vide_reste_unknown_et_ne_pretend_pas_etre_saine(db):
    out = await dq.fraicheur_alimentation(db)
    assert out["statut"] == "unknown"
    assert out["age_derniere_course_h"] is None


# ── Cotes figées ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cote_non_republiee_avant_le_depart_est_figee(db):
    await _course(db, "C6", depart=MAINTENANT + timedelta(hours=1), statut="a_venir")
    vieille = MAINTENANT - timedelta(minutes=dq.SEUIL_COTE_FIGEE_MIN + 20)
    fraiche = MAINTENANT - timedelta(minutes=2)
    for n in range(1, 4):
        await _partant(db, "C6", n, cote_pmu=3.0, cote_pmu_datetime=vieille)
    for n in range(4, 6):
        await _partant(db, "C6", n, cote_pmu=3.0, cote_pmu_datetime=fraiche)
    await db.commit()

    out = await dq.cotes_figees(db)
    assert out["mesurable"] is True
    assert out["n_cotes_a_venir"] == 5
    assert out["n_figees"] == 3


@pytest.mark.asyncio
async def test_cotes_figees_ignore_les_lignes_sans_date_source(db):
    """Sans `cote_pmu_datetime` (lignes < migration 0033) on ne conclut rien."""
    await _course(db, "C7", depart=MAINTENANT + timedelta(hours=1), statut="a_venir")
    for n in range(1, 6):
        await _partant(db, "C7", n, cote_pmu=3.0, cote_pmu_datetime=None)
    await db.commit()

    out = await dq.cotes_figees(db)
    assert out["n_cotes_a_venir"] == 0
    assert out["n_figees"] == 0


# ── Concordance ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_arrivee_citant_un_numero_inconnu_est_detectee(db):
    """Un règlement sur un cheval absent des partants fausserait gains et ROI."""
    await _course(db, "C8", depart=MAINTENANT - timedelta(hours=1), nb_partants=2)
    await _partant(db, "C8", 1, cote_pmu=3.0)
    await _partant(db, "C8", 2, cote_pmu=5.0)
    db.add(Resultat(course_id="C8", classement=[
        {"numero": 1, "position": 1},
        {"numero": 99, "position": 2},      # jamais vu parmi les partants
    ]))
    await db.commit()

    out = await dq.concordance_partants(db)
    assert out["n_arrivees_numero_inconnu"] == 1


@pytest.mark.asyncio
async def test_ecart_entre_nb_partants_annonce_et_enregistre(db):
    await _course(db, "C9", depart=MAINTENANT - timedelta(hours=1), nb_partants=10)
    await _partant(db, "C9", 1, cote_pmu=3.0)
    await db.commit()

    out = await dq.concordance_partants(db)
    assert out["n_nb_partants_discordant"] == 1


@pytest.mark.asyncio
async def test_un_non_partant_ne_cree_pas_de_fausse_discordance(db):
    """`nb_partants` est le champ DÉCLARÉ : un cheval déclaré forfait y reste
    compté. Le comparer aux seuls partants effectifs faisait passer l'écart de 21
    à 42 courses sur 85 en production — un faux signal qui noyait les vraies
    incohérences de source."""
    await _course(db, "C9b", depart=MAINTENANT - timedelta(hours=1), nb_partants=3)
    await _partant(db, "C9b", 1, cote_pmu=3.0)
    await _partant(db, "C9b", 2, cote_pmu=4.0)
    await _partant(db, "C9b", 3, cote_pmu=None, non_partant=True)   # forfait
    await db.commit()

    out = await dq.concordance_partants(db)
    assert out["n_nb_partants_discordant"] == 0


# ── Rapport global ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_le_rapport_remonte_les_anomalies_et_le_statut(db):
    await _course(db, "CA", depart=MAINTENANT - timedelta(hours=2))
    for n in range(1, 61):
        await _partant(db, "CA", n, cote_pmu=None)      # source critique morte
    await db.commit()

    rapport = await dq.rapport_qualite(db)
    codes = {a["code"] for a in rapport["anomalies"]}
    assert "source_critique_degradee" in codes
    assert rapport["statut_global"] == "critical"


@pytest.mark.asyncio
async def test_donnees_saines_ne_produisent_aucune_anomalie(db):
    await _course(db, "CB", depart=MAINTENANT - timedelta(hours=2))
    for n in range(1, 61):
        await _partant(db, "CB", n, cote_pmu=3.0, cote_geny=3.1)
    await db.commit()

    rapport = await dq.rapport_qualite(db)
    codes = {a["code"] for a in rapport["anomalies"]}
    assert "source_critique_degradee" not in codes
    assert "arrivee_numero_inconnu" not in codes


@pytest.mark.asyncio
async def test_courses_a_venir_sans_aucune_cote_sont_signalees(db):
    await _course(db, "CC", depart=MAINTENANT + timedelta(hours=2), statut="a_venir")
    for n in range(1, 6):
        await _partant(db, "CC", n, cote_pmu=None)
    await db.commit()

    out = await dq.courses_non_pronosticables(db)
    assert out["n_a_venir"] == 1
    assert out["n_sans_aucune_cote"] == 1


# ── Horodatage RÉEL de la cote (migration 0033) ──────────────────────────────

def test_epoch_pmu_converti_en_utc():
    """`dernierRapportDirect.dateRapport` (epoch ms) → heure de publication réelle."""
    from scraper.sources.pmu import _epoch_ms_to_dt

    dt = _epoch_ms_to_dt(1787084913000)
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.year == 2026 and dt.month == 8 and dt.day == 18


@pytest.mark.parametrize("valeur", [None, 0, True, False, "abc", "", -1, 1787084913])
def test_epoch_aberrant_ne_fabrique_jamais_de_date(valeur):
    """Une date fausse serait pire que pas de date : elle ferait passer une cote
    périmée pour fraîche. Notamment 1787084913 (secondes, pas ms) → 1970."""
    from scraper.sources.pmu import _epoch_ms_to_dt

    assert _epoch_ms_to_dt(valeur) is None


def test_le_snapshot_prefere_l_heure_source_a_l_heure_de_calcul():
    """`odds_observed_at` doit dater la COTE, pas le calcul du pronostic."""
    from ml.prediction_snapshots import build_snapshot_values

    calcul = datetime(2026, 8, 18, 14, 30, tzinfo=timezone.utc)
    publication = datetime(2026, 8, 18, 14, 10, tzinfo=timezone.utc)
    base = dict(
        prediction_run_id="run", snapshot_id="snap", prediction_id="pred",
        participation_id="part", course_id="C1", model_version_id=None,
        features={}, observed_at=calcul,
        course_start_at=datetime(2026, 8, 18, 15, 0, tzinfo=timezone.utc),
        proba_top1=0.3, proba_top3=0.6, proba_top1_raw=None, proba_top3_raw=None,
        proba_top1_low=None, proba_top1_high=None, rang_predit=1,
        confidence_score=50.0, cote_figee=4.2,
    )

    avec = build_snapshot_values(**base, odds_observed_at=publication)
    assert avec["odds_observed_at"] == publication

    # Sans date source (lignes antérieures à 0033) : repli sur l'heure du calcul,
    # borne SUPÉRIEURE honnête — la cote existait au plus tard à cet instant.
    sans = build_snapshot_values(**base)
    assert sans["odds_observed_at"] == calcul


def test_pas_de_cote_figee_pas_d_horodatage_invente():
    from ml.prediction_snapshots import build_snapshot_values

    calcul = datetime(2026, 8, 18, 14, 30, tzinfo=timezone.utc)
    values = build_snapshot_values(
        prediction_run_id="run", snapshot_id="snap", prediction_id="pred",
        participation_id="part", course_id="C1", model_version_id=None,
        features={}, observed_at=calcul, course_start_at=None,
        proba_top1=0.3, proba_top3=0.6, proba_top1_raw=None, proba_top3_raw=None,
        proba_top1_low=None, proba_top1_high=None, rang_predit=1,
        confidence_score=50.0, cote_figee=None,
    )
    assert values["odds_observed_at"] is None


# ── Santé des scrapers : « succès » ne veut pas dire « données » ─────────────

async def _scrape_log(db, source, *, statut, nb_partants, n=1, quand=None):
    from db.models import ScrapeLog
    for i in range(n):
        db.add(ScrapeLog(log_id=f"sl-{source}-{statut}-{nb_partants}-{i}",
                         source=source, statut=statut, nb_partants=nb_partants,
                         created_at=quand or (MAINTENANT - timedelta(hours=1))))


@pytest.mark.asyncio
async def test_scraper_ok_sans_donnees_est_detecte(db):
    """Cas réel : betclic/geny/winamax affichaient ~242 exécutions « ok » avec
    nb_partants=0 — un échec total présenté comme un succès."""
    await _scrape_log(db, "betclic", statut="ok", nb_partants=0, n=30)
    await db.commit()

    out = await dq.sante_scrapers(db)
    assert out["sources"]["betclic"]["statut"] == "ok_but_empty"
    assert out["sources"]["betclic"]["n_ok"] == 30
    assert out["sources"]["betclic"]["n_ok_avec_donnees"] == 0


@pytest.mark.asyncio
async def test_scraper_qui_extrait_vraiment_est_ok(db):
    await _scrape_log(db, "pmu", statut="ok", nb_partants=453, n=30)
    await db.commit()

    out = await dq.sante_scrapers(db)
    assert out["sources"]["pmu"]["statut"] == "ok"


@pytest.mark.asyncio
async def test_source_desactivee_volontairement_ne_declenche_pas_d_alerte(db, monkeypatch):
    """`SCRAPER_DISABLED_SOURCES` : leur silence est voulu, alerter serait du bruit."""
    monkeypatch.setenv("SCRAPER_DISABLED_SOURCES", "turfoo,zeturf")
    await _scrape_log(db, "turfoo", statut="ok", nb_partants=0, n=30)
    await db.commit()

    out = await dq.sante_scrapers(db)
    assert out["sources"]["turfoo"]["statut"] == "disabled"
    assert "turfoo" in out["sources_desactivees"]


@pytest.mark.asyncio
async def test_scraper_trop_peu_execute_ne_conclut_pas(db):
    await _scrape_log(db, "nouveau", statut="ok", nb_partants=0, n=3)
    await db.commit()

    out = await dq.sante_scrapers(db)
    assert out["sources"]["nouveau"]["statut"] == "insufficient_data"


@pytest.mark.asyncio
async def test_le_rapport_signale_les_scrapers_vides(db):
    await _scrape_log(db, "winamax", statut="ok", nb_partants=0, n=30)
    await db.commit()

    rapport = await dq.rapport_qualite(db)
    codes = {a["code"] for a in rapport["anomalies"]}
    assert "scraper_succes_sans_donnees" in codes


@pytest.mark.asyncio
async def test_scraper_sans_partants_mais_avec_courses_reste_ok(db):
    """Faux positif trouvé en production : `pool_pmu`, `resultats` et `paris_turf`
    enregistrent des courses et ZÉRO partant — ce n'est pas leur rôle d'en
    extraire. Les signaler aurait noyé les vraies pannes sous du bruit."""
    from db.models import ScrapeLog
    for i in range(30):
        db.add(ScrapeLog(log_id=f"sl-pool-{i}", source="pool_pmu", statut="ok",
                         nb_courses=36, nb_partants=0,
                         created_at=MAINTENANT - timedelta(hours=1)))
    await db.commit()

    out = await dq.sante_scrapers(db)
    assert out["sources"]["pool_pmu"]["statut"] == "ok"


@pytest.mark.asyncio
async def test_scraper_qui_n_enregistre_rien_du_tout_est_signale(db):
    """betclic/unibet/winamax : 206 exécutions « ok », 0 course ET 0 partant."""
    from db.models import ScrapeLog
    for i in range(30):
        db.add(ScrapeLog(log_id=f"sl-uni-{i}", source="unibet", statut="ok",
                         nb_courses=0, nb_partants=0,
                         created_at=MAINTENANT - timedelta(hours=1)))
    await db.commit()

    out = await dq.sante_scrapers(db)
    assert out["sources"]["unibet"]["statut"] == "ok_but_empty"
