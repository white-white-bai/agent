"""Langfuse 埋点：no-op 降级、Span 生命周期与节点级 trace。"""
from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from agent_platform.core.config import Settings
from agent_platform.engine.context import EngineContext
from agent_platform.engine.runtime import run_graph
from agent_platform.graph.schema import GraphDef
from agent_platform.observability.langfuse import LangfuseTracer, Span, Tracer, build_tracer


class FakeLLM:
    async def __call__(self, *, provider, model, system_prompt, user_prompt, temperature, max_tokens):
        return f"echo:{user_prompt}"


class _FakeHandle:
    def __init__(self, log: list) -> None:
        self._log = log

    def end(self, **kwargs: Any) -> None:
        self._log.append(kwargs)


class _FakeTrace:
    def __init__(self, log: list, *, fail: bool = False) -> None:
        self._log = log
        self.fail = fail
        self.span_calls: list[dict] = []

    def span(self, **kwargs: Any) -> _FakeHandle:
        if self.fail:
            raise RuntimeError("langfuse down")
        self.span_calls.append(kwargs)
        return _FakeHandle(self._log)


class _FakeClient:
    def __init__(self, trace: Any = None, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self._trace = trace
        self.trace_kwargs: dict = {}
        self.calls: list[str] = []

    def trace(self, **kwargs: Any) -> Any:
        self.trace_kwargs = kwargs
        return self._trace

    def flush(self) -> None:
        self.calls.append("flush")

    def shutdown(self) -> None:
        self.calls.append("shutdown")


def _inject_langfuse(monkeypatch, factory: Any) -> None:
    module = types.ModuleType("langfuse")
    module.Langfuse = factory
    monkeypatch.setitem(sys.modules, "langfuse", module)


# --------------------------------------------------------------------------- 降级


def test_build_tracer_without_host_is_noop():
    tracer = build_tracer(Settings())
    assert isinstance(tracer, Tracer)
    assert tracer.enabled is False
    span = tracer.span("node", {"a": 1})
    span.end(output={"ok": True})
    assert span.output == {"ok": True}
    assert tracer.flush() is None
    assert tracer.shutdown() is None


def test_build_tracer_falls_back_when_langfuse_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "langfuse", None)
    assert isinstance(build_tracer(Settings(langfuse_host="https://lf.local")), Tracer)


def test_build_tracer_falls_back_when_client_construction_fails(monkeypatch):
    def boom(**kwargs: Any) -> Any:
        raise RuntimeError("bad keys")

    _inject_langfuse(monkeypatch, boom)
    tracer = build_tracer(Settings(langfuse_host="https://lf.local"))
    assert isinstance(tracer, Tracer)
    assert tracer.enabled is False


def test_build_tracer_uses_langfuse_when_configured(monkeypatch):
    created: dict[str, Any] = {}

    def factory(**kwargs: Any) -> _FakeClient:
        client = _FakeClient(trace="trace-handle", **kwargs)
        created["client"] = client
        return client

    _inject_langfuse(monkeypatch, factory)
    tracer = build_tracer(
        Settings(
            langfuse_host="https://lf.local",
            langfuse_public_key="pk",
            langfuse_secret_key="sk",
        ),
        name="chat-messages",
        user_id="alice",
        metadata={"app_id": "app-1"},
    )
    assert isinstance(tracer, LangfuseTracer)
    assert tracer.enabled is True
    assert created["client"].kwargs == {
        "host": "https://lf.local",
        "public_key": "pk",
        "secret_key": "sk",
    }
    assert created["client"].trace_kwargs == {
        "name": "chat-messages",
        "user_id": "alice",
        "metadata": {"app_id": "app-1"},
    }


def test_build_tracer_maps_anonymous_user_to_none(monkeypatch):
    created: dict[str, Any] = {}

    def factory(**kwargs: Any) -> _FakeClient:
        client = _FakeClient(trace="t", **kwargs)
        created["client"] = client
        return client

    _inject_langfuse(monkeypatch, factory)
    build_tracer(Settings(langfuse_host="https://lf.local"))
    assert created["client"].trace_kwargs == {"name": "graph-run", "user_id": None, "metadata": {}}


# --------------------------------------------------------------------------- Span


