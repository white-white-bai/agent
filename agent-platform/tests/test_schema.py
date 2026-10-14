import pytest
from pydantic import ValidationError

from agent_platform.graph.schema import GraphDef, NodeType


def test_graph_def_validates_node_config():
    graph = GraphDef.model_validate(
        {
            "nodes": [
                {"id": "start", "type": "start"},
                {"id": "llm", "type": "llm", "config": {"model": "qwen", "user_prompt": "{{ query }}"}},
            ]
        }
    )
    assert graph.start_node().id == "start"
    assert graph.node("llm").typed_config().model == "qwen"


def test_graph_def_rejects_duplicate_node_ids():
    with pytest.raises(ValidationError):
        GraphDef.model_validate(
            {
                "nodes": [
                    {"id": "a", "type": "start"},
                    {"id": "a", "type": "answer"},
                ]
            }
        )


def test_unknown_node_type_rejected():
    with pytest.raises(ValidationError):
        GraphDef.model_validate({"nodes": [{"id": "x", "type": "not-a-node"}]})


def test_start_then_end_roundtrip_json():
    graph = GraphDef.model_validate(
        {"nodes": [{"id": "s", "type": "start"}, {"id": "e", "type": "end"}]}
    )
    dumped = graph.model_dump(mode="json")
    assert GraphDef.model_validate(dumped) == graph
    assert NodeType.START.value == "start"
