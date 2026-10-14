"""执行态定义。"""
from __future__ import annotations

from typing import Any, TypedDict


class GraphState(TypedDict, total=False):
    inputs: dict[str, Any]
    variables: dict[str, Any]
    query: str
    answer: str
    route: str
    error: str
