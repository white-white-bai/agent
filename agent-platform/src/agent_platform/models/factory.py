"""模型调用器工厂：按配置的 OpenAI 兼容模型条目构建 LLMInvoker。

模型清单来自 `AP_LLM_MODELS`：
    {"<key>": {"label": str, "base_url": str, "api_key": str, "model": str}}
任意 OpenAI 兼容端点（云端兼容网关 / DeepSeek / 私有部署等）都按此接入。
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agent_platform.core.config import Settings
from agent_platform.engine.context import ChatModelBuilder, LLMInvoker


def resolve_llm_model(settings: Settings, key: str) -> tuple[str, dict[str, Any]]:
    """按 key 取模型条目；key 为空时取清单第一个。返回 (实际 key, 条目)。"""
    models = settings.llm_models
    if not models:
        raise RuntimeError("未配置任何大模型：请设置 AP_LLM_MODELS（OpenAI 兼容 base_url + api_key + model）")
    if not key:
        key = next(iter(models))
    entry = models.get(key)
    if entry is None:
        raise RuntimeError(f"未配置的模型: {key}（可选：{', '.join(models)}）")
    return key, entry


def build_llm_invoker(settings: Settings) -> LLMInvoker:
    # 同一个 invoker 生命周期内复用底层 ChatOpenAI：autonomous 模式会在一个请求里多次调用。
    cached_models: dict[tuple[Any, ...], Any] = {}

    def _chat_model(key: str, entry: dict[str, Any], temperature: float, max_tokens: int | None) -> Any:
        cache_key = (key, float(temperature), max_tokens)
        cached = cached_models.get(cache_key)
        if cached is not None:
            return cached
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {
            "model": entry.get("model") or "",
            "base_url": entry.get("base_url") or None,
            "api_key": entry.get("api_key") or "sk-placeholder",
            "temperature": temperature,
            "max_tokens": max_tokens,
            "max_retries": settings.llm_max_retries,
        }
        if settings.llm_timeout_seconds > 0:
            kwargs["timeout"] = settings.llm_timeout_seconds
        model = ChatOpenAI(**kwargs)
        cached_models[cache_key] = model
        return model

    async def invoke(
        *,
        provider: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int | None,
        messages: list[Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        return_message: bool = False,
        tags: list[str] | None = None,
    ) -> Any:
        key, entry = resolve_llm_model(settings, provider)
        if not entry.get("model"):
            raise RuntimeError(f"模型条目缺少 model 字段: {key}")
        llm = _chat_model(key, entry, temperature, max_tokens)
        runnable = llm.bind_tools(tools, tool_choice=tool_choice) if tools else llm
        if messages is None:
            messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        config: dict[str, Any] | None = None
        if tags:
            config = {"tags": list(tags), "metadata": {tag: True for tag in tags}}
        result = await runnable.ainvoke(messages, config=config)
        if return_message:
            return result
        content = result.content
        return content if isinstance(content, str) else str(content)

    return invoke


def build_chat_model(
    settings: Settings, provider: str, *, temperature: float = 0.3, max_tokens: int | None = None
) -> Any:
    """构建支持工具调用/多轮消息/流式的 ChatModel（供自主 agent 循环用）。

    与 `build_llm_invoker`（system+user→str 的单轮协议）并存，互不影响。
    """
    from langchain_openai import ChatOpenAI

    key, entry = resolve_llm_model(settings, provider)
    model = entry.get("model") or ""
    if not model:
        raise RuntimeError(f"模型条目缺少 model 字段: {key}")
    return ChatOpenAI(
        model=model,
        base_url=entry.get("base_url") or None,
        api_key=entry.get("api_key") or "sk-placeholder",
        temperature=temperature,
        max_tokens=max_tokens,
        streaming=True,
    )


def build_chat_model_builder(settings: Settings) -> ChatModelBuilder:
    def build(*, provider: str, temperature: float, max_tokens: int | None) -> Any:
        return build_chat_model(settings, provider, temperature=temperature, max_tokens=max_tokens)

    return build
