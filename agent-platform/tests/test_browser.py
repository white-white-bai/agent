"""可选浏览器工具：URL 安全边界、工具装配、无 Playwright 时失败关闭。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_platform.agentapp.schema import AgentAppDef
from agent_platform.agentapp.tools import build_agent_tools
from agent_platform.core.config import Settings
from agent_platform.engine.context import EngineContext
from agent_platform.tools import browser


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "javascript:alert(1)", "http://localhost:8080", "http://127.0.0.1/"],
)
def test_validate_url_blocks_non_public_schemes_and_hosts(url):
    settings = SimpleNamespace(browser_allowed_hosts="", browser_allow_private=False)
    with pytest.raises(browser.BrowserError):
        browser.validate_url(url, settings)


def test_validate_url_allowlist_and_private_override():
    settings = SimpleNamespace(browser_allowed_hosts="example.com", browser_allow_private=False)
    assert browser.validate_url("https://sub.example.com/a", settings).startswith("https://")
    with pytest.raises(browser.BrowserError):
        browser.validate_url("https://evil.com", settings)

    private = SimpleNamespace(browser_allowed_hosts="", browser_allow_private=True)
    assert browser.validate_url("http://127.0.0.1:8000", private).startswith("http://")


@pytest.mark.asyncio
async def test_browser_tools_only_assembled_when_enabled():
    ctx = EngineContext(llm=None)
    enabled = Settings(browser_enabled=True)
    tools, _ = await build_agent_tools(
        AgentAppDef(browser=True), enabled, ctx, tenant_code="t", thread_id="th"
    )
    names = {tool.name for tool in tools}
    assert {"browser_open", "browser_click", "browser_fill", "browser_text"} <= names

    disabled, _ = await build_agent_tools(
        AgentAppDef(browser=True), Settings(browser_enabled=False), ctx, tenant_code="t", thread_id="th"
    )
    assert all(not tool.name.startswith("browser_") for tool in disabled)


class _FakeLocator:
    async def inner_text(self) -> str:
        return "页面正文"


class _FakePage:
    url = "https://example.com/page"

    async def title(self) -> str:
        return "示例页"

    async def goto(self, url: str, wait_until: str = "") -> None:
        return None

    def set_default_timeout(self, value: int) -> None:
        return None

    def locator(self, selector: str) -> _FakeLocator:
        return _FakeLocator()


@pytest.mark.asyncio
async def test_browser_session_snapshot_with_fake_page():
    session = browser.BrowserSession(SimpleNamespace(browser_max_chars=100))
    session._page = _FakePage()

    snapshot = await session.goto("https://example.com")

    assert "TITLE: 示例页" in snapshot
    assert "页面正文" in snapshot


@pytest.mark.asyncio
async def test_browser_tool_wiring_and_guard(monkeypatch):
    class FakeSession:
        async def goto(self, url: str) -> str:
            return f"PAGE:{url}"

    async def fake_get_session(thread_id: str, settings):
        return FakeSession()

    monkeypatch.setattr(browser, "get_session", fake_get_session)
    settings = SimpleNamespace(browser_enabled=True)
    tools = browser.build_browser_tools(
        settings, "th", guard=lambda value, source: f"[{source}]{value}"
    )
    open_tool = next(tool for tool in tools if tool.name == "browser_open")

    assert await open_tool.ainvoke({"url": "https://example.com"}) == "[browser_open]PAGE:https://example.com"


@pytest.mark.asyncio
async def test_browser_start_fails_closed_without_playwright(monkeypatch):
    def unavailable():
        raise browser.BrowserUnavailable("playwright missing")

    monkeypatch.setattr(browser, "_load_playwright", unavailable)
    session = browser.BrowserSession(SimpleNamespace())

    with pytest.raises(browser.BrowserUnavailable, match="playwright missing"):
        await session.start()
