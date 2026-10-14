import pytest

from agent_platform.engine.runtime import run_graph
from agent_platform.graph.schema import GraphDef

CONDITION_GRAPH = GraphDef.model_validate(
    {
        "inputs": [{"name": "score", "type": "number", "required": True}],
        "nodes": [
            {"id": "start", "type": "start"},
            {
                "id": "cond",
                "type": "condition",
                "config": {"branches": [{"id": "big", "expression": "score > 5"}], "fallback_id": "small"},
            },
            {"id": "answer_big", "type": "answer", "config": {"template": "big"}},
            {"id": "answer_small", "type": "answer", "config": {"template": "small"}},
            {"id": "end", "type": "end"},
        ],
        "edges": [
            {"source": "start", "target": "cond"},
            {"source": "cond", "target": "answer_big", "source_handle": "big"},
            {"source": "cond", "target": "answer_small", "source_handle": "small"},
            {"source": "answer_big", "target": "end"},
            {"source": "answer_small", "target": "end"},
        ],
    }
)


@pytest.mark.asyncio
async def test_condition_takes_true_branch(engine_ctx):
    state = await run_graph(CONDITION_GRAPH, {"score": 10}, engine_ctx)
    assert state["answer"] == "big"


@pytest.mark.asyncio
async def test_condition_falls_back(engine_ctx):
    state = await run_graph(CONDITION_GRAPH, {"score": 1}, engine_ctx)
    assert state["answer"] == "small"
