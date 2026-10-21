"""Agent 轨迹评测：事件标准化、路径距离、禁用工具、LLM judge 与 CLI 门禁。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_platform.agentapp.eval import (
    AgentTrace,
    EvalCase,
    evaluate_cases,
    load_cases,
    load_traces,
    main,
    parse_sse_events,
    path_score,
    sequence_distance,
    trace_from_events,
)

ROOT = Path(__file__).resolve().parents[1]


def test_trace_from_events_standardizes_agent_stream():
    events = [
        {"type": "agent_plan", "plan": "先查资料"},
        {"type": "token", "content": "答"},
        {"type": "agent_tool", "tools": [{"tool": "knowledge_search", "content": "x"}]},
        {"type": "agent_reflection", "rounds": 1},
        {"type": "token", "content": "案"},
        {"type": "final", "answer": "答案", "state": {"variables": {"paused": False}}},
    ]

    trace = trace_from_events("case-1", events)

    assert trace.case_id == "case-1"
    assert trace.plan == "先查资料"
    assert trace.tool_calls == ["knowledge_search"]
    assert trace.reflections == 1
    assert trace.answer == "答案"
    assert trace.token_chars == 2
    assert trace.status == "completed"


def test_interrupt_marks_trace_paused():
    trace = trace_from_events(
        "case",
        [{"type": "agent_interrupt", "prompt": "approve?"}, {"type": "final", "answer": "approve?"}],
    )
    assert trace.status == "interrupted"


def test_sequence_distance_and_score():
    assert sequence_distance(["a", "b", "c"], ["a", "b", "c"]) == 0
    assert sequence_distance(["a", "b", "c"], ["a", "x"]) == 2
    exact, distance = path_score(["a", "b"], ["a", "b"])
    assert exact == 1.0 and distance == 0
    partial, distance = path_score(["a", "b", "c"], ["a", "x", "c"])
    assert partial < 1.0 and distance == 1


@pytest.mark.asyncio
async def test_exact_path_passes():
    case = EvalCase(
        id="ok",
        expected_tools=["knowledge_search", "delegate_gov.compliance"],
        answer_contains=["合规"],
    )
    trace = AgentTrace(
        case_id="ok",
        tool_calls=["knowledge_search", "delegate_gov.compliance"],
        answer="整体合规",
    )

    result = await evaluate_cases([case], {"ok": trace})

    assert result.passed == 1
    assert result.results[0].path_score == 1.0


@pytest.mark.asyncio
async def test_deviation_forbidden_and_answer_fail():
    case = EvalCase(
        id="bad",
        expected_tools=["a", "b", "c"],
        forbidden_tools=["delete_account"],
        answer_contains=["必须包含"],
    )
    trace = AgentTrace(case_id="bad", tool_calls=["a", "delete_account"], answer="其它")

    result = await evaluate_cases([case], {"bad": trace})

    item = result.results[0]
    assert not item.passed
    assert item.distance > 0
    assert item.forbidden_hits == ["delete_account"]
    assert item.missing_answer == ["必须包含"]


@pytest.mark.asyncio
async def test_tool_count_status_and_missing_trace_fail():
    case = EvalCase(
        id="limit",
        expected_tools=["a"],
        max_tool_calls=1,
        require_status="completed",
    )
    trace = AgentTrace(case_id="limit", tool_calls=["a", "b"], status="interrupted")

    result = await evaluate_cases([case], {"limit": trace})

    assert not result.results[0].passed
    assert any("次数超限" in reason for reason in result.results[0].reasons)
    assert any("状态不符" in reason for reason in result.results[0].reasons)

    missing = await evaluate_cases([case], {})
    assert not missing.results[0].passed
    assert missing.results[0].reasons == ["缺少对应轨迹"]


@pytest.mark.asyncio
async def test_llm_judge_can_fail_or_pass():
    case = EvalCase(id="judge", expected_tools=[], judge=True, judge_min_score=0.7)
    trace = AgentTrace(case_id="judge", answer="答案")

    async def low_judge(query: str, answer: str, _case: EvalCase):
        return {"score": 0.2, "reason": "答非所问"}

    async def high_judge(query: str, answer: str, _case: EvalCase):
        return 0.9

    assert not (await evaluate_cases([case], {"judge": trace}, judge=low_judge)).results[0].passed
    assert (await evaluate_cases([case], {"judge": trace}, judge=high_judge)).results[0].passed
    missing_judge = await evaluate_cases([case], {"judge": trace})
    assert not missing_judge.results[0].passed
    assert any("未配置 judge" in reason for reason in missing_judge.results[0].reasons)


def test_parse_sse_events_ignores_invalid_lines():
    events = parse_sse_events(
        'event: message\ndata: {"type": "token", "content": "x"}\n\nnot-json\ndata: bad\n'
    )
    assert events == [{"type": "token", "content": "x"}]


def test_trace_collects_tool_args_and_latency():
    events = [
        {"type": "agent_tool_call", "ts": 10.0, "calls": [{"id": "c1", "name": "weather", "args": {"city": "常州"}}]},
        {"type": "agent_tool", "ts": 10.2, "tools": [{"tool": "weather", "tool_call_id": "c1", "content": "晴"}]},
        {"type": "final", "ts": 11.0, "answer": "常州晴"},
    ]

    trace = trace_from_events("c1", events)

    assert trace.tool_calls == ["weather"]
    assert trace.tool_events[0]["args"] == {"city": "常州"}
    assert trace.tool_events[0]["duration_ms"] == 200
    assert trace.duration_ms == 1000


@pytest.mark.asyncio
async def test_expected_args_and_duration_constraints():
    case = EvalCase(
        id="args",
        expected_tools=["weather"],
        expected_tool_args={"weather": {"city": "常州"}},
        max_duration_ms=500,
    )
    good = AgentTrace(
        case_id="args",
        tool_calls=["weather"],
        tool_events=[{"name": "weather", "args": {"city": "常州"}}],
        duration_ms=300,
        answer="ok",
    )
    bad = AgentTrace(
        case_id="args",
        tool_calls=["weather"],
        tool_events=[{"name": "weather", "args": {"city": "南京"}}],
        duration_ms=900,
        answer="ok",
    )

    assert (await evaluate_cases([case], {"args": good})).passed == 1
    result = (await evaluate_cases([case], {"args": bad})).results[0]
    assert not result.passed
    assert result.arg_mismatches
    assert any("耗时超限" in reason for reason in result.reasons)


def test_example_eval_files_pass_as_ci_gate(capsys):
    cases = load_cases(ROOT / "evals/agent_cases.example.jsonl")
    traces = load_traces(ROOT / "evals/agent_traces.example.jsonl")

    assert main(["--cases", str(ROOT / "evals/agent_cases.example.jsonl"), "--traces", str(ROOT / "evals/agent_traces.example.jsonl")]) == 0
    output = capsys.readouterr().out
    assert "2/2 通过" in output
    assert len(cases) == 2 and len(traces) == 2


def test_cli_returns_nonzero_on_path_deviation(tmp_path):
    cases = tmp_path / "cases.jsonl"
    traces = tmp_path / "traces.jsonl"
    cases.write_text(
        json.dumps({"id": "c1", "expected_tools": ["a", "b"]}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    traces.write_text(
        json.dumps({"id": "c1", "tool_calls": ["a", "x"], "answer": "ok"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    assert main(["--cases", str(cases), "--traces", str(traces)]) == 1
