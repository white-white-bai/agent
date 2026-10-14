"""MCP Client / 工具桥：JSON-RPC 调用、会话头、SSE 解析与外部工具服务解析。"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from agent_platform.core.config import Settings
from agent_platform.core.db import session_scope
from agent_platform.domain.models import McpServer
from agent_platform.graph.schema import ToolConfig, ToolRef
from agent_platform.tools import mcp_bridge as bridge_mod
from agent_platform.tools import mcp_client as client_mod
from agent_platform.tools.mcp_bridge import _render_args, build_tool_invoker
from agent_platform.tools.mcp_client import PROTOCOL_VERSION, McpError, McpHttpClient, _parse_response


def _patch_http(monkeypatch, module, handler):
    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        return real_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(module.httpx, "AsyncClient", factory)


def _mcp_handler(
    requests: list[httpx.Request],
    *,
    session_id: str = "sess-1",
    tools: list[dict[str, Any]] | None = None,
    is_error: bool = False,
    rpc_error: Any = None,
    methods_with_error: tuple[str, ...] = ("tools/call",),
):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = json.loads(request.content)
        method = payload["method"]
        headers = {}
        body: dict[str, Any] = {"jsonrpc": "2.0", "id": payload["id"]}
        result: dict[str, Any] = {}
        if method == "initialize":
            headers["Mcp-Session-Id"] = session_id
            result = {"protocolVersion": PROTOCOL_VERSION, "serverInfo": {"name": "demo"}}
        elif method == "tools/list":
            result = {"tools": tools if tools is not None else [{"name": "weather"}]}
        elif method == "tools/call":
            result = {"isError": is_error, "content": [{"type": "text", "text": "ok"}]}
        if rpc_error is not None and method in methods_with_error:
            body["error"] = rpc_error
        else:
            body["result"] = result
        return httpx.Response(200, json=body, headers=headers)

    return handler


def _seed_server(*, name: str, tenant_code: str, url: str = "", kind: str = "mcp") -> None:
    with session_scope() as session:
        session.add(
            McpServer(
                uuid=f"{name}-uuid",
                tenant_code=tenant_code,
                name=name,
                kind=kind,
                url=url or f"https://{name}.local/mcp",
                headers={"X-Tenant": tenant_code},
            )
        )


# --------------------------------------------------------------------------- 响应解析


def test_parse_response_reads_json_body():
    response = httpx.Response(200, json={"result": {"tools": []}})
    assert _parse_response(response) == {"result": {"tools": []}}


def test_parse_response_reads_last_sse_data_line():
    response = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        text='event: message\ndata: {"id": 1}\n\ndata: {"id": 2, "result": {}}\n\n',
    )
    assert _parse_response(response) == {"id": 2, "result": {}}


def test_parse_response_rejects_empty_event_stream():
    response = httpx.Response(200, headers={"content-type": "text/event-stream"}, text="event: ping\n\n")
    with pytest.raises(McpError, match="MCP 事件流响应为空"):
        _parse_response(response)


# --------------------------------------------------------------------------- 客户端


@pytest.mark.asyncio
async def test_initialize_captures_session_id_and_reuses_it(monkeypatch):
    requests: list[httpx.Request] = []
    _patch_http(monkeypatch, client_mod, _mcp_handler(requests))
    client = McpHttpClient("https://mcp.local/rpc", headers={"X-Api-Key": "k"})

    result = await client.initialize()
    assert result["protocolVersion"] == PROTOCOL_VERSION
    assert client._session_id == "sess-1"

    first, second = requests[0], requests[1]
    assert str(first.url) == "https://mcp.local/rpc"
    assert first.headers["content-type"] == "application/json"
    assert first.headers["accept"] == "application/json, text/event-stream"
    assert first.headers["x-api-key"] == "k"
    assert "mcp-session-id" not in first.headers
    assert json.loads(first.content) == {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "agent-platform", "version": "0.1.0"},
        },
    }
    assert second.headers["mcp-session-id"] == "sess-1"
    assert json.loads(second.content)["method"] == "notifications/initialized"


@pytest.mark.asyncio
async def test_initialize_tolerates_failing_notification(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["method"] == "notifications/initialized":
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(200, json={"id": 1, "result": {"ok": True}})

    _patch_http(monkeypatch, client_mod, handler)
    assert await McpHttpClient("https://mcp.local/rpc").initialize() == {"ok": True}


@pytest.mark.asyncio
async def test_list_tools_and_call_tool(monkeypatch):
    requests: list[httpx.Request] = []
    handler = _mcp_handler(requests, tools=[{"name": "weather", "description": "查询天气"}])
    _patch_http(monkeypatch, client_mod, handler)
    client = McpHttpClient("https://mcp.local/rpc")

    assert await client.list_tools() == [{"name": "weather", "description": "查询天气"}]
    result = await client.call_tool("weather", {"city": "常州"})
    assert result["isError"] is False
    assert json.loads(requests[-1].content) == {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "weather", "arguments": {"city": "常州"}},
    }


@pytest.mark.asyncio
async def test_call_tool_raises_on_tool_error(monkeypatch):
    _patch_http(monkeypatch, client_mod, _mcp_handler([], is_error=True))
    with pytest.raises(McpError, match="MCP 工具执行失败: weather"):
        await McpHttpClient("https://mcp.local/rpc").call_tool("weather", {})


@pytest.mark.asyncio
async def test_rpc_error_payload_becomes_mcp_error(monkeypatch):
    handler = _mcp_handler([], rpc_error={"code": -32601, "message": "Method not found"}, methods_with_error=("tools/list",))
    _patch_http(monkeypatch, client_mod, handler)
    with pytest.raises(McpError, match="Method not found"):
        await McpHttpClient("https://mcp.local/rpc").list_tools()


@pytest.mark.asyncio
async def test_rpc_propagates_http_error_status(monkeypatch):
    _patch_http(monkeypatch, client_mod, lambda request: httpx.Response(503, text="down"))
    with pytest.raises(httpx.HTTPStatusError):
        await McpHttpClient("https://mcp.local/rpc").list_tools()


# --------------------------------------------------------------------------- 工具桥


def test_render_args_evaluates_strings_and_passes_through_literals():
    rendered = _render_args(
        {"city": "query", "limit": 3, "flag": True, "nested": {"k": "query"}},
        {"query": "常州"},
    )
    assert rendered["city"] == "常州"
    assert rendered["limit"] == 3
    assert rendered["flag"] is True
    assert rendered["nested"] == {"k": "query"}


@pytest.mark.asyncio
async def test_tool_invoker_calls_http_bridge(monkeypatch):
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"echo": "常州"})

    _patch_http(monkeypatch, bridge_mod, handler)
    settings = Settings(tool_servers={"demo": {"url": "https://demo.local/api/", "kind": "http"}})
    invoke = build_tool_invoker(settings)
    config = ToolConfig(tools=[ToolRef(name="echo", server="demo", args={"city": "query"})])

    assert await invoke(config, {"query": "常州"}, "t") == [{"echo": "常州"}]
    assert str(captured[0].url) == "https://demo.local/api/tools/echo"
    assert json.loads(captured[0].content) == {"city": "常州"}


@pytest.mark.asyncio
async def test_tool_invoker_calls_mcp_server(monkeypatch):
    requests: list[httpx.Request] = []
    _patch_http(monkeypatch, client_mod, _mcp_handler(requests))
    settings = Settings(tool_servers={"demo": {"url": "https://demo.local/mcp"}})
    invoke = build_tool_invoker(settings)
    config = ToolConfig(tools=[ToolRef(name="weather", server="demo", args={"city": "query"})])

    results = await invoke(config, {"query": "常州"}, "t")
    assert results[0]["isError"] is False
    assert [json.loads(request.content)["method"] for request in requests] == [
        "initialize",
        "notifications/initialized",
        "tools/call",
    ]
    assert json.loads(requests[-1].content)["params"] == {
        "name": "weather",
        "arguments": {"city": "常州"},
    }


@pytest.mark.asyncio
async def test_tool_invoker_falls_back_to_legacy_servers_map(monkeypatch):
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"ok": True})

    _patch_http(monkeypatch, bridge_mod, handler)
    invoke = build_tool_invoker(Settings(), servers={"legacy": "https://legacy.local/api"})
    config = ToolConfig(tools=[ToolRef(name="ping", server="legacy")])

    assert await invoke(config, {}, "t") == [{"ok": True}]
    assert str(captured[0].url) == "https://legacy.local/api/tools/ping"


@pytest.mark.asyncio
async def test_tool_invoker_resolves_server_from_database(monkeypatch):
    requests: list[httpx.Request] = []
    _patch_http(monkeypatch, client_mod, _mcp_handler(requests))
    _seed_server(name="db-tool", tenant_code="t", url="https://db.local/mcp")
    invoke = build_tool_invoker(Settings())
    config = ToolConfig(tools=[ToolRef(name="weather", server="db-tool")])

    results = await invoke(config, {}, "t")
    assert results[0]["isError"] is False
    assert str(requests[0].url) == "https://db.local/mcp"
    assert requests[0].headers["x-tenant"] == "t"


@pytest.mark.asyncio
async def test_tool_invoker_rejects_unknown_server():
    invoke = build_tool_invoker(Settings())
    config = ToolConfig(tools=[ToolRef(name="weather", server="ghost")])
    with pytest.raises(RuntimeError, match="未知工具服务: ghost"):
        await invoke(config, {}, "t")

    unset = ToolConfig(tools=[ToolRef(name="weather")])
    with pytest.raises(RuntimeError, match=r"未知工具服务: \(未指定\)"):
        await invoke(unset, {}, "t")


@pytest.mark.asyncio
async def test_tool_invoker_rejects_other_tenant_server():
    _seed_server(name="db-tool", tenant_code="other")
    invoke = build_tool_invoker(Settings())
    config = ToolConfig(tools=[ToolRef(name="weather", server="db-tool")])
    with pytest.raises(RuntimeError, match="未知工具服务: db-tool"):
        await invoke(config, {}, "t")


@pytest.mark.asyncio
async def test_tool_invoker_skips_soft_deleted_server():
    _seed_server(name="db-tool", tenant_code="t")
    with session_scope() as session:
        session.query(McpServer).filter(McpServer.name == "db-tool").update({"is_deleted": 1})
    invoke = build_tool_invoker(Settings())
    config = ToolConfig(tools=[ToolRef(name="weather", server="db-tool")])
    with pytest.raises(RuntimeError, match="未知工具服务: db-tool"):
        await invoke(config, {}, "t")


@pytest.mark.asyncio
async def test_tool_invoker_collects_multiple_refs(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"path": request.url.path})

    _patch_http(monkeypatch, bridge_mod, handler)
    settings = Settings(tool_servers={"demo": {"url": "https://demo.local", "kind": "http"}})
    invoke = build_tool_invoker(settings)
    config = ToolConfig(
        tools=[ToolRef(name="a", server="demo"), ToolRef(name="b", server="demo")],
        output_var="out",
    )
    assert await invoke(config, {}, "t") == [{"path": "/tools/a"}, {"path": "/tools/b"}]
