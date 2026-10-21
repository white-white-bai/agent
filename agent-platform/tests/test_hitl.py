"""人工审批节点与管理端 interrupt/resume。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from agent_platform.api import admin as admin_mod
from agent_platform.api import services
from agent_platform.core.config import Settings
from agent_platform.core.db import session_scope
from agent_platform.domain.models import Run

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


def test_hitl_disabled_auto_approves_and_keeps_final_last(api_client, seed_app, monkeypatch):
    app_uuid, _ = seed_app(tenant_code="t", app_id="app-1", api_key="key-1")
    monkeypatch.setattr(admin_mod, "get_settings", lambda: Settings(hitl_enabled=False))

    response = api_client.post(
        f"/admin/apps/{app_uuid}/graph/run",
        json={"definition": DEFINITION, "inputs": {}},
    )

    assert response.status_code == 200
    events = _events(response)
    types = [item["type"] for item in events]
    assert "interrupt" not in types
    assert types[-1] == "final"
    assert events[-1]["answer"] == "approved"
    assert services.list_runs("t") == []


def test_hitl_interrupt_then_resume_approve(api_client, seed_app, monkeypatch):
    app_uuid, _ = seed_app(tenant_code="t", app_id="app-1", api_key="key-1")
    monkeypatch.setattr(admin_mod, "get_settings", lambda: Settings(hitl_enabled=True))

    response = api_client.post(
        f"/admin/apps/{app_uuid}/graph/run",
        json={"definition": DEFINITION, "inputs": {}},
    )

    events = _events(response)
    types = [item["type"] for item in events]
    assert "run_started" in types
    assert "interrupt" in types
    assert types[-1] == "final"
    started = next(item for item in events if item["type"] == "run_started")
    thread_id = started["thread_id"]
    run = services.get_run(thread_id)
    assert run is not None and run.status == "interrupted"

    resumed = api_client.post(
        f"/admin/runs/{thread_id}/resume",
        json={"action": "approve", "payload": {"note": "ok"}},
    )
    resumed_events = _events(resumed)
    assert resumed_events[-1]["type"] == "final"
    assert resumed_events[-1]["answer"] == "approved"
    assert services.get_run(thread_id).status == "completed"


def test_hitl_resume_reject_routes_to_reject_branch(api_client, seed_app, monkeypatch):
    app_uuid, _ = seed_app(tenant_code="t", app_id="app-1", api_key="key-1")
    monkeypatch.setattr(admin_mod, "get_settings", lambda: Settings(hitl_enabled=True))

    response = api_client.post(
        f"/admin/apps/{app_uuid}/graph/run",
        json={"definition": DEFINITION, "inputs": {}},
    )
    events = _events(response)
    thread_id = next(item for item in events if item["type"] == "run_started")["thread_id"]

    resumed = api_client.post(
        f"/admin/runs/{thread_id}/resume",
        json={"action": "reject", "payload": {"reason": "no"}},
    )
    resumed_events = _events(resumed)
    assert resumed_events[-1]["type"] == "final"
    assert resumed_events[-1]["answer"] == "rejected"


def test_hitl_resume_conflicts_when_not_interrupted(api_client, seed_app, monkeypatch):
    app_uuid, _ = seed_app(tenant_code="t", app_id="app-1", api_key="key-1")
    monkeypatch.setattr(admin_mod, "get_settings", lambda: Settings(hitl_enabled=True))

    response = api_client.post(
        f"/admin/apps/{app_uuid}/graph/run",
        json={"definition": DEFINITION, "inputs": {}},
    )
    events = _events(response)
    thread_id = next(item for item in events if item["type"] == "run_started")["thread_id"]
    api_client.post(f"/admin/runs/{thread_id}/resume", json={"action": "approve"})

    conflict = api_client.post(f"/admin/runs/{thread_id}/resume", json={"action": "approve"})
    assert conflict.status_code == 409


def test_hitl_rejects_unknown_action(api_client, seed_app, monkeypatch):
    app_uuid, _ = seed_app(tenant_code="t", app_id="app-1", api_key="key-1")
    monkeypatch.setattr(admin_mod, "get_settings", lambda: Settings(hitl_enabled=True))
    response = api_client.post(
        f"/admin/apps/{app_uuid}/graph/run",
        json={"definition": DEFINITION, "inputs": {}},
    )
    thread_id = next(item for item in _events(response) if item["type"] == "run_started")["thread_id"]

    bad = api_client.post(f"/admin/runs/{thread_id}/resume", json={"action": "ghost"})
    assert bad.status_code == 400
    assert services.get_run(thread_id).status == "interrupted"

    ok = api_client.post(f"/admin/runs/{thread_id}/resume", json={"action": "approve"})
    assert _events(ok)[-1]["answer"] == "approved"


def test_hitl_resume_records_audit_fields(api_client, seed_app, monkeypatch):
    app_uuid, _ = seed_app(tenant_code="t", app_id="app-1", api_key="key-1")
    monkeypatch.setattr(admin_mod, "get_settings", lambda: Settings(hitl_enabled=True))
    response = api_client.post(
        f"/admin/apps/{app_uuid}/graph/run",
        json={"definition": DEFINITION, "inputs": {}},
    )
    thread_id = next(item for item in _events(response) if item["type"] == "run_started")["thread_id"]

    api_client.post(f"/admin/runs/{thread_id}/resume", json={"action": "approve"})

    run = services.get_run(thread_id)
    assert run.status == "completed"
    assert run.resolved_by == "anonymous"
    assert run.resolved_at is not None


def test_hitl_cancel_prevents_resume(api_client, seed_app, monkeypatch):
    app_uuid, _ = seed_app(tenant_code="t", app_id="app-1", api_key="key-1")
    monkeypatch.setattr(admin_mod, "get_settings", lambda: Settings(hitl_enabled=True))
    response = api_client.post(
        f"/admin/apps/{app_uuid}/graph/run",
        json={"definition": DEFINITION, "inputs": {}},
    )
    thread_id = next(item for item in _events(response) if item["type"] == "run_started")["thread_id"]

    cancelled = api_client.post(f"/admin/runs/{thread_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"] == "cancelled"
    assert api_client.post(f"/admin/runs/{thread_id}/resume", json={"action": "approve"}).status_code == 409


def test_hitl_claim_is_atomic():
    services.create_run(
        tenant_code="t",
        app_uuid="a1",
        thread_id="claim-thread",
        graph_definition=DEFINITION,
    )
    services.update_run("claim-thread", status="interrupted")

    assert services.claim_run("claim-thread", "a") is True
    assert services.claim_run("claim-thread", "b") is False


def test_hitl_expire_stale_runs():
    services.create_run(
        tenant_code="t",
        app_uuid="a1",
        thread_id="stale-thread",
        graph_definition=DEFINITION,
    )
    services.update_run("stale-thread", status="interrupted")
    with session_scope() as session:
        row = session.scalar(select(Run).where(Run.thread_id == "stale-thread"))
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=120)

    expired = services.expire_stale_runs(60, "t")

    assert expired >= 1
    assert services.get_run("stale-thread").status == "expired"


def test_external_chat_auto_approves_without_interrupt(api_client, seed_app):
    seed_app(tenant_code="t", app_id="app-1", api_key="key-1", definition=DEFINITION)

    response = api_client.post(
        "/v1/chat-messages",
        json={"query": "hi", "user": "u1"},
        headers={"Api-Key": "key-1"},
    )

    assert response.status_code == 200
    assert "message_end" in response.text
    assert "approved" in response.text
    assert "interrupt" not in response.text
