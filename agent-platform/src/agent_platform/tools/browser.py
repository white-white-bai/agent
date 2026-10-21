"""可选 Playwright 浏览器工具：导航 / 点击 / 输入 / 按键 / 取文本 / 截图。

默认关闭（AP_BROWSER_ENABLED=false），且需要 `pip install playwright && playwright install chromium`。
同一 thread_id 复用一个 page，运行结束由 agent runtime 调用 close_browser 清理。
"""
from __future__ import annotations

import ipaddress
import logging
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from langchain_core.tools import StructuredTool
from pydantic import Field, create_model

logger = logging.getLogger(__name__)


class BrowserError(RuntimeError):
    pass


class BrowserUnavailable(BrowserError):
    pass


def _load_playwright() -> Any:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise BrowserUnavailable(
            "浏览器工具不可用：请安装 playwright 与 chromium（pip install playwright && playwright install chromium）"
        ) from exc
    return async_playwright


def _host_allowed(host: str, settings: Any) -> bool:
    allowed = [
        item.strip().lower()
        for item in str(getattr(settings, "browser_allowed_hosts", "") or "").split(",")
        if item.strip()
    ]
    if allowed and not any(host == item or host.endswith(f".{item}") for item in allowed):
        return False
    if getattr(settings, "browser_allow_private", False):
        return True
    if host in ("localhost", "0.0.0.0") or host.endswith(".local"):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
    )


def validate_url(url: str, settings: Any) -> str:
    raw = str(url or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise BrowserError("浏览器只允许 http/https URL")
    host = (parsed.hostname or "").lower()
    if not host:
        raise BrowserError("URL 缺少 host")
    if not _host_allowed(host, settings):
        raise BrowserError(f"URL host 不在允许范围：{host}")
    return raw


class BrowserSession:
    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None

    async def start(self) -> None:
        if self._page is not None:
            return
        async_playwright = _load_playwright()
        try:
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                headless=bool(getattr(self.settings, "browser_headless", True))
            )
            context_kwargs: dict[str, Any] = {"ignore_https_errors": False, "accept_downloads": True}
            state_path = str(getattr(self.settings, "browser_storage_state", "") or "")
            if state_path and Path(state_path).exists():
                context_kwargs["storage_state"] = state_path
            self._context = await self._browser.new_context(**context_kwargs)
            self._page = await self._context.new_page()
            self._page.set_default_timeout(int(getattr(self.settings, "browser_timeout_ms", 15000) or 15000))
        except BrowserError:
            raise
        except Exception as exc:
            await self.close()
            raise BrowserUnavailable(f"浏览器启动失败: {exc}") from exc

    async def close(self) -> None:
        state_path = str(getattr(self.settings, "browser_storage_state", "") or "")
        if state_path and self._context is not None:
            try:
                Path(state_path).parent.mkdir(parents=True, exist_ok=True)
                await self._context.storage_state(path=state_path)
            except Exception:
                logger.warning("保存浏览器登录态失败：%s", state_path, exc_info=True)
        for name in ("_context", "_browser", "_pw"):
            obj = getattr(self, name, None)
            setattr(self, name, None)
            if obj is not None:
                try:
                    await obj.close()
                except Exception:
                    logger.debug("关闭浏览器资源失败：%s", name, exc_info=True)
        self._page = None

    async def page(self) -> Any:
        await self.start()
        return self._page

    def _limit(self) -> int:
        return max(int(getattr(self.settings, "browser_max_chars", 4000) or 4000), 1)

    async def snapshot(self) -> str:
        page = await self.page()
        title = await page.title()
        text = await page.locator("body").inner_text()
        return f"URL: {page.url}\nTITLE: {title}\n{str(text)[: self._limit()]}"

    async def goto(self, url: str) -> str:
        page = await self.page()
        await page.goto(validate_url(url, self.settings), wait_until="domcontentloaded")
        return await self.snapshot()

    async def click(self, selector: str) -> str:
        page = await self.page()
        await page.locator(selector).first.click()
        return await self.snapshot()

    async def fill(self, selector: str, text: str) -> str:
        page = await self.page()
        await page.locator(selector).first.fill(text)
        return await self.snapshot()

    async def press(self, key: str) -> str:
        page = await self.page()
        await page.keyboard.press(key)
        return await self.snapshot()

    async def text(self, selector: str = "") -> str:
        page = await self.page()
        value = await (page.locator(selector).first.inner_text() if selector else page.locator("body").inner_text())
        return str(value)[: self._limit()]

    async def screenshot(self) -> str:
        page = await self.page()
        directory = Path(str(getattr(self.settings, "browser_screenshot_dir", ".run/browser") or ".run/browser"))
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{uuid.uuid4().hex}.png"
        await page.screenshot(path=str(path), full_page=True)
        return str(path)

    async def download(self, selector: str) -> str:
        page = await self.page()
        async with page.expect_download() as info:
            await page.locator(selector).first.click()
        download = await info.value
        directory = Path(str(getattr(self.settings, "browser_download_dir", ".run/downloads") or ".run/downloads"))
        directory.mkdir(parents=True, exist_ok=True)
        name = str(getattr(download, "suggested_filename", "") or f"{uuid.uuid4().hex}.bin")
        path = directory / name
        await download.save_as(str(path))
        return str(path)


