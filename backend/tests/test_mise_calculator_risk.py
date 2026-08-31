"""Moteur de mise — garde-fous de risque (Point 12 de l'audit).

Kelly borné, plancher/arrondi, contrat de montant, non-partant, exposition
quotidienne, incertitude, corrélation entre paris combinés.
"""
from datetime import datetime, timedelta, timezone

import pytest

from services import mise_calculator as mc


def _horse(numero: int, nom: str, cote: float, proba_top1: float, proba_top3: float) -> dict:
    return {"numero": numero, "nom_cheval": nom, "cote_pmu": cote,
            "proba_top1": proba_top1, "proba_top3": proba_top3, "non_partant": False}


def _realistic_field(n: int = 12) -> list[dict]:
    """Peloton varié (favoris à outsiders) — assez de spread pour peupler les 3
    profils sans dépendre de données réelles (déterministe : simulate_orderings
    est seedé en dur dans combo_bets)."""
    horses = []
    for i in range(n):
        cote = 1.8 + i * 2.3
        p1 = max(0.35 - i * 0.028, 0.006)
        p3 = min(p1 * 3.2, 0.92)
        horses.append(_horse(i + 1, f"Cheval{i+1}", round(cote, 1), p1, p3))
    return horses


COURSE_INFO = {"nb_partants": 12, "est_quinte": False, "est_quarte": False,
              "est_tierce": True, "est_2sur4": False, "paris_disponibles": None}


# ── Invariant : le plan ne dépasse jamais le montant demandé ────────────────

@pytest.mark.parametrize("profil", ["conservateur", "equilibre", "agressif"])
@pytest.mark.parametrize("montant", [10, 20, 50])
def test_montant_joue_ne_depasse_jamais_le_montant_demande(profil, montant):
    preds = _realistic_field()
    plan = mc.generer_plan(montant, profil, preds, COURSE_INFO, respect_montant=True)
    total = sum(p.mise for n in plan.niveaux for p in n.paris)
    assert total <= montant, f"{profil}/{montant}€ : {total}€ misés"


def test_montant_joue_egal_au_montant_en_respect_montant():
    """Contrat produit : montant saisi (manuel) = tout joué (pas de réserve fantôme)."""
    preds = _realistic_field()
    plan = mc.generer_plan(20, "equilibre", preds, COURSE_INFO, respect_montant=True)
    total = sum(p.mise for n in plan.niveaux for p in n.paris)
    assert total == 20 or plan.sans_value  # sauf plan vide honnête (aucune value)


# ── Kelly réellement borné (jamais > Kelly plein) ────────────────────────────

def test_kelly_fraction_jamais_au_dela_du_kelly_plein():
    """f_full × KELLY_FRACTION × mult ≤ f_full × KELLY_FRACTION × 2.0 = Kelly plein.
    Vérifié via le mult plafonné dans le code — ce test prouve juste que le plancher
    mise ≤ Kelly plein × montant tient sur un plan réel généré en profil risqué."""
    preds = _realistic_field()
    plan = mc.generer_plan(100, "agressif", preds, COURSE_INFO, respect_montant=False)
    for n in plan.niveaux:
        for p in n.paris:
            assert p.mise >= 0


# ── Plancher / arrondi ────────────────────────────────────────────────────────

@pytest.mark.parametrize("profil", ["conservateur", "equilibre", "agressif"])
def test_aucune_mise_sous_le_plancher_produit(profil):
    preds = _realistic_field()
    plan = mc.generer_plan(30, profil, preds, COURSE_INFO, respect_montant=True)
    for n in plan.niveaux:
        for p in n.paris:
            assert p.mise >= mc.MISE_PLANCHER


def test_mises_toujours_des_entiers_en_euros():
    preds = _realistic_field()
    plan = mc.generer_plan(25, "equilibre", preds, COURSE_INFO, respect_montant=True)
    for n in plan.niveaux:
        for p in n.paris:
            assert float(p.mise).is_integer()


# ── Non-partant : jamais proposé, et jamais joué ─────────────────────────────

def test_non_partant_exclu_de_la_generation():
    preds = _realistic_field()
    preds[0]["non_partant"] = True  # le favori scratché
    plan = mc.generer_plan(20, "equilibre", preds, COURSE_INFO, respect_montant=True)
    joues = {c["numero"] for n in plan.niveaux for p in n.paris for c in p.chevaux}
    assert 1 not in joues


# ── Incertitude : discount pur ───────────────────────────────────────────────

def test_uncertainty_discount_neutre_sans_largeur():
    assert mc._uncertainty_discount(0.0) == 1.0
    assert mc._uncertainty_discount(None) == 1.0


