import pytest
from fastapi.testclient import TestClient

from agent_platform.api import main as main_mod
from agent_platform.api.main import app, get_engine_context, get_idempotency_store
from agent_platform.core import redis as redismod
from agent_platform.core.config import Settings
from agent_platform.core.idempotency import PREFIX, IdempotencyStore


def _store(**overrides) -> IdempotencyStore:
    return IdempotencyStore(Settings(idempotency_ttl_seconds=600, **overrides))


def test_key_for_ignores_derived_key_by_default():
    store = _store()
    assert store.key_for(app_uuid="a", user="u", conversation_id="c", query="q") == ""
    assert store.key_for(app_uuid="a", explicit="k1") == PREFIX + "k1"
    assert store.key_for(app_uuid="a", explicit="  ") == ""


def test_key_for_derives_when_enabled():
    store = _store(idempotency_derive_key=True)
    assert store.key_for(app_uuid="a", user="u", conversation_id="c", query="q") == PREFIX + "a|u|c|q"
    assert store.key_for(app_uuid="a", user="u", conversation_id="c", query="q", explicit="k1") == PREFIX + "k1"


def test_disabled_store_never_holds():
    store = IdempotencyStore(Settings(idempotency_ttl_seconds=0, idempotency_derive_key=True))
    key = store.key_for(app_uuid="a", query="q")
    assert key
    assert store.acquire(key).hit is False
    store.complete(key, {"answer": "x"})
    assert store.acquire(key).hit is False


def test_acquire_blocks_until_completed():
    store = _store()
    key = store.key_for(app_uuid="a", explicit="k")

    assert store.acquire(key).hit is False
    second = store.acquire(key)
    assert second.in_flight is True
    assert second.replay is None

    store.complete(key, {"conversation_id": "c", "message_id": "m", "answer": "hi"})
    third = store.acquire(key)
    assert third.replay == {"conversation_id": "c", "message_id": "m", "answer": "hi"}
    assert third.in_flight is False


def test_release_frees_key():
    store = _store()
    key = store.key_for(app_uuid="a", explicit="k")
    store.acquire(key)
    store.release(key)
    assert store.acquire(key).hit is False


def test_expired_lock_is_reacquirable():
    store = _store()
    key = store.key_for(app_uuid="a", explicit="k")
    store.acquire(key)
    value, _ = redismod._memory_values[key]
    redismod._memory_values[key] = (value, 0.0)
    assert store.acquire(key).hit is False


def test_unparsable_payload_is_treated_as_in_flight():
    store = _store()
    key = store.key_for(app_uuid="a", explicit="k")
    redismod.set_value(key, "{", 600)
    assert store.acquire(key).in_flight is True


@pytest.fixture()
def idem_client(engine_ctx, seed_app):
    app_uuid, api_key = seed_app()
    app.dependency_overrides[get_engine_context] = lambda: engine_ctx
    app.dependency_overrides[get_idempotency_store] = lambda: _store()
    with TestClient(app) as client:
        yield client, app_uuid, api_key
    app.dependency_overrides.clear()


def _fake_stream(calls: list[str], answer: str = "回答"):
    async def stream(graph_def, inputs, ctx, checkpointer=None, thread_id=None):
        calls.append(inputs["query"])
        yield {"type": "final", "answer": answer, "state": {"variables": {}}}

    return stream


def test_same_key_replays_without_rerunning(idem_client, monkeypatch):
    client, _, api_key = idem_client
    calls: list[str] = []
    monkeypatch.setattr(main_mod, "stream_graph", _fake_stream(calls))
    headers = {"Api-Key": api_key, "Idempotency-Key": "abc"}

    first = client.post("/v1/chat-messages", json={"query": "q"}, headers=headers)
    second = client.post("/v1/chat-messages", json={"query": "q"}, headers=headers)

    assert calls == ["q"]
    assert first.status_code == second.status_code == 200
    assert second.text.count('"event": "message_end"') == 1
    assert "回答" in second.text


def test_body_key_is_honoured(idem_client, monkeypatch):
    client, _, api_key = idem_client
    calls: list[str] = []
    monkeypatch.setattr(main_mod, "stream_graph", _fake_stream(calls))
    payload = {"query": "q", "idempotency_key": "abc"}

    client.post("/v1/chat-messages", json=payload, headers={"Api-Key": api_key})
    client.post("/v1/chat-messages", json=payload, headers={"Api-Key": api_key})

    assert calls == ["q"]


def test_without_key_every_request_runs(idem_client, monkeypatch):
    client, _, api_key = idem_client
    calls: list[str] = []
    monkeypatch.setattr(main_mod, "stream_graph", _fake_stream(calls))

    client.post("/v1/chat-messages", json={"query": "q"}, headers={"Api-Key": api_key})
    client.post("/v1/chat-messages", json={"query": "q"}, headers={"Api-Key": api_key})

    assert calls == ["q", "q"]


def test_distinct_keys_run_separately(idem_client, monkeypatch):
    client, _, api_key = idem_client
    calls: list[str] = []
    monkeypatch.setattr(main_mod, "stream_graph", _fake_stream(calls))

    client.post("/v1/chat-messages", json={"query": "q"}, headers={"Api-Key": api_key, "Idempotency-Key": "a"})
    client.post("/v1/chat-messages", json={"query": "q"}, headers={"Api-Key": api_key, "Idempotency-Key": "b"})

    assert calls == ["q", "q"]


def test_in_flight_key_returns_error_event(idem_client, monkeypatch):
    client, app_uuid, api_key = idem_client
    calls: list[str] = []
    monkeypatch.setattr(main_mod, "stream_graph", _fake_stream(calls))

    occupied = _store()
    occupied.acquire(occupied.key_for(app_uuid=app_uuid, explicit="abc"))

    response = client.post(
        "/v1/chat-messages", json={"query": "q"}, headers={"Api-Key": api_key, "Idempotency-Key": "abc"}
    )

    assert calls == []
    assert main_mod.IN_FLIGHT_REPLY in response.text


def test_failed_run_releases_key(idem_client, monkeypatch):
    client, _, api_key = idem_client
    calls: list[str] = []

    async def boom(graph_def, inputs, ctx, checkpointer=None, thread_id=None):
        calls.append(inputs["query"])
        raise RuntimeError("model down")
        yield  # pragma: no cover

    monkeypatch.setattr(main_mod, "stream_graph", boom)
    headers = {"Api-Key": api_key, "Idempotency-Key": "abc"}

    first = client.post("/v1/chat-messages", json={"query": "q"}, headers=headers)
    assert "model down" in first.text

    monkeypatch.setattr(main_mod, "stream_graph", _fake_stream(calls))
    second = client.post("/v1/chat-messages", json={"query": "q"}, headers=headers)

    assert calls == ["q", "q"]
    assert "回答" in second.text
