import re
import uuid

import pytest
from fastapi.testclient import TestClient

from agent_platform.api import main as main_mod
from agent_platform.api import services
from agent_platform.api.main import app, get_engine_context
from agent_platform.core.config import Settings
from agent_platform.core.db import session_scope
from agent_platform.domain.models import App, Conversation, Graph, GraphVersion
from agent_platform.graph.schema import GraphDef

GRAPH_DEF = GraphDef.model_validate(
    {
        "nodes": [
            {"id": "start", "type": "start"},
            {"id": "llm", "type": "llm", "config": {"user_prompt": "{{ query }}", "output_var": "text"}},
            {"id": "answer", "type": "answer", "config": {"template": "{{ text }}"}},
            {"id": "end", "type": "end"},
        ],
        "edges": [
            {"source": "start", "target": "llm"},
            {"source": "llm", "target": "answer"},
            {"source": "answer", "target": "end"},
        ],
    }
).model_dump(mode="json")


def _seed_published_app() -> None:
    with session_scope() as session:
        app_row = App(uuid=uuid.uuid4().hex, tenant_code="t", app_id="app-1", api_key="key-1", app_name="demo")
        session.add(app_row)
        session.flush()
        graph = Graph(uuid=uuid.uuid4().hex, tenant_code="t", app_uuid=app_row.uuid, status="published")
        session.add(graph)
        session.flush()
        version = GraphVersion(uuid=uuid.uuid4().hex, graph_uuid=graph.uuid, version=1, definition=GRAPH_DEF)
        session.add(version)
        session.flush()
        graph.published_version_id = version.id


@pytest.fixture
def client(engine_ctx):
    _seed_published_app()
    app.dependency_overrides[get_engine_context] = lambda: engine_ctx
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_chat_streams_message_end(client):
    response = client.post("/v1/chat-messages", json={"query": "hi"}, headers={"Api-Key": "key-1"})
    assert response.status_code == 200
    assert "message_end" in response.text
    assert "echo:hi" in response.text


def test_cloud_compat_path_alias(client):
    response = client.post("/api/transfer/one/chat-messages", json={"query": "hi"}, headers={"Api-Key": "key-1"})
    assert response.status_code == 200
    assert "echo:hi" in response.text


def test_unknown_api_key_returns_default_reply(client):
    response = client.post("/v1/chat-messages", json={"query": "hi"}, headers={"Api-Key": "unknown"})
    assert "message_end" in response.text
    assert "智能客服" in response.text


def _seed_conversation() -> Conversation:
    with session_scope() as session:
        row = Conversation(
            uuid=uuid.uuid4().hex, tenant_code="t", app_uuid="app-uuid", conversation_id=uuid.uuid4().hex
        )
        session.add(row)
        session.flush()
        return row


def test_load_history_is_empty_when_window_disabled():
    conversation = _seed_conversation()
    services.save_message(conversation, "user", query="q1")
    assert services.load_history(conversation, 0) == []
    assert services.load_history(conversation, -1) == []


def test_load_history_returns_trailing_window_in_chronological_order():
    conversation = _seed_conversation()
    services.save_message(conversation, "user", query="q1")
    services.save_message(conversation, "assistant", query="q1", answer="a1")
    services.save_message(conversation, "user", query="q2")
    services.save_message(conversation, "assistant", query="q2", answer="a2")

    assert services.load_history(conversation, 3) == [
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
    ]
    assert len(services.load_history(conversation, 10)) == 4


def test_chat_injects_history_window_into_graph_inputs(client, monkeypatch):
    monkeypatch.setattr(main_mod, "get_settings", lambda: Settings(history_window=4))
    seen: list[dict] = []

    async def fake_stream(graph_def, inputs, ctx, checkpointer=None, thread_id=None):
        seen.append(dict(inputs))
        yield {"type": "final", "answer": "回答", "state": {"variables": {}}}

    monkeypatch.setattr(main_mod, "stream_graph", fake_stream)

    first = client.post("/v1/chat-messages", json={"query": "第一问"}, headers={"Api-Key": "key-1"})
    assert "history" not in seen[0]
    conversation_id = re.search(r'"conversation_id": "([0-9a-f]+)"', first.text).group(1)

    client.post(
        "/v1/chat-messages",
        json={"query": "第二问", "conversation_id": conversation_id},
        headers={"Api-Key": "key-1"},
    )
    assert seen[1]["history"] == [
        {"role": "user", "content": "第一问"},
        {"role": "assistant", "content": "回答"},
    ]
    assert seen[1]["query"] == "第二问"
