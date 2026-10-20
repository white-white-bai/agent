"""工具调用治理：参数校验、瞬时错误指数退避重试、失败兜底。

只重试**瞬时错误**（超时 / 连接失败 / 5xx / 429）；参数错误与业务错误直接抛出。
兜底默认关闭，开启后按策略返回空值 / 固定值 / 提示话术。
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TRUE = {"true", "1", "yes", "on"}
_FALSE = {"false", "0", "no", "off", ""}
_WIDTH_LIMIT = 20000


class ToolValidationError(Exception):
    """参数校验失败（不可重试）。"""


def _type_ok(kind: str, value: Any) -> bool:
    if kind in ("string", "text"):
        return isinstance(value, str) and len(value) <= _WIDTH_LIMIT
    if kind in ("number", "integer", "float"):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind in ("boolean", "bool"):
        if isinstance(value, bool):
            return True
        return isinstance(value, str) and value.strip().lower() in (_TRUE | _FALSE)
    if kind in ("array", "list"):
        return isinstance(value, (list, tuple))
    if kind in ("object", "dict"):
        return isinstance(value, dict)
    return True


def _required(spec: dict[str, Any]) -> bool:
    value = spec.get("required")
    if isinstance(value, str):
        return value.strip().lower() in _TRUE
    return bool(value)


def validate_args(params: list[dict[str, Any]] | None, args: dict[str, Any]) -> list[str]:
    """按声明的参数 schema 校验，返回错误清单（空表示通过）。"""
    errors: list[str] = []
    for spec in params or []:
        if not isinstance(spec, dict):
            continue
        name = str(spec.get("name") or "")
        if not name:
            continue
        value = args.get(name)
        if value is None or value == "":
            if _required(spec):
                errors.append(f"缺少必填参数 {name}")
            continue
        kind = str(spec.get("type") or "string").lower()
        if not _type_ok(kind, value):
            errors.append(f"参数 {name} 类型应为 {kind}")
            continue
        options = spec.get("enum") or []
        if options and value not in options:
            errors.append(f"参数 {name} 取值需为 {list(options)} 之一")
    return errors


def is_retryable(error: BaseException) -> bool:
    """瞬时错误才重试：超时 / 传输错误 / 5xx / 429。"""
    if isinstance(error, (httpx.TimeoutException, httpx.TransportError)):
        return True
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        return status >= 500 or status == 429
    return False


async def call_with_retry(
    fn: Callable[[], Awaitable[Any]],
    *,
    attempts: int = 1,
    backoff: float = 0.5,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Any:
    """指数退避重试；非瞬时错误立即抛出。"""
    total = max(int(attempts or 1), 1)
    attempt = 0
    while True:
        try:
            return await fn()
        except Exception as exc:
            attempt += 1
            if attempt >= total or not is_retryable(exc):
                raise
            await sleep(max(backoff, 0.0) * (2 ** (attempt - 1)))


def resolve_failure(fallback: dict[str, Any] | None, error: BaseException) -> tuple[bool, Any]:
    """按兜底策略给出替代返回值：返回 (是否兜底, 值)。"""
    policy = fallback or {}
    if not policy.get("enabled"):
        return False, None
    mode = str(policy.get("mode") or "empty")
    if mode == "value":
        return True, policy.get("value")
    if mode == "text":
        message = str(policy.get("value") or policy.get("text") or "该服务暂时不可用，请稍后再试。")
        return True, {"error": str(error), "message": message}
    return True, None


async def call_tool_governed(
    *,
    params: list[dict[str, Any]] | None,
    args: dict[str, Any],
    call: Callable[[], Awaitable[Any]],
    name: str = "",
    validate: bool = True,
    attempts: int = 1,
    backoff: float = 0.5,
    fallback: dict[str, Any] | None = None,
) -> Any:
    """统一入口：参数校验 → 重试调用 → 失败兜底。"""
    if validate:
        errors = validate_args(params, args)
        if errors:
            raise ToolValidationError(f"工具 {name or '?'} 参数校验失败：" + "；".join(errors))
    try:
        return await call_with_retry(call, attempts=attempts, backoff=backoff)
    except Exception as exc:
        handled, value = resolve_failure(fallback, exc)
        if handled:
            logger.warning("工具 %s 调用失败已兜底：%s", name or "?", exc)
            return value
        raise
