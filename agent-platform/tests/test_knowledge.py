"""知识库：哈希嵌入、余弦相似度、内置向量库与外接检索器。"""
from __future__ import annotations

import json
import math
import uuid

import httpx
import pytest

from agent_platform.core.config import Settings
from agent_platform.graph.schema import KnowledgeConfig
from agent_platform.knowledge import embeddings as embeddings_mod
from agent_platform.knowledge import retrievers as retrievers_mod
from agent_platform.knowledge.documents import (
    add_segment,
    create_document,
    delete_document,
    list_documents,
    list_segments,
    update_segment,
)
from agent_platform.knowledge.embeddings import Embedder, cosine, hash_embed
from agent_platform.knowledge.retrievers import build_retriever
from agent_platform.knowledge.vector_store import build_builtin_searcher, search_documents


def _seed(tenant_code: str, dataset_id: str, name: str, content: str, embedding: list[float]):
    """建一份文档 + 单个分段（旧的「一行即一分段」用例的最小等价物）。"""
    document = create_document(
        tenant_code=tenant_code, dataset_id=dataset_id, name=name, content=content, status="ready"
    )
    add_segment(
        tenant_code=tenant_code,
        dataset_id=dataset_id,
        document_uuid=document.uuid,
        content=content,
        embedding=embedding,
    )
    return document


def _patch_http(monkeypatch, module, handler, captured: list):
    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        captured.append(kwargs)
        return real_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(module.httpx, "AsyncClient", factory)


# --------------------------------------------------------------------------- 嵌入


def test_hash_embed_is_deterministic_and_normalized():
    first = hash_embed("常州市政务服务中心")
    assert first == hash_embed("常州市政务服务中心")
    assert len(first) == 256
    assert math.isclose(math.sqrt(sum(v * v for v in first)), 1.0, rel_tol=1e-9)


def test_hash_embed_respects_dimension_and_handles_empty():
    assert len(hash_embed("abc", dim=32)) == 32
    assert hash_embed("") == [0.0] * 256
    assert hash_embed("   ") == [0.0] * 256


def test_hash_embed_differs_for_different_text():
    assert hash_embed("天气查询") != hash_embed("办事指南")


def test_cosine_bounds_and_edge_cases():
    assert math.isclose(cosine([1.0, 0.0], [1.0, 0.0]), 1.0)
    assert math.isclose(cosine([1.0, 0.0], [0.0, 1.0]), 0.0)
    assert cosine([1.0, 2.0], [1.0]) == 0.0
    assert cosine([], [1.0]) == 0.0
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


@pytest.mark.asyncio
async def test_embedder_local_mode_uses_hash_embedding():
    vector = await Embedder(Settings(embedding_dim=64)).encode("常州天气")
    assert vector == hash_embed("常州天气", 64)
    assert len(await Embedder(None).encode("常州天气")) == 256


@pytest.mark.asyncio
async def test_embedder_remote_mode(monkeypatch):
    captured: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"data": [{"embedding": [0.25, 0.75]}]})

    _patch_http(monkeypatch, embeddings_mod, handler, [])
    settings = Settings(
        embedding_base_url="https://embed.local/v1/", embedding_api_key="k", embedding_model="m3"
    )
    vector = await Embedder(settings).encode("常州天气")
    assert vector == [0.25, 0.75]
    request = captured[0]
    assert str(request.url) == "https://embed.local/v1/embeddings"
    assert request.headers["authorization"] == "Bearer k"
    assert json.loads(request.content) == {"model": "m3", "input": "常州天气"}


@pytest.mark.asyncio
async def test_embedder_remote_mode_without_api_key(monkeypatch):
    captured: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"data": [{"embedding": [1.0]}]})

    _patch_http(monkeypatch, embeddings_mod, handler, [])
    await Embedder(Settings(embedding_base_url="https://embed.local")).encode("x")
    assert "authorization" not in captured[0].headers


# --------------------------------------------------------------------------- 内置向量库


def test_document_and_segment_lifecycle():
    document = _seed("t", "d1", "常州政务", "常州天气查询办事指南", hash_embed("常州天气查询办事指南"))
    assert document.uuid and document.name == "常州政务"

    rows, total = list_documents("t")
    assert total == 1 and [row.uuid for row in rows] == [document.uuid]
    assert list_documents("t", "d1")[0][0].uuid == document.uuid
    assert list_documents("t", "d2") == ([], 0)
    assert list_documents("other") == ([], 0)

    assert delete_document(document.uuid) is True
    assert delete_document(document.uuid) is False
    assert list_documents("t") == ([], 0)


