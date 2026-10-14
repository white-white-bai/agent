import uuid

import pytest
from fastapi.testclient import TestClient

from agent_platform.api.main import app, get_engine_context
from agent_platform.core.db import session_scope
from agent_platform.domain.models import App, Graph, GraphVersion
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
