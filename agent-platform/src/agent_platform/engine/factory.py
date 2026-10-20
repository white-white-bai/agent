"""EngineContext 构建工厂（API 与 worker 共用）。"""
from __future__ import annotations

from typing import Any

from agent_platform.api import services
from agent_platform.core.config import Settings, get_settings
from agent_platform.engine.agents.runner import build_agent_invoker
from agent_platform.engine.context import EngineContext
from agent_platform.knowledge.retrievers import build_retriever
from agent_platform.models.factory import build_llm_invoker
from agent_platform.tools.mcp_bridge import build_tool_invoker


def build_engine_context(
    settings: Settings | None = None,
    *,
    tenant_code: str = "",
    tracer: Any = None,
) -> EngineContext:
    settings = settings or get_settings()
    return EngineContext(
        llm=build_llm_invoker(settings),
        retriever=build_retriever(settings),
        tools=build_tool_invoker(settings),
        agents=build_agent_invoker(settings),
        tenant_code=tenant_code,
        tracer=tracer,
        subgraph_enabled=settings.subgraph_enabled,
        resolve_subgraph=lambda ref, tenant: services.resolve_subgraph(ref, tenant),
    )
