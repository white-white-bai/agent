"""Agent 运行轨迹持久化与查询。"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select

from agent_platform.core.db import session_scope
from agent_platform.domain.models import AgentTraceLog


def save_trace(
    *,
    tenant_code: str,
    app_uuid: str,
    thread_id: str,
    query: str,
    events: list[dict[str, Any]],
) -> str | None:
    from agent_platform.agentapp.eval import trace_from_events

    trace = trace_from_events(uuid.uuid4().hex, events)
    row_uuid = uuid.uuid4().hex
    with session_scope() as session:
        session.add(
            AgentTraceLog(
                uuid=row_uuid,
                tenant_code=tenant_code,
                app_uuid=app_uuid,
                thread_id=thread_id,
                query=query,
                tool_calls=trace.tool_calls,
                tool_events=trace.tool_events,
                answer=trace.answer,
                status=trace.status,
                duration_ms=trace.duration_ms,
                token_chars=trace.token_chars,
            )
        )
    return row_uuid


def list_traces(
    tenant_code: str = "",
    *,
    app_uuid: str = "",
    status: str = "",
    page: int = 1,
    size: int = 20,
) -> tuple[list[AgentTraceLog], int]:
    page = max(int(page or 1), 1)
    size = min(max(int(size or 20), 1), 200)
    with session_scope() as session:
        stmt = select(AgentTraceLog)
        if tenant_code:
            stmt = stmt.where(AgentTraceLog.tenant_code == tenant_code)
        if app_uuid:
            stmt = stmt.where(AgentTraceLog.app_uuid == app_uuid)
        if status:
            stmt = stmt.where(AgentTraceLog.status == status)
        total = int(session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        rows = list(
            session.scalars(
                stmt.order_by(AgentTraceLog.id.desc()).offset((page - 1) * size).limit(size)
            ).all()
        )
        return rows, total
