"""智能体编排：7 种工作模式、提示词组装与节点接线。"""
from __future__ import annotations

import pytest

from agent_platform.api import services
from agent_platform.core.config import Settings
from agent_platform.engine import nodes
from agent_platform.engine.agents.modes import (
    ModeContext,
    run_agent_as_tool,
    run_consensus,
    run_deep_search,
    run_pipeline,
    run_plan_execute,
    run_react,
    run_reflection,
    run_supervisor,
)
from agent_platform.engine.agents.prompts import build_system_prompt, split_reasoning
from agent_platform.engine.agents.registry import AgentSpec, PromptSpec
from agent_platform.engine.agents.runner import build_agent_invoker
from agent_platform.engine.context import EngineContext
from agent_platform.graph.schema import AgentConfig, NodeDef, NodeType, ToolRef


class ScriptedLLM:
    """按脚本依次返回回复；脚本只剩一条时重复返回该条。"""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if not self.replies:
            return ""
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


async def _no_retriever(config, query, tenant_code=""):
    return []


async def _no_caller(name, args, *, server="", tenant_code=""):
    return None


def _mc(llm, retriever=None, caller=None) -> ModeContext:
    return ModeContext(
        llm=llm,
        caller=caller or _no_caller,
        retriever=retriever or _no_retriever,
        tenant_code="t",
    )


def _spec(code: str = "local.a", **fields) -> AgentSpec:
    data = {"code": code, "max_steps": 4, "temperature": 0.0}
    data.update(fields)
    return AgentSpec(**data)


def _seed_agent(code: str, **fields):
    return services.create_agent(tenant_code="t", code=code, **fields)


def test_agent_modes_include_autonomous():
    from agent_platform.engine.agents.modes import MODES
    from agent_platform.graph.schema import AGENT_MODES

    assert "autonomous" in AGENT_MODES
    assert "autonomous" in MODES


# --------------------------------------------------------------------------- 提示词


def test_build_system_prompt_adds_examples_and_cot():
    spec = _spec(system_prompt="基础人设", cot=True)
    template = PromptSpec(code="tpl", examples=[{"input": "i", "output": "o"}], cot_hint="拆解提示")
    text = build_system_prompt(spec, template)
    assert "基础人设" in text
    assert "示例 1" in text and "输入：i" in text and "输出：o" in text
    assert "拆解提示" in text
    assert "<reasoning>" in text


def test_build_system_prompt_falls_back_to_template_system():
    spec = _spec(system_prompt="")
    assert build_system_prompt(spec, PromptSpec(system_prompt="模板人设")) == "模板人设"
    assert build_system_prompt(spec, None) == ""


def test_split_reasoning_extracts_tag():
    answer, reasoning = split_reasoning("<reasoning>先看 A</reasoning>结论：先 A")
    assert reasoning == "先看 A"
    assert answer == "结论：先 A"
    assert split_reasoning("没有标签") == ("没有标签", "")
    assert split_reasoning("") == ("", "")


# --------------------------------------------------------------------------- react


@pytest.mark.asyncio
async def test_react_calls_tool_then_answers():
    llm = ScriptedLLM(['Action: {"name": "gov.lookup", "args": {"keyword": "社保"}}', "根据观察：社保需窗口办理。"])
    called: list[tuple] = []

    async def caller(name, args, *, server="", tenant_code=""):
        called.append((name, args, server, tenant_code))
        return {"items": ["社保"]}

    spec = _spec(tools=[ToolRef(name="gov.lookup", server="demo")])
    result = await run_react(spec, _mc(llm, caller=caller), {}, "社保怎么办", "你是助手")

    assert called == [("gov.lookup", {"keyword": "社保"}, "demo", "t")]
    assert result["answer"] == "根据观察：社保需窗口办理。"
    assert result["steps"][0]["action"] == "gov.lookup"
    assert result["steps"][0]["result"] == {"items": ["社保"]}


