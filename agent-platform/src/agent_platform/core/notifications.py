"""HITL 外部通知：中断时向 Webhook 推送事件，失败只记日志、不阻断执行。"""
from __future__ import annotations

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
    body = {"event": event, "payload": payload}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
        return True
    except Exception:  # 外部通知失败不能影响审批链路
        logger.warning("HITL Webhook 通知失败：%s", event, exc_info=True)
        return False
