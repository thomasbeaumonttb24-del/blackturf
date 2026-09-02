"""Un conseil, une observation — pas ses trente-trois ré-émissions.

Le même plan est ré-émis à chaque mouvement de cote : ~33 snapshots pré-course par
course en production. Toutes ces copies entraient dans l'agrégat de rentabilité, ce
qui faussait TOUTE la statistique du plan de mise :

  - `n_paris` / `n_plans` gonflés d'un facteur ~33 → des seuils de fiabilité
    atteints avec UNE course (constat prod : Tiercé Désordre 35 paris / 1 course,
    Pick5 86 paris / 3 courses, Mini Multi en 4 228 paris / 17 courses) ;
  - l'IC bootstrap ré-échantillonnait 33 copies du même résultat → intervalle ~5,7×
    (√33) trop étroit, donc une fausse certitude publiée ;
  - `losing_streak_max` ×33 pendant que la série ATTENDUE ne croît qu'en ln(n) → le
    test « série > 2× l'attendu » devenait vrai presque partout ;
  - pondération biaisée vers les courses longues et liquides.

La règle de dédup est celle qui sert déjà à l'apprentissage des profils : le DERNIER
conseil émis avant le départ fait foi.
"""
from datetime import datetime, timedelta, timezone

import pytest

from db.models import (
    BetPlanSettlement, BetPlanSnapshot, Course, Participation, Resultat,
)
from ml import bet_plan_performance as bpp

DEPART = datetime(2026, 8, 18, 14, 0, tzinfo=timezone.utc)


def _plan(mise, numero, type_="Placé"):
    return {
        "montant_joue": mise, "ev_global": 0.1, "esperance_gain": mise * 0.1,
        "niveaux": [{"niveau": "securite", "paris": [{
            "type": type_, "chevaux": [{"numero": numero, "nom": "X"}],
            "mise": mise, "gain_potentiel": mise * 3, "probabilite": 0.4,
            "ev_estime": 0.1, "description": "d",
        }]}],
    }


async def _course(db, course_id, numero, gagne):
    db.add(Course(course_id=course_id, reunion_id="R1", numero=1, nom="T",
                  date_heure=DEPART, hippodrome_nom="Pau", discipline="Plat",
                  distance=2000, nb_partants=10, statut="termine"))
    db.add(Participation(participation_id=f"p-{course_id}", course_id=course_id,
                         cheval_id=f"ch-{course_id}", numero=numero, cote_pmu=3.0))
    db.add(Resultat(course_id=course_id, classement=[
        {"numero": numero if gagne else numero + 1, "position": 1},
        {"numero": numero if not gagne else numero + 1, "position": 2},
    ]))


async def _emission(db, course_id, suffixe, *, numero, gagne, mise=4.0,
                    emitted_at, profil="equilibre", montant=10.0):
    """Une ré-émission du MÊME conseil (seule la cote a bougé entre-temps)."""
    sid = f"bp-{course_id}-{suffixe}"
    db.add(BetPlanSnapshot(
        plan_snapshot_id=sid, course_id=course_id, subject_hash="system",
        profil=profil, montant_demande=montant, plan=_plan(mise, numero),
        plan_hash=f"h-{sid}", cotes_utilisees={str(numero): 3.0},
        algo_config={}, algo_version="mp-t", nb_paris=1, montant_joue=mise,
        emitted_at=emitted_at, course_start_at=DEPART, is_pre_course=True,
        origin="mise_plan",
    ))
    net = (mise * 2.5 - mise) if gagne else -mise
    db.add(BetPlanSettlement(
        settlement_id=f"st-{sid}", plan_snapshot_id=sid, course_id=course_id,
        bilan={"paris": [{"type": "Placé", "mise": mise,
                          "gain": mise * 2.5 if gagne else 0.0,
                          "statut": "gagne" if gagne else "perdu"}]},
        montant_mise=mise, montant_retour=mise * 2.5 if gagne else 0.0,
        net=net, roi=(net / mise * 100), nb_paris=1, nb_gagnes=1 if gagne else 0,
        statut="settled", settled_at=DEPART + timedelta(hours=3),
    ))


@pytest.mark.asyncio
async def test_trente_re_emissions_du_meme_conseil_comptent_pour_une(db):
    await _course(db, "C1", numero=1, gagne=False)
    base = DEPART - timedelta(hours=10)
    for k in range(30):
        await _emission(db, "C1", k, numero=1, gagne=False,
                        emitted_at=base + timedelta(minutes=20 * k))
    await db.commit()

    out = await bpp.compute_forward_performance(db, "type_pari")
    seg = out["segments"]["Placé"]
    assert seg["n_plans"] == 1, "une course conseillée = un plan, pas trente"
    assert seg["n_paris"] == 1
    assert seg["n_courses"] == 1
    assert seg["montant_mise"] == 4.0, "la mise ne doit pas être comptée trente fois"


