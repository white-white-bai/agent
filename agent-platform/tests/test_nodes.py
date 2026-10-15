"""节点执行：知识 / 工具 / 代码 / 聚合 / 条件 / 结束 与受限代码沙箱。"""
from __future__ import annotations

import json

import pytest

from agent_platform.engine import nodes
from agent_platform.engine.code_sandbox import CodeExecutionError, run_code
from agent_platform.engine.context import EngineContext
from agent_platform.graph.schema import CodeConfig, NodeDef, NodeType


def _node(node_id: str, node_type: NodeType, **config) -> NodeDef:
    return NodeDef(id=node_id, type=node_type, config=config)


class RecordingLLM:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return "模型回答"


def _retriever(chunks: list[dict], calls: list[tuple]):
    async def retrieve(config, query, tenant_code):
        calls.append((config, query, tenant_code))
        return chunks

    return retrieve


def _invoker(results: list, calls: list[tuple]):
    async def invoke(config, variables, tenant_code=""):
        calls.append((config, dict(variables), tenant_code))
        return results

    return invoke


# --------------------------------------------------------------------------- start / llm


def test_run_start_merges_inputs_and_sets_query():
    state = nodes.run_start(_node("start", NodeType.START), {"inputs": {"query": "常州", "n": 3}}, EngineContext(llm=RecordingLLM()))
    assert state["variables"] == {"query": "常州", "n": 3}
    assert state["query"] == "常州"


def test_run_start_coerces_non_string_query():
    state = nodes.run_start(_node("start", NodeType.START), {"inputs": {"query": 42}}, EngineContext(llm=RecordingLLM()))
    assert state["query"] == "42"
    assert nodes.run_start(_node("start", NodeType.START), {}, EngineContext(llm=RecordingLLM()))["query"] == ""


@pytest.mark.asyncio
async def test_run_llm_renders_prompts_and_aliases_output():
    llm = RecordingLLM()
    ctx = EngineContext(llm=llm)
    node = _node(
        "llm-1",
        NodeType.LLM,
        system_prompt="你是{{ role }}助手",
        user_prompt="{{ query }}",
        output_var="text",
        temperature=0.2,
        max_tokens=128,
    )
    state = await nodes.run_llm(node, {"variables": {"role": "政务", "query": "常州天气"}}, ctx)

    assert llm.calls[0]["system_prompt"] == "你是政务助手"
    assert llm.calls[0]["user_prompt"] == "常州天气"
    assert llm.calls[0]["temperature"] == 0.2
    assert llm.calls[0]["max_tokens"] == 128
    assert state["variables"]["text"] == "模型回答"
    assert state["variables"]["llm-1"] == "模型回答"


# --------------------------------------------------------------------------- knowledge / tool


@pytest.mark.asyncio
async def test_run_knowledge_uses_tenant_scope_and_stores_chunks():
    calls: list[tuple] = []
    chunks = [{"content": "常州天气", "score": 0.9}]
    ctx = EngineContext(llm=RecordingLLM(), retriever=_retriever(chunks, calls), tenant_code="t")
    node = _node("kb-1", NodeType.KNOWLEDGE, query="查{{ query }}", top_k=3, dataset_ids=["d1"])

    state = await nodes.run_knowledge(node, {"variables": {"query": "天气"}}, ctx)
    config, query, tenant_code = calls[0]
    assert query == "查天气"
    assert tenant_code == "t"
    assert config.top_k == 3 and config.dataset_ids == ["d1"]
    assert state["variables"]["chunks"] == chunks
    assert state["variables"]["kb-1"] == chunks


@pytest.mark.asyncio
async def test_run_tool_passes_rendered_variables():
    calls: list[tuple] = []
    ctx = EngineContext(llm=RecordingLLM(), tools=_invoker([{"ok": True}], calls), tenant_code="t")
    node = _node("tool-1", NodeType.TOOL, tools=[{"name": "weather", "server": "demo"}], output_var="out")

    state = await nodes.run_tool(node, {"variables": {"query": "常州"}}, ctx)
    config, variables, tenant_code = calls[0]
    assert [ref.name for ref in config.tools] == ["weather"]
    assert variables == {"query": "常州"}
    assert tenant_code == "t"
    assert state["variables"]["out"] == [{"ok": True}]
    assert state["variables"]["tool-1"] == [{"ok": True}]


# --------------------------------------------------------------------------- code