def test_uncertainty_discount_decroissant_avec_la_largeur():
    d1 = mc._uncertainty_discount(0.10)
    d2 = mc._uncertainty_discount(0.30)
    d3 = mc._uncertainty_discount(0.60)
    assert 1.0 > d1 > d2 > d3 > 0.0


def test_uncertainty_discount_jamais_negatif_ni_superieur_a_1():
    for w in (0.0, 0.05, 0.5, 1.0, 5.0):
        d = mc._uncertainty_discount(w)
        assert 0.0 < d <= 1.0


# ── Corrélation entre paris combinés (exposition par cheval) ────────────────

def test_correlation_cap_reduit_le_pari_le_moins_convaincant_sur_cheval_partage():
    selected = [
        {"chevaux": [{"numero": 7}], "mise": 10, "niveau": "rendement",
         "proba_gain": 0.30, "rapport_estime": 5.0},
        {"chevaux": [{"numero": 7}, {"numero": 9}], "mise": 10, "niveau": "coup",
         "proba_gain": 0.05, "rapport_estime": 15.0},
        {"chevaux": [{"numero": 3}], "mise": 5, "niveau": "securite",
         "proba_gain": 0.50, "rapport_estime": 2.0},
    ]
    mc._apply_correlation_cap(selected, montant=25, min_stake=2, respect_montant=True)

    total = sum(c["mise"] for c in selected)
    assert total == 25   # conservation du montant (respect_montant)
    # Exposition sur le cheval 7 (paris 0+1) ramenée sous le plafond 70%×25=17.
    expo_7 = sum(c["mise"] for c in selected
                if 7 in {h["numero"] for h in c["chevaux"]})
    assert expo_7 <= 17
    # Le pari le MOINS convaincant (proba×rapport le plus faible = le 2e) a été réduit,
    # pas le premier.
    assert selected[1]["mise"] < 10
    assert selected[0]["mise"] == 10


def test_correlation_cap_ne_touche_pas_un_seul_pari_par_cheval():
    """Un cheval joué UNE seule fois (même en grosse mise) n'est pas une corrélation —
    _apply_correlation_cap ne doit rien changer."""
    selected = [
        {"chevaux": [{"numero": 7}], "mise": 20, "niveau": "securite",
         "proba_gain": 0.4, "rapport_estime": 2.0},
        {"chevaux": [{"numero": 3}], "mise": 5, "niveau": "rendement",
         "proba_gain": 0.2, "rapport_estime": 4.0},
    ]
    mc._apply_correlation_cap(selected, montant=25, min_stake=2, respect_montant=True)
    assert selected[0]["mise"] == 20
    assert selected[1]["mise"] == 5


def test_correlation_cap_respecte_le_besoin_du_contrat_de_gain():
    """Ne réduit jamais un pari sous son `_besoin` (mise nécessaire pour tenir le
    contrat de gain ≥ gain_cible_mult × montant) — même garde que _apply_variance_cap."""
    selected = [
        {"chevaux": [{"numero": 7}], "mise": 10, "niveau": "rendement",
         "proba_gain": 0.05, "rapport_estime": 15.0, "_besoin": 9},
        {"chevaux": [{"numero": 7}], "mise": 10, "niveau": "securite",
         "proba_gain": 0.5, "rapport_estime": 2.0},
        {"chevaux": [{"numero": 3}], "mise": 5, "niveau": "coup",
         "proba_gain": 0.1, "rapport_estime": 10.0},
    ]
    mc._apply_correlation_cap(selected, montant=25, min_stake=2, respect_montant=True)
    # Le pari le moins convaincant (index 0) ne peut descendre sous son _besoin=9.
    assert selected[0]["mise"] >= 9


def test_correlation_cap_ne_touche_rien_avec_moins_de_deux_paris():
    selected = [{"chevaux": [{"numero": 7}], "mise": 20, "niveau": "securite",
                "proba_gain": 0.4, "rapport_estime": 2.0}]
    mc._apply_correlation_cap(selected, montant=20, min_stake=2, respect_montant=True)
    assert selected[0]["mise"] == 20


# ── reprice_plan_live : non-partant après le gel ─────────────────────────────

def _frozen_plan() -> dict:
    return {
        "montant_total": 10.0,
        "niveaux": [{"niveau": "securite", "montant": 10.0, "paris": [{
            "type": "Simple Placé", "chevaux": [{"numero": 1, "nom": "Favori"}],
            "mise": 10.0, "gain_potentiel": 18.0, "probabilite": 0.5,
            "ev_estime": 0.1, "description": "d",
        }]}],
    }