@pytest.mark.asyncio
async def test_c_est_la_derniere_emission_avant_le_depart_qui_fait_foi(db):
    """Même règle que `record_profil_runs` : le dernier conseil émis fait foi."""
    await _course(db, "C2", numero=2, gagne=True)
    base = DEPART - timedelta(hours=5)
    await _emission(db, "C2", "tot", numero=2, gagne=True, mise=2.0, emitted_at=base)
    await _emission(db, "C2", "tard", numero=2, gagne=True, mise=9.0,
                    emitted_at=base + timedelta(hours=4))
    await db.commit()

    out = await bpp.compute_forward_performance(db, "type_pari")
    seg = out["segments"]["Placé"]
    assert seg["n_plans"] == 1
    assert seg["montant_mise"] == 9.0, "la mise retenue est celle du dernier conseil"


@pytest.mark.asyncio
async def test_deux_profils_sur_la_meme_course_restent_deux_observations(db):
    """La dédup porte sur le CONSEIL, pas sur la course : deux profils, c'est deux
    conseils différents, et le rapport les segmente."""
    await _course(db, "C3", numero=3, gagne=False)
    base = DEPART - timedelta(hours=3)
    for k in range(5):
        await _emission(db, "C3", f"eq{k}", numero=3, gagne=False, profil="equilibre",
                        emitted_at=base + timedelta(minutes=10 * k))
        await _emission(db, "C3", f"ag{k}", numero=3, gagne=False, profil="agressif",
                        emitted_at=base + timedelta(minutes=10 * k))
    await db.commit()

    out = await bpp.compute_forward_performance(db, "profil")
    assert out["segments"]["equilibre"]["n_plans"] == 1
    assert out["segments"]["agressif"]["n_plans"] == 1
    assert out["global"]["n_plans"] == 2


@pytest.mark.asyncio
async def test_deux_montants_demandes_restent_deux_plans_distincts(db):
    """10 € et 50 € ne produisent pas la même sélection : ce sont deux conseils."""
    await _course(db, "C4", numero=4, gagne=False)
    base = DEPART - timedelta(hours=2)
    await _emission(db, "C4", "a", numero=4, gagne=False, montant=10.0, emitted_at=base)
    await _emission(db, "C4", "b", numero=4, gagne=False, montant=50.0, emitted_at=base)
    await db.commit()

    out = await bpp.compute_forward_performance(db, "type_pari")
    assert out["segments"]["Placé"]["n_plans"] == 2


@pytest.mark.asyncio
async def test_le_dernier_reglement_fait_toujours_foi(db):
    """La dédup des ré-émissions ne doit pas casser celle des règlements : un rapport
    publié tardivement ajoute une ligne, et c'est elle qui compte."""
    await _course(db, "C5", numero=5, gagne=True)
    await _emission(db, "C5", "u", numero=5, gagne=True, mise=4.0,
                    emitted_at=DEPART - timedelta(hours=1))
    db.add(BetPlanSettlement(
        settlement_id="st-tardif", plan_snapshot_id="bp-C5-u", course_id="C5",
        bilan={"paris": [{"type": "Placé", "mise": 4.0, "gain": 40.0,
                          "statut": "gagne"}]},
        montant_mise=4.0, montant_retour=40.0, net=36.0, roi=900.0,
        nb_paris=1, nb_gagnes=1, statut="settled",
        settled_at=DEPART + timedelta(days=2),
    ))
    await db.commit()

    out = await bpp.compute_forward_performance(db, "type_pari")
    seg = out["segments"]["Placé"]
    assert seg["n_plans"] == 1
    assert seg["montant_retour"] == 40.0, "le règlement le plus récent fait foi"


@pytest.mark.asyncio
async def test_la_serie_de_pertes_n_est_plus_multipliee_par_les_re_emissions(db):
    """Avant : 3 courses perdantes ré-émises 10 fois = série de 30, comparée à une
    série attendue qui ne croît qu'en ln(n) → tout segment finissait « drawdown
    excessif ». Après : la série vaut le nombre de courses réellement perdues."""
    base = DEPART - timedelta(hours=6)
    for i in range(12):
        cid = f"S{i}"
        await _course(db, cid, numero=1, gagne=False)
        for k in range(10):
            await _emission(db, cid, k, numero=1, gagne=False,
                            emitted_at=base + timedelta(minutes=5 * k))
    await db.commit()

    out = await bpp.compute_forward_performance(db, "type_pari")
    seg = out["segments"]["Placé"]
    assert seg["n_plans"] == 12
    assert seg["losing_streak_max"] == 12, "12 courses perdues, pas 120 plans"