def test_run_code_node_prefers_injected_runner():
    seen: list[tuple] = []

    def runner(config, variables):
        seen.append((config, dict(variables)))
        return {"total": 3}

    ctx = EngineContext(llm=RecordingLLM(), code_runner=runner)
    node = _node("code-1", NodeType.CODE, code="")
    state = nodes.run_code_node(node, {"variables": {"n": 1}}, ctx)
    assert seen[0][1] == {"n": 1}
    assert state["variables"] == {"n": 1, "total": 3, "code-1": {"total": 3}}


def test_run_code_node_falls_back_to_sandbox():
    node = _node(
        "code-1",
        NodeType.CODE,
        code="def main(**inputs):\n    return {'doubled': inputs['n'] * 2}\n",
        inputs=[{"name": "n", "expression": "n"}],
    )
    state = nodes.run_code_node(node, {"variables": {"n": 21}}, EngineContext(llm=RecordingLLM()))
    assert state["variables"]["doubled"] == 42
    assert state["variables"]["code-1"] == {"doubled": 42}


# --------------------------------------------------------------------------- aggregate / condition


def test_run_aggregate_evaluates_expressions():
    node = _node("agg-1", NodeType.AGGREGATE, variables=["query", "n * 2"], output_var="aggregated")
    state = nodes.run_aggregate(node, {"variables": {"query": "常州", "n": 4}}, EngineContext(llm=RecordingLLM()))
    assert state["variables"]["aggregated"] == {"query": "常州", "n * 2": 8}
    assert state["variables"]["agg-1"] == {"query": "常州", "n * 2": 8}


def test_run_condition_picks_first_matching_branch():
    node = _node(
        "cond-1",
        NodeType.CONDITION,
        branches=[{"id": "a", "expression": "n > 10"}, {"id": "b", "expression": "n > 1"}],
        fallback_id="fallback",
    )
    assert nodes.run_condition(node, {"variables": {"n": 5}}, EngineContext(llm=RecordingLLM()))["route"] == "b"
    assert nodes.run_condition(node, {"variables": {"n": 50}}, EngineContext(llm=RecordingLLM()))["route"] == "a"


def test_run_condition_uses_fallback_when_nothing_matches():
    node = _node(
        "cond-1",
        NodeType.CONDITION,
        branches=[{"id": "a", "expression": "n > 10"}],
        fallback_id="fallback",
    )
    assert nodes.run_condition(node, {"variables": {"n": 1}}, EngineContext(llm=RecordingLLM()))["route"] == "fallback"
    assert nodes.run_condition(_node("c", NodeType.CONDITION), {}, EngineContext(llm=RecordingLLM()))["route"] == ""


def test_run_condition_propagates_expression_error():
    from agent_platform.engine.expr import ExpressionError

    node = _node("c", NodeType.CONDITION, branches=[{"id": "a", "expression": "missing > 1"}])
    with pytest.raises(ExpressionError, match="表达式求值失败"):
        nodes.run_condition(node, {"variables": {}}, EngineContext(llm=RecordingLLM()))


# --------------------------------------------------------------------------- answer / end


def test_run_answer_renders_template():
    node = _node("answer", NodeType.ANSWER, template="你好 {{ name }}", output_var="reply")
    state = nodes.run_answer(node, {"variables": {"name": "常州"}}, EngineContext(llm=RecordingLLM()))
    assert state["answer"] == "你好 常州"
    assert state["variables"]["reply"] == "你好 常州"


def test_run_answer_propagates_render_error():
    from agent_platform.engine.expr import ExpressionError

    node = _node("answer", NodeType.ANSWER, template="{{ missing }}")
    with pytest.raises(ExpressionError, match="模板渲染失败"):
        nodes.run_answer(node, {"variables": {}}, EngineContext(llm=RecordingLLM()))


def test_run_end_joins_outputs_only_without_answer():
    node = _node("end", NodeType.END, outputs={"a": "query", "b": "n * 2"})
    state = nodes.run_end(node, {"variables": {"query": "常州", "n": 4}}, EngineContext(llm=RecordingLLM()))
    assert state["answer"] == "常州\n8"

    kept = nodes.run_end(node, {"variables": {"query": "常州", "n": 4}, "answer": "已有"}, EngineContext(llm=RecordingLLM()))
    assert kept["answer"] == "已有"

    empty = nodes.run_end(_node("end", NodeType.END), {"variables": {}}, EngineContext(llm=RecordingLLM()))
    assert "answer" not in empty


# --------------------------------------------------------------------------- parameter-extractor / template-transform


class ScriptedLLM:
    """按脚本逐次返回模型回复的 LLM mock。"""

    def __init__(self, replies, error: Exception | None = None) -> None:
        self.replies = list(replies)
        self.error = error
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.replies.pop(0)


