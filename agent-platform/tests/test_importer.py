import json

import pytest

from agent_platform.engine.expr import evaluate, render
from agent_platform.graph.schema import GraphDef, NodeType
from agent_platform.importer import DifyImportError, convert, load_dsl, parse_dsl


def _dsl(nodes, edges, variables=None):
    return {
        "app": {"id": "app-1", "name": "客服助手"},
        "workflow": {
            "graph": {
                "nodes": nodes,
                "edges": edges,
            }
        },
        "kind": "app",
        "version": "0.1.5",
        "start_variables": variables,
    }


def _node(node_id, node_type, data=None, x=0, y=0):
    payload = {"type": node_type, "title": node_id}
    payload.update(data or {})
    return {"id": node_id, "type": "custom", "position": {"x": x, "y": y}, "data": payload}


def _edge(source, target, handle=None):
    edge = {"id": f"{source}-{target}", "source": source, "target": target}
    if handle is not None:
        edge["sourceHandle"] = handle
    return edge


BASIC = _dsl(
    nodes=[
        _node(
            "start",
            "start",
            {"variables": [{"variable": "query", "type": "text-input", "required": True, "label": "提问"}]},
        ),
        _node("llm_1", "llm", {"model": {"name": "gpt-4o", "provider": "openai"}, "prompt_template": []}),
        _node("answer_1", "answer", {"answer": "您好：{{#llm_1.text#}}"}),
        _node("end", "end", {"outputs": [{"variable": "result", "value_selector": ["llm_1", "text"]}]}),
    ],
    edges=[_edge("start", "llm_1"), _edge("llm_1", "answer_1"), _edge("answer_1", "end")],
)


def test_convert_registers_inputs_and_edges():
    result = convert(BASIC, app_id="app-1", name="客服助手")
    graph = GraphDef.model_validate(result.definition)
    assert result.stats == {"total": 4, "converted": 4, "degraded": 0}
    assert graph.app_id == "app-1"
    assert graph.name == "客服助手"
    assert [item.name for item in graph.inputs] == ["query"]
    assert graph.inputs[0].required is True
    assert graph.inputs[0].type.value == "string"
    assert [node.type for node in graph.nodes] == [
        NodeType.START,
        NodeType.LLM,
        NodeType.ANSWER,
        NodeType.END,
    ]
    assert graph.node("start1").type is NodeType.START


def test_convert_rewrites_references_into_templates():
    result = convert(BASIC)
    graph = GraphDef.model_validate(result.definition)
    answer = graph.node("answer3").typed_config()
    assert answer.template == "您好：{{ llm2 }}"
    assert render(answer.template, {"llm2": "在的"}) == "您好：在的"


def test_convert_rewrites_end_outputs_into_bare_expressions():
    result = convert(BASIC)
    graph = GraphDef.model_validate(result.definition)
    end = graph.node("end4").typed_config()
    assert end.outputs == {"result": "llm2"}
    assert evaluate(end.outputs["result"], {"llm2": "回答"}) == "回答"


def test_convert_llm_config_defaults():
    result = convert(BASIC)
    graph = GraphDef.model_validate(result.definition)
    llm = graph.node("llm2").typed_config()
    assert llm.provider == "cloud_gateway"
    assert llm.model == "gpt-4o"
    assert llm.output_var == "llm2"
    assert llm.user_prompt == "{{ query }}"
    assert llm.temperature == 0.7
    assert llm.max_tokens is None


def test_convert_llm_prompt_roles_and_completion_params():
    dsl = _dsl(
        nodes=[
            _node("start", "start", {"variables": []}),
            _node(
                "llm_1",
                "llm",
                {
                    "model": {
                        "name": "deepseek-chat",
                        "provider": "langgenius/deepseek",
                        "completion_params": {"temperature": 0.2, "max_tokens": 512},
                    },
                    "prompt_template": [
                        {"role": "system", "text": "你是{{#start.role#}}助手"},
                        {"role": "user", "text": "{{#sys.query#}}"},
                    ],
                },
            ),
        ],
        edges=[_edge("start", "llm_1")],
    )
    result = convert(dsl, llm_provider="openai")
    graph = GraphDef.model_validate(result.definition)
    llm = graph.node("llm2").typed_config()
    assert llm.provider == "openai"
    assert llm.system_prompt == "你是{{ role }}助手"
    assert llm.user_prompt == "{{ query }}"
    assert llm.temperature == 0.2
    assert llm.max_tokens == 512
    assert any("provider" in item for item in result.warnings)


