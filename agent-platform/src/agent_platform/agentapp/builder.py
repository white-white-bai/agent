"""自主 agent 的 LangGraph 状态图：规划 → 原生 function-calling 循环 → 反思 → 收尾。

与工作流图（`engine/builder.py`）不同：这里节点由 agent 自己驱动，工具由 LLM 原生 tool_calls 触发。
"""
from __future__ import annotations

import json
from typing import Annotated, Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt

from agent_platform.agentapp.schema import AgentAppDef
from agent_platform.engine.agents.modes import CRITIQUE_PROMPT, REVISE_PROMPT
from agent_platform.engine.context import EngineContext

AGENT_NODE = "agent"
PLAN_NODE = "plan"
TOOLS_NODE = "tools"
REFLECT_NODE = "reflect"
FINALIZE_NODE = "finalize"
APPROVAL_NODE = "approval"

PLANNER_SYSTEM = "你是任务规划器。请针对用户问题给出简要的可执行计划（不超过 5 步），直接输出计划正文。"


class AgentState(MessagesState):
    messages: Annotated[list[AnyMessage], add_messages]
    plan: str
    reflections: list[dict]
    iterations: int
    summary: str
    query: str
    answer: str
    hitl_rejected: bool


def _content_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [item.get("text", "") if isinstance(item, dict) else str(item) for item in content]
        return "".join(parts)
    try:
        return json.dumps(content, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(content)


def _last_answer_text(state: dict[str, Any]) -> str:
    for message in reversed(state.get("messages", [])):
        if isinstance(message, AIMessage):
            text = _content_text(message).strip()
            if text:
                return text
    return ""


def _trim(messages: list[AnyMessage], window: int, max_chars: int = 0) -> list[AnyMessage]:
    """按窗口裁剪，且不以孤立 ToolMessage 开头（保持 tool_call 配对）。"""
    if window <= 0 or len(messages) <= window:
        result = messages
    else:
        index = len(messages) - window
        while index > 0 and isinstance(messages[index], ToolMessage):
            index -= 1
        result = messages[index:]
    if max_chars <= 0:
        return result
    trimmed = list(result)
    total = sum(len(_content_text(message)) for message in trimmed)
    while len(trimmed) > 1 and total > max_chars:
        removed = trimmed.pop(0)
        total -= len(_content_text(removed))
        while trimmed and isinstance(trimmed[0], ToolMessage):
            removed = trimmed.pop(0)
            total -= len(_content_text(removed))
    return trimmed


def _model_input(state: dict[str, Any], agent_def: AgentAppDef) -> list[AnyMessage]:
    prefix: list[AnyMessage] = []
    if agent_def.instructions:
        prefix.append(SystemMessage(agent_def.instructions))
    if state.get("summary"):
        prefix.append(SystemMessage(f"历史对话摘要：\n{state['summary']}"))
    if state.get("plan"):
        prefix.append(SystemMessage(f"执行计划：\n{state['plan']}"))
    return prefix + _trim(
        list(state.get("messages", [])),
        agent_def.memory.window,
        agent_def.memory.max_chars,
    )


def _hitl_covers(agent_def: AgentAppDef, name: str) -> bool:
    policy = agent_def.hitl.policy
    if policy == "before_all_tools":
        return True
    if policy == "before_listed":
        listed = {str(item) for item in agent_def.hitl.tools}
        ref_hitl = {ref.name for ref in agent_def.tools if ref.hitl}
        return name in listed or name in ref_hitl
    return False


def _approved(decision: Any) -> bool:
    if isinstance(decision, bool):
        return decision
    if isinstance(decision, str):
        return decision.strip().lower() in ("approve", "approved", "yes", "true", "1")
    if isinstance(decision, dict):
        return str(decision.get("decision") or "").strip().lower() in ("approve", "approved", "yes")
    return False


def build_agent_graph(
    agent_def: AgentAppDef,
    ctx: EngineContext,
    tools: list[Any],
    *,
    checkpointer: Any = None,
    max_steps: int | None = None,
):
    limit = max(int(max_steps or agent_def.max_steps or 1), 1)
    reflect_rounds = max(int(agent_def.reflection_rounds or 0), 0)
    hitl_active = bool(agent_def.hitl.enabled) and checkpointer is not None

    async def plan_node(state: AgentState) -> dict[str, Any]:
        model = ctx.chat_model(provider=agent_def.provider, temperature=0.0, max_tokens=agent_def.max_tokens)
        response = await model.ainvoke(
            [SystemMessage(PLANNER_SYSTEM), HumanMessage(str(state.get("query") or ""))]
        )
        return {"plan": _content_text(response).strip()}

    async def agent_node(state: AgentState) -> dict[str, Any]:
        model = ctx.chat_model(
            provider=agent_def.provider, temperature=agent_def.temperature, max_tokens=agent_def.max_tokens
        )
        bound = model.bind_tools(tools) if tools else model
        response = await bound.ainvoke(_model_input(state, agent_def))
        return {"messages": [response], "iterations": int(state.get("iterations", 0)) + 1}

    async def reflect_node(state: AgentState) -> dict[str, Any]:
        draft = _last_answer_text(state)
        model = ctx.chat_model(
            provider=agent_def.provider, temperature=agent_def.temperature, max_tokens=agent_def.max_tokens
        )
        critic_system = "\n\n".join(part for part in ("你是严格的审查者。", agent_def.instructions) if part)
        critique = await model.ainvoke(
            [
                SystemMessage(critic_system),
                HumanMessage(f"原始任务：{state.get('query', '')}\n\n待审查回答：\n{draft}\n\n{CRITIQUE_PROMPT}"),
            ]
        )
        critique_text = _content_text(critique).strip()
        rounds = list(state.get("reflections", []))
        rounds.append({"draft": draft, "critique": critique_text})
        if "无需修改" in critique_text:
            return {"reflections": rounds}
        revision = await model.ainvoke(
            [
                SystemMessage(agent_def.instructions or "你是助手。"),
                HumanMessage(f"原始任务：{state.get('query', '')}\n\n当前回答：\n{draft}\n\n审查意见：\n{critique_text}\n\n{REVISE_PROMPT}"),
            ]
        )
        return {"reflections": rounds, "messages": [AIMessage(_content_text(revision).strip())]}

    def finalize_node(state: AgentState) -> dict[str, Any]:
        return {"answer": _last_answer_text(state)}

    def approval_node(state: AgentState) -> dict[str, Any]:
        last = state["messages"][-1] if state.get("messages") else None
        calls = list(getattr(last, "tool_calls", []) or [])
        pending = [call for call in calls if _hitl_covers(agent_def, str(call.get("name") or ""))]
        if not pending:
            return {"hitl_rejected": False}
        names = "、".join(str(call.get("name")) for call in pending)
        try:
            prompt = agent_def.hitl.prompt.format(tool=names, args=[call.get("args") for call in pending])
        except (KeyError, IndexError, ValueError):
            prompt = f"即将执行工具 {names}，是否批准？"
        decision = interrupt({"tool": names, "tools": [str(call.get("name")) for call in pending], "prompt": prompt})
        if _approved(decision):
            return {"hitl_rejected": False}
        return {
            "hitl_rejected": True,
            "messages": [
                ToolMessage(content=f"用户拒绝执行工具：{names}", tool_call_id=call["id"], status="error")
                for call in calls
            ],
        }

    def route_after_approval(state: AgentState) -> str:
        return AGENT_NODE if state.get("hitl_rejected") else TOOLS_NODE

    def route_after_agent(state: AgentState) -> str:
        last = state["messages"][-1] if state.get("messages") else None
        has_tools = isinstance(last, AIMessage) and bool(getattr(last, "tool_calls", None))
        if has_tools and tools:
            if int(state.get("iterations", 0)) >= limit:
                return FINALIZE_NODE
            return APPROVAL_NODE if hitl_active else TOOLS_NODE
        return REFLECT_NODE if reflect_rounds > 0 else FINALIZE_NODE

    def route_after_reflect(state: AgentState) -> str:
        rounds = state.get("reflections", [])
        if len(rounds) >= reflect_rounds:
            return FINALIZE_NODE
        if rounds and "无需修改" in str(rounds[-1].get("critique", "")):
            return FINALIZE_NODE
        return REFLECT_NODE

    graph: StateGraph = StateGraph(AgentState)
    graph.add_node(AGENT_NODE, agent_node)
    graph.add_node(FINALIZE_NODE, finalize_node)
    graph.add_node(REFLECT_NODE, reflect_node)
    if tools:
        graph.add_node(TOOLS_NODE, ToolNode(tools))
    if hitl_active:
        graph.add_node(APPROVAL_NODE, approval_node)
    if agent_def.planning:
        graph.add_node(PLAN_NODE, plan_node)
        graph.add_edge(START, PLAN_NODE)
        graph.add_edge(PLAN_NODE, AGENT_NODE)
    else:
        graph.add_edge(START, AGENT_NODE)

    route_map = {FINALIZE_NODE: FINALIZE_NODE, REFLECT_NODE: REFLECT_NODE}
    if tools:
        route_map[TOOLS_NODE] = TOOLS_NODE
    if hitl_active:
        route_map[APPROVAL_NODE] = APPROVAL_NODE
    graph.add_conditional_edges(AGENT_NODE, route_after_agent, route_map)
    graph.add_conditional_edges(
        REFLECT_NODE, route_after_reflect, {FINALIZE_NODE: FINALIZE_NODE, REFLECT_NODE: REFLECT_NODE}
    )
    if tools:
        graph.add_edge(TOOLS_NODE, AGENT_NODE)
    if hitl_active:
        graph.add_conditional_edges(
            APPROVAL_NODE, route_after_approval, {AGENT_NODE: AGENT_NODE, TOOLS_NODE: TOOLS_NODE}
        )
    graph.add_edge(FINALIZE_NODE, END)

    return graph.compile(checkpointer=checkpointer, name="agent")
