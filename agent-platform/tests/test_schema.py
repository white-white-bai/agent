import pytest
from pydantic import ValidationError

from agent_platform.graph.schema import GraphDef, NodeType


def test_graph_def_validates_node_config():
    graph = GraphDef.model_validate(
        {
            "nodes": [
                {"id": "start", "type": "start"},
                {"id": "llm", "type": "llm", "config": {"provider": "qwen", "user_prompt": "{{ query }}"}},
            ]
        }
    )
    assert graph.start_node().id == "start"
    assert graph.node("llm").typed_config().provider == "qwen"


def test_graph_def_validates_new_node_configs():
    graph = GraphDef.model_validate(
        {
            "nodes": [
                {"id": "start", "type": "start"},
                {"id": "http", "type": "http-request", "config": {"method": "post", "url": "https://x", "body_type": "json"}},
                {"id": "cls", "type": "question-classifier", "config": {"classes": [{"id": "a", "name": "甲"}]}},
                {"id": "assign", "type": "variable-assigner", "config": {"items": [{"name": "n", "expression": "1"}]}},
                {"id": "lop", "type": "list-operator", "config": {"operation": "sort", "desc": True}},
            ]
        }
    )
    assert graph.node("http").typed_config().method == "POST"
    assert graph.node("cls").typed_config().classes[0].id == "a"
    assert graph.node("assign").typed_config().items[0].name == "n"
    assert graph.node("lop").typed_config().desc is True


def test_llm_config_accepts_context_and_rejects_bad_types():
    from agent_platform.graph.schema import LLMConfig

    assert LLMConfig.model_validate({"context": "chunks"}).context == "chunks"
    assert LLMConfig.model_validate({}).context == ""
    with pytest.raises(ValidationError):
        LLMConfig.model_validate({"temperature": "hot"})


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


def test_parameter_extractor_and_template_transform_configs():
    graph = GraphDef.model_validate(
        {
            "nodes": [
                {
                    "id": "extract",
                    "type": "parameter-extractor",
                    "config": {
                        "parameters": [
                            {"name": "region", "type": "string", "required": "true"},
                            {"name": "tags", "type": "array[string]", "required": "false"},
                        ]
                    },
                },
                {
                    "id": "tpl",
                    "type": "template-transform",
                    "config": {"variables": [{"name": "city", "expression": "query"}], "template": "{{ city }}"},
                },
            ]
        }
    )
    extractor = graph.node("extract").typed_config()
    assert extractor.parameters[0].required is True
    # 前端表单传字符串，bool("false") is True 的坑由 field_validator 挡掉
    assert extractor.parameters[1].required is False
    template = graph.node("tpl").typed_config()
    assert template.variables[0].name == "city"
    assert template.output_var == "output"


def test_agent_config_accepts_autonomous_mode_and_discover_flag():
    from agent_platform.graph.schema import AGENT_MODES, ToolRef

    assert "autonomous" in AGENT_MODES
    graph = GraphDef.model_validate(
        {
            "nodes": [
                {
                    "id": "agent",
                    "type": "agent",
                    "config": {
                        "agent": "local.auto",
                        "mode": "autonomous",
                        "tools": [{"name": "weather", "server": "demo", "discover": "true"}],
                    },
                }
            ]
        }
    )
    config = graph.node("agent").typed_config()
    assert config.mode == "autonomous"
    assert config.tools[0].discover is True
    assert ToolRef.model_validate({"name": "t", "discover": ""}).discover is False
