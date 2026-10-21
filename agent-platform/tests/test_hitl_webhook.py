"""外部 HITL 审批回调：签名后恢复图运行，并拒绝重放/篡改。"""
from __future__ import annotations

import json
from types import SimpleNamespace

from agent_platform.agentapp.schema import AgentAppDef
from agent_platform.api import admin as admin_mod
from agent_platform.api import hitl_webhook as webhook_mod
from agent_platform.api import services
from agent_platform.core.config import Settings
from agent_platform.core.hitl_tokens import graph_interrupt_id, make_action_token

DEFINITION = {
    "schema_version": "1.1",
    "nodes": [
        {"id": "start1", "type": "start"},
        {
            "id": "approval2",
            "type": "approval",
            "title": "人工确认",
            "config": {
                "question": "确认继续吗？",
                "options": ["approve", "reject"],
                "output_var": "approval",
                "default_action": "approve",
            },
        },
        {"id": "ok3", "type": "answer", "config": {"template": "approved", "output_var": "answer"}},
        {"id": "no4", "type": "answer", "config": {"template": "rejected", "output_var": "answer"}},
        {"id": "end5", "type": "end"},
    ],
    "edges": [
        {"id": "e1", "source": "start1", "target": "approval2"},
        {"id": "e2", "source": "approval2", "target": "ok3", "source_handle": "approve"},
        {"id": "e3", "source": "approval2", "target": "no4", "source_handle": "reject"},
        {"id": "e4", "source": "ok3", "target": "end5"},
        {"id": "e5", "source": "no4", "target": "end5"},
    ],
}


def _events(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def _interrupted_run(api_client, seed_app, monkeypatch):
    app_uuid, _ = seed_app(tenant_code="t", app_id="app-1", api_key="key-1")
    monkeypatch.setattr(
        admin_mod,
        "get_settings",
        lambda: Settings(hitl_enabled=True, hitl_webhook_secret="secret"),
    )
    response = api_client.post(
        f"/admin/apps/{app_uuid}/graph/run",
        json={"definition": DEFINITION, "inputs": {}},
    )
    thread_id = next(item for item in _events(response) if item["type"] == "run_started")["thread_id"]
    run = services.get_run(thread_id)
    return app_uuid, thread_id, graph_interrupt_id(run.interrupt_payload or {})


def test_hitl_webhook_resumes_once(api_client, seed_app, monkeypatch):
    monkeypatch.setattr(
        webhook_mod, "get_settings", lambda: Settings(hitl_webhook_secret="secret")
    )
    app_uuid, thread_id, interrupt_id = _interrupted_run(api_client, seed_app, monkeypatch)
    token = make_action_token(
        kind="graph",
        app_uuid=app_uuid,
        thread_id=thread_id,
        interrupt_id=interrupt_id,
        secret="secret",
    )

    response = api_client.post("/webhooks/hitl/approve", json={"token": token})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "completed"
    assert data["answer"] == "approved"
    assert services.get_run(thread_id).status == "completed"

    replay = api_client.post("/webhooks/hitl/approve", json={"token": token})
    assert replay.status_code == 409


def test_hitl_webhook_rejects_tampered_token(api_client, seed_app, monkeypatch):
    monkeypatch.setattr(
        webhook_mod, "get_settings", lambda: Settings(hitl_webhook_secret="secret")
    )
    _app_uuid, _thread_id, _interrupt_id = _interrupted_run(api_client, seed_app, monkeypatch)

    response = api_client.post("/webhooks/hitl/approve", json={"token": "bad.token"})

    assert response.status_code == 403


def test_hitl_webhook_rejects_unknown_decision(api_client, monkeypatch):
    monkeypatch.setattr(
        webhook_mod, "get_settings", lambda: Settings(hitl_webhook_secret="secret")
    )
    response = api_client.post("/webhooks/hitl/maybe", json={"token": "x"})
    assert response.status_code == 400


def test_claim_hitl_action_is_cross_request_idempotent():
    assert services.claim_hitl_action("graph", "thread-x", "int-x", "approve") is True
    assert services.claim_hitl_action("graph", "thread-x", "int-x", "reject") is False
    assert services.claim_hitl_action("graph", "thread-x", "int-y", "approve") is True


def test_hitl_actions_endpoint_filters_tenant(api_client):
    services.claim_hitl_action("graph", "thread-t", "int-t", "approve", tenant_code="t")
    services.claim_hitl_action("graph", "thread-o", "int-o", "reject", tenant_code="other")

    response = api_client.get("/admin/hitl-actions", params={"tenant_code": "t"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["thread_id"] == "thread-t"
    assert data["items"][0]["decision"] == "approve"


def test_hitl_webhook_agent_route(api_client, monkeypatch):
    monkeypatch.setattr(
        webhook_mod, "get_settings", lambda: Settings(hitl_webhook_secret="secret")
    )
    monkeypatch.setattr(webhook_mod.services, "get_app_by_uuid", lambda _uuid: SimpleNamespace(tenant_code="t"))
    monkeypatch.setattr(webhook_mod.services, "get_published_agent", lambda _uuid: AgentAppDef())
    monkeypatch.setattr(webhook_mod, "get_checkpointer", lambda: object())

    async def pending(*args, **kwargs):
        return {"interrupt_id": "int-agent", "prompt": "approve?"}

    async def fake_resume(*args, **kwargs):
        yield {"type": "final", "answer": "agent-approved"}

    monkeypatch.setattr(webhook_mod, "pending_agent_interrupt", pending)
    monkeypatch.setattr(webhook_mod, "resume_agent", fake_resume)
    token = make_action_token(
        kind="agent",
        app_uuid="app-1",
        thread_id="conv-1",
        interrupt_id="int-agent",
        secret="secret",
    )

    response = api_client.post("/webhooks/hitl/approve", json={"token": token})

    assert response.status_code == 200
    assert response.json()["data"] == {
        "kind": "agent",
        "thread_id": "conv-1",
        "status": "completed",
        "answer": "agent-approved",
    }
