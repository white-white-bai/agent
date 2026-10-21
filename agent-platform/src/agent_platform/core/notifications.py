"""HITL 外部通知：中断时向 Webhook 推送事件，失败只记日志、不阻断执行。"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


async def notify_hitl(event: str, payload: dict[str, Any], settings: Any) -> bool:
    url = str(getattr(settings, "hitl_webhook_url", "") or "")
    if not url:
        return False
    headers = {"Content-Type": "application/json"}
    secret = str(getattr(settings, "hitl_webhook_secret", "") or "")
    if secret:
        headers["X-Webhook-Secret"] = secret
    timeout = float(getattr(settings, "hitl_webhook_timeout_seconds", 3.0) or 3.0)
    attempts = max(int(getattr(settings, "hitl_webhook_attempts", 2) or 1), 1)
    backoff = max(float(getattr(settings, "hitl_webhook_backoff_seconds", 0.2) or 0), 0.0)
    body = {"event": event, "payload": payload}
    for attempt in range(1, attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=body, headers=headers)
                response.raise_for_status()
            return True
        except Exception:  # 外部通知失败不能影响审批链路
            if attempt >= attempts:
                logger.warning("HITL Webhook 通知失败（已重试 %s 次）：%s", attempt, event, exc_info=True)
                return False
            await asyncio.sleep(backoff * attempt)
    return False
