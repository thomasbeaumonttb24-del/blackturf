"""Règles produit du quota quotidien des plans de mise (essai gratuit Free/
Découverte confirmé par Thomas le 2026-08-16 : 1/jour, pas 2 — le calculateur
était auparavant bloqué à 403 total pour ces plans, cf. MISE_PLAN_DAILY_LIMITS
dans api/routes/courses.py).

Grille arrêtée par Thomas le 2026-08-16 : Free 1/jour, Standard 5/jour, Expert
illimité — sur le classement IA COMME sur le plan de mise."""
from types import SimpleNamespace

import pytest

from api.routes import courses


@pytest.fixture
def redis(monkeypatch):
    import fakeredis
    from services import quota_classement

    r = fakeredis.FakeAsyncRedis()

    async def _get():
        return r

    monkeypatch.setattr(quota_classement, "_redis", _get)
    return r


@pytest.mark.asyncio
@pytest.mark.parametrize("plan,limit", [("standard", 5), ("starter", 5)])
async def test_mise_plan_daily_limits(redis, plan, limit):
    user = SimpleNamespace(user_id="user-1", email="u@exemple.fr", plan=plan, is_admin=False)

    for index in range(limit):
        allowed, remaining, configured_limit = await courses._mise_plan_quota_check(user, f"course-{index}")
        assert allowed is True
        assert remaining == limit - index - 1
        assert configured_limit == limit

    allowed, remaining, configured_limit = await courses._mise_plan_quota_check(user, "course-over")
    assert (allowed, remaining, configured_limit) == (False, 0, limit)


@pytest.mark.asyncio
@pytest.mark.parametrize("plan", ["free", "decouverte"])
async def test_gratuit_seulement_sur_la_course_revelee(redis, plan):
    """Compte gratuit : le plan de mise suit la course dont le classement a été
    révélé, et ne consomme JAMAIS la course du jour à lui seul."""
    from services import quota_classement

    user = SimpleNamespace(user_id="user-1", email="g@exemple.fr", plan=plan, is_admin=False)
    assert (await courses._mise_plan_quota_check(user, "course-1"))[0] is False
    assert (await quota_classement.etat(user))["restant"] == 1  # rien consommé
    await quota_classement.consommer(user, "course-1")
    assert (await courses._mise_plan_quota_check(user, "course-1"))[0] is True
    assert (await courses._mise_plan_quota_check(user, "course-2"))[0] is False


@pytest.mark.asyncio
async def test_same_course_does_not_consume_quota_twice(redis):
    user = SimpleNamespace(user_id="user-1", email="u@exemple.fr", plan="standard", is_admin=False)

    first = await courses._mise_plan_quota_check(user, "course-1")
    refreshed = await courses._mise_plan_quota_check(user, "course-1")

    assert first == (True, 4, 5)
    assert refreshed == (True, 4, 5)


@pytest.mark.asyncio
async def test_expert_is_unlimited():
    user = SimpleNamespace(user_id="user-1", plan="expert", is_admin=False)
    assert await courses._mise_plan_quota_check(user, "course-1") == (True, -1, -1)


# ── Cohérence des deux grilles ──────────────────────────────────────────────
# Les quotas vivent dans DEUX fichiers (classement IA dans predictions.py, plan de
# mise dans courses.py). Ils ont divergé sans que personne ne le voie (Free 2 vs 1,
# Standard 6 vs 6 alors que le commentaire annonçait 1 et 5) : un compte Free
# pouvait ouvrir le classement de 2 courses mais le plan de mise d'une seule.
# Ces tests figent la grille produit et interdisent une nouvelle dérive silencieuse.

def test_grille_produit_exacte():
    from api.routes import predictions

    attendu = {"free": 1, "decouverte": 1, "standard": 5, "starter": 5}
    assert courses.MISE_PLAN_DAILY_LIMITS == attendu
    assert predictions.PRONO_DAILY_LIMITS == attendu


def test_les_deux_grilles_restent_alignees():
    """Free doit voir le classement ET le plan de mise de la MÊME course."""
    from api.routes import predictions

    assert courses.MISE_PLAN_DAILY_LIMITS == predictions.PRONO_DAILY_LIMITS


def test_expert_absent_des_deux_grilles():
    """Illimité = absent de la table (le code renvoie -1 quand la clé manque).
    Un « expert: 999 » ajouté par mégarde le rendrait limité."""
    from api.routes import predictions

    for table in (courses.MISE_PLAN_DAILY_LIMITS, predictions.PRONO_DAILY_LIMITS):
        assert "expert" not in table
        assert "pro" not in table
