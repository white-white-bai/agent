"""用户级长期记忆：存储、召回、抽取、默认关闭与资源隔离。"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from agent_platform.api import main as main_mod
from agent_platform.api import services
from agent_platform.api.main import app, get_engine_context
from agent_platform.core.config import Settings
from agent_platform.core.db import session_scope
from agent_platform.domain.models import Conversation, Message
from agent_platform.engine.context import EngineContext
from agent_platform.knowledge.embeddings import Embedder
from agent_platform.memory import store
from agent_platform.memory.extract import dispatch_extract, extract_user_memory
from agent_platform.memory.recall import recall, render_memory_text


class MemoryLLM:
    def __init__(self, reply: object = "[]", *, fail: bool = False) -> None:
        self.reply = reply
        self.fail = fail
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("llm down")
        return self.reply


def _settings(**overrides) -> Settings:
    data = {
        "embedding_dim": 16,
        "user_memory_scope": "app",
        "user_memory_max_per_user": 20,
        "user_memory_max_chars": 4000,
        "user_memory_top_k": 5,
        "user_memory_score_threshold": 0.1,
        "user_memory_extract_async": False,
    }
    data.update(overrides)
    return Settings(**data)


def _seed_conversation(tenant="t", app_uuid="app-1", user="u1", conversation_id="conv-1") -> str:
    with session_scope() as session:
        row = Conversation(
            uuid=uuid.uuid4().hex,
            tenant_code=tenant,
            app_uuid=app_uuid,
            conversation_id=conversation_id,
            user_name=user,
        )
        session.add(row)
        session.flush()
        return row.uuid


def _add_message(conversation_uuid: str, role: str, query: str = "", answer: str = "") -> int:
    with session_scope() as session:
        row = Message(
            uuid=uuid.uuid4().hex,
            conversation_uuid=conversation_uuid,
            message_id=uuid.uuid4().hex,
            role=role,
            query=query,
            answer=answer,
        )
        session.add(row)
        session.flush()
        return row.id


def test_upsert_dedups_and_keeps_scope_isolation():
    settings = _settings()
    first = store.upsert_memory(
        tenant_code="t",
        app_uuid="a1",
        user_key="u1",
        kind="preference",
        content="喜欢简洁回答",
        importance=0.4,
        embedding=[1.0] * 16,
        embedding_model="hash:16",
        settings=settings,
    )
    second = store.upsert_memory(
        tenant_code="t",
        app_uuid="a1",
        user_key="u1",
        kind="preference",
        content="喜欢简洁回答",
        importance=0.9,
        embedding=[1.0] * 16,
        embedding_model="hash:16",
        settings=settings,
    )
    store.upsert_memory(
        tenant_code="t",
        app_uuid="a2",
        user_key="u1",
        kind="fact",
        content="住在常州",
        embedding=[1.0] * 16,
        embedding_model="hash:16",
        settings=settings,
    )
    store.upsert_memory(
        tenant_code="t",
        app_uuid="a1",
        user_key="u2",
        kind="fact",
        content="住在南京",
        embedding=[1.0] * 16,
        embedding_model="hash:16",
        settings=settings,
    )

    assert first.uuid == second.uuid
    rows, total = store.list_memories("t", user_key="u1", app_uuid="a1")
    assert total == 1
    assert rows[0].importance == 0.9
    assert len(store.list_memories("t")[0]) == 3


def test_aggregate_user_memories_by_app(api_client):
    settings = _settings()
    store.create_memory(
        tenant_code="t", app_uuid="a1", user_key="u1", kind="fact", content="应用一记忆", settings=settings
    )
    store.create_memory(
        tenant_code="t", app_uuid="a2", user_key="u1", kind="fact", content="应用二记忆", settings=settings
    )

    response = api_client.get(
        "/admin/user-memories/aggregate", params={"user_key": "u1", "tenant_code": "t"}
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 2
    assert {(item["app_uuid"], item["count"]) for item in data["apps"]} == {("a1", 1), ("a2", 1)}


def test_import_exported_memories(api_client):
    settings = _settings()
    store.create_memory(
        tenant_code="t", app_uuid="a1", user_key="u1", kind="fact", content="导出内容", settings=settings
    )
    exported = api_client.get(
        "/admin/user-memories/export", params={"tenant_code": "t", "user_key": "u1"}
    ).json()["data"]

    response = api_client.post(
        "/admin/user-memories/import",
        json={
            "tenant_code": "t",
            "target_user_key": "u-imported",
            "target_app_uuid": "b1",
            "items": exported["items"],
        },
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"imported": 1, "skipped": 0, "total": 1}
    assert store.list_memories("t", user_key="u-imported", app_uuid="b1")[1] == 1


def test_export_and_migrate_user_memories(api_client):
    settings = _settings()
    store.create_memory(
        tenant_code="t", app_uuid="a1", user_key="u1", kind="fact", content="应用一", settings=settings
    )
    store.create_memory(
        tenant_code="t", app_uuid="a2", user_key="u1", kind="preference", content="应用二", settings=settings
    )

    exported = api_client.get(
        "/admin/user-memories/export", params={"tenant_code": "t", "user_key": "u1"}
    )
    assert exported.status_code == 200
    assert exported.json()["data"]["total"] == 2

    migrated = api_client.post(
        "/admin/user-memories/migrate",
        json={
            "tenant_code": "t",
            "source_user_key": "u1",
            "target_user_key": "u2",
            "target_app_uuid": "b1",
        },
    )
    assert migrated.status_code == 200
    assert migrated.json()["data"] == {"exported": 2, "upserted": 2, "deleted": 0}
    assert store.list_memories("t", user_key="u2", app_uuid="b1")[1] == 2
    assert store.list_memories("t", user_key="u1")[1] == 2

    moved = api_client.post(
        "/admin/user-memories/migrate",
        json={
            "tenant_code": "t",
            "source_user_key": "u1",
            "target_user_key": "u3",
            "delete_source": True,
        },
    )
    assert moved.json()["data"]["deleted"] == 2
    assert store.list_memories("t", user_key="u1")[1] == 0
    assert store.list_memories("t", user_key="u3")[1] == 2

    cross = api_client.post(
        "/admin/user-memories/migrate",
        json={
            "tenant_code": "t",
            "target_tenant_code": "t2",
            "source_user_key": "u3",
            "target_user_key": "u4",
            "target_app_uuid": "c1",
        },
    )
    assert cross.status_code == 200
    assert store.list_memories("t2", user_key="u4", app_uuid="c1")[1] == 2
    assert store.list_memories("t", user_key="u3")[1] == 2


def test_upsert_near_duplicate_merges_by_cosine_threshold():
    settings = _settings(embedding_dim=2, user_memory_dedup_threshold=0.9)
    first = store.upsert_memory(
        tenant_code="t",
        app_uuid="a1",
        user_key="u1",
        kind="fact",
        content="喜欢简洁",
        embedding=[1.0, 0.0],
        embedding_model="hash:2",
        settings=settings,
    )
    second = store.upsert_memory(
        tenant_code="t",
        app_uuid="a1",
        user_key="u1",
        kind="fact",
        content="喜欢简洁回答",
        embedding=[0.99, 0.1],
        embedding_model="hash:2",
        settings=settings,
    )

    assert first.uuid == second.uuid
    rows, total = store.list_memories("t", user_key="u1", app_uuid="a1")
    assert total == 1
    assert rows[0].content == "喜欢简洁"


def test_upsert_below_threshold_inserts_new_row():
    settings = _settings(embedding_dim=2, user_memory_dedup_threshold=0.99)
    first = store.upsert_memory(
        tenant_code="t",
        app_uuid="a1",
        user_key="u1",
        kind="fact",
        content="喜欢简洁",
        embedding=[1.0, 0.0],
        embedding_model="hash:2",
        settings=settings,
    )
    second = store.upsert_memory(
        tenant_code="t",
        app_uuid="a1",
        user_key="u1",
        kind="fact",
        content="喜欢详细",
        embedding=[0.0, 1.0],
        embedding_model="hash:2",
        settings=settings,
    )

    assert first.uuid != second.uuid
    assert store.list_memories("t", user_key="u1", app_uuid="a1")[1] == 2


@pytest.mark.asyncio
async def test_recall_filters_stale_embedding_model():
    settings = _settings(embedding_dim=16)
    store.create_memory(
        tenant_code="t",
        app_uuid="a1",
        user_key="u1",
        kind="fact",
        content="旧模型记忆",
        embedding=[1.0] * 16,
        embedding_model="old:model",
        settings=settings,
    )
    current = "当前模型记忆"
    vector = await Embedder(settings).encode(current)
    store.create_memory(
        tenant_code="t",
        app_uuid="a1",
        user_key="u1",
        kind="fact",
        content=current,
        embedding=vector,
        embedding_model="hash:16",
        settings=settings,
    )

    hits = await recall(settings, tenant_code="t", app_uuid="a1", user_key="u1", query=current)

    assert [item["content"] for item in hits] == [current]


@pytest.mark.asyncio
async def test_rebuild_embeddings_updates_model():
    settings = _settings(embedding_dim=16)
    row = store.create_memory(
        tenant_code="t",
        app_uuid="a1",
        user_key="u1",
        kind="fact",
        content="需要重建",
        embedding=[0.0] * 16,
        embedding_model="old:model",
        settings=settings,
    )

    updated = await store.rebuild_embeddings(settings, "t", user_key="u1", app_uuid="a1")

    assert updated == 1
    refreshed = store.get_memory(row.uuid)
    assert refreshed.embedding_model == "hash:16"
    assert len(refreshed.embedding) == 16


@pytest.mark.asyncio
async def test_recall_only_returns_matching_user_and_app():
    settings = _settings()
    embedder = Embedder(settings)
    content = "喜欢简洁回答"
    vector = await embedder.encode(content)
    store.create_memory(
        tenant_code="t",
        app_uuid="a1",
        user_key="u1",
        kind="preference",
        content=content,
        embedding=vector,
        embedding_model="hash:16",
        settings=settings,
    )
    store.create_memory(
        tenant_code="t",
        app_uuid="a2",
        user_key="u1",
        kind="preference",
        content=content,
        embedding=vector,
        embedding_model="hash:16",
        settings=settings,
    )
    store.create_memory(
        tenant_code="t",
        app_uuid="a1",
        user_key="u2",
        kind="preference",
        content=content,
        embedding=vector,
        embedding_model="hash:16",
        settings=settings,
    )

    hits = await recall(settings, tenant_code="t", app_uuid="a1", user_key="u1", query=content)

    assert [item["content"] for item in hits] == [content]
    assert "仅作参考" in render_memory_text(hits)
    rows, _ = store.list_memories("t", user_key="u1", app_uuid="a1")
    assert rows[0].hit_count == 1


@pytest.mark.asyncio
async def test_extract_creates_memory_and_advances_watermark():
    conversation_uuid = _seed_conversation()
    _add_message(conversation_uuid, "user", query="我喜欢简洁回答")
    last_id = _add_message(conversation_uuid, "assistant", answer="好的，我会简洁回答")
    llm = MemoryLLM('[{"kind": "preference", "content": "用户喜欢简洁回答", "importance": 0.9}]')
    settings = _settings()

    result = await extract_user_memory(
        settings,
        tenant_code="t",
        app_uuid="app-1",
        user_key="u1",
        conversation_uuid=conversation_uuid,
        llm=llm,
    )

    assert result["created"] == 1
    rows, total = store.list_memories("t", user_key="u1", app_uuid="app-1")
    assert total == 1 and rows[0].content == "用户喜欢简洁回答"
    assert rows[0].embedding
    state = store.get_state("t", "u1", "app-1")
    assert state is not None and state.last_message_id == last_id

    again = await extract_user_memory(
        settings,
        tenant_code="t",
        app_uuid="app-1",
        user_key="u1",
        conversation_uuid=conversation_uuid,
        llm=llm,
    )
    assert again["created"] == 0
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_extract_failure_and_parse_error_do_not_advance_watermark():
    conversation_uuid = _seed_conversation()
    _add_message(conversation_uuid, "user", query="我喜欢简洁回答")
    settings = _settings()

    failed = await extract_user_memory(
        settings,
        tenant_code="t",
        app_uuid="app-1",
        user_key="u1",
        conversation_uuid=conversation_uuid,
        llm=MemoryLLM(fail=True),
    )
    assert failed["reason"] == "llm_error"
    assert store.get_state("t", "u1", "app-1") is None

    parsed = await extract_user_memory(
        settings,
        tenant_code="t",
        app_uuid="app-1",
        user_key="u1",
        conversation_uuid=conversation_uuid,
        llm=MemoryLLM("not json"),
    )
    assert parsed["reason"] == "parse_error"
    assert store.get_state("t", "u1", "app-1") is None


@pytest.mark.asyncio
async def test_dispatch_extract_sync_returns_sync():
    conversation_uuid = _seed_conversation()
    _add_message(conversation_uuid, "user", query="我喜欢简洁回答")
    settings = _settings(user_memory_extract_async=False)
    llm = MemoryLLM("[]")

    mode = await dispatch_extract(
        settings,
        tenant_code="t",
        app_uuid="app-1",
        user_key="u1",
        conversation_uuid=conversation_uuid,
        llm=llm,
    )

    assert mode == "sync"
    state = store.get_state("t", "u1", "app-1")
    assert state is not None


def _capture_stream(monkeypatch) -> list[dict]:
    seen: list[dict] = []

    async def fake_stream(graph_def, inputs, ctx, checkpointer=None, thread_id=None):
        seen.append(dict(inputs))
        yield {
            "type": "final",
            "answer": "回答",
            "state": {"variables": {"chunks": [{"content": "知识", "document_name": "doc"}]}},
        }

    monkeypatch.setattr(main_mod, "stream_graph", fake_stream)
    return seen


@pytest.fixture()
def memory_client(seed_app):
    app.dependency_overrides[get_engine_context] = lambda: EngineContext(llm=MemoryLLM("[]"))
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_chat_default_off_does_not_inject_memory(memory_client, seed_app, monkeypatch):
    seed_app(tenant_code="t", app_id="app-1", api_key="key-1")
    seen = _capture_stream(monkeypatch)
    monkeypatch.setattr(main_mod, "get_settings", lambda: Settings())

    response = memory_client.post(
        "/v1/chat-messages",
        json={"query": "你好", "user": "u1"},
        headers={"Api-Key": "key-1"},
    )

    assert response.status_code == 200
    assert "user_memory" not in seen[0]
    assert "user_memory_text" not in seen[0]


@pytest.mark.asyncio
async def test_chat_recall_injects_memory_but_not_retriever_resources(memory_client, seed_app, monkeypatch):
    app_uuid, _ = seed_app(tenant_code="t", app_id="app-1", api_key="key-1")
    settings = _settings(
        user_memory_enabled=True,
        user_memory_recall_enabled=True,
        user_memory_write_enabled=False,
    )
    vector = await Embedder(settings).encode("喜欢简洁回答")
    store.create_memory(
        tenant_code="t",
        app_uuid=app_uuid,
        user_key="u1",
        kind="preference",
        content="喜欢简洁回答",
        embedding=vector,
        embedding_model="hash:16",
        settings=settings,
    )
    seen = _capture_stream(monkeypatch)
    monkeypatch.setattr(main_mod, "get_settings", lambda: settings)

    response = memory_client.post(
        "/v1/chat-messages",
        json={"query": "喜欢简洁回答", "user": "u1"},
        headers={"Api-Key": "key-1"},
    )

    assert response.status_code == 200
    assert seen[0]["user_memory"][0]["content"] == "喜欢简洁回答"
    assert "喜欢简洁回答" in seen[0]["user_memory_text"]
    conversation = services.list_conversations(app_uuid, "u1")[0]
    messages = services.list_messages(conversation.conversation_id)
    assistant = [row for row in messages if row.role == "assistant"][-1]
    resources = assistant.answer_metadata.get("retriever_resources") or []
    assert all(item.get("content") != "喜欢简洁回答" for item in resources)


def test_admin_memory_crud_recall_and_config(api_client):
    created = api_client.post(
        "/admin/user-memories",
        json={
            "tenant_code": "t",
            "app_uuid": "a1",
            "user_key": "u1",
            "kind": "preference",
            "content": "喜欢简洁回答",
            "importance": 0.8,
        },
    )
    assert created.status_code == 200
    memory_uuid = created.json()["data"]["uuid"]

    listed = api_client.get("/admin/user-memories", params={"tenant_code": "t"}).json()["data"]
    assert listed["total"] == 1 and listed["items"][0]["content"] == "喜欢简洁回答"

    users = api_client.get("/admin/user-memories/users", params={"tenant_code": "t"}).json()["data"]
    assert users[0]["user_key"] == "u1"

    config = api_client.get("/admin/memory/config").json()["data"]
    assert config["enabled"] is False

    recall_resp = api_client.post(
        "/admin/user-memories/recall",
        json={"tenant_code": "t", "app_uuid": "a1", "user_key": "u1", "query": "喜欢简洁回答"},
    )
    assert recall_resp.status_code == 200
    assert recall_resp.json()["data"]["hits"][0]["content"] == "喜欢简洁回答"

    updated = api_client.put(
        f"/admin/user-memories/{memory_uuid}",
        json={"content": "用户偏好简洁", "kind": "preference", "importance": 0.9, "enabled": True},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["content"] == "用户偏好简洁"

    assert api_client.delete(f"/admin/user-memories/{memory_uuid}").status_code == 200
    assert api_client.get("/admin/user-memories", params={"tenant_code": "t"}).json()["data"]["total"] == 0
