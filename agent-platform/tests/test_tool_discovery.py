"""工具 schema 转换与 MCP 运行时发现。"""
from __future__ import annotations

import pytest

from agent_platform.api import services
from agent_platform.core.config import Settings
from agent_platform.graph.schema import ToolRef
from agent_platform.tools import discovery as discovery_mod
from agent_platform.tools import mcp_bridge
from agent_platform.tools.mcp_bridge import ResolvedTool, ToolBox
from agent_platform.tools.mcp_client import McpHttpClient
from agent_platform.tools.schema import (
    from_mcp_tool,
    params_to_json_schema,
    safe_function_name,
    schema_to_params,
)


@pytest.fixture(autouse=True)
def _clear_discovery_cache():
    discovery_mod.clear_discovery_cache()
    yield
    discovery_mod.clear_discovery_cache()


def test_safe_function_name_replaces_dots_and_illegal_chars():
    assert safe_function_name("gov.business.query") == "gov_business_query"
    assert safe_function_name("123-tool") == "t_123-tool"
    assert safe_function_name("") == "tool"


def test_params_to_json_schema_maps_types_and_required():
    schema = params_to_json_schema(
        [
            {"name": "keyword", "type": "string", "required": True, "description": "关键词"},
            {"name": "page", "type": "number"},
            {"name": "tags", "type": "array[string]"},
            {"name": "level", "type": "string", "enum": ["a", "b"]},
            {"name": "optional", "type": "string", "required": "false"},
        ]
    )
    assert schema["type"] == "object"
    assert schema["required"] == ["keyword"]
    assert schema["properties"]["keyword"] == {"type": "string", "description": "关键词"}
    assert schema["properties"]["page"]["type"] == "number"
    assert schema["properties"]["tags"] == {"type": "array", "items": {"type": "string"}}
    assert schema["properties"]["level"]["enum"] == ["a", "b"]


def test_from_mcp_tool_uses_input_schema_and_params():
    tool, params = from_mcp_tool(
        {
            "name": "weather.lookup",
            "description": "查天气",
            "inputSchema": {
                "type": "object",
                "properties": {"city": {"type": "string", "description": "城市"}},
                "required": ["city"],
            },
        }
    )
    assert tool["function"]["name"] == "weather_lookup"
    assert tool["function"]["description"] == "查天气"
    assert tool["function"]["parameters"]["required"] == ["city"]
    assert params == [{"name": "city", "type": "string", "required": True, "description": "城市"}]


def test_schema_to_params_handles_empty_schema():
    assert schema_to_params(None) == []
    assert schema_to_params({}) == []
    assert schema_to_params({"type": "object"}) == []


async def test_discover_server_tools_disabled_does_not_call_server(monkeypatch):
    called = {"spec": 0}
    monkeypatch.setattr(
        mcp_bridge,
        "_server_spec",
        lambda settings, name, tenant: called.__setitem__("spec", called["spec"] + 1) or {"url": "x"},
    )
    settings = Settings(tool_discovery_enabled=False)
    assert await discovery_mod.discover_server_tools(settings, "demo", "t") == []
    assert called["spec"] == 0


async def test_discover_server_tools_returns_normalized_and_caches(monkeypatch):
    list_calls = {"n": 0}

    async def fake_initialize(self):
        return {}

    async def fake_list(self):
        list_calls["n"] += 1
        return [
            {"name": "weather", "description": "查天气", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "", "description": "无名"},
        ]

    monkeypatch.setattr(McpHttpClient, "initialize", fake_initialize)
    monkeypatch.setattr(McpHttpClient, "list_tools", fake_list)
    monkeypatch.setattr(
        mcp_bridge,
        "_server_spec",
        lambda settings, name, tenant: {"url": "https://mcp.local/rpc", "kind": "mcp", "headers": {}},
    )
    settings = Settings(tool_discovery_enabled=True, tool_discovery_ttl_seconds=300)

    first = await discovery_mod.discover_server_tools(settings, "demo", "t")
    second = await discovery_mod.discover_server_tools(settings, "demo", "t")

    assert list_calls["n"] == 1
    assert first == second
    assert first == [
        {
            "name": "weather",
            "description": "查天气",
            "inputSchema": {"type": "object", "properties": {}},
            "server": "demo",
        }
    ]


async def test_discover_server_tools_failure_degrades_to_empty(monkeypatch):
    async def fake_initialize(self):
        return {}

    async def fake_list(self):
        raise RuntimeError("offline")

    monkeypatch.setattr(McpHttpClient, "initialize", fake_initialize)
    monkeypatch.setattr(McpHttpClient, "list_tools", fake_list)
    monkeypatch.setattr(
        mcp_bridge,
        "_server_spec",
        lambda settings, name, tenant: {"url": "https://mcp.local/rpc", "kind": "mcp", "headers": {}},
    )
    settings = Settings(tool_discovery_enabled=True)

    assert await discovery_mod.discover_server_tools(settings, "demo", "t") == []


async def test_toolbox_schemas_for_declared_tool():
    services.create_tool(
        tenant_code="t",
        name="gov.business.query",
        label="业务查询",
        server="demo",
        kind="http",
        params=[{"name": "keyword", "type": "string", "required": True}],
    )
    toolbox = ToolBox(Settings())

    schemas, mapping = await toolbox.schemas([ToolRef(name="gov.business.query", server="demo")], "t")

    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == "gov_business_query"
    assert schemas[0]["function"]["parameters"]["required"] == ["keyword"]
    assert mapping["gov_business_query"].ref.name == "gov.business.query"
    assert mapping["gov_business_query"].params == [{"name": "keyword", "type": "string", "required": True}]


async def test_toolbox_schemas_expands_discovered_server(monkeypatch):
    async def fake_discover(settings, server, tenant_code=""):
        return [
            {
                "name": "weather.lookup",
                "description": "查天气",
                "inputSchema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
                "server": server,
            }
        ]

    monkeypatch.setattr(mcp_bridge, "discover_server_tools", fake_discover)
    toolbox = ToolBox(Settings(tool_discovery_enabled=True))

    schemas, mapping = await toolbox.schemas([ToolRef(name="", server="demo", discover=True)], "t")

    assert schemas[0]["function"]["name"] == "weather_lookup"
    binding = mapping["weather_lookup"]
    assert binding.ref.name == "weather.lookup"
    assert binding.ref.server == "demo"
    assert binding.params == [{"name": "city", "type": "string", "required": True}]


async def test_toolbox_call_passes_resolved_params(monkeypatch):
    captured: list[tuple] = []

    async def fake_call(settings, name, args, *, server="", tenant_code="", params=None):
        captured.append((name, args, server, tenant_code, params))
        return {"ok": True}

    monkeypatch.setattr(mcp_bridge, "call_declared_tool", fake_call)
    toolbox = ToolBox(Settings())
    binding = ResolvedTool(
        ref=ToolRef(name="weather.lookup", server="demo"),
        params=[{"name": "city", "type": "string", "required": True}],
    )

    result = await toolbox.call(binding, {"city": "常州"}, "t")

    assert result == {"ok": True}
    assert captured == [
        (
            "weather.lookup",
            {"city": "常州"},
            "demo",
            "t",
            [{"name": "city", "type": "string", "required": True}],
        )
    ]
