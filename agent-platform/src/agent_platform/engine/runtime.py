"""执行器：编译、运行、流式。"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from agent_platform.engine.builder import build_graph
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


async def stream_graph(
    graph_def: GraphDef,
    inputs: dict[str, Any],
    ctx: EngineContext,
    checkpointer: Any = None,
    thread_id: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """产出 token 增量与最终态。

    事件：{"type": "token", "content": str} ... 最后 {"type": "final", "answer": str}
    """
    app = build_graph(graph_def, ctx, checkpointer)
    config = _config(checkpointer, thread_id)
    final_state: GraphState = {}
    async for event in app.astream_events({"inputs": inputs}, config=config, version="v2"):
        kind = event.get("event")
        if kind == "on_chat_model_stream":
            chunk = event.get("data", {}).get("chunk")
            text = getattr(chunk, "content", "") if chunk is not None else ""
            if text:
                yield {"type": "token", "content": text}
        elif kind == "on_chain_end" and event.get("name") == "LangGraph":
            output = event.get("data", {}).get("output")
            if isinstance(output, dict):
                final_state = output
    yield {"type": "final", "answer": final_state.get("answer", ""), "state": final_state}