def test_search_documents_ranks_and_filters():
    content = "常州天气查询办事指南"
    _seed("t", "d1", "相关", content, hash_embed(content))
    _seed("t", "d2", "无关", "上海公积金提取流程", hash_embed("上海公积金提取流程"))

    results = search_documents(tenant_code="t", query_vector=hash_embed(content), top_k=5)
    assert results[0]["document_name"] == "相关"
    assert results[0]["score"] == 1.0
    assert results[0]["dataset_id"] == "d1"

    scoped = search_documents(tenant_code="t", query_vector=hash_embed(content), dataset_ids=["d2"])
    assert [item["document_name"] for item in scoped] == ["无关"]

    assert search_documents(tenant_code="t", query_vector=hash_embed(content), score_threshold=0.99) == [
        item for item in results if item["score"] >= 0.99
    ]
    assert search_documents(tenant_code="t", query_vector=hash_embed(content), top_k=1) == results[:1]


def test_search_documents_ignores_soft_deleted_and_disabled():
    content = "常州天气查询"
    document = _seed("t", "d1", "x", content, hash_embed(content))
    assert search_documents(tenant_code="t", query_vector=hash_embed(content))

    segment = list_segments(document.uuid)[0][0]
    update_segment(segment.uuid, enabled=0)
    assert search_documents(tenant_code="t", query_vector=hash_embed(content)) == []

    update_segment(segment.uuid, enabled=1)
    delete_document(document.uuid)
    assert search_documents(tenant_code="t", query_vector=hash_embed(content)) == []


@pytest.mark.asyncio
async def test_builtin_searcher_queries_store():
    content = "常州天气查询办事指南"
    _seed("t", "d1", "指南", content, hash_embed(content))
    searcher = build_builtin_searcher(Settings(embedding_dim=256))
    results = await searcher(
        tenant_code="t", query=content, dataset_ids=["d1"], top_k=3, score_threshold=None
    )
    assert results[0]["document_name"] == "指南"


# --------------------------------------------------------------------------- 外接检索


@pytest.mark.asyncio
async def test_retriever_builtin_kind_uses_vector_store():
    content = "常州天气查询办事指南"
    _seed("t", "d1", "指南", content, hash_embed(content))
    retrieve = build_retriever(Settings())
    config = KnowledgeConfig(retriever="builtin", dataset_ids=["d1"])
    results = await retrieve(config, content, "t")
    assert results[0]["content"] == content


@pytest.mark.asyncio
async def test_retriever_http_kinds(monkeypatch):
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"data": [{"content": "chunk", "score": 0.9}]})

    _patch_http(monkeypatch, retrievers_mod, handler, [])
    settings = Settings(
        light_rag_base_url="https://rag.local",
        light_rag_api_key="rag-key",
        knowflow_base_url="https://knowflow.local",
        knowledge_graph_base_url="https://kg.local",
    )
    retrieve = build_retriever(settings)

    for kind, url in (
        ("light_rag", "https://rag.local/query"),
        ("knowflow", "https://knowflow.local/query"),
        ("knowledge_graph", "https://kg.local/query"),
    ):
        config = KnowledgeConfig(retriever=kind, dataset_ids=["d1"], top_k=3)
        results = await retrieve(config, "常州天气", "t")
        assert results == [{"content": "chunk", "score": 0.9}]
        assert str(captured[-1].url) == url
        assert json.loads(captured[-1].content) == {"query": "常州天气", "top_k": 3, "dataset_ids": ["d1"]}

    assert captured[0].headers["authorization"] == "Bearer rag-key"
    assert "authorization" not in captured[1].headers


@pytest.mark.asyncio
async def test_retriever_http_accepts_bare_list_and_missing_base_url(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"content": "raw"}])

    _patch_http(monkeypatch, retrievers_mod, handler, [])
    retrieve = build_retriever(Settings(light_rag_base_url="https://rag.local"))
    config = KnowledgeConfig(retriever="light_rag")
    assert await retrieve(config, "q", "t") == [{"content": "raw"}]

    unconfigured = build_retriever(Settings())
    with pytest.raises(RuntimeError, match="知识平台 base_url 未配置"):
        await unconfigured(config, "q", "t")


