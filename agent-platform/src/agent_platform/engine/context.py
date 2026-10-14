"""引擎运行时依赖（模型 / 检索 / 工具 / 代码执行）。"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from agent_platform.graph.schema import CodeConfig, KnowledgeConfig, ToolConfig


class LLMInvoker(Protocol):
    async def __call__(
        self,
        *,
        provider: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int | None,
    ) -> str: ...


class Retriever(Protocol):
    async def __call__(self, config: KnowledgeConfig, query: str) -> list[dict[str, Any]]: ...


class ToolInvoker(Protocol):
    async def __call__(self, config: ToolConfig, variables: dict[str, Any]) -> Any: ...


class CodeRunner(Protocol):
    def __call__(self, config: CodeConfig, variables: dict[str, Any]) -> dict[str, Any]: ...


async def _empty_retriever(config: KnowledgeConfig, query: str) -> list[dict[str, Any]]:
    return []


async def _unavailable_tool_invoker(config: ToolConfig, variables: dict[str, Any]) -> Any:
    raise RuntimeError("工具调用未配置：请在 EngineContext 注入 ToolInvoker")


@dataclass
class EngineContext:
    llm: LLMInvoker
    retriever: Retriever = field(default=_empty_retriever)
    tools: ToolInvoker = field(default=_unavailable_tool_invoker)
    code_runner: CodeRunner | None = None


EngineNodeFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
