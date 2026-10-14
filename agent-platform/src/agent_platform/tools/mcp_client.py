"""MCP Client：以 Streamable HTTP + JSON-RPC 2.0 接入外部真 MCP Server。"""
from __future__ import annotations

import json
from typing import Any

import httpx

PROTOCOL_VERSION = "2025-06-18"


class McpError(Exception):
    pass


def _parse_response(response: httpx.Response) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        payload: dict[str, Any] | None = None
        for line in response.text.splitlines():
            if line.startswith("data:"):
                chunk = line[5:].strip()
                if chunk:
                    payload = json.loads(chunk)
        if payload is None:
            raise McpError("MCP 事件流响应为空")
        return payload
    return response.json()


class McpHttpClient:
    """单个 MCP Server 的 Streamable HTTP 客户端（无状态：每次请求带 session header）。"""

    def __init__(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        client_name: str = "agent-platform",
    ) -> None:
        self.url = url
        self.headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if headers:
            self.headers.update(headers)
        self.timeout = timeout
        self.client_name = client_name
        self._session_id = ""
        self._request_id = 0

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        headers = dict(self.headers)
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        body = {"jsonrpc": "2.0", "id": self._next_id(), "method": method, "params": params or {}}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.url, json=body, headers=headers)
        response.raise_for_status()
        session_id = response.headers.get("Mcp-Session-Id")
        if session_id:
            self._session_id = session_id
        payload = _parse_response(response)
        if payload.get("error"):
            raise McpError(str(payload["error"]))
        return payload.get("result", {})

    async def initialize(self) -> dict[str, Any]:
        result = await self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": self.client_name, "version": "0.1.0"},
            },
        )
        try:
            await self._rpc("notifications/initialized")
        except Exception:  # noqa: BLE001, S110
            pass
        return result

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._rpc("tools/list")
        return result.get("tools", [])

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        result = await self._rpc("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise McpError(f"MCP 工具执行失败: {name}")
        return result
