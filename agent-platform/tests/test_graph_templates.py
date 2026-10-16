"""内置图模板：结构、合规判定表达式，以及「打回重写」回环与步数保护。"""
from __future__ import annotations

import pytest

from agent_platform.api import graph_templates
from agent_platform.core import agents_seed
from agent_platform.core.config import Settings
from agent_platform.engine.agents.runner import build_agent_invoker
from agent_platform.engine.context import EngineContext
from agent_platform.engine.expr import evaluate
from agent_platform.engine.runtime import run_graph
from agent_platform.graph.schema import GraphDef

TEMPLATE = graph_templates.GRAPH_TEMPLATES["pipeline.gov_consult"]
DEFINITION = TEMPLATE["definition"]


def _agent_by_id(node_id: str) -> dict:
    return next(node for node in DEFINITION["nodes"] if node["id"] == node_id)


def _edges_from(node_id: str) -> list[dict]:
    return [edge for edge in DEFINITION["edges"] if edge["source"] == node_id]


# --------------------------------------------------------------------------- 结构


def test_template_nodes_are_valid_and_ordered():
    graph_def = GraphDef.model_validate(DEFINITION)
    assert [node.type.value for node in graph_def.nodes] == [
        "start",
        "agent",
        "agent",
        "agent",
        "agent",
        "condition",
        "variable-assigner",
        "answer",
        "end",
    ]
    assert [node.typed_config().agent for node in graph_def.nodes[:5] if node.type.value == "agent"] == [
        "gov.intent",
        "gov.retrieval",
        "gov.generate",
        "gov.compliance",
    ]


def test_template_condition_branches_route_back_to_generate():
    config = _agent_by_id("cond6")["config"]
    assert config["fallback_id"] == "pass"
    assert [branch["id"] for branch in config["branches"]] == ["revise"]

    handles = {edge["source_handle"]: edge["target"] for edge in _edges_from("cond6")}
    assert handles == {"pass": "answer8", "revise": "revise7"}

    # 回环：计数节点回到内容生成
    assert [edge["target"] for edge in _edges_from("revise7")] == ["generate4"]
    assert _agent_by_id("revise7")["config"]["items"] == [
        {"name": "retry", "expression": "(retry | default(0) | int) + 1"}
    ]


def test_template_generate_query_mentions_compliance_feedback():
    query = _agent_by_id("generate4")["config"]["query"]
    assert "{% if (review | default('')) %}" in query
    assert "{{ review }}" in query


# --------------------------------------------------------------------------- 判定表达式


@pytest.mark.parametrize(
    ("verdict", "retry", "expected"),
    [
        ("判定：不通过\n理由：缺少依据。", 0, True),
        ("判定：通过\n理由：无问题。", 0, False),
        ('{"pass": false, "reason": "缺少依据"}', 0, True),
        ('{"pass": true, "reason": "无问题"}', 0, False),
        ("{'pass': false, 'reason': 'x'}", 0, True),
        ('{"pass":false}', 1, True),
        ("判定：不通过", 2, False),
        ('{"pass": false}', 2, False),
    ],
)
def test_revise_expression_detects_failed_compliance(verdict, retry, expected):
    assert bool(evaluate(graph_templates.REVISE_EXPRESSION, {"review": verdict, "retry": retry})) is expected


def test_revise_expression_is_safe_without_variables():
    # 首轮没有 review 也没有 retry，两个变量都缺省，不应报错
    assert evaluate(graph_templates.REVISE_EXPRESSION, {}) is False
    # review 已判定不通过、retry 尚未写入时按 0 计，应当重写
    assert evaluate(graph_templates.REVISE_EXPRESSION, {"review": "判定：不通过"}) is True


# --------------------------------------------------------------------------- 回环执行


class ScriptedAgentsLLM:
    """按 system 提示词识别是哪个智能体，返回对应脚本回复。"""

    def __init__(self, always_fail: bool = False) -> None:
        self.always_fail = always_fail
        self.calls: list[dict[str, str]] = []
        self.compliance_rounds = 0
        self.generate_rounds = 0

    def prompts_for(self, marker: str, field: str = "user_prompt") -> list[str]:
        return [call[field] for call in self.calls if marker in call["system_prompt"]]

    async def __call__(self, *, provider, system_prompt, user_prompt, temperature, max_tokens):
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        if "合规质检" in system_prompt:
            self.compliance_rounds += 1
            if self.always_fail or self.compliance_rounds == 1:
                return "判定：不通过\n理由：缺少政策依据。"
            return "判定：通过\n理由：无问题。"
        if "意图识别" in system_prompt:
            return "业务类型：市场准入；关键要素：营业执照变更"
        if "检索查询改写助手" in system_prompt:
            return ""
        if "知识检索" in system_prompt:
            return "资料：需提供身份证明与住所使用证明。"
        if "内容生成" in system_prompt:
            self.generate_rounds += 1
            return f"答复草稿第 {self.generate_rounds} 版"
        return "默认回复"


def _context(llm: ScriptedAgentsLLM) -> EngineContext:
    agents_seed.seed()
    return EngineContext(llm=llm, agents=build_agent_invoker(Settings()))


@pytest.mark.asyncio
async def test_template_rewrites_once_when_compliance_fails():
    llm = ScriptedAgentsLLM()
    state = await run_graph(GraphDef.model_validate(DEFINITION), {"query": "营业执照怎么变更？"}, _context(llm))

    assert llm.compliance_rounds == 2
    assert state["variables"]["retry"] == 1
    assert state["answer"].startswith("答复草稿第")
    assert "已按合规意见修订 1 轮" in state["answer"]

    # 首轮生成不带合规意见，重写那轮把合规意见回灌了进去
    generate_prompts = llm.prompts_for("内容生成")
    assert "缺少政策依据" not in generate_prompts[0]
    assert "缺少政策依据" in generate_prompts[-1]


@pytest.mark.asyncio
async def test_template_stops_rewriting_at_limit():
    llm = ScriptedAgentsLLM(always_fail=True)
    state = await run_graph(GraphDef.model_validate(DEFINITION), {"query": "营业执照怎么变更？"}, _context(llm))

    # 打回 2 次后计数器兜底，不会死循环
    assert state["variables"]["retry"] == graph_templates.MAX_COMPLIANCE_RETRIES
    assert llm.compliance_rounds == graph_templates.MAX_COMPLIANCE_RETRIES + 1
    assert state["answer"].startswith("答复草稿第")
    assert f"已按合规意见修订 {graph_templates.MAX_COMPLIANCE_RETRIES} 轮" in state["answer"]


@pytest.mark.asyncio
async def test_template_skips_rewrite_when_compliance_passes():
    class PassingLLM(ScriptedAgentsLLM):
        async def __call__(self, **kwargs):
            if "合规质检" in kwargs["system_prompt"]:
                self.compliance_rounds += 1
                return "判定：通过\n理由：无问题。"
            return await super().__call__(**kwargs)

    llm = PassingLLM()
    state = await run_graph(GraphDef.model_validate(DEFINITION), {"query": "营业执照怎么变更？"}, _context(llm))

    assert llm.compliance_rounds == 1
    assert "retry" not in state["variables"]
    assert "已按合规意见修订" not in state["answer"]
