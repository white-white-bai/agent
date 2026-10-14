"""模型调用器工厂：按 provider 构建 LLMInvoker。"""
from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from agent_platform.core.config import Settings
from agent_platform.engine.context import LLMInvoker
from agent_platform.models.cloud_gateway import CloudGatewayChatModel


def build_llm_invoker(settings: Settings) -> LLMInvoker:
    async def invoke(
        *,
        provider: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int | None,
    ) -> str:
        if provider == "openai":
            from langchain_openai import ChatOpenAI

            llm = ChatOpenAI(
                model=model or "gpt-3.5-turbo",
                base_url=settings.openai_base_url or None,
                api_key=settings.openai_api_key or "sk-placeholder",
                temperature=temperature,
                max_tokens=max_tokens,
            )
        else:
            llm = CloudGatewayChatModel(
                model_name=model,
                base_url=settings.cloud_gateway_base_url,
                client_id=settings.cloud_gateway_client_id,
                client_secret=settings.cloud_gateway_client_secret,
                llm_app_id=settings.cloud_gateway_llm_app_id,
            )

        messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        result = await llm.ainvoke(messages)
        content = result.content
        return content if isinstance(content, str) else str(content)

    return invoke