def test_convert_llm_context_variable_selector():
    dsl = _dsl(
        nodes=[
            _node("start", "start", {"variables": []}),
            _node("kr", "knowledge-retrieval", {"query_variable_selector": ["sys", "query"]}),
            _node(
                "llm_1",
                "llm",
                {
                    "model": {"name": "m"},
                    "context": {"enabled": True, "variable_selector": ["kr", "result"]},
                    "prompt_template": [{"role": "user", "text": "资料：{{#context#}}\n问：{{#sys.query#}}"}],
                },
            ),
        ],
        edges=[_edge("start", "kr"), _edge("kr", "llm_1")],
    )
    graph = GraphDef.model_validate(convert(dsl).definition)
    assert graph.node("llm3").typed_config().user_prompt == "资料：{{ knowledge2 }}\n问：{{ query }}"


def test_convert_knowledge_node():
    dsl = _dsl(
        nodes=[
            _node("start", "start", {"variables": []}),
            _node(
                "kr",
                "knowledge-retrieval",
                {
                    "dataset_ids": ["ds-1", "ds-2"],
                    "query_variable_selector": ["start", "question"],
                    "multiple_retrieval_config": {"top_k": 3, "score_threshold": 0.4},
                },
            ),
        ],
        edges=[_edge("start", "kr")],
    )
    result = convert(dsl, retriever="light_rag")
    graph = GraphDef.model_validate(result.definition)
    knowledge = graph.node("knowledge2").typed_config()
    assert knowledge.retriever == "light_rag"
    assert knowledge.dataset_ids == ["ds-1", "ds-2"]
    assert knowledge.query == "{{ question }}"
    assert knowledge.top_k == 3
    assert knowledge.score_threshold == 0.4
    assert any("重新入库" in item for item in result.warnings)


def test_convert_condition_branches_and_handles():
    dsl = _dsl(
        nodes=[
            _node("start", "start", {"variables": []}),
            _node(
                "if_1",
                "if-else",
                {
                    "cases": [
                        {
                            "case_id": "true",
                            "logical_operator": "and",
                            "conditions": [
                                {
                                    "variable_selector": ["code_1", "score"],
                                    "comparison_operator": ">",
                                    "value": "0.5",
                                },
                                {
                                    "variable_selector": ["start", "name"],
                                    "comparison_operator": "contains",
                                    "value": "张",
                                },
                            ],
                        }
                    ]
                },
            ),
            _node("code_1", "code", {"code": "def main():\n    return {'score': 1}", "outputs": {"score": {}}}),
            _node("answer_1", "answer", {"answer": "命中"}),
            _node("answer_2", "answer", {"answer": "未命中"}),
        ],
        edges=[
            _edge("start", "code_1"),
            _edge("code_1", "if_1"),
            _edge("if_1", "answer_1", "true"),
            _edge("if_1", "answer_2", "false"),
        ],
    )
    graph = GraphDef.model_validate(convert(dsl).definition)
    condition = graph.node("ifelse2").typed_config()
    assert condition.fallback_id == "false"
    assert [branch.id for branch in condition.branches] == ["true"]
    expression = condition.branches[0].expression
    assert evaluate(expression, {"code3": {"score": 0.8}, "name": "张三"}) is True
    assert evaluate(expression, {"code3": {"score": 0.8}, "name": "李四"}) is False
    assert evaluate(expression, {"code3": {"score": 0.1}, "name": "张三"}) is False


def test_convert_condition_logical_or_and_unsupported_operator():
    dsl = _dsl(
        nodes=[
            _node("start", "start", {"variables": []}),
            _node(
                "if_1",
                "if-else",
                {
                    "cases": [
                        {
                            "case_id": "case_a",
                            "logical_operator": "or",
                            "conditions": [
                                {"variable_selector": ["start", "a"], "comparison_operator": "empty", "value": ""},
                                {
                                    "variable_selector": ["start", "a"],
                                    "comparison_operator": "all of",
                                    "value": ["x", "y"],
                                },
                            ],
                        }
                    ]
                },
            ),
            _node("end", "end", {"outputs": []}),
        ],
        edges=[_edge("start", "if_1"), _edge("if_1", "end", "case_a"), _edge("if_1", "end", "false")],
    )
    result = convert(dsl)
    graph = GraphDef.model_validate(result.definition)
    expression = graph.node("ifelse2").typed_config().branches[0].expression
    assert evaluate(expression, {"a": ""}) is True
    assert evaluate(expression, {"a": "有值"}) is False
    assert any("all of" in item for item in result.warnings)