@pytest.mark.asyncio
async def test_run_parameter_extractor_parses_json_and_stores_fields():
    llm = ScriptedLLM(['{"region": "常州", "count": "3", "tags": ["a"]}'])
    ctx = EngineContext(llm=llm)
    node = _node(
        "extract-1",
        NodeType.PARAMETER_EXTRACTOR,
        query="{{ query }}",
        instruction="提取区域",
        parameters=[
            {"name": "region", "type": "string", "required": True},
            {"name": "count", "type": "number"},
            {"name": "tags", "type": "array[string]"},
            {"name": "missing", "type": "string"},
        ],
        output_var="extracted",
    )
    state = await nodes.run_parameter_extractor(node, {"variables": {"query": "常州的天气"}}, ctx)

    assert llm.calls[0]["user_prompt"] == "提取区域\n\n常州的天气"
    data = state["variables"]["extracted"]
    assert data == {
        "region": "常州",
        "count": 3.0,
        "tags": ["a"],
        "missing": None,
        "__is_success": 1,
        "__reason": "",
    }
    assert state["variables"]["extract-1"] == data
    # 参数名不平铺进全局变量，避免覆盖同名输入
    assert "region" not in state["variables"]


@pytest.mark.asyncio
async def test_run_parameter_extractor_strips_code_fence():
    llm = ScriptedLLM(['```json\n{"region": "南京"}\n```'])
    ctx = EngineContext(llm=llm)
    node = _node("extract-1", NodeType.PARAMETER_EXTRACTOR, query="{{ query }}", parameters=[{"name": "region"}])
    state = await nodes.run_parameter_extractor(node, {"variables": {"query": "q"}}, ctx)
    assert state["variables"]["extract-1"]["region"] == "南京"
    assert state["variables"]["extract-1"]["__is_success"] == 1


@pytest.mark.asyncio
async def test_run_parameter_extractor_degrades_on_bad_json():
    llm = ScriptedLLM(["完全不是 JSON"])
    ctx = EngineContext(llm=llm)
    node = _node(
        "extract-1",
        NodeType.PARAMETER_EXTRACTOR,
        query="{{ query }}",
        parameters=[{"name": "region", "type": "string"}, {"name": "tags", "type": "array[string]"}],
    )
    state = await nodes.run_parameter_extractor(node, {"variables": {"query": "q"}}, ctx)
    data = state["variables"]["extract-1"]
    assert data["__is_success"] == 0
    assert "JSON 解析失败" in data["__reason"]
    assert data["region"] is None
    assert data["tags"] == []


@pytest.mark.asyncio
async def test_run_parameter_extractor_degrades_on_llm_error():
    llm = ScriptedLLM([], error=RuntimeError("网关超时"))
    ctx = EngineContext(llm=llm)
    node = _node("extract-1", NodeType.PARAMETER_EXTRACTOR, query="{{ query }}", parameters=[{"name": "region"}])
    state = await nodes.run_parameter_extractor(node, {"variables": {"query": "q"}}, ctx)
    data = state["variables"]["extract-1"]
    assert data["__is_success"] == 0
    assert "网关超时" in data["__reason"]


def test_run_template_transform_binds_local_variables():
    node = _node(
        "tpl-1",
        NodeType.TEMPLATE_TRANSFORM,
        variables=[{"name": "city", "expression": "query"}, {"name": "n", "expression": "n * 2"}],
        template="{{ city }} 共 {{ n }} 条",
        output_var="output",
    )
    state = nodes.run_template_transform(node, {"variables": {"query": "常州", "n": 21}}, EngineContext(llm=RecordingLLM()))
    assert state["variables"]["output"] == "常州 共 42 条"
    assert state["variables"]["tpl-1"] == "常州 共 42 条"


def test_run_template_transform_propagates_render_error():
    from agent_platform.engine.expr import ExpressionError

    node = _node("tpl-1", NodeType.TEMPLATE_TRANSFORM, template="{{ missing }}")
    with pytest.raises(ExpressionError, match="模板渲染失败"):
        nodes.run_template_transform(node, {"variables": {}}, EngineContext(llm=RecordingLLM()))


# --------------------------------------------------------------------------- 代码沙箱


def test_run_code_requires_code():
    with pytest.raises(CodeExecutionError, match="代码节点为空"):
        run_code(CodeConfig(code="   "), {})


def test_run_code_requires_main_function():
    with pytest.raises(CodeExecutionError, match="代码节点必须定义 main"):
        run_code(CodeConfig(code="value = 1\n"), {})


