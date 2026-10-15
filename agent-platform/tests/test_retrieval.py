"""检索流水线：关键词召回、RRF 融合、重排序，以及默认关闭时与纯向量检索等价。"""
from __future__ import annotations

import httpx
import pytest

from agent_platform.core.config import Settings
from agent_platform.graph.schema import KnowledgeConfig
from agent_platform.knowledge import retrieval as retrieval_mod
from agent_platform.knowledge.embeddings import hash_embed
from agent_platform.knowledge.retrieval import rerank_documents, rrf_merge
from agent_platform.knowledge.retrievers import build_retriever
from agent_platform.knowledge.vector_store import (
    add_document,
    build_builtin_searcher,
    fetch_documents,
    lexical_hits,
    search_documents,
)

ZERO = [0.0] * 256
# 在 patch 之前抓住真实类，否则工厂会递归调用自己
_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _fake_client(handler):
    def factory(**kwargs):
        kwargs.pop("transport", None)
        return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler), **kwargs)

    return factory


# --------------------------------------------------------------------------- 纯逻辑


def test_rrf_merge_dedupes_and_keeps_best_score():
    first = [
        {"document_name": "A", "content": "x", "score": 0.9},
        {"document_name": "B", "content": "y", "score": 0.5},
    ]
    second = [
        {"document_name": "B", "content": "y", "score": 3.0},
        {"document_name": "C", "content": "z", "score": 1.0},
    ]
    merged = rrf_merge(first, second, k=60)
    assert [item["document_name"] for item in merged] == ["B", "A", "C"]
    assert merged[0]["score"] == 3.0
    assert all("_fused" not in item for item in merged)


@pytest.mark.asyncio
async def test_rerank_documents_reorders_and_truncates(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.read().decode("utf-8")
        return httpx.Response(
            200,
            json={"results": [{"index": 1, "relevance_score": 0.91}, {"index": 0, "relevance_score": 0.12}]},
        )

    monkeypatch.setattr(retrieval_mod.httpx, "AsyncClient", _fake_client(handler))
    documents = [
        {"content": "甲", "document_name": "A", "score": 0.5},
        {"content": "乙", "document_name": "B", "score": 0.4},
    ]
    result = await rerank_documents("q", documents, base_url="https://rerank.local/", model="m", top_n=2)
    assert captured["url"] == "https://rerank.local/rerank"
    assert '"query":"q"' in captured["body"]
    assert captured["body"].count('"documents"') == 1
    assert [item["document_name"] for item in result] == ["B", "A"]
    assert result[0]["score"] == 0.91


@pytest.mark.asyncio
async def test_rerank_documents_without_base_url_is_passthrough():
    documents = [{"content": "甲", "document_name": "A", "score": 0.5}]
    assert await rerank_documents("q", documents, base_url="") == documents


# --------------------------------------------------------------------------- 召回


def test_lexical_hits_match_keywords_only():
    add_document(tenant_code="t", dataset_id="d1", title="指南", content="常州天气查询办事指南", embedding=ZERO)
    add_document(tenant_code="t", dataset_id="d1", title="其它", content="汽车置换补贴标准", embedding=ZERO)
    documents = fetch_documents("t", ["d1"])
    hits = lexical_hits(documents, "常州天气")
    assert [item["document_name"] for item in hits] == ["指南"]
    assert lexical_hits(documents, "完全无关的东西") == []


# --------------------------------------------------------------------------- 流水线


@pytest.mark.asyncio
async def test_defaults_are_identical_to_pure_vector_search():
    content = "常州天气查询办事指南"
    add_document(tenant_code="t", dataset_id="d1", title="指南", content=content, embedding=hash_embed(content))
    add_document(tenant_code="t", dataset_id="d1", title="其它", content="汽车置换", embedding=hash_embed("汽车置换"))

    searcher = build_builtin_searcher(Settings(embedding_dim=256))
    pipeline = await searcher(tenant_code="t", query=content, dataset_ids=["d1"], top_k=5, score_threshold=None)
    reference = search_documents(
        tenant_code="t", query_vector=hash_embed(content), dataset_ids=["d1"], top_k=5, score_threshold=None
    )
    assert pipeline == reference


@pytest.mark.asyncio
async def test_hybrid_recall_surfaces_keyword_only_hit():
    add_document(tenant_code="t", dataset_id="d1", title="关键词", content="苏超购票专题智能体上线", embedding=ZERO)
    searcher = build_builtin_searcher(
        Settings(embedding_dim=256, retrieval_hybrid_enabled=True, retrieval_coarse_top_k=5, retrieval_lexical_top_k=5)
    )
    vector_only = await searcher(
        tenant_code="t", query="苏超购票", dataset_ids=["d1"], top_k=5, score_threshold=0.5, hybrid=False
    )
    hybrid = await searcher(
        tenant_code="t", query="苏超购票", dataset_ids=["d1"], top_k=5, score_threshold=0.5, hybrid=True
    )
    assert vector_only == []
    assert [item["document_name"] for item in hybrid] == ["关键词"]


@pytest.mark.asyncio
async def test_rerank_reorders_and_falls_back_on_failure(monkeypatch):
    add_document(tenant_code="t", dataset_id="d1", title="A", content="甲", embedding=hash_embed("甲"))
    add_document(tenant_code="t", dataset_id="d1", title="B", content="乙", embedding=hash_embed("乙"))
    searcher = build_builtin_searcher(
        Settings(embedding_dim=256, rerank_enabled=True, rerank_base_url="https://rerank.local", rerank_model="m")
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"results": [{"index": 1, "relevance_score": 9.0}, {"index": 0, "relevance_score": 0.1}]}
        )

    monkeypatch.setattr(retrieval_mod.httpx, "AsyncClient", _fake_client(handler))
    hits = await searcher(tenant_code="t", query="甲", dataset_ids=["d1"], top_k=2, score_threshold=None)
    assert hits[0]["score"] == 9.0

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("rerank down", request=request)

    monkeypatch.setattr(retrieval_mod.httpx, "AsyncClient", _fake_client(boom))
    fallback = await searcher(tenant_code="t", query="甲", dataset_ids=["d1"], top_k=2, score_threshold=None)
    assert fallback and fallback[0]["score"] != 9.0


@pytest.mark.asyncio
async def test_node_level_hybrid_override_beats_global_default():
    add_document(tenant_code="t", dataset_id="d1", title="关键词", content="苏超购票专题", embedding=ZERO)
    retrieve = build_retriever(Settings(embedding_dim=256, retrieval_coarse_top_k=5, retrieval_lexical_top_k=5))

    overridden = KnowledgeConfig(retriever="builtin", dataset_ids=["d1"], top_k=5, score_threshold=0.5, hybrid=True)
    assert [item["document_name"] for item in await retrieve(overridden, "苏超购票", "t")] == ["关键词"]

    default = KnowledgeConfig(retriever="builtin", dataset_ids=["d1"], top_k=5, score_threshold=0.5)
    assert await retrieve(default, "苏超购票", "t") == []
