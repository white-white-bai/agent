"""受限 Python 代码节点执行（禁用导入/网络，白名单内置函数）。"""
from __future__ import annotations

from typing import Any

from agent_platform.engine.expr import evaluate
from agent_platform.graph.schema import CodeConfig

_SAFE_BUILTINS = {
    "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict, "enumerate": enumerate,
    "float": float, "int": int, "len": len, "list": list, "max": max, "min": min, "range": range,
    "round": round, "set": set, "sorted": sorted, "str": str, "sum": sum, "tuple": tuple, "zip": zip,
    "ValueError": ValueError, "Exception": Exception, "print": None,
}


class CodeExecutionError(Exception):
    pass


def run_code(config: CodeConfig, variables: dict[str, Any]) -> dict[str, Any]:
    if not config.code.strip():
        raise CodeExecutionError("代码节点为空")

    inputs = {item.name: evaluate(item.expression, variables) for item in config.inputs}

    sandbox_globals: dict[str, Any] = {"__builtins__": _SAFE_BUILTINS}
    try:
        exec(compile(config.code, "<code_node>", "exec"), sandbox_globals)
        main = sandbox_globals.get("main")
        if not callable(main):
            raise CodeExecutionError("代码节点必须定义 main(**inputs) 函数")
        result = main(**inputs)
    except CodeExecutionError:
        raise
    except Exception as exc:
        raise CodeExecutionError(f"代码节点执行失败: {exc}") from exc

    if result is None:
        result = {}
    if not isinstance(result, dict):
        raise CodeExecutionError("代码节点 main 必须返回 dict")

    if config.outputs:
        return {name: result.get(name) for name in config.outputs}
    return result
