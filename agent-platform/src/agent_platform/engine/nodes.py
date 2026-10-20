"""核心节点执行逻辑。"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx
from langgraph.types import interrupt

from agent_platform.engine.code_sandbox import run_code
from agent_platform.engine.context import EngineContext
from agent_platform.engine.expr import evaluate, render
from agent_platform.engine.state import GraphState
from agent_platform.graph.schema import (
    AgentConfig,
    AggregateConfig,
    AnswerConfig,
    ApprovalConfig,
    ClassifierClass,
    ConditionConfig,
    EndConfig,
    ExtractorParameter,
    HttpRequestConfig,
    KnowledgeConfig,
    ListOperatorConfig,
    LLMConfig,
    NodeDef,
    ParameterExtractorConfig,
    QuestionClassifierConfig,
    TemplateTransformConfig,
    ToolConfig,
    VariableAssignerConfig,
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


def _as_text(value: Any) -> str:
    """把上下文变量（可能是 chunk 列表）摊平成可拼进提示词的文本。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("content") or item.get("text") or json.dumps(item, ensure_ascii=False)))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    if isinstance(value, dict):
        return str(value.get("content") or value.get("text") or json.dumps(value, ensure_ascii=False))
    return str(value)


async def run_llm(node: NodeDef, state: GraphState, ctx: EngineContext) -> GraphState:
    config: LLMConfig = node.typed_config()
    variables = _variables(state)
    user_prompt = render(config.user_prompt, variables)
    if config.context:
        context_text = _as_text(evaluate(config.context, variables))
        if context_text:
            user_prompt = f"{user_prompt}\n\n参考上下文：\n{context_text}"
    answer = await ctx.llm(
        provider=config.provider,
        system_prompt=render(config.system_prompt, variables),
        user_prompt=user_prompt,
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


async def run_http_request(node: NodeDef, state: GraphState, ctx: EngineContext) -> GraphState:
    """HTTP 请求：url/headers/params/body 走模板渲染，输出 {body, status_code, headers}。"""
    config: HttpRequestConfig = node.typed_config()
    variables = _variables(state)
    url = render(config.url, variables).strip()
    if not url:
        raise ValueError("HTTP 请求节点缺少 url")
    headers = {key: render(value, variables) for key, value in config.headers.items()}
    params = {key: render(value, variables) for key, value in config.params.items()}
    kwargs: dict[str, Any] = {"headers": headers, "params": params}
    if config.body_type == "json":
        text = render(config.body, variables).strip()
        if text:
            try:
                parsed_body = json.loads(text)
            except ValueError:
                parsed_body = text
            if isinstance(parsed_body, (dict, list)):
                kwargs["json"] = parsed_body
            else:
                kwargs["content"] = str(parsed_body)
    elif config.body_type == "text":
        text = render(config.body, variables)
        if text:
            kwargs["content"] = text
    async with httpx.AsyncClient(timeout=config.timeout) as client:
        response = await client.request(config.method, url, **kwargs)
    try:
        body: Any = response.json()
    except ValueError:
        body = response.text
    result = {"body": body, "status_code": response.status_code, "headers": dict(response.headers)}
    return _store(state, variables, node.id, config.output_var, result)


def _match_classifier_class(raw: str, classes: list[ClassifierClass]) -> ClassifierClass:
    """把模型输出归一化到类别：先精确（id/name），再包含，最后兜底第一个。"""
    text = (raw or "").strip().strip("\"'").strip()
    lowered = text.lower()
    for item in classes:
        if lowered in (item.id.lower(), item.name.lower()):
            return item
    for item in classes:
        if item.id.lower() in lowered or item.name.lower() in lowered:
            return item
    return classes[0]


async def run_question_classifier(node: NodeDef, state: GraphState, ctx: EngineContext) -> GraphState:
    """问题分类器：LLM 判定类别，类别 id 写入 state['route'] 驱动分支。"""
    config: QuestionClassifierConfig = node.typed_config()
    variables = _variables(state)
    if not config.classes:
        raise ValueError("问题分类器未定义类别")
    options = "\n".join(f"- {item.id}: {item.name}" for item in config.classes)
    system_prompt = (
        "你是问题分类器。请判断用户问题属于下列哪一个类别，只输出类别 id，不要输出任何其它内容。\n"
        f"类别：\n{options}"
    )
    if config.instruction:
        system_prompt = f"{system_prompt}\n\n补充指令：{render(config.instruction, variables)}"
    raw = await ctx.llm(
        provider=config.provider,
        system_prompt=system_prompt,
        user_prompt=render(config.query, variables),
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )
    chosen = _match_classifier_class(raw, config.classes)
    variables[config.output_var] = chosen.id
    variables[node.id] = chosen.id
    return {**state, "variables": variables, "route": chosen.id}


def run_variable_assigner(node: NodeDef, state: GraphState, ctx: EngineContext) -> GraphState:
    """变量赋值：逐个 item 求值后写入同名变量。"""
    config: VariableAssignerConfig = node.typed_config()
    variables = _variables(state)
    assigned = {item.name: evaluate(item.expression, variables) for item in config.items if item.name}
    variables.update(assigned)
    variables[node.id] = assigned
    return {**state, "variables": variables}


def _list_sort_key(value: Any) -> tuple[int, float, str]:
    if isinstance(value, bool):
        return (1, 0.0, str(value))
    if isinstance(value, (int, float)):
        return (0, float(value), "")
    return (1, 0.0, str(value))


def run_list_operator(node: NodeDef, state: GraphState, ctx: EngineContext) -> GraphState:
    """数组操作：取首/尾/下标/截取/筛选/排序/长度。"""
    config: ListOperatorConfig = node.typed_config()
    variables = _variables(state)
    source = evaluate(config.variable, variables) if config.variable else None
    items = list(source) if isinstance(source, (list, tuple)) else ([] if source is None else [source])
    operation = config.operation
    if operation == "first":
        result: Any = items[0] if items else None
    elif operation == "last":
        result = items[-1] if items else None
    elif operation == "at":
        result = items[config.index] if 0 <= config.index < len(items) else None
    elif operation == "limit":
        result = items[: max(config.count, 0)]
    elif operation == "size":
        result = len(items)
    elif operation == "filter":
        expression = config.expression or "true"
        result = [item for item in items if evaluate(expression, {**variables, "item": item})]
    elif operation == "sort":
        expression = config.expression or "item"
        result = sorted(
            items,
            key=lambda item: _list_sort_key(evaluate(expression, {**variables, "item": item})),
            reverse=config.desc,
        )
    else:
        result = items
    return _store(state, variables, node.id, config.output_var, result)


async def run_agent_node(node: NodeDef, state: GraphState, ctx: EngineContext) -> GraphState:
    """智能体节点：按 8 种工作模式执行。"""
    config: AgentConfig = node.typed_config()
    variables = _variables(state)
    result = await ctx.agents(config, variables, ctx, ctx.tenant_code)
    variables[config.output_var] = result.get("answer", "")
    variables[node.id] = result
    next_state: GraphState = {**state, "variables": variables}
    if result.get("route"):
        next_state["route"] = str(result["route"])
    return next_state


def run_approval(node: NodeDef, state: GraphState, ctx: EngineContext) -> GraphState:
    """人工审批：HITL 开启时中断等待 resume；关闭时按默认动作自动通过。"""
    config: ApprovalConfig = node.typed_config()
    variables = _variables(state)
    if getattr(ctx, "hitl_enabled", False):
        payload = evaluate(config.payload, variables) if config.payload else {}
        decision = interrupt(
            {
                "node": node.id,
                "title": node.title,
                "question": config.question,
                "options": list(config.options),
                "payload": payload,
            }
        )
    else:
        decision = {"action": config.default_action}
    if not isinstance(decision, dict):
        decision = {"action": config.default_action}
    variables[node.id] = decision
    variables[config.output_var] = decision
    next_state: GraphState = {**state, "variables": variables}
    if decision.get("action"):
        next_state["route"] = str(decision["action"])
    return next_state


async def run_subgraph_node(node: NodeDef, state: GraphState, ctx: EngineContext) -> GraphState:
    """单点运行子图节点（编辑器「运行此节点」）；候选多选时使用第一个。"""
    from agent_platform.engine.builder import build_graph
    from agent_platform.graph.schema import SubgraphRef

    if not getattr(ctx, "subgraph_enabled", False):
        raise ValueError("子图功能未启用（AP_SUBGRAPH_ENABLED=false）")
    config = node.typed_config()
    refs = list(config.candidates or [])
    if not refs and (config.app_uuid or config.template_key):
        refs = [SubgraphRef(app_uuid=config.app_uuid, template_key=config.template_key, version=config.version)]
    if not refs:
        raise ValueError(f"子图节点 {node.id} 未配置引用")
    resolver = getattr(ctx, "resolve_subgraph", None)
    if resolver is None:
        raise ValueError("子图解析器未配置")
    child_def = resolver(refs[0], ctx.tenant_code)
    if child_def is None:
        raise ValueError(f"子图不存在或不可见：{refs[0].app_uuid or refs[0].template_key}")
    child = build_graph(child_def, ctx, None)
    result = await child.ainvoke({"inputs": dict(state.get("variables") or {})})
    variables = _variables(state)
    variables[config.output_var] = result.get("answer", "")
    variables[node.id] = result
    return {
        **state,
        "variables": variables,
        "answer": result.get("answer", state.get("answer", "")),
    }


def run_end(node: NodeDef, state: GraphState, ctx: EngineContext) -> GraphState:
    config: EndConfig = node.typed_config()
    if config.outputs and not state.get("answer"):
        variables = _variables(state)
        answer = "\n".join(str(evaluate(expr, variables)) for expr in config.outputs.values())
        return {**state, "answer": answer}
    return state