_SESSIONS: dict[str, BrowserSession] = {}


async def get_session(thread_id: str, settings: Any) -> BrowserSession:
    key = thread_id or "__default__"
    session = _SESSIONS.get(key)
    if session is None:
        session = BrowserSession(settings)
        _SESSIONS[key] = session
    return session


async def close_browser(thread_id: str) -> None:
    session = _SESSIONS.pop(thread_id or "__default__", None)
    if session is not None:
        await session.close()


async def close_all() -> None:
    for key in list(_SESSIONS):
        await close_browser(key)


def build_browser_tools(
    settings: Any,
    thread_id: str,
    guard: Callable[[Any, str], Any] | None = None,
) -> list[StructuredTool]:
    if not getattr(settings, "browser_enabled", False):
        return []

    def _wrap(value: Any, source: str) -> Any:
        return guard(value, source) if guard is not None else value

    async def _open(url: str) -> Any:
        session = await get_session(thread_id, settings)
        return _wrap(await session.goto(url), "browser_open")

    async def _click(selector: str) -> Any:
        session = await get_session(thread_id, settings)
        return _wrap(await session.click(selector), "browser_click")

    async def _fill(selector: str, text: str) -> Any:
        session = await get_session(thread_id, settings)
        return _wrap(await session.fill(selector, text), "browser_fill")

    async def _press(key: str) -> Any:
        session = await get_session(thread_id, settings)
        return _wrap(await session.press(key), "browser_press")

    async def _text(selector: str = "") -> Any:
        session = await get_session(thread_id, settings)
        return _wrap(await session.text(selector), "browser_text")

    async def _screenshot() -> Any:
        session = await get_session(thread_id, settings)
        return _wrap(await session.screenshot(), "browser_screenshot")

    async def _download(selector: str) -> Any:
        session = await get_session(thread_id, settings)
        return _wrap(await session.download(selector), "browser_download")

    return [
        StructuredTool.from_function(
            coroutine=_open,
            name="browser_open",
            description="打开一个 http/https 页面并返回标题与正文。",
            args_schema=create_model("browser_open_args", url=(str, Field(..., description="页面 URL"))),
        ),
        StructuredTool.from_function(
            coroutine=_click,
            name="browser_click",
            description="点击 CSS selector 对应的元素，返回操作后的页面文本。",
            args_schema=create_model("browser_click_args", selector=(str, Field(..., description="CSS selector"))),
        ),
        StructuredTool.from_function(
            coroutine=_fill,
            name="browser_fill",
            description="在输入框中填写文本，返回操作后的页面文本。",
            args_schema=create_model(
                "browser_fill_args",
                selector=(str, Field(..., description="CSS selector")),
                text=(str, Field(..., description="要填写的文本")),
            ),
        ),
        StructuredTool.from_function(
            coroutine=_press,
            name="browser_press",
            description="按下键盘按键（如 Enter / Tab），返回操作后的页面文本。",
            args_schema=create_model("browser_press_args", key=(str, Field(..., description="按键名"))),
        ),
        StructuredTool.from_function(
            coroutine=_text,
            name="browser_text",
            description="读取页面正文或指定 selector 的文本。",
            args_schema=create_model(
                "browser_text_args",
                selector=(str, Field(default="", description="可选 CSS selector")),
            ),
        ),
        StructuredTool.from_function(
            coroutine=_screenshot,
            name="browser_screenshot",
            description="截取当前页面并返回截图文件路径。",
        ),
        StructuredTool.from_function(
            coroutine=_download,
            name="browser_download",
            description="点击 selector 触发下载并返回保存路径（适合 CSV 等附件）。",
            args_schema=create_model(
                "browser_download_args", selector=(str, Field(..., description="触发下载的 CSS selector"))
            ),
        ),
    ]
