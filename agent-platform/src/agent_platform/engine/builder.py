"""由 GraphDef 构建 LangGraph 可执行图。"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from langgraph.graph import END, START, StateGraph

from agent_platform.engine import nodes
from agent_platform.engine.context import EngineContext
from agent_platform.engine.expr import render
from agent_platform.engine.state import GraphState
from agent_platform.graph.schema import GraphDef, NodeDef, NodeType, SubgraphConfig, SubgraphRef

logger = logging.getLogger(__name__)


def _subgraph_refs(config: SubgraphConfig) -> list[SubgraphRef]:
    refs = list(config.candidates or [])
    if not refs and (config.app_uuid or config.template_key):
        refs = [SubgraphRef(app_uuid=config.app_uuid, template_key=config.template_key, version=config.version)]
    return refs


def _candidate_key(ref: SubgraphRef, index: int, used: set[str]) -> str:
    raw = ref.label or ref.app_uuid or ref.template_key or f"candidate_{index}"
    key = re.sub(r"[|:]", "_", raw).strip() or f"candidate_{index}"
    base = key
    suffix = 2
    while key in used:
        key = f"{base}_{suffix}"
        suffix += 1
    used.add(key)
    return key


async def _select_candidate(
    node: NodeDef,
    config: SubgraphConfig,
    keys: list[str],
    state: GraphState,
    ctx: EngineContext,
) -> str:
    variables = dict(state.get("variables", {}))
    if config.router:
        try:
            from agent_platform.engine.agents.registry import load_agent

            spec = load_agent(config.router, ctx.tenant_code)
            query = render(config.query, variables)
            raw = await ctx.llm(
                provider=spec.provider,
                system_prompt=spec.system_prompt or "你是任务路由器，只输出一个候选子图名。",
                user_prompt=f"可选子图：{'、'.join(keys)}\n任务：{query}\n只输出一个候选名。",
                temperature=0.0,
                max_tokens=32,
            )
            text = str(raw or "").strip().lower()
            for key in keys:
                if key.lower() in text:
                    return key
        except Exception as exc:  # noqa: BLE001 - 路由失败回退到 state.route / 第一个候选
            logger.warning("子图路由失败，回退到 state.route / 第一个候选：%s", exc)
    current = str(state.get("route") or "")
    return current if current in keys else keys[0]


RUNNERS: dict[NodeType, Callable] = {
    NodeType.START: nodes.run_start,
    NodeType.END: nodes.run_end,
    NodeType.LLM: nodes.run_llm,
    NodeType.KNOWLEDGE: nodes.run_knowledge,
    NodeType.CONDITION: nodes.run_condition,
    NodeType.CODE: nodes.run_code_node,
    NodeType.TOOL: nodes.run_tool,
    NodeType.AGGREGATE: nodes.run_aggregate,
    NodeType.ANSWER: nodes.run_answer,
    NodeType.PARAMETER_EXTRACTOR: nodes.run_parameter_extractor,
    NodeType.TEMPLATE_TRANSFORM: nodes.run_template_transform,
    NodeType.HTTP_REQUEST: nodes.run_http_request,
    NodeType.QUESTION_CLASSIFIER: nodes.run_question_classifier,
    NodeType.VARIABLE_ASSIGNER: nodes.run_variable_assigner,
    NodeType.LIST_OPERATOR: nodes.run_list_operator,
    NodeType.AGENT: nodes.run_agent_node,
    NodeType.APPROVAL: nodes.run_approval,
    NodeType.SUBGRAPH: nodes.run_subgraph_node,
}

_ASYNC_TYPES = (
    NodeType.LLM,
    NodeType.KNOWLEDGE,
    NodeType.TOOL,
    NodeType.PARAMETER_EXTRACTOR,
    NodeType.HTTP_REQUEST,
    NodeType.QUESTION_CLASSIFIER,
    NodeType.AGENT,
)


def _tracer(ctx: EngineContext) -> Any:
    tracer = getattr(ctx, "tracer", None)
    return tracer if tracer is not None and getattr(tracer, "enabled", False) else None


def _node_fn(node: NodeDef, ctx: EngineContext) -> Callable[[GraphState], Any]:
    runner = RUNNERS[node.type]
    tracer = _tracer(ctx)

    if node.type in _ASYNC_TYPES:

        async def afn(state: GraphState) -> GraphState:
            if tracer is None:
                return await runner(node, state, ctx)
            with tracer.node_span(node.id, node.type.value, payload=state.get("variables")) as span:
                result = await runner(node, state, ctx)
                span.end(output=result.get("variables"))
                return result

        return afn

    def sfn(state: GraphState) -> GraphState:
        if tracer is None:
            return runner(node, state, ctx)
        with tracer.node_span(node.id, node.type.value, payload=state.get("variables")) as span:
            result = runner(node, state, ctx)
            span.end(output=result.get("variables"))
            return result

    return sfn


def _route_paths(graph_def: GraphDef, node: NodeDef, fallback_id: str) -> tuple[Callable, dict[str, str]]:
    route_map: dict[str, str] = {}
    for edge in graph_def.outgoing(node.id):
        key = edge.source_handle or fallback_id
        route_map[key] = edge.target
    route_map.setdefault(fallback_id, route_map.get(fallback_id, END))

    def route_fn(state: GraphState) -> str:
        route = state.get("route") or fallback_id
        return route if route in route_map else fallback_id

    return route_fn, route_map


def _condition_paths(graph_def: GraphDef, node: NodeDef) -> tuple[Callable, dict[str, str]]:
    return _route_paths(graph_def, node, node.typed_config().fallback_id)


def _classifier_paths(graph_def: GraphDef, node: NodeDef) -> tuple[Callable, dict[str, str]]:
    classes = node.typed_config().classes
    return _route_paths(graph_def, node, classes[0].id if classes else "")


def build_graph(
    graph_def: GraphDef,
    ctx: EngineContext,
    checkpointer: Any = None,
    *,
    interrupt_before: list[str] | None = None,
    interrupt_after: list[str] | None = None,
    depth: int = 0,
    visited: set[tuple[str, int | None, str]] | None = None,
):
    sg: StateGraph = StateGraph(GraphState)

    for node in graph_def.nodes:
        if node.type == NodeType.SUBGRAPH:
            continue
        sg.add_node(node.id, _node_fn(node, ctx))

    start = graph_def.start_node()
    if start is not None:
        sg.add_edge(START, start.id)

    for node in graph_def.nodes:
        if node.type == NodeType.SUBGRAPH:
            if not getattr(ctx, "subgraph_enabled", False):
                raise ValueError("子图功能未启用（AP_SUBGRAPH_ENABLED=false）")
            config: SubgraphConfig = node.typed_config()
            refs = _subgraph_refs(config)
            if not refs:
                raise ValueError(f"子图节点 {node.id} 未配置引用")
            limit = int(config.max_depth or 2)
            if depth >= limit:
                raise ValueError(f"子图嵌套超过上限 {limit}")
            resolver = getattr(ctx, "resolve_subgraph", None)
            if resolver is None:
                raise ValueError("子图解析器未配置")
            visited_set = set(visited or set())
            used: set[str] = set()
            keys: list[str] = []
            for index, ref in enumerate(refs):
                key = _candidate_key(ref, index, used)
                ref_key = (ref.app_uuid, ref.version, ref.template_key)
                if ref_key in visited_set:
                    raise ValueError(f"子图引用成环：{ref.app_uuid or ref.template_key}")
                child_def = resolver(ref, ctx.tenant_code)
                if child_def is None:
                    raise ValueError(f"子图不存在或不可见：{ref.app_uuid or ref.template_key}")
                child = build_graph(
                    child_def,
                    ctx,
                    None,
                    depth=depth + 1,
                    visited=visited_set | {ref_key},
                )
                sg.add_node(f"{node.id}__{index}", child)
                keys.append(key)

            async def router_fn(
                state: GraphState,
                _node: NodeDef = node,
                _config: SubgraphConfig = config,
                _keys: list[str] = keys,
            ) -> GraphState:
                selected = await _select_candidate(_node, _config, _keys, state, ctx)
                variables = dict(state.get("variables", {}))
                variables[_node.id] = {"candidate": selected}
                return {**state, "variables": variables, "route": selected}

            def route_fn(state: GraphState, _keys: list[str] = keys) -> str:
                route = str(state.get("route") or _keys[0])
                return route if route in _keys else _keys[0]

            sg.add_node(node.id, router_fn)
            sg.add_conditional_edges(
                node.id,
                route_fn,
                {key: f"{node.id}__{index}" for index, key in enumerate(keys)},
            )
            outgoing = graph_def.outgoing(node.id)
            for index in range(len(refs)):
                child_id = f"{node.id}__{index}"
                if not outgoing:
                    sg.add_edge(child_id, END)
                for edge in outgoing:
                    sg.add_edge(child_id, edge.target)
            continue
        if node.type == NodeType.CONDITION:
            route_fn, path_map = _condition_paths(graph_def, node)
            sg.add_conditional_edges(node.id, route_fn, path_map)
        elif node.type == NodeType.QUESTION_CLASSIFIER:
            route_fn, path_map = _classifier_paths(graph_def, node)
            sg.add_conditional_edges(node.id, route_fn, path_map)
        elif node.type in (NodeType.AGENT, NodeType.APPROVAL) and any(
            edge.source_handle for edge in graph_def.outgoing(node.id)
        ):
            # supervisor / 审批节点通过带句柄的出边做动态路由（句柄 = 成员 code / 审批动作）
            handles = [edge.source_handle for edge in graph_def.outgoing(node.id) if edge.source_handle]
            route_fn, path_map = _route_paths(graph_def, node, handles[0])
            sg.add_conditional_edges(node.id, route_fn, path_map)
        elif node.type == NodeType.END:
            sg.add_edge(node.id, END)
        else:
            outgoing = graph_def.outgoing(node.id)
            if not outgoing:
                sg.add_edge(node.id, END)
            for edge in outgoing:
                sg.add_edge(node.id, edge.target)

    return sg.compile(
        checkpointer=checkpointer,
        interrupt_before=interrupt_before,
        interrupt_after=interrupt_after,
    )
