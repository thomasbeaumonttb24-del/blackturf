"""Règles produit du quota quotidien des plans de mise (essai gratuit Free/
Découverte confirmé par Thomas le 2026-08-16 : 1/jour, pas 2 — le calculateur
était auparavant bloqué à 403 total pour ces plans, cf. MISE_PLAN_DAILY_LIMITS
dans api/routes/courses.py)."""
from types import SimpleNamespace

import pytest

from api.routes import courses


class FakeRedis:
    def __init__(self):
        self.values: dict[str, set[str]] = {}

    async def sismember(self, key, value):
        return value in self.values.get(key, set())

    async def scard(self, key):
        return len(self.values.get(key, set()))

    async def sadd(self, key, value):
        self.values.setdefault(key, set()).add(value)

    async def expire(self, key, ttl):
        return True


@pytest.mark.asyncio
@pytest.mark.parametrize("plan,limit", [("free", 1), ("decouverte", 1), ("standard", 6), ("starter", 6)])
async def test_mise_plan_daily_limits(monkeypatch, plan, limit):
    redis = FakeRedis()

    async def fake_get_redis():
        return redis

    monkeypatch.setattr(courses, "get_redis", fake_get_redis)
    user = SimpleNamespace(user_id="user-1", plan=plan, is_admin=False)

    for index in range(limit):
        allowed, remaining, configured_limit = await courses._mise_plan_quota_check(user, f"course-{index}")
        assert allowed is True
        assert remaining == limit - index - 1
        assert configured_limit == limit

    allowed, remaining, configured_limit = await courses._mise_plan_quota_check(user, "course-over")
    assert (allowed, remaining, configured_limit) == (False, 0, limit)


@pytest.mark.asyncio
async def test_same_course_does_not_consume_quota_twice(monkeypatch):
    redis = FakeRedis()

    async def fake_get_redis():
        return redis

    monkeypatch.setattr(courses, "get_redis", fake_get_redis)
    user = SimpleNamespace(user_id="user-1", plan="free", is_admin=False)

    first = await courses._mise_plan_quota_check(user, "course-1")
    refreshed = await courses._mise_plan_quota_check(user, "course-1")

    assert first == (True, 0, 1)
    assert refreshed == (True, 0, 1)


@pytest.mark.asyncio
async def test_expert_is_unlimited():
    user = SimpleNamespace(user_id="user-1", plan="expert", is_admin=False)
    assert await courses._mise_plan_quota_check(user, "course-1") == (True, -1, -1)
