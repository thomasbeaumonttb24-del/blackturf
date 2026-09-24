"""Ticket Quinté+ traité comme de l'argent réellement misé — décision du 2026-09-24.

1. « Enregistrer ce plan » écrit AUSSI le ticket Quinté+ dans le capital
   (bankroll_entries), réglé ensuite aux vrais rapports — champ de plusieurs
   combinaisons et Bonus 4sur5 / Bonus 3 compris — et tenu hors de l'apprentissage
   des poids par type du plan principal.
2. Le plafond d'exposition quotidienne compte le coût du Quinté+.
3. Le palmarès montre le Quinté+ sur une ligne à part, jamais dans le ROI du plan
   principal, et « premiers résultats à venir » tant qu'aucun ticket n'est réglé.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from services import mise_calculator as mc
from services.bet_settlement import (
    MARQUEUR_MODULE_QUINTE, est_ligne_module_quinte, note_ligne_module_quinte,
    regler_ligne_quinte, settle_module_quinte,
)

_INFO_QUINTE = {
    "nb_partants": 16, "est_simple_gagnant": True, "est_simple_place": True,
    "est_couple_gagnant": True, "est_couple_place": True, "est_trio": True,
    "est_couple_ordre": True, "est_2sur4": True, "est_tierce": True,
    "est_quarte": True, "est_quinte": True,
}
_INFO_SANS_QUINTE = dict(_INFO_QUINTE, est_quinte=False)


def _preds(n=16):
    return [
        {"numero": i + 1, "nom_cheval": f"Cheval{i + 1}",
         "cote_pmu": 2.0 + i * 1.5, "proba_top1": max(0.30 - i * 0.018, 0.005),
         "proba_top3": max(0.6 - i * 0.03, 0.02), "non_partant": False}
        for i in range(n)
    ]


def _plan_dict(montant, profil, info=_INFO_QUINTE):
    return mc.plan_to_dict(mc.generer_plan(montant, profil, _preds(), info,
                                           respect_montant=True))


# Arrivée RÉELLE du Quinté+ du 24/09/2026 (24092026R1C1, ParisLongchamp) et ses
# rapports détaillés tels que publiés par le PMU (lus en base de prod).
ARRIVEE_2409 = [{"numero": n, "position": i} for i, n in enumerate((13, 8, 10, 4, 16, 7), 1)]
DETAIL_2409 = {"e_quinte_plus": [
    {"libelle": "e-Quinté+ Ordre", "rapport": 4703.3, "combinaison": "13-8-10-4-16"},
    {"libelle": "e-Quinté+ Désordre", "rapport": 39.1, "combinaison": "13-8-10-4-16"},
    {"libelle": "e-Bonus 4sur5", "rapport": 2.4, "combinaison": "13-8-10-4"},
    {"libelle": "e-Bonus 4sur5", "rapport": 2.4, "combinaison": "13-8-10-16"},
    {"libelle": "e-Bonus 4sur5", "rapport": 2.4, "combinaison": "13-8-4-16"},
    {"libelle": "e-Bonus 4sur5", "rapport": 2.4, "combinaison": "13-10-4-16"},
    {"libelle": "e-Bonus 4sur5", "rapport": 2.4, "combinaison": "8-10-4-16"},
    {"libelle": "e-Bonus 3", "rapport": 2.1, "combinaison": "13-8-10"},
]}
AGREGAT_2409 = {"e_quinte_plus": 4703.3}


# ── 1. Lignes de capital écrites par « Enregistrer ce plan » ─────────────────

def test_enregistrer_le_plan_ecrit_aussi_le_ticket_quinte():
    from api.routes.courses import lignes_capital_du_plan
    plan = _plan_dict(100, "equilibre")          # champ 6 : 6 combinaisons à 2 € = 12 €
    lignes = lignes_capital_du_plan(plan, "equilibre")
    quinte = [l for l in lignes if l.get("_quinte")]
    principal = [l for l in lignes if not l.get("_quinte")]

    assert len(quinte) == 1, "une ligne Quinté+ et une seule"
    q = quinte[0]
    assert q["type_pari"] == "Quinté+ Désordre"
    assert q["mise"] == plan["module_quinte"]["cout_total"] == 12.0
    assert [int(n) for n in q["chevaux"].replace("N°", "").split(" + ")] == [
        c["numero"] for c in plan["module_quinte"]["chevaux"]]
    assert est_ligne_module_quinte(q["notes"])
    assert "champ 6 chevaux" in q["notes"]
    # Le plan principal garde ses lignes, inchangées, et le total = montant saisi.
    assert principal and all(not est_ligne_module_quinte(l["notes"]) for l in principal)
    assert sum(l["mise"] for l in principal) == pytest.approx(plan["montant_joue"])
    assert sum(l["mise"] for l in lignes) == pytest.approx(100.0)


@pytest.mark.parametrize("profil", ("conservateur", "equilibre"))
def test_ticket_quinte_ajoute_au_montant_sous_4_euros_est_enregistre(profil):
    from api.routes.courses import lignes_capital_du_plan
    plan = _plan_dict(3, profil)
    lignes = lignes_capital_du_plan(plan, profil)
    q = [l for l in lignes if l.get("_quinte")]
    assert len(q) == 1 and q[0]["mise"] == 2.0
    assert sum(l["mise"] for l in lignes) == pytest.approx(plan["montant_total"]) == 5.0


def test_hors_course_quinte_aucune_ligne_quinte():
    from api.routes.courses import lignes_capital_du_plan
    lignes = lignes_capital_du_plan(_plan_dict(20, "agressif", _INFO_SANS_QUINTE), "agressif")
    assert lignes and not any(l.get("_quinte") for l in lignes)
    assert not any(est_ligne_module_quinte(l["notes"]) for l in lignes)


def test_module_indisponible_aucune_ligne_quinte():
    from api.routes.courses import lignes_capital_du_plan
    plan = {"niveaux": [], "module_quinte": {"disponible": False, "cout_total": 0.0}}
    assert lignes_capital_du_plan(plan, "equilibre") == []


def test_note_du_ticket_quinte():
    assert note_ligne_module_quinte("agressif", "tendue") == f"{MARQUEUR_MODULE_QUINTE} · agressif · tendue"
    assert not est_ligne_module_quinte("Plan de mise IA · agressif")
    assert not est_ligne_module_quinte(None)


async def _course_quinte_a_venir(db, course_id="QUINTE1"):
    import uuid
    from db.models import Cheval, Course, Participation, Prediction
    db.add(Course(course_id=course_id, reunion_id="R1", numero=1, nom="Quinté du jour",
                  date_heure=datetime.now(timezone.utc) + timedelta(hours=3),
                  hippodrome_nom="Vincennes", discipline="Plat", distance=2000,
                  nb_partants=14, statut="a_venir", est_quinte=True, est_tierce=True,
                  est_quarte=True))
    for p in _preds(14):
        cid, pid = str(uuid.uuid4()), str(uuid.uuid4())
        db.add(Cheval(cheval_id=cid, nom=p["nom_cheval"], age=4, sexe="H"))
        db.add(Participation(participation_id=pid, course_id=course_id, cheval_id=cid,
                             numero=p["numero"], cote_pmu=p["cote_pmu"], non_partant=False))
        db.add(Prediction(prediction_id=str(uuid.uuid4()), participation_id=pid,
                          course_id=course_id, proba_top1=p["proba_top1"],
                          proba_top3=p["proba_top3"], rang_predit=p["numero"]))
    await db.commit()


@pytest.mark.asyncio
async def test_route_enregistrer_paris_ecrit_et_remplace_le_ticket_quinte(client, db, admin_headers):
    from sqlalchemy import select
    from db.models import BankrollEntry
    await _course_quinte_a_venir(db)

    for _ in range(2):   # ré-enregistrer le même profil remplace, ne cumule pas
        resp = await client.post("/api/v1/courses/QUINTE1/enregistrer-paris",
                                 json={"montant": 100, "profil_risque": "equilibre"},
                                 headers=admin_headers)
        assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["quinte_enregistre"] is True and body["montant_quinte"] == 12.0
    assert body["montant_total"] == pytest.approx(100.0)

    db.expire_all()
    lignes = (await db.execute(select(BankrollEntry).where(
        BankrollEntry.course_id == "QUINTE1"))).scalars().all()
    quinte = [l for l in lignes if est_ligne_module_quinte(l.notes)]
    assert len(quinte) == 1
    assert quinte[0].type_pari == "Quinté+ Désordre" and quinte[0].mise == 12.0
    assert quinte[0].suivi_reco_ia is True and quinte[0].resultat is None
    assert len(quinte[0].chevaux.split(" + ")) == 6
    assert body["enregistres"] == len(lignes)
    assert sum(l.mise for l in lignes) == pytest.approx(100.0)


# ── 1. Règlement d'une ligne Quinté+ du capital ──────────────────────────────

def test_reglement_reel_du_24_09_tendu_bonus_4sur5():
    """Tendu prudent du 24/09 (8-7-4-16-10) : 4 des 5 premiers → Bonus 4sur5 à 2,4."""
    q = regler_ligne_quinte("Quinté+ Désordre", [8, 7, 4, 16, 10], 2.0,
                            ARRIVEE_2409, AGREGAT_2409, 15, DETAIL_2409)
    assert q["resultat"] == "gagne"
    assert q["gain_perte"] == pytest.approx(2.0 * 2.4 - 2.0)
    assert q["cote"] == pytest.approx(2.4)
    assert q["bilan"]["nb_bonus"] == 1


def test_reglement_champ_6_plusieurs_combinaisons_gagnantes():
    """Champ 6 à 12 € (6 × 2 €) : deux combinaisons contiennent 8-10-4-16 → deux
    Bonus 4sur5. Un règlement par settle_pari (une seule combinaison de 5) l'aurait
    déclaré perdant : 6 chevaux ≠ 5."""
    q = regler_ligne_quinte("Quinté+ Désordre", [8, 7, 4, 16, 10, 6], 12.0,
                            ARRIVEE_2409, AGREGAT_2409, 15, DETAIL_2409)
    assert q["resultat"] == "gagne"
    assert q["bilan"]["nb_combinaisons"] == 6 and q["bilan"]["nb_gagnantes"] == 2
    assert q["gain_perte"] == pytest.approx(2 * 2.0 * 2.4 - 12.0)


def test_reglement_champ_avec_cinq_sur_cinq_et_bonus():
    """Champ 6 qui contient les 5 premiers : 1 Désordre + 5 Bonus 4sur5, chacun à
    son rapport — jamais l'Ordre pour une combinaison issue d'un champ."""
    q = regler_ligne_quinte("Quinté+ Désordre", [13, 8, 10, 4, 16, 2], 12.0,
                            ARRIVEE_2409, AGREGAT_2409, 15, DETAIL_2409)
    rangs = sorted(g["rang"] for g in q["bilan"]["gagnantes"])
    assert rangs == ["Bonus 4sur5"] * 5 + ["Désordre"]
    assert q["gain_perte"] == pytest.approx(2.0 * 39.1 + 5 * 2.0 * 2.4 - 12.0)


def test_reglement_bonus_3_seul():
    q = regler_ligne_quinte("Quinté+ Désordre", [13, 8, 10, 1, 2], 2.0,
                            ARRIVEE_2409, AGREGAT_2409, 15, DETAIL_2409)
    assert q["resultat"] == "gagne"
    assert q["bilan"]["gagnantes"][0]["rang"] == "Bonus 3"
    assert q["gain_perte"] == pytest.approx(2.0 * 2.1 - 2.0)


def test_reglement_perdu():
    q = regler_ligne_quinte("Quinté+ Désordre", [1, 2, 3, 5, 6, 9, 11], 42.0,
                            ARRIVEE_2409, AGREGAT_2409, 15, DETAIL_2409)
    assert q["resultat"] == "perd" and q["gain_perte"] == -42.0


def test_reglement_en_attente_si_rapport_gagnant_absent():
    """Bonus gagné mais aucun rapport détaillé publié : on attend, rien n'est inventé."""
    assert regler_ligne_quinte("Quinté+ Désordre", [8, 7, 4, 16, 10], 2.0,
                               ARRIVEE_2409, AGREGAT_2409, 15, None) is None


