"""执行器：编译、运行、流式。"""
from __future__ import annotations

import inspect
from collections.abc import AsyncIterator
from typing import Any

from langgraph.types import Command

from agent_platform.engine.builder import RUNNERS, build_graph
from agent_platform.engine.context import EngineContext
from agent_platform.engine.state import GraphState
from agent_platform.graph.schema import GraphDef, NodeType


def _config(checkpointer: Any, thread_id: str | None) -> dict[str, Any]:
    if checkpointer and not thread_id:
        raise ValueError("checkpointer 需要 thread_id")
    if checkpointer and thread_id:
        return {"configurable": {"thread_id": thread_id}}
    return {}


class _TokenBuffer:
    """自主循环的 token 过滤：中间轮缓存后丢弃，最终答复轮 flush。"""

    def __init__(self) -> None:
        self._buffers: dict[str, list[str]] = {}

    @staticmethod
    def _run_id(event: dict[str, Any]) -> str:
        return str(event.get("run_id") or "")

    @staticmethod
    def _tags(event: dict[str, Any]) -> list[str]:
        return list(event.get("tags") or [])

    @staticmethod
    def _suppressed(event: dict[str, Any]) -> bool:
        if "agent-suppress" in _TokenBuffer._tags(event):
            return True
        metadata = event.get("metadata") or {}
        return bool(metadata.get("agent-suppress") or metadata.get("agent_suppress"))

    @staticmethod
    def _output_tool_calls(output: Any) -> Any:
        tool_calls = getattr(output, "tool_calls", None)
        if tool_calls is None and isinstance(output, dict):
            tool_calls = output.get("tool_calls")
        if tool_calls is None and hasattr(output, "generations"):
            try:
                tool_calls = getattr(output.generations[0].message, "tool_calls", None)
            except (AttributeError, IndexError, TypeError):
                tool_calls = None
        return tool_calls

    def on_stream(self, event: dict[str, Any]) -> str | None:
        chunk = event.get("data", {}).get("chunk")
        text = getattr(chunk, "content", "") if chunk is not None else ""
        if not isinstance(text, str):
            text = "" if text is None else str(text)
        if not text:
            return None
        if "agent-internal" in self._tags(event):
            self._buffers.setdefault(self._run_id(event), []).append(text)
            return None
        return text

    def on_end(self, event: dict[str, Any]) -> str | None:
        run_id = self._run_id(event)
        buffered = "".join(self._buffers.pop(run_id, []))
        if not buffered:
            return None
        output = event.get("data", {}).get("output")
        if self._output_tool_calls(output) or self._suppressed(event):
            return None
        return buffered


async def run_graph(
    graph_def: GraphDef,
    inputs: dict[str, Any],
    ctx: EngineContext,
    checkpointer: Any = None,
    thread_id: str | None = None,
    *,
    resume: Any = None,
) -> GraphState:
    app = build_graph(graph_def, ctx, checkpointer)
    if isinstance(resume, Command):
        payload = resume
    elif resume is not None:
        payload = Command(resume=resume)
    else:
        payload = {"inputs": inputs}
    return await app.ainvoke(payload, config=_config(checkpointer, thread_id))


async def run_node(
    graph_def: GraphDef,
    node_id: str,
    inputs: dict[str, Any],
    ctx: EngineContext,
) -> dict[str, Any]:
    """单独执行一个节点（编辑器「点节点运行」）。

    不做上游推导：把传入的 inputs 直接当作可用变量，直接调该节点的 runner。
    """
    node = graph_def.node(node_id)
    if node is None:
        raise ValueError(f"节点不存在: {node_id}")
    if node.type == NodeType.APPROVAL:
        raise ValueError("审批节点需整图运行（需要 checkpointer 与 thread_id）")
    runner = RUNNERS[node.type]
    state: GraphState = {"inputs": dict(inputs), "variables": dict(inputs)}
    tracer = getattr(ctx, "tracer", None)
    if tracer is not None and getattr(tracer, "enabled", False):
        # 单节点运行不走 build_graph，这里手动补一个节点 span
        with tracer.node_span(node_id, node.type.value, payload=state["variables"]) as span:
            outcome = runner(node, state, ctx)
            result: GraphState = await outcome if inspect.isawaitable(outcome) else outcome
            span.end(output=result.get("variables"))
    else:
        outcome = runner(node, state, ctx)
        result = await outcome if inspect.isawaitable(outcome) else outcome
    variables = result.get("variables", {})
    # 多数节点把产出写在 variables[node_id]；answer/end 写在 answer，condition/classifier 写在 route
    output = variables.get(node_id)
    if output is None:
        output = result.get("answer") or result.get("route") or None
    return {
        "node_id": node_id,
        "node_type": node.type.value,
        "route": result.get("route", ""),
        "answer": result.get("answer", ""),
        "output": output,
        "variables": variables,
    }


async def stream_graph(
    graph_def: GraphDef,
    inputs: dict[str, Any],
    ctx: EngineContext,
    checkpointer: Any = None,
    thread_id: str | None = None,
    *,
    resume: Any = None,
    allow_interrupt: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    """产出节点进度、token 增量与最终态。

    事件：{"type": "node_start"|"node_end"|...}、{"type": "token", "content": str} ... 最后
    {"type": "final", "answer": str, "state": GraphState}。

    注意：对外对话链路（`api/main.py::_chat_stream`）只识别 token/final，未知事件被忽略，
    因此这里新增事件类型不会改变对外 SSE 契约。
    """
    app = build_graph(graph_def, ctx, checkpointer)
    config = _config(checkpointer, thread_id)
    node_ids = {node.id for node in graph_def.nodes}
    titles = {node.id: (node.title or node.type.value) for node in graph_def.nodes}
    final_state: GraphState = {}
    tokens = _TokenBuffer()
    if thread_id:
        yield {"type": "run_started", "thread_id": thread_id}
    if isinstance(resume, Command):
        payload = resume
    elif resume is not None:
        payload = Command(resume=resume)
    else:
        payload = {"inputs": inputs}
    async for event in app.astream_events(payload, config=config, version="v2"):
        kind = event.get("event")
        name = event.get("name")
        if kind == "on_chain_start" and name in node_ids:
            yield {"type": "node_start", "node": name, "title": titles.get(name, name)}
        elif kind == "on_chain_end" and name in node_ids:
            output = event.get("data", {}).get("output")
            variables = output.get("variables") if isinstance(output, dict) else {}
            yield {"type": "node_end", "node": name, "variables": variables or {}}
        elif kind == "on_chat_model_stream":
            text = tokens.on_stream(event)
            if text:
                yield {"type": "token", "content": text}
        elif kind == "on_chat_model_end":
            text = tokens.on_end(event)
            if text:
                yield {"type": "token", "content": text}
        elif kind == "on_chain_end" and name == "LangGraph":
            output = event.get("data", {}).get("output")
            if isinstance(output, dict):
                final_state = output

    if checkpointer and thread_id:
        snapshot = await app.aget_state(config)
        if snapshot.values:
            final_state = snapshot.values
        if allow_interrupt and snapshot.interrupts:
            yield {
                "type": "interrupt",
                "thread_id": thread_id,
                "checkpoint_id": (snapshot.config.get("configurable") or {}).get("checkpoint_id", ""),
                "interrupts": [
                    {"id": item.id, "value": item.value} for item in snapshot.interrupts
                ],
            }
    yield {"type": "final", "answer": final_state.get("answer", ""), "state": final_state}
