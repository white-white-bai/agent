"""核心节点执行逻辑。"""
from __future__ import annotations

from typing import Any

from agent_platform.engine.code_sandbox import run_code
from agent_platform.engine.context import EngineContext
from agent_platform.engine.expr import evaluate, render
from agent_platform.engine.state import GraphState
from agent_platform.graph.schema import (
    AggregateConfig,
    AnswerConfig,
    ConditionConfig,
    EndConfig,
    KnowledgeConfig,
    LLMConfig,
    NodeDef,
    ToolConfig,
)


def _variables(state: GraphState) -> dict[str, Any]:
    return dict(state.get("variables", {}))


def _store(state: GraphState, variables: dict[str, Any], node_id: str, name: str, value: Any) -> GraphState:
    variables[name] = value
    variables[node_id] = value
    return {**state, "variables": variables}


def run_start(node: NodeDef, state: GraphState, ctx: EngineContext) -> GraphState:
    graph_inputs = state.get("inputs", {})
    variables = _variables(state)
    variables.update(graph_inputs)
    return {**state, "variables": variables, "query": str(graph_inputs.get("query", ""))}


async def run_llm(node: NodeDef, state: GraphState, ctx: EngineContext) -> GraphState:
    config: LLMConfig = node.typed_config()
    variables = _variables(state)
    answer = await ctx.llm(
        provider=config.provider,
        model=config.model,
        system_prompt=render(config.system_prompt, variables),
        user_prompt=render(config.user_prompt, variables),
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )
    return _store(state, variables, node.id, config.output_var, answer)


async def run_knowledge(node: NodeDef, state: GraphState, ctx: EngineContext) -> GraphState:
    config: KnowledgeConfig = node.typed_config()
    variables = _variables(state)
    chunks = await ctx.retriever(config, render(config.query, variables))
    return _store(state, variables, node.id, config.output_var, chunks)


def run_condition(node: NodeDef, state: GraphState, ctx: EngineContext) -> GraphState:
    config: ConditionConfig = node.typed_config()
    variables = _variables(state)
    route = config.fallback_id
    for branch in config.branches:
        if evaluate(branch.expression, variables):
            route = branch.id
            break
    return {**state, "route": route}


def run_code_node(node: NodeDef, state: GraphState, ctx: EngineContext) -> GraphState:
    config = node.typed_config()
    variables = _variables(state)
    outputs = (ctx.code_runner or run_code)(config, variables)
    variables.update(outputs)
    variables[node.id] = outputs
    return {**state, "variables": variables}


async def run_tool(node: NodeDef, state: GraphState, ctx: EngineContext) -> GraphState:
    config: ToolConfig = node.typed_config()
    variables = _variables(state)
    result = await ctx.tools(config, variables)
    return _store(state, variables, node.id, config.output_var, result)


def run_aggregate(node: NodeDef, state: GraphState, ctx: EngineContext) -> GraphState:
    config: AggregateConfig = node.typed_config()
    variables = _variables(state)
    aggregated = {expr: evaluate(expr, variables) for expr in config.variables}
    return _store(state, variables, node.id, config.output_var, aggregated)


def run_answer(node: NodeDef, state: GraphState, ctx: EngineContext) -> GraphState:
    config: AnswerConfig = node.typed_config()
    variables = _variables(state)
    answer = render(config.template, variables)
    variables[config.output_var] = answer
    return {**state, "variables": variables, "answer": answer}


def run_end(node: NodeDef, state: GraphState, ctx: EngineContext) -> GraphState:
    config: EndConfig = node.typed_config()
    if config.outputs and not state.get("answer"):
        variables = _variables(state)
        answer = "\n".join(str(evaluate(expr, variables)) for expr in config.outputs.values())
        return {**state, "answer": answer}
    return state
