"""HITL Webhook 通知：开关、鉴权头、失败降级。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_platform.core import notifications


class _Response:
    def raise_for_status(self) -> None:
        return None


@pytest.mark.asyncio
async def test_notify_hitl_disabled_without_url(monkeypatch):
    called = False

    def fake_client(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(notifications.httpx, "AsyncClient", fake_client)

    assert await notifications.notify_hitl("agent.interrupt", {"x": 1}, SimpleNamespace()) is False
    assert not called


@pytest.mark.asyncio
async def test_notify_hitl_posts_event_and_secret(monkeypatch):
    seen: list[dict] = []

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json, headers):
            seen.append({"url": url, "json": json, "headers": headers, "timeout": self.timeout})
            return _Response()

    monkeypatch.setattr(notifications.httpx, "AsyncClient", FakeClient)
    settings = SimpleNamespace(
        hitl_webhook_url="https://hooks.example/hitl",
        hitl_webhook_secret="s3cret",
        hitl_webhook_timeout_seconds=1.5,
    )

    assert await notifications.notify_hitl("agent.interrupt", {"thread_id": "t1"}, settings) is True
    assert seen[0]["url"] == "https://hooks.example/hitl"
    assert seen[0]["json"] == {"event": "agent.interrupt", "payload": {"thread_id": "t1"}}
    assert seen[0]["headers"]["X-Webhook-Secret"] == "s3cret"
    assert seen[0]["timeout"] == 1.5


@pytest.mark.asyncio
async def test_notify_hitl_formats_slack_and_teams(monkeypatch):
    seen: list[dict] = []

    class FakeClient:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json, headers):
            seen.append({"url": url, "json": json})
            return _Response()

    monkeypatch.setattr(notifications.httpx, "AsyncClient", FakeClient)
    settings = SimpleNamespace(
        hitl_webhook_url="",
        hitl_slack_webhook_url="https://hooks.slack/x",
        hitl_teams_webhook_url="https://hooks.teams/x",
        hitl_webhook_attempts=1,
        hitl_webhook_timeout_seconds=1,
    )

    assert await notifications.notify_hitl("agent.interrupt", {"thread_id": "t1"}, settings) is True
    assert {item["url"] for item in seen} == {"https://hooks.slack/x", "https://hooks.teams/x"}
    assert all("text" in item["json"] for item in seen)
    teams = next(item for item in seen if "teams" in item["url"])
    assert teams["json"]["@type"] == "MessageCard"


@pytest.mark.asyncio
async def test_notify_hitl_retries_transient_failure(monkeypatch):
    class FlakyClient:
        calls = 0

        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            FlakyClient.calls += 1
            if FlakyClient.calls == 1:
                raise RuntimeError("temporary")
            return _Response()

    monkeypatch.setattr(notifications.httpx, "AsyncClient", FlakyClient)
    settings = SimpleNamespace(
        hitl_webhook_url="https://hooks.example/hitl",
        hitl_webhook_attempts=2,
        hitl_webhook_backoff_seconds=0,
    )

    assert await notifications.notify_hitl("agent.interrupt", {"thread_id": "t1"}, settings) is True
    assert FlakyClient.calls == 2


@pytest.mark.asyncio
async def test_notify_hitl_failure_is_swallowed(monkeypatch):
    class BrokenClient:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            raise RuntimeError("network down")

    monkeypatch.setattr(notifications.httpx, "AsyncClient", BrokenClient)
    settings = SimpleNamespace(
        hitl_webhook_url="https://hooks.example/hitl",
        hitl_webhook_attempts=1,
    )

    assert await notifications.notify_hitl("graph.interrupt", {"thread_id": "t1"}, settings) is False
