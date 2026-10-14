"""内置向量库：文档落 MySQL（ap_document），检索用余弦相似度（纯 Python）。"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from agent_platform.core.config import Settings
from agent_platform.core.db import session_scope
from agent_platform.domain.models import Document
from agent_platform.knowledge.embeddings import Embedder, cosine


def add_document(
    *,
    tenant_code: str,
    dataset_id: str,
    title: str,
    content: str,
    embedding: list[float],
    metadata: dict[str, Any] | None = None,
) -> Document:
    with session_scope() as session:
        document = Document(
            uuid=uuid.uuid4().hex,
            tenant_code=tenant_code,
            dataset_id=dataset_id,
            title=title,
            content=content,
            embedding=embedding,
            doc_metadata=metadata or {},
        )
        session.add(document)
        session.flush()
        return document


def list_documents(tenant_code: str, dataset_id: str = "") -> list[Document]:
    with session_scope() as session:
        stmt = select(Document).where(Document.tenant_code == tenant_code, Document.is_deleted == 0)
        if dataset_id:
            stmt = stmt.where(Document.dataset_id == dataset_id)
        return list(session.scalars(stmt.order_by(Document.id.desc())).all())


def delete_document(uuid_value: str) -> bool:
    with session_scope() as session:
        document = session.scalar(select(Document).where(Document.uuid == uuid_value, Document.is_deleted == 0))
        if document is None:
            return False
        document.is_deleted = 1
        return True


def search_documents(
    *,
    tenant_code: str,
    query_vector: list[float],
    dataset_ids: list[str] | None = None,
    top_k: int = 5,
    score_threshold: float | None = None,
) -> list[dict[str, Any]]:
    with session_scope() as session:
        stmt = select(Document).where(Document.tenant_code == tenant_code, Document.is_deleted == 0)
        if dataset_ids:
            stmt = stmt.where(Document.dataset_id.in_(dataset_ids))
        documents = list(session.scalars(stmt).all())

    scored: list[dict[str, Any]] = []
    for document in documents:
        score = cosine(query_vector, list(document.embedding or []))
        if score_threshold is not None and score < score_threshold:
            continue
        scored.append(
            {
                "content": document.content,
                "document_name": document.title,
                "dataset_id": document.dataset_id,
                "score": round(score, 6),
            }
        )
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:top_k]


def build_builtin_searcher(settings: Settings):
    embedder = Embedder(settings)

    async def search(
        *, tenant_code: str, query: str, dataset_ids: list[str], top_k: int, score_threshold: float | None
    ) -> list[dict[str, Any]]:
        vector = await embedder.encode(query)
        return search_documents(
            tenant_code=tenant_code,
            query_vector=vector,
            dataset_ids=dataset_ids,
            top_k=top_k,
            score_threshold=score_threshold,
        )

    return search
