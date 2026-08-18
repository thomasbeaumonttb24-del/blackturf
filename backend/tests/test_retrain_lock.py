"""Un seul entraînement lourd peut s'exécuter à la fois."""

import pytest

from ml import pipeline


class _FakeAsyncRedis:
    def __init__(self, *, acquired=True):
        self.acquired = acquired
        self.set_calls = []
        self.eval_calls = []

    async def set(self, key, value, *, ex, nx):
        self.set_calls.append((key, value, ex, nx))
        return self.acquired

    async def eval(self, script, nkeys, key, token):
        self.eval_calls.append((script, nkeys, key, token))
        return 1


@pytest.mark.asyncio
async def test_retrain_executes_and_releases_owned_lease(monkeypatch):
    redis = _FakeAsyncRedis(acquired=True)

    async def _get_redis():
        return redis

    monkeypatch.setattr("db.redis_client.get_redis", _get_redis)
    calls = []

    async def _runner():
        calls.append("ran")

    assert await pipeline._run_retraining_with_lease("test", _runner) is True
    assert calls == ["ran"]
    assert redis.set_calls[0][2:] == (pipeline.RETRAIN_LEASE_S, True)
    assert len(redis.eval_calls) == 1
    assert redis.eval_calls[0][2] == pipeline._RETRAIN_LEASE_KEY


@pytest.mark.asyncio
async def test_concurrent_retrain_is_skipped(monkeypatch):
    redis = _FakeAsyncRedis(acquired=False)

    async def _get_redis():
        return redis

    monkeypatch.setattr("db.redis_client.get_redis", _get_redis)
    called = False

    async def _runner():
        nonlocal called
        called = True

    assert await pipeline._run_retraining_with_lease("test", _runner) is False
    assert called is False
    assert redis.eval_calls == []


@pytest.mark.asyncio
async def test_redis_failure_is_fail_closed(monkeypatch):
    async def _get_redis():
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr("db.redis_client.get_redis", _get_redis)
    called = False

    async def _runner():
        nonlocal called
        called = True

    assert await pipeline._run_retraining_with_lease("test", _runner) is False
    assert called is False


@pytest.mark.asyncio
async def test_lease_is_released_when_training_fails(monkeypatch):
    redis = _FakeAsyncRedis(acquired=True)

    async def _get_redis():
        return redis

    monkeypatch.setattr("db.redis_client.get_redis", _get_redis)

    async def _runner():
        raise RuntimeError("training failed")

    with pytest.raises(RuntimeError, match="training failed"):
        await pipeline._run_retraining_with_lease("test", _runner)
    assert len(redis.eval_calls) == 1
