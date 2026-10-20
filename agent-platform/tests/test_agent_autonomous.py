"""autonomous 模式：原生 tool_calls、消息栈、重规划、反思与降级。"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent_platform.engine.agents.modes import REPLAN_PROMPT, ModeContext, run_autonomous
from agent_platform.engine.agents.registry import AgentSpec
from agent_platform.graph.schema import ToolRef
from agent_platform.tools.schema import safe_function_name


class ScriptedToolLLM:
    """按脚本返回 AIMessage / str；脚本只剩一条时重复返回。"""

    def __init__(self, replies: list[object], *, fail_first: bool = False) -> None:
        self.replies = list(replies)
        self.calls: list[dict] = []
        self.fail_first = fail_first
        self._failed = False

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_first and not self._failed:
            self._failed = True
            raise RuntimeError("tools unsupported")
        if not self.replies:
            return AIMessage(content="")
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


@dataclass
class Binding:
    ref: ToolRef
    params: list = field(default_factory=list)


class FakeToolBox:
    def __init__(self, *, results=None, errors=None) -> None:
        self.results = results or {}
        self.errors = errors or {}
        self.calls: list[tuple[str, dict, str]] = []

    async def schemas(self, refs, tenant_code=""):
        schemas = []
        mapping = {}
        for ref in refs:
            name = safe_function_name(ref.name)
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": ref.name,
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            )
            mapping[name] = Binding(ref=ref)
        return schemas, mapping

    async def call(self, binding, args, tenant_code=""):
        self.calls.append((binding.ref.name, args, tenant_code))
        if binding.ref.name in self.errors:
            raise self.errors[binding.ref.name]
        return self.results.get(binding.ref.name, {"ok": True})


def _spec(**fields) -> AgentSpec:
    data = {"code": "local.autonomous", "mode": "autonomous", "max_steps": 4, "reflection_rounds": 0, "temperature": 0.0}
    data.update(fields)
    return AgentSpec(**data)


def _mc(llm, toolbox=None, *, tenant_code="t", max_chars=4000) -> ModeContext:
    async def no_retriever(config, query, tenant_code=""):
        return []

    async def no_caller(name, args, *, server="", tenant_code=""):
        return None

    return ModeContext(
        llm=llm,
        caller=no_caller,
        retriever=no_retriever,
        tenant_code=tenant_code,
        toolbox=toolbox,
        tool_result_max_chars=max_chars,
    )


def _tool_call(name: str, args: dict, call_id: str = "c1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


@pytest.mark.asyncio
async def test_native_tool_call_then_answer():
    llm = ScriptedToolLLM([_tool_call("gov_lookup", {"keyword": "社保"}), AIMessage(content="社保需窗口办理。")])
    toolbox = FakeToolBox(results={"gov.lookup": {"items": ["社保"]}})
    spec = _spec(tools=[ToolRef(name="gov.lookup", server="demo")])

    result = await run_autonomous(spec, _mc(llm, toolbox), {}, "社保怎么办", "你是助手")

    assert toolbox.calls == [("gov.lookup", {"keyword": "社保"}, "t")]
    assert result["answer"] == "社保需窗口办理。"
    assert result["steps"][0]["action"] == "gov.lookup"
    assert result["steps"][0]["result"] == {"items": ["社保"]}
    assert result["steps"][0]["tool_call_id"] == "c1"
    assert result["reflection"] == []
    # 第二轮请求应携带 ToolMessage
    second_messages = llm.calls[1]["messages"]
    assert any(isinstance(item, ToolMessage) and item.tool_call_id == "c1" for item in second_messages)


@pytest.mark.asyncio
async def test_parallel_tool_calls_in_one_message():
    reply = AIMessage(
        content="",
        tool_calls=[
            {"name": "t1", "args": {"q": 1}, "id": "c1"},
            {"name": "t2", "args": {"q": 2}, "id": "c2"},
        ],
    )
    llm = ScriptedToolLLM([reply, AIMessage(content="汇总完成")])
    toolbox = FakeToolBox(results={"t1": "一", "t2": "二"})
    spec = _spec(tools=[ToolRef(name="t1"), ToolRef(name="t2")])

    result = await run_autonomous(spec, _mc(llm, toolbox), {}, "任务", "system")

    assert [call[0] for call in toolbox.calls] == ["t1", "t2"]
    assert len(result["steps"]) == 2
    assert [step["tool_call_id"] for step in result["steps"]] == ["c1", "c2"]
    assert result["answer"] == "汇总完成"


@pytest.mark.asyncio
async def test_unknown_tool_is_reported_and_loop_continues():
    llm = ScriptedToolLLM([_tool_call("ghost", {}), AIMessage(content="改用直接回答")])
    toolbox = FakeToolBox()
    spec = _spec(tools=[ToolRef(name="t1")])

    result = await run_autonomous(spec, _mc(llm, toolbox), {}, "问题", "system")

    assert toolbox.calls == []
    assert result["steps"][0]["error"] == "未知工具"
    assert result["answer"] == "改用直接回答"


@pytest.mark.asyncio
async def test_consecutive_tool_failures_trigger_replan():
    llm = ScriptedToolLLM(
        [
            _tool_call("t1", {"attempt": 1}, "c1"),
            _tool_call("t1", {"attempt": 2}, "c2"),
            _tool_call("t1", {"attempt": 3}, "c3"),
            AIMessage(content="工具不可用，说明如下。"),
        ]
    )
    toolbox = FakeToolBox(errors={"t1": RuntimeError("boom")})
    spec = _spec(tools=[ToolRef(name="t1")], max_steps=5)

    result = await run_autonomous(spec, _mc(llm, toolbox), {}, "问题", "system")

    assert [step["result"] for step in result["steps"]] == [{"error": "boom"}] * 3
    assert result["answer"] == "工具不可用，说明如下。"
    # 第三次调用时 messages 里应出现重规划提示
    third_messages = llm.calls[2]["messages"]
    assert any(isinstance(item, HumanMessage) and REPLAN_PROMPT in str(item.content) for item in third_messages)


@pytest.mark.asyncio
async def test_repeated_call_stops_and_finalizes():
    llm = ScriptedToolLLM(
        [
            _tool_call("t1", {"q": "x"}, "c1"),
            _tool_call("t1", {"q": "x"}, "c2"),
            _tool_call("t1", {"q": "x"}, "c3"),
            AIMessage(content="重复调用已停止，给出最终答复。"),
        ]
    )
    toolbox = FakeToolBox(results={"t1": "ok"})
    spec = _spec(tools=[ToolRef(name="t1")], max_steps=5)

    result = await run_autonomous(spec, _mc(llm, toolbox), {}, "问题", "system")

    assert len(toolbox.calls) == 2
    assert result["steps"][-1]["error"] == "重复调用"
    assert result["answer"] == "重复调用已停止，给出最终答复。"


@pytest.mark.asyncio
async def test_max_rounds_finalizes_without_tools():
    llm = ScriptedToolLLM([_tool_call("t1", {}, "c1"), AIMessage(content="轮数用尽后的答复")])
    toolbox = FakeToolBox(results={"t1": "ok"})
    spec = _spec(tools=[ToolRef(name="t1")], max_steps=1)

    result = await run_autonomous(spec, _mc(llm, toolbox), {}, "问题", "system")

    assert result["answer"] == "轮数用尽后的答复"
    assert "tools" not in llm.calls[-1]
    assert "tool_choice" not in llm.calls[-1]


@pytest.mark.asyncio
async def test_text_action_fallback_when_gateway_ignores_tools():
    llm = ScriptedToolLLM(
        ['Action: {"name": "t1", "args": {"q": "x"}}', "根据工具观察回答"]
    )
    toolbox = FakeToolBox(results={"t1": "观察结果"})
    spec = _spec(tools=[ToolRef(name="t1")])

    result = await run_autonomous(spec, _mc(llm, toolbox), {}, "问题", "system")

    assert toolbox.calls == [("t1", {"q": "x"}, "t")]
    assert result["steps"][0]["action"] == "t1"
    assert result["answer"] == "根据工具观察回答"


@pytest.mark.asyncio
async def test_native_failure_falls_back_to_react():
    llm = ScriptedToolLLM(["文本协议答复"], fail_first=True)
    spec = _spec(tools=[ToolRef(name="t1")])

    result = await run_autonomous(spec, _mc(llm, FakeToolBox()), {}, "问题", "system")

    assert result["answer"] == "文本协议答复"
    assert result["steps"] == []


@pytest.mark.asyncio
async def test_history_and_summary_are_injected_as_messages():
    llm = ScriptedToolLLM([AIMessage(content="答复")])
    variables = {
        "summary": "之前聊过社保",
        "history": [
            {"role": "user", "content": "第一问"},
            {"role": "assistant", "content": "第一答"},
        ],
    }

    await run_autonomous(_spec(), _mc(llm, FakeToolBox()), variables, "第二问", "系统人设")

    messages = llm.calls[0]["messages"]
    assert isinstance(messages[0], SystemMessage) and "之前聊过社保" in messages[0].content
    assert isinstance(messages[1], SystemMessage) and "系统人设" in messages[1].content
    assert isinstance(messages[2], HumanMessage) and messages[2].content == "第一问"
    assert isinstance(messages[3], AIMessage) and messages[3].content == "第一答"
    assert isinstance(messages[4], HumanMessage) and messages[4].content == "第二问"


@pytest.mark.asyncio
async def test_reflection_revises_final_answer():
    llm = ScriptedToolLLM(
        [
            _tool_call("t1", {}, "c1"),
            "初稿",
            "建议补充渠道",
            "修订稿",
        ]
    )
    toolbox = FakeToolBox(results={"t1": "ok"})
    spec = _spec(tools=[ToolRef(name="t1")], reflection_rounds=1)

    result = await run_autonomous(spec, _mc(llm, toolbox), {}, "问题", "system")

    assert result["answer"] == "修订稿"
    assert result["reflection"][0]["critique"] == "建议补充渠道"


@pytest.mark.asyncio
async def test_tool_result_is_truncated_before_injection():
    llm = ScriptedToolLLM([_tool_call("t1", {}, "c1"), AIMessage(content="答复")])
    toolbox = FakeToolBox(results={"t1": "x" * 100})
    spec = _spec(tools=[ToolRef(name="t1")])

    await run_autonomous(spec, _mc(llm, toolbox, max_chars=10), {}, "问题", "system")

    tool_messages = [item for item in llm.calls[1]["messages"] if isinstance(item, ToolMessage)]
    assert len(tool_messages) == 1
    assert tool_messages[0].content.startswith("x" * 10)
    assert len(tool_messages[0].content) < 100


@pytest.mark.asyncio
async def test_without_toolbox_degrades_to_react():
    llm = ScriptedToolLLM(["直接回答"])
    spec = _spec(tools=[ToolRef(name="t1")])

    result = await run_autonomous(spec, _mc(llm, None), {}, "问题", "system")

    assert result["answer"] == "直接回答"


@pytest.mark.asyncio
async def test_no_tools_direct_answer_uses_message_interface():
    llm = ScriptedToolLLM([AIMessage(content="无工具回答")])
    spec = _spec(tools=[])

    result = await run_autonomous(spec, _mc(llm, FakeToolBox()), {}, "问题", "system")

    assert result["answer"] == "无工具回答"
    assert "messages" in llm.calls[0]
    assert "tools" not in llm.calls[0]
