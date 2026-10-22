"""Agent 运行轨迹持久化与查询。"""
from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
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


def export_traces(
    tenant_code: str,
    *,
    app_uuid: str = "",
    days: int = 7,
    limit: int = 100,
    status: str = "",
) -> list[dict[str, Any]]:
    """把生产轨迹导出为 eval_agent_traces.py 可直接读取的 JSON 结构。"""
    days = min(max(int(days or 7), 1), 90)
    limit = min(max(int(limit or 100), 1), 10000)
    today = datetime.now(timezone.utc).replace(tzinfo=None).date()
    start_date = today - timedelta(days=days - 1)
    since = datetime(start_date.year, start_date.month, start_date.day)
    with session_scope() as session:
        stmt = select(AgentTraceLog).where(AgentTraceLog.created_at >= since)
        if tenant_code:
            stmt = stmt.where(AgentTraceLog.tenant_code == tenant_code)
        if app_uuid:
            stmt = stmt.where(AgentTraceLog.app_uuid == app_uuid)
        if status:
            stmt = stmt.where(AgentTraceLog.status == status)
        rows = list(session.scalars(stmt.order_by(AgentTraceLog.id.desc()).limit(limit)).all())
    return [
        {
            "id": row.uuid,
            "case_id": row.uuid,
            "query": row.query,
            "tool_calls": list(row.tool_calls or []),
            "tool_events": list(row.tool_events or []),
            "answer": row.answer,
            "status": row.status,
            "duration_ms": int(row.duration_ms or 0),
            "token_chars": int(row.token_chars or 0),
            "error": "",
        }
        for row in rows
    ]


def trace_stats(
    tenant_code: str = "",
    *,
    app_uuid: str = "",
    days: int = 7,
    limit: int = 10000,
) -> dict[str, Any]:
    """轨迹聚合：状态、耗时、工具使用与每日趋势。"""
    days = min(max(int(days or 7), 1), 90)
    today = datetime.now(timezone.utc).replace(tzinfo=None).date()
    start_date = today - timedelta(days=days - 1)
    since = datetime(start_date.year, start_date.month, start_date.day)
    with session_scope() as session:
        stmt = select(AgentTraceLog).where(AgentTraceLog.created_at >= since)
        if tenant_code:
            stmt = stmt.where(AgentTraceLog.tenant_code == tenant_code)
        if app_uuid:
            stmt = stmt.where(AgentTraceLog.app_uuid == app_uuid)
        rows = list(
            session.scalars(
                stmt.order_by(AgentTraceLog.id.desc()).limit(min(max(int(limit or 10000), 1), 50000))
            ).all()
        )
    durations = sorted(int(row.duration_ms or 0) for row in rows)
    p95 = durations[min(round(len(durations) * 0.95) - 1, len(durations) - 1)] if durations else 0
    tools: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    daily: dict[str, int] = {}
    for offset in range(days):
        daily[(start_date + timedelta(days=offset)).isoformat()] = 0
    for row in rows:
        statuses[str(row.status or "completed")] += 1
        for item in row.tool_calls or []:
            tools[str(item)] += 1
        day = row.created_at.date().isoformat() if row.created_at else ""
        if day in daily:
            daily[day] += 1
    return {
        "total": len(rows),
        "statuses": dict(statuses),
        "avg_duration_ms": round(sum(durations) / len(durations), 1) if durations else 0,
        "p95_duration_ms": p95,
        "avg_tool_calls": round(sum(len(row.tool_calls or []) for row in rows) / len(rows), 2) if rows else 0,
        "avg_token_chars": round(sum(int(row.token_chars or 0) for row in rows) / len(rows), 1) if rows else 0,
        "top_tools": [{"tool": name, "count": count} for name, count in tools.most_common(10)],
        "daily": [{"date": day, "count": count} for day, count in sorted(daily.items())],
        "days": days,
    }