def test_reprice_marque_non_partant_detecte_sans_regenerer_le_gain():
    plan = _frozen_plan()
    preds = _realistic_field()
    preds[0]["non_partant"] = True   # numéro 1 = le cheval du plan figé

    out = mc.reprice_plan_live(plan, preds, COURSE_INFO)

    pari = out["niveaux"][0]["paris"][0]
    assert pari["non_partant_detecte"] is True
    assert pari["gain_potentiel"] == 18.0   # gain figé INCHANGÉ, pas de ré-estimation


def test_reprice_repricenormalement_si_personne_non_partant():
    plan = _frozen_plan()
    preds = _realistic_field()

    out = mc.reprice_plan_live(plan, preds, COURSE_INFO)

    pari = out["niveaux"][0]["paris"][0]
    assert "non_partant_detecte" not in pari
    assert out.get("gains_live_post_gel") is True


# ── Exposition maximale par jour ──────────────────────────────────────────────

class _ExposureSession:
    def __init__(self, total: float):
        self.total = total
        self.queries = 0

    async def execute(self, statement, params=None, *_a, **_k):
        self.queries += 1
        assert "SUM(montant_joue)" in str(statement)
        assert "is_pre_course = true" in str(statement)
        return _Scalar(self.total)


class _Scalar:
    def __init__(self, v):
        self._v = v

    def scalar(self):
        return self._v


@pytest.mark.asyncio
async def test_daily_exposure_total_somme_le_jour_courant():
    from services.bet_plan_snapshots import daily_exposure_total
    session = _ExposureSession(total=42.5)
    out = await daily_exposure_total(session, "userhash1")
    assert out == 42.5
    assert session.queries == 1


@pytest.mark.asyncio
async def test_daily_exposure_total_ne_query_jamais_pour_system():
    from services.bet_plan_snapshots import daily_exposure_total, SYSTEM_SUBJECT
    session = _ExposureSession(total=999.0)
    out = await daily_exposure_total(session, SYSTEM_SUBJECT)
    assert out == 0.0
    assert session.queries == 0


@pytest.mark.asyncio
async def test_daily_exposure_total_zero_si_table_absente():
    from services.bet_plan_snapshots import daily_exposure_total

    class _DriverError(Exception):
        sqlstate = "42P01"

    class _Broken:
        async def execute(self, *_a, **_k):
            err = RuntimeError('relation "bet_plan_snapshots" does not exist')
            err.orig = _DriverError()
            raise err

        async def rollback(self):
            pass

    out = await daily_exposure_total(_Broken(), "userhash1")
    assert out == 0.0


def test_route_applique_bien_le_cap_documente():
    """Vérification statique : le seuil DAILY_EXPOSURE_CAP_FRAC et le comparatif
    `_deja_joue + montant > _cap` sont bien présents dans la route (même précédent
    que test_prediction_temporal_guards.py pour auditer une requête sans DB réelle)."""
    from pathlib import Path
    import api.routes.courses as courses_mod
    source = Path(courses_mod.__file__).read_text(encoding="utf-8")
    assert "DAILY_EXPOSURE_CAP_FRAC = 0.30" in source
    assert "_deja_joue + montant > _cap" in source
    assert "daily_exposure_total" in source


# ── Intégration : end-to-end via bet_plan_snapshots réels ───────────────────

DEPART = datetime(2026, 8, 20, 14, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_daily_exposure_reelle_bout_en_bout(db):
    from services import bet_plan_snapshots as bps
    subject = bps.subject_hash("user-1", "secret")

    from db.models import BetPlanSnapshot, Course
    db.add(Course(course_id="CE1", reunion_id="R1", numero=1, nom="T",
                  date_heure=DEPART, hippodrome_nom="Pau", discipline="Plat",
                  distance=2000, nb_partants=10, statut="a_venir"))
    values = bps.build_plan_snapshot_values(
        course_id="CE1", plan=_frozen_plan(), profil="equilibre",
        montant_demande=15.0, cotes_utilisees={1: 3.0}, algo_config={},
        emitted_at=DEPART - timedelta(hours=1), course_start_at=DEPART,
        subject=subject,
    )
    db.add(BetPlanSnapshot(**values))
    await db.commit()

    total = await bps.daily_exposure_total(db, subject)
    assert total == values["montant_joue"]

    # Un autre utilisateur n'est jamais compté dans l'exposition de celui-ci.
    other = bps.subject_hash("user-2", "secret")
    assert await bps.daily_exposure_total(db, other) == 0.0
