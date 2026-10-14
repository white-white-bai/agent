"""FastAPI 依赖：引擎上下文 / 护栏 / 追踪。"""
from __future__ import annotations

import uuid
from typing import Any

from agent_platform.core.config import get_settings
from agent_platform.core.guards import GuardChain
from agent_platform.engine.context import EngineContext
from agent_platform.engine.factory import build_engine_context
from agent_platform.observability.langfuse import build_tracer


def get_engine_context() -> EngineContext:
    return build_engine_context(get_settings())


def get_guard_chain() -> GuardChain:
    return GuardChain(get_settings())


def build_request_tracer(user: str = "", metadata: dict[str, Any] | None = None) -> Any:
    return build_tracer(get_settings(), name="chat-messages", user_id=user, metadata=metadata or {})


def new_id() -> str:
    return uuid.uuid4().hex
