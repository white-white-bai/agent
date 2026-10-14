"""检索适配器：内置向量库 + 外接（知流 / LightRAG / 知识图谱）。"""
from __future__ import annotations

from typing import Any

import httpx

from agent_platform.core.config import Settings
from agent_platform.engine.context import Retriever
from agent_platform.graph.schema import KnowledgeConfig
from agent_platform.knowledge.vector_store import build_builtin_searcher


async def _http_retrieve(
    base_url: str,
    api_key: str,
    query: str,
    top_k: int,
    dataset_ids: list[str] | None = None,
    timeout: float = 20.0,
) -> list[dict[str, Any]]:
    if not base_url:
        raise RuntimeError("知识平台 base_url 未配置")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    payload: dict[str, Any] = {"query": query, "top_k": top_k}
    if dataset_ids:
        payload["dataset_ids"] = dataset_ids
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(f"{base_url.rstrip('/')}/query", json=payload, headers=headers)
    response.raise_for_status()
    data = response.json()
    items = data.get("data") if isinstance(data, dict) else data
    return items or []


def build_retriever(settings: Settings) -> Retriever:
    builtin_search = build_builtin_searcher(settings)

    async def retrieve(config: KnowledgeConfig, query: str, tenant_code: str = "") -> list[dict[str, Any]]:
        if config.retriever == "builtin":
            return await builtin_search(
                tenant_code=tenant_code,
                query=query,
                dataset_ids=config.dataset_ids,
                top_k=config.top_k,
                score_threshold=config.score_threshold,
            )
        if config.retriever == "light_rag":
            return await _http_retrieve(
                settings.light_rag_base_url, settings.light_rag_api_key, query, config.top_k, config.dataset_ids
            )
        if config.retriever == "knowflow":
            return await _http_retrieve(
                settings.knowflow_base_url, "", query, config.top_k, config.dataset_ids
            )
        if config.retriever == "knowledge_graph":
            return await _http_retrieve(
                settings.knowledge_graph_base_url, "", query, config.top_k, config.dataset_ids
            )
        raise RuntimeError(f"未知检索器类型: {config.retriever}")

    return retrieve
