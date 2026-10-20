"""工具调用：内置 HTTP→MCP 桥 + MCP Client，并套用参数校验 / 重试 / 兜底治理。

工具声明来自 `ap_tool`（可管理端维护）；未声明的引用回退到旧的「服务 + 工具名」行为。
"""
from __future__ import annotations

import functools
import logging
from typing import Any

import httpx
from sqlalchemy import select

from agent_platform.core.config import Settings
from agent_platform.core.db import session_scope
from agent_platform.domain.models import McpServer, Tool
from agent_platform.engine.context import ToolInvoker
from agent_platform.engine.expr import evaluate
from agent_platform.graph.schema import ToolConfig
from agent_platform.tools.mcp_client import McpHttpClient
from agent_platform.tools.policy import call_tool_governed

logger = logging.getLogger(__name__)

DEFAULT_PATH_TEMPLATE = "/tools/{name}"


def _tool_spec(name: str, tenant_code: str) -> dict[str, Any] | None:
    """按工具名解析 `ap_tool` 声明。"""
    with session_scope() as session:
        row = session.scalar(select(Tool).where(Tool.name == name, Tool.is_deleted == 0))
    if row is None:
        return None
    if row.tenant_code and tenant_code and row.tenant_code != tenant_code:
        return None
    return {
        "name": row.name,
        "label": row.label,
        "description": row.description or "",
        "server": row.server,
        "kind": row.kind or "http",
        "http_method": row.http_method or "POST",
        "http_path": row.http_path or "",
        "params": list(row.params or []),
        "retry_attempts": row.retry_attempts,
        "retry_backoff_seconds": row.retry_backoff_seconds,
        "fallback": dict(row.fallback or {}),
    }


def _server_spec(settings: Settings, name: str, tenant_code: str) -> dict[str, Any] | None:
    spec = settings.tool_servers.get(name)
    if spec:
        return dict(spec)
    with session_scope() as session:
        row = session.scalar(select(McpServer).where(McpServer.name == name, McpServer.is_deleted == 0))
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


async def _invoke(tool_spec: dict[str, Any], server_spec: dict[str, Any], name: str, args: dict[str, Any]) -> Any:
    kind = str(tool_spec.get("kind") or server_spec.get("kind") or "mcp")
    url = str(server_spec.get("url") or "")
    if kind == "http":
        if not url:
            raise RuntimeError(f"工具 {name} 未配置服务地址")
        path = str(tool_spec.get("http_path") or "") or DEFAULT_PATH_TEMPLATE.format(name=name)
        method = str(tool_spec.get("http_method") or "POST").upper()
        timeout = float(server_spec.get("timeout", 30.0))
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(method, f"{url.rstrip('/')}/{path.lstrip('/')}", json=args)
        response.raise_for_status()
        return response.json()
    client = McpHttpClient(url, headers=server_spec.get("headers"), timeout=float(server_spec.get("timeout", 30.0)))
    await client.initialize()
    return await client.call_tool(name, args)


def _policy(settings: Settings, tool_spec: dict[str, Any] | None) -> dict[str, Any]:
    """合并全局默认与工具级覆盖，得到 call_tool_governed 的参数。"""
    spec = tool_spec or {}
    attempts = spec.get("retry_attempts")
    backoff = spec.get("retry_backoff_seconds")
    fallback = dict(spec.get("fallback") or {})
    if not fallback.get("enabled") and settings.tool_fallback_enabled:
        fallback = {"enabled": True, "mode": fallback.get("mode") or "empty", "value": fallback.get("value")}
    return {
        "params": spec.get("params") or [],
        "validate": settings.tool_validate,
        "attempts": settings.tool_retry_attempts if attempts is None else int(attempts),
        "backoff": settings.tool_retry_backoff_seconds if backoff is None else float(backoff),
        "fallback": fallback,
    }


async def _dispatch(
    settings: Settings,
    tool_spec: dict[str, Any],
    server_name: str,
    legacy: dict[str, str],
    tool_name: str,
    args: dict[str, Any],
    tenant_code: str,
) -> Any:
    """解析服务地址并调用——放在 call 闭包里，保证参数校验先于服务解析报错。"""
    server_spec = _server_spec(settings, server_name, tenant_code) if server_name else None
    if server_spec is None and server_name in legacy:
        server_spec = {"url": legacy[server_name], "kind": "http"}
    if server_spec is None:
        raise RuntimeError(f"未知工具服务: {server_name or '(未指定)'}")
    return await _invoke(tool_spec, server_spec, tool_name, args)


async def call_declared_tool(
    settings: Settings, name: str, args: dict[str, Any], *, server: str = "", tenant_code: str = ""
) -> Any:
    """按声明调用一次工具：参数校验 → 瞬时错误重试 → 失败兜底。"""
    tool_spec = _tool_spec(name, tenant_code)
    server_name = server or (tool_spec or {}).get("server") or ""
    call = functools.partial(_dispatch, settings, tool_spec or {}, server_name, {}, name, args, tenant_code)
    return await call_tool_governed(name=name, args=args, call=call, **_policy(settings, tool_spec))


def build_tool_invoker(settings: Settings, servers: dict[str, str] | None = None) -> ToolInvoker:
    legacy = servers or {}

    async def invoke(config: ToolConfig, variables: dict[str, Any], tenant_code: str = "") -> list[Any]:
        results: list[Any] = []
        for ref in config.tools:
            args = _render_args(ref.args, variables)
            try:
                tool_spec = _tool_spec(ref.name, tenant_code)
                server_name = ref.server or (tool_spec or {}).get("server") or ""
                call = functools.partial(
                    _dispatch, settings, tool_spec or {}, server_name, legacy, ref.name, args, tenant_code
                )
                results.append(
                    await call_tool_governed(name=ref.name, args=args, call=call, **_policy(settings, tool_spec))
                )
            except Exception as exc:
                if ref.on_error == "skip":
                    logger.warning("工具 %s 调用失败已跳过：%s", ref.name, exc)
                    continue
                raise
        return results

    return invoke


def build_tool_caller(settings: Settings):
    """给 Agent 用的工具调用入口（参数已是字面值，不再按表达式求值）。"""

    async def call(name: str, args: dict[str, Any], *, server: str = "", tenant_code: str = "") -> Any:
        return await call_declared_tool(settings, name, args, server=server, tenant_code=tenant_code)

    return call