def test_reglement_non_partants():
    tous = regler_ligne_quinte("Quinté+ Désordre", [8, 7, 4, 16, 10], 2.0,
                               ARRIVEE_2409, AGREGAT_2409, 15, DETAIL_2409, non_partants={7})
    assert tous["resultat"] == "rembourse" and tous["gain_perte"] == 0.0
    # Champ 6 avec un non-partant : ses 5 combinaisons sont remboursées, la 6e
    # (sans lui) est jouée à 2 € — le net se calcule sur ces 2 €, pas sur 12 €.
    partiel = regler_ligne_quinte("Quinté+ Désordre", [8, 7, 4, 16, 10, 6], 12.0,
                                  ARRIVEE_2409, AGREGAT_2409, 15, DETAIL_2409,
                                  non_partants={6})
    assert partiel["bilan"]["nb_rembourse"] == 5
    assert partiel["gain_perte"] == pytest.approx(2.0 * 2.4 - 2.0)


def test_regler_ligne_quinte_ignore_les_autres_types():
    assert regler_ligne_quinte("Trio", [13, 8, 10], 2.0, ARRIVEE_2409, {}, 15, None) is None
    assert regler_ligne_quinte("Quinté+ Désordre", [13, 8, 10, 4], 2.0,
                               ARRIVEE_2409, AGREGAT_2409, 15, DETAIL_2409) is None


