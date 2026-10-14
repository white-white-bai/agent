"""监控看板汇总：会话量 / 消息量 / 满意度 / token / 错误率。

数据源全部取自中台自有表（`ap_conversation` / `ap_message` / `ap_metric_event`），
不依赖 Langfuse（其未配置时降级 no-op）。按租户 / 应用 / 天数窗口聚合，返回可直接画图的逐日序列。
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Select, func, select

from agent_platform.core.db import session_scope
from agent_platform.domain.models import Conversation, Message, MetricEvent

MAX_DAYS = 90


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def record_error(*, tenant_code: str = "", app_uuid: str = "", detail: str = "") -> None:
    """记录一次执行失败（供错误率统计）。不参与对话链路，写失败不得影响主流程。"""
    try:
        with session_scope() as session:
            session.add(
                MetricEvent(tenant_code=tenant_code, app_uuid=app_uuid, kind="error", detail=str(detail)[:512])
            )
    except Exception:  # noqa: BLE001
        return


def _scoped(columns: Sequence[Any], *, tenant_code: str, app_uuid: str, start: datetime) -> Select:
    stmt = (
        select(*columns)
        .join(Conversation, Conversation.uuid == Message.conversation_uuid)
        .where(Message.created_at >= start)
    )
    if tenant_code:
        stmt = stmt.where(Conversation.tenant_code == tenant_code)
    if app_uuid:
        stmt = stmt.where(Conversation.app_uuid == app_uuid)
    return stmt


def _conversation_scope(tenant_code: str, app_uuid: str) -> list[Any]:
    filters = []
    if tenant_code:
        filters.append(Conversation.tenant_code == tenant_code)
    if app_uuid:
        filters.append(Conversation.app_uuid == app_uuid)
    return filters


def _event_scope(tenant_code: str, app_uuid: str) -> list[Any]:
    filters = []
    if tenant_code:
        filters.append(MetricEvent.tenant_code == tenant_code)
    if app_uuid:
        filters.append(MetricEvent.app_uuid == app_uuid)
    return filters


def _fill(labels: list[str], rows: Sequence[tuple[Any, int]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = dict.fromkeys(labels, 0)
    for day, count in rows:
        key = str(day)[:10]
        if key in counts:
            counts[key] = int(count or 0)
    return [{"date": label, "count": counts[label]} for label in labels]


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def overview(*, tenant_code: str = "", app_uuid: str = "", days: int = 7) -> dict[str, Any]:
    days = max(1, min(int(days or 7), MAX_DAYS))
    today = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=days - 1)
    labels = [(start + timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(days)]
    scope = {"tenant_code": tenant_code, "app_uuid": app_uuid, "start": start}
    day = func.date(Message.created_at)

    with session_scope() as session:
        conversation_total = int(
            session.scalar(
                select(func.count(Conversation.id))
                .where(Conversation.created_at >= start)
                .where(*_conversation_scope(tenant_code, app_uuid))
            )
            or 0
        )
        conversation_series = session.execute(
            select(func.date(Conversation.created_at), func.count(Conversation.id))
            .where(Conversation.created_at >= start)
            .where(*_conversation_scope(tenant_code, app_uuid))
            .group_by(func.date(Conversation.created_at))
        ).all()
        role_rows = session.execute(
            _scoped([Message.role, func.count(Message.id)], **scope).group_by(Message.role)
        ).all()
        token_rows = session.execute(
            _scoped([day, func.coalesce(func.sum(Message.tokens), 0)], **scope).group_by(day)
        ).all()
        feedback_rows = session.execute(
            _scoped([Message.feedback, func.count(Message.id)], **scope)
            .where(Message.feedback.isnot(None))
            .group_by(Message.feedback)
        ).all()
        event_day = func.date(MetricEvent.created_at)
        error_total = int(
            session.scalar(
                select(func.count(MetricEvent.id))
                .where(MetricEvent.kind == "error", MetricEvent.created_at >= start)
                .where(*_event_scope(tenant_code, app_uuid))
            )
            or 0
        )
        error_rows = session.execute(
            select(event_day, func.count(MetricEvent.id))
            .where(MetricEvent.kind == "error", MetricEvent.created_at >= start)
            .where(*_event_scope(tenant_code, app_uuid))
            .group_by(event_day)
        ).all()

    roles = {str(role): int(count or 0) for role, count in role_rows}
    feedback = {str(rating): int(count or 0) for rating, count in feedback_rows}
    likes = feedback.get("like", 0)
    dislikes = feedback.get("dislike", 0)
    turns = roles.get("user", 0)

    return {
        "range": {"days": days, "start": labels[0], "end": labels[-1]},
        "conversations": {"total": conversation_total, "series": _fill(labels, conversation_series)},
        "messages": {
            "total": sum(roles.values()),
            "user": turns,
            "assistant": roles.get("assistant", 0),
        },
        "satisfaction": {"like": likes, "dislike": dislikes, "rate": _rate(likes, likes + dislikes)},
        "tokens": {"total": sum(int(count or 0) for _, count in token_rows), "series": _fill(labels, token_rows)},
        "errors": {"total": error_total, "rate": _rate(error_total, turns), "series": _fill(labels, error_rows)},
    }
