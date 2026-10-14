import pytest

from agent_platform.engine.runtime import run_graph, stream_graph
from agent_platform.graph.schema import GraphDef

GRAPH = GraphDef.model_validate(
    {
        "nodes": [
            {"id": "start", "type": "start"},
            {"id": "llm", "type": "llm", "config": {"user_prompt": "{{ query }}", "output_var": "text"}},
            {"id": "answer", "type": "answer", "config": {"template": "{{ text }}"}},
            {"id": "end", "type": "end"},
        ],
        "edges": [
            {"source": "start", "target": "llm"},
            {"source": "llm", "target": "answer"},
            {"source": "answer", "target": "end"},
        ],
    }
)


@pytest.mark.asyncio
async def test_run_llm_answer_flow(engine_ctx):
    state = await run_graph(GRAPH, {"query": "hi"}, engine_ctx)
    assert state["answer"] == "echo:hi"


@pytest.mark.asyncio
async def test_stream_reaches_final_answer(engine_ctx):
    final = None
    async for item in stream_graph(GRAPH, {"query": "hi"}, engine_ctx):
        if item["type"] == "final":
            final = item
    assert final is not None
    assert final["answer"] == "echo:hi"


@pytest.mark.asyncio
async def test_run_with_mysql_checkpointer(engine_ctx):
    from agent_platform.checkpoint.mysql import MySQLCheckpointSaver

    saver = MySQLCheckpointSaver()
    state = await run_graph(GRAPH, {"query": "hi"}, engine_ctx, checkpointer=saver, thread_id="t-1")
    assert state["answer"] == "echo:hi"
    saved = saver.get_tuple({"configurable": {"thread_id": "t-1"}})
    assert saved is not None
