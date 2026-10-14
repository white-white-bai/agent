"""记忆摘要：窗口之外的历史压缩为 summary 变量注入图输入。"""
import re
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from agent_platform.api import main as main_mod
from agent_platform.api import services
from agent_platform.api.main import app, get_engine_context
from agent_platform.core.config import Settings
from agent_platform.core.db import session_scope
from agent_platform.domain.models import Conversation
from agent_platform.engine.context import EngineContext


def _seed_conversation() -> Conversation:
    with session_scope() as session:
        row = Conversation(
            uuid=uuid.uuid4().hex, tenant_code="t", app_uuid="app-uuid", conversation_id=uuid.uuid4().hex
        )
        session.add(row)
        session.flush()
        return row


def _stored(conversation_uuid: str) -> Conversation:
    with session_scope() as session:
        return session.scalar(select(Conversation).where(Conversation.uuid == conversation_uuid))


class RecordingLLM:
    def __init__(self, reply: str = "摘要正文", fail: bool = False) -> None:
        self.reply = reply
        self.fail = fail
        self.calls: list[dict] = []

    async def __call__(self, *, provider, model, system_prompt, user_prompt, temperature, max_tokens):
        self.calls.append(
            {"provider": provider, "model": model, "system_prompt": system_prompt, "user_prompt": user_prompt}
        )
        if self.fail:
            raise RuntimeError("模型不可用")
        return self.reply


async def _summarize(conversation, window=2, llm=None, max_chars=4000) -> str:
    return await services.refresh_summary(
        conversation,
        window,
        llm or RecordingLLM(),
        provider="cloud_gateway",
        model="m1",
        max_chars=max_chars,
    )


async def test_refresh_summary_skips_when_window_disabled():
    conversation = _seed_conversation()
    services.save_message(conversation, "user", query="q1")
    llm = RecordingLLM()

    assert await _summarize(conversation, window=0, llm=llm) == ""
    assert llm.calls == []
    assert _stored(conversation.uuid).summary in ("", None)


async def test_refresh_summary_skips_when_nothing_overflows_window():
    conversation = _seed_conversation()
    services.save_message(conversation, "user", query="q1")
    services.save_message(conversation, "assistant", query="q1", answer="a1")
    llm = RecordingLLM()

    assert await _summarize(conversation, window=5, llm=llm) == ""
    assert llm.calls == []


async def test_refresh_summary_compresses_overflow_and_watermarks_it():
    conversation = _seed_conversation()
    services.save_message(conversation, "user", query="q1")
    services.save_message(conversation, "assistant", query="q1", answer="a1")
    services.save_message(conversation, "user", query="q2")
    services.save_message(conversation, "assistant", query="q2", answer="a2")
    llm = RecordingLLM(reply="用户问过 q1")

    assert await _summarize(conversation, window=2, llm=llm) == "用户问过 q1"
    assert "user: q1" in llm.calls[0]["user_prompt"]
    assert "assistant: a1" in llm.calls[0]["user_prompt"]
    assert "q2" not in llm.calls[0]["user_prompt"]

    stored = _stored(conversation.uuid)
    assert stored.summary == "用户问过 q1"
    assert stored.summary_upto_id == 2

    llm.calls.clear()
    assert await _summarize(conversation, window=2, llm=llm) == "用户问过 q1"
    assert llm.calls == []


async def test_refresh_summary_merges_previous_summary_incrementally():
    conversation = _seed_conversation()
    services.save_message(conversation, "user", query="q1")
    services.save_message(conversation, "assistant", query="q1", answer="a1")
    services.save_message(conversation, "user", query="q2")
    services.save_message(conversation, "assistant", query="q2", answer="a2")
    services.save_message(conversation, "user", query="q3")
    services.save_message(conversation, "assistant", query="q3", answer="a3")
    llm = RecordingLLM()

    await _summarize(conversation, window=2, llm=llm)
    assert "已有摘要" not in llm.calls[0]["user_prompt"]

    services.save_message(conversation, "user", query="q4")
    services.save_message(conversation, "assistant", query="q4", answer="a4")
    await _summarize(conversation, window=2, llm=llm)
    assert "已有摘要：\n摘要正文" in llm.calls[1]["user_prompt"]
    assert "user: q3" in llm.calls[1]["user_prompt"]


