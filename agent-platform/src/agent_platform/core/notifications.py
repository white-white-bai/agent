"""HITL 外部通知：支持直接重试或持久化 outbox。"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


async def _post(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> bool:
    if not url:
        return False
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
        return True
    except Exception:  # 外部通知失败不能影响审批链路
        logger.warning("HITL Webhook 投递失败：%s", url, exc_info=True)
        return False


def _summary(event: str, payload: dict[str, Any]) -> str:
    data = payload or {}
    approval = data.get("approval") or {}
    lines = [
        f"事件：{event}",
        f"线程：{data.get('thread_id') or '-'}",
        f"应用：{data.get('app_uuid') or '-'}",
    ]
    if data.get("interrupt"):
        lines.append(f"中断：{str(data['interrupt'])[:500]}")
    if approval.get("approve_url"):
        lines.append(f"批准：{approval['approve_url']}")
    if approval.get("reject_url"):
        lines.append(f"驳回：{approval['reject_url']}")
    return "\n".join(lines)


async def post_webhook(event: str, payload: dict[str, Any], settings: Any) -> bool:
    """发送一次 Webhook；支持通用 JSON、Slack text、Teams MessageCard。"""
    secret = str(getattr(settings, "hitl_webhook_secret", "") or "")
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-Webhook-Secret"] = secret
    timeout = float(getattr(settings, "hitl_webhook_timeout_seconds", 3.0) or 3.0)
    summary = _summary(event, payload)
    targets = [
        (
            str(getattr(settings, "hitl_webhook_url", "") or ""),
            {"event": event, "payload": payload},
        ),
        (str(getattr(settings, "hitl_slack_webhook_url", "") or ""), {"text": f"*{event}*\n{summary}"}),
        (
            str(getattr(settings, "hitl_teams_webhook_url", "") or ""),
            {
                "@type": "MessageCard",
                "@context": "https://schema.org/extensions",
                "summary": event,
                "text": summary.replace("\n", "\n\n"),
            },
        ),
    ]
    configured = [(url, body) for url, body in targets if url]
    if not configured:
        return False
    results = [await _post(url, body, headers, timeout) for url, body in configured]
    return all(results)


async def notify_hitl(event: str, payload: dict[str, Any], settings: Any) -> bool:
    if not any(
        str(getattr(settings, attr, "") or "")
        for attr in ("hitl_webhook_url", "hitl_slack_webhook_url", "hitl_teams_webhook_url")
    ):
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
