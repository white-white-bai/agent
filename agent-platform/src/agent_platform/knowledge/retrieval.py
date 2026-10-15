"""检索流水线的纯逻辑：RRF 融合与重排序调用（向量/关键词召回在 vector_store 里）。"""
from __future__ import annotations

from typing import Any

import httpx

Hit = dict[str, Any]


def _key(item: Hit) -> tuple[str, str]:
    return (str(item.get("document_name", "")), str(item.get("content", "")))


def rrf_merge(*rankings: list[Hit], k: int = 60) -> list[Hit]:
    """按 RRF（Reciprocal Rank Fusion）融合多路召回结果。

    同一条目（文档名 + 内容）合并；`score` 保留各路里的最高原始分，排序用融合分。
    """
    fused: dict[tuple[str, str], Hit] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            entry = fused.get(_key(item))
            if entry is None:
                entry = dict(item)
                entry["_fused"] = 0.0
                fused[_key(item)] = entry
            entry["_fused"] = float(entry["_fused"]) + 1.0 / (k + rank + 1)
            if (item.get("score") or 0.0) > (entry.get("score") or 0.0):
                entry["score"] = item.get("score")
    ordered = sorted(fused.values(), key=lambda item: float(item["_fused"]), reverse=True)
    for item in ordered:
        item.pop("_fused", None)
    return ordered


async def rerank_documents(
    query: str,
    documents: list[Hit],
    *,
    base_url: str,
    api_key: str = "",
    model: str = "",
    top_n: int = 0,
    timeout: float = 20.0,
) -> list[Hit]:
    """调 `{base_url}/rerank` 重排序。

    请求 `{model, query, documents, top_n}`，响应 `{results: [{index, relevance_score}]}`。
    """
    if not base_url or not documents:
        return documents
    payload: dict[str, Any] = {
        "model": model or "rerank",
        "query": query,
        "documents": [str(item.get("content", "")) for item in documents],
    }
    if top_n > 0:
        payload["top_n"] = top_n
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(f"{base_url.rstrip('/')}/rerank", json=payload, headers=headers)
    response.raise_for_status()
    results = (response.json() or {}).get("results") or []
    reranked: list[Hit] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if not isinstance(index, int) or not (0 <= index < len(documents)):
            continue
        entry = dict(documents[index])
        score = item.get("relevance_score", item.get("score"))
        if score is not None:
            try:
                entry["score"] = round(float(score), 6)
            except (TypeError, ValueError):
                pass
        reranked.append(entry)
    if not reranked:
        return documents
    return reranked[:top_n] if top_n > 0 else reranked
