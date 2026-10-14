"""节点执行：知识 / 工具 / 代码 / 聚合 / 条件 / 结束 与受限代码沙箱。"""
from __future__ import annotations

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


def test_run_code_blocks_imports_and_print():
    config = CodeConfig(code="def main(**inputs):\n    import os\n    return {}\n")
    with pytest.raises(CodeExecutionError, match="代码节点执行失败"):
        run_code(config, {})

    printed = run_code(
        CodeConfig(code="def main(**inputs):\n    try:\n        print('x')\n    except Exception:\n        return {'blocked': True}\n    return {'blocked': False}\n"),
        {},
    )
    assert printed == {"blocked": True}