def test_tendu_identique_a_settle_module_quinte():
    module = {"disponible": True, "type_pari": "Quinté+ Désordre", "cout_total": 2.0,
              "chevaux": [{"numero": n} for n in (13, 8, 10, 4, 16)]}
    b = settle_module_quinte(module, ARRIVEE_2409, AGREGAT_2409, 15, DETAIL_2409)
    q = regler_ligne_quinte("Quinté+ Désordre", [13, 8, 10, 4, 16], 2.0,
                            ARRIVEE_2409, AGREGAT_2409, 15, DETAIL_2409)
    # Tendu joué dans l'ordre exact de l'arrivée : payé à l'Ordre.
    assert q["gain_perte"] == pytest.approx(b["net"]) == pytest.approx(2.0 * 4703.3 - 2.0)


async def _course_terminee(db, course_id="24092026R1C1"):
    from db.models import Course, Resultat
    db.add(Course(course_id=course_id, reunion_id="R1", numero=1, nom="Quinté",
                  date_heure=datetime(2026, 9, 24, 11, 55, tzinfo=timezone.utc),
                  hippodrome_nom="ParisLongchamp", discipline="Plat", distance=2000,
                  nb_partants=15, statut="termine"))
    db.add(Resultat(course_id=course_id, classement=ARRIVEE_2409, rapports=AGREGAT_2409,
                    rapports_detail=DETAIL_2409))
    await db.commit()