async def test_refresh_summary_stops_at_max_chars_without_skipping_messages():
    conversation = _seed_conversation()
    services.save_message(conversation, "user", query="x" * 50)
    services.save_message(conversation, "user", query="y" * 50)
    services.save_message(conversation, "user", query="latest")
    llm = RecordingLLM()

    await _summarize(conversation, window=1, llm=llm, max_chars=90)
    assert _stored(conversation.uuid).summary_upto_id == 1
    assert "y" * 50 not in llm.calls[0]["user_prompt"]

    await _summarize(conversation, window=1, llm=llm)
    assert "user: " + "y" * 50 in llm.calls[1]["user_prompt"]


async def test_refresh_summary_degrades_on_model_failure():
    conversation = _seed_conversation()
    services.save_message(conversation, "user", query="q1")
    services.save_message(conversation, "assistant", query="q1", answer="a1")
    services.save_message(conversation, "user", query="q2")

    assert await _summarize(conversation, window=2, llm=RecordingLLM(fail=True)) == ""
    stored = _stored(conversation.uuid)
    assert stored.summary in ("", None)
    assert stored.summary_upto_id == 0


async def test_refresh_summary_keeps_previous_on_blank_reply():
    conversation = _seed_conversation()
    services.save_message(conversation, "user", query="q1")
    services.save_message(conversation, "assistant", query="q1", answer="a1")
    services.save_message(conversation, "user", query="q2")
    services.save_message(conversation, "assistant", query="q2", answer="a2")

    assert await _summarize(conversation, window=2, llm=RecordingLLM(reply="旧摘要")) == "旧摘要"
    services.save_message(conversation, "user", query="q3")
    services.save_message(conversation, "assistant", query="q3", answer="a3")

    assert await _summarize(conversation, window=2, llm=RecordingLLM(reply="   ")) == "旧摘要"
    stored = _stored(conversation.uuid)
    assert stored.summary == "旧摘要"
    assert stored.summary_upto_id == 2


@pytest.fixture
def client(seed_app):
    app.dependency_overrides[get_engine_context] = lambda: EngineContext(llm=RecordingLLM())
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _capture_stream(monkeypatch) -> list[dict]:
    seen: list[dict] = []

    async def fake_stream(graph_def, inputs, ctx, checkpointer=None, thread_id=None):
        seen.append(dict(inputs))
        yield {"type": "final", "answer": "回答", "state": {"variables": {}}}

    monkeypatch.setattr(main_mod, "stream_graph", fake_stream)
    return seen


def test_chat_injects_summary_once_history_overflows_window(seed_app, client, monkeypatch):
    seed_app(app_id="app-1", api_key="key-1")
    monkeypatch.setattr(
        main_mod,
        "get_settings",
        lambda: Settings(history_window=2, history_summary_enabled=True, history_summary_model="m1"),
    )
    seen = _capture_stream(monkeypatch)

    first = client.post("/v1/chat-messages", json={"query": "第一问"}, headers={"Api-Key": "key-1"})
    assert "summary" not in seen[0]
    conversation_id = re.search(r'"conversation_id": "([0-9a-f]+)"', first.text).group(1)

    client.post(
        "/v1/chat-messages",
        json={"query": "第二问", "conversation_id": conversation_id},
        headers={"Api-Key": "key-1"},
    )
    assert seen[1]["history"] == [
        {"role": "user", "content": "第一问"},
        {"role": "assistant", "content": "回答"},
    ]
    assert "summary" not in seen[1]

    client.post(
        "/v1/chat-messages",
        json={"query": "第三问", "conversation_id": conversation_id},
        headers={"Api-Key": "key-1"},
    )
    assert seen[2]["summary"] == "摘要正文"
    assert seen[2]["query"] == "第三问"
    assert len(seen[2]["history"]) == 2


def test_chat_omits_summary_when_disabled(seed_app, client, monkeypatch):
    seed_app(app_id="app-1", api_key="key-1")
    monkeypatch.setattr(main_mod, "get_settings", lambda: Settings(history_window=1))
    seen = _capture_stream(monkeypatch)

    first = client.post("/v1/chat-messages", json={"query": "第一问"}, headers={"Api-Key": "key-1"})
    conversation_id = re.search(r'"conversation_id": "([0-9a-f]+)"', first.text).group(1)
    client.post(
        "/v1/chat-messages",
        json={"query": "第二问", "conversation_id": conversation_id},
        headers={"Api-Key": "key-1"},
    )
    assert all("summary" not in payload for payload in seen)
