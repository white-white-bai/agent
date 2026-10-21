"""用户记忆持久化：CRUD、去重、水位线、上限淘汰。"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, or_, select, update

from agent_platform.core.db import session_scope
from agent_platform.domain.models import UserMemory, UserMemoryState
from agent_platform.knowledge.embeddings import cosine

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_user_key(user: str) -> str:
    return (user or "").strip()


def content_hash(kind: str, content: str) -> str:
    raw = f"{kind or 'fact'}:{(content or '').strip()}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def embedding_model_name(settings: Any) -> str:
    model = str(getattr(settings, "embedding_model", "") or "")
    return model or f"hash:{getattr(settings, 'embedding_dim', 256)}"


def _expires_at(settings: Any, value: datetime | None = None) -> datetime | None:
    if value is not None:
        return value
    days = int(getattr(settings, "user_memory_ttl_days", 0) or 0)
    return _now() + timedelta(days=days) if days > 0 else None


def list_memories(
    tenant_code: str,
    *,
    user_key: str = "",
    app_uuid: str = "",
    query: str = "",
    page: int = 1,
    size: int = 20,
) -> tuple[list[UserMemory], int]:
    page = max(int(page or 1), 1)
    size = min(max(int(size or 20), 1), 200)
    with session_scope() as session:
        stmt = select(UserMemory).where(UserMemory.is_deleted == 0)
        if tenant_code:
            stmt = stmt.where(UserMemory.tenant_code == tenant_code)
        if user_key:
            stmt = stmt.where(UserMemory.user_key == user_key)
        if app_uuid:
            stmt = stmt.where(UserMemory.app_uuid == app_uuid)
        if query:
            stmt = stmt.where(UserMemory.content.contains(query))
        total = int(session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        rows = list(
            session.scalars(
                stmt.order_by(UserMemory.updated_at.desc(), UserMemory.id.desc())
                .offset((page - 1) * size)
                .limit(size)
            ).all()
        )
        return rows, total


def list_memory_users(tenant_code: str, *, app_uuid: str = "", limit: int = 100) -> list[dict[str, Any]]:
    with session_scope() as session:
        stmt = select(
            UserMemory.user_key,
            func.max(UserMemory.user_name),
            func.count(UserMemory.id),
            func.max(UserMemory.updated_at),
        ).where(UserMemory.is_deleted == 0)
        if tenant_code:
            stmt = stmt.where(UserMemory.tenant_code == tenant_code)
        if app_uuid:
            stmt = stmt.where(UserMemory.app_uuid == app_uuid)
        rows = session.execute(
            stmt.group_by(UserMemory.user_key)
            .order_by(func.max(UserMemory.updated_at).desc())
            .limit(max(int(limit or 100), 1))
        ).all()
        return [
            {
                "user_key": user_key,
                "user_name": user_name or user_key,
                "count": int(count or 0),
                "last_updated": last_updated.isoformat() if last_updated else "",
            }
            for user_key, user_name, count, last_updated in rows
        ]


def get_memory(memory_uuid: str, tenant_code: str = "") -> UserMemory | None:
    with session_scope() as session:
        row = session.scalar(
            select(UserMemory).where(UserMemory.uuid == memory_uuid, UserMemory.is_deleted == 0)
        )
    if row is None:
        return None
    if tenant_code and row.tenant_code and row.tenant_code != tenant_code:
        return None
    return row


def create_memory(
    *,
    tenant_code: str,
    app_uuid: str,
    user_key: str,
    user_name: str = "",
    kind: str = "fact",
    content: str = "",
    importance: float = 0.5,
    embedding: list[float] | None = None,
    embedding_model: str = "",
    source_conversation_id: str = "",
    source_message_id: str = "",
    expires_at: datetime | None = None,
    enabled: int = 1,
    settings: Any = None,
) -> UserMemory:
    normalized = normalize_user_key(user_key)
    text = (content or "").strip()
    if not normalized:
        raise ValueError("user_key 不能为空")
    if not text:
        raise ValueError("content 不能为空")
    digest = content_hash(kind, text)
    with session_scope() as session:
        row = UserMemory(
            uuid=uuid.uuid4().hex,
            tenant_code=tenant_code,
            app_uuid=app_uuid,
            user_key=normalized,
            user_name=user_name or normalized,
            kind=kind or "fact",
            content=text,
            embedding=list(embedding or []),
            embedding_model=embedding_model,
            importance=max(0.0, min(float(importance), 1.0)),
            source_conversation_id=source_conversation_id,
            source_message_id=source_message_id,
            content_hash=digest,
            enabled=int(enabled),
            expires_at=_expires_at(settings, expires_at),
        )
        session.add(row)
        session.flush()
        return row


def upsert_memory(
    *,
    tenant_code: str,
    app_uuid: str,
    user_key: str,
    user_name: str = "",
    kind: str = "fact",
    content: str = "",
    importance: float = 0.5,
    embedding: list[float] | None = None,
    embedding_model: str = "",
    source_conversation_id: str = "",
    source_message_id: str = "",
    expires_at: datetime | None = None,
    settings: Any = None,
) -> UserMemory:
    normalized = normalize_user_key(user_key)
    text = (content or "").strip()
    if not normalized:
        raise ValueError("user_key 不能为空")
    if not text:
        raise ValueError("content 不能为空")
    digest = content_hash(kind, text)
    with session_scope() as session:
        row = session.scalar(
            select(UserMemory).where(
                UserMemory.tenant_code == tenant_code,
                UserMemory.user_key == normalized,
                UserMemory.app_uuid == app_uuid,
                UserMemory.content_hash == digest,
            )
        )
        if row is not None:
            row.content = text
            row.user_name = user_name or row.user_name
            row.importance = max(float(row.importance or 0), max(0.0, min(float(importance), 1.0)))
            row.updated_at = _now()
            row.is_deleted = 0
            row.enabled = 1
            if embedding:
                row.embedding = list(embedding)
                row.embedding_model = embedding_model or row.embedding_model
            if expires_at is not None:
                row.expires_at = expires_at
            session.flush()
            return row

        threshold = float(getattr(settings, "user_memory_dedup_threshold", 0) or 0) if settings else 0.0
        if threshold > 0 and embedding:
            limit = int(getattr(settings, "user_memory_max_per_user", 200) or 200)
            candidates = list(
                session.scalars(
                    select(UserMemory)
                    .where(
                        UserMemory.tenant_code == tenant_code,
                        UserMemory.user_key == normalized,
                        UserMemory.app_uuid == app_uuid,
                        UserMemory.is_deleted == 0,
                        UserMemory.kind == (kind or "fact"),
                    )
                    .order_by(UserMemory.id.desc())
                    .limit(max(limit, 1))
                ).all()
            )
            best = None
            best_score = 0.0
            for candidate in candidates:
                if not candidate.embedding:
                    continue
                score = cosine(list(embedding), list(candidate.embedding))
                if score > best_score:
                    best = candidate
                    best_score = score
            if best is not None and best_score >= threshold:
                # 近似重复：保留原内容与唯一键，只提升重要度并刷新向量/来源
                best.importance = max(
                    float(best.importance or 0), max(0.0, min(float(importance), 1.0))
                )
                best.embedding = list(embedding)
                best.embedding_model = embedding_model or best.embedding_model
                best.updated_at = _now()
                best.is_deleted = 0
                best.enabled = 1
                if expires_at is not None:
                    best.expires_at = expires_at
                session.flush()
                return best

        row = UserMemory(
            uuid=uuid.uuid4().hex,
            tenant_code=tenant_code,
            app_uuid=app_uuid,
            user_key=normalized,
            user_name=user_name or normalized,
            kind=kind or "fact",
            content=text,
            embedding=list(embedding or []),
            embedding_model=embedding_model,
            importance=max(0.0, min(float(importance), 1.0)),
            source_conversation_id=source_conversation_id,
            source_message_id=source_message_id,
            content_hash=digest,
            enabled=1,
            expires_at=_expires_at(settings, expires_at),
        )
        session.add(row)
        session.flush()
        return row


def update_memory(
    memory_uuid: str,
    *,
    tenant_code: str = "",
    content: str | None = None,
    kind: str | None = None,
    importance: float | None = None,
    enabled: int | None = None,
    embedding: list[float] | None = None,
    embedding_model: str = "",
    expires_at: datetime | None = None,
) -> UserMemory | None:
    with session_scope() as session:
        row = session.scalar(
            select(UserMemory).where(UserMemory.uuid == memory_uuid, UserMemory.is_deleted == 0)
        )
        if row is None:
            return None
        if tenant_code and row.tenant_code and row.tenant_code != tenant_code:
            return None
        if content is not None:
            text = content.strip()
            if not text:
                raise ValueError("content 不能为空")
            row.content = text
            row.content_hash = content_hash(kind or row.kind, text)
            row.embedding = list(embedding or [])
            row.embedding_model = embedding_model or row.embedding_model
        if kind is not None:
            row.kind = kind
        if importance is not None:
            row.importance = max(0.0, min(float(importance), 1.0))
        if enabled is not None:
            row.enabled = int(enabled)
        if expires_at is not None:
            row.expires_at = expires_at
        session.flush()
        return row


def delete_memory(memory_uuid: str, tenant_code: str = "") -> bool:
    with session_scope() as session:
        row = session.scalar(
            select(UserMemory).where(UserMemory.uuid == memory_uuid, UserMemory.is_deleted == 0)
        )
        if row is None:
            return False
        if tenant_code and row.tenant_code and row.tenant_code != tenant_code:
            return False
        row.is_deleted = 1
        return True


def purge_user(tenant_code: str, user_key: str, app_uuid: str = "") -> int:
    normalized = normalize_user_key(user_key)
    with session_scope() as session:
        stmt = delete(UserMemory).where(
            UserMemory.tenant_code == tenant_code,
            UserMemory.user_key == normalized,
        )
        if app_uuid:
            stmt = stmt.where(UserMemory.app_uuid == app_uuid)
        deleted = session.execute(stmt).rowcount or 0
        state_stmt = delete(UserMemoryState).where(
            UserMemoryState.tenant_code == tenant_code,
            UserMemoryState.user_key == normalized,
        )
        if app_uuid:
            state_stmt = state_stmt.where(UserMemoryState.app_uuid == app_uuid)
        session.execute(state_stmt)
        return int(deleted)


def get_state(tenant_code: str, user_key: str, app_uuid: str) -> UserMemoryState | None:
    with session_scope() as session:
        return session.scalar(
            select(UserMemoryState).where(
                UserMemoryState.tenant_code == tenant_code,
                UserMemoryState.user_key == user_key,
                UserMemoryState.app_uuid == app_uuid,
            )
        )


def advance_state(tenant_code: str, user_key: str, app_uuid: str, last_message_id: int) -> None:
    with session_scope() as session:
        row = session.scalar(
            select(UserMemoryState).where(
                UserMemoryState.tenant_code == tenant_code,
                UserMemoryState.user_key == user_key,
                UserMemoryState.app_uuid == app_uuid,
            )
        )
        if row is None:
            row = UserMemoryState(
                uuid=uuid.uuid4().hex,
                tenant_code=tenant_code,
                user_key=user_key,
                app_uuid=app_uuid,
                last_message_id=0,
            )
            session.add(row)
        row.last_message_id = max(int(row.last_message_id or 0), int(last_message_id))
        row.last_run_at = _now()
        session.flush()


def enforce_limits(settings: Any, tenant_code: str, user_key: str, app_uuid: str) -> int:
    limit = int(getattr(settings, "user_memory_max_per_user", 0) or 0)
    if limit <= 0:
        return 0
    with session_scope() as session:
        rows = list(
            session.scalars(
                select(UserMemory)
                .where(
                    UserMemory.tenant_code == tenant_code,
                    UserMemory.user_key == user_key,
                    UserMemory.app_uuid == app_uuid,
                    UserMemory.is_deleted == 0,
                )
                .order_by(UserMemory.importance.asc(), UserMemory.last_hit_at.asc(), UserMemory.id.asc())
            ).all()
        )
        excess = len(rows) - limit
        for row in rows[: max(excess, 0)]:
            row.is_deleted = 1
        return max(excess, 0)


async def rebuild_embeddings(
    settings: Any,
    tenant_code: str,
    *,
    user_key: str = "",
    app_uuid: str = "",
) -> int:
    """按当前 embedding 模型/维度重建记忆向量（用于换模型后的迁移）。"""
    from agent_platform.knowledge.embeddings import Embedder

    embedder = Embedder(settings)
    model = embedding_model_name(settings)
    updated = 0
    with session_scope() as session:
        stmt = select(UserMemory).where(
            UserMemory.tenant_code == tenant_code,
            UserMemory.is_deleted == 0,
        )
        if user_key:
            stmt = stmt.where(UserMemory.user_key == normalize_user_key(user_key))
        if app_uuid:
            stmt = stmt.where(UserMemory.app_uuid == app_uuid)
        for row in session.scalars(stmt).all():
            try:
                row.embedding = await embedder.encode(row.content or "")
                row.embedding_model = model
                updated += 1
            except Exception:
                logger.warning("用户记忆向量重建失败：%s", row.uuid, exc_info=True)
    return updated


def memory_passages(
    tenant_code: str,
    user_key: str,
    app_uuid: str,
    *,
    scope: str = "app",
    limit: int = 200,
    embedding_model: str = "",
    embedding_dim: int = 0,
) -> list[dict[str, Any]]:
    now = _now()
    with session_scope() as session:
        stmt = select(UserMemory).where(
            UserMemory.tenant_code == tenant_code,
            UserMemory.user_key == user_key,
            UserMemory.is_deleted == 0,
            UserMemory.enabled == 1,
            or_(UserMemory.expires_at.is_(None), UserMemory.expires_at > now),
        )
        if scope == "tenant":
            stmt = stmt.where(or_(UserMemory.app_uuid == app_uuid, UserMemory.app_uuid == ""))
        else:
            stmt = stmt.where(UserMemory.app_uuid == app_uuid)
        if embedding_model:
            # 空 model 视为历史/手工数据，允许参与检索；维度在下面再校验
            stmt = stmt.where(
                or_(UserMemory.embedding_model == embedding_model, UserMemory.embedding_model == "")
            )
        stmt = stmt.order_by(UserMemory.importance.desc(), UserMemory.updated_at.desc())
        rows = list(session.scalars(stmt.limit(max(int(limit or 200), 1))).all())
        if embedding_dim:
            rows = [
                row
                for row in rows
                if row.embedding and len(row.embedding) == embedding_dim
            ]
        return [
            {
                "uuid": row.uuid,
                "content": row.content or "",
                "embedding": list(row.embedding or []),
                "kind": row.kind or "fact",
                "importance": float(row.importance or 0),
                "document_name": row.kind or "fact",
                "dataset_id": "",
                "position": index,
            }
            for index, row in enumerate(rows)
        ]


def touch_hits(memory_uuids: list[str]) -> None:
    if not memory_uuids:
        return
    with session_scope() as session:
        session.execute(
            update(UserMemory)
            .where(UserMemory.uuid.in_(memory_uuids))
            .values(hit_count=UserMemory.hit_count + 1, last_hit_at=_now())
        )
