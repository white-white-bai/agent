"""HITL 通知 outbox：持久化待投递事件，失败后由后台轮询重试。"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select

from agent_platform.core.db import session_scope
from agent_platform.core.notifications import post_webhook
from agent_platform.domain.models import HitlOutbox

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def enqueue_hitl(event: str, payload: dict[str, Any]) -> str:
    row_uuid = uuid.uuid4().hex
    with session_scope() as session:
        session.add(
            HitlOutbox(
                uuid=row_uuid,
                event=event,
                payload=payload,
                status="pending",
                attempts=0,
                next_retry_at=_now(),
            )
        )
    return row_uuid


async def flush_one(row_uuid: str, settings: Any) -> bool:
    with session_scope() as session:
        row = session.scalar(select(HitlOutbox).where(HitlOutbox.uuid == row_uuid))
        if row is None or row.status == "sent":
            return False
        event = row.event
        payload = dict(row.payload or {})
    ok = await post_webhook(event, payload, settings)
    with session_scope() as session:
        row = session.scalar(select(HitlOutbox).where(HitlOutbox.uuid == row_uuid))
        if row is None:
            return ok
        row.attempts = int(row.attempts or 0) + 1
        row.updated_at = _now()
        if ok:
            row.status = "sent"
            row.last_error = ""
            row.next_retry_at = None
        else:
            max_attempts = max(int(getattr(settings, "hitl_outbox_max_attempts", 6) or 1), 1)
            backoff = max(float(getattr(settings, "hitl_outbox_backoff_seconds", 5.0) or 0.0), 0.0)
            row.status = "failed" if row.attempts >= max_attempts else "pending"
            row.last_error = "webhook delivery failed"
            delay = backoff * (2 ** max(row.attempts - 1, 0))
            row.next_retry_at = _now() + timedelta(seconds=delay)
    return ok


async def flush_pending(settings: Any, limit: int = 20) -> int:
    now = _now()
    with session_scope() as session:
        rows = list(
            session.scalars(
                select(HitlOutbox)
                .where(
                    HitlOutbox.status == "pending",
                    or_(HitlOutbox.next_retry_at.is_(None), HitlOutbox.next_retry_at <= now),
                )
                .order_by(HitlOutbox.id.asc())
                .limit(max(int(limit or 20), 1))
            ).all()
        )
        ids = [row.uuid for row in rows]
    sent = 0
    for row_uuid in ids:
        if await flush_one(row_uuid, settings):
            sent += 1
    return sent


async def worker(settings: Any) -> None:
    interval = max(float(getattr(settings, "hitl_outbox_poll_seconds", 5.0) or 5.0), 0.1)
    while True:
        try:
            await flush_pending(settings)
        except Exception:
            logger.exception("HITL outbox 轮询失败")
        await asyncio.sleep(interval)