@pytest.mark.asyncio
async def test_react_without_tools_answers_directly():
    llm = ScriptedLLM(["直接回答"])
    result = await run_react(_spec(), _mc(llm), {}, "问题", "system")
    assert result["answer"] == "直接回答"
    assert result["steps"] == []
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_react_records_tool_errors_as_observation():
    llm = ScriptedLLM(['Action: {"name": "t1", "args": {}}', "工具不可用，直接说明。"])
    called = {"n": 0}

    async def caller(name, args, *, server="", tenant_code=""):
        called["n"] += 1
        raise RuntimeError("boom")

    result = await run_react(_spec(tools=[ToolRef(name="t1")]), _mc(llm, caller=caller), {}, "问题", "system")
    assert called["n"] == 1
    assert result["steps"][0]["result"] == {"error": "boom"}
    assert result["answer"] == "工具不可用，直接说明。"


@pytest.mark.asyncio
async def test_react_ignores_unknown_tool():
    llm = ScriptedLLM(['Action: {"name": "ghost", "args": {}}', "改用直接回答"])
    result = await run_react(_spec(tools=[ToolRef(name="t1")]), _mc(llm), {}, "问题", "system")
    assert result["steps"][0]["error"] == "未知工具"
    assert result["answer"] == "改用直接回答"


# --------------------------------------------------------------------------- plan-execute


@pytest.mark.asyncio
async def test_plan_execute_runs_planned_steps():
    llm = ScriptedLLM(['{"steps": ["查材料", "查渠道"]}', "材料：身份证", "渠道：政务网", "汇总：身份证 + 政务网"])
    result = await run_plan_execute(_spec(max_steps=3), _mc(llm), {}, "企业开办怎么办", "system")
    assert [item["step"] for item in result["steps"]] == ["查材料", "查渠道"]
    assert result["answer"] == "汇总：身份证 + 政务网"


@pytest.mark.asyncio
async def test_plan_execute_falls_back_when_plan_unparseable():
    llm = ScriptedLLM(["没有 JSON", "一步结论", "汇总答复"])
    result = await run_plan_execute(_spec(max_steps=2), _mc(llm), {}, "任务", "system")
    assert len(result["steps"]) == 1
    assert result["answer"] == "汇总答复"


# --------------------------------------------------------------------------- reflection


@pytest.mark.asyncio
async def test_reflection_revises_until_rounds_exhausted():
    llm = ScriptedLLM(["初稿", "建议补充办理渠道", "修订稿"])
    result = await run_reflection(_spec(reflection_rounds=1), _mc(llm), {}, "问题", "system")
    assert result["answer"] == "修订稿"
    assert result["steps"][0]["critique"] == "建议补充办理渠道"


@pytest.mark.asyncio
async def test_reflection_stops_when_critic_is_satisfied():
    llm = ScriptedLLM(["定稿", "无需修改"])
    result = await run_reflection(_spec(reflection_rounds=3), _mc(llm), {}, "问题", "system")
    assert result["answer"] == "定稿"
    assert len(result["steps"]) == 1


# --------------------------------------------------------------------------- pipeline / supervisor / agent-as-tool


@pytest.mark.asyncio
async def test_consensus_majority_vote_and_handoffs():
    _seed_agent("member.one", mode="react", system_prompt="一")
    _seed_agent("member.two", mode="react", system_prompt="二")
    _seed_agent("member.three", mode="react", system_prompt="三")
    llm = ScriptedLLM(["相同答案", "相同答案", "另一个答案"])
    spec = _spec(mode="consensus", pipeline=["member.one", "member.two", "member.three"])

    result = await run_consensus(spec, _mc(llm), {}, "任务", "system")

    assert result["answer"] == "相同答案"
    assert len(result["steps"]) == 3
    assert len(result["handoffs"]) == 3
    assert result["handoffs"][0]["from_agent"] == spec.code
    assert result["handoffs"][0]["to_agent"] == "member.one"