@pytest.mark.asyncio
async def test_settle_pending_bets_regle_la_ligne_quinte_du_capital(db):
    from api.routes.bankroll import settle_pending_bets
    from db.models import BankrollEntry
    await _course_terminee(db)
    now = datetime(2026, 9, 24, 11, 0, tzinfo=timezone.utc)
    champ = BankrollEntry(entry_id="q1", user_id="u1", course_id="24092026R1C1", date=now,
                          type_pari="Quinté+ Désordre",
                          chevaux="N°8 + N°7 + N°4 + N°16 + N°10 + N°6", mise=12.0,
                          suivi_reco_ia=True,
                          notes=note_ligne_module_quinte("equilibre", "champ 6 chevaux"))
    principal = BankrollEntry(entry_id="p1", user_id="u1", course_id="24092026R1C1",
                              date=now, type_pari="Simple Gagnant", chevaux="N°8",
                              mise=8.0, suivi_reco_ia=True, notes="Plan de mise IA · equilibre")
    db.add_all([champ, principal])
    await db.commit()

    await settle_pending_bets(db, None)
    await db.refresh(champ)
    await db.refresh(principal)
    assert champ.resultat == "gagne"
    assert champ.gain_perte == pytest.approx(2 * 2.0 * 2.4 - 12.0)
    assert champ.cote == pytest.approx(0.8)
    assert principal.resultat == "perd" and principal.gain_perte == -8.0


