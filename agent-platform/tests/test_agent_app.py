"""Agent 应用：定义 schema、草稿/发布服务、原生 function-calling 运行时、工具构建。"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field, ValidationError

from agent_platform.agentapp import tools as agent_tools
from agent_platform.agentapp.runtime import resume_agent, run_agent, stream_agent
from agent_platform.agentapp.schema import AgentAppDef, AgentHitlConfig, AgentToolRef
from agent_platform.api import services
from agent_platform.core.config import Settings
from agent_platform.core.db import session_scope
from agent_platform.domain.models import App
from agent_platform.engine.agents.registry import AgentSpec
from agent_platform.engine.context import EngineContext
from agent_platform.graph.schema import KnowledgeConfig


class FakeToolChatModel(BaseChatModel):
    """按脚本依次返回 AIMessage；支持 bind_tools 与流式。"""

    responses: list[AIMessage] = Field(default_factory=list)
    index: int = 0
    bound: list[Any] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "fake-tool-chat"

    def bind_tools(self, tools, **kwargs):
        self.bound = list(tools)
        return self

    def _pick(self) -> AIMessage:
        reply = self.responses[min(self.index, len(self.responses) - 1)]
        self.index += 1
        return reply

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._pick())])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return self._generate(messages)

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        reply = self._pick()
        text = reply.content if isinstance(reply.content, str) else ""
        for char in text:
            chunk = AIMessageChunk(content=char)
            if run_manager:
                await run_manager.on_llm_new_token(char, chunk=chunk)
            yield ChatGenerationChunk(message=chunk)
        for call in reply.tool_calls:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[{
                        "name": call["name"],
                        "args": json.dumps(call["args"]),
                        "id": call["id"],
                        "index": 0,
                    }],
                )
            )


def _ctx(chat_model: Any, retriever: Any = None) -> EngineContext:
    ctx = EngineContext(llm=lambda **_kw: "", chat_model=lambda **_kw: chat_model)
    if retriever is not None:
        ctx.retriever = retriever
    return ctx


async def _collect(stream) -> list[dict]:
    return [item async for item in stream]


def _seed_app(app_uuid: str = "app-uuid") -> None:
    with session_scope() as session:
        session.add(App(uuid=app_uuid, tenant_code="t", app_id="a1", api_key="k1"))


# --------------------------------------------------------------------------- schema / 服务


def test_agent_app_def_defaults_and_document():
    definition = AgentAppDef.model_validate(
        {"name": "问答", "instructions": "你是助手", "tools": [{"name": "t1", "server": "s"}]}
    )
    assert definition.max_steps == 6
    assert definition.knowledge.retriever == "builtin"
    assert definition.tools[0].name == "t1"
    assert definition.to_document()["name"] == "问答"


def test_agent_draft_publish_rollback():
    _seed_app()
    services.save_agent_draft("app-uuid", AgentAppDef(name="v1", instructions="one").to_document(), tenant_code="t")
    assert services.get_agent_draft("app-uuid")["name"] == "v1"

    version = services.publish_agent_draft("app-uuid", tenant_code="t", note="首版")
    assert version is not None and version.version == 1
    assert services.get_published_agent("app-uuid").name == "v1"

    services.save_agent_draft("app-uuid", AgentAppDef(name="v2").to_document())
    services.publish_agent_draft("app-uuid")
    assert services.get_published_agent("app-uuid").name == "v2"

    assert services.rollback_agent("app-uuid", 1) is not None
    assert services.get_published_agent("app-uuid").name == "v1"
    assert len(services.list_agent_versions("app-uuid")) == 2


def test_publish_rejects_invalid_definition():
    _seed_app()
    with pytest.raises(ValidationError):
        services.publish_agent_draft("app-uuid", definition={"hitl": {"policy": "nope"}})
    assert services.get_published_agent("app-uuid") is None


# --------------------------------------------------------------------------- 工具构建


def test_declared_tool_schema_reflects_params():
    services.create_tool(
        tenant_code="t",
        name="gov.lookup",
        description="按关键词查社保",
        params=[
            {"name": "keyword", "type": "string", "required": True},
            {"name": "top", "type": "number", "required": False},
        ],
    )
    tool = agent_tools._declared_tool(AgentToolRef(name="gov.lookup"), Settings(), "t")
    assert tool.description == "按关键词查社保"
    schema = tool.args_schema.model_json_schema()
    assert schema["properties"]["keyword"]["type"] == "string"
    assert "top" in schema["properties"]


def test_agent_def_from_spec_maps_fields():
    mapped = agent_tools.agent_def_from_spec(
        AgentSpec(code="x", label="X", system_prompt="hi", retriever={"dataset_ids": ["d1"], "top_k": 3})
    )
    assert mapped.instructions == "hi"
    assert mapped.knowledge.dataset_ids == ["d1"]
    assert mapped.knowledge.top_k == 3


async def test_build_agent_tools_includes_knowledge_and_respects_depth():
    definition = AgentAppDef(knowledge=KnowledgeConfig(dataset_ids=["d1"]), sub_agents=["sub.one"])
    ctx = _ctx(FakeToolChatModel(responses=[AIMessage("x")]), retriever=lambda *a, **k: [])
    tools, sink = await agent_tools.build_agent_tools(
        definition, Settings(agent_app_depth=0), ctx, tenant_code="t", thread_id="th", depth=0
    )
    assert sink == []
    names = {tool.name for tool in tools}
    assert agent_tools.KNOWLEDGE_TOOL in names
    assert "delegate_sub.one" in names
    delegate = next(tool for tool in tools if tool.name == "delegate_sub.one")
    result = json.loads(await delegate.ainvoke({"query": "q"}))
    assert result["status"] == "error"
    assert result["answer"] == "委派深度已达上限，请自行作答。"


async def test_sub_agent_handoff_is_typed(monkeypatch):
    spec = SimpleNamespace(
        code="sub.one",
        label="子 Agent",
        system_prompt="sub",
        provider="",
        temperature=0.3,
        max_tokens=None,
        tools=[],
        retriever={},
        max_steps=3,
    )
    monkeypatch.setattr("agent_platform.engine.agents.registry.load_agent", lambda *args, **kwargs: spec)

    async def fake_run_agent(*args, **kwargs):
        return {"answer": "child-answer"}

    monkeypatch.setattr("agent_platform.agentapp.runtime.run_agent", fake_run_agent)
    tools, _ = await agent_tools.build_agent_tools(
        AgentAppDef(name="parent", sub_agents=["sub.one"]),
        Settings(agent_app_depth=2),
        _ctx(FakeToolChatModel(responses=[AIMessage("x")])),
        tenant_code="t",
        thread_id="th",
    )
    delegate = next(tool for tool in tools if tool.name == "delegate_sub.one")

    handoff = json.loads(await delegate.ainvoke({"query": "q"}))

    assert handoff["from_agent"] == "parent"
    assert handoff["to_agent"] == "sub.one"
    assert handoff["status"] == "ok"
    assert handoff["answer"] == "child-answer"
    assert handoff["detail"] == {"depth": 1}


async def test_build_agent_tools_discovers_mcp_tools(monkeypatch):
    class FakeMcp:
        def __init__(self, url, **_kwargs):
            self.url = url

        async def initialize(self):
            return {}

        async def list_tools(self):
            return [{
                "name": "mcp.echo",
                "description": "回显",
                "inputSchema": {"properties": {"text": {"type": "string"}}, "required": ["text"]},
            }]

        async def call_tool(self, name, args):
            return {"name": name, "args": args}

    monkeypatch.setattr(agent_tools, "McpHttpClient", FakeMcp)
    monkeypatch.setattr(agent_tools, "_server_spec", lambda *args, **kwargs: {"url": "http://mcp"})

    definition = AgentAppDef(mcp_servers=["demo"])
    tools, _ = await agent_tools.build_agent_tools(
        definition, Settings(), _ctx(FakeToolChatModel(responses=[AIMessage("x")])), tenant_code="t"
    )
    echo = next(tool for tool in tools if tool.name == "mcp.echo")
    assert echo.description == "回显"
    assert await echo.ainvoke({"text": "hi"}) == {"name": "mcp.echo", "args": {"text": "hi"}}


# --------------------------------------------------------------------------- 运行时


@pytest.mark.asyncio
async def test_stream_agent_native_tool_loop_and_contract():
    async def retriever(config, query, tenant_code=""):
        return [{"content": f"{query}相关资料", "document_name": "d"}]

    definition = AgentAppDef(knowledge=KnowledgeConfig(dataset_ids=["d1"]), knowledge_as_tool=True)
    model = FakeToolChatModel(responses=[
        AIMessage(content="", tool_calls=[{"name": agent_tools.KNOWLEDGE_TOOL, "args": {"query": "社保"}, "id": "c1"}]),
        AIMessage(content="社保需窗口办理。"),
    ])
    ctx = _ctx(model, retriever=retriever)

    items = await _collect(stream_agent(definition, {"query": "社保怎么办"}, ctx, tenant_code="t"))
    tokens = "".join(item["content"] for item in items if item["type"] == "token")
    final = next(item for item in items if item["type"] == "final")

    assert tokens == "社保需窗口办理。"
    assert final["answer"] == "社保需窗口办理。"
    assert len(model.bound) == 1  # 知识工具被绑定给模型
    assert final["state"]["variables"]["chunks"][0]["content"] == "社保相关资料"
    assert any(item["type"] == "agent_tool" for item in items)


@pytest.mark.asyncio
async def test_stream_agent_planning_node_runs():
    definition = AgentAppDef(planning=True)
    model = FakeToolChatModel(responses=[AIMessage(content="计划：先查再答"), AIMessage(content="最终答复")])
    items = await _collect(stream_agent(definition, {"query": "问题"}, _ctx(model)))
    assert any(item["type"] == "agent_plan" for item in items)
    assert next(item for item in items if item["type"] == "final")["answer"] == "最终答复"


@pytest.mark.asyncio
async def test_run_agent_uses_checkpointer_memory_across_turns():
    from agent_platform.checkpoint.mysql import MySQLCheckpointSaver

    definition = AgentAppDef()
    model = FakeToolChatModel(responses=[AIMessage(content="第一答"), AIMessage(content="第二答")])
    ctx = _ctx(model)
    saver = MySQLCheckpointSaver()

    first = await run_agent(definition, {"query": "你好"}, ctx, checkpointer=saver, thread_id="conv-1")
    assert first["answer"] == "第一答"

    captured: list[list[Any]] = []
    original = model._generate

    def capturing(messages, stop=None, run_manager=None, **kwargs):
        captured.append(list(messages))
        return original(messages)

    model._generate = capturing  # type: ignore[method-assign]
    second = await run_agent(definition, {"query": "继续"}, ctx, checkpointer=saver, thread_id="conv-1")

    assert second["answer"] == "第二答"
    seen = [getattr(m, "content", "") for m in captured[0] if isinstance(m, (HumanMessage, AIMessage))]
    assert "你好" in seen and "第一答" in seen and "继续" in seen


# --------------------------------------------------------------------------- Human-in-the-loop


async def _retriever(config, query, tenant_code=""):
    return [{"content": "hit", "document_name": "d"}]


def _hitl_definition() -> AgentAppDef:
    return AgentAppDef(
        knowledge=KnowledgeConfig(dataset_ids=["d1"]),
        knowledge_as_tool=True,
        hitl=AgentHitlConfig(enabled=True, policy="before_all_tools"),
    )


def _tool_call_model() -> FakeToolChatModel:
    return FakeToolChatModel(responses=[
        AIMessage(content="", tool_calls=[{"name": agent_tools.KNOWLEDGE_TOOL, "args": {"query": "q"}, "id": "c1"}]),
        AIMessage(content="已根据资料回答"),
    ])


@pytest.mark.asyncio
async def test_hitl_pauses_then_approve_resumes():
    from agent_platform.checkpoint.mysql import MySQLCheckpointSaver

    definition = _hitl_definition()
    model = _tool_call_model()
    ctx = _ctx(model, retriever=_retriever)
    saver = MySQLCheckpointSaver()

    items = await _collect(stream_agent(definition, {"query": "q"}, ctx, checkpointer=saver, thread_id="t-hitl"))
    assert any(item["type"] == "agent_interrupt" for item in items)
    paused = next(item for item in items if item["type"] == "final")
    assert paused["state"]["variables"]["paused"] is True

    resumed = await _collect(
        resume_agent(definition, {"decision": "approve"}, ctx, checkpointer=saver, thread_id="t-hitl")
    )
    final = next(item for item in resumed if item["type"] == "final")
    assert final["answer"] == "已根据资料回答"
    assert final["state"]["variables"]["chunks"][0]["content"] == "hit"


@pytest.mark.asyncio
async def test_hitl_reject_skips_tool_and_answers():
    from agent_platform.checkpoint.mysql import MySQLCheckpointSaver

    definition = _hitl_definition()
    model = FakeToolChatModel(responses=[
        AIMessage(content="", tool_calls=[{"name": agent_tools.KNOWLEDGE_TOOL, "args": {"query": "q"}, "id": "c1"}]),
        AIMessage(content="未查资料，直接作答"),
    ])
    ctx = _ctx(model, retriever=_retriever)
    saver = MySQLCheckpointSaver()

    await _collect(stream_agent(definition, {"query": "q"}, ctx, checkpointer=saver, thread_id="t-rej"))
    resumed = await _collect(
        resume_agent(definition, {"decision": "reject"}, ctx, checkpointer=saver, thread_id="t-rej")
    )
    final = next(item for item in resumed if item["type"] == "final")
    assert final["answer"] == "未查资料，直接作答"
    assert final["state"]["variables"]["chunks"] == []  # 工具被拒绝，未检索


@pytest.mark.asyncio
async def test_stream_agent_reports_paused_thread_instead_of_rerunning():
    from agent_platform.checkpoint.mysql import MySQLCheckpointSaver

    definition = _hitl_definition()
    ctx = _ctx(_tool_call_model(), retriever=_retriever)
    saver = MySQLCheckpointSaver()
    await _collect(stream_agent(definition, {"query": "q"}, ctx, checkpointer=saver, thread_id="t-pend"))

    # 同会话再次发起普通轮：不静默续跑旧中断，而是回传待审批提示
    again = await _collect(stream_agent(definition, {"query": "新问题"}, ctx, checkpointer=saver, thread_id="t-pend"))
    final = next(item for item in again if item["type"] == "final")
    assert final["state"]["variables"]["paused"] is True


@pytest.mark.asyncio
async def test_checkpointer_delete_thread_clears_memory():
    from agent_platform.checkpoint.mysql import MySQLCheckpointSaver

    definition = AgentAppDef()
    ctx = _ctx(FakeToolChatModel(responses=[AIMessage(content="x")]))
    saver = MySQLCheckpointSaver()
    await run_agent(definition, {"query": "q"}, ctx, checkpointer=saver, thread_id="conv-del")

    config = {"configurable": {"thread_id": "conv-del"}}
    assert saver.get_tuple(config) is not None
    saver.delete_thread("conv-del")
    assert saver.get_tuple(config) is None


# --------------------------------------------------------------------------- 入口分叉 / 管理端


def _seed_agent_app(api_key: str = "ak", app_type: str = "agent", publish: bool = True) -> str:
    row = services.create_app(
        tenant_code="t", app_id="ag-1", api_key=api_key, app_name="agent app", app_type=app_type
    )
    if publish:
        services.save_agent_draft(row.uuid, AgentAppDef(name="A", instructions="hi").to_document())
        services.publish_agent_draft(row.uuid)
    return row.uuid


def test_chat_dispatch_to_agent_app(api_client, monkeypatch):
    from agent_platform.api import main as main_mod

    _seed_agent_app()
    monkeypatch.setattr(main_mod, "get_settings", lambda: Settings(agent_app_enabled=True))
    calls: list[dict] = []

    async def fake_stream(agent_def, inputs, ctx, **kwargs):
        calls.append({"def": agent_def, "inputs": inputs, "kwargs": kwargs})
        yield {"type": "token", "content": "你好"}
        yield {"type": "final", "answer": "你好", "state": {"variables": {"chunks": [{"content": "资料", "document_name": "d"}]}}}

    monkeypatch.setattr(main_mod, "stream_agent", fake_stream)

    response = api_client.post("/v1/chat-messages", json={"query": "hi", "user": "u"}, headers={"Api-Key": "ak"})
    assert response.status_code == 200
    assert "message" in response.text and "你好" in response.text
    assert "message_end" in response.text
    assert "retriever_resources" in response.text and '"document_name": "d"' in response.text
    assert calls and calls[0]["def"].name == "A"


def test_chat_agent_app_disabled_falls_back_to_graph(api_client, monkeypatch):
    from agent_platform.api import main as main_mod

    _seed_agent_app()
    monkeypatch.setattr(main_mod, "get_settings", lambda: Settings(agent_app_enabled=False))
    called = {"agent": False}

    async def fake_stream(*args, **kwargs):
        called["agent"] = True
        yield {"type": "final", "answer": "x", "state": {}}

    monkeypatch.setattr(main_mod, "stream_agent", fake_stream)

    # 未发布图 → 走图路径拿到 default_reply，且不进入 agent 运行时（默认关闭不变）
    response = api_client.post("/v1/chat-messages", json={"query": "hi"}, headers={"Api-Key": "ak"})
    assert called["agent"] is False
    assert "智能客服" in response.text


def test_agent_admin_draft_publish_rollback(api_client):
    created = api_client.post(
        "/admin/apps", json={"app_id": "ag-admin", "app_name": "A", "app_type": "agent", "tenant_code": "t"}
    )
    app_uuid = created.json()["data"]["uuid"]

    assert api_client.get(f"/admin/apps/{app_uuid}/agent").json()["data"]["definition"] == {}
    draft = AgentAppDef(name="A", instructions="hi").to_document()
    saved = api_client.put(f"/admin/apps/{app_uuid}/agent/draft", json={"definition": draft})
    assert saved.json()["data"]["status"] == "draft"

    published = api_client.post(f"/admin/apps/{app_uuid}/agent/publish", json={"note": "首版"})
    assert published.json()["data"]["version"] == 1
    versions = api_client.get(f"/admin/apps/{app_uuid}/agent/versions").json()["data"]
    assert len(versions) == 1
    assert api_client.post(f"/admin/apps/{app_uuid}/agent/rollback", json={"version": 1}).status_code == 200

    bad = api_client.post(f"/admin/apps/{app_uuid}/agent/publish", json={"definition": {"hitl": {"policy": "x"}}})
    assert bad.status_code == 400


def test_agent_resume_requires_published_definition(api_client):
    created = api_client.post("/admin/apps", json={"app_id": "ag-res", "app_type": "agent", "tenant_code": "t"})
    app_uuid = created.json()["data"]["uuid"]
    response = api_client.post(
        f"/admin/apps/{app_uuid}/agent/resume", json={"conversation_id": "c", "decision": "approve"}
    )
    assert response.status_code == 400


def test_clear_agent_memory_endpoint(api_client):
    created = api_client.post("/admin/apps", json={"app_id": "ag-mem", "app_type": "agent", "tenant_code": "t"})
    app_uuid = created.json()["data"]["uuid"]
    response = api_client.delete(f"/admin/apps/{app_uuid}/agent/conversations/c1/memory")
    assert response.status_code == 200
    assert response.json()["data"]["cleared"] is True
