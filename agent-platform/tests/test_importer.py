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
    assert llm.provider == ""
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


def test_convert_parameter_extractor_node():
    dsl = _dsl(
        nodes=[
            _node("start", "start", {"variables": []}),
            _node(
                "pe",
                "parameter-extractor",
                {
                    "model": {"provider": "openai", "name": "gpt-4o", "completion_params": {"temperature": 0.1}},
                    "query": ["sys", "query"],
                    "instruction": "从 {{#start.topic#}} 提取",
                    "parameters": [
                        {"name": "region", "type": "string", "required": True, "description": "区域"},
                        {"name": "intention", "type": "select", "options": ["购票", "置换"]},
                    ],
                    "reasoning_mode": "function_call",
                },
            ),
            _node("answer_1", "answer", {"answer": "{{#pe.region#}}"}),
        ],
        edges=[_edge("start", "pe"), _edge("pe", "answer_1")],
    )
    result = convert(dsl)
    graph = GraphDef.model_validate(result.definition)
    assert graph.node("extract2") is not None
    extractor = graph.node("extract2").typed_config()
    assert extractor.provider == ""
    assert extractor.query == "{{ query }}"
    assert [item.name for item in extractor.parameters] == ["region", "intention"]
    assert extractor.parameters[0].required is True
    assert extractor.parameters[1].options == ["购票", "置换"]
    assert extractor.output_var == "extract2"
    # 下游引用按参数名平铺到 extract2.<name>
    assert graph.node("answer3").typed_config().template == "{{ extract2.region }}"
    assert not any("旁路" in item for item in result.warnings)
    assert any("function_call" in item for item in result.warnings)


def test_convert_template_transform_node_binds_local_variables():
    dsl = _dsl(
        nodes=[
            _node("start", "start", {"variables": []}),
            _node("llm_1", "llm", {"model": {"name": "m"}, "prompt_template": []}),
            _node(
                "tpl",
                "template-transform",
                {
                    "variables": [{"variable": "text", "value_selector": ["llm_1", "text"]}],
                    "template": "结论：{{ text }}",
                },
            ),
            _node("answer_1", "answer", {"answer": "{{#tpl.output#}}"}),
        ],
        edges=[_edge("start", "llm_1"), _edge("llm_1", "tpl"), _edge("tpl", "answer_1")],
    )
    result = convert(dsl)
    graph = GraphDef.model_validate(result.definition)
    assert graph.node("tpl3") is not None
    template = graph.node("tpl3").typed_config()
    assert [item.model_dump() for item in template.variables] == [{"name": "text", "expression": "llm2"}]
    assert template.template == "结论：{{ text }}"
    assert template.output_var == "tpl3"
    assert graph.node("answer4").typed_config().template == "{{ tpl3 }}"
    assert not any("旁路" in item for item in result.warnings)


def test_convert_degraded_node_rewires_edges():
    dsl = _dsl(
        nodes=[
            _node("start", "start", {"variables": []}),
            _node("de", "document-extractor", {}),
            _node("answer_1", "answer", {"answer": "完"}),
        ],
        edges=[_edge("start", "de"), _edge("de", "answer_1")],
    )
    result = convert(dsl)
    graph = GraphDef.model_validate(result.definition)
    assert [node.id for node in graph.nodes] == ["start1", "answer3"]
    assert [(edge.source, edge.target) for edge in graph.edges] == [("start1", "answer3")]
    assert result.stats["degraded"] == 1
    assert any("document-extractor" in item for item in result.warnings)