@pytest.mark.asyncio
async def test_consensus_tie_uses_judge():
    _seed_agent("member.one", mode="react", system_prompt="一")
    _seed_agent("member.two", mode="react", system_prompt="二")
    llm = ScriptedLLM(["答案 A", "答案 B", "合并答案"])
    spec = _spec(mode="consensus", pipeline=["member.one", "member.two"])

    result = await run_consensus(spec, _mc(llm), {}, "任务", "system")

    assert result["answer"] == "合并答案"
    assert result["route"] == "consensus"


@pytest.mark.asyncio
async def test_pipeline_chains_members_in_order():
    _seed_agent("member.one", mode="react", system_prompt="第一棒")
    _seed_agent("member.two", mode="react", system_prompt="第二棒")
    llm = ScriptedLLM(["第一棒结果", "第二棒结果"])
    spec = _spec(mode="pipeline", pipeline=["member.one", "member.two"])
    result = await run_pipeline(spec, _mc(llm), {}, "原始任务", "system")
    assert [item["agent"] for item in result["steps"]] == ["member.one", "member.two"]
    assert result["answer"] == "第二棒结果"
    assert "第一棒结果" in llm.calls[1]["user_prompt"]


@pytest.mark.asyncio
async def test_pipeline_single_self_member_does_not_recurse():
    llm = ScriptedLLM(["单次回答"])
    result = await run_pipeline(_spec(mode="pipeline"), _mc(llm), {}, "问题", "system")
    assert result["answer"] == "单次回答"
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_supervisor_routes_then_finishes():
    _seed_agent("member.one", mode="react", system_prompt="成员")
    llm = ScriptedLLM(["member.one", "成员答复", "finish"])
    spec = _spec(mode="supervisor", pipeline=["member.one"])
    result = await run_supervisor(spec, _mc(llm), {}, "任务", "system")
    assert result["route"] == "member.one"
    assert result["answer"] == "成员答复"
    assert [item["agent"] for item in result["steps"]] == ["member.one"]


@pytest.mark.asyncio
async def test_supervisor_without_members_degrades_to_react():
    llm = ScriptedLLM(["直接回答"])
    result = await run_supervisor(_spec(mode="supervisor"), _mc(llm), {}, "任务", "system")
    assert result["answer"] == "直接回答"
    assert not result.get("route")


@pytest.mark.asyncio
async def test_agent_as_tool_delegates_to_member():
    _seed_agent("member.one", mode="react", system_prompt="子智能体")
    llm = ScriptedLLM(['Action: {"name": "agent:member.one", "args": {"query": "子问题"}}', "子答复", "汇总答复"])
    spec = _spec(mode="agent_as_tool", pipeline=["member.one"])
    result = await run_agent_as_tool(spec, _mc(llm), {}, "主问题", "system")
    assert result["steps"][0]["agent"] == "member.one"
    assert result["steps"][0]["query"] == "子问题"
    assert result["answer"] == "汇总答复"


@pytest.mark.asyncio
async def test_agent_as_tool_without_members_degrades_to_react():
    llm = ScriptedLLM(["直接回答"])
    result = await run_agent_as_tool(_spec(mode="agent_as_tool"), _mc(llm), {}, "问题", "system")
    assert result["answer"] == "直接回答"


# --------------------------------------------------------------------------- deep search


@pytest.mark.asyncio
async def test_deep_search_expands_queries_and_collects_sources():
    llm = ScriptedLLM(["查询A\n查询B", "基于资料的回答"])
    queries: list[str] = []

    async def retriever(config, query, tenant_code=""):
        queries.append(query)
        return [{"content": f"{query}-内容", "document_name": "d", "score": 0.5}]

    spec = _spec(mode="deep_search", max_steps=3, retriever={"top_k": 2})
    result = await run_deep_search(spec, _mc(llm, retriever=retriever), {}, "原始问题", "system")

    assert queries[0] == "原始问题"
    assert "查询A" in queries and "查询B" in queries
    assert len(result["sources"]) == len(queries)
    assert result["answer"] == "基于资料的回答"


