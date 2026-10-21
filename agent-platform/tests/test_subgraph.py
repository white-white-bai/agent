"""动态子图：引用解析、递归编译、候选路由、关闭开关与发布校验。"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from agent_platform.api import services
from agent_platform.core.config import Settings
from agent_platform.core.db import session_scope
from agent_platform.domain.models import Graph, GraphVersion
from agent_platform.engine import nodes
from agent_platform.engine.context import EngineContext
from agent_platform.engine.runtime import run_graph
from agent_platform.graph.schema import CodeInput, GraphDef, SubgraphConfig


class ScriptedLLM:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


def _answer_graph(template: str) -> dict:
    return {
        "nodes": [
            {"id": "start", "type": "start"},
            {"id": "answer", "type": "answer", "config": {"template": template, "output_var": "answer"}},
            {"id": "end", "type": "end"},
        ],
        "edges": [
            {"source": "start", "target": "answer"},
            {"source": "answer", "target": "end"},
        ],
    }


def _parent(child_uuid: str, **config) -> dict:
    return {
        "schema_version": "1.1",
        "nodes": [
            {"id": "start1", "type": "start"},
            {"id": "sub2", "type": "subgraph", "config": {"app_uuid": child_uuid, "version": 1, **config}},
            {"id": "end3", "type": "end"},
        ],
        "edges": [
            {"source": "start1", "target": "sub2"},
            {"source": "sub2", "target": "end3"},
        ],
    }


def _ctx(llm, tenant_code="t") -> EngineContext:
    return EngineContext(
        llm=llm,
        tenant_code=tenant_code,
        subgraph_enabled=True,
        resolve_subgraph=services.resolve_subgraph,
    )


@pytest.mark.asyncio
async def test_single_subgraph_executes_and_returns_answer(seed_app):
    child_uuid, _ = seed_app(tenant_code="t", app_id="child", api_key="key-child", definition=_answer_graph("A"))
    parent = GraphDef.model_validate(_parent(child_uuid))

    state = await run_graph(parent, {"query": "hi"}, _ctx(ScriptedLLM(["unused"])))

    assert state["answer"] == "A"


@pytest.mark.asyncio
async def test_subgraph_input_mapping_and_output_var(seed_app):
    child_uuid, _ = seed_app(
        tenant_code="t",
        app_id="child",
        api_key="key-child",
        definition=_answer_graph("{{ topic }}"),
    )
    parent = GraphDef.model_validate(
        _parent(
            child_uuid,
            inputs=[{"name": "topic", "expression": "query"}],
            output_var="sub_out",
        )
    )

    state = await run_graph(parent, {"query": "hello"}, _ctx(ScriptedLLM(["unused"])))

    assert state["answer"] == "hello"
    assert state["variables"]["sub_out"] == "hello"
    assert state["variables"]["sub2"]["answer"] == "hello"


@pytest.mark.asyncio
async def test_candidate_router_selects_registered_subgraph(seed_app):
    child_a, _ = seed_app(tenant_code="t", app_id="child-a", api_key="key-a", definition=_answer_graph("A"))
    child_b, _ = seed_app(tenant_code="t", app_id="child-b", api_key="key-b", definition=_answer_graph("B"))
    services.create_agent(tenant_code="t", code="router.agent", label="router", system_prompt="router")
    parent = GraphDef.model_validate(
        _parent(
            "",
            candidates=[
                {"app_uuid": child_a, "version": 1, "label": "alpha"},
                {"app_uuid": child_b, "version": 1, "label": "beta"},
            ],
            router="router.agent",
        )
    )

    state = await run_graph(parent, {"query": "hi"}, _ctx(ScriptedLLM(["beta"])))

    assert state["answer"] == "B"


@pytest.mark.asyncio
async def test_subgraph_disabled_raises(seed_app):
    child_uuid, _ = seed_app(tenant_code="t", app_id="child", api_key="key-child", definition=_answer_graph("A"))
    parent = GraphDef.model_validate(_parent(child_uuid))
    ctx = _ctx(ScriptedLLM(["unused"]))
    ctx.subgraph_enabled = False

    with pytest.raises(ValueError, match="子图功能未启用"):
        await run_graph(parent, {"query": "hi"}, ctx)


def test_pin_subgraph_tree_pins_nested_versions(seed_app):
    child_uuid, _ = seed_app(
        tenant_code="t", app_id="child", api_key="key-child", definition=_answer_graph("C")
    )
    middle_uuid, _ = seed_app(
        tenant_code="t",
        app_id="middle",
        api_key="key-middle",
        definition=_parent(child_uuid, version=None),
    )
    parent_def = GraphDef.model_validate(_parent(middle_uuid, version=None))

    pinned, snapshot = services.pin_subgraph_tree(parent_def, "t")

    assert pinned.node("sub2").typed_config().version == 1
    keys = {(item["app_uuid"], item["version"], item["template_key"]) for item in snapshot}
    assert (middle_uuid, 1, "") in keys
    assert (child_uuid, 1, "") in keys
    middle = next(item for item in snapshot if item["app_uuid"] == middle_uuid)
    middle_def = GraphDef.model_validate(middle["definition"])
    assert middle_def.node("sub2").typed_config().version == 1


def test_subgraph_output_preserves_parent_context():
    config = SubgraphConfig(
        inputs=[CodeInput(name="topic", expression="query")],
        output_var="sub_out",
    )
    parent_state = {
        "inputs": {"x": 1},
        "variables": {"query": "hello"},
        "query": "hello",
        "route": "keep",
        "error": "parent-error",
    }

    mapped = nodes.map_subgraph_inputs(config, parent_state, "parent-key")
    assert mapped["inputs"] == {"topic": "hello", "query": "hello"}

    result = nodes.store_subgraph_output(
        "sub2",
        config,
        {**mapped, "answer": "A", "route": "child-route"},
        "parent-key",
    )

    assert result["answer"] == "A"
    assert result["inputs"] == {"x": 1}
    assert result["route"] == "keep"
    assert result["error"] == "parent-error"
    assert result["variables"]["sub_out"] == "A"
    assert result["variables"]["sub2"] == {"answer": "A", "candidate": "child-route"}


def test_publish_rejects_subgraph_when_feature_disabled(api_client, seed_app):
    parent_uuid, _ = seed_app(tenant_code="t", app_id="parent", api_key="key-parent")
    child_uuid, _ = seed_app(tenant_code="t", app_id="child", api_key="key-child", definition=_answer_graph("A"))

    response = api_client.post(
        f"/admin/apps/{parent_uuid}/graph/publish",
        json={"definition": _parent(child_uuid)},
    )

    assert response.status_code == 400
    assert "子图" in response.json()["detail"]


def test_subgraph_cycle_is_rejected_by_validator(monkeypatch):
    monkeypatch.setattr(
        "agent_platform.core.config.get_settings", lambda: Settings(subgraph_enabled=True)
    )
    self_definition = _parent("app-a")
    services.create_app(tenant_code="t", app_id="app-a", api_key="key-a", app_uuid="app-a")
    services.get_or_create_graph("app-a", "t")
    with session_scope() as session:
        graph = session.scalar(select(Graph).where(Graph.app_uuid == "app-a"))
        version = GraphVersion(
            uuid=uuid.uuid4().hex,
            graph_uuid=graph.uuid,
            version=1,
            definition=self_definition,
        )
        session.add(version)
        session.flush()
        graph.published_version_id = version.id
        graph.status = "published"

    with pytest.raises(ValueError, match="成环"):
        services.validate_subgraph_refs(GraphDef.model_validate(self_definition), "t")