def test_convert_condition_without_handle_falls_back_to_last():
    dsl = _dsl(
        nodes=[
            _node("start", "start", {"variables": []}),
            _node("if_1", "if-else", {"cases": [{"case_id": "c1", "conditions": []}]}),
            _node("end", "end", {"outputs": []}),
        ],
        edges=[_edge("start", "if_1"), _edge("if_1", "end", "c1")],
    )
    graph = GraphDef.model_validate(convert(dsl).definition)
    assert graph.node("ifelse2").typed_config().fallback_id == "c1"


def test_convert_code_node():
    dsl = _dsl(
        nodes=[
            _node("start", "start", {"variables": []}),
            _node(
                "code_1",
                "code",
                {
                    "code_language": "python3",
                    "code": "def main(n):\n    return {'double': n * 2}",
                    "variables": [{"variable": "n", "value_selector": ["start", "count"]}],
                    "outputs": {"double": {"type": "number"}},
                    "timeout": 5000,
                },
            ),
        ],
        edges=[_edge("start", "code_1")],
    )
    graph = GraphDef.model_validate(convert(dsl).definition)
    code = graph.node("code2").typed_config()
    assert code.code.startswith("def main")
    assert code.timeout_ms == 5000
    assert code.outputs == ["double"]
    assert [(item.name, item.expression) for item in code.inputs] == [("n", "count")]


def test_convert_code_node_rejects_other_language():
    dsl = _dsl(
        nodes=[
            _node("start", "start", {"variables": []}),
            _node("code_1", "code", {"code_language": "javascript", "code": "function main(){}"}),
        ],
        edges=[_edge("start", "code_1")],
    )
    result = convert(dsl)
    graph = GraphDef.model_validate(result.definition)
    assert [node.type for node in graph.nodes] == [NodeType.START]
    assert result.stats["degraded"] == 1
    assert any("javascript" in item for item in result.warnings)


def test_convert_tool_node_arguments():
    dsl = _dsl(
        nodes=[
            _node("start", "start", {"variables": []}),
            _node(
                "tool_1",
                "tool",
                {
                    "provider_name": "政务查询",
                    "tool_name": "query_person",
                    "tool_parameters": {
                        "id_card": {"type": "variable", "value": ["start", "id"]},
                        "fixed": {"type": "constant", "value": "abc"},
                        "count": 3,
                    },
                },
            ),
        ],
        edges=[_edge("start", "tool_1")],
    )
    result = convert(dsl)
    graph = GraphDef.model_validate(result.definition)
    tool = graph.node("tool2").typed_config()
    assert tool.output_var == "tool2"
    assert len(tool.tools) == 1
    ref = tool.tools[0]
    assert ref.name == "query_person"
    assert ref.server == "政务查询"
    assert ref.args == {"id_card": "id", "fixed": '"abc"', "count": 3}
    assert evaluate(ref.args["fixed"], {}) == "abc"
    assert any("MCP" in item for item in result.warnings)


def test_convert_aggregate_node():
    dsl = _dsl(
        nodes=[
            _node("start", "start", {"variables": []}),
            _node("agg", "variable-aggregator", {"variables": [["start", "a"], ["start", "b"]]}),
        ],
        edges=[_edge("start", "agg")],
    )
    graph = GraphDef.model_validate(convert(dsl).definition)
    aggregate = graph.node("aggregate2").typed_config()
    assert aggregate.variables == ["a", "b"]
    assert aggregate.output_var == "aggregate2"


def test_convert_degraded_node_rewires_edges():
    dsl = _dsl(
        nodes=[
            _node("start", "start", {"variables": []}),
            _node("http_1", "http-request", {"url": "https://example.com"}),
            _node("answer_1", "answer", {"answer": "完"}),
        ],
        edges=[_edge("start", "http_1"), _edge("http_1", "answer_1")],
    )
    result = convert(dsl)
    graph = GraphDef.model_validate(result.definition)
    assert [node.id for node in graph.nodes] == ["start1", "answer3"]
    assert [(edge.source, edge.target) for edge in graph.edges] == [("start1", "answer3")]
    assert result.stats["degraded"] == 1
    assert any("http-request" in item for item in result.warnings)


def test_convert_degraded_chain_rewires_transitively():
    dsl = _dsl(
        nodes=[
            _node("start", "start", {"variables": []}),
            _node("tpl", "template-transform", {}),
            _node("http_1", "http-request", {}),
            _node("answer_1", "answer", {"answer": "完"}),
        ],
        edges=[_edge("start", "tpl"), _edge("tpl", "http_1"), _edge("http_1", "answer_1")],
    )
    graph = GraphDef.model_validate(convert(dsl).definition)
    assert [(edge.source, edge.target) for edge in graph.edges] == [("start1", "answer4")]


