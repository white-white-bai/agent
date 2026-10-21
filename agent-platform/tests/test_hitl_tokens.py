"""HITL 审批 token：签名、过期、篡改与一键链接。"""
from __future__ import annotations

import pytest

from agent_platform.core.config import Settings
from agent_platform.core.hitl_tokens import (
    HitlTokenError,
    approval_links,
    make_action_token,
    verify_action_token,
)


def _token(**overrides):
    data = {
        "kind": "graph",
        "app_uuid": "app-1",
        "thread_id": "thread-1",
        "interrupt_id": "int-1",
        "secret": "secret",
        "ttl_seconds": 60,
    }
    data.update(overrides)
    return make_action_token(**data)


def test_token_roundtrip_binds_fields():
    payload = verify_action_token(_token(), "secret")
    assert payload["kind"] == "graph"
    assert payload["app_uuid"] == "app-1"
    assert payload["thread_id"] == "thread-1"
    assert payload["interrupt_id"] == "int-1"


def test_token_rejects_tamper_and_wrong_secret():
    token = _token()
    with pytest.raises(HitlTokenError):
        verify_action_token(token + "x", "secret")
    with pytest.raises(HitlTokenError):
        verify_action_token(token, "other")


def test_token_rejects_expired_and_bad_kind(monkeypatch):
    from agent_platform.core import hitl_tokens

    monkeypatch.setattr(hitl_tokens.time, "time", lambda: 1000)
    token = _token(ttl_seconds=1)
    monkeypatch.setattr(hitl_tokens.time, "time", lambda: 2000)
    with pytest.raises(HitlTokenError, match="过期"):
        verify_action_token(token, "secret")
    with pytest.raises(HitlTokenError):
        verify_action_token(_token(kind="unknown"), "secret")


def test_approval_links_require_secret_and_use_base_url():
    assert approval_links(
        kind="graph", app_uuid="a", thread_id="t", interrupt_id="i", settings=Settings()
    ) == {}

    links = approval_links(
        kind="graph",
        app_uuid="a",
        thread_id="t",
        interrupt_id="i",
        settings=Settings(hitl_webhook_secret="secret", hitl_callback_base_url="https://api.example"),
    )
    assert links["approve_url"] == "https://api.example/webhooks/hitl/approve"
    assert links["reject_url"] == "https://api.example/webhooks/hitl/reject"
    assert verify_action_token(links["token"], "secret")["interrupt_id"] == "i"