# ── 1. Hors de l'apprentissage des poids par type ────────────────────────────

@pytest.mark.asyncio
async def test_ticket_quinte_du_plan_exclu_de_l_apprentissage_par_type(db):
    from db.models import BankrollEntry
    from ml.bet_performance import compute_type_roi_weights
    now = datetime(2026, 9, 24, 11, 0, tzinfo=timezone.utc)

    def _ligne(eid, type_pari, mise, net, notes):
        return BankrollEntry(entry_id=eid, user_id="u1", course_id=None, date=now,
                             type_pari=type_pari, chevaux="N°1", mise=mise,
                             resultat="gagne" if net > 0 else "perd", gain_perte=net,
                             suivi_reco_ia=True, notes=notes)

    db.add_all([
        # Le Quinté+ du plan principal (profil risqué) : appris normalement.
        _ligne("a", "Quinté+ Désordre", 2.0, -2.0, "Plan de mise IA · agressif"),
        # Le ticket Quinté+ enregistré avec le plan : un gros gain qui, compté,
        # ferait monter le poids appris du type.
        _ligne("b", "Quinté+ Désordre", 12.0, 500.0,
               note_ligne_module_quinte("equilibre", "champ 6 chevaux")),
        _ligne("c", "Simple Gagnant", 10.0, 5.0, "Plan de mise IA · equilibre"),
    ])
    await db.commit()

    poids = await compute_type_roi_weights(db)
    # Seule la ligne du plan principal compte : ROI −100 % → poids plancher.
    assert poids["Quinté+ Désordre"] == pytest.approx(max(0.5, 1.0 - 1.0 * 1 / 13), abs=1e-3)
    assert "Simple Gagnant" in poids

    # Sans ligne du plan principal, le type n'est pas appris du tout.
    await db.execute(text("DELETE FROM bankroll_entries WHERE entry_id = 'a'"))
    await db.commit()
    assert "Quinté+ Désordre" not in await compute_type_roi_weights(db)


# ── 2. Plafond d'exposition quotidienne ──────────────────────────────────────

@pytest.mark.asyncio
async def test_exposition_quotidienne_compte_le_quinte(db):
    from db.models import BetPlanSnapshot, Course
    from services import bet_plan_snapshots as bps
    subject = bps.subject_hash("user-q", "secret")
    maintenant = datetime.now(timezone.utc)
    depart = maintenant + timedelta(hours=2)
    db.add(Course(course_id="EXPQ", reunion_id="R1", numero=1, nom="Q",
                  date_heure=depart, hippodrome_nom="Pau", discipline="Plat",
                  distance=2000, nb_partants=16, statut="a_venir"))
    plan = _plan_dict(20, "equilibre")
    assert plan["montant_quinte"] == 2.0 and plan["montant_joue"] == 18.0
    values = bps.build_plan_snapshot_values(
        course_id="EXPQ", plan=plan, profil="equilibre", montant_demande=20.0,
        cotes_utilisees={1: 3.0}, algo_config={}, emitted_at=maintenant - timedelta(minutes=1),
        course_start_at=depart, subject=subject)
    db.add(BetPlanSnapshot(**values))
    # Un plan d'avant le Quinté+ (sans `montant_quinte`) compte pour son seul montant joué.
    ancien = dict(_plan_dict(10, "equilibre", _INFO_SANS_QUINTE))
    ancien.pop("montant_quinte", None)
    values2 = bps.build_plan_snapshot_values(
        course_id="EXPQ", plan=ancien, profil="agressif", montant_demande=10.0,
        cotes_utilisees={1: 3.0}, algo_config={}, emitted_at=maintenant - timedelta(minutes=2),
        course_start_at=depart, subject=subject)
    db.add(BetPlanSnapshot(**values2))
    await db.commit()

    total = await bps.daily_exposure_total(db, subject)
    assert total == pytest.approx(18.0 + 2.0 + values2["montant_joue"])


