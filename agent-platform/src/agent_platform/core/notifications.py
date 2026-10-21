"""HITL 外部通知：支持直接重试或持久化 outbox。"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


async def post_webhook(event: str, payload: dict[str, Any], settings: Any) -> bool:
    """发送一次 Webhook；网络/HTTP 失败返回 False。"""
    url = str(getattr(settings, "hitl_webhook_url", "") or "")
    if not url:
        return False
    headers = {"Content-Type": "application/json"}
    secret = str(getattr(settings, "hitl_webhook_secret", "") or "")
    if secret:
        headers["X-Webhook-Secret"] = secret
    timeout = float(getattr(settings, "hitl_webhook_timeout_seconds", 3.0) or 3.0)
    body = {"event": event, "payload": payload}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
        return True
    except Exception:  # 外部通知失败不能影响审批链路
        logger.warning("HITL Webhook 投递失败：%s", event, exc_info=True)
        return False


async def notify_hitl(event: str, payload: dict[str, Any], settings: Any) -> bool:
    if not str(getattr(settings, "hitl_webhook_url", "") or ""):
        return False
    if getattr(settings, "hitl_outbox_enabled", False):
        from agent_platform.core.hitl_outbox import enqueue_hitl, flush_one

        try:
            row_uuid = enqueue_hitl(event, payload)
        except Exception:
            logger.warning("HITL outbox 入队失败，回退直接投递：%s", event, exc_info=True)
            row_uuid = ""
        if row_uuid:
            await flush_one(row_uuid, settings)
            return True
    attempts = max(int(getattr(settings, "hitl_webhook_attempts", 2) or 1), 1)
    backoff = max(float(getattr(settings, "hitl_webhook_backoff_seconds", 0.2) or 0), 0.0)
    for attempt in range(1, attempts + 1):
        if await post_webhook(event, payload, settings):
            return True
        if attempt < attempts:
            await asyncio.sleep(backoff * attempt)
    logger.warning("HITL Webhook 通知失败（已重试 %s 次）：%s", attempts, event)
    return False
