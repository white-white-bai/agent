"""核心节点执行逻辑。"""
from __future__ import annotations

import json
import re
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
    ExtractorParameter,
    KnowledgeConfig,
    LLMConfig,
    NodeDef,
    ParameterExtractorConfig,
    TemplateTransformConfig,
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
        system_prompt=render(config.system_prompt, variables),
        user_prompt=render(config.user_prompt, variables),
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )
    return _store(state, variables, node.id, config.output_var, answer)


async def run_knowledge(node: NodeDef, state: GraphState, ctx: EngineContext) -> GraphState:
    config: KnowledgeConfig = node.typed_config()
    variables = _variables(state)
    chunks = await ctx.retriever(config, render(config.query, variables), ctx.tenant_code)
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
    result = await ctx.tools(config, variables, ctx.tenant_code)
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


_CODE_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _extract_json_object(text: str) -> dict[str, Any]:
    """从模型回复中容错提取 JSON 对象：剥 code fence、截取首个 {...} 后解析。"""
    fenced = _CODE_FENCE_PATTERN.search(text)
    if fenced:
        text = fenced.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("回复中未找到 JSON 对象")
    return json.loads(text[start : end + 1])


def _coerce_param_value(value: Any, param: ExtractorParameter) -> Any:
    """按参数定义做宽松类型收敛，失败时保留原值不抛异常。"""
    kind = (param.type or "string").lower()
    try:
        if kind.startswith("array"):
            return list(value) if isinstance(value, (list, tuple)) else ([] if value is None else [value])
        if kind == "number":
            return float(value) if not isinstance(value, (int, float)) else value
        if kind == "bool":
            return value if isinstance(value, bool) else str(value).strip().lower() in ("true", "1", "yes", "on")
        return value if isinstance(value, str) else ("" if value is None else str(value))
    except (TypeError, ValueError):
        return value


def _fill_extractor_defaults(data: dict[str, Any], parameters: list[ExtractorParameter]) -> dict[str, Any]:
    """补齐缺失参数（array 类型填空列表、其余填 None）并写入 __is_success / __reason 内置字段。"""
    for param in parameters:
        if param.name not in data:
            data[param.name] = [] if (param.type or "").lower().startswith("array") else None
    data.setdefault("__is_success", 1)
    data.setdefault("__reason", "")
    return data


async def run_parameter_extractor(node: NodeDef, state: GraphState, ctx: EngineContext) -> GraphState:
    """参数提取器：LLM 结构化提取，输出按参数名平铺并带 __is_success / __reason。"""
    config: ParameterExtractorConfig = node.typed_config()
    variables = _variables(state)
    query = render(config.query, variables)
    lines = [f"- {p.name}（{p.type}{'，必填' if p.required else ''}{'，可选值：' + '/'.join(p.options) if p.options else ''}）"
             + (f"：{p.description}" if p.description else "")
             for p in config.parameters]
    system_prompt = (
        "你是参数提取器。请从用户内容中提取下列参数，并且只输出一个 JSON 对象，不要输出任何解释文字。\n"
        + "\n".join(lines)
    )
    user_prompt = render(config.instruction, variables)
    user_prompt = f"{user_prompt}\n\n{query}" if user_prompt else query
    try:
        answer = await ctx.llm(
            provider=config.provider,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )
    except Exception as exc:  # noqa: BLE001 - 提取失败不阻断整条链路
        data = _fill_extractor_defaults({}, config.parameters)
        data["__is_success"] = 0
        data["__reason"] = f"模型调用失败: {exc}"
        variables[node.id] = data
        variables[config.output_var] = data
        return {**state, "variables": variables}
    try:
        parsed = _extract_json_object(answer)
        if not isinstance(parsed, dict):
            raise TypeError("JSON 不是对象")
    except (ValueError, TypeError) as exc:
        data = _fill_extractor_defaults({}, config.parameters)
        data["__is_success"] = 0
        data["__reason"] = f"JSON 解析失败: {exc}"
        variables[node.id] = data
        variables[config.output_var] = data
        return {**state, "variables": variables}
    data = {
        param.name: _coerce_param_value(parsed.get(param.name), param)
        for param in config.parameters
        if param.name in parsed
    }
    data = _fill_extractor_defaults(data, config.parameters)
    # 只写 node_id 与 output_var 两个键，避免参数名覆盖全局同名变量
    variables[node.id] = data
    variables[config.output_var] = data
    return {**state, "variables": variables}


def run_template_transform(node: NodeDef, state: GraphState, ctx: EngineContext) -> GraphState:
    """模板转换：把入参表达式绑定到本地变量名后渲染 Jinja2 模板，输出固定为字符串。"""
    config: TemplateTransformConfig = node.typed_config()
    variables = _variables(state)
    local_vars = {item.name: evaluate(item.expression, variables) for item in config.variables}
    output = render(config.template, local_vars)
    return _store(state, variables, node.id, config.output_var, output)


def run_end(node: NodeDef, state: GraphState, ctx: EngineContext) -> GraphState:
    config: EndConfig = node.typed_config()
    if config.outputs and not state.get("answer"):
        variables = _variables(state)
        answer = "\n".join(str(evaluate(expr, variables)) for expr in config.outputs.values())
        return {**state, "answer": answer}
    return state
