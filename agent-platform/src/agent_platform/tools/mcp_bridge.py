"""工具调用：内置 HTTP→MCP 桥（声明式 HTTP 工具）+ MCP Client 接入外部真 MCP Server。"""
from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import select

from agent_platform.core.config import Settings
from agent_platform.core.db import session_scope
from agent_platform.domain.models import McpServer
from agent_platform.engine.context import ToolInvoker
from agent_platform.engine.expr import evaluate
from agent_platform.graph.schema import ToolConfig
from agent_platform.tools.mcp_client import McpHttpClient


def _resolve_spec(settings: Settings, name: str, tenant_code: str) -> dict[str, Any] | None:
    spec = settings.tool_servers.get(name)
    if spec:
        return dict(spec)
    with session_scope() as session:
        row = session.scalar(
            select(McpServer).where(McpServer.name == name, McpServer.is_deleted == 0)
        )
    if row is None:
        return None
    if row.tenant_code and tenant_code and row.tenant_code != tenant_code:
        return None
    return {"url": row.url, "kind": row.kind, "headers": row.headers or {}}


def _render_args(ref_args: dict[str, Any], variables: dict[str, Any]) -> dict[str, Any]:
    return {
        key: evaluate(value, variables) if isinstance(value, str) else value
        for key, value in ref_args.items()
    }


async def _call_http_bridge(base_url: str, name: str, args: dict[str, Any]) -> Any:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(f"{base_url.rstrip('/')}/tools/{name}", json=args)
    response.raise_for_status()
    return response.json()


def build_tool_invoker(settings: Settings, servers: dict[str, str] | None = None) -> ToolInvoker:
    legacy = servers or {}

    async def invoke(config: ToolConfig, variables: dict[str, Any], tenant_code: str = "") -> list[Any]:
        results: list[Any] = []
        for ref in config.tools:
            args = _render_args(ref.args, variables)
            spec = _resolve_spec(settings, ref.server, tenant_code) if ref.server else None
            if spec is None and ref.server in legacy:
                spec = {"url": legacy[ref.server], "kind": "http"}
            if spec is None:
                raise RuntimeError(f"未知工具服务: {ref.server or '(未指定)'}")
            kind = spec.get("kind", "mcp")
            url = spec.get("url", "")
            if kind == "http":
                results.append(await _call_http_bridge(url, ref.name, args))
            else:
                client = McpHttpClient(
                    url, headers=spec.get("headers"), timeout=float(spec.get("timeout", 30.0))
                )
                await client.initialize()
                results.append(await client.call_tool(ref.name, args))
        return results

    return invoke