def test_convert_degraded_chain_rewires_transitively():
    dsl = _dsl(
        nodes=[
            _node("start", "start", {"variables": []}),
            _node("it", "iteration", {}),
            _node("de", "document-extractor", {}),
            _node("answer_1", "answer", {"answer": "完"}),
        ],
        edges=[_edge("start", "it"), _edge("it", "de"), _edge("de", "answer_1")],
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
    # llm_provider 现在是 AP_LLM_MODELS 的任意条目 key，不再做枚举校验；retriever 仍校验
    assert convert(BASIC, llm_provider="deepseek").definition
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


# --------------------------------------------------------------------------- http / classifier / assigner / list


def test_convert_http_request_node():
    dsl = _dsl(
        nodes=[
            _node("start", "start", {"variables": [{"variable": "query", "type": "text-input"}]}),
            _node(
                "http_1",
                "http-request",
                {
                    "method": "post",
                    "url": "https://api.test/{{#start.query#}}",
                    "headers": "Content-Type:application/json\nX-Token: abc",
                    "params": "page:1",
                    "authorization": {"type": "bearer", "config": {"api_key": "{{#start.query#}}"}},
                    "body": {"type": "json", "data": [{"key": "q", "value": "{{#start.query#}}"}]},
                    "timeout": 15,
                },
            ),
            _node("answer_1", "answer", {"answer": "{{#http_1.body#}}"}),
        ],
        edges=[_edge("start", "http_1"), _edge("http_1", "answer_1")],
    )
    result = convert(dsl)
    graph = GraphDef.model_validate(result.definition)
    http = graph.node("http2").typed_config()
    assert http.method == "POST"
    assert http.url == "https://api.test/{{ query }}"
    assert http.headers == {"Content-Type": "application/json", "X-Token": "abc", "Authorization": "Bearer {{ query }}"}
    assert http.params == {"page": "1"}
    assert http.body_type == "json"
    assert json.loads(http.body) == {"q": "{{ query }}"}
    assert http.timeout == 15
    # http 是多字段输出：{{#http_1.body#}} 应改写成 http2.body
    assert graph.node("answer3").typed_config().template == "{{ http2.body }}"
    assert not any("不支持，已旁路" in item for item in result.warnings)


def test_convert_http_request_rejects_unsupported_method():
    dsl = _dsl(nodes=[_node("http_1", "http-request", {"method": "trace", "url": "https://x"})], edges=[])
    result = convert(dsl)
    assert GraphDef.model_validate(result.definition).node("http1").typed_config().method == "GET"
    assert any("HTTP 方法 TRACE 不支持" in item for item in result.warnings)


def test_convert_question_classifier_node():
    dsl = _dsl(
        nodes=[
            _node("start", "start", {"variables": []}),
            _node(
                "cls",
                "question-classifier",
                {
                    "query_variable_selector": ["start", "query"],
                    "classes": [{"id": "billing", "name": "计费"}, {"id": "refund", "name": "退费"}],
                    "instruction": "按意图分类",
                    "model": {"provider": "openai", "completion_params": {"temperature": 0.1}},
                },
            ),
            _node("a1", "answer", {"answer": "计费"}),
            _node("a2", "answer", {"answer": "退费"}),
        ],
        edges=[_edge("start", "cls"), _edge("cls", "a1", handle="billing"), _edge("cls", "a2", handle="refund")],
    )
    result = convert(dsl)
    graph = GraphDef.model_validate(result.definition)
    cls = graph.node("classifier2").typed_config()
    assert [(item.id, item.name) for item in cls.classes] == [("billing", "计费"), ("refund", "退费")]
    assert cls.query == "{{ query }}"
    assert cls.instruction == "按意图分类"
    assert cls.temperature == 0.1
    assert [e.source_handle for e in graph.edges if e.source == "classifier2"] == ["billing", "refund"]
    assert not any("不支持，已旁路" in item for item in result.warnings)


def test_convert_normalizes_dify_default_handles():
    dsl = _dsl(
        nodes=[
            _node("start", "start", {"variables": []}),
            _node("k1", "knowledge-retrieval", {"dataset_ids": []}),
            _node("llm_1", "llm", {"prompt_template": []}),
        ],
        edges=[
            {"id": "e1", "source": "start", "target": "k1", "sourceHandle": "source", "targetHandle": "target"},
            {"id": "e2", "source": "k1", "target": "llm_1", "sourceHandle": "source", "targetHandle": "target"},
        ],
    )
    graph = GraphDef.model_validate(convert(dsl).definition)
    assert [edge.source_handle for edge in graph.edges] == ["", ""]


def test_convert_variable_assigner_node():
    dsl = _dsl(
        nodes=[
            _node("start", "start", {"variables": []}),
            _node(
                "set",
                "variable-assigner",
                {
                    "items": [
                        {"variable_selector": ["conversation", "total"], "value_selector": ["start", "query"]},
                        {"variable_selector": ["conversation", "flag"], "value": "yes"},
                    ]
                },
            ),
        ],
        edges=[_edge("start", "set")],
    )
    result = convert(dsl)
    graph = GraphDef.model_validate(result.definition)
    assigner = graph.node("assigner2").typed_config()
    assert [(item.name, item.expression) for item in assigner.items] == [("total", "query"), ("flag", '"yes"')]
    assert not any("不支持，已旁路" in item for item in result.warnings)


def test_convert_variable_assigner_warns_on_unsupported_operation():
    dsl = _dsl(
        nodes=[
            _node("start", "start", {"variables": []}),
            _node(
                "set",
                "variable-assigner",
                {"items": [{"variable_selector": ["conversation", "n"], "value_selector": ["start", "query"], "operation": "+="}]},
            ),
        ],
        edges=[_edge("start", "set")],
    )
    result = convert(dsl)
    assert any("变量赋值操作 += 不支持" in item for item in result.warnings)


def test_convert_list_operator_node():
    dsl = _dsl(
        nodes=[
            _node("start", "start", {"variables": []}),
            _node("k1", "knowledge-retrieval", {"dataset_ids": [], "query_variable_selector": ["start", "query"]}),
            _node("lop", "list-operator", {"variable": ["k1", "result"], "operation": "limit", "limit": 2}),
        ],
        edges=[_edge("start", "k1"), _edge("k1", "lop")],
    )
    result = convert(dsl)
    graph = GraphDef.model_validate(result.definition)
    config = graph.node("listop3").typed_config()
    assert config.variable == "knowledge2"
    assert config.operation == "limit"
    assert config.count == 2
    assert not any("不支持，已旁路" in item for item in result.warnings)


def test_convert_list_operator_unknown_operation_degrades():
    dsl = _dsl(nodes=[_node("lop", "list-operator", {"operation": "slice", "variable": ["a", "b"]})], edges=[])
    result = convert(dsl)
    assert GraphDef.model_validate(result.definition).node("listop1").typed_config().operation == "first"
    assert any("数组操作 slice 不支持" in item for item in result.warnings)


def test_convert_llm_context_expands_in_place():
    dsl = _dsl(
        nodes=[
            _node("start", "start", {"variables": []}),
            _node("k1", "knowledge-retrieval", {"dataset_ids": [], "query_variable_selector": ["start", "query"]}),
            _node(
                "llm_1",
                "llm",
                {
                    "context": {"enabled": True, "variable_selector": ["k1", "result"]},
                    "prompt_template": [{"role": "user", "text": "{{#context#}}"}],
                },
            ),
        ],
        edges=[_edge("start", "k1"), _edge("k1", "llm_1")],
    )
    result = convert(dsl)
    graph = GraphDef.model_validate(result.definition)
    llm = graph.node("llm3").typed_config()
    assert llm.user_prompt == "{{ knowledge2 }}"
    assert llm.context == ""


def test_convert_llm_context_uses_field_when_prompt_has_no_context_var():
    dsl = _dsl(
        nodes=[
            _node("start", "start", {"variables": []}),
            _node("k1", "knowledge-retrieval", {"dataset_ids": [], "query_variable_selector": ["start", "query"]}),
            _node(
                "llm_1",
                "llm",
                {
                    "context": {"enabled": True, "variable_selector": ["k1", "result"]},
                    "prompt_template": [{"role": "user", "text": "请回答 {{#sys.query#}}"}],
                },
            ),
        ],
        edges=[_edge("start", "k1"), _edge("k1", "llm_1")],
    )
    result = convert(dsl)
    graph = GraphDef.model_validate(result.definition)
    assert graph.node("llm3").typed_config().context == "knowledge2"


def test_convert_adds_placeholders_for_runtime_variables():
    dsl = _dsl(
        nodes=[
            _node("start", "start", {"variables": [{"variable": "query", "type": "text-input"}]}),
            _node("llm_1", "llm", {"prompt_template": [{"role": "user", "text": "{{#sys.user_id#}} 问 {{#sys.query#}}"}]}),
        ],
        edges=[_edge("start", "llm_1")],
    )
    result = convert(dsl)
    graph = GraphDef.model_validate(result.definition)
    names = [item.name for item in graph.inputs]
    assert names == ["query", "user_id"]
    assert graph.node("llm2").typed_config().user_prompt == "{{ user_id }} 问 {{ query }}"
