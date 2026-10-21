"""HITL 审批链接签名：HMAC-SHA256 + 过期时间，token 绑定 interrupt id。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any


class HitlTokenError(ValueError):
    pass


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _sign(payload: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).hexdigest()


def make_action_token(
    *,
    kind: str,
    app_uuid: str,
    thread_id: str,
    interrupt_id: str,
    secret: str,
    ttl_seconds: int = 86400,
) -> str:
    if not secret:
        raise HitlTokenError("HITL 签名密钥未配置")
    now = int(time.time())
    payload = {
        "v": 1,
        "kind": kind,
        "app_uuid": app_uuid,
        "thread_id": thread_id,
        "interrupt_id": interrupt_id,
        "iat": now,
        "exp": now + max(int(ttl_seconds or 0), 1),
    }
    encoded = _b64encode(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return f"{encoded}.{_sign(encoded, secret)}"


def verify_action_token(token: str, secret: str) -> dict[str, Any]:
    if not secret:
        raise HitlTokenError("HITL 签名密钥未配置")
    try:
        encoded, signature = str(token or "").split(".", 1)
    except ValueError as exc:
        raise HitlTokenError("审批 token 格式非法") from exc
    if not hmac.compare_digest(_sign(encoded, secret), signature):
        raise HitlTokenError("审批 token 签名不匹配")
    try:
        payload = json.loads(_b64decode(encoded))
    except (ValueError, json.JSONDecodeError) as exc:
        raise HitlTokenError("审批 token 内容非法") from exc
    if int(payload.get("exp") or 0) < int(time.time()):
        raise HitlTokenError("审批 token 已过期")
    if payload.get("kind") not in ("graph", "agent"):
        raise HitlTokenError("审批 token kind 非法")
    for key in ("app_uuid", "thread_id", "interrupt_id"):
        if not payload.get(key):
            raise HitlTokenError(f"审批 token 缺少 {key}")
    return payload


def graph_interrupt_id(item: dict[str, Any] | None) -> str:
    pending = (item or {}).get("interrupts") or []
    if not pending or not isinstance(pending[0], dict):
        return ""
    return str(pending[0].get("id") or "")


def approval_links(
    *,
    kind: str,
    app_uuid: str,
    thread_id: str,
    interrupt_id: str,
    settings: Any,
) -> dict[str, Any]:
    secret = str(getattr(settings, "hitl_webhook_secret", "") or "")
    if not secret or not interrupt_id:
        return {}
    ttl = int(getattr(settings, "hitl_action_ttl_seconds", 86400) or 86400)
    token = make_action_token(
        kind=kind,
        app_uuid=app_uuid,
        thread_id=thread_id,
        interrupt_id=interrupt_id,
        secret=secret,
        ttl_seconds=ttl,
    )
    base = str(getattr(settings, "hitl_callback_base_url", "") or "").rstrip("/")
    prefix = f"{base}/webhooks/hitl" if base else "/webhooks/hitl"
    return {
        "token": token,
        "expires_in": ttl,
        "approve_url": f"{prefix}/approve",
        "reject_url": f"{prefix}/reject",
    }
