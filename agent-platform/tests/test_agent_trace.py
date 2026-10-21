"""Agent 生产轨迹持久化：保存、查询与工具事件字段。"""
from __future__ import annotations

from agent_platform.core.agent_trace import list_traces, save_trace


def test_save_and_list_agent_trace():
    events = [
        {"type": "agent_tool_call", "ts": 1.0, "calls": [{"id": "c1", "name": "weather", "args": {"city": "常州"}}]},
        {"type": "agent_tool", "ts": 1.2, "tools": [{"tool": "weather", "tool_call_id": "c1", "content": "晴"}]},
        {"type": "final", "ts": 2.0, "answer": "常州晴"},
    ]

    row_uuid = save_trace(
        tenant_code="t",
        app_uuid="app-1",
        thread_id="thread-1",
        query="天气",
        events=events,
    )

    assert row_uuid
    rows, total = list_traces("t", app_uuid="app-1")
    assert total == 1
    row = rows[0]
    assert row.thread_id == "thread-1"
    assert row.tool_calls == ["weather"]
    assert row.tool_events[0]["args"] == {"city": "常州"}
    assert row.answer == "常州晴"
    assert row.duration_ms == 1000