def test_span_end_records_output_error_and_duration():
    span = Span("node", {"node_type": "llm"})
    assert span.duration_ms == 0.0
    span.end(output={"text": "hi"})
    assert span.output == {"text": "hi"}
    assert span.error == ""
    assert span.duration_ms >= 0.0

    failed = Span("node")
    failed.end(error="boom")
    assert failed.error == "boom"
    assert failed.output is None


def test_span_end_forwards_to_handle():
    log: list = []
    span = Span("node", {"node_type": "llm"})
    span.set_handle(_FakeHandle(log))
    span.end(output={"text": "hi"})
    assert log == [{"output": {"text": "hi"}, "metadata": {"node_type": "llm"}}]


def test_span_end_merges_error_into_metadata():
    log: list = []
    span = Span("node", {"node_type": "llm"})
    span.set_handle(_FakeHandle(log))
    span.end(error="boom")
    assert log == [{"output": None, "metadata": {"node_type": "llm", "error": "boom"}}]


def test_span_end_swallows_handle_errors():
    class Boom:
        def end(self, **kwargs: Any) -> None:
            raise RuntimeError("cannot export")

    span = Span("node")
    span.set_handle(Boom())
    span.end(output="x")
    assert span.output == "x"


# --------------------------------------------------------------------------- node_span


def test_node_span_reraises_and_records_error():
    tracer = Tracer()
    with pytest.raises(ValueError, match="boom"), tracer.node_span("llm-1", "llm", payload={"query": "hi"}) as span:
        raise ValueError("boom")
    assert span.name == "llm-1"
    assert span.metadata == {"node_type": "llm", "input": {"query": "hi"}}
    assert span.error == "boom"


def test_node_span_leaves_successful_span_clean():
    tracer = Tracer()
    with tracer.node_span("llm-1", "llm") as span:
        span.end(output={"text": "hi"})
    assert span.error == ""
    assert span.output == {"text": "hi"}


def test_langfuse_tracer_span_attaches_handle():
    log: list = []
    trace = _FakeTrace(log)
    tracer = LangfuseTracer(_FakeClient(), trace)
    span = tracer.span("llm-1", {"node_type": "llm"})
    assert trace.span_calls == [{"name": "llm-1", "metadata": {"node_type": "llm"}}]
    span.end(output={"text": "hi"})
    assert log == [{"output": {"text": "hi"}, "metadata": {"node_type": "llm"}}]


def test_langfuse_tracer_survives_span_failure():
    tracer = LangfuseTracer(_FakeClient(), _FakeTrace([], fail=True))
    span = tracer.span("llm-1")
    assert span._handle is None
    span.end(output="x")
    assert span.output == "x"


def test_langfuse_tracer_flush_and_shutdown_delegate():
    client = _FakeClient()
    tracer = LangfuseTracer(client, _FakeTrace([]))
    tracer.flush()
    tracer.shutdown()
    assert client.calls == ["flush", "flush", "shutdown"]


def test_langfuse_tracer_swallows_client_errors():
    class Boom:
        def flush(self) -> None:
            raise RuntimeError("nope")

        def shutdown(self) -> None:
            raise RuntimeError("nope")

    tracer = LangfuseTracer(Boom(), _FakeTrace([]))
    tracer.flush()
    tracer.shutdown()


# --------------------------------------------------------------------------- 图内埋点


@pytest.mark.asyncio
async def test_enabled_tracer_records_one_span_per_node(graph_def):
    log: list = []
    trace = _FakeTrace(log)
    tracer = LangfuseTracer(_FakeClient(), trace)
    ctx = EngineContext(llm=FakeLLM(), tracer=tracer)

    state = await run_graph(GraphDef.model_validate(graph_def), {"query": "常州"}, ctx)
    assert state["answer"] == "echo:常州"
    assert [call["name"] for call in trace.span_calls] == ["start", "llm", "answer", "end"]
    assert len(log) == 4


@pytest.mark.asyncio
async def test_disabled_tracer_is_not_used(graph_def):
    log: list = []
    tracer = Tracer()
    tracer.span = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no span expected"))
    ctx = EngineContext(llm=FakeLLM(), tracer=tracer)

    assert (await run_graph(GraphDef.model_validate(graph_def), {"query": "常州"}, ctx))["answer"] == "echo:常州"
    assert log == []
