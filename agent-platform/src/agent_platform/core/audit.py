"""工具调用审计：默认关闭；审计写入失败不能影响工具执行。"""
from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import func, select

from agent_platform.core.db import session_scope
from agent_platform.domain.models import ToolAuditLog

logger = logging.getLogger(__name__)


@asynccontextmanager
async def audit_tool_call(
    settings: Any,
    *,
    tenant_code: str = "",
    tool_name: str,
    server: str = "",
    args: dict[str, Any] | None = None,
) -> AsyncIterator[None]:
    if not getattr(settings, "tool_audit_enabled", False):
        yield
        return
    started = time.perf_counter()
    status = "ok"
    error = ""
    try:
        yield
    except Exception as exc:
        status = "error"
        error = str(exc)[:2000]
        raise
    finally:
        duration_ms = int((time.perf_counter() - started) * 1000)
        try:
            encoded = json.loads(json.dumps(args or {}, ensure_ascii=False, default=str))
            with session_scope() as session:
                session.add(
                    ToolAuditLog(
                        uuid=uuid.uuid4().hex,
                        tenant_code=tenant_code,
                        tool_name=tool_name,
                        server=server,
                        args=encoded,
                        status=status,
                        error=error,
                        duration_ms=duration_ms,
                    )
                )
        except Exception:
            logger.warning("工具审计写入失败：%s", tool_name, exc_info=True)


def list_tool_audits(
    tenant_code: str = "",
    *,
    tool_name: str = "",
    status: str = "",
    page: int = 1,
    size: int = 20,
) -> tuple[list[ToolAuditLog], int]:
    page = max(int(page or 1), 1)
    size = min(max(int(size or 20), 1), 200)
    with session_scope() as session:
        stmt = select(ToolAuditLog)
        if tenant_code:
            stmt = stmt.where(ToolAuditLog.tenant_code == tenant_code)
        if tool_name:
            stmt = stmt.where(ToolAuditLog.tool_name == tool_name)
        if status:
            stmt = stmt.where(ToolAuditLog.status == status)
        total = int(session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        rows = list(
            session.scalars(
                stmt.order_by(ToolAuditLog.id.desc()).offset((page - 1) * size).limit(size)
            ).all()
        )
        return rows, total
