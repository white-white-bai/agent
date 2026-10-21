"""Agent 执行轨迹评测：轨迹标准化、工具路径距离、禁用工具/答案约束与可选 LLM judge。

设计目标：CI 里回放录制好的轨迹，工具调用顺序偏离标准路径即失败；不依赖 Langfuse 在线服务。
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

Judge = Callable[[str, str, "EvalCase"], Awaitable[dict[str, Any] | float]]


@dataclass
class AgentTrace:
    """一条可评测的 Agent 执行轨迹。"""

    case_id: str = ""
    tool_calls: list[str] = field(default_factory=list)
    plan: str = ""
    reflections: int = 0
    answer: str = ""
    status: str = "completed"
    token_chars: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.case_id,
            "tool_calls": self.tool_calls,
            "plan": self.plan,
            "reflections": self.reflections,
            "answer": self.answer,
            "status": self.status,
            "token_chars": self.token_chars,
            "error": self.error,
        }


class EvalCase(BaseModel):
    """一条评测用例；expected_tools 是标准工具调用序列。"""

    id: str
    query: str = ""
    expected_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    answer_contains: list[str] = Field(default_factory=list)
    min_path_score: float = 1.0
    max_tool_calls: int | None = None
    require_status: str = ""
    judge: bool = False
    judge_min_score: float = 0.7


@dataclass
class EvalResult:
    case_id: str
    passed: bool
    path_score: float
    distance: int
    expected_tools: list[str]
    actual_tools: list[str]
    forbidden_hits: list[str] = field(default_factory=list)
    missing_answer: list[str] = field(default_factory=list)
    judge_score: float | None = None
    reasons: list[str] = field(default_factory=list)
    trace: AgentTrace | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.case_id,
            "passed": self.passed,
            "path_score": self.path_score,
            "distance": self.distance,
            "expected_tools": self.expected_tools,
            "actual_tools": self.actual_tools,
            "forbidden_hits": self.forbidden_hits,
            "missing_answer": self.missing_answer,
            "judge_score": self.judge_score,
            "reasons": self.reasons,
            "trace": self.trace.to_dict() if self.trace else None,
        }


@dataclass
class EvalReport:
    results: list[EvalResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for item in self.results if item.passed)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "results": [item.to_dict() for item in self.results],
        }


def _tool_name(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        return str(item.get("tool") or item.get("name") or "").strip()
    return ""


def trace_from_events(case_id: str, events: Iterable[dict[str, Any]], *, answer: str = "") -> AgentTrace:
    """把 stream_agent 的 SSE 事件标准化为轨迹。"""
    trace = AgentTrace(case_id=case_id, answer=answer)
    for event in events or []:
        if not isinstance(event, dict):
            continue
        kind = str(event.get("type") or "")
        if kind == "token":
            trace.token_chars += len(str(event.get("content") or ""))
        elif kind == "agent_plan":
            trace.plan = str(event.get("plan") or "")
        elif kind == "agent_tool":
            for item in event.get("tools") or []:
                name = _tool_name(item)
                if name:
                    trace.tool_calls.append(name)
        elif kind == "agent_reflection":
            trace.reflections = max(trace.reflections, int(event.get("rounds") or 0))
        elif kind == "agent_interrupt":
            trace.status = "interrupted"
        elif kind == "error":
            trace.status = "failed"
            trace.error = str(event.get("message") or event.get("error") or "")
        elif kind == "final":
            trace.answer = str(event.get("answer") or trace.answer)
            state = event.get("state") or {}
            variables = state.get("variables") if isinstance(state, dict) else {}
            if isinstance(variables, dict) and variables.get("paused"):
                trace.status = "interrupted"
    return trace


def normalize_trace(payload: dict[str, Any], *, fallback_id: str = "") -> AgentTrace:
    """兼容录制轨迹字典（tool_calls 直出）与事件列表两种格式。"""
    case_id = str(payload.get("id") or payload.get("case_id") or fallback_id)
    if "events" in payload:
        trace = trace_from_events(case_id, payload.get("events") or [], answer=str(payload.get("answer") or ""))
    else:
        tools = payload.get("tool_calls")
        if tools is None:
            tools = payload.get("tools") or []
        trace = AgentTrace(
            case_id=case_id,
            tool_calls=[name for item in tools or [] if (name := _tool_name(item))],
            plan=str(payload.get("plan") or ""),
            reflections=int(payload.get("reflections") or 0),
            answer=str(payload.get("answer") or ""),
            status=str(payload.get("status") or "completed"),
            token_chars=int(payload.get("token_chars") or 0),
            error=str(payload.get("error") or ""),
        )
    for key in ("answer", "status", "plan", "error"):
        value = payload.get(key)
        if value not in (None, ""):
            setattr(trace, key, str(value))
    if payload.get("reflections") is not None:
        trace.reflections = int(payload.get("reflections") or 0)
    if payload.get("token_chars") is not None:
        trace.token_chars = int(payload.get("token_chars") or 0)
    return trace


def sequence_distance(expected: list[str], actual: list[str]) -> int:
    """Levenshtein 编辑距离：插入/删除/替换工具各计 1。"""
    previous = list(range(len(actual) + 1))
    for index, left in enumerate(expected, start=1):
        current = [index]
        for offset, right in enumerate(actual, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[offset] + 1,
                    previous[offset - 1] + (left != right),
                )
            )
        previous = current
    return previous[-1]


def path_score(expected: list[str], actual: list[str]) -> tuple[float, int]:
    distance = sequence_distance(expected, actual)
    longest = max(len(expected), len(actual), 1)
    return max(0.0, 1.0 - distance / longest), distance


def _normalize_judge(value: dict[str, Any] | float) -> tuple[float, str]:
    if isinstance(value, (int, float)):
        return max(0.0, min(float(value), 1.0)), ""
    score = float(value.get("score") or 0.0)
    return max(0.0, min(score, 1.0)), str(value.get("reason") or "")


async def score_trace(trace: AgentTrace, case: EvalCase, judge: Judge | None = None) -> EvalResult:
    score, distance = path_score(case.expected_tools, trace.tool_calls)
    forbidden = [name for name in trace.tool_calls if name in set(case.forbidden_tools)]
    missing = [text for text in case.answer_contains if text not in trace.answer]
    reasons: list[str] = []
    if score < case.min_path_score:
        reasons.append(f"工具路径偏离：期望 {case.expected_tools}，实际 {trace.tool_calls}")
    if forbidden:
        reasons.append(f"调用了禁用工具：{forbidden}")
    if missing:
        reasons.append(f"答案缺少关键内容：{missing}")
    if case.require_status and trace.status != case.require_status:
        reasons.append(f"状态不符：期望 {case.require_status}，实际 {trace.status}")
    if case.max_tool_calls is not None and len(trace.tool_calls) > case.max_tool_calls:
        reasons.append(f"工具调用次数超限：{len(trace.tool_calls)} > {case.max_tool_calls}")

    judge_score: float | None = None
    if case.judge:
        if judge is None:
            reasons.append("用例要求 LLM judge，但未配置 judge")
        else:
            try:
                judge_score, judge_reason = _normalize_judge(await judge(case.query, trace.answer, case))
            except Exception as exc:  # noqa: BLE001 - judge 失败按 0 分处理，不阻断其它规则
                judge_score = 0.0
                judge_reason = f"judge 调用失败: {exc}"
            if judge_score < case.judge_min_score:
                reasons.append(f"LLM judge 未通过：{judge_score:.2f} < {case.judge_min_score:.2f} {judge_reason}".strip())

    return EvalResult(
        case_id=case.id,
        passed=not reasons,
        path_score=score,
        distance=distance,
        expected_tools=list(case.expected_tools),
        actual_tools=list(trace.tool_calls),
        forbidden_hits=forbidden,
        missing_answer=missing,
        judge_score=judge_score,
        reasons=reasons,
        trace=trace,
    )


async def evaluate_cases(
    cases: Iterable[EvalCase],
    traces: dict[str, AgentTrace] | Iterable[AgentTrace],
    judge: Judge | None = None,
) -> EvalReport:
    if not isinstance(traces, dict):
        traces = {trace.case_id: trace for trace in traces}
    report = EvalReport()
    for case in cases:
        trace = traces.get(case.id)
        if trace is None:
            report.results.append(
                EvalResult(
                    case_id=case.id,
                    passed=False,
                    path_score=0.0,
                    distance=len(case.expected_tools),
                    expected_tools=list(case.expected_tools),
                    actual_tools=[],
                    reasons=["缺少对应轨迹"],
                )
            )
            continue
        report.results.append(await score_trace(trace, case, judge=judge))
    return report


def _load_records(path: str | Path) -> list[dict[str, Any]]:
    text = Path(path).read_text(encoding="utf-8")
    if not text.strip():
        return []
    if str(path).endswith(".jsonl"):
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("cases", "traces", "items", "data"):
            if isinstance(payload.get(key), list):
                return payload[key]
        return [payload]
    raise ValueError(f"无法识别的评测文件：{path}")


def load_cases(path: str | Path) -> list[EvalCase]:
    return [EvalCase.model_validate(item) for item in _load_records(path)]


def load_traces(path: str | Path) -> dict[str, AgentTrace]:
    traces: dict[str, AgentTrace] = {}
    for item in _load_records(path):
        trace = normalize_trace(item)
        if trace.case_id:
            traces[trace.case_id] = trace
    return traces


def render_report(report: EvalReport) -> str:
    lines = [f"Agent 轨迹评测：{report.passed}/{report.total} 通过，{report.failed} 失败"]
    for item in report.results:
        mark = "PASS" if item.passed else "FAIL"
        lines.append(
            f"[{mark}] {item.case_id} path={item.path_score:.2f} distance={item.distance} "
            f"actual={item.actual_tools}"
        )
        for reason in item.reasons:
            lines.append(f"       - {reason}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="回放 Agent 轨迹并按标准工具路径打分")
    parser.add_argument("--cases", required=True, help="评测用例 JSON/JSONL")
    parser.add_argument("--traces", required=True, help="录制轨迹 JSON/JSONL")
    parser.add_argument("--json", action="store_true", help="输出 JSON 报告")
    args = parser.parse_args(argv)

    report = _run_async(evaluate_cases(load_cases(args.cases), load_traces(args.traces)))
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(render_report(report))
    return 0 if report.failed == 0 else 1


def _run_async(coro: Awaitable[EvalReport]) -> EvalReport:
    import asyncio

    return asyncio.run(coro)  # type: ignore[arg-type]
