"""Dify DSL → 中台图 schema 导入器。

可映射节点：start / end / llm / knowledge-retrieval / if-else / code / tool / variable-aggregator / answer；
其余节点（http-request、template-transform、iteration、question-classifier 等）旁路并给出提示。
引用 `{{#node.var#}}` 按节点输出重写为中台变量名；条件分支以 Dify 边的 sourceHandle 作为分支 id
（与 `engine.builder._condition_paths` 的 route_map 键一致）。
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from agent_platform.graph.schema import GraphDef, NodeType, VariableDef, VarType

REF_PATTERN = re.compile(r"\{\{#\s*([^#{}]+?)\s*#\}\}")

_DIFY_TO_MIDDLE: dict[str, NodeType] = {
    "start": NodeType.START,
    "end": NodeType.END,
    "llm": NodeType.LLM,
    "knowledge-retrieval": NodeType.KNOWLEDGE,
    "if-else": NodeType.CONDITION,
    "code": NodeType.CODE,
    "tool": NodeType.TOOL,
    "variable-aggregator": NodeType.AGGREGATE,
    "answer": NodeType.ANSWER,
}

_ID_PREFIX: dict[NodeType, str] = {
    NodeType.START: "start",
    NodeType.END: "end",
    NodeType.LLM: "llm",
    NodeType.KNOWLEDGE: "knowledge",
    NodeType.CONDITION: "ifelse",
    NodeType.CODE: "code",
    NodeType.TOOL: "tool",
    NodeType.AGGREGATE: "aggregate",
    NodeType.ANSWER: "answer",
}

_INPUT_TYPES: dict[str, VarType] = {
    "text-input": VarType.STRING,
    "paragraph": VarType.STRING,
    "select": VarType.STRING,
    "number": VarType.NUMBER,
    "checkbox": VarType.BOOLEAN,
    "file": VarType.FILE,
    "file-list": VarType.FILE,
}

_SINGLE_OUTPUT: dict[NodeType, set[str]] = {
    NodeType.LLM: {"text"},
    NodeType.KNOWLEDGE: {"result"},
    NodeType.TOOL: {"text", "files", "json"},
    NodeType.ANSWER: {"answer"},
    NodeType.AGGREGATE: {"output"},
}

_OPERATORS: dict[str, str] = {
    "is": "{v} == {l}",
    "=": "{v} == {l}",
    "==": "{v} == {l}",
    "is not": "{v} != {l}",
    "≠": "{v} != {l}",
    "!=": "{v} != {l}",
    "<>": "{v} != {l}",
    ">": "{v} > {l}",
    "≥": "{v} >= {l}",
    ">=": "{v} >= {l}",
    "<": "{v} < {l}",
    "≤": "{v} <= {l}",
    "<=": "{v} <= {l}",
    "contains": "{l} in {v}",
    "not contains": "{l} not in {v}",
    "in": "{v} in {l}",
    "not in": "{v} not in {l}",
    "start with": "{v}.startswith({l})",
    "end with": "{v}.endswith({l})",
    "empty": "not {v}",
    "not empty": "{v}",
    "null": "{v} is none",
    "is null": "{v} is none",
    "exists": "{v} is none",
    "not null": "{v} is not none",
    "is not null": "{v} is not none",
    "not exists": "{v} is not none",
}


class DifyImportError(Exception):
    pass


@dataclass
class ImportResult:
    definition: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


def _literal(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False)


_NUMERIC_OPERATORS = (">", "≥", ">=", "<", "≤", "<=")


def _comparison_literal(value: Any) -> str:
    """Dify 把比较值序列化成字符串，数值比较需还原成数字，否则字符串无法与数字比较。"""
    if isinstance(value, str):
        text = value.strip()
        try:
            return json.dumps(int(text))
        except ValueError:
            try:
                return json.dumps(float(text))
            except ValueError:
                pass
    return _literal(value)


class _Converter:
    def __init__(self, *, app_id: str, name: str, llm_provider: str, retriever: str) -> None:
        self.app_id = app_id
        self.name = name
        self.llm_provider = llm_provider
        self.retriever = retriever
        self.warnings: list[str] = []
        self.inputs: list[VariableDef] = []
        self.raw_nodes: list[dict[str, Any]] = []
        self.raw_edges: list[dict[str, Any]] = []
        self.id_map: dict[str, str] = {}
        self.type_map: dict[str, NodeType] = {}
        self.data_map: dict[str, dict[str, Any]] = {}
        self._seen: set[str] = set()
        self._input_names: set[str] = set()

    # ------------------------------------------------------------------ 工具

    def warn(self, message: str) -> None:
        if message not in self._seen:
            self._seen.add(message)
            self.warnings.append(message)

    @staticmethod
    def _title(node: dict[str, Any]) -> str:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        return str(data.get("title") or data.get("type") or node.get("id") or "未命名")

    @staticmethod
    def _is_python_code(data: dict[str, Any]) -> bool:
        language = str(data.get("code_language") or "python3").strip().lower()
        return language in ("python3", "python")

    # ------------------------------------------------------------------ 引用重写

    def _selector(self, selector: Any) -> str:
        if not isinstance(selector, (list, tuple)) or len(selector) < 2:
            return ""
        head = str(selector[0])
        tail = ".".join(str(item) for item in selector[1:])
        if head == "sys" or head == "env":
            if head == "sys" and tail == "query":
                return "query"
            self.warn(f"{head}.{tail} 依赖运行时注入，导入后请确认该变量出现在图输入中")
            return tail
        our_id = self.id_map.get(head)
        if our_id is None:
            self.warn(f"变量引用 {head}.{tail} 指向已旁路或不存在的节点，已保留原名 {tail}")
            return tail
        ntype = self.type_map[head]
        if ntype is NodeType.START:
            return tail
        if ntype is NodeType.CODE:
            return f"{our_id}.{tail}"
        if ntype is NodeType.END:
            self.warn(f"end 节点 {head} 无输出变量，引用 {tail} 已保留原名")
            return tail
        expected = _SINGLE_OUTPUT.get(ntype, set())
        if expected and tail not in expected:
            self.warn(f"节点 {head} 的输出变量 {tail} 未识别，已按整节点结果 {our_id} 处理")
        return our_id

    def _template(self, text: Any, extra: dict[str, str] | None = None) -> str:
        if text is None:
            return ""
        if not isinstance(text, str):
            return json.dumps(text, ensure_ascii=False)

        def _sub(match: Any) -> str:
            ref = match.group(1).strip()
            rendered = (extra or {}).get(ref)
            if rendered is None:
                head, _, tail = ref.partition(".")
                if not tail:
                    self.warn(f"变量引用 {{{{#{ref}#}}}} 无法解析，已保留原名 {ref}")
                    rendered = ref
                else:
                    rendered = self._selector([head, tail])
            return f"{{{{ {rendered} }}}}"

        return REF_PATTERN.sub(_sub, text)

    def _expression(self, text: Any) -> str:
        """把 Dify 的取值文本转成可直接 evaluate 的表达式（纯引用保留原类型）。"""
        if not isinstance(text, str):
            return _literal(text)
        if "{{#" not in text:
            return _literal(text)
        parts: list[str] = []
        cursor = 0
        for match in REF_PATTERN.finditer(text):
            literal = text[cursor:match.start()]
            if literal:
                parts.append(json.dumps(literal, ensure_ascii=False))
            head, _, tail = match.group(1).strip().partition(".")
            parts.append(self._selector([head, tail]) if tail else _literal(match.group(1).strip()))
            cursor = match.end()
        tail_text = text[cursor:]
        if tail_text:
            parts.append(json.dumps(tail_text, ensure_ascii=False))
        if len(parts) == 1:
            return parts[0]
        return " ~ ".join(parts)

    def _param(self, value: Any) -> Any:
        if isinstance(value, dict):
            if "value" in value:
                return self._param(value["value"])
            return {key: self._param(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)) and len(value) >= 2 and all(isinstance(item, str) for item in value):
            return self._selector(list(value))
        if isinstance(value, str):
            return self._expression(value)
        return value

    # ------------------------------------------------------------------ 装配

    def _plan(self) -> list[tuple[dict[str, Any], str, str, NodeType]]:
        planned: list[tuple[dict[str, Any], str, str, NodeType]] = []
        for index, node in enumerate(self.raw_nodes):
            dify_id = str(node.get("id") or "")
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            dify_type = str(data.get("type") or node.get("type") or "")
            title = self._title(node)
            if not dify_id:
                self.warn(f"第 {index + 1} 个节点缺少 id，已旁路")
                continue
            if dify_id in self.id_map:
                self.warn(f"节点 id {dify_id} 重复，后者已旁路")
                continue
            ntype = _DIFY_TO_MIDDLE.get(dify_type)
            if ntype is None:
                self.warn(f"节点 {dify_id}({title}) 类型 {dify_type or '未知'} 不支持，已旁路")
                continue
            if ntype is NodeType.CODE and not self._is_python_code(data):
                language = data.get("code_language")
                self.warn(f"节点 {dify_id}({title}) 代码语言 {language} 不支持，已旁路")
                continue
            our_id = f"{_ID_PREFIX[ntype]}{index + 1}"
            self.id_map[dify_id] = our_id
            self.type_map[dify_id] = ntype
            self.data_map[dify_id] = data
            planned.append((node, dify_id, our_id, ntype))
        return planned

    def _config(self, our_id: str, dify_id: str, ntype: NodeType, data: dict[str, Any]) -> dict[str, Any]:
        if ntype is NodeType.START:
            return self._start_config(data)
        if ntype is NodeType.END:
            return self._end_config(data)
        if ntype is NodeType.LLM:
            return self._llm_config(our_id, dify_id, data)
        if ntype is NodeType.KNOWLEDGE:
            return self._knowledge_config(our_id, data)
        if ntype is NodeType.CONDITION:
            return self._condition_config(dify_id, data)
        if ntype is NodeType.CODE:
            return self._code_config(data)
        if ntype is NodeType.TOOL:
            return self._tool_config(our_id, dify_id, data)
        if ntype is NodeType.AGGREGATE:
            return self._aggregate_config(our_id, data)
        return self._answer_config(our_id, data)

    def _start_config(self, data: dict[str, Any]) -> dict[str, Any]:
        for item in data.get("variables") or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("variable") or "")
            if not name or name in self._input_names:
                continue
            self._input_names.add(name)
            self.inputs.append(
                VariableDef(
                    name=name,
                    type=_INPUT_TYPES.get(str(item.get("type") or ""), VarType.STRING),
                    required=bool(item.get("required")),
                    default=item.get("default"),
                    description=str(item.get("label") or ""),
                )
            )
        return {}

    def _end_config(self, data: dict[str, Any]) -> dict[str, Any]:
        outputs: dict[str, str] = {}
        for item in data.get("outputs") or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("variable") or "")
            expression = self._selector(item.get("value_selector"))
            if name and expression:
                outputs[name] = expression
            elif name:
                self.warn(f"end 输出 {name} 缺少取值表达式，已忽略")
        return {"outputs": outputs}

    def _llm_config(self, our_id: str, dify_id: str, data: dict[str, Any]) -> dict[str, Any]:
        model = data.get("model") if isinstance(data.get("model"), dict) else {}
        params = model.get("completion_params") if isinstance(model.get("completion_params"), dict) else {}
        if model.get("provider"):
            self.warn(f"Dify 模型 provider 不直接映射，LLM 节点统一使用 {self.llm_provider}（模型名沿用 model.name）")
        extra = self._context_ref(data)
        system_parts: list[str] = []
        user_parts: list[str] = []
        for item in data.get("prompt_template") or []:
            if not isinstance(item, dict):
                continue
            text = self._template(item.get("text"), extra)
            role = str(item.get("role") or "user")
            if role == "system":
                system_parts.append(text)
            else:
                if role != "user":
                    self.warn(f"节点 {dify_id} 提示词含 {role} 角色，已并入 user_prompt")
                user_parts.append(text)
        max_tokens = params.get("max_tokens")
        return {
            "provider": self.llm_provider,
            "model": str(model.get("name") or ""),
            "system_prompt": "\n\n".join(system_parts),
            "user_prompt": "\n\n".join(user_parts) or "{{ query }}",
            "temperature": float(params.get("temperature") or 0.7),
            "max_tokens": int(max_tokens) if max_tokens else None,
            "output_var": our_id,
        }

    def _context_ref(self, data: dict[str, Any]) -> dict[str, str]:
        context = data.get("context")
        if not isinstance(context, dict) or not context.get("enabled"):
            return {}
        expression = self._selector(context.get("variable_selector"))
        return {"context": expression} if expression else {}

    def _knowledge_config(self, our_id: str, data: dict[str, Any]) -> dict[str, Any]:
        expression = self._selector(data.get("query_variable_selector"))
        config = data.get("multiple_retrieval_config") or data.get("single_retrieval_config") or {}
        if not isinstance(config, dict):
            config = {}
        dataset_ids = [str(item) for item in (data.get("dataset_ids") or [])]
        if dataset_ids:
            self.warn("Dify 知识库数据集需在中台重新入库后才能检索（dataset_id 已保留）")
        threshold = config.get("score_threshold")
        return {
            "retriever": self.retriever,
            "dataset_ids": dataset_ids,
            "query": f"{{{{ {expression} }}}}" if expression else "{{ query }}",
            "top_k": int(config.get("top_k") or 5),
            "score_threshold": float(threshold) if threshold is not None else None,
            "output_var": our_id,
        }

    def _condition_config(self, dify_id: str, data: dict[str, Any]) -> dict[str, Any]:
        handles = [
            str(edge.get("sourceHandle"))
            for edge in self.raw_edges
            if isinstance(edge, dict) and str(edge.get("source")) == dify_id and edge.get("sourceHandle")
        ]
        branches: list[dict[str, str]] = []
        for index, case in enumerate(data.get("cases") or []):
            if not isinstance(case, dict):
                continue
            case_id = str(case.get("case_id") or "")
            if not case_id:
                case_id = handles[index] if index < len(handles) else f"case_{index + 1}"
            branches.append({"id": case_id, "expression": self._condition_expression(case)})
        if len(branches) > len(handles):
            self.warn(f"条件节点 {dify_id} 的分支数多于出边数，多余分支将走兜底路径")
        if not handles:
            self.warn(f"条件节点 {dify_id} 没有出边，所有分支直达结束")
            fallback = ""
        elif "false" in handles:
            fallback = "false"
        else:
            fallback = handles[-1]
        return {"branches": branches, "fallback_id": fallback}

    def _condition_expression(self, case: dict[str, Any]) -> str:
        parts: list[str] = []
        for condition in case.get("conditions") or []:
            if not isinstance(condition, dict):
                continue
            rendered = self._condition_part(condition)
            if rendered:
                parts.append(rendered)
        if not parts:
            return "false"
        operator = " and " if str(case.get("logical_operator") or "and") == "and" else " or "
        return operator.join(parts)

    def _condition_part(self, condition: dict[str, Any]) -> str:
        variable = self._selector(condition.get("variable_selector"))
        operator = str(condition.get("comparison_operator") or "").strip()
        template = _OPERATORS.get(operator)
        if not variable:
            self.warn("条件缺少变量取值，该条件恒为 false")
            return "false"
        if template is None:
            self.warn(f"条件运算符 {operator or '未知'} 不支持，该条件恒为 false")
            return "false"
        value = condition.get("value")
        if isinstance(value, list) and len(value) >= 2:
            literal = self._selector(value)
        elif operator in _NUMERIC_OPERATORS:
            literal = _comparison_literal(value)
        else:
            literal = _literal(value)
        return template.format(v=variable, l=literal)

    def _code_config(self, data: dict[str, Any]) -> dict[str, Any]:
        inputs: list[dict[str, str]] = []
        for item in data.get("variables") or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("variable") or "")
            expression = self._selector(item.get("value_selector"))
            if name and expression:
                inputs.append({"name": name, "expression": expression})
            elif name:
                self.warn(f"代码节点入参 {name} 缺少取值表达式，已忽略")
        return {
            "code": str(data.get("code") or ""),
            "inputs": inputs,
            "outputs": [str(key) for key in (data.get("outputs") or {})],
            "timeout_ms": int(data.get("timeout") or 3000),
        }

    def _tool_config(self, our_id: str, dify_id: str, data: dict[str, Any]) -> dict[str, Any]:
        server = str(data.get("provider_name") or data.get("provider_id") or "")
        args = {
            str(key): self._param(value)
            for key, value in (data.get("tool_parameters") or {}).items()
        }
        self.warn(f"工具节点需在中台注册 MCP Server（{server or '未署名'}）后才能运行")
        return {
            "tools": [
                {
                    "name": str(data.get("tool_name") or data.get("tool_label") or dify_id),
                    "server": server,
                    "args": args,
                }
            ],
            "output_var": our_id,
        }

    def _aggregate_config(self, our_id: str, data: dict[str, Any]) -> dict[str, Any]:
        variables = [self._selector(item) for item in (data.get("variables") or [])]
        return {"variables": [item for item in variables if item], "output_var": our_id}

    def _answer_config(self, our_id: str, data: dict[str, Any]) -> dict[str, Any]:
        return {"template": self._template(data.get("answer")), "output_var": our_id}

    # ------------------------------------------------------------------ 边

    def _build_edges(self) -> list[dict[str, str]]:
        successors: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for edge in self.raw_edges:
            if isinstance(edge, dict):
                successors[str(edge.get("source"))].append(edge)

        edges: list[dict[str, str]] = []
        emitted: set[tuple[str, str, str]] = set()

        def emit(source: str, target: str, handle: str) -> None:
            key = (source, target, handle)
            if key in emitted:
                return
            emitted.add(key)
            edges.append(
                {
                    "id": f"e_{source}_{target}_{handle or 'default'}",
                    "source": source,
                    "target": target,
                    "source_handle": handle,
                }
            )

        def descend(node_id: str, visited: set[str]) -> list[str]:
            reached: list[str] = []
            for edge in successors.get(node_id, []):
                target = str(edge.get("target"))
                if target in self.id_map:
                    reached.append(target)
                elif target not in visited:
                    visited.add(target)
                    reached.extend(descend(target, visited))
            return reached

        for edge in self.raw_edges:
            if not isinstance(edge, dict):
                continue
            source = str(edge.get("source"))
            if source not in self.id_map:
                continue
            handle = str(edge.get("sourceHandle") or "")
            target = str(edge.get("target"))
            if target in self.id_map:
                emit(self.id_map[source], self.id_map[target], handle)
                continue
            for reached in descend(target, {target}):
                emit(self.id_map[source], self.id_map[reached], handle)
        return edges

    # ------------------------------------------------------------------ 入口

    def run(self, graph: dict[str, Any]) -> ImportResult:
        raw_nodes = graph.get("nodes")
        raw_edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
        self.raw_nodes = [node for node in raw_nodes if isinstance(node, dict)]
        self.raw_edges = [edge for edge in raw_edges if isinstance(edge, dict)]

        planned = self._plan()

        nodes: list[dict[str, Any]] = []
        for raw, dify_id, our_id, ntype in planned:
            position = raw.get("position") if isinstance(raw.get("position"), dict) else {}
            nodes.append(
                {
                    "id": our_id,
                    "type": ntype.value,
                    "title": self._title(raw),
                    "position": {"x": float(position.get("x") or 0), "y": float(position.get("y") or 0)},
                    "config": self._config(our_id, dify_id, ntype, self.data_map[dify_id]),
                }
            )
        if not any(node["type"] == NodeType.START.value for node in nodes):
            self.warn("未找到 start 节点，导入后需手工补齐")

        try:
            definition = GraphDef(
                app_id=self.app_id, name=self.name, inputs=self.inputs, nodes=nodes, edges=self._build_edges()
            )
        except ValidationError as exc:
            raise DifyImportError(f"生成的图校验失败: {exc}") from exc

        degraded = len(self.raw_nodes) - len(nodes)
        return ImportResult(
            definition=definition.model_dump(mode="json"),
            warnings=list(self.warnings),
            stats={"total": len(self.raw_nodes), "converted": len(nodes), "degraded": degraded},
        )


def _extract_graph(dsl: Any) -> dict[str, Any]:
    if not isinstance(dsl, dict):
        raise DifyImportError("DSL 必须是对象（JSON/YAML）")
    workflow = dsl.get("workflow")
    graph = workflow.get("graph") if isinstance(workflow, dict) else None
    if not isinstance(graph, dict):
        graph = dsl.get("graph")
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
        raise DifyImportError("DSL 中未找到 workflow.graph.nodes")
    return graph


def convert(
    dsl: Any,
    *,
    app_id: str = "",
    name: str = "",
    llm_provider: str = "cloud_gateway",
    retriever: str = "builtin",
) -> ImportResult:
    """Dify DSL → 中台图定义。llm_provider / retriever 为导入后统一切换的适配器名。"""
    if llm_provider not in ("cloud_gateway", "openai"):
        raise DifyImportError(f"不支持的 llm_provider: {llm_provider}")
    if retriever not in ("builtin", "light_rag", "knowflow", "knowledge_graph"):
        raise DifyImportError(f"不支持的 retriever: {retriever}")
    graph = _extract_graph(dsl)
    app = dsl.get("app") if isinstance(dsl.get("app"), dict) else {}
    converter = _Converter(
        app_id=app_id or str(app.get("id") or ""),
        name=name or str(app.get("name") or ""),
        llm_provider=llm_provider,
        retriever=retriever,
    )
    return converter.run(graph)


def parse_dsl(text: str) -> dict[str, Any]:
    """解析 DSL 文本：先按 JSON，再按 YAML（Dify 前端导出为 YAML）。"""
    if not text or not text.strip():
        raise DifyImportError("DSL 内容为空")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        import yaml

        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise DifyImportError(f"DSL 解析失败: {exc}") from exc
    if not isinstance(data, dict):
        raise DifyImportError("DSL 内容必须是对象")
    return data


def load_dsl(path: str | Path) -> dict[str, Any]:
    """从文件读取 DSL（.json / .yml / .yaml）。"""
    file_path = Path(path)
    if not file_path.is_file():
        raise DifyImportError(f"DSL 文件不存在: {file_path}")
    return parse_dsl(file_path.read_text(encoding="utf-8"))
