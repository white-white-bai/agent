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
        self._pages: list[Any] = []

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
            self._pages = [self._page]
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
        self._pages = []

    async def page(self) -> Any:
        await self.start()
        return self._page

    def _limit(self) -> int:
        return max(int(getattr(self.settings, "browser_max_chars", 4000) or 4000), 1)

    async def snapshot(self) -> str:
        page = await self.page()
        title = await page.title()
        text = await page.locator("body").inner_text()
        frames = [
            f"- {getattr(frame, 'name', '') or '(unnamed)'}: {getattr(frame, 'url', '')}"
            for frame in getattr(page, "frames", [])
            if frame is not getattr(page, "main_frame", frame)
        ]
        frame_text = f"\nFRAMES:\n{chr(10).join(frames)}" if frames else ""
        return f"URL: {page.url}\nTITLE: {title}\n{str(text)[: self._limit()]}{frame_text}"

    def _root(self, page: Any, frame_selector: str = "") -> Any:
        if frame_selector:
            return page.frame_locator(frame_selector)
        return page

    async def goto(self, url: str) -> str:
        page = await self.page()
        await page.goto(validate_url(url, self.settings), wait_until="domcontentloaded")
        return await self.snapshot()

    async def click(self, selector: str, frame_selector: str = "") -> str:
        page = await self.page()
        await self._root(page, frame_selector).locator(selector).first.click()
        return await self.snapshot()

    async def click_xy(self, x: float, y: float) -> str:
        page = await self.page()
        await page.mouse.click(float(x), float(y))
        return await self.snapshot()

    async def scroll(self, delta_y: int) -> str:
        page = await self.page()
        await page.mouse.wheel(0, int(delta_y))
        return await self.snapshot()

    async def fill(self, selector: str, text: str, frame_selector: str = "") -> str:
        page = await self.page()
        await self._root(page, frame_selector).locator(selector).first.fill(text)
        return await self.snapshot()

    async def press(self, key: str, selector: str = "", frame_selector: str = "") -> str:
        page = await self.page()
        if selector:
            await self._root(page, frame_selector).locator(selector).first.press(key)
        else:
            await page.keyboard.press(key)
        return await self.snapshot()

    async def text(self, selector: str = "", frame_selector: str = "") -> str:
        page = await self.page()
        root = self._root(page, frame_selector)
        value = await (root.locator(selector).first.inner_text() if selector else root.locator("body").inner_text())
        return str(value)[: self._limit()]

    async def frames(self) -> list[dict[str, Any]]:
        page = await self.page()
        main = getattr(page, "main_frame", None)
        return [
            {
                "index": index,
                "name": getattr(frame, "name", "") or "",
                "url": getattr(frame, "url", "") or "",
                "main": frame is main,
            }
            for index, frame in enumerate(getattr(page, "frames", []))
        ]

    async def captcha(self) -> dict[str, Any]:
        """检测常见人机验证；不尝试绕过，交由人工处理。"""
        page = await self.page()
        selectors = (
            'iframe[src*="recaptcha"]',
            'iframe[src*="hcaptcha"]',
            'iframe[src*="turnstile"]',
            ".g-recaptcha",
            ".h-captcha",
            "[data-sitekey]",
            'img[src*="captcha"]',
            "#captcha",
        )
        found: list[str] = []
        for selector in selectors:
            try:
                if await page.locator(selector).count() > 0:
                    found.append(selector)
            except Exception:
                logger.debug("CAPTCHA selector 探测失败：%s", selector, exc_info=True)
                continue
        return {
            "found": bool(found),
            "selectors": found,
            "message": "检测到人机验证，需要人工完成后再继续。" if found else "未检测到人机验证。",
        }

    async def inspect(self) -> str:
        """返回带编号/坐标的可交互元素与截图路径，供按坐标点击。"""
        page = await self.page()
        elements = await page.evaluate(
            """() => Array.from(document.querySelectorAll(
                'a,button,input,select,textarea,[role="button"],[onclick]'
            )).map((el) => {
                const r = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                const text = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim();
                return {
                    tag: el.tagName.toLowerCase(),
                    type: el.getAttribute('type') || '',
                    text: text.slice(0, 80),
                    x: r.x, y: r.y, width: r.width, height: r.height,
                    visible: r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none'
                };
            }).filter((e) => e.visible).slice(0, 120)"""
        )
        lines = []
        for index, item in enumerate(elements or [], start=1):
            x = round(float(item.get("x") or 0) + float(item.get("width") or 0) / 2)
            y = round(float(item.get("y") or 0) + float(item.get("height") or 0) / 2)
            label = item.get("text") or item.get("type") or ""
            lines.append(f"[{index}] <{item.get('tag')}> {label} @ ({x}, {y})")
        path = await self.screenshot()
        body = "\n".join(lines) if lines else "（未发现可交互元素）"
        return f"{body}\nSCREENSHOT: {path}"

    async def screenshot(self) -> str:
        page = await self.page()
        directory = Path(str(getattr(self.settings, "browser_screenshot_dir", ".run/browser") or ".run/browser"))
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{uuid.uuid4().hex}.png"
        await page.screenshot(path=str(path), full_page=True)
        return str(path)

    async def look(self, question: str = "") -> str:
        """截图并交给多模态模型理解；只返回文字，不落盘。"""
        import base64

        from langchain_core.messages import HumanMessage

        from agent_platform.models.factory import resolve_llm_model

        page = await self.page()
        image = await page.screenshot(type="png", full_page=True)
        if not isinstance(image, (bytes, bytearray)):
            raise BrowserError("截图失败：页面未返回图片数据")
        provider = str(getattr(self.settings, "browser_vision_provider", "") or "")
        _, entry = resolve_llm_model(self.settings, provider)
        model = entry.get("model") or ""
        if not model:
            raise BrowserError(f"视觉模型条目缺少 model 字段: {provider or 'default'}")
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=model,
            base_url=entry.get("base_url") or None,
            api_key=entry.get("api_key") or "sk-placeholder",
            temperature=0.0,
            max_tokens=int(getattr(self.settings, "browser_vision_max_tokens", 800) or 800),
        )
        prompt = question or "描述当前页面的可见内容，并指出下一步可操作的关键元素。"
        encoded = base64.b64encode(bytes(image)).decode("ascii")
        message = HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
            ]
        )
        result = await llm.ainvoke([message])
        return str(result.content or "")[: self._limit()]

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

    async def upload(self, selector: str, file_path: str) -> str:
        upload_root = str(getattr(self.settings, "browser_upload_dir", "") or "")
        if not upload_root:
            raise BrowserError("browser_upload 未配置 AP_BROWSER_UPLOAD_DIR")
        root = Path(upload_root).resolve()
        target = Path(file_path).resolve()
        if target != root and root not in target.parents:
            raise BrowserError("上传文件必须位于 AP_BROWSER_UPLOAD_DIR 内")
        if not target.is_file():
            raise BrowserError(f"上传文件不存在：{file_path}")
        page = await self.page()
        await page.locator(selector).first.set_input_files(str(target))
        return await self.snapshot()

    async def new_tab(self, url: str = "") -> str:
        context = self._context
        if context is None:
            await self.start()
            context = self._context
        page = await context.new_page()
        page.set_default_timeout(int(getattr(self.settings, "browser_timeout_ms", 15000) or 15000))
        self._pages.append(page)
        self._page = page
        if url:
            await page.goto(validate_url(url, self.settings), wait_until="domcontentloaded")
        return await self.snapshot()

    async def tabs(self) -> list[dict[str, Any]]:
        return [
            {"index": index, "url": getattr(page, "url", ""), "active": page is self._page}
            for index, page in enumerate(self._pages)
        ]

    async def switch_tab(self, index: int) -> str:
        if index < 0 or index >= len(self._pages):
            raise BrowserError(f"标签页不存在：{index}")
        self._page = self._pages[index]
        return await self.snapshot()

    async def close_tab(self, index: int | None = None) -> str:
        if not self._pages:
            return "（无标签页）"
        selected = len(self._pages) - 1 if index is None else index
        if selected < 0 or selected >= len(self._pages):
            raise BrowserError(f"标签页不存在：{selected}")
        page = self._pages.pop(selected)
        await page.close()
        if not self._pages:
            self._page = None
            return "（无标签页）"
        self._page = self._pages[min(selected, len(self._pages) - 1)]
        return await self.snapshot()


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

    async def _click(selector: str, frame_selector: str = "") -> Any:
        session = await get_session(thread_id, settings)
        return _wrap(await session.click(selector, frame_selector), "browser_click")

    async def _click_xy(x: float, y: float) -> Any:
        session = await get_session(thread_id, settings)
        return _wrap(await session.click_xy(x, y), "browser_click_xy")

    async def _scroll(delta_y: int) -> Any:
        session = await get_session(thread_id, settings)
        return _wrap(await session.scroll(delta_y), "browser_scroll")

    async def _fill(selector: str, text: str, frame_selector: str = "") -> Any:
        session = await get_session(thread_id, settings)
        return _wrap(await session.fill(selector, text, frame_selector), "browser_fill")

    async def _press(key: str, selector: str = "", frame_selector: str = "") -> Any:
        session = await get_session(thread_id, settings)
        return _wrap(await session.press(key, selector, frame_selector), "browser_press")

    async def _text(selector: str = "", frame_selector: str = "") -> Any:
        session = await get_session(thread_id, settings)
        return _wrap(await session.text(selector, frame_selector), "browser_text")

    async def _inspect() -> Any:
        session = await get_session(thread_id, settings)
        return _wrap(await session.inspect(), "browser_inspect")

    async def _frames() -> Any:
        session = await get_session(thread_id, settings)
        return _wrap(await session.frames(), "browser_frames")

    async def _captcha() -> Any:
        session = await get_session(thread_id, settings)
        return _wrap(await session.captcha(), "browser_captcha")

    async def _screenshot() -> Any:
        session = await get_session(thread_id, settings)
        return _wrap(await session.screenshot(), "browser_screenshot")

    async def _look(question: str = "") -> Any:
        session = await get_session(thread_id, settings)
        return _wrap(await session.look(question), "browser_look")

    async def _download(selector: str) -> Any:
        session = await get_session(thread_id, settings)
        return _wrap(await session.download(selector), "browser_download")

    async def _upload(selector: str, file_path: str) -> Any:
        session = await get_session(thread_id, settings)
        return _wrap(await session.upload(selector, file_path), "browser_upload")

    async def _new_tab(url: str = "") -> Any:
        session = await get_session(thread_id, settings)
        return _wrap(await session.new_tab(url), "browser_new_tab")

    async def _tabs() -> Any:
        session = await get_session(thread_id, settings)
        return _wrap(await session.tabs(), "browser_tabs")

    async def _switch_tab(index: int) -> Any:
        session = await get_session(thread_id, settings)
        return _wrap(await session.switch_tab(index), "browser_switch_tab")

    async def _close_tab(index: int | None = None) -> Any:
        session = await get_session(thread_id, settings)
        return _wrap(await session.close_tab(index), "browser_close_tab")

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
            description=(
                "点击 CSS selector 对应的元素（支持 Shadow DOM；iframe 内元素传 frame_selector），"
                "返回操作后的页面文本。"
            ),
            args_schema=create_model(
                "browser_click_args",
                selector=(str, Field(..., description="CSS selector")),
                frame_selector=(str, Field(default="", description="可选 iframe 的 CSS selector")),
            ),
        ),
        StructuredTool.from_function(
            coroutine=_click_xy,
            name="browser_click_xy",
            description="按视口坐标点击，用于坐标式操作；可先调用 browser_inspect 获取元素中心点。",
            args_schema=create_model(
                "browser_click_xy_args",
                x=(float, Field(..., description="视口 x 坐标")),
                y=(float, Field(..., description="视口 y 坐标")),
            ),
        ),
        StructuredTool.from_function(
            coroutine=_scroll,
            name="browser_scroll",
            description="滚动页面（正数向下、负数向上），返回操作后的页面文本。",
            args_schema=create_model(
                "browser_scroll_args", delta_y=(int, Field(..., description="纵向滚动像素"))
            ),
        ),
        StructuredTool.from_function(
            coroutine=_fill,
            name="browser_fill",
            description="在输入框中填写文本（支持 Shadow DOM 与 iframe），返回操作后的页面文本。",
            args_schema=create_model(
                "browser_fill_args",
                selector=(str, Field(..., description="CSS selector")),
                text=(str, Field(..., description="要填写的文本")),
                frame_selector=(str, Field(default="", description="可选 iframe 的 CSS selector")),
            ),
        ),
        StructuredTool.from_function(
            coroutine=_press,
            name="browser_press",
            description="按下键盘按键（如 Enter / Tab）；传 selector 时在元素上按键，支持 iframe。",
            args_schema=create_model(
                "browser_press_args",
                key=(str, Field(..., description="按键名")),
                selector=(str, Field(default="", description="可选目标元素 CSS selector")),
                frame_selector=(str, Field(default="", description="可选 iframe 的 CSS selector")),
            ),
        ),
        StructuredTool.from_function(
            coroutine=_text,
            name="browser_text",
            description="读取页面正文或指定 selector 的文本；支持 iframe。",
            args_schema=create_model(
                "browser_text_args",
                selector=(str, Field(default="", description="可选 CSS selector")),
                frame_selector=(str, Field(default="", description="可选 iframe 的 CSS selector")),
            ),
        ),
        StructuredTool.from_function(
            coroutine=_inspect,
            name="browser_inspect",
            description=(
                "返回带编号与中心坐标的可交互元素（链接/按钮/输入框等）并截图；"
                "适合配合 browser_click_xy 做坐标式操作。"
            ),
        ),
        StructuredTool.from_function(
            coroutine=_frames,
            name="browser_frames",
            description="列出页面所有 frame/iframe 的索引、名称、URL 与是否主文档。",
        ),
        StructuredTool.from_function(
            coroutine=_captcha,
            name="browser_captcha",
            description="检测页面是否出现 reCAPTCHA/hCaptcha/Turnstile 等验证；只提示人工处理，不绕过。",
        ),
        StructuredTool.from_function(
            coroutine=_screenshot,
            name="browser_screenshot",
            description="截取当前页面并返回截图文件路径。",
        ),
    ] + (
        [
            StructuredTool.from_function(
                coroutine=_look,
                name="browser_look",
                description=(
                    "截取当前页面并交给多模态模型理解，返回文字描述；"
                    "可用于读取截图中的文字、布局和可操作元素。"
                ),
                args_schema=create_model(
                    "browser_look_args",
                    question=(str, Field(default="", description="可选：想从截图中了解的问题")),
                ),
            )
        ]
        if getattr(settings, "browser_vision_enabled", False)
        else []
    ) + [
        StructuredTool.from_function(
            coroutine=_download,
            name="browser_download",
            description="点击 selector 触发下载并返回保存路径（适合 CSV 等附件）。",
            args_schema=create_model(
                "browser_download_args", selector=(str, Field(..., description="触发下载的 CSS selector"))
            ),
        ),
        StructuredTool.from_function(
            coroutine=_upload,
            name="browser_upload",
            description="向文件输入框上传 AP_BROWSER_UPLOAD_DIR 内的文件。",
            args_schema=create_model(
                "browser_upload_args",
                selector=(str, Field(..., description="file input 的 CSS selector")),
                file_path=(str, Field(..., description="上传目录内的文件路径")),
            ),
        ),
        StructuredTool.from_function(
            coroutine=_new_tab,
            name="browser_new_tab",
            description="新建标签页（可选打开 URL）并切换过去，返回页面文本。",
            args_schema=create_model(
                "browser_new_tab_args", url=(str, Field(default="", description="可选 URL"))
            ),
        ),
        StructuredTool.from_function(
            coroutine=_tabs,
            name="browser_tabs",
            description="列出当前浏览器标签页及 active 状态。",
        ),
        StructuredTool.from_function(
            coroutine=_switch_tab,
            name="browser_switch_tab",
            description="切换到指定标签页，返回页面文本。",
            args_schema=create_model(
                "browser_switch_tab_args", index=(int, Field(..., description="标签页索引"))
            ),
        ),
        StructuredTool.from_function(
            coroutine=_close_tab,
            name="browser_close_tab",
            description="关闭指定标签页（缺省关闭当前页），返回剩余活动页面文本。",
            args_schema=create_model(
                "browser_close_tab_args",
                index=(int | None, Field(default=None, description="可选标签页索引")),
            ),
        ),
    ]
