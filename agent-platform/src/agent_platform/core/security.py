"""兼容层鉴权：云智 JWT token 签发/校验 + 原始 Dify Bearer apiKey 解析。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from agent_platform.core.config import get_settings


class AuthError(Exception):
    pass


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _sign(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def issue_token(client_id: str, *, ttl_seconds: int = 3600) -> tuple[str, int]:
    settings = get_settings()
    expire = int(time.time()) + ttl_seconds
    body = json.dumps({"sub": client_id, "exp": expire}, ensure_ascii=False).encode()
    encoded = _b64encode(body)
    return f"{encoded}.{_sign(body, settings.jwt_secret)}", ttl_seconds


def verify_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        encoded, signature = token.rsplit(".", 1)
        body = _b64decode(encoded)
    except Exception as exc:
        raise AuthError("token 格式非法") from exc
    if not hmac.compare_digest(signature, _sign(body, settings.jwt_secret)):
        raise AuthError("token 签名校验失败")
    payload = json.loads(body)
    if int(payload.get("exp", 0)) < int(time.time()):
        raise AuthError("token 已过期")
    return payload


def check_client(client_id: str, client_secret: str) -> bool:
    clients = get_settings().oauth_clients
    if not clients:
        return bool(client_id)
    return clients.get(client_id) == client_secret


def resolve_api_key(
    api_key_header: str | None,
    authorization: str | None,
    *,
    require_token: bool = False,
) -> str:
    """从请求头解析 app 的 api_key（云智 JWT + Api-Key，或原始 Dify Bearer apiKey）。"""
    token = ""
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() in ("jwt", "bearer"):
            token = value.strip()
    if require_token and token:
        verify_token(token)
    if api_key_header:
        return api_key_header
    # 原始 Dify：Authorization: Bearer <apiKey>
    if token:
        return token
    return ""
