"""模板渲染与条件表达式（Jinja2）。"""
from __future__ import annotations

from typing import Any

from jinja2 import Environment, StrictUndefined, TemplateError
from jinja2.nativetypes import NativeEnvironment


class ExpressionError(Exception):
    pass


_render_env = Environment(undefined=StrictUndefined, autoescape=False)
_expr_env = NativeEnvironment(undefined=StrictUndefined, autoescape=False)


def render(template: str, variables: dict[str, Any]) -> str:
    if template is None:
        return ""
    try:
        return _render_env.from_string(template).render(**variables)
    except TemplateError as exc:
        raise ExpressionError(f"模板渲染失败: {exc}") from exc


def evaluate(expression: str, variables: dict[str, Any]) -> Any:
    try:
        compiled = _expr_env.compile_expression(expression, undefined_to_none=False)
        return compiled(**variables)
    except TemplateError as exc:
        raise ExpressionError(f"表达式求值失败: {exc}") from exc
