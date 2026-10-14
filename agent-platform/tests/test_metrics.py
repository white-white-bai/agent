"""监控看板：会话量 / 消息量 / 满意度 / token / 错误率汇总与查询接口。"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from agent_platform.api import main as main_mod
from agent_platform.api.main import app, get_engine_context
from agent_platform.core import accounts, metrics
from agent_platform.core.config import get_settings
from agent_platform.core.db import session_scope
from agent_platform.domain.models import App, Conversation, Message, MetricEvent


def _seed_app(tenant_code: str = "t", app_id: str = "app-1", api_key: str = "key-1") -> str:
    with session_scope() as session:
        row = App(
            uuid=uuid.uuid4().hex, tenant_code=tenant_code, app_id=app_id, api_key=api_key, app_name="demo"
        )
        session.add(row)
        session.flush()
        return row.uuid


def _seed_conversation(app_uuid: str, tenant_code: str = "t", user_name: str = "u1") -> str:
    with session_scope() as session:
        row = Conversation(
            uuid=uuid.uuid4().hex,
            tenant_code=tenant_code,
            app_uuid=app_uuid,
            conversation_id=uuid.uuid4().hex,
            user_name=user_name,
        )
        session.add(row)
        session.flush()
        return row.uuid


def _seed_message(
    conversation_uuid: str, role: str = "user", tokens: int = 0, feedback: str | None = None, answer: str = ""
) -> None:
    with session_scope() as session:
        session.add(
            Message(
                uuid=uuid.uuid4().hex,
                conversation_uuid=conversation_uuid,
                message_id=uuid.uuid4().hex,
                role=role,
                query="问" if role == "user" else "",
                answer=answer,
                tokens=tokens,
                feedback=feedback,
            )
        )


@pytest.fixture()
def client(engine_ctx):
    app.dependency_overrides[get_engine_context] = lambda: engine_ctx
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_on(monkeypatch):
    monkeypatch.setenv("AP_ADMIN_AUTH_ENABLED", "true")
    monkeypatch.setenv("AP_ADMIN_SEED_USERNAME", "admin")
    monkeypatch.setenv("AP_ADMIN_SEED_PASSWORD", "admin123")
    get_settings.cache_clear()
    accounts.seed()
    yield
    get_settings.cache_clear()


# --------------------------------------------------------------------------- 汇总

def test_overview_empty_is_zero_filled():
    data = metrics.overview(days=3)
    assert data["range"]["days"] == 3
    assert len(data["range"]["start"]) == 10 and len(data["range"]["end"]) == 10
    assert data["conversations"]["total"] == 0
    assert [row["count"] for row in data["conversations"]["series"]] == [0, 0, 0]
    assert data["messages"] == {"total": 0, "user": 0, "assistant": 0}
    assert data["satisfaction"] == {"like": 0, "dislike": 0, "rate": 0.0}
    assert data["tokens"]["total"] == 0
    assert [row["count"] for row in data["tokens"]["series"]] == [0, 0, 0]
    assert data["errors"]["total"] == 0 and data["errors"]["rate"] == 0.0
    assert [row["count"] for row in data["errors"]["series"]] == [0, 0, 0]


def test_overview_aggregates_conversations_messages_tokens_and_satisfaction():
    app_uuid = _seed_app()
    first = _seed_conversation(app_uuid)
    second = _seed_conversation(app_uuid, user_name="u2")
    _seed_message(first, role="user")
    _seed_message(first, role="assistant", tokens=30, answer="答", feedback="like")
    _seed_message(second, role="user")
    _seed_message(second, role="assistant", tokens=20, feedback="dislike")

    data = metrics.overview(app_uuid=app_uuid, days=7)
    assert data["conversations"]["total"] == 2
    assert data["conversations"]["series"][-1]["count"] == 2
    assert data["messages"] == {"total": 4, "user": 2, "assistant": 2}
    assert data["tokens"]["total"] == 50
    assert data["tokens"]["series"][-1]["count"] == 50
    assert data["satisfaction"] == {"like": 1, "dislike": 1, "rate": 0.5}


def test_overview_rates_and_day_window():
    app_uuid = _seed_app()
    conversation = _seed_conversation(app_uuid)
    _seed_message(conversation, role="user")
    _seed_message(conversation, role="user")
    _seed_message(conversation, role="assistant", feedback="like")
    metrics.record_error(tenant_code="t", app_uuid=app_uuid, detail="boom")

    data = metrics.overview(app_uuid=app_uuid, days=1)
    assert data["satisfaction"]["rate"] == 1.0
    assert data["errors"]["total"] == 1 and data["errors"]["rate"] == 0.5
    assert len(data["conversations"]["series"]) == 1


def test_overview_clamps_days_window():
    assert metrics.overview(days=0)["range"]["days"] == 7
    assert metrics.overview(days=-5)["range"]["days"] == 1
    assert metrics.overview(days=10_000)["range"]["days"] == metrics.MAX_DAYS


def test_overview_scopes_by_tenant_and_app():
    first_app = _seed_app(tenant_code="t", app_id="app-1")
    second_app = _seed_app(tenant_code="other", app_id="app-2")
    _seed_message(_seed_conversation(first_app, tenant_code="t"))
    _seed_message(_seed_conversation(second_app, tenant_code="other"))
    metrics.record_error(tenant_code="t", app_uuid=first_app, detail="a")
    metrics.record_error(tenant_code="other", app_uuid=second_app, detail="b")

    scoped = metrics.overview(tenant_code="t", app_uuid=first_app)
    assert scoped["messages"]["user"] == 1 and scoped["errors"]["total"] == 1
    by_tenant = metrics.overview(tenant_code="other")
    assert by_tenant["messages"]["user"] == 1 and by_tenant["errors"]["total"] == 1
    assert metrics.overview()["messages"]["user"] == 2
    assert metrics.overview(app_uuid="ghost")["messages"]["user"] == 0


# --------------------------------------------------------------------------- 错误事件

def test_record_error_persists_and_truncates_detail():
    metrics.record_error(tenant_code="t", app_uuid="app-1", detail="x" * 900)
    with session_scope() as session:
        row = session.query(MetricEvent).one()
    assert row.kind == "error" and row.tenant_code == "t" and row.app_uuid == "app-1"
    assert len(row.detail) == 512


def test_record_error_swallows_storage_failure(monkeypatch):
    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(metrics, "session_scope", _boom)
    assert metrics.record_error(tenant_code="t", app_uuid="app-1", detail="x") is None


# --------------------------------------------------------------------------- 查询接口

def test_metrics_overview_endpoint_returns_envelope(client):
    app_uuid = _seed_app()
    _seed_message(_seed_conversation(app_uuid), role="user")
    response = client.get("/admin/metrics/overview", params={"app_uuid": app_uuid, "days": 2})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["range"]["days"] == 2
    assert data["messages"]["user"] == 1
    assert len(data["errors"]["series"]) == 2


def test_metrics_overview_requires_permission_and_token(client, auth_on):
    assert client.get("/admin/metrics/overview").status_code == 401
    token = client.post("/admin/login", json={"username": "admin", "password": "admin123"}).json()["data"]["token"]
    allowed = client.get("/admin/metrics/overview", headers={"Authorization": f"Bearer {token}"})
    assert allowed.status_code == 200


def test_metrics_overview_honours_account_tenant(client, auth_on, monkeypatch):
    accounts.create_user("viewer-t", "pw12345678", role_code="viewer", tenant_code="t")
    token = client.post("/admin/login", json={"username": "viewer-t", "password": "pw12345678"}).json()["data"][
        "token"
    ]
    headers = {"Authorization": f"Bearer {token}"}
    own_app = _seed_app(tenant_code="t", app_id="app-1")
    other_app = _seed_app(tenant_code="other", app_id="app-2")
    _seed_message(_seed_conversation(own_app, tenant_code="t"))
    _seed_message(_seed_conversation(other_app, tenant_code="other"))

    own = client.get("/admin/metrics/overview", params={"tenant_code": "t"}, headers=headers).json()["data"]
    assert own["messages"]["user"] == 1 and own["errors"]["total"] == 0
    forced = client.get("/admin/metrics/overview", params={"tenant_code": "other"}, headers=headers).json()["data"]
    assert forced["messages"]["user"] == 1
    assert (
        client.get("/admin/metrics/overview", params={"app_uuid": other_app}, headers=headers).json()["data"][
            "messages"
        ]["user"]
        == 0
    )


# --------------------------------------------------------------------------- 链路埋点

def test_chat_failure_is_recorded_as_metric_event(client, seed_app, monkeypatch):
    app_uuid, api_key = seed_app(tenant_code="t", app_id="app-1", api_key="key-1")

    async def failing_stream(graph_def, inputs, ctx, checkpointer=None, thread_id=None):
        raise RuntimeError("模型不可用")
        yield {}

    monkeypatch.setattr(main_mod, "stream_graph", failing_stream)
    response = client.post("/v1/chat-messages", json={"query": "hi"}, headers={"Api-Key": api_key})
    assert "error" in response.text and "模型不可用" in response.text

    data = metrics.overview(tenant_code="t", app_uuid=app_uuid)
    assert data["errors"]["total"] == 1
    assert data["errors"]["rate"] == 1.0
    assert client.get("/admin/metrics/overview", params={"app_uuid": app_uuid}).json()["data"]["errors"]["total"] == 1
