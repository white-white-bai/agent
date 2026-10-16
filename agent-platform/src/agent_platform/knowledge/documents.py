"""知识库文档与分段读写：ap_document（元数据）+ ap_document_segment（分段）。"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, func, select

from agent_platform.core.db import session_scope
from agent_platform.domain.models import Document, DocumentSegment

# --------------------------------------------------------------------------- 文档


def create_document(
    *,
    tenant_code: str,
    dataset_id: str,
    name: str,
    content: str = "",
    file_type: str = "",
    file_size: int = 0,
    char_count: int = 0,
    chunk_count: int = 0,
    status: str = "ready",
    metadata: dict[str, Any] | None = None,
    created_by: str = "",
    uuid_value: str = "",
) -> Document:
    with session_scope() as session:
        row = Document(
            uuid=uuid_value or uuid.uuid4().hex,
            tenant_code=tenant_code,
            dataset_id=dataset_id,
            name=name,
            content=content,
            file_type=file_type,
            file_size=file_size,
            char_count=char_count,
            chunk_count=chunk_count,
            status=status,
            doc_metadata=metadata or {},
            created_by=created_by,
        )
        session.add(row)
        session.flush()
        return row


def get_document(uuid_value: str, tenant_code: str = "") -> Document | None:
    with session_scope() as session:
        return _get_document(session, uuid_value, tenant_code)


def _get_document(session: Any, uuid_value: str, tenant_code: str = "") -> Document | None:
    stmt = select(Document).where(Document.uuid == uuid_value, Document.is_deleted == 0)
    if tenant_code:
        stmt = stmt.where(Document.tenant_code == tenant_code)
    return session.scalar(stmt)


def list_documents(
    tenant_code: str, dataset_id: str = "", page: int = 1, size: int = 20
) -> tuple[list[Document], int]:
    size = max(size, 1)
    page = max(page, 1)
    with session_scope() as session:
        conditions = [Document.tenant_code == tenant_code, Document.is_deleted == 0]
        if dataset_id:
            conditions.append(Document.dataset_id == dataset_id)
        total = session.scalar(select(func.count(Document.id)).where(*conditions)) or 0
        stmt = (
            select(Document)
            .where(*conditions)
            .order_by(Document.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        return list(session.scalars(stmt).all()), int(total)


def update_document(
    uuid_value: str,
    *,
    name: str | None = None,
    status: str | None = None,
    error: str | None = None,
    char_count: int | None = None,
    chunk_count: int | None = None,
    metadata: dict[str, Any] | None = None,
    tenant_code: str = "",
) -> Document | None:
    with session_scope() as session:
        row = _get_document(session, uuid_value, tenant_code)
        if row is None:
            return None
        if name is not None:
            row.name = name
        if status is not None:
            row.status = status
        if error is not None:
            row.error = error
        if char_count is not None:
            row.char_count = char_count
        if chunk_count is not None:
            row.chunk_count = chunk_count
        if metadata is not None:
            row.doc_metadata = metadata
        session.flush()
        return row


def delete_document(uuid_value: str, tenant_code: str = "") -> bool:
    """软删文档并物理删除其分段。"""
    with session_scope() as session:
        row = _get_document(session, uuid_value, tenant_code)
        if row is None:
            return False
        row.is_deleted = 1
        session.execute(delete(DocumentSegment).where(DocumentSegment.document_uuid == uuid_value))
        return True


def replace_segments(document_uuid: str, segments: list[dict[str, Any]]) -> list[DocumentSegment]:
    """重建某文档的全部分段（重传入库用）：先清空再批量写入。"""
    with session_scope() as session:
        document = session.scalar(select(Document).where(Document.uuid == document_uuid))
        if document is None:
            return []
        session.execute(delete(DocumentSegment).where(DocumentSegment.document_uuid == document_uuid))
        rows: list[DocumentSegment] = []
        for index, item in enumerate(segments):
            row = DocumentSegment(
                uuid=uuid.uuid4().hex,
                tenant_code=document.tenant_code,
                dataset_id=document.dataset_id,
                document_uuid=document_uuid,
                position=int(item.get("position", index)),
                content=item.get("content", ""),
                embedding=item.get("embedding") or [],
            )
            session.add(row)
            rows.append(row)
        session.flush()
        return rows


# --------------------------------------------------------------------------- 分段


def add_segment(
    *,
    tenant_code: str,
    dataset_id: str,
    document_uuid: str,
    content: str,
    embedding: list[float],
    position: int = 0,
    enabled: int = 1,
) -> DocumentSegment:
    with session_scope() as session:
        row = DocumentSegment(
            uuid=uuid.uuid4().hex,
            tenant_code=tenant_code,
            dataset_id=dataset_id,
            document_uuid=document_uuid,
            position=position,
            content=content,
            embedding=embedding,
            enabled=enabled,
        )
        session.add(row)
        session.flush()
        return row


def list_segments(
    document_uuid: str, tenant_code: str = "", page: int = 1, size: int = 100
) -> tuple[list[DocumentSegment], int]:
    size = max(size, 1)
    page = max(page, 1)
    with session_scope() as session:
        conditions = [DocumentSegment.document_uuid == document_uuid]
        if tenant_code:
            conditions.append(DocumentSegment.tenant_code == tenant_code)
        total = session.scalar(select(func.count(DocumentSegment.id)).where(*conditions)) or 0
        stmt = (
            select(DocumentSegment)
            .where(*conditions)
            .order_by(DocumentSegment.position, DocumentSegment.id)
            .offset((page - 1) * size)
            .limit(size)
        )
        return list(session.scalars(stmt).all()), int(total)


def get_segment(uuid_value: str, tenant_code: str = "") -> DocumentSegment | None:
    with session_scope() as session:
        return _get_segment(session, uuid_value, tenant_code)


def _get_segment(session: Any, uuid_value: str, tenant_code: str = "") -> DocumentSegment | None:
    stmt = select(DocumentSegment).where(DocumentSegment.uuid == uuid_value)
    if tenant_code:
        stmt = stmt.where(DocumentSegment.tenant_code == tenant_code)
    return session.scalar(stmt)


def update_segment(
    uuid_value: str,
    *,
    content: str | None = None,
    embedding: list[float] | None = None,
    enabled: int | None = None,
    tenant_code: str = "",
) -> DocumentSegment | None:
    with session_scope() as session:
        row = _get_segment(session, uuid_value, tenant_code)
        if row is None:
            return None
        if content is not None:
            row.content = content
        if embedding is not None:
            row.embedding = embedding
        if enabled is not None:
            row.enabled = enabled
        session.flush()
        return row


def delete_segment(uuid_value: str, tenant_code: str = "") -> bool:
    with session_scope() as session:
        row = _get_segment(session, uuid_value, tenant_code)
        if row is None:
            return False
        session.delete(row)
        return True


def count_segments(document_uuid: str) -> int:
    with session_scope() as session:
        return int(
            session.scalar(
                select(func.count(DocumentSegment.id)).where(DocumentSegment.document_uuid == document_uuid)
            )
            or 0
        )
