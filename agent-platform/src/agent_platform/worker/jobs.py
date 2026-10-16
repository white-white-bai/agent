"""异步任务处理器：知识入库 / 工作流批处理 / 报告生成。"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select

from agent_platform.api import services
from agent_platform.core.config import get_settings
from agent_platform.core.db import session_scope
from agent_platform.domain.models import Conversation, Message
from agent_platform.engine.factory import build_engine_context
from agent_platform.engine.runtime import run_graph
from agent_platform.knowledge.ingest import ingest_document


async def knowledge_ingest(payload: dict[str, Any]) -> dict[str, Any]:
    """按 document_uuid 重建分段（入库 / 重传）。"""
    document_uuid = payload.get("document_uuid", "")
    if not document_uuid:
        raise RuntimeError("知识入库缺少 document_uuid")
    return await ingest_document(document_uuid)


async def graph_batch_run(payload: dict[str, Any]) -> dict[str, Any]:
    app = services.get_app_by_app_id(payload.get("app_id", ""))
    if app is None:
        raise RuntimeError(f"应用不存在: {payload.get('app_id')}")
    graph_def = services.get_published_graph(app.uuid)
    if graph_def is None:
        raise RuntimeError("应用未发布图定义")
    ctx = build_engine_context(get_settings(), tenant_code=app.tenant_code)
    state = await run_graph(graph_def, payload.get("inputs", {}), ctx)
    return {"answer": state.get("answer", ""), "variables": state.get("variables", {})}


async def report_generate(payload: dict[str, Any]) -> dict[str, Any]:
    tenant_code = payload.get("tenant_code", "")
    with session_scope() as session:
        conversations = session.scalar(
            select(func.count(Conversation.id)).where(Conversation.tenant_code == tenant_code)
        )
        messages = session.scalar(
            select(func.count(Message.id))
            .join(Conversation, Conversation.uuid == Message.conversation_uuid)
            .where(Conversation.tenant_code == tenant_code)
        )
        tokens = session.scalar(
            select(func.coalesce(func.sum(Message.tokens), 0))
            .join(Conversation, Conversation.uuid == Message.conversation_uuid)
            .where(Conversation.tenant_code == tenant_code)
        )
    return {
        "report_id": uuid.uuid4().hex,
        "tenant_code": tenant_code,
        "conversations": conversations or 0,
        "messages": messages or 0,
        "tokens": tokens or 0,
    }


HANDLERS = {
    "knowledge_ingest": knowledge_ingest,
    "graph_batch_run": graph_batch_run,
    "report_generate": report_generate,
}


async def handle_job(job: dict[str, Any]) -> Any:
    handler = HANDLERS.get(job.get("type", ""))
    if handler is None:
        raise RuntimeError(f"未知任务类型: {job.get('type')}")
    return await handler(job.get("payload") or {})
