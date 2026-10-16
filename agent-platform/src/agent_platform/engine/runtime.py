"""执行器：编译、运行、流式。"""
from __future__ import annotations

import inspect
from collections.abc import AsyncIterator
from typing import Any

from agent_platform.engine.builder import RUNNERS, build_graph
from agent_platform.engine.context import EngineContext
from agent_platform.engine.state import GraphState
from agent_platform.graph.schema import GraphDef


def _config(checkpointer: Any, thread_id: str | None) -> dict[str, Any]:
    if checkpointer and thread_id:
        return {"configurable": {"thread_id": thread_id}}
    return {}


async def run_graph(
    graph_def: GraphDef,
    inputs: dict[str, Any],
    ctx: EngineContext,
    checkpointer: Any = None,
    thread_id: str | None = None,
) -> GraphState:
    app = build_graph(graph_def, ctx, checkpointer)
    return await app.ainvoke({"inputs": inputs}, config=_config(checkpointer, thread_id))


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
    async for event in app.astream_events({"inputs": inputs}, config=config, version="v2"):
        kind = event.get("event")
        name = event.get("name")
        if kind == "on_chain_start" and name in node_ids:
            yield {"type": "node_start", "node": name, "title": titles.get(name, name)}
        elif kind == "on_chain_end" and name in node_ids:
            output = event.get("data", {}).get("output")
            variables = output.get("variables") if isinstance(output, dict) else {}
            yield {"type": "node_end", "node": name, "variables": variables or {}}
        elif kind == "on_chat_model_stream":
            chunk = event.get("data", {}).get("chunk")
            text = getattr(chunk, "content", "") if chunk is not None else ""
            if text:
                yield {"type": "token", "content": text}
        elif kind == "on_chain_end" and name == "LangGraph":
            output = event.get("data", {}).get("output")
            if isinstance(output, dict):
                final_state = output
    yield {"type": "final", "answer": final_state.get("answer", ""), "state": final_state}
