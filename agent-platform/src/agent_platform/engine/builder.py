"""由 GraphDef 构建 LangGraph 可执行图。"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.graph import END, START, StateGraph

from agent_platform.engine import nodes
from agent_platform.engine.context import EngineContext
from agent_platform.engine.state import GraphState
from agent_platform.graph.schema import GraphDef, NodeDef, NodeType

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


def build_graph(graph_def: GraphDef, ctx: EngineContext, checkpointer: Any = None):
    sg: StateGraph = StateGraph(GraphState)

    for node in graph_def.nodes:
        sg.add_node(node.id, _node_fn(node, ctx))

    start = graph_def.start_node()
    if start is not None:
        sg.add_edge(START, start.id)

    for node in graph_def.nodes:
        if node.type == NodeType.CONDITION:
            route_fn, path_map = _condition_paths(graph_def, node)
            sg.add_conditional_edges(node.id, route_fn, path_map)
        elif node.type == NodeType.QUESTION_CLASSIFIER:
            route_fn, path_map = _classifier_paths(graph_def, node)
            sg.add_conditional_edges(node.id, route_fn, path_map)
        elif node.type == NodeType.AGENT and any(edge.source_handle for edge in graph_def.outgoing(node.id)):
            # supervisor 模式的 agent 通过带句柄的出边做动态路由（句柄 = 成员 agent code）
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

    return sg.compile(checkpointer=checkpointer)