def test_supplement_quinte_pour_le_plafond():
    assert mc.supplement_quinte(3, "equilibre", _INFO_QUINTE) == 2.0     # ajouté au montant
    assert mc.supplement_quinte(1, "agressif", _INFO_QUINTE) == 2.0
    assert mc.supplement_quinte(10, "equilibre", _INFO_QUINTE) == 0.0    # pris sur le montant
    assert mc.supplement_quinte(3, "equilibre", _INFO_SANS_QUINTE) == 0.0
    # Cohérent avec le plan réellement généré.
    for montant in (1, 2, 3, 4, 10):
        plan = _plan_dict(montant, "equilibre")
        assert plan["montant_total"] == max(2, montant) + mc.supplement_quinte(
            montant, "equilibre", _INFO_QUINTE)


def test_route_plafond_compte_le_montant_engage():
    from pathlib import Path
    import api.routes.courses as courses_mod
    source = Path(courses_mod.__file__).read_text(encoding="utf-8")
    assert "_engage = montant + supplement_quinte(" in source
    assert "_deja_joue + _engage > _cap" in source


# ── 3. Palmarès : ligne Quinté+ séparée ──────────────────────────────────────

_DDL_PROFIL_RUN_LOG = """
CREATE TABLE IF NOT EXISTS profil_run_log (
    log_id TEXT PRIMARY KEY, course_id TEXT, profil TEXT, plan TEXT, resultat TEXT,
    statut TEXT, roi_reel REAL, meta TEXT, created_at TEXT, settled_at TEXT
)"""


async def _run(db, log_id, profil, plan, created_at="2026-09-24 11:44:05.000000",
               meta=None, statut="settled", course_id="24092026R1C1"):
    await db.execute(text("""
        INSERT INTO profil_run_log (log_id, course_id, profil, plan, resultat, statut,
                                    meta, created_at, settled_at)
        VALUES (:id, :cid, :p, :plan, :res, :st, :meta, :ca, :ca)
    """), {"id": log_id, "cid": course_id, "p": profil, "plan": json.dumps(plan),
           "res": json.dumps({"paris": [], "total_mise": 8.0, "total_gain": 0.0}),
           "st": statut, "meta": json.dumps(meta) if meta else None, "ca": created_at})


def _module(numeros, cout):
    return {"disponible": True, "type_pari": "Quinté+ Désordre", "cout_total": cout,
            "couverture": "tendue" if len(numeros) == 5 else f"champ {len(numeros)} chevaux",
            "chevaux": [{"numero": n} for n in numeros]}


@pytest.mark.asyncio
async def test_palmares_quinte_premiers_resultats_a_venir_sans_ticket_regle(db, monkeypatch):
    from api.routes import stats as _stats
    from api.routes.stats import _quinte_palmares
    # Mécanique du règlement sur les plans réels du 24/09, figés avant l'affichage
    # du module : on recule la borne d'affichage pour les compter ici.
    monkeypatch.setattr(_stats, "QUINTE_MODULE_DEPUIS", _stats.datetime(2026, 9, 23, tzinfo=_stats.timezone.utc))
    await db.execute(text(_DDL_PROFIL_RUN_LOG))
    await _course_terminee(db)
    await _run(db, "r0", "equilibre", {"niveaux": [], "module_quinte": None})
    await db.commit()
    q = await _quinte_palmares(db)
    assert q["disponible"] is False and q["nb_tickets"] == 0 and q["roi"] is None