@pytest.mark.asyncio
async def test_deep_search_handles_empty_retrieval():
    llm = ScriptedLLM(["查询A", "资料不足，说明如下。"])
    result = await run_deep_search(_spec(mode="deep_search"), _mc(llm), {}, "冷门问题", "system")
    assert result["sources"] == []
    assert "未检索到资料" in llm.calls[-1]["user_prompt"]


# --------------------------------------------------------------------------- 节点与 runner 接线


@pytest.mark.asyncio
async def test_agent_node_stores_structured_result():
    async def invoker(config, variables, ctx, tenant_code=""):
        return {"answer": "答复", "reasoning": "推理", "steps": [], "sources": [], "route": "", "mode": "react"}

    ctx = EngineContext(llm=ScriptedLLM(["x"]), agents=invoker)
    node = NodeDef(id="agent1", type=NodeType.AGENT, config={"agent": "gov.intent", "output_var": "out"})
    state = await nodes.run_agent_node(node, {"variables": {"query": "x"}}, ctx)

    assert state["variables"]["out"] == "答复"
    assert state["variables"]["agent1"]["reasoning"] == "推理"


@pytest.mark.asyncio
async def test_agent_node_propagates_supervisor_route():
    async def invoker(config, variables, ctx, tenant_code=""):
        return {"answer": "a", "route": "billing"}

    ctx = EngineContext(llm=ScriptedLLM(["x"]), agents=invoker)
    node = NodeDef(id="agent1", type=NodeType.AGENT, config={"agent": "gov.intent"})
    state = await nodes.run_agent_node(node, {"variables": {}}, ctx)
    assert state["route"] == "billing"


@pytest.mark.asyncio
async def test_agent_node_without_runtime_reports_clear_error():
    node = NodeDef(id="agent1", type=NodeType.AGENT, config={"agent": "gov.intent"})
    with pytest.raises(RuntimeError, match="智能体运行时未配置"):
        await nodes.run_agent_node(node, {"variables": {}}, EngineContext(llm=ScriptedLLM(["x"])))


@pytest.mark.asyncio
async def test_build_agent_invoker_runs_definition_with_overrides():
    _seed_agent(
        "local.cot",
        mode="react",
        system_prompt="系统人设",
        cot=True,
        prompt_template="",
        provider="",
        max_steps=2,
    )
    invoker = build_agent_invoker(Settings())
    llm = ScriptedLLM(["<reasoning>推理过程</reasoning>最终答复"])
    ctx = EngineContext(llm=llm)

    config = AgentConfig(agent="local.cot", query="{{ query }}", inputs=[{"name": "topic", "expression": "query"}])
    result = await invoker(config, {"query": "社保"}, ctx, "t")

    assert result["answer"] == "最终答复"
    assert result["reasoning"] == "推理过程"
    assert result["mode"] == "react"
    assert "<reasoning>" in llm.calls[0]["system_prompt"]
    assert llm.calls[0]["user_prompt"] == "社保"


@pytest.mark.asyncio
async def test_build_agent_invoker_rejects_unknown_agent():
    invoker = build_agent_invoker(Settings())
    with pytest.raises(ValueError, match="未找到智能体定义"):
        await invoker(AgentConfig(agent="ghost"), {}, EngineContext(llm=ScriptedLLM(["x"])), "t")


@pytest.mark.asyncio
async def test_build_agent_invoker_runs_autonomous_mode():
    _seed_agent(
        "local.auto",
        mode="autonomous",
        system_prompt="系统人设",
        max_steps=2,
        reflection_rounds=0,
    )
    invoker = build_agent_invoker(Settings())
    llm = ScriptedLLM(["自主答复"])
    ctx = EngineContext(llm=llm)

    result = await invoker(AgentConfig(agent="local.auto", query="{{ query }}"), {"query": "问题"}, ctx, "t")

    assert result["answer"] == "自主答复"
    assert result["mode"] == "autonomous"
    assert result["steps"] == []
    assert result["reflection"] == []
    # autonomous 走 message 接口，且不会把旧 5 参数路径混在一起
    assert "messages" in llm.calls[0]
