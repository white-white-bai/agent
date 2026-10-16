"""知识库（数据集）读写：ap_dataset 与文档/分段的级联。"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select

from agent_platform.core.db import session_scope
from agent_platform.domain.models import Dataset, Document, DocumentSegment


def list_datasets(tenant_code: str) -> list[Dataset]:
    with session_scope() as session:
        stmt = select(Dataset).where(Dataset.tenant_code == tenant_code, Dataset.is_deleted == 0)
        return list(session.scalars(stmt.order_by(Dataset.id.desc())).all())


def get_dataset(uuid_value: str, tenant_code: str = "") -> Dataset | None:
    with session_scope() as session:
        return _get(session, uuid_value, tenant_code)


def _get(session: Any, uuid_value: str, tenant_code: str = "") -> Dataset | None:
    stmt = select(Dataset).where(Dataset.uuid == uuid_value, Dataset.is_deleted == 0)
    if tenant_code:
        stmt = stmt.where(Dataset.tenant_code == tenant_code)
    return session.scalar(stmt)


def create_dataset(
    *,
    tenant_code: str,
    name: str,
    description: str = "",
    retrieval: dict[str, Any] | None = None,
    embedding_model: str = "",
    index_method: str = "high_quality",
    chunk_config: dict[str, Any] | None = None,
    uuid_value: str = "",
) -> Dataset:
    with session_scope() as session:
        row = Dataset(
            uuid=uuid_value or uuid.uuid4().hex,
            tenant_code=tenant_code,
            name=name,
            description=description,
            embedding_model=embedding_model,
            index_method=index_method or "high_quality",
            chunk_config=chunk_config or {},
            retrieval=retrieval or {},
        )
        session.add(row)
        session.flush()
        return row


def update_dataset(
    uuid_value: str,
    *,
    name: str | None = None,
    description: str | None = None,
    retrieval: dict[str, Any] | None = None,
    embedding_model: str | None = None,
    index_method: str | None = None,
    chunk_config: dict[str, Any] | None = None,
    tenant_code: str = "",
) -> Dataset | None:
    with session_scope() as session:
        row = _get(session, uuid_value, tenant_code)
        if row is None:
            return None
        if name is not None:
            row.name = name
        if description is not None:
            row.description = description
        if retrieval is not None:
            row.retrieval = retrieval
        if embedding_model is not None:
            row.embedding_model = embedding_model
        if index_method is not None:
            row.index_method = index_method
        if chunk_config is not None:
            row.chunk_config = chunk_config
        session.flush()
        return row


def delete_dataset(uuid_value: str, tenant_code: str = "") -> bool:
    """软删知识库：同时级联软删其文档并物理删除分段（检索因此不再命中）。"""
    with session_scope() as session:
        row = _get(session, uuid_value, tenant_code)
        if row is None:
            return False
        row.is_deleted = 1
        for document in session.scalars(
            select(Document).where(Document.dataset_id == uuid_value, Document.is_deleted == 0)
        ):
            document.is_deleted = 1
        for segment in session.scalars(select(DocumentSegment).where(DocumentSegment.dataset_id == uuid_value)):
            session.delete(segment)
        return True


def document_counts(tenant_code: str, dataset_ids: list[str]) -> dict[str, int]:
    """按知识库统计未删文档数（供列表展示）。"""
    if not dataset_ids:
        return {}
    with session_scope() as session:
        stmt = (
            select(Document.dataset_id, func.count(Document.id))
            .where(
                Document.tenant_code == tenant_code,
                Document.is_deleted == 0,
                Document.dataset_id.in_(dataset_ids),
            )
            .group_by(Document.dataset_id)
        )
        return {dataset_id: count for dataset_id, count in session.execute(stmt).all()}
