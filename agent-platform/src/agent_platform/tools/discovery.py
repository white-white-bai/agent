"""MCP 工具运行时发现：tools/list + TTL 缓存。

默认关闭（AP_TOOL_DISCOVERY_ENABLED=false）；关闭时调用方不应发起发现请求。
发现结果不落库，只作为当前请求的工具候选。
"""
from __future__ import annotations

import logging
import time
from typing import Any

from agent_platform.core.config import Settings
from agent_platform.tools.mcp_client import McpHttpClient

logger = logging.getLogger(__name__)

_CACHE: dict[tuple[str, str], tuple[float, list[dict[str, Any]]]] = {}


def clear_discovery_cache() -> None:
    _CACHE.clear()


def _normalize(tool: dict[str, Any], server: str) -> dict[str, Any] | None:
    if not isinstance(tool, dict):
        return None
    name = str(tool.get("name") or "").strip()
    if not name:
        return None
    return {
        "name": name,
        "description": str(tool.get("description") or ""),
        "inputSchema": tool.get("inputSchema") or tool.get("input_schema") or {},
        "server": server,
    }


async def discover_server_tools(
    settings: Settings,
    server_name: str,
    tenant_code: str = "",
) -> list[dict[str, Any]]:
    """发现一个 MCP Server 的工具；失败时返回空列表，不阻断对话。"""
    if not settings.tool_discovery_enabled or not server_name:
        return []

    ttl = max(float(settings.tool_discovery_ttl_seconds or 0), 0.0)
    key = (server_name, tenant_code)
    now = time.monotonic()
    if ttl > 0:
        cached = _CACHE.get(key)
        if cached is not None and now - cached[0] < ttl:
            return list(cached[1])

    # 局部导入避免 discovery ↔ mcp_bridge 的循环依赖。
    from agent_platform.tools.mcp_bridge import _server_spec

    spec = _server_spec(settings, server_name, tenant_code)
    if spec is None:
        logger.warning("MCP 工具发现跳过：未知服务 %s", server_name)
        return []
    if str(spec.get("kind") or "mcp").lower() != "mcp":
        return []
    url = str(spec.get("url") or "")
    if not url:
        return []

    client = McpHttpClient(
        url,
        headers=spec.get("headers"),
        timeout=float(spec.get("timeout", 30.0)),
    )
    try:
        await client.initialize()
        raw_tools = await client.list_tools()
    except Exception as exc:  # noqa: BLE001 - 发现失败只降级
        logger.warning("MCP 工具发现失败（%s）：%s", server_name, exc)
        return []

    limit = max(int(settings.tool_discovery_max_tools or 0), 1)
    tools = [item for item in (_normalize(tool, server_name) for tool in raw_tools[:limit]) if item]
    if ttl > 0:
        _CACHE[key] = (now, tools)
    return list(tools)