def test_run_code_passes_evaluated_inputs():
    config = CodeConfig(
        code="def main(**inputs):\n    return {'sum': inputs['a'] + inputs['b']}\n",
        inputs=[{"name": "a", "expression": "n"}, {"name": "b", "expression": "2"}],
    )
    assert run_code(config, {"n": 1}) == {"sum": 3}


def test_run_code_filters_declared_outputs():
    config = CodeConfig(
        code="def main(**inputs):\n    return {'keep': 1, 'drop': 2}\n", outputs=["keep"]
    )
    assert run_code(config, {}) == {"keep": 1}


def test_run_code_treats_none_result_as_empty_dict():
    assert run_code(CodeConfig(code="def main(**inputs):\n    return None\n"), {}) == {}


def test_run_code_rejects_non_dict_result():
    with pytest.raises(CodeExecutionError, match="代码节点 main 必须返回 dict"):
        run_code(CodeConfig(code="def main(**inputs):\n    return [1, 2]\n"), {})


def test_run_code_wraps_runtime_errors():
    config = CodeConfig(code="def main(**inputs):\n    raise ValueError('坏了')\n")
    with pytest.raises(CodeExecutionError, match="代码节点执行失败: 坏了"):
        run_code(config, {})


def test_run_code_wraps_syntax_errors():
    with pytest.raises(CodeExecutionError, match="代码节点执行失败"):
        run_code(CodeConfig(code="def main(**inputs)\n    return {}\n"), {})


# --------------------------------------------------------------------------- http / classifier / assigner / list


