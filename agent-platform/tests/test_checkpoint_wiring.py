"""checkpoint 接线：默认不写表，开启后对话链路落 checkpoint。"""
from __future__ import annotations

from sqlalchemy import func, select

from agent_platform.api import main as main_mod
from agent_platform.core.config import Settings
from agent_platform.core.db import session_scope
from agent_platform.domain.models import Checkpoint


def _checkpoint_count() -> int:
    with session_scope() as session:
        return int(session.scalar(select(func.count(Checkpoint.id))) or 0)


def test_chat_does_not_write_checkpoint_by_default(api_client, seed_app):
    seed_app(tenant_code="t", app_id="app-1", api_key="key-1")

    response = api_client.post(
        "/v1/chat-messages",
        json={"query": "hi", "user": "u1", "conversation_id": "conv-a"},
        headers={"Api-Key": "key-1"},
    )

    assert response.status_code == 200
    assert "message_end" in response.text
    assert _checkpoint_count() == 0


def test_chat_writes_checkpoint_when_enabled(api_client, seed_app, monkeypatch):
    seed_app(tenant_code="t", app_id="app-1", api_key="key-1")
    monkeypatch.setattr(main_mod, "get_settings", lambda: Settings(checkpointer_enabled=True))

    response = api_client.post(
        "/v1/chat-messages",
        json={"query": "hi", "user": "u1", "conversation_id": "conv-a"},
        headers={"Api-Key": "key-1"},
    )

    assert response.status_code == 200
    assert "echo:hi" in response.text
    assert _checkpoint_count() > 0
    with session_scope() as session:
        thread_ids = {
            row for row in session.scalars(select(Checkpoint.thread_id)).all()
        }
    assert thread_ids == {"conv-a"}
