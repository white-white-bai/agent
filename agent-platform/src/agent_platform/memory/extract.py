"""用户记忆抽取：按水位线增量读取会话，模型抽取 JSON 事实并落库。"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from sqlalchemy import func, select

from agent_platform.core.db import session_scope
from agent_platform.domain.models import Conversation, Message
from agent_platform.knowledge.embeddings import Embedder
from agent_platform.memory import store
from agent_platform.models.factory import build_llm_invoker

logger = logging.getLogger(__name__)

MEMORY_KINDS = {"fact", "preference", "episode"}
MEMORY_SYSTEM_PROMPT = (
    "你是用户长期记忆抽取器。从给定对话中抽取稳定的用户事实、偏好与长期目标；"
    "忽略一次性寒暄、临时数字与无法验证的推测。只输出 JSON 数组，每项格式："
    '{"kind": "fact|preference|episode", "content": "简洁中文陈述", "importance": 0.0}。'
    "没有可抽取内容时只输出 []，不要输出任何解释。"
)
_JSON_ARRAY = re.compile(r"\[.*\]", re.DOTALL)
_MAX_ITEMS = 20
_background_tasks: set[asyncio.Task] = set()


def _pending_messages(
    tenant_code: str,
    app_uuid: str,
    user_key: str,
    watermark: int,
) -> list[Message]:
    with session_scope() as session:
        stmt = (
            select(Message)
            .join(Conversation, Conversation.uuid == Message.conversation_uuid)
            .where(
                Conversation.tenant_code == tenant_code,
                func.trim(Conversation.user_name) == user_key,
                Message.id > watermark,
            )
        )
        if app_uuid:
            stmt = stmt.where(Conversation.app_uuid == app_uuid)
        return list(session.scalars(stmt.order_by(Message.id.asc())).all())


def _render_rows(rows: list[Message], max_chars: int) -> tuple[str, int]:
    lines: list[str] = []
    used = 0
    last_id = 0
    for row in rows:
        text = (row.answer if row.role == "assistant" else row.query) or ""
        if not text:
            last_id = row.id
            continue
        line = f"{row.role}: {text}"
        if lines and used + len(line) > max_chars:
            break
        lines.append(line)
        used += len(line)
        last_id = row.id
    return "\n".join(lines), last_id


def _parse_memories(raw: str) -> list[dict[str, Any]] | None:
    match = _JSON_ARRAY.search(raw or "")
    if match is None:
        return None
    try:
        payload = json.loads(match.group(0))
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, list):
        return None
    result: list[dict[str, Any]] = []
    for item in payload[:_MAX_ITEMS]:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        kind = str(item.get("kind") or "fact").strip().lower()
        if kind not in MEMORY_KINDS:
            kind = "fact"
        try:
            importance = float(item.get("importance", 0.5))
        except (TypeError, ValueError):
            importance = 0.5
        result.append({"kind": kind, "content": content, "importance": importance})
    return result


async def extract_user_memory(
    settings: Any,
    *,
    tenant_code: str,
    app_uuid: str,
    user_key: str,
    conversation_uuid: str = "",
    llm: Any = None,
) -> dict[str, Any]:
    normalized = store.normalize_user_key(user_key)
    if not normalized:
        return {"created": 0, "reason": "empty_user"}
    store_app_uuid = "" if str(getattr(settings, "user_memory_scope", "app")) == "tenant" else app_uuid
    state = store.get_state(tenant_code, normalized, store_app_uuid)
    watermark = int(getattr(state, "last_message_id", 0) or 0)
    query_app_uuid = "" if store_app_uuid == "" else app_uuid
    rows = await asyncio.to_thread(_pending_messages, tenant_code, query_app_uuid, normalized, watermark)
    if not rows:
        return {"created": 0, "reason": "no_messages"}
    body, last_id = _render_rows(rows, max(int(getattr(settings, "user_memory_max_chars", 4000) or 0), 1))
    if not body:
        store.advance_state(tenant_code, normalized, store_app_uuid, last_id)
        return {"created": 0, "reason": "empty_body"}
    invoker = llm or build_llm_invoker(settings)
    try:
        raw = await invoker(
            provider=str(getattr(settings, "user_memory_provider", "") or ""),
            system_prompt=MEMORY_SYSTEM_PROMPT,
            user_prompt=body,
            temperature=0.2,
            max_tokens=None,
        )
    except Exception as exc:  # noqa: BLE001 - 抽取失败不推进水位线
        logger.warning("用户记忆抽取模型调用失败：%s", exc)
        return {"created": 0, "reason": "llm_error"}
    if not str(raw or "").strip():
        return {"created": 0, "reason": "empty_reply"}
    items = _parse_memories(str(raw or ""))
    if items is None:
        return {"created": 0, "reason": "parse_error"}
    if not items:
        store.advance_state(tenant_code, normalized, store_app_uuid, last_id)
        return {"created": 0, "reason": "no_items", "watermark": last_id}

    embedder = Embedder(settings)
    embedding_model = store.embedding_model_name(settings)
    source_conversation = conversation_uuid or (rows[-1].conversation_uuid if rows else "")
    created = 0
    for item in items:
        try:
            embedding = await embedder.encode(item["content"])
            store.upsert_memory(
                tenant_code=tenant_code,
                app_uuid=store_app_uuid,
                user_key=normalized,
                user_name=normalized,
                kind=item["kind"],
                content=item["content"],
                importance=item["importance"],
                embedding=embedding,
                embedding_model=embedding_model,
                source_conversation_id=source_conversation,
                source_message_id=str(last_id),
                settings=settings,
            )
            created += 1
        except Exception as exc:  # noqa: BLE001 - 单条失败不阻断其它条目
            logger.warning("用户记忆写入失败：%s", exc)
    store.enforce_limits(settings, tenant_code, normalized, store_app_uuid)
    store.advance_state(tenant_code, normalized, store_app_uuid, last_id)
    return {"created": created, "watermark": last_id, "items": len(items)}


async def _run_extract(settings: Any, payload: dict[str, Any], llm: Any = None) -> None:
    try:
        await extract_user_memory(settings, llm=llm, **payload)
    except Exception:
        logger.warning("用户记忆后台抽取失败", exc_info=True)


def _on_done(task: asyncio.Task) -> None:
    _background_tasks.discard(task)


async def dispatch_extract(
    settings: Any,
    *,
    tenant_code: str,
    app_uuid: str,
    user_key: str,
    conversation_uuid: str = "",
    llm: Any = None,
) -> str:
    payload = {
        "tenant_code": tenant_code,
        "app_uuid": app_uuid,
        "user_key": user_key,
        "conversation_uuid": conversation_uuid,
    }
    if not bool(getattr(settings, "user_memory_extract_async", True)):
        await extract_user_memory(settings, llm=llm, **payload)
        return "sync"
    from agent_platform.core.redis import get_redis

    if get_redis() is not None:
        from agent_platform.worker.queue import enqueue

        enqueue("user_memory_extract", payload)
        return "queued"
    task = asyncio.create_task(_run_extract(settings, payload, llm))
    _background_tasks.add(task)
    task.add_done_callback(_on_done)
    return "scheduled"
