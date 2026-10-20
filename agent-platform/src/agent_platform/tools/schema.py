"""工具 schema 转换：ap_tool.params / MCP inputSchema → OpenAI function schema。"""
from __future__ import annotations

import hashlib
import re
from typing import Any

_TYPE_MAP = {
    "string": "string",
    "text": "string",
    "number": "number",
    "integer": "integer",
    "float": "number",
    "boolean": "boolean",
    "bool": "boolean",
    "array": "array",
    "list": "array",
    "object": "object",
    "dict": "object",
}


def safe_function_name(name: str) -> str:
    """OpenAI 兼容端通常只接受 [A-Za-z0-9_-]；点号工具名需要安全化。"""
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", name or "").strip("_")
    if not text:
        text = "tool"
    if not text[0].isalpha():
        text = f"t_{text}"
    if len(text) > 64:
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
        text = f"{text[:55]}_{digest}"
    return text


def _json_type(kind: str) -> str:
    lowered = (kind or "string").strip().lower()
    if lowered.startswith("array"):
        return "array"
    return _TYPE_MAP.get(lowered, "string")


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


def params_to_json_schema(params: list[dict[str, Any]] | None) -> dict[str, Any]:
    """把 ap_tool.params 的扁平定义转成 JSON Schema object。"""
    properties: dict[str, Any] = {}
    required: list[str] = []
    for item in params or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        kind = _json_type(str(item.get("type") or "string"))
        prop: dict[str, Any] = {"type": kind}
        description = item.get("description")
        if description:
            prop["description"] = str(description)
        options = item.get("enum") or item.get("options")
        if options:
            prop["enum"] = list(options)
        if kind == "array":
            prop["items"] = {"type": "string"}
        properties[name] = prop
        if _as_bool(item.get("required")):
            required.append(name)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def schema_to_params(schema: dict[str, Any] | None) -> list[dict[str, Any]]:
    """把 JSON Schema 的顶层 properties 转回 policy.validate_args 认得的 params。"""
    if not isinstance(schema, dict):
        return []
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return []
    required = set(schema.get("required") or [])
    params: list[dict[str, Any]] = []
    for name, prop in properties.items():
        if not isinstance(prop, dict):
            continue
        item: dict[str, Any] = {
            "name": str(name),
            "type": str(prop.get("type") or "string"),
            "required": name in required,
        }
        if prop.get("description"):
            item["description"] = str(prop["description"])
        if prop.get("enum"):
            item["enum"] = list(prop["enum"])
        params.append(item)
    return params


def to_openai_tool(
    name: str,
    description: str = "",
    params: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """由声明参数生成 OpenAI function tool。"""
    return {
        "type": "function",
        "function": {
            "name": safe_function_name(name),
            "description": description or name,
            "parameters": params_to_json_schema(params),
        },
    }


def from_mcp_tool(tool: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """把 MCP tools/list 的一项转成 OpenAI tool + 本地校验参数。"""
    raw_name = str(tool.get("name") or "").strip()
    input_schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    if not isinstance(input_schema, dict):
        input_schema = {}
    input_schema = dict(input_schema)
    input_schema.setdefault("type", "object")
    input_schema.setdefault("properties", {})
    schema = {
        "type": "function",
        "function": {
            "name": safe_function_name(raw_name),
            "description": str(tool.get("description") or raw_name),
            "parameters": input_schema,
        },
    }
    return schema, schema_to_params(input_schema)
