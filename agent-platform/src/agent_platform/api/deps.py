"""FastAPI 依赖：引擎上下文 / 护栏 / 幂等 / 并发 / 追踪 / 管理端鉴权。"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import Depends, Header, HTTPException

from agent_platform.core.accounts import ANONYMOUS, AdminPrincipal, principal_from_token
from agent_platform.core.concurrency import ConcurrencyLimiter
from agent_platform.core.config import get_settings
from agent_platform.core.guards import GuardChain
from agent_platform.core.idempotency import IdempotencyStore
from agent_platform.core.security import AuthError
from agent_platform.engine.context import EngineContext
from agent_platform.engine.factory import build_engine_context
from agent_platform.observability.langfuse import build_tracer


def get_engine_context() -> EngineContext:
    return build_engine_context(get_settings())


def get_guard_chain() -> GuardChain:
    return GuardChain(get_settings())


def get_idempotency_store() -> IdempotencyStore:
    return IdempotencyStore(get_settings())


def get_concurrency_limiter() -> ConcurrencyLimiter:
    return ConcurrencyLimiter(get_settings())


def build_request_tracer(user: str = "", metadata: dict[str, Any] | None = None) -> Any:
    return build_tracer(get_settings(), name="chat-messages", user_id=user, metadata=metadata or {})


def new_id() -> str:
    return uuid.uuid4().hex


# --------------------------------------------------------------------------- 管理端鉴权

def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        return ""
    scheme, _, value = authorization.partition(" ")
    return value.strip() if scheme.lower() in ("bearer", "jwt") else ""


def get_current_admin(authorization: str | None = Header(default=None)) -> AdminPrincipal:
    """解析管理员令牌。`AP_ADMIN_AUTH_ENABLED=false`（默认）时返回匿名全权，行为与改造前一致。"""
    if not get_settings().admin_auth_enabled:
        return ANONYMOUS
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="缺少管理员令牌")
    try:
        return principal_from_token(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def require_admin(principal: AdminPrincipal = Depends(get_current_admin)) -> AdminPrincipal:
    """认证：路由级 `dependencies=[Depends(require_admin)]`。"""
    return principal


def require_permission(permission: str) -> Callable[..., AdminPrincipal]:
    """授权：路由级 `dependencies=[Depends(require_permission("app:write"))]`。"""

    def _dependency(principal: AdminPrincipal = Depends(get_current_admin)) -> AdminPrincipal:
        if get_settings().admin_auth_enabled and not principal.allows(permission):
            raise HTTPException(status_code=403, detail=f"缺少权限: {permission}")
        return principal

    return _dependency