@pytest.mark.asyncio
async def test_palmares_quinte_ligne_separee_reglee_aux_vrais_rapports(db, monkeypatch):
    from api.routes import stats as _stats
    from api.routes.stats import _quinte_palmares
    # Mécanique du règlement sur les plans réels du 24/09, figés avant l'affichage
    # du module : on recule la borne d'affichage pour les compter ici.
    monkeypatch.setattr(_stats, "QUINTE_MODULE_DEPUIS", _stats.datetime(2026, 9, 23, tzinfo=_stats.timezone.utc))
    await db.execute(text(_DDL_PROFIL_RUN_LOG))
    await _course_terminee(db)
    # Les trois plans réellement figés du 24/09 (tendu / champ 6 / champ 7).
    await _run(db, "r1", "conservateur", {"niveaux": [], "module_quinte": _module([8, 7, 4, 16, 10], 2.0)})
    await _run(db, "r2", "equilibre", {"niveaux": [], "module_quinte": _module([8, 7, 4, 16, 10, 6], 12.0)})
    await _run(db, "r3", "agressif", {"niveaux": [], "module_quinte": _module([8, 7, 4, 16, 10, 6, 3], 42.0)})
    # Exclus : un backfill, et un plan figé APRÈS le départ.
    await _run(db, "r4", "agressif", {"module_quinte": _module([13, 8, 10, 4, 16], 2.0)},
               meta={"backfill": "true"})
    await _run(db, "r5", "agressif", {"module_quinte": _module([13, 8, 10, 4, 16], 2.0)},
               created_at="2026-09-24 12:30:00.000000")
    await db.commit()

    q = await _quinte_palmares(db)
    assert q["disponible"] is True
    assert q["nb_tickets"] == 3 and q["nb_courses"] == 1
    assert q["mise_totale"] == pytest.approx(56.0)
    # 1 + 2 + 3 combinaisons contiennent 8-10-4-16 → six Bonus 4sur5 à 2,4 pour 1 €.
    assert q["nb_bonus"] == 6 and q["nb_cinq_sur_cinq"] == 0
    assert q["retour"] == pytest.approx(6 * 2.0 * 2.4)
    assert q["roi"] == pytest.approx(round((28.8 - 56.0) / 56.0 * 100, 1))
    assert q["nb_tickets_gagnants"] == 3
    assert set(q["par_profil"]) == {"conservateur", "equilibre", "agressif"}


@pytest.mark.asyncio
async def test_palmares_quinte_ticket_en_attente_hors_chiffres(db, monkeypatch):
    from api.routes import stats as _stats
    from api.routes.stats import _quinte_palmares
    # Mécanique du règlement sur les plans réels du 24/09, figés avant l'affichage
    # du module : on recule la borne d'affichage pour les compter ici.
    monkeypatch.setattr(_stats, "QUINTE_MODULE_DEPUIS", _stats.datetime(2026, 9, 23, tzinfo=_stats.timezone.utc))
    from db.models import Resultat
    await db.execute(text(_DDL_PROFIL_RUN_LOG))
    await _course_terminee(db)
    res = await db.get(Resultat, "24092026R1C1")
    res.rapports_detail = None                     # Bonus gagné, rapport pas publié
    await _run(db, "r1", "conservateur", {"module_quinte": _module([8, 7, 4, 16, 10], 2.0)})
    await db.commit()
    q = await _quinte_palmares(db)
    assert q["disponible"] is False and q["nb_en_attente"] == 1 and q["mise_totale"] == 0.0


@pytest.mark.asyncio
async def test_palmares_public_expose_le_bloc_quinte_a_part(client):
    data = (await client.get("/api/v1/stats/palmares-public")).json()
    assert "quinte" in data
    assert data["quinte"]["disponible"] is False     # base vide : premiers résultats à venir


