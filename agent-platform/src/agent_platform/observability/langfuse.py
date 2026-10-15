"""Langfuse 埋点：节点级 trace（输入/输出/耗时/错误）；未配置或未安装时降级为 no-op。

降级是**有声音**的：配置了 host 但 SDK 缺失 / 初始化失败时，首次会记一条 warning，
避免「配了密钥却什么都没上报」这种情况没人发现。
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any

from agent_platform.core.config import Settings

logger = logging.getLogger(__name__)

_warned = False


def _warn_once(message: str) -> None:
    global _warned
    if not _warned:
        _warned = True
        logger.warning(message)


def reset_warning() -> None:
    """测试用：重置「只告警一次」的标记。"""
    global _warned
    _warned = False


class Span:
    def __init__(self, name: str, metadata: dict[str, Any] | None = None) -> None:
        self.name = name
        self.metadata = metadata or {}
        self.started_at = time.perf_counter()
        self.duration_ms = 0.0
        self.output: Any = None
        self.error: str = ""
        self._handle: Any = None

    def set_handle(self, handle: Any) -> None:
        self._handle = handle

    def end(self, output: Any = None, error: str = "") -> None:
        self.duration_ms = round((time.perf_counter() - self.started_at) * 1000, 3)
        self.output = output
        self.error = error
        if self._handle is not None:
            try:
                self._handle.end(output=output, metadata={**self.metadata, "error": error} if error else self.metadata)
            except Exception:  # noqa: BLE001, S110
                pass


class Tracer:
    """基类：无副作用实现。"""

    enabled = False

    def span(self, name: str, metadata: dict[str, Any] | None = None) -> Span:
        return Span(name, metadata)

    @contextmanager
    def node_span(self, node_id: str, node_type: str, payload: Any = None):
        span = self.span(node_id, {"node_type": node_type, "input": payload})
        try:
            yield span
        except Exception as exc:
            span.end(error=str(exc))
            raise

    def flush(self) -> None:
        return None

    def shutdown(self) -> None:
        return None


class LangfuseTracer(Tracer):
    enabled = True

    def __init__(self, client: Any, trace: Any) -> None:
        self._client = client
        self._trace = trace

    def span(self, name: str, metadata: dict[str, Any] | None = None) -> Span:
        span = Span(name, metadata)
        try:
            span.set_handle(self._trace.span(name=name, metadata=metadata or {}))
        except Exception:  # noqa: BLE001, S110
            pass
        return span

    def flush(self) -> None:
        try:
            self._client.flush()
        except Exception:  # noqa: BLE001, S110
            pass

    def shutdown(self) -> None:
        self.flush()
        try:
            self._client.shutdown()
        except Exception:  # noqa: BLE001, S110
            pass


def build_tracer(settings: Settings, *, name: str = "graph-run", user_id: str = "", metadata: dict | None = None) -> Tracer:
    if not settings.langfuse_host:
        return Tracer()
    try:
        from langfuse import Langfuse
    except Exception as exc:  # noqa: BLE001
        _warn_once(
            f"Langfuse 已配置（{settings.langfuse_host}）但 SDK 不可用，链路追踪降级为 no-op："
            f"{type(exc).__name__}: {exc}（需要安装 langfuse>=2,<3）"
        )
        return Tracer()
    try:
        client = Langfuse(
            host=settings.langfuse_host,
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
        )
        trace = client.trace(name=name, user_id=user_id or None, metadata=metadata or {})
        return LangfuseTracer(client, trace)
    except Exception as exc:  # noqa: BLE001
        _warn_once(
            f"Langfuse 初始化失败（{settings.langfuse_host}），链路追踪降级为 no-op："
            f"{type(exc).__name__}: {exc}"
        )
        return Tracer()
