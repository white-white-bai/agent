"""自主 agent 执行入口：产出与工作流一致的 token/final 契约，供 `_chat_stream` 直接消费。"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessageChunk, HumanMessage, ToolMessage

from agent_platform.agentapp.builder import (
    AGENT_NODE,
    FINALIZE_NODE,
    PLAN_NODE,
    REFLECT_NODE,
    TOOLS_NODE,
    build_agent_graph,
)
from agent_platform.agentapp.schema import AgentAppDef
from agent_platform.agentapp.tools import build_agent_tools
from agent_platform.core.config import get_settings
from agent_platform.engine.context import EngineContext

_INTERRUPT = "__interrupt__"


def _config(checkpointer: Any, thread_id: str | None) -> dict[str, Any]:
    if checkpointer and thread_id:
        return {"configurable": {"thread_id": thread_id}}
    return {}


def _initial(agent_def: AgentAppDef, inputs: dict[str, Any]) -> dict[str, Any]:
    query = str(inputs.get("query") or "")
    return {
        "messages": [HumanMessage(query)],
        "query": query,
        "summary": str(inputs.get("summary") or ""),
        "plan": "",
        "reflections": [],
        "iterations": 0,
    }


def _tool_events(update: Any) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    messages = (update or {}).get("messages") if isinstance(update, dict) else None
    for message in messages or []:
        if isinstance(message, ToolMessage):
            content = message.content
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False, default=str)
            events.append({"tool": getattr(message, "name", "") or "", "content": content[:500]})
    return events


def _interrupt_value(update: Any) -> dict[str, Any]:
    items = update if isinstance(update, (list, tuple)) else [update]
    for item in items:
        value = getattr(item, "value", item)
        if isinstance(value, dict):
            return value
    return {}


async def _pending_interrupt(graph: Any, config: dict[str, Any]) -> dict[str, Any] | None:
    """若该 thread 处于中断暂停态，返回其中断载荷（避免新一轮静默续跑旧中断）。"""
    if not config:
        return None
    snapshot = await graph.aget_state(config)
    if snapshot is None or not getattr(snapshot, "next", None):
        return None
    for task in getattr(snapshot, "tasks", ()) or ():
        for item in getattr(task, "interrupts", ()) or ():
            value = getattr(item, "value", None)
            if isinstance(value, dict):
                return value
    return {}


async def _drive(graph: Any, payload: Any, config: dict[str, Any], sink: list[dict]) -> AsyncIterator[dict[str, Any]]:
    """驱动一张编译好的 agent 图，产出 token / 内部事件 / final。"""
    answer = ""
    interrupt_payload: dict[str, Any] | None = None
    async for mode, chunk in graph.astream(payload, config=config, stream_mode=["messages", "updates"]):
        if mode == "messages":
            message, meta = chunk
            if not isinstance(message, AIMessageChunk) or (meta or {}).get("langgraph_node") != AGENT_NODE:
                continue
            if getattr(message, "tool_call_chunks", None):
                continue
            text = message.content
            if isinstance(text, str) and text:
                answer += text
                yield {"type": "token", "content": text}
            continue
        for node, update in (chunk or {}).items():
            if node == _INTERRUPT:
                interrupt_payload = _interrupt_value(update)
                yield {"type": "agent_interrupt", **interrupt_payload}
            elif node == PLAN_NODE:
                yield {"type": "agent_plan", "plan": (update or {}).get("plan", "")}
            elif node == TOOLS_NODE:
                yield {"type": "agent_tool", "tools": _tool_events(update)}
            elif node == REFLECT_NODE:
                yield {"type": "agent_reflection", "rounds": len((update or {}).get("reflections") or [])}
            elif node == FINALIZE_NODE:
                answer = (update or {}).get("answer") or answer

    if interrupt_payload is not None:
        answer = str(interrupt_payload.get("prompt") or answer)
        yield {
            "type": "final",
            "answer": answer,
            "state": {"variables": {"chunks": list(sink), "answer": answer, "paused": True}},
        }
        return
    yield {"type": "final", "answer": answer, "state": {"variables": {"chunks": list(sink), "answer": answer}}}


async def _prepare(agent_def: AgentAppDef, ctx: EngineContext, checkpointer: Any, thread_id: str | None, tenant_code: str, depth: int):
    settings = get_settings()
    tools, sink = await build_agent_tools(
        agent_def, settings, ctx, tenant_code=tenant_code, thread_id=thread_id or "", depth=depth
    )
    graph = build_agent_graph(agent_def, ctx, tools, checkpointer=checkpointer, max_steps=agent_def.max_steps)
    return graph, sink, _config(checkpointer, thread_id)


async def _close_session(thread_id: str) -> None:
    from agent_platform.tools.browser import close_browser

    await close_browser(thread_id or "")


async def stream_agent(
    agent_def: AgentAppDef,
    inputs: dict[str, Any],
    ctx: EngineContext,
    *,
    checkpointer: Any = None,
    thread_id: str | None = None,
    tenant_code: str = "",
    depth: int = 0,
) -> AsyncIterator[dict[str, Any]]:
    """事件：token（最终答复增量）、agent_plan / agent_tool / agent_reflection / agent_interrupt（内部事件，对外被忽略）、
    最后一条 final（answer + state.variables.chunks）。"""
    try:
        graph, sink, config = await _prepare(agent_def, ctx, checkpointer, thread_id, tenant_code, depth)
        pending = await _pending_interrupt(graph, config)
        if pending is not None:
            # 该会话存在待审批中断：不静默续跑，回传待审批提示，由管理端显式 resume
            prompt = str(pending.get("prompt") or "上一轮工具调用待人工确认。")
            yield {"type": "final", "answer": prompt, "state": {"variables": {"chunks": [], "answer": prompt, "paused": True}}}
            return
        async for item in _drive(graph, _initial(agent_def, inputs), config, sink):
            yield item
    finally:
        await _close_session(thread_id or "")


async def resume_agent(
    agent_def: AgentAppDef,
    resume_value: dict[str, Any],
    ctx: EngineContext,
    *,
    checkpointer: Any,
    thread_id: str,
    tenant_code: str = "",
    depth: int = 0,
) -> AsyncIterator[dict[str, Any]]:
    """对处于中断暂停态的会话续跑（人工批准 / 拒绝）。"""
    from langgraph.types import Command

    try:
        graph, sink, config = await _prepare(agent_def, ctx, checkpointer, thread_id, tenant_code, depth)
        async for item in _drive(graph, Command(resume=resume_value), config, sink):
            yield item
    finally:
        await _close_session(thread_id)


async def run_agent(
    agent_def: AgentAppDef,
    inputs: dict[str, Any],
    ctx: EngineContext,
    *,
    checkpointer: Any = None,
    thread_id: str | None = None,
    tenant_code: str = "",
    depth: int = 0,
) -> dict[str, Any]:
    """非流式版本：返回 {answer, state:{variables:{chunks}}}。"""
    try:
        graph, sink, config = await _prepare(agent_def, ctx, checkpointer, thread_id, tenant_code, depth)
        state = await graph.ainvoke(_initial(agent_def, inputs), config=config)
        answer = str(state.get("answer") or "")
        return {"answer": answer, "state": {"variables": {"chunks": list(sink), "answer": answer}}}
    finally:
        await _close_session(thread_id or "")
