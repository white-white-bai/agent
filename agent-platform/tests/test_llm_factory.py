"""模型工厂：原生 tool calling、消息栈与超时/重试配置。"""
from __future__ import annotations

from typing import ClassVar

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent_platform.core.config import Settings
from agent_platform.models.factory import build_llm_invoker


class FakeChatModel:
    instances: ClassVar[list[FakeChatModel]] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.bound: tuple | None = None
        self.messages: list | None = None
        self.config: dict | None = None
        FakeChatModel.instances.append(self)

    def bind_tools(self, tools, tool_choice=None):
        self.bound = (tools, tool_choice)
        return self

    async def ainvoke(self, messages, config=None):
        self.messages = messages
        self.config = config
        return AIMessage(content="ok", tool_calls=[{"name": "t", "args": {"q": 1}, "id": "c1"}])


@pytest.fixture(autouse=True)
def _reset_fake_models(monkeypatch):
    FakeChatModel.instances = []
    monkeypatch.setattr("langchain_openai.ChatOpenAI", FakeChatModel)
    yield


def _settings(**overrides) -> Settings:
    data = {
        "llm_models": {"m": {"model": "demo", "base_url": "http://llm.local/v1", "api_key": "k"}},
        "llm_timeout_seconds": 12.0,
        "llm_max_retries": 1,
    }
    data.update(overrides)
    return Settings(**data)


@pytest.mark.asyncio
async def test_native_tool_call_uses_messages_tools_and_tags():
    invoker = build_llm_invoker(_settings())
    tools = [{"type": "function", "function": {"name": "t", "description": "d", "parameters": {"type": "object"}}}]

    result = await invoker(
        provider="m",
        system_prompt="",
        user_prompt="",
        temperature=0.2,
        max_tokens=100,
        messages=[HumanMessage(content="hi")],
        tools=tools,
        tool_choice="auto",
        return_message=True,
        tags=["agent-internal"],
    )

    assert isinstance(result, AIMessage)
    assert result.tool_calls[0]["name"] == "t"
    model = FakeChatModel.instances[0]
    assert model.bound == (tools, "auto")
    assert model.messages[0].content == "hi"
    assert model.config == {"tags": ["agent-internal"], "metadata": {"agent-internal": True}}
    assert model.kwargs["timeout"] == 12.0
    assert model.kwargs["max_retries"] == 1


@pytest.mark.asyncio
async def test_legacy_call_keeps_system_human_messages_and_returns_text():
    invoker = build_llm_invoker(_settings(llm_timeout_seconds=0))

    result = await invoker(
        provider="m",
        system_prompt="sys",
        user_prompt="user",
        temperature=0.2,
        max_tokens=100,
    )

    assert result == "ok"
    model = FakeChatModel.instances[0]
    assert isinstance(model.messages[0], SystemMessage) and model.messages[0].content == "sys"
    assert isinstance(model.messages[1], HumanMessage) and model.messages[1].content == "user"
    assert model.config is None
    assert "timeout" not in model.kwargs


@pytest.mark.asyncio
async def test_model_instance_is_reused_within_invoker():
    invoker = build_llm_invoker(_settings())

    await invoker(provider="m", system_prompt="s", user_prompt="u", temperature=0.2, max_tokens=100)
    await invoker(provider="m", system_prompt="s", user_prompt="u2", temperature=0.2, max_tokens=100)

    assert len(FakeChatModel.instances) == 1
