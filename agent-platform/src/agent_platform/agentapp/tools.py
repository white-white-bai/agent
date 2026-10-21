"""把声明式工具 / 知识检索 / 子 agent 转成 LangChain 工具，供原生 function-calling 循环绑定。

执行统一复用 `tools/mcp_bridge.py::call_declared_tool`，白拿参数校验 / 重试 / 兜底治理。
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import Field, create_model

from agent_platform.agentapp.schema import AgentAppDef, AgentToolRef
from agent_platform.core.config import Settings
from agent_platform.core.prompt_guard import sanitize_untrusted
from agent_platform.engine.context import EngineContext
from agent_platform.graph.schema import KnowledgeConfig
from agent_platform.tools.mcp_bridge import _server_spec, _tool_spec, call_declared_tool
from agent_platform.tools.mcp_client import McpHttpClient

logger = logging.getLogger(__name__)

_TYPE_MAP: dict[str, type] = {
    "string": str,
    "text": str,
    "number": float,
    "integer": int,
    "float": float,
    "boolean": bool,
    "bool": bool,
    "array": list,
    "list": list,
    "object": dict,
    "dict": dict,
}

KNOWLEDGE_TOOL = "knowledge_search"
DELEGATE_PREFIX = "delegate_"


def _text(value: Any) -> str:
    import json

    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def _guard(settings: Settings, value: Any, source: str) -> Any:
    if not getattr(settings, "prompt_guard_enabled", False):
        return value
    return sanitize_untrusted(
        value,
        source=source,
        max_chars=int(getattr(settings, "prompt_guard_max_chars", 12000) or 12000),
    )


def _args_schema(tool_name: str, params: list[dict[str, Any]]) -> type:
    """由 ap_tool.params 生成本工具的 pydantic 入参模型（供 bind_tools 用）。"""
    fields: dict[str, Any] = {}
    for spec in params or []:
        if not isinstance(spec, dict):
            continue
        name = str(spec.get("name") or "")
        if not name:
            continue
        py_type = _TYPE_MAP.get(str(spec.get("type") or "string").lower(), str)
        description = str(spec.get("description") or "")
        if spec.get("required"):
            fields[name] = (py_type, Field(..., description=description))
        else:
            fields[name] = (py_type | None, Field(default=None, description=description))
    return create_model(f"{tool_name}_args", **fields)


def _schema_model(tool_name: str, schema: dict[str, Any] | None) -> type:
    """由 MCP tools/list 的 JSON Schema 生成 pydantic 入参模型。"""
    schema = schema or {}
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    fields: dict[str, Any] = {}
    for prop, spec in properties.items():
        spec = spec if isinstance(spec, dict) else {}
        py_type = _TYPE_MAP.get(str(spec.get("type") or "string").lower(), str)
        description = str(spec.get("description") or "")
        if prop in required:
            fields[str(prop)] = (py_type, Field(..., description=description))
        else:
            fields[str(prop)] = (py_type | None, Field(default=None, description=description))
    return create_model(f"{tool_name}_args", **fields)


def _declared_tool(ref: AgentToolRef, settings: Settings, tenant_code: str) -> StructuredTool:
    spec = _tool_spec(ref.name, tenant_code) or {}
    params = list(spec.get("params") or [])
    description = str(spec.get("description") or spec.get("label") or ref.name)
    server = ref.server or str(spec.get("server") or "")

    async def _run(**kwargs: Any) -> Any:
        args = {key: value for key, value in kwargs.items() if value is not None}
        result = await call_declared_tool(settings, ref.name, args, server=server, tenant_code=tenant_code)
        return _guard(settings, result, ref.name)

    return StructuredTool.from_function(
        coroutine=_run,
        name=ref.name,
        description=description,
        args_schema=_args_schema(ref.name, params),
    )


def _knowledge_tool(
    agent_def: AgentAppDef, settings: Settings, ctx: EngineContext, tenant_code: str, sink: list[dict]
) -> StructuredTool:
    config: KnowledgeConfig = agent_def.knowledge

    async def _run(query: str) -> str:
        chunks = await ctx.retriever(config, query, tenant_code)
        hits = list(chunks or [])
        known = {str(item.get("content") or "") for item in sink}
        for item in hits:
            key = str(item.get("content") or "")
            if key and key not in known:
                known.add(key)
                sink.append(item)
        if not hits:
            return _guard(settings, "（未检索到资料）", KNOWLEDGE_TOOL)
        text = "\n\n".join(
            f"[{index + 1}] {item.get('content', '')}" for index, item in enumerate(hits)
        )
        return _guard(settings, text, KNOWLEDGE_TOOL)

    return StructuredTool.from_function(
        coroutine=_run,
        name=KNOWLEDGE_TOOL,
        description="检索知识库，返回与查询最相关的资料片段。",
        args_schema=create_model("knowledge_search_args", query=(str, Field(..., description="检索问题"))),
    )


def _sub_agent_tool(code: str, agent_def: AgentAppDef, settings: Settings, ctx: EngineContext,
                    tenant_code: str, thread_id: str, depth: int) -> StructuredTool:
    from agent_platform.agentapp.runtime import run_agent  # 延迟导入避免循环
    from agent_platform.engine.agents.registry import load_agent

    async def _run(query: str) -> str:
        if depth >= settings.agent_app_depth:
            return "委派深度已达上限，请自行作答。"
        sub_spec = load_agent(code, tenant_code, settings.agent_app_max_steps)
        sub_def = agent_def_from_spec(sub_spec)
        result = await run_agent(
            sub_def, {"query": query}, ctx, checkpointer=None, thread_id=f"{thread_id}:{code}",
            tenant_code=tenant_code, depth=depth + 1,
        )
        return _guard(settings, str(result.get("answer") or ""), f"{DELEGATE_PREFIX}{code}")

    return StructuredTool.from_function(
        coroutine=_run,
        name=f"{DELEGATE_PREFIX}{code}",
        description=f"把子任务委派给智能体 {code}，参数为 query。",
        args_schema=create_model(f"{DELEGATE_PREFIX}{code}_args", query=(str, Field(..., description="子任务"))),
    )


def agent_def_from_spec(spec: Any) -> AgentAppDef:
    """把旧 ap_agent 定义（AgentSpec）映射为 AgentAppDef，供子 agent 委派复用。"""
    return AgentAppDef(
        name=spec.label or spec.code,
        instructions=spec.system_prompt or "",
        provider=spec.provider or "",
        temperature=float(spec.temperature if spec.temperature is not None else 0.3),
        max_tokens=spec.max_tokens,
        tools=[AgentToolRef(name=ref.name, server=ref.server) for ref in (spec.tools or [])],
        knowledge=KnowledgeConfig(
            retriever=str((spec.retriever or {}).get("retriever") or "builtin"),
            dataset_ids=[str(item) for item in ((spec.retriever or {}).get("dataset_ids") or [])],
            top_k=int((spec.retriever or {}).get("top_k") or 5),
        ),
        max_steps=int(spec.max_steps or 6),
    )


async def _append_mcp_tools(
    server_name: str, settings: Settings, tenant_code: str, tools: list[StructuredTool]
) -> None:
    """从 MCP Server 动态发现工具（tools/list），失败只记日志、不阻断 agent。"""
    spec = _server_spec(settings, server_name, tenant_code)
    if not spec:
        logger.warning("未知 MCP Server：%s", server_name)
        return
    client = McpHttpClient(
        str(spec.get("url") or ""),
        headers=spec.get("headers"),
        timeout=float(spec.get("timeout", 30.0)),
    )
    try:
        await client.initialize()
        definitions = await client.list_tools()
    except Exception as exc:  # noqa: BLE001 - 发现失败降级为「该 server 无工具」
        logger.warning("MCP Server %s 工具发现失败：%s", server_name, exc)
        return

    for item in definitions or []:
        name = str(item.get("name") or "")
        if not name:
            continue

        async def _run(_name: str = name, **kwargs: Any) -> Any:
            args = {key: value for key, value in kwargs.items() if value is not None}
            result = await client.call_tool(_name, args)
            return _guard(settings, result, _name)

        tools.append(
            StructuredTool.from_function(
                coroutine=_run,
                name=name,
                description=str(item.get("description") or name),
                args_schema=_schema_model(name, item.get("inputSchema")),
            )
        )


async def build_agent_tools(
    agent_def: AgentAppDef,
    settings: Settings,
    ctx: EngineContext,
    *,
    tenant_code: str = "",
    thread_id: str = "",
    depth: int = 0,
) -> tuple[list[StructuredTool], list[dict]]:
    """构建本 agent 的可用工具；返回 (工具列表, 检索命中的收集槽)。

    收集槽由调用方持有，最终作为 chunks 供 retriever_resources 使用。
    """
    tools: list[StructuredTool] = []
    for ref in agent_def.tools:
        tools.append(_declared_tool(ref, settings, tenant_code))
    sink: list[dict] = []
    if agent_def.knowledge_as_tool and agent_def.knowledge.dataset_ids:
        tools.append(_knowledge_tool(agent_def, settings, ctx, tenant_code, sink))
    for code in agent_def.sub_agents:
        tools.append(_sub_agent_tool(code, agent_def, settings, ctx, tenant_code, thread_id, depth))
    for server_name in agent_def.mcp_servers:
        await _append_mcp_tools(server_name, settings, tenant_code, tools)
    return tools, sink
