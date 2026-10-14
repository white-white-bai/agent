"""worker：队列收发、任务处理器与轮询入口。"""
from __future__ import annotations

import uuid

import pytest

from agent_platform.core.db import session_scope
from agent_platform.domain.models import Conversation, Message
from agent_platform.engine.context import EngineContext
from agent_platform.knowledge.embeddings import hash_embed
from agent_platform.knowledge.vector_store import list_documents
from agent_platform.worker import jobs as jobs_mod
from agent_platform.worker import main as worker_main
from agent_platform.worker.jobs import handle_job, knowledge_ingest, report_generate
from agent_platform.worker.queue import dequeue, enqueue


def _seed_conversation(tenant_code: str = "t") -> str:
    with session_scope() as session:
        row = Conversation(
            uuid=uuid.uuid4().hex,
            tenant_code=tenant_code,
            app_uuid="app-uuid",
            conversation_id=uuid.uuid4().hex,
        )
        session.add(row)
        session.flush()
        for tokens in (10, 25):
            session.add(
                Message(
                    uuid=uuid.uuid4().hex,
                    conversation_uuid=row.uuid,
                    message_id=uuid.uuid4().hex,
                    role="user",
                    query="q",
                    tokens=tokens,
                )
            )
        return row.uuid


# --------------------------------------------------------------------------- 队列


def test_enqueue_and_dequeue_roundtrip():
    assert enqueue("report_generate", {"tenant_code": "t"}) == "report_generate"
    assert dequeue() == {"type": "report_generate", "payload": {"tenant_code": "t"}}
    assert dequeue() is None


def test_enqueue_defaults_payload_to_empty_dict():
    enqueue("knowledge_ingest")
    assert dequeue() == {"type": "knowledge_ingest", "payload": {}}


def test_queue_is_first_in_first_out():
    enqueue("a")
    enqueue("b")
    assert dequeue()["type"] == "a"
    assert dequeue()["type"] == "b"
    assert dequeue() is None


# --------------------------------------------------------------------------- 任务分发


@pytest.mark.asyncio
async def test_handle_job_rejects_unknown_type():
    with pytest.raises(RuntimeError, match="未知任务类型: ghost"):
        await handle_job({"type": "ghost", "payload": {}})
    with pytest.raises(RuntimeError, match="未知任务类型: None"):
        await handle_job({})


# --------------------------------------------------------------------------- 知识入库


@pytest.mark.asyncio
async def test_knowledge_ingest_stores_document():
    result = await knowledge_ingest(
        {
            "tenant_code": "ing",
            "dataset_id": "d1",
            "title": "常州指南",
            "content": "常州天气查询办事指南",
            "metadata": {"source": "upload"},
        }
    )
    documents = list_documents("ing", "d1")
    assert [row.uuid for row in documents] == [result["document_uuid"]]
    assert documents[0].content == "常州天气查询办事指南"
    assert documents[0].embedding == hash_embed("常州天气查询办事指南")


@pytest.mark.asyncio
async def test_knowledge_ingest_handles_empty_payload():
    result = await knowledge_ingest({})
    assert uuid.UUID(result["document_uuid"]).hex == result["document_uuid"]
    assert list_documents("changzhou")[0].doc_metadata == {}


# --------------------------------------------------------------------------- 批处理


@pytest.mark.asyncio
async def test_graph_batch_run_requires_existing_app():
    with pytest.raises(RuntimeError, match="应用不存在: missing"):
        await jobs_mod.graph_batch_run({"app_id": "missing"})
    with pytest.raises(RuntimeError, match="应用不存在: None"):
        await jobs_mod.graph_batch_run({})


@pytest.mark.asyncio
async def test_graph_batch_run_requires_published_graph(seed_app):
    seed_app(app_id="draft-app", published=False)
    with pytest.raises(RuntimeError, match="应用未发布图定义"):
        await jobs_mod.graph_batch_run({"app_id": "draft-app"})


@pytest.mark.asyncio
async def test_graph_batch_run_runs_published_graph(seed_app, monkeypatch):
    seed_app(app_id="live-app", tenant_code="t")

    def fake_context(settings, *, tenant_code="", tracer=None):
        assert tenant_code == "t"
        return EngineContext(llm=FakeLLM())

    monkeypatch.setattr(jobs_mod, "build_engine_context", fake_context)
    result = await jobs_mod.graph_batch_run({"app_id": "live-app", "inputs": {"query": "常州天气"}})
    assert result["answer"] == "echo:常州天气"
    assert result["variables"]["text"] == "echo:常州天气"


class FakeLLM:
    async def __call__(self, *, provider, model, system_prompt, user_prompt, temperature, max_tokens):
        return f"echo:{user_prompt}"


# --------------------------------------------------------------------------- 报告


@pytest.mark.asyncio
async def test_report_generate_aggregates_tenant_activity():
    _seed_conversation("t")
    _seed_conversation("other")

    report = await report_generate({"tenant_code": "t"})
    assert report["tenant_code"] == "t"
    assert report["conversations"] == 1
    assert report["messages"] == 2
    assert report["tokens"] == 35
    assert uuid.UUID(report["report_id"]).hex == report["report_id"]


@pytest.mark.asyncio
async def test_report_generate_without_activity():
    report = await report_generate({"tenant_code": "empty"})
    assert report["conversations"] == 0
    assert report["messages"] == 0
    assert report["tokens"] == 0


# --------------------------------------------------------------------------- 轮询入口


@pytest.mark.asyncio
async def test_run_once_returns_false_on_empty_queue():
    assert await worker_main.run_once() is False


@pytest.mark.asyncio
async def test_run_once_drains_enqueued_job():
    enqueue("report_generate", {"tenant_code": "t"})
    assert await worker_main.run_once() is True
    assert dequeue() is None


@pytest.mark.asyncio
async def test_run_once_swallows_handler_failure():
    enqueue("ghost")
    assert await worker_main.run_once() is True
    assert dequeue() is None
