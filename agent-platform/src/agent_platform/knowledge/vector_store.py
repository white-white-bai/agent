"""内置向量库：文档落 MySQL（ap_document）；检索流水线 = 粗召回（向量）→ 精召回（混合，RRF）→ 重排序。"""
from __future__ import annotations

import logging
import math
import uuid
from typing import Any

from sqlalchemy import select

from agent_platform.core.config import Settings
from agent_platform.core.db import session_scope
from agent_platform.domain.models import Document
from agent_platform.knowledge.embeddings import Embedder, cosine, tokenize
from agent_platform.knowledge.retrieval import rerank_documents, rrf_merge

logger = logging.getLogger(__name__)


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


def fetch_documents(tenant_code: str, dataset_ids: list[str] | None = None) -> list[Document]:
    with session_scope() as session:
        stmt = select(Document).where(Document.tenant_code == tenant_code, Document.is_deleted == 0)
        if dataset_ids:
            stmt = stmt.where(Document.dataset_id.in_(dataset_ids))
        return list(session.scalars(stmt).all())


def _as_hit(document: Document, score: float) -> dict[str, Any]:
    return {
        "content": document.content,
        "document_name": document.title,
        "dataset_id": document.dataset_id,
        "score": round(score, 6),
    }


def vector_hits(
    documents: list[Document], query_vector: list[float], score_threshold: float | None = None
) -> list[dict[str, Any]]:
    """粗召回：余弦相似度打分（可选阈值过滤），按分降序。"""
    hits: list[dict[str, Any]] = []
    for document in documents:
        score = cosine(query_vector, list(document.embedding or []))
        if score_threshold is not None and score < score_threshold:
            continue
        hits.append(_as_hit(document, score))
    hits.sort(key=lambda item: item["score"], reverse=True)
    return hits


def lexical_hits(documents: list[Document], query: str) -> list[dict[str, Any]]:
    """关键词召回：查询词项在文档中的命中数按文档长度开方归一（BM25 简化版）。"""
    query_tokens = set(tokenize(query))
    if not query_tokens:
        return []
    hits: list[dict[str, Any]] = []
    for document in documents:
        tokens = tokenize(document.content or "")
        if not tokens:
            continue
        overlap = sum(1 for token in tokens if token in query_tokens)
        if overlap <= 0:
            continue
        hits.append(_as_hit(document, overlap / math.sqrt(len(tokens))))
    hits.sort(key=lambda item: item["score"], reverse=True)
    return hits


def search_documents(
    *,
    tenant_code: str,
    query_vector: list[float],
    dataset_ids: list[str] | None = None,
    top_k: int = 5,
    score_threshold: float | None = None,
) -> list[dict[str, Any]]:
    """纯向量检索（默认路径，关闭混合/重排时行为与改造前一致）。"""
    return vector_hits(fetch_documents(tenant_code, dataset_ids), query_vector, score_threshold)[:top_k]


async def retrieve_hits(
    *,
    documents: list[Document],
    query: str,
    query_vector: list[float],
    top_k: int,
    score_threshold: float | None,
    coarse_top_k: int = 0,
    hybrid: bool = False,
    lexical_top_k: int = 0,
    rrf_k: int = 60,
    rerank: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """粗召回 →（可选）混合精召回 →（可选）重排序 → 取 top_k。

    重排序失败只记日志并回退，不阻断检索。
    """
    recall_k = coarse_top_k if coarse_top_k > 0 else top_k
    candidates = vector_hits(documents, query_vector, score_threshold)[:recall_k]
    if hybrid:
        lexical = lexical_hits(documents, query)[: lexical_top_k if lexical_top_k > 0 else recall_k]
        candidates = rrf_merge(candidates, lexical, k=rrf_k)
    if rerank and candidates:
        top_n = int(rerank.get("top_k") or 0) or top_k
        try:
            candidates = await rerank_documents(
                query,
                candidates,
                base_url=str(rerank.get("base_url") or ""),
                api_key=str(rerank.get("api_key") or ""),
                model=str(rerank.get("model") or ""),
                top_n=top_n,
            )
        except Exception:
            logger.warning("重排序调用失败，回退到未重排结果", exc_info=True)
    return candidates[:top_k]


def _pick(node_value: Any, global_value: Any) -> Any:
    return global_value if node_value is None else node_value


def _rerank_options(settings: Settings, node_flag: bool | None) -> dict[str, Any] | None:
    enabled = settings.rerank_enabled if node_flag is None else bool(node_flag)
    if not enabled or not settings.rerank_base_url:
        return None
    return {
        "base_url": settings.rerank_base_url,
        "api_key": settings.rerank_api_key,
        "model": settings.rerank_model,
        "top_k": settings.rerank_top_k,
    }


def build_builtin_searcher(settings: Settings):
    embedder = Embedder(settings)

    async def search(
        *,
        tenant_code: str,
        query: str,
        dataset_ids: list[str],
        top_k: int,
        score_threshold: float | None,
        coarse_top_k: int | None = None,
        hybrid: bool | None = None,
        rerank: bool | None = None,
    ) -> list[dict[str, Any]]:
        documents = fetch_documents(tenant_code, dataset_ids)
        query_vector = await embedder.encode(query)
        return await retrieve_hits(
            documents=documents,
            query=query,
            query_vector=query_vector,
            top_k=top_k,
            score_threshold=score_threshold,
            coarse_top_k=int(_pick(coarse_top_k, settings.retrieval_coarse_top_k) or 0),
            hybrid=bool(_pick(hybrid, settings.retrieval_hybrid_enabled)),
            lexical_top_k=settings.retrieval_lexical_top_k,
            rrf_k=settings.retrieval_rrf_k,
            rerank=_rerank_options(settings, rerank),
        )

    return search
