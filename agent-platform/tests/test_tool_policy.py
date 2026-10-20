"""工具治理：参数校验 / 瞬时错误重试 / 失败兜底。"""
from __future__ import annotations

import httpx
import pytest

from agent_platform.tools.policy import (
    ToolValidationError,
    call_tool_governed,
    call_with_retry,
    is_retryable,
    resolve_failure,
    validate_args,
)

PARAMS = [
    {"name": "keyword", "type": "string", "required": True},
    {"name": "page", "type": "number"},
    {"name": "mode", "type": "string", "enum": ["a", "b"]},
]


async def _no_sleep(seconds: float) -> None:
    return None


def _status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://tool.local")
    return httpx.HTTPStatusError("boom", request=request, response=httpx.Response(status, request=request))


# --------------------------------------------------------------------------- 参数校验


def test_validate_args_flags_missing_type_and_enum():
    assert validate_args(PARAMS, {"keyword": "x", "page": 1, "mode": "a"}) == []
    errors = validate_args(PARAMS, {"page": "x", "mode": "c"})
    assert any("缺少必填参数 keyword" in item for item in errors)
    assert any("参数 page 类型应为 number" in item for item in errors)
    assert any("参数 mode 取值需为" in item for item in errors)


def test_validate_args_treats_string_false_as_optional():
    assert validate_args([{"name": "q", "type": "string", "required": "false"}], {}) == []
    assert validate_args([{"name": "q", "type": "string", "required": "true"}], {}) == ["缺少必填参数 q"]


def test_validate_args_boolean_and_unknown_specs():
    params = [{"name": "flag", "type": "boolean"}, {"name": "items", "type": "array"}]
    assert validate_args(params, {"flag": "true", "items": [1]}) == []
    assert validate_args(params, {"flag": "maybe"}) != []
    assert validate_args(params, {"items": {"a": 1}}) != []
    assert validate_args(None, {}) == []
    assert validate_args([{"type": "string"}], {}) == []


# --------------------------------------------------------------------------- 重试


def test_is_retryable_only_for_transient_errors():
    assert is_retryable(httpx.ConnectError("x")) is True
    assert is_retryable(httpx.TimeoutException("x")) is True
    assert is_retryable(_status_error(503)) is True
    assert is_retryable(_status_error(429)) is True
    assert is_retryable(_status_error(404)) is False
    assert is_retryable(ValueError("业务错误")) is False


@pytest.mark.asyncio
async def test_call_with_retry_transient_then_success():
    calls = {"n": 0}
    slept: list[float] = []

    async def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("down")
        return "ok"

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    assert await call_with_retry(flaky, attempts=3, backoff=0.5, sleep=sleep) == "ok"
    assert calls["n"] == 3
    assert slept == [0.5, 1.0]


@pytest.mark.asyncio
async def test_call_with_retry_stops_on_business_error():
    calls = {"n": 0}

    async def failing() -> None:
        calls["n"] += 1
        raise ValueError("业务错误")

    with pytest.raises(ValueError, match="业务错误"):
        await call_with_retry(failing, attempts=3, backoff=0.0, sleep=_no_sleep)
    assert calls["n"] == 1


# --------------------------------------------------------------------------- 兜底


def test_resolve_failure_modes():
    assert resolve_failure({}, ValueError("x")) == (False, None)
    assert resolve_failure({"enabled": True, "mode": "empty"}, ValueError("x")) == (True, None)
    assert resolve_failure({"enabled": True, "mode": "value", "value": []}, ValueError("x")) == (True, [])
    handled, payload = resolve_failure({"enabled": True, "mode": "text", "value": "稍后再试"}, ValueError("x"))
    assert handled is True
    assert payload["message"] == "稍后再试"


@pytest.mark.asyncio
async def test_call_tool_governed_validates_retries_and_falls_back():
    async def never() -> None:
        raise AssertionError("不应被调用")

    with pytest.raises(ToolValidationError, match="参数校验失败"):
        await call_tool_governed(name="t", params=PARAMS, args={}, call=never)

    async def failing() -> None:
        raise httpx.ConnectError("down")

    with pytest.raises(httpx.ConnectError):
        await call_tool_governed(name="t", params=PARAMS, args={"keyword": "x"}, call=failing, attempts=1)

    result = await call_tool_governed(
        name="t",
        params=PARAMS,
        args={"keyword": "x"},
        call=failing,
        attempts=1,
        fallback={"enabled": True, "mode": "value", "value": {"ok": False}},
    )
    assert result == {"ok": False}