def test_convert_duplicate_ids_are_bypassed():
    dsl = _dsl(
        nodes=[
            _node("start", "start", {"variables": []}),
            _node("start", "llm", {"model": {"name": "m"}}),
        ],
        edges=[],
    )
    result = convert(dsl)
    assert [node["type"] for node in result.definition["nodes"]] == ["start"]
    assert any("重复" in item for item in result.warnings)


def test_convert_unknown_reference_is_kept_with_warning():
    dsl = _dsl(
        nodes=[
            _node("start", "start", {"variables": []}),
            _node("answer_1", "answer", {"answer": "{{#missing.var#}}"}),
        ],
        edges=[_edge("start", "answer_1")],
    )
    result = convert(dsl)
    graph = GraphDef.model_validate(result.definition)
    assert graph.node("answer2").typed_config().template == "{{ var }}"
    assert any("missing" in item for item in result.warnings)


def test_convert_warns_when_start_node_missing():
    dsl = _dsl(nodes=[_node("answer_1", "answer", {"answer": "独"})], edges=[])
    result = convert(dsl)
    assert any("start" in item for item in result.warnings)


def test_convert_rejects_unknown_adapters():
    with pytest.raises(DifyImportError):
        convert(BASIC, llm_provider="anthropic")
    with pytest.raises(DifyImportError):
        convert(BASIC, retriever="milvus")


def test_convert_rejects_malformed_dsl():
    with pytest.raises(DifyImportError):
        convert([1, 2, 3])
    with pytest.raises(DifyImportError):
        convert({"app": {}})
    with pytest.raises(DifyImportError):
        convert({"graph": {"nodes": "nope"}})


def test_convert_falls_back_to_top_level_graph():
    dsl = {"graph": {"nodes": [_node("answer_1", "answer", {"answer": "x"})], "edges": []}}
    result = convert(dsl)
    assert [node["type"] for node in result.definition["nodes"]] == ["answer"]


def test_convert_app_metadata_defaults():
    dsl = _dsl(nodes=[_node("answer_1", "answer", {"answer": "x"})], edges=[])
    assert convert(dsl).definition["app_id"] == "app-1"
    assert convert(dsl).definition["name"] == "客服助手"
    assert convert(dsl, app_id="override", name="改名").definition["app_id"] == "override"
    assert convert(dsl, app_id="override", name="改名").definition["name"] == "改名"


def test_convert_warns_on_mixed_template_expression():
    dsl = _dsl(
        nodes=[
            _node("start", "start", {"variables": []}),
            _node(
                "tool_1",
                "tool",
                {
                    "tool_name": "t",
                    "tool_parameters": {"q": {"type": "variable", "value": "前缀-{{#start.a#}}"}},
                },
            ),
        ],
        edges=[_edge("start", "tool_1")],
    )
    graph = GraphDef.model_validate(convert(dsl).definition)
    args = graph.node("tool2").typed_config().tools[0].args
    assert args["q"] == '"前缀-" ~ a'
    assert evaluate(args["q"], {"a": "值"}) == "前缀-值"


def test_graph_roundtrips_through_dump():
    result = convert(BASIC)
    GraphDef.model_validate(json.loads(json.dumps(result.definition)))


def test_parse_dsl_accepts_json_and_yaml():
    assert parse_dsl(json.dumps(BASIC))["workflow"]["graph"]["nodes"]
    yaml_text = (
        "app:\n"
        "  id: app-2\n"
        "  name: yaml 应用\n"
        "workflow:\n"
        "  graph:\n"
        "    nodes:\n"
        "      - id: answer_1\n"
        "        data:\n"
        "          type: answer\n"
        "          answer: 你好\n"
        "    edges: []\n"
    )
    parsed = parse_dsl(yaml_text)
    assert parsed["app"]["name"] == "yaml 应用"
    graph = GraphDef.model_validate(convert(parsed).definition)
    assert graph.node("answer1").typed_config().template == "你好"


def test_parse_dsl_rejects_bad_input():
    with pytest.raises(DifyImportError):
        parse_dsl("")
    with pytest.raises(DifyImportError):
        parse_dsl("{{{")
    with pytest.raises(DifyImportError):
        parse_dsl("- 1\n- 2\n")


def test_load_dsl_from_file(tmp_path):
    path = tmp_path / "app.yml"
    path.write_text(json.dumps(BASIC), encoding="utf-8")
    assert convert(load_dsl(path)).stats["converted"] == 4
    with pytest.raises(DifyImportError):
        load_dsl(tmp_path / "missing.yml")
