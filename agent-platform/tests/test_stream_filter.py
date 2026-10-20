"""自主循环流式过滤：中间轮丢弃、最终轮 flush、反思轮抑制。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, AIMessageChunk

from agent_platform.engine.runtime import _TokenBuffer


def _stream(run_id: str = "r1", text: str = "x", tags: list[str] | None = None) -> dict:
    return {
        "event": "on_chat_model_stream",
        "run_id": run_id,
        "tags": tags or [],
        "data": {"chunk": AIMessageChunk(content=text)},
    }


def _end(run_id: str = "r1", content: str = "", tool_calls: list | None = None, tags: list[str] | None = None) -> dict:
    return {
        "event": "on_chat_model_end",
        "run_id": run_id,
        "tags": tags or [],
        "data": {"output": AIMessage(content=content, tool_calls=tool_calls or [])},
    }


def test_intermediate_tool_round_is_discarded():
    buf = _TokenBuffer()
    tags = ["agent-internal"]
    assert buf.on_stream(_stream(tags=tags, text="我需要调用工具")) is None
    assert buf.on_stream(_stream(tags=tags, text="...")) is None
    end = _end(tags=tags, tool_calls=[{"name": "t", "args": {}, "id": "c1"}])
    assert buf.on_end(end) is None


def test_final_answer_round_is_flushed():
    buf = _TokenBuffer()
    tags = ["agent-internal"]
    assert buf.on_stream(_stream(tags=tags, text="he")) is None
    assert buf.on_stream(_stream(tags=tags, text="llo")) is None
    assert buf.on_end(_end(tags=tags, content="hello")) == "hello"


def test_reflection_round_is_suppressed():
    buf = _TokenBuffer()
    tags = ["agent-internal", "agent-suppress"]
    buf.on_stream(_stream(tags=tags, text="审查意见"))
    assert buf.on_end(_end(tags=tags, content="审查意见")) is None


def test_non_tagged_stream_passes_through():
    buf = _TokenBuffer()
    assert buf.on_stream(_stream(tags=[], text="普通输出")) == "普通输出"
    assert buf.on_end(_end(tags=[], content="普通输出")) is None


def test_end_without_buffered_stream_returns_none():
    buf = _TokenBuffer()
    assert buf.on_end(_end(run_id="missing", content="x")) is None


def test_dict_output_tool_calls_are_detected():
    buf = _TokenBuffer()
    tags = ["agent-internal"]
    buf.on_stream(_stream(tags=tags, text="x"))
    event = {
        "event": "on_chat_model_end",
        "run_id": "r1",
        "tags": tags,
        "data": {"output": {"tool_calls": [{"name": "t", "args": {}, "id": "c1"}]}},
    }
    assert buf.on_end(event) is None


def test_buffers_are_isolated_by_run_id():
    buf = _TokenBuffer()
    tags = ["agent-internal"]
    buf.on_stream(_stream(run_id="a", tags=tags, text="A"))
    buf.on_stream(_stream(run_id="b", tags=tags, text="B"))
    assert buf.on_end(_end(run_id="a", tags=tags, content="A")) == "A"
    assert buf.on_end(_end(run_id="b", tags=tags, content="B")) == "B"