class _FakeResponse:
    def __init__(self, payload, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status
        self.headers = {"X-Test": "1"}
        self.text = payload if isinstance(payload, str) else json.dumps(payload)

    def json(self):
        # 文本响应 json() 会抛 JSONDecodeError（ValueError 子类），与 httpx 行为一致
        return json.loads(self.text)


class _FakeClient:
    def __init__(self, response: _FakeResponse, captured: dict) -> None:
        self._response = response
        self._captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def request(self, method, url, **kwargs):
        self._captured.update({"method": method, "url": url, **kwargs})
        return self._response


async def test_run_llm_appends_knowledge_context():
    llm = RecordingLLM()
    node = _node("llm-1", NodeType.LLM, context="chunks", user_prompt="{{ query }}")
    state = await nodes.run_llm(
        node,
        {"variables": {"query": "问", "chunks": [{"content": "段一"}, {"content": "段二"}]}},
        EngineContext(llm=llm),
    )
    assert llm.calls[0]["user_prompt"] == "问\n\n参考上下文：\n段一\n段二"
    assert state["variables"]["text"] == "模型回答"


@pytest.mark.asyncio
async def test_run_http_request_renders_and_exposes_fields(monkeypatch):
    captured: dict = {}
    response = _FakeResponse({"ok": True, "id": 7})
    monkeypatch.setattr(nodes.httpx, "AsyncClient", lambda **kwargs: _FakeClient(response, captured))
    node = _node(
        "http1",
        NodeType.HTTP_REQUEST,
        method="POST",
        url="https://api.test/{{ path }}",
        headers={"X-A": "{{ query }}"},
        params={"q": "{{ query }}"},
        body_type="json",
        body='{"q": "{{ query }}"}',
        output_var="http",
    )
    state = await nodes.run_http_request(
        node, {"variables": {"query": "甲", "path": "items"}}, EngineContext(llm=RecordingLLM())
    )
    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.test/items"
    assert captured["headers"] == {"X-A": "甲"}
    assert captured["params"] == {"q": "甲"}
    assert captured["json"] == {"q": "甲"}
    assert state["variables"]["http"]["body"] == {"ok": True, "id": 7}
    assert state["variables"]["http"]["status_code"] == 200
    assert state["variables"]["http1"] == state["variables"]["http"]


@pytest.mark.asyncio
async def test_run_http_request_falls_back_to_text_body(monkeypatch):
    captured: dict = {}
    response = _FakeResponse("raw text")
    monkeypatch.setattr(nodes.httpx, "AsyncClient", lambda **kwargs: _FakeClient(response, captured))
    node = _node("http1", NodeType.HTTP_REQUEST, method="GET", url="https://api.test/x", body_type="json", body="not-json")
    state = await nodes.run_http_request(node, {"variables": {}}, EngineContext(llm=RecordingLLM()))
    assert captured["content"] == "not-json"
    assert state["variables"]["http"]["body"] == "raw text"


@pytest.mark.asyncio
async def test_run_http_request_requires_url():
    with pytest.raises(ValueError, match="缺少 url"):
        await nodes.run_http_request(_node("http1", NodeType.HTTP_REQUEST, url="  "), {}, EngineContext(llm=RecordingLLM()))


@pytest.mark.asyncio
async def test_run_question_classifier_routes_to_matched_class():
    class _LLM:
        def __init__(self) -> None:
            self.prompt = ""

        async def __call__(self, **kwargs):
            self.prompt = kwargs["system_prompt"]
            return "退费"

    llm = _LLM()
    node = _node(
        "classifier1",
        NodeType.QUESTION_CLASSIFIER,
        classes=[{"id": "billing", "name": "计费"}, {"id": "refund", "name": "退费"}],
        output_var="class_name",
    )
    state = await nodes.run_question_classifier(node, {"variables": {"query": "我要退款"}}, EngineContext(llm=llm))
    assert state["route"] == "refund"
    assert state["variables"]["class_name"] == "refund"
    assert "计费" in llm.prompt and "只输出类别 id" in llm.prompt


@pytest.mark.asyncio
async def test_run_question_classifier_matches_id_and_falls_back():
    class _IdLLM:
        async def __call__(self, **kwargs):
            return "  BILLING  "

    node = _node("c", NodeType.QUESTION_CLASSIFIER, classes=[{"id": "billing", "name": "计费"}, {"id": "other", "name": "其它"}])
    variables = {"query": "问题"}
    state = await nodes.run_question_classifier(node, {"variables": variables}, EngineContext(llm=_IdLLM()))
    assert state["route"] == "billing"

    class _UnknownLLM:
        async def __call__(self, **kwargs):
            return "说不清"

    fallback = await nodes.run_question_classifier(node, {"variables": variables}, EngineContext(llm=_UnknownLLM()))
    assert fallback["route"] == "billing"


@pytest.mark.asyncio
async def test_run_question_classifier_requires_classes():
    with pytest.raises(ValueError, match="未定义类别"):
        await nodes.run_question_classifier(_node("c", NodeType.QUESTION_CLASSIFIER), {}, EngineContext(llm=RecordingLLM()))


def test_run_variable_assigner_writes_named_variables():
    node = _node(
        "assigner1",
        NodeType.VARIABLE_ASSIGNER,
        items=[{"name": "total", "expression": "1 + 2"}, {"name": "label", "expression": "query"}],
    )
    state = nodes.run_variable_assigner(node, {"variables": {"query": "甲"}}, EngineContext(llm=RecordingLLM()))
    assert state["variables"]["total"] == 3
    assert state["variables"]["label"] == "甲"
    assert state["variables"]["assigner1"] == {"total": 3, "label": "甲"}


def _list_result(config: dict, variables: dict | None = None):
    node = _node("list1", NodeType.LIST_OPERATOR, **config)
    return nodes.run_list_operator(node, {"variables": variables or {}}, EngineContext(llm=RecordingLLM()))["variables"][
        "list_result"
    ]


def test_run_list_operator_basic_operations():
    data = {"items": [3, 1, 2]}
    assert _list_result({"variable": "items", "operation": "first"}, data) == 3
    assert _list_result({"variable": "items", "operation": "last"}, data) == 2
    assert _list_result({"variable": "items", "operation": "at", "index": 1}, data) == 1
    assert _list_result({"variable": "items", "operation": "at", "index": 9}, data) is None
    assert _list_result({"variable": "items", "operation": "limit", "count": 2}, data) == [3, 1]
    assert _list_result({"variable": "items", "operation": "size"}, data) == 3
    assert _list_result({"variable": "items", "operation": "sort"}, data) == [1, 2, 3]
    assert _list_result({"variable": "items", "operation": "sort", "desc": True}, data) == [3, 2, 1]


def test_run_list_operator_filter_and_empty_source():
    data = {"items": [{"score": 5}, {"score": 9}]}
    assert _list_result({"variable": "items", "operation": "filter", "expression": "item.score > 6"}, data) == [{"score": 9}]
    assert _list_result({"variable": "", "operation": "size"}) == 0


def test_run_code_blocks_imports_and_print():
    config = CodeConfig(code="def main(**inputs):\n    import os\n    return {}\n")
    with pytest.raises(CodeExecutionError, match="代码节点执行失败"):
        run_code(config, {})

    printed = run_code(
        CodeConfig(code="def main(**inputs):\n    try:\n        print('x')\n    except Exception:\n        return {'blocked': True}\n    return {'blocked': False}\n"),
        {},
    )
    assert printed == {"blocked": True}
