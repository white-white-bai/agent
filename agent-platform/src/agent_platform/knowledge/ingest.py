"""知识库文档入库：分块 → 向量化 → 落分段，支持同步与异步入库。

异步派发：Redis 可用则入 worker 队列；否则在 API 进程内起 asyncio 任务
（compose 默认未启用 Redis，进程内队列无法被独立 worker 消费）。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from agent_platform.core.config import get_settings
from agent_platform.core.redis import get_redis
from agent_platform.knowledge import datasets as datasets_mod
from agent_platform.knowledge import documents as documents_mod
from agent_platform.knowledge.chunking import chunk_document, normalize_config
from agent_platform.knowledge.embeddings import Embedder

logger = logging.getLogger(__name__)

# 持有后台任务引用，避免被 GC 提前回收
_background_tasks: set[asyncio.Task] = set()


def resolve_chunk_config(document: Any, dataset: Any) -> dict[str, Any]:
    """分段配置优先级：文档覆盖 > 知识库默认 > 全局设置。"""
    if document is not None and getattr(document, "chunk_config", None):
        return normalize_config(document.chunk_config)
    if dataset is not None and getattr(dataset, "chunk_config", None):
        return normalize_config(dataset.chunk_config)
    settings = get_settings()
    return normalize_config(
        {"max_chars": settings.document_chunk_chars, "overlap_chars": settings.document_chunk_overlap}
    )


async def ingest_document(document_uuid: str) -> dict[str, Any]:
    """按文档 uuid 重建分段：取配置 → 清洗分块 →（可选）向量化 → 写分段 → 回填状态。

    `index_method == 'economy'` 的知识库不生成向量（分段 embedding 为空，仅关键词可召回）。
    """
    settings = get_settings()
    document = documents_mod.get_document(document_uuid)
    if document is None:
        raise RuntimeError(f"文档不存在: {document_uuid}")
    dataset = datasets_mod.get_dataset(document.dataset_id) if document.dataset_id else None
    text = document.content or ""
    try:
        config = resolve_chunk_config(document, dataset)
        chunks = chunk_document(text, config)
        embedder = None if (dataset is not None and dataset.index_method == "economy") else Embedder(settings)
        segments = []
        for index, chunk in enumerate(chunks):
            embedding = [] if embedder is None else await embedder.encode(chunk)
            segments.append({"position": index, "content": chunk, "embedding": embedding})
        documents_mod.replace_segments(document_uuid, segments)
        documents_mod.update_document(
            document_uuid, status="ready", error="", char_count=len(text), chunk_count=len(segments)
        )
        return {"document_uuid": document_uuid, "chunks": len(segments)}
    except Exception as exc:
        logger.warning("文档入库失败: %s", document_uuid, exc_info=True)
        documents_mod.update_document(document_uuid, status="failed", error=str(exc)[:500])
        raise


def dispatch_ingest(document_uuid: str) -> str:
    """异步入库：返回 'queued'（worker）或 'scheduled'（进程内后台任务）。"""
    if get_redis() is not None:
        from agent_platform.worker.queue import enqueue

        enqueue("knowledge_ingest", {"document_uuid": document_uuid})
        return "queued"
    task = asyncio.create_task(ingest_document(document_uuid))
    _background_tasks.add(task)
    task.add_done_callback(_on_done)
    return "scheduled"


def _on_done(task: asyncio.Task) -> None:
    _background_tasks.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.warning("后台入库任务异常: %s", task.exception())
