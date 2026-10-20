"""引擎运行时依赖（模型 / 检索 / 工具 / 代码执行 / 追踪）。"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from agent_platform.graph.schema import AgentConfig, CodeConfig, KnowledgeConfig, ToolConfig


class LLMInvoker(Protocol):
    async def __call__(
        self,
        *,
        provider: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int | None,
        messages: list[Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        return_message: bool = False,
        tags: list[str] | None = None,
    ) -> Any: ...


class Retriever(Protocol):
    async def __call__(
        self, config: KnowledgeConfig, query: str, tenant_code: str = ""
    ) -> list[dict[str, Any]]: ...


class ToolInvoker(Protocol):
    async def __call__(
        self, config: ToolConfig, variables: dict[str, Any], tenant_code: str = ""
    ) -> Any: ...


class CodeRunner(Protocol):
    def __call__(self, config: CodeConfig, variables: dict[str, Any]) -> dict[str, Any]: ...


class AgentInvoker(Protocol):
    """智能体节点执行入口（7 种工作模式在内部落地）。"""

    async def __call__(
        self, config: AgentConfig, variables: dict[str, Any], ctx: EngineContext, tenant_code: str = ""
    ) -> dict[str, Any]: ...


async def _empty_retriever(
    config: KnowledgeConfig, query: str, tenant_code: str = ""
) -> list[dict[str, Any]]:
    return []


async def _unavailable_tool_invoker(
    config: ToolConfig, variables: dict[str, Any], tenant_code: str = ""
) -> Any:
    raise RuntimeError("工具调用未配置：请在 EngineContext 注入 ToolInvoker")


async def _unavailable_agent_invoker(
    config: AgentConfig, variables: dict[str, Any], ctx: EngineContext, tenant_code: str = ""
) -> dict[str, Any]:
    raise RuntimeError("智能体运行时未配置：请在 EngineContext 注入 AgentInvoker")


@dataclass
class EngineContext:
    llm: LLMInvoker
    retriever: Retriever = field(default=_empty_retriever)
    tools: ToolInvoker = field(default=_unavailable_tool_invoker)
    code_runner: CodeRunner | None = None
    agents: AgentInvoker = field(default=_unavailable_agent_invoker)
    tenant_code: str = ""
    tracer: Any = None
    hitl_enabled: bool = False
    subgraph_enabled: bool = False
    resolve_subgraph: Any = None


EngineNodeFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