@pytest.mark.asyncio
async def test_retriever_rejects_unknown_kind():
    config = KnowledgeConfig.model_construct(retriever="ghost", dataset_ids=[], query="q", top_k=5)
    with pytest.raises(RuntimeError, match="未知检索器类型: ghost"):
        await build_retriever(Settings())(config, "q", "t")


@pytest.mark.asyncio
async def test_retriever_propagates_http_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    _patch_http(monkeypatch, retrievers_mod, handler, [])
    retrieve = build_retriever(Settings(light_rag_base_url="https://rag.local"))
    with pytest.raises(httpx.HTTPStatusError):
        await retrieve(KnowledgeConfig(retriever="light_rag"), "q", "t")


def test_document_uuids_are_unique():
    content = "常州天气"
    first = _seed("t", "d1", "a", content, hash_embed(content))
    second = _seed("t", "d1", "b", content, hash_embed(content))
    assert first.uuid != second.uuid
    assert uuid.UUID(first.uuid).hex == first.uuid


# --------------------------------------------------------------------------- 索引方式 / 检索模式


def test_resolve_retrieval_reads_dataset_and_forces_fulltext_for_economy():
    from agent_platform.knowledge.datasets import create_dataset, update_dataset
    from agent_platform.knowledge.vector_store import resolve_retrieval

    dataset = create_dataset(tenant_code="t", name="kb", retrieval={"mode": "hybrid"})
    assert resolve_retrieval("t", [dataset.uuid])["mode"] == "hybrid"

    update_dataset(dataset.uuid, index_method="economy")
    assert resolve_retrieval("t", [dataset.uuid])["mode"] == "fulltext"

    assert resolve_retrieval("t", []) == {}
    assert resolve_retrieval("t", ["missing"]) == {}


@pytest.mark.asyncio
async def test_economy_ingest_skips_embeddings_and_recalls_fulltext():
    from agent_platform.knowledge.datasets import create_dataset
    from agent_platform.knowledge.ingest import ingest_document

    dataset = create_dataset(tenant_code="t", name="kb", index_method="economy", chunk_config={"max_chars": 50})
    document = create_document(
        tenant_code="t", dataset_id=dataset.uuid, name="d", content="苏超购票专题智能体上线", status="pending"
    )
    await ingest_document(document.uuid)

    segments, total = list_segments(document.uuid)
    assert total == 1 and segments[0].embedding == []

    searcher = build_builtin_searcher(Settings(embedding_dim=256))
    hits = await searcher(
        tenant_code="t", query="苏超购票", dataset_ids=[dataset.uuid], top_k=5, score_threshold=None
    )
    assert [hit["document_name"] for hit in hits] == ["d"]


@pytest.mark.asyncio
async def test_fulltext_mode_recalls_by_keywords_only():
    from agent_platform.knowledge.datasets import create_dataset
    from agent_platform.knowledge.ingest import ingest_document

    dataset = create_dataset(tenant_code="t", name="kb", retrieval={"mode": "fulltext"})
    document = create_document(
        tenant_code="t", dataset_id=dataset.uuid, name="kw", content="苏超购票专题", status="pending"
    )
    await ingest_document(document.uuid)

    searcher = build_builtin_searcher(Settings(embedding_dim=256))
    hits = await searcher(
        tenant_code="t", query="苏超购票", dataset_ids=[dataset.uuid], top_k=5, score_threshold=None
    )
    assert [hit["document_name"] for hit in hits] == ["kw"]


@pytest.mark.asyncio
async def test_ingest_honours_document_chunk_config_override():
    from agent_platform.knowledge.datasets import create_dataset
    from agent_platform.knowledge.ingest import ingest_document

    dataset = create_dataset(tenant_code="t", name="kb", chunk_config={"max_chars": 100})
    document = create_document(
        tenant_code="t",
        dataset_id=dataset.uuid,
        name="d",
        content="甲" * 25,
        status="pending",
        chunk_config={"max_chars": 10},
    )
    await ingest_document(document.uuid)
    _, total = list_segments(document.uuid)
    assert total == 3
