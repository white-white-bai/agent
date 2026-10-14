import asyncio

import pytest
from fastapi.testclient import TestClient

from agent_platform.api import main as main_mod
from agent_platform.api.main import app, get_concurrency_limiter, get_engine_context
from agent_platform.core import redis as redismod
from agent_platform.core.concurrency import PREFIX, ConcurrencyLimiter
from agent_platform.core.config import Settings


def _limiter(**overrides) -> ConcurrencyLimiter:
    return ConcurrencyLimiter(Settings(max_concurrency_per_app=1, **overrides))


def test_disabled_limiter_always_allows():
    limiter = ConcurrencyLimiter(Settings(max_concurrency_per_app=0))
    assert limiter.acquire("app") is True
    assert limiter.acquire("app") is True
    limiter.release("app")


def test_rejects_over_limit_and_release_frees_slot():
    limiter = _limiter()
    assert limiter.acquire("app") is True
    assert limiter.acquire("app") is False
    limiter.release("app")
    assert limiter.acquire("app") is True


def test_limits_are_per_app():
    limiter = _limiter()
    assert limiter.acquire("app-1") is True
    assert limiter.acquire("app-2") is True
    assert limiter.acquire("app-1") is False


def test_slot_key_prefix_and_ttl():
    limiter = _limiter()
    limiter.acquire("app")
    count, expires = redismod._memory_counters[PREFIX + "app"]
    assert count == 1
    assert expires > 0


async def test_acquire_with_wait_gives_up_when_full():
    limiter = _limiter(concurrency_wait_seconds=0.25)
    assert limiter.acquire("app") is True
    assert await limiter.acquire_with_wait("app") is False


async def test_acquire_with_wait_succeeds_after_release():
    limiter = _limiter(concurrency_wait_seconds=2.0)
    assert limiter.acquire("app") is True

    async def release_later() -> None:
        await asyncio.sleep(0.3)
        limiter.release("app")

    task = asyncio.create_task(release_later())
    assert await limiter.acquire_with_wait("app") is True
    await task


@pytest.fixture()
def limited_client(engine_ctx, seed_app, monkeypatch):
    app_uuid, api_key = seed_app()
    limiter = _limiter()
    app.dependency_overrides[get_engine_context] = lambda: engine_ctx
    app.dependency_overrides[get_concurrency_limiter] = lambda: limiter
    with TestClient(app) as client:
        yield client, app_uuid, api_key, limiter
    app.dependency_overrides.clear()


def _fake_stream(calls: list[str]):
    async def stream(graph_def, inputs, ctx, checkpointer=None, thread_id=None):
        calls.append(inputs["query"])
        yield {"type": "final", "answer": "回答", "state": {"variables": {}}}

    return stream


def test_full_slot_rejects_request(limited_client, monkeypatch):
    client, app_uuid, api_key, limiter = limited_client
    calls: list[str] = []
    monkeypatch.setattr(main_mod, "stream_graph", _fake_stream(calls))
    limiter.acquire(app_uuid)

    response = client.post("/v1/chat-messages", json={"query": "q"}, headers={"Api-Key": api_key})

    assert calls == []
    assert main_mod.CONCURRENCY_REPLY in response.text


def test_slot_is_released_after_run(limited_client, monkeypatch):
    client, app_uuid, api_key, limiter = limited_client
    monkeypatch.setattr(main_mod, "stream_graph", _fake_stream([]))

    client.post("/v1/chat-messages", json={"query": "q"}, headers={"Api-Key": api_key})

    count, _ = redismod._memory_counters[PREFIX + app_uuid]
    assert count == 0
    assert limiter.acquire(app_uuid) is True


def test_slot_is_released_after_error(limited_client, monkeypatch):
    client, app_uuid, api_key, limiter = limited_client

    async def boom(graph_def, inputs, ctx, checkpointer=None, thread_id=None):
        raise RuntimeError("model down")
        yield  # pragma: no cover

    monkeypatch.setattr(main_mod, "stream_graph", boom)

    client.post("/v1/chat-messages", json={"query": "q"}, headers={"Api-Key": api_key})

    count, _ = redismod._memory_counters[PREFIX + app_uuid]
    assert count == 0
    assert limiter.acquire(app_uuid) is True


def test_guard_rejection_also_releases_slot(limited_client, monkeypatch):
    client, app_uuid, api_key, _limiter_instance = limited_client
    calls: list[str] = []
    monkeypatch.setattr(main_mod, "stream_graph", _fake_stream(calls))

    from agent_platform.core.guards import GuardDecision

    class _Rejecting:
        def pre_check(self, **kwargs):
            return GuardDecision(allowed=False, reply="不聊这个", guard="sensitive")

    app.dependency_overrides[main_mod.get_guard_chain] = lambda: _Rejecting()
    try:
        response = client.post("/v1/chat-messages", json={"query": "q"}, headers={"Api-Key": api_key})
    finally:
        app.dependency_overrides.pop(main_mod.get_guard_chain, None)

    assert calls == []
    assert "不聊这个" in response.text
    count, _ = redismod._memory_counters[PREFIX + app_uuid]
    assert count == 0
