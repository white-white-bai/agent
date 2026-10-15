"""7 种 Agent 工作模式：react / plan_execute / reflection / supervisor / pipeline / agent_as_tool / deep_search。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import Any

from agent_platform.engine.agents.prompts import build_system_prompt
from agent_platform.engine.agents.registry import AgentSpec, load_agent, load_template
from agent_platform.graph.schema import KnowledgeConfig, ToolRef

MAX_DEPTH = 3
ACTION_HEAD = re.compile(r"Action\s*[:：]\s*", re.IGNORECASE)
PLAN_JSON = re.compile(r"\{.*\}", re.DOTALL)
CRITIQUE_PROMPT = "请严格审查上一条回答：指出事实错误、信息遗漏与不合规表达，并给出修改建议。若确实无需修改，只回答「无需修改」。"
REVISE_PROMPT = "请根据审查意见修订回答，直接输出修订后的完整答复正文。"


@dataclass
class ModeContext:
    """模式运行时依赖：模型 / 工具调用器 / 检索器 / 租户 / 递归深度。"""

    llm: Any
    caller: Any
    retriever: Any
    tenant_code: str = ""
    depth: int = 0


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


async def _ask(
    mc: ModeContext,
    spec: AgentSpec,
    system: str,
    user: str,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    return await mc.llm(
        provider=spec.provider,
        system_prompt=system,
        user_prompt=user,
        temperature=spec.temperature if temperature is None else temperature,
        max_tokens=spec.max_tokens if max_tokens is None else max_tokens,
    )


def _retriever_config(spec: AgentSpec) -> KnowledgeConfig:
    data = spec.retriever or {}
    threshold = data.get("score_threshold")
    return KnowledgeConfig(
        retriever=str(data.get("retriever") or "builtin"),
        dataset_ids=[str(item) for item in (data.get("dataset_ids") or [])],
        top_k=int(data.get("top_k") or 5),
        score_threshold=float(threshold) if threshold is not None else None,
    )


def _tool_hint(tools: list[ToolRef]) -> str:
    if not tools:
        return ""
    names = "、".join(ref.name for ref in tools)
    return (
        f"可用工具：{names}。需要调用工具时，单独输出一行：\n"
        'Action: {"name": "工具名", "args": {...}}\n'
        "拿到观察结果后再继续；信息足够时直接给出最终答复（不要再输出 Action）。"
    )


def _first_json_object(text: str, start: int) -> dict[str, Any] | None:
    """从 start 处的 `{` 起做括号配对，尽量解析出一个 JSON 对象。"""
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    payload = json.loads(text[start : index + 1])
                except (ValueError, TypeError):
                    return None
                return payload if isinstance(payload, dict) else None
    return None


def _extract_action(text: str) -> tuple[str, dict[str, Any]] | None:
    head = ACTION_HEAD.search(text or "")
    if head is None:
        return None
    start = text.find("{", head.end())
    if start < 0:
        return None
    payload = _first_json_object(text, start)
    if payload is None:
        return None
    name = str(payload.get("name") or "")
    if not name:
        return None
    args = payload.get("args")
    return name, args if isinstance(args, dict) else {}


def _parse_steps(raw: str) -> list[str]:
    found = PLAN_JSON.search(raw or "")
    if found is None:
        return []
    try:
        payload = json.loads(found.group(0))
    except (ValueError, TypeError):
        return []
    steps = payload.get("steps") if isinstance(payload, dict) else payload
    if not isinstance(steps, list):
        return []
    return [str(item).strip() for item in steps if str(item).strip()]


def _find_ref(tools: list[ToolRef], name: str) -> ToolRef | None:
    return next((ref for ref in tools if ref.name == name), None)


def _render_history(history: list[dict[str, str]]) -> str:
    return "\n".join(f"{item['agent']}：{item['answer']}" for item in history)


def _match_member(choice: str, members: list[str]) -> str | None:
    text = (choice or "").strip().strip("\"'`").lower()
    if not text or "finish" in text:
        return None
    for code in members:
        if text == code.lower():
            return code
    for code in members:
        if code.lower() in text:
            return code
    return None


# --------------------------------------------------------------------------- 模式实现


async def run_react(
    spec: AgentSpec, mc: ModeContext, variables: dict[str, Any], query: str, system: str
) -> dict[str, Any]:
    """ReAct：Thought → Action（工具）→ Observation 循环；无工具时等价于带 CoT 的一次推理。"""
    hint = _tool_hint(spec.tools)
    base_system = "\n\n".join(part for part in (system, hint) if part)
    steps: list[dict[str, Any]] = []
    observation = ""
    answer = ""
    for _ in range(max(int(spec.max_steps or 1), 1)):
        user = query if not observation else f"{query}\n\n已有观察：\n{observation}"
        reply = await _ask(mc, spec, base_system, user)
        action = _extract_action(reply) if spec.tools else None
        if action is None:
            answer = reply.strip()
            break
        name, args = action
        ref = _find_ref(spec.tools, name)
        if ref is None:
            steps.append({"action": name, "args": args, "error": "未知工具"})
            observation = f"{observation}\n{name} 不在可用工具列表".strip()
            continue
        try:
            result = await mc.caller(name, args, server=ref.server, tenant_code=mc.tenant_code)
        except Exception as exc:  # noqa: BLE001 - 工具失败转为观察结果，继续推理
            result = {"error": str(exc)}
        steps.append({"action": name, "args": args, "result": result})
        observation = f"{observation}\n{name} -> {_text(result)}".strip()
    if not answer:
        answer = await _ask(mc, spec, base_system, f"{query}\n\n已知观察：\n{observation}\n\n请给出最终答复。")
    return {"answer": answer.strip(), "steps": steps}


async def run_plan_execute(
    spec: AgentSpec, mc: ModeContext, variables: dict[str, Any], query: str, system: str
) -> dict[str, Any]:
    """Plan-and-Execute：先出 JSON 计划，再逐步执行，最后汇总。"""
    limit = max(int(spec.max_steps or 1), 1)
    raw = await _ask(
        mc,
        spec,
        system,
        f'请把任务拆解成不超过 {limit} 个可执行步骤，只输出 JSON：{{"steps": ["步骤1", "步骤2"]}}。\n任务：{query}',
        temperature=0.0,
    )
    steps = _parse_steps(raw)[:limit] or [query]
    results: list[dict[str, Any]] = []
    accumulated = ""
    for index, step in enumerate(steps, start=1):
        user = (
            f"任务总目标：{query}\n已完成：\n{accumulated or '（无）'}\n\n"
            f"当前步骤 {index}：{step}\n\n请给出这一步的结论。"
        )
        reply = await _ask(mc, spec, system, user)
        results.append({"step": step, "answer": reply.strip()})
        accumulated = f"{accumulated}\n步骤{index}：{reply.strip()}".strip()
    answer = await _ask(mc, spec, system, f"任务：{query}\n\n各步骤结论：\n{accumulated}\n\n请汇总成最终答复。")
    return {"answer": answer.strip(), "steps": results}


async def run_reflection(
    spec: AgentSpec, mc: ModeContext, variables: dict[str, Any], query: str, system: str
) -> dict[str, Any]:
    """Reflection：生成 → 自我审查 → 修订，迭代若干轮。"""
    draft = (await _ask(mc, spec, system, query)).strip()
    rounds: list[dict[str, str]] = []
    critic_system = "\n\n".join(part for part in ("你是严格的审查者。", system) if part)
    for _ in range(max(int(spec.reflection_rounds or 0), 0)):
        critique = (
            await _ask(
                mc,
                spec,
                critic_system,
                f"原始任务：{query}\n\n待审查回答：\n{draft}\n\n{CRITIQUE_PROMPT}",
            )
        ).strip()
        rounds.append({"draft": draft, "critique": critique})
        if "无需修改" in critique:
            break
        draft = (
            await _ask(
                mc,
                spec,
                system,
                f"原始任务：{query}\n\n当前回答：\n{draft}\n\n审查意见：\n{critique}\n\n{REVISE_PROMPT}",
            )
        ).strip()
    return {"answer": draft, "steps": rounds}


async def run_pipeline(
    spec: AgentSpec, mc: ModeContext, variables: dict[str, Any], query: str, system: str
) -> dict[str, Any]:
    """Pipeline：按成员顺序依次执行，上游结果作为下游输入。"""
    members = spec.pipeline or [spec.code]
    steps: list[dict[str, str]] = []
    upstream = ""
    for index, code in enumerate(members):
        if code == spec.code and index == 0 and len(members) == 1:
            reply = (await _ask(mc, spec, system, query)).strip()
            steps.append({"agent": code, "answer": reply})
            upstream = reply
            break
        sub_spec = load_agent(code, mc.tenant_code, spec.max_steps)
        sub_system = build_system_prompt(sub_spec, load_template(sub_spec.prompt_template, mc.tenant_code))
        user = query if not upstream else f"原始问题：{query}\n\n上游结果：\n{upstream}"
        result = await run_spec(sub_spec, mc, variables, user, sub_system)
        answer = str(result.get("answer") or "").strip()
        steps.append({"agent": code, "answer": answer})
        upstream = answer
    return {"answer": upstream, "steps": steps}


async def run_supervisor(
    spec: AgentSpec, mc: ModeContext, variables: dict[str, Any], query: str, system: str
) -> dict[str, Any]:
    """Supervisor Router：路由模型每轮挑一个成员执行，直到 finish；终选写入 route。"""
    members = spec.pipeline
    if not members:
        return await run_react(spec, mc, variables, query, system)
    history: list[dict[str, str]] = []
    route = ""
    router_system = system or "你是任务调度器，只输出一个名字。"
    for _ in range(max(int(spec.max_steps or 1), 1)):
        prompt = (
            f"可选智能体：{'、'.join([*members, 'finish'])}\n"
            f"执行记录：\n{_render_history(history) or '（无）'}\n\n"
            f"任务：{query}\n\n只输出下一步要调用的智能体名；全部完成则输出 finish。"
        )
        choice = await _ask(mc, spec, router_system, prompt, temperature=0.0, max_tokens=32)
        picked = _match_member(choice, members)
        if picked is None:
            break
        sub_spec = load_agent(picked, mc.tenant_code, spec.max_steps)
        sub_system = build_system_prompt(sub_spec, load_template(sub_spec.prompt_template, mc.tenant_code))
        user = query if not history else f"原始问题：{query}\n\n上游结果：\n{history[-1]['answer']}"
        result = await run_spec(sub_spec, mc, variables, user, sub_system)
        history.append({"agent": picked, "answer": str(result.get("answer") or "")})
        route = picked
    return {"answer": history[-1]["answer"] if history else "", "steps": history, "route": route}


async def run_agent_as_tool(
    spec: AgentSpec, mc: ModeContext, variables: dict[str, Any], query: str, system: str
) -> dict[str, Any]:
    """Agent-as-Tool：把子智能体暴露成工具，主智能体通过 Action 委派。"""
    members = spec.pipeline
    if not members:
        return await run_react(spec, mc, variables, query, system)
    hint = (
        f"可委派的子智能体：{'、'.join(f'agent:{code}' for code in members)}。"
        '需要委派时单独输出一行：Action: {"name": "agent:<code>", "args": {"query": "..."}}'
    )
    base_system = "\n\n".join(part for part in (system, hint) if part)
    steps: list[dict[str, str]] = []
    observation = ""
    answer = ""
    for _ in range(max(int(spec.max_steps or 1), 1)):
        user = query if not observation else f"{query}\n\n已有观察：\n{observation}"
        reply = await _ask(mc, spec, base_system, user)
        action = _extract_action(reply)
        if action is None:
            answer = reply.strip()
            break
        name, args = action
        code = name.split(":", 1)[1].strip() if name.lower().startswith("agent:") else ""
        if code not in members:
            observation = f"{observation}\n未知子智能体 {name}".strip()
            continue
        sub_spec = load_agent(code, mc.tenant_code, spec.max_steps)
        sub_system = build_system_prompt(sub_spec, load_template(sub_spec.prompt_template, mc.tenant_code))
        sub_query = str(args.get("query") or query)
        result = await run_spec(sub_spec, mc, variables, sub_query, sub_system)
        sub_answer = str(result.get("answer") or "")
        steps.append({"agent": code, "query": sub_query, "answer": sub_answer})
        observation = f"{observation}\n{code} -> {sub_answer}".strip()
    if not answer:
        answer = await _ask(mc, spec, base_system, f"{query}\n\n已有观察：\n{observation}\n\n请给出最终答复。")
    return {"answer": answer.strip(), "steps": steps}


async def run_deep_search(
    spec: AgentSpec, mc: ModeContext, variables: dict[str, Any], query: str, system: str
) -> dict[str, Any]:
    """Deep Search：查询改写 → 多轮检索去重 → 基于资料作答并标注引用。"""
    config = _retriever_config(spec)
    limit = max(int(spec.max_steps or 1), 1)
    expanded = await _ask(
        mc,
        spec,
        "你是检索查询改写助手。",
        f"请为下面的问题给出 3 条互补的检索式，每行一条，不要编号。\n问题：{query}",
        temperature=0.0,
        max_tokens=200,
    )
    queries = [query]
    for line in (expanded or "").splitlines():
        text = line.strip().lstrip("-*0123456789.、 ")
        if text and text not in queries:
            queries.append(text)
    seen: set[str] = set()
    sources: list[dict[str, Any]] = []
    rounds: list[dict[str, Any]] = []
    for item in queries[:limit]:
        chunks = await mc.retriever(config, item, mc.tenant_code)
        fresh = 0
        for chunk in chunks or []:
            key = str(chunk.get("content") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            sources.append(chunk)
            fresh += 1
        rounds.append({"query": item, "hits": len(chunks or []), "fresh": fresh})
    context = (
        "\n\n".join(f"[{index + 1}] {item.get('content', '')}" for index, item in enumerate(sources))
        or "（未检索到资料）"
    )
    answer = await _ask(
        mc,
        spec,
        system,
        f"问题：{query}\n\n检索资料：\n{context}\n\n请基于资料作答；资料不足时明确说明，并标注引用编号。",
    )
    return {"answer": answer.strip(), "steps": rounds, "sources": sources[:20]}


MODES: dict[str, Any] = {
    "react": run_react,
    "plan_execute": run_plan_execute,
    "reflection": run_reflection,
    "supervisor": run_supervisor,
    "pipeline": run_pipeline,
    "agent_as_tool": run_agent_as_tool,
    "deep_search": run_deep_search,
}


async def run_spec(
    spec: AgentSpec, mc: ModeContext, variables: dict[str, Any], query: str, system: str
) -> dict[str, Any]:
    """按 spec.mode 分发；超过递归深度时退化为一次直接回答，避免自递归。"""
    if mc.depth >= MAX_DEPTH:
        return {"answer": (await _ask(mc, spec, system, query)).strip(), "steps": []}
    handler = MODES.get(spec.mode) or MODES["react"]
    return await handler(spec, replace(mc, depth=mc.depth + 1), variables, query, system)
