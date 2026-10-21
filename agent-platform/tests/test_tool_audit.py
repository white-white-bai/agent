"""工具调用审计：开关、成功/失败记录与查询接口。"""
from __future__ import annotations

import pytest

from agent_platform.core.audit import audit_tool_call, list_tool_audits
from agent_platform.core.config import Settings


@pytest.mark.asyncio
async def test_audit_records_success_and_failure():
    settings = Settings(tool_audit_enabled=True)

    async with audit_tool_call(
        settings, tenant_code="t", tool_name="echo", server="demo", args={"x": 1}
    ):
        pass
    with pytest.raises(RuntimeError):
        async with audit_tool_call(
            settings, tenant_code="t", tool_name="echo", server="demo", args={"x": 2}
        ):
            raise RuntimeError("boom")

    rows, total = list_tool_audits("t", tool_name="echo")

    assert total == 2
    assert {row.status for row in rows} == {"ok", "error"}
    error_row = next(row for row in rows if row.status == "error")
    assert error_row.error == "boom"
    assert error_row.args == {"x": 2}
    assert error_row.duration_ms >= 0


@pytest.mark.asyncio
async def test_audit_disabled_writes_nothing():
    async with audit_tool_call(
        Settings(), tenant_code="t", tool_name="echo", server="demo", args={}
    ):
        pass
    assert list_tool_audits("t")[1] == 0
