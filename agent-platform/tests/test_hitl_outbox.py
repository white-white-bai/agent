"""HITL outbox：入队、投递成功、失败重试状态。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from agent_platform.core import hitl_outbox
from agent_platform.core.db import session_scope
from agent_platform.domain.models import HitlOutbox


def _settings(**overrides):
    data = {
        "hitl_webhook_url": "https://hooks.example/hitl",
        "hitl_webhook_timeout_seconds": 1.0,
        "hitl_outbox_max_attempts": 2,
        "hitl_outbox_backoff_seconds": 0,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _row(row_uuid: str) -> HitlOutbox | None:
    with session_scope() as session:
        return session.scalar(select(HitlOutbox).where(HitlOutbox.uuid == row_uuid))


@pytest.mark.asyncio
async def test_outbox_delivers_and_marks_sent(monkeypatch):
    async def fake_post(event, payload, settings):
        return True

    monkeypatch.setattr(hitl_outbox, "post_webhook", fake_post)
    row_uuid = hitl_outbox.enqueue_hitl("agent.interrupt", {"thread_id": "t1"})

    assert await hitl_outbox.flush_one(row_uuid, _settings()) is True
    row = _row(row_uuid)
    assert row is not None and row.status == "sent"
    assert row.attempts == 1


@pytest.mark.asyncio
async def test_outbox_marks_failed_after_max_attempts(monkeypatch):
    async def fake_post(event, payload, settings):
        return False

    monkeypatch.setattr(hitl_outbox, "post_webhook", fake_post)
    row_uuid = hitl_outbox.enqueue_hitl("graph.interrupt", {"thread_id": "t2"})

    assert await hitl_outbox.flush_one(row_uuid, _settings(hitl_outbox_max_attempts=1)) is False
    row = _row(row_uuid)
    assert row is not None and row.status == "failed"
    assert row.attempts == 1
