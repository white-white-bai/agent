"""内置 HTTP→MCP 桥：把声明的 HTTP 工具暴露为 agent 可调用的工具。

M1 实现为 HTTP 直调桥（MCP Server 的等价能力）；后续可叠加标准 MCP Client 接入外部真 MCP Server。
"""
from __future__ import annotations

from typing import Any

import httpx

from agent_platform.core.config import Settings
from agent_platform.engine.context import ToolInvoker
from agent_platform.engine.expr import evaluate
from agent_platform.graph.schema import ToolConfig


def build_tool_invoker(settings: Settings, servers: dict[str, str] | None = None) -> ToolInvoker:
    registry = servers or {}

    async def invoke(config: ToolConfig, variables: dict[str, Any]) -> list[Any]:
        results: list[Any] = []
        for ref in config.tools:
            base_url = registry.get(ref.server)
            if not base_url:
                raise RuntimeError(f"未知工具服务: {ref.server or '(未指定)'}")
            args = {
                key: evaluate(value, variables) if isinstance(value, str) else value
                for key, value in ref.args.items()
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(f"{base_url.rstrip('/')}/tools/{ref.name}", json=args)
            response.raise_for_status()
            results.append(response.json())
        return results

    return invoke