@pytest.mark.asyncio
async def test_palmares_quinte_exclut_les_tickets_jamais_affiches(db):
    """Les plans figés avant l'affichage du module (2026-09-24 17:08 UTC) portaient
    un Quinté+ calculé mais invisible : ils ne comptent pas au palmarès."""
    from api.routes.stats import _quinte_palmares
    await db.execute(text(_DDL_PROFIL_RUN_LOG))
    await _course_terminee(db)
    await _run(db, "r1", "conservateur", {"niveaux": [], "module_quinte": _module([8, 7, 4, 16, 10], 2.0)})
    await db.commit()
    q = await _quinte_palmares(db)
    assert q["disponible"] is False and q["nb_tickets"] == 0


@pytest.mark.asyncio
async def test_palmares_public_quinte_sans_roi_ni_montants(client):
    """Le public reçoit des comptages : ni ROI, ni mise/retour agrégés (qui
    permettraient de le recalculer), ni détail par profil — réservés à l'admin."""
    q = (await client.get("/api/v1/stats/palmares-public")).json()["quinte"]
    for champ in ("roi", "net", "mise_totale", "retour", "par_profil"):
        assert champ not in q, champ
    assert {"nb_tickets", "nb_bonus", "nb_tickets_gagnants"} <= set(q)


@pytest.mark.parametrize("montant,total", [(3, 13.0), (20, 20.0)])
def test_risque_cinq_lignes_de_capital_une_par_ticket(montant, total):
    """Plan risqué enregistré : cinq lignes Quinté+ (une par ticket tendu, 2 €),
    chacune avec ses cinq chevaux, réglables comme un tendu."""
    from api.routes.courses import lignes_capital_du_plan
    plan = _plan_dict(montant, "agressif")
    lignes = lignes_capital_du_plan(plan, "agressif")
    q = [l for l in lignes if l.get("_quinte")]
    assert len(q) == 5 and all(l["mise"] == 2.0 for l in q)
    assert [l["chevaux"] for l in q] == [
        " + ".join(f"N°{n}" for n in c) for c in plan["module_quinte"]["combinaisons"]]
    assert all(est_ligne_module_quinte(l["notes"]) for l in q)
    assert sum(l["mise"] for l in lignes) == pytest.approx(plan["montant_total"]) == total


@pytest.mark.asyncio
async def test_palmares_quinte_compte_les_cinq_tickets_du_risque(db, monkeypatch):
    """Un plan risqué = cinq tickets tendus : le palmarès en compte cinq, et compte
    gagnant chaque ticket payé (Ordre, Bonus 4sur5, Bonus 3), sur les rapports réels."""
    from api.routes import stats as _stats
    from api.routes.stats import _quinte_palmares
    monkeypatch.setattr(_stats, "QUINTE_MODULE_DEPUIS",
                        _stats.datetime(2026, 9, 23, tzinfo=_stats.timezone.utc))
    await db.execute(text(_DDL_PROFIL_RUN_LOG))
    await _course_terminee(db)
    module = {"disponible": True, "type_pari": "Quinté+ Désordre", "cout_total": 10.0,
              "couverture": "5 tickets tendus", "chevaux": [],
              "combinaisons": [[13, 8, 10, 4, 16], [8, 10, 4, 16, 7], [8, 7, 4, 16, 10],
                               [1, 2, 3, 5, 6], [13, 8, 10, 2, 3]]}
    await _run(db, "r1", "agressif", {"niveaux": [], "module_quinte": module})
    await db.commit()
    q = await _quinte_palmares(db)
    assert q["nb_tickets"] == 5 and q["nb_courses"] == 1
    assert q["mise_totale"] == pytest.approx(10.0)
    # Ordre (ticket joué dans l'ordre d'arrivée), deux Bonus 4sur5, un Bonus 3.
    assert q["nb_tickets_gagnants"] == 4
    assert q["retour"] == pytest.approx(2 * 4703.3 + 2 * 2 * 2.4 + 2 * 2.1, abs=0.01)
